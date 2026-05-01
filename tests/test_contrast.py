"""Pure-logic tests for contrast helpers + e2e against a synthetic fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from pdf_a11y.checks._contrast import (
    contrast_ratio,
    is_large_text,
    luminance,
    sample_background,
    threshold_for,
    unpack_color_int,
)
from pdf_a11y.checks.visual import ColorContrastCheck
from pdf_a11y.context import PdfContext

# ---------- Pure-logic ----------


def test_luminance_known_values() -> None:
    # WCAG-defined: black = 0, white = 1.0.
    assert luminance((0, 0, 0)) == 0.0
    assert abs(luminance((255, 255, 255)) - 1.0) < 1e-9


def test_contrast_ratio_black_on_white_is_max() -> None:
    assert abs(contrast_ratio((0, 0, 0), (255, 255, 255)) - 21.0) < 1e-3


def test_contrast_ratio_symmetric() -> None:
    a = contrast_ratio((50, 50, 50), (200, 200, 200))
    b = contrast_ratio((200, 200, 200), (50, 50, 50))
    assert abs(a - b) < 1e-9


def test_unpack_color_int_packs_rgb_msb_first() -> None:
    assert unpack_color_int(0xFF8800) == (0xFF, 0x88, 0x00)
    assert unpack_color_int(0x000000) == (0, 0, 0)


def test_is_large_text_thresholds() -> None:
    assert is_large_text(18.0, bold=False) is True
    assert is_large_text(14.0, bold=True) is True
    assert is_large_text(13.9, bold=True) is False
    assert is_large_text(17.0, bold=False) is False


def test_threshold_for_normal_vs_large() -> None:
    assert threshold_for(12.0, bold=False) == 4.5
    assert threshold_for(20.0, bold=False) == 3.0
    assert threshold_for(15.0, bold=True) == 3.0


def test_sample_background_uniform_white() -> None:
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    rgb, uniform = sample_background(img, (40, 40, 60, 60))
    assert rgb == (255, 255, 255)
    assert uniform is True


def test_sample_background_non_uniform_flagged() -> None:
    """Half-white, half-black background → not uniform."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, 50:, :] = 255
    # bbox in the middle so left strip = black, right strip = white.
    rgb, uniform = sample_background(img, (40, 40, 60, 60))
    assert uniform is False
    assert rgb is not None


def test_sample_background_returns_none_when_bbox_invalid() -> None:
    img = np.full((100, 100, 3), 255, dtype=np.uint8)
    rgb, uniform = sample_background(img, (50, 50, 50, 50))  # zero-area
    assert rgb is None
    assert uniform is False


# ---------- E2E against synthetic low-contrast fixture ----------


def _ctx(path: Path) -> PdfContext:
    return PdfContext(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source=str(path),
    )


def test_vis001_flags_low_contrast_pages_only(low_contrast_pdf: Path) -> None:
    check = ColorContrastCheck()
    with _ctx(low_contrast_pdf) as ctx:
        findings = check.run(ctx)
    # We expect findings on pages 2 and 3 (gray text), not on page 1 (black).
    pages_flagged = {f.page for f in findings}
    assert 1 not in pages_flagged
    assert 2 in pages_flagged
    # Either page 2 (normal) or page 3 (large) should be flagged at minimum.
    assert pages_flagged
    # Findings should report the offending colour pair.
    sample = findings[0]
    assert sample.evidence["fg_rgb"] != sample.evidence["bg_rgb"]
    assert sample.evidence["ratio"] < sample.evidence["threshold"]


def test_vis001_clean_doc_has_no_findings(known_good_pdf: Path) -> None:
    check = ColorContrastCheck()
    with _ctx(known_good_pdf) as ctx:
        findings = check.run(ctx)
    # A short well-formed UA fixture should not have low-contrast text.
    assert findings == []
