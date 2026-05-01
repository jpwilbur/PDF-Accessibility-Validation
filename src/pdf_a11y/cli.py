"""Typer CLI for pdf-a11y."""

from __future__ import annotations

import asyncio
import csv
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from pdf_a11y.config import Config
from pdf_a11y.models import BatchReport, report_paths_for
from pdf_a11y.pipeline import Pipeline
from pdf_a11y.report import (
    render_batch_html,
    render_pdf_html,
    write_findings_jsonl,
    write_summary_csv,
)

app = typer.Typer(
    name="pdf-a11y",
    help="Batch PDF accessibility evaluator (PDF/UA, Matterhorn, WCAG, Section 508).",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


@app.callback()
def _root(
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, markup=False)],
    )


@app.command()
def evaluate(
    inputs: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "One or more inputs: a URL, a local PDF path, a directory of PDFs, "
                "or a CSV/.txt file listing URLs (CSV must have a 'url' column; "
                "additional columns are passed through as metadata). Omit when "
                "using --op-report-id."
            )
        ),
    ] = None,
    op_report_id: Annotated[
        str | None,
        typer.Option(
            "--op-report-id",
            help=(
                "Pull URLs from an ObservePoint saved-report by ID. The saved "
                "report MUST expose a LINK_URL column."
            ),
        ),
    ] = None,
    op_api_key: Annotated[
        str | None,
        typer.Option(
            "--op-api-key",
            help=(
                "ObservePoint API key (required with --op-report-id). "
                "Defaults to env var OP_API_KEY if set."
            ),
            envvar="OP_API_KEY",
        ),
    ] = None,
    output_dir: Annotated[
        Path, typer.Option("--output-dir", "-o", help="Directory for HTML/JSON output.")
    ] = Path("./reports"),
    cache_dir: Annotated[
        Path, typer.Option("--cache-dir", help="PDF download cache directory.")
    ] = Path("./.cache/pdfs"),
    weights: Annotated[
        Path | None,
        typer.Option(
            "--weights",
            help="Path to weights.yaml (default: ./weights.yaml if present).",
        ),
    ] = None,
    concurrency: Annotated[
        int | None,
        typer.Option("--concurrency", "-c", min=1, max=20, help="Override download concurrency."),
    ] = None,
) -> None:
    """Download, evaluate, and report on a set of PDFs."""
    weights_path = weights or (Path("./weights.yaml") if Path("./weights.yaml").exists() else None)
    config = Config.load(weights_path)
    config.paths.output_dir = output_dir
    config.paths.cache_dir = cache_dir
    if concurrency is not None:
        config.network.concurrency = concurrency

    sources: list[str] = []
    user_metadata: list[dict[str, str]] = []

    if op_report_id:
        if not op_api_key:
            console.print(
                "[red]--op-api-key is required when --op-report-id is set "
                "(or set OP_API_KEY).[/red]"
            )
            raise typer.Exit(code=2)
        from pdf_a11y.observepoint import fetch_pdf_urls

        console.print(
            f"Fetching URLs from ObservePoint saved report "
            f"[bold]{op_report_id}[/bold]…"
        )
        op_result = fetch_pdf_urls(api_key=op_api_key, report_id=op_report_id)
        if op_result.error:
            console.print(f"[red]{op_result.error}[/red]")
            raise typer.Exit(code=1)
        console.print(
            f"  → '{op_result.report_name}' ({op_result.grid_entity_type}) — "
            f"{len(op_result.urls)} URLs"
        )
        for url in op_result.urls:
            sources.append(url)
            user_metadata.append(
                {
                    "op_report_id": op_report_id,
                    "op_report_name": op_result.report_name or "",
                }
            )

    if inputs:
        extra_sources, extra_meta = _expand_inputs(inputs)
        sources.extend(extra_sources)
        user_metadata.extend(extra_meta)

    if not sources:
        console.print(
            "[red]No PDFs to evaluate.[/red] Pass file/URL arguments or "
            "use --op-report-id."
        )
        raise typer.Exit(code=1)

    console.print(
        f"Evaluating [bold]{len(sources)}[/bold] PDF(s) "
        f"with concurrency={config.network.concurrency}…"
    )

    pipeline = Pipeline(config)
    batch = asyncio.run(pipeline.run(sources, user_metadata))

    _write_outputs(batch, output_dir)
    _print_summary(batch)
    console.print(f"\nReports written to [bold]{output_dir.resolve()}[/bold]")


