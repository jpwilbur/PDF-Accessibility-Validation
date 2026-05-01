"""Functional tests for STRUCT-* checks against real fixture PDFs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pdf_a11y.checks.structure import (
    EncryptionAccessibilityCheck,
    LanguageCheck,
    PdfUaIdentifierCheck,
    ScanOnlyCheck,
    TaggedPdfCheck,
    TitleCheck,
)
from pdf_a11y.context import PdfContext


def _ctx(path: Path) -> PdfContext:
    return PdfContext(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source=str(path),
    )


# ---------- STRUCT-001 (tagged) ----------


def test_struct001_passes_on_known_good(known_good_pdf: Path) -> None:
    with _ctx(known_good_pdf) as ctx:
        findings = TaggedPdfCheck().run(ctx)
    assert findings == []


def test_struct001_passes_on_synthetic_scan_pdf_until_we_strip_tags(
    scan_only_pdf: Path,
) -> None:
    """Synthetic scan PDF written by PyMuPDF has no /MarkInfo, so STRUCT-001 fires."""
    with _ctx(scan_only_pdf) as ctx:
        findings = TaggedPdfCheck().run(ctx)
    assert len(findings) == 1
    assert findings[0].severity.value == "Critical"


# ---------- STRUCT-002 (title + DisplayDocTitle) ----------


def test_struct002_flags_missing_title_and_display_doctitle(
    scan_only_pdf: Path,
) -> None:
    with _ctx(scan_only_pdf) as ctx:
        findings = TitleCheck().run(ctx)
    # Synthetic PDF has neither title nor DisplayDocTitle.
    messages = [f.message for f in findings]
    assert any("Title" in m for m in messages)
    assert any("DisplayDocTitle" in m for m in messages)


# ---------- STRUCT-003 (language) ----------


def test_struct003_flags_missing_language(scan_only_pdf: Path) -> None:
    with _ctx(scan_only_pdf) as ctx:
        findings = LanguageCheck().run(ctx)
    assert len(findings) == 1
    assert "/Lang" in findings[0].message


def test_struct003_passes_when_language_present(known_good_pdf: Path) -> None:
    with _ctx(known_good_pdf) as ctx:
        findings = LanguageCheck().run(ctx)
    assert findings == []


# ---------- STRUCT-005 (encryption blocking AT) ----------


def test_struct005_passes_when_not_encrypted(known_good_pdf: Path) -> None:
    with _ctx(known_good_pdf) as ctx:
        findings = EncryptionAccessibilityCheck().run(ctx)
    assert findings == []


# ---------- STRUCT-006 (PDF/UA claim — only applies to tagged docs) ----------


def test_struct006_inapplicable_for_untagged(scan_only_pdf: Path) -> None:
    check = PdfUaIdentifierCheck()
    with _ctx(scan_only_pdf) as ctx:
        assert check.applies_to(ctx) is False


def test_struct006_inapplicable_when_verapdf_runs(known_good_pdf: Path, has_verapdf: bool) -> None:
    """When veraPDF is available, STRUCT-006 defers to PDFUA-5-1 to avoid
    double-counting. When it's not, STRUCT-006 stays applicable."""
    check = PdfUaIdentifierCheck()
    with _ctx(known_good_pdf) as ctx:
        applicable = check.applies_to(ctx)
    if has_verapdf:
        assert applicable is False
    else:
        assert applicable is True


# ---------- STRUCT-008 (scan-only) ----------


def test_struct008_passes_on_text_pdf(known_good_pdf: Path) -> None:
    with _ctx(known_good_pdf) as ctx:
        findings = ScanOnlyCheck().run(ctx)
    assert findings == []


@pytest.mark.needs_tesseract
def test_struct008_critical_fails_synthetic_scan(scan_only_pdf: Path, has_tesseract: bool) -> None:
    if not has_tesseract:
        pytest.skip("tesseract not installed")
    with _ctx(scan_only_pdf) as ctx:
        findings = ScanOnlyCheck().run(ctx)
    assert len(findings) == 1
    f = findings[0]
    assert f.severity.value == "Critical"
    assert "scan" in f.message.lower()
    assert f.evidence.get("ocr_chars_max", 0) > 0
