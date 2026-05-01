"""End-to-end smoke test: pipeline → reports for a small fixture set."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pdf_a11y.config import Config
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
