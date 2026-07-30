"""End-to-end smoke test: pipeline → reports for a small fixture set."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from pdf_a11y.config import Config
from pdf_a11y.models import (
    BatchReport,
    FileMetadata,
    PdfReport,
    Score,
    ToolVersions,
)
from pdf_a11y.pipeline import Pipeline
from pdf_a11y.report import (
    render_batch_html,
    render_pdf_html,
    write_findings_jsonl,
    write_summary_csv,
)


def test_pipeline_against_known_good_and_synthetic_scan(
    known_good_pdf: Path,
    scan_only_pdf: Path,
    tmp_path: Path,
) -> None:
    cfg = Config()
    cfg.paths.cache_dir = tmp_path / "cache"
    pipeline = Pipeline(cfg)
    sources = [str(known_good_pdf), str(scan_only_pdf)]
    batch = asyncio.run(pipeline.run(sources))

    assert len(batch.reports) == 2
    by_source = {r.metadata.source: r for r in batch.reports}
    good = by_source[str(known_good_pdf)]
    scan = by_source[str(scan_only_pdf)]

    assert good.score.grade in {"A", "B"}
    assert good.score.critical_fail is False

    # Synthetic scan: untagged + (if tesseract is available) scan-only.
    # Either way, STRUCT-001 fires → critical-fail F.
    assert scan.score.grade == "F"
    assert scan.score.critical_fail is True
    assert "STRUCT-001" in scan.score.critical_fail_reasons


def test_report_artifacts_render(known_good_pdf: Path, scan_only_pdf: Path, tmp_path: Path) -> None:
    cfg = Config()
    cfg.paths.cache_dir = tmp_path / "cache"
    pipeline = Pipeline(cfg)
    batch = asyncio.run(pipeline.run([str(known_good_pdf), str(scan_only_pdf)]))

    out = tmp_path / "out"
    out.mkdir()
    pdfs_dir = out / "pdfs"
    pdfs_dir.mkdir()
    links: dict[str, str] = {}
    for r in batch.reports:
        html = render_pdf_html(r)
        assert "<html" in html
        assert "</html>" in html
        p = pdfs_dir / f"{r.metadata.sha256[:12]}.html"
        p.write_text(html)
        links[r.metadata.sha256] = str(p.relative_to(out))

    summary = render_batch_html(batch, links)
    assert "Batch accessibility report" in summary
    (out / "summary.html").write_text(summary)

    write_findings_jsonl(batch, out / "findings.jsonl")
    write_summary_csv(batch, out / "summary.csv")
    assert (out / "findings.jsonl").exists()
    assert (out / "summary.csv").exists()

    # Sanity: at least one finding for the failing doc.
    lines = (out / "findings.jsonl").read_text().strip().splitlines()
    assert any(json.loads(line)["check_id"] == "STRUCT-001" for line in lines)


# ----- blocked-URL reporting --------------------------------------------
#
# A host that refuses us (mass.gov returns 403 to unrecognised UA tokens)
# produces rows with no accessibility verdict. They must not surface as
# "F / 0.0", or a reader counts blocked URLs as failing documents and a
# whole run looks worthless.


def _report(*, source: str, blocked: bool, error: str | None) -> PdfReport:
    now = datetime.now(UTC)
    return PdfReport(
        metadata=FileMetadata(
            source=source,
            local_path="",
            sha256="" if error else "a" * 64,
            byte_size=0,
            http_status=403 if blocked else (200 if not error else 404),
            blocked=blocked,
        ),
        score=Score(raw_penalty=0, max_penalty=0, score_pct=0.0, grade="F"),
        check_results=[],
        tool_versions=ToolVersions(pdf_a11y="test", python="3.12"),
        started_at=now,
        finished_at=now,
        duration_ms=0.0,
        error=error,
    )


def _batch(reports: list[PdfReport]) -> BatchReport:
    now = datetime.now(UTC)
    return BatchReport(
        started_at=now,
        finished_at=now,
        reports=reports,
        tool_versions=ToolVersions(pdf_a11y="test", python="3.12"),
    )


def _csv_rows(batch: BatchReport, tmp_path: Path) -> list[dict[str, str]]:
    path = tmp_path / "summary.csv"
    write_summary_csv(batch, path)
    with path.open() as fh:
        return list(csv.DictReader(fh))


def test_blocked_row_csv_has_no_grade_or_score(tmp_path: Path) -> None:
    batch = _batch(
        [_report(source="https://x.gov/a.pdf", blocked=True, error="HTTP 403 — refused")]
    )
    (row,) = _csv_rows(batch, tmp_path)
    assert row["Blocked By Site"] == "TRUE"
    assert row["PDF URL Status"] == "403"
    assert row["Accessibility Grade"] == ""
    assert row["Accessibility Score"] == ""
    assert row["# Critical Findings"] == ""
    assert row["Critical Fail"] == ""


def test_non_blocked_error_row_also_has_no_grade(tmp_path: Path) -> None:
    batch = _batch([_report(source="https://x.gov/gone.pdf", blocked=False, error="HTTP 404")])
    (row,) = _csv_rows(batch, tmp_path)
    assert row["Blocked By Site"] == "FALSE"
    assert row["Accessibility Grade"] == ""


def test_evaluated_row_keeps_its_grade(tmp_path: Path) -> None:
    batch = _batch([_report(source="https://x.gov/ok.pdf", blocked=False, error=None)])
    (row,) = _csv_rows(batch, tmp_path)
    assert row["Accessibility Grade"] == "F"
    assert row["Accessibility Score"] == "0.0"


def test_batch_counts_separate_blocked_from_other_errors() -> None:
    batch = _batch(
        [
            _report(source="a", blocked=True, error="HTTP 403 — refused"),
            _report(source="b", blocked=False, error="HTTP 404"),
            _report(source="c", blocked=False, error=None),
        ]
    )
    assert batch.total == 3
    assert batch.blocked == 1
    assert batch.errored == 2
    assert batch.evaluated == 1


def test_batch_html_explains_blocked_rows_are_not_failures() -> None:
    batch = _batch([_report(source="https://x.gov/a.pdf", blocked=True, error="HTTP 403")])
    html = render_batch_html(batch, {})
    assert "blocked by the site" in html
    assert "not</strong> an accessibility result" in html
    # The grade cell must not claim an F for a document we never retrieved.
    assert 'class="grade grade-f"' not in html