@app.command("gen-docs")
def gen_docs(
    docs_dir: Annotated[
        Path,
        typer.Option(
            "--docs-dir",
            help="Where to write checks.md and standards-mapping.md.",
        ),
    ] = Path("./docs"),
) -> None:
    """Regenerate docs/checks.md and docs/standards-mapping.md from the registry."""
    from pdf_a11y.docs_gen import write_all

    catalog, mapping = write_all(docs_dir)
    console.print(f"Wrote [bold]{catalog}[/bold]")
    console.print(f"Wrote [bold]{mapping}[/bold]")


@app.command("list-checks")
def list_checks(
    category: Annotated[
        str | None,
        typer.Option(
            "--category",
            "-c",
            help=(
                "Filter by category (Structure, Semantics, Text, Visual, "
                "Navigation, Forms, Multimedia)."
            ),
        ),
    ] = None,
    id_prefix: Annotated[
        str | None,
        typer.Option("--prefix", help="Filter by check-id prefix (e.g. 'STRUCT', 'PDFUA', 'SEM')."),
    ] = None,
) -> None:
    """List registered checks. Filter with --category and/or --prefix."""
    from pdf_a11y.checks import all_checks

    cat_norm = category.lower() if category else None

    table = Table(title="Registered checks", show_lines=False)
    table.add_column("ID", style="bold cyan")
    table.add_column("Name")
    table.add_column("Severity")
    table.add_column("Category")
    table.add_column("Detection")
    table.add_column("Standards")

    shown = 0
    for check in all_checks():
        if cat_norm and check.category.value.lower() != cat_norm:
            continue
        if id_prefix and not check.id.startswith(id_prefix):
            continue
        std = ", ".join(f"{s.standard.value} §{s.clause}" for s in check.standards) or "—"
        table.add_row(
            check.id,
            check.name,
            check.severity.value,
            check.category.value,
            check.detection.value,
            std,
        )
        shown += 1
    console.print(table)
    console.print(f"[dim]{shown} check(s) shown.[/dim]")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _expand_inputs(raw_inputs: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    sources: list[str] = []
    metadata: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(src: str, meta: dict[str, str]) -> None:
        if src in seen:
            return
        seen.add(src)
        sources.append(src)
        metadata.append(meta)

    for raw in raw_inputs:
        if raw.startswith(("http://", "https://")):
            _add(raw, {})
            continue
        path = Path(raw)
        if path.is_dir():
            for p in sorted(path.rglob("*.pdf")):
                _add(str(p.resolve()), {})
            continue
        if path.is_file():
            if path.suffix.lower() == ".csv":
                with path.open(newline="", encoding="utf-8") as fh:
                    reader = csv.DictReader(fh)
                    if not reader.fieldnames or "url" not in reader.fieldnames:
                        console.print(f"[red]CSV {path} missing 'url' column[/red]", style="red")
                        sys.exit(1)
                    for row in reader:
                        url = (row.get("url") or "").strip()
                        if not url:
                            continue
                        meta = {k: v for k, v in row.items() if k != "url" and v is not None}
                        _add(url, meta)
                continue
            if path.suffix.lower() in {".txt", ".list"}:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        _add(line, {})
                continue
            # Assume single PDF file
            _add(str(path.resolve()), {})
            continue
        # Not URL, not a path that exists — pass through (likely a typo, will fail later visibly)
        _add(raw, {})

    return sources, metadata


def _write_outputs(batch: BatchReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir = output_dir / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    per_pdf_links: dict[str, str] = {}
    for report in batch.reports:
        if not report.metadata.sha256:
            continue
        html_path, json_path = report_paths_for(output_dir, report.metadata.sha256)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_pdf_html(report), encoding="utf-8")
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        per_pdf_links[report.metadata.sha256] = str(html_path.relative_to(output_dir))

    summary_html = output_dir / "summary.html"
    summary_html.write_text(render_batch_html(batch, per_pdf_links), encoding="utf-8")

    write_findings_jsonl(batch, output_dir / "findings.jsonl")
    write_summary_csv(batch, output_dir / "summary.csv")


def _print_summary(batch: BatchReport) -> None:
    table = Table(title="Results")
    table.add_column("Grade")
    table.add_column("Score")
    table.add_column("Document")
    table.add_column("Critical")
    table.add_column("Major")
    table.add_column("Minor")
    table.add_column("Top issues")

    for r in batch.reports:
        counts = {"Critical": 0, "Major": 0, "Minor": 0}
        for f in r.findings:
            if f.severity.value in counts:
                counts[f.severity.value] += 1
        top = ", ".join(f.check_id for f in r.top_findings) or "—"
        title = r.metadata.title or r.metadata.source
        if len(title) > 60:
            title = title[:57] + "…"
        table.add_row(
            r.score.grade,
            f"{r.score.score_pct:.1f}",
            title,
            str(counts["Critical"]),
            str(counts["Major"]),
            str(counts["Minor"]),
            top,
        )
    console.print(table)
