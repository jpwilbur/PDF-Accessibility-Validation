"""Render-level tests for HTTP status display in HTML reports."""

from __future__ import annotations

from datetime import UTC, datetime

from pdf_a11y.models import (
    FileMetadata,
    PdfReport,
    Score,
    ToolVersions,
)
from pdf_a11y.report import render_pdf_html

_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)
_TOOLS = ToolVersions(pdf_a11y="9.9.9", python="3.12")


def _report(*, http_status: int | None, sha: str = "a" * 64) -> PdfReport:
    meta = FileMetadata(
        source="https://example.com/doc.pdf",
        local_path="/tmp/doc.pdf",
        sha256=sha,
        byte_size=1234,
        http_status=http_status,
        page_count=3,
        has_tagged_structure=True,
    )
    score = Score(raw_penalty=0, max_penalty=100, score_pct=95.0, grade="A")
    return PdfReport(
        metadata=meta,
        score=score,
        check_results=[],
        findings=[],
        tool_versions=_TOOLS,
        started_at=_NOW,
        finished_at=_NOW,
        duration_ms=1.0,
    )


def test_per_pdf_shows_numeric_http_status() -> None:
    html = render_pdf_html(_report(http_status=200))
    assert "HTTP status" in html
    assert ">200<" in html


def test_per_pdf_shows_dash_for_missing_status() -> None:
    html = render_pdf_html(_report(http_status=None))
    assert "HTTP status" in html
    # The status row renders an em-dash when there's no network status.
    assert "—" in html
