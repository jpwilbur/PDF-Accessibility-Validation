"""Pure-logic tests for SEM-* classifiers (don't require PDF parsing).

The integration with structure-tree walking is exercised end-to-end via the
fixture run.
"""

from __future__ import annotations

from pdf_a11y.checks.semantics import (
    AltTextQualityCheck,
    HasH1Check,
    HeadingSequenceCheck,
    LinkTextQualityCheck,
)

# ---------- SEM-002 alt-text classifier ----------


def test_alt_filename_flagged() -> None:
    assert AltTextQualityCheck._classify("photo_2024.jpg") == "looks like a filename"
    assert AltTextQualityCheck._classify("Slide 1.png") == "looks like a filename"


def test_alt_generic_placeholder_flagged() -> None:
    for word in ("image", "Picture", "decorative", "TBD", "todo"):
        assert AltTextQualityCheck._classify(word) is not None


def test_alt_too_terse_flagged() -> None:
    assert AltTextQualityCheck._classify("Fig") is not None
    assert AltTextQualityCheck._classify("a") is not None


def test_alt_too_long_flagged() -> None:
    long_alt = "x" * 260
    assert AltTextQualityCheck._classify(long_alt) == "is suspiciously long"


def test_alt_good_passes() -> None:
    good = "Bar chart showing 2024 quarterly revenue split by region."
    assert AltTextQualityCheck._classify(good) is None


# ---------- SEM-009 link-text classifier ----------


def test_link_click_here_flagged() -> None:
    assert LinkTextQualityCheck._classify("Click here") is not None
    assert LinkTextQualityCheck._classify("read more.") is not None
    assert LinkTextQualityCheck._classify("more info") is not None


def test_link_bare_long_url_flagged() -> None:
    url = "https://example.com/very/long/path/to/something/important.pdf"
    assert LinkTextQualityCheck._classify(url) is not None


def test_link_short_text_flagged() -> None:
    assert LinkTextQualityCheck._classify("X") is not None


def test_link_descriptive_passes() -> None:
    assert LinkTextQualityCheck._classify("Download the 2024 annual report (PDF)") is None


def test_link_short_url_in_context_passes() -> None:
    # 30-char threshold means short URLs are not flagged.
    assert LinkTextQualityCheck._classify("https://a.co/x") is None


# ---------- SEM-004 / SEM-005 sanity (instantiation only) ----------


def test_sem004_check_metadata() -> None:
    c = HeadingSequenceCheck()
    assert c.id == "SEM-004"
    assert c.severity.value == "Major"


def test_sem005_check_metadata() -> None:
    c = HasH1Check()
    assert c.id == "SEM-005"
    assert c.severity.value == "Minor"
