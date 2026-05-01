"""Color-contrast helpers for VIS-001.

WCAG 2.1 §1.4.3 (Contrast Minimum, AA):
    - 4.5:1 for normal text
    - 3.0:1 for large text (>= 18pt, or >= 14pt bold)

This is a heuristic: we read the text foreground color from PyMuPDF's
content-stream extraction, render the page, and sample background pixels
in a margin around each text bbox. False positives happen when the
"background" we sample isn't actually behind the text (e.g., text overlaid
on an image), which we partially detect via a uniformity check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # numpy.typing.NDArray needs only types at type-check time
    from numpy.typing import NDArray

# WCAG 2.1 §1.4.3 thresholds.
NORMAL_THRESHOLD = 4.5
LARGE_THRESHOLD = 3.0

# Large-text classification (per WCAG): >=18pt regular, or >=14pt bold.
LARGE_TEXT_PT = 18.0
LARGE_BOLD_PT = 14.0

# Below this size, glyphs are usually invisible/decorative — skip.
MIN_FONT_PT = 6.0

# Background sampling parameters.
BG_MARGIN_PX = 4
BG_UNIFORMITY_RGB_DELTA = 30.0
"""If background medians on different sides of the bbox vary by more than this
RGB-norm distance, we treat the background as non-uniform (e.g. text over a
photograph) and decline to compute a contrast ratio."""

# Anti-flicker margin: only flag findings whose ratio is at least this much
# below threshold; near-misses are flagged as manual_verify.
NEAR_MISS_FRACTION = 0.9


def luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance for an sRGB triplet (0-255 each)."""

    def chan(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    l1 = luminance(fg)
    l2 = luminance(bg)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def is_large_text(font_pt: float, *, bold: bool) -> bool:
    return font_pt >= LARGE_TEXT_PT or (bold and font_pt >= LARGE_BOLD_PT)


def threshold_for(font_pt: float, *, bold: bool) -> float:
    return LARGE_THRESHOLD if is_large_text(font_pt, bold=bold) else NORMAL_THRESHOLD


def unpack_color_int(color_int: int) -> tuple[int, int, int]:
    """PyMuPDF span['color'] is packed sRGB as 0xRRGGBB."""
    return ((color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF)


def sample_background(
    img: NDArray[np.uint8],
    bbox_px: tuple[int, int, int, int],
    *,
    margin: int = BG_MARGIN_PX,
) -> tuple[tuple[int, int, int] | None, bool]:
    """Sample background colour around a text bbox.

    Returns (rgb_tuple, uniform). `rgb_tuple` is None if there's no usable
    background space around the bbox (e.g. text touches the page edge).
    `uniform` is False if the four sampled strips disagree by more than
    BG_UNIFORMITY_RGB_DELTA — in that case the caller should not trust the
    estimate (text is likely overlaid on a non-uniform background like an
    image).
    """
    h, w = img.shape[:2]
    x0, y0, x1, y1 = bbox_px
    x0 = max(0, min(w, x0))
    x1 = max(0, min(w, x1))
    y0 = max(0, min(h, y0))
    y1 = max(0, min(h, y1))
    if x1 <= x0 or y1 <= y0:
        return None, False

    strips: list[NDArray[np.uint8]] = []
    if y0 - margin >= 0:
        strips.append(img[max(0, y0 - margin) : y0, x0:x1])
    if y1 + margin <= h:
        strips.append(img[y1 : min(h, y1 + margin), x0:x1])
    if x0 - margin >= 0:
        strips.append(img[y0:y1, max(0, x0 - margin) : x0])
    if x1 + margin <= w:
        strips.append(img[y0:y1, x1 : min(w, x1 + margin)])

    medians: list[NDArray[np.float64]] = []
    for s in strips:
        if s.size == 0:
            continue
        flat = s.reshape(-1, 3) if s.ndim == 3 else s.reshape(-1, 1)
        if flat.shape[1] == 1:
            # Grayscale → broadcast to RGB.
            v = float(np.median(flat))
            medians.append(np.array([v, v, v], dtype=np.float64))
        else:
            medians.append(np.median(flat, axis=0).astype(np.float64))

    if not medians:
        return None, False

    stack = np.stack(medians)
    overall = np.median(stack, axis=0)
    # Per-strip distance from overall median.
    deltas = np.linalg.norm(stack - overall, axis=1)
    uniform = bool(np.max(deltas) <= BG_UNIFORMITY_RGB_DELTA)
    rgb = (int(overall[0]), int(overall[1]), int(overall[2]))
    return rgb, uniform


__all__ = [
    "BG_MARGIN_PX",
    "LARGE_BOLD_PT",
    "LARGE_TEXT_PT",
    "LARGE_THRESHOLD",
    "MIN_FONT_PT",
    "NEAR_MISS_FRACTION",
    "NORMAL_THRESHOLD",
    "contrast_ratio",
    "is_large_text",
    "luminance",
    "sample_background",
    "threshold_for",
    "unpack_color_int",
]
