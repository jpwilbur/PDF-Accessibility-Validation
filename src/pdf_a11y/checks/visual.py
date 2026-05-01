"""Visual perceptual checks (VIS-*).

VIS-001 — Color contrast (WCAG AA, §1.4.3). Heuristic: read text foreground
color from the PyMuPDF content-stream extraction, render the page, sample
background pixels around each text bbox, compute contrast ratio. Skip spans
where the background is non-uniform (likely text over a photo) since we
can't reliably estimate background there.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from pdf_a11y.checks._contrast import (
    BG_MARGIN_PX,
    MIN_FONT_PT,
    NEAR_MISS_FRACTION,
    contrast_ratio,
    is_large_text,
    sample_background,
    threshold_for,
    unpack_color_int,
)
from pdf_a11y.checks.base import Check
from pdf_a11y.checks.registry import register
from pdf_a11y.context import PdfContext
from pdf_a11y.models import (
    Category,
    DetectionMethod,
    Finding,
    Severity,
    Standard,
    StandardRef,
)

logger = logging.getLogger(__name__)


_WCAG_CONTRAST_AA = StandardRef(
    standard=Standard.WCAG_21_AA,
    clause="1.4.3",
    title="Contrast (Minimum)",
    url="https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html",
)
_SECTION_508 = StandardRef(
    standard=Standard.SECTION_508,
    clause="E207.2 / WCAG 1.4.3",
    title="Section 508 — adopted WCAG 1.4.3",
    url="https://www.access-board.gov/ict/#E207-revised-508-standards",
)


@register
class ColorContrastCheck(Check):
    id = "VIS-001"
    name = "Text contrast meets WCAG AA"
    description = (
        "Heuristic check of text contrast against WCAG 2.1 §1.4.3 thresholds "
        "(4.5:1 for normal text, 3:1 for large text). For each text span, the "
        "foreground colour is read from the PDF content stream and the "
        "background is sampled from rendered pixels around the span's "
        "bounding box. Spans whose background is not uniform (e.g. text "
        "overlaid on photos) are skipped to avoid false positives."
    )
    severity = Severity.MAJOR
    category = Category.VISUAL
    detection = DetectionMethod.HEURISTIC
    standards = [_WCAG_CONTRAST_AA, _SECTION_508]
    remediation = (
        "Increase the contrast between the text colour and the colour "
        "behind it. Aim for a luminance ratio of at least 4.5:1 for body "
        "text and 3:1 for large/bold display text. Tools like the WebAIM "
        "Contrast Checker can verify candidate colour pairs."
    )

    DPI = 150
    MAX_PAGES = 50
    """Cap pages we render per doc — beyond this, contrast is overwhelmingly
    repetitive and the per-check finding cap (10) saturates anyway."""

    SAMPLE_PADDING_PT = 1.5
    """Fitz bbox edges sometimes clip glyph descenders; pad slightly to avoid
    the bbox cutting through anti-aliased text pixels when sampling."""

    def applies_to(self, ctx: PdfContext) -> bool:
        return ctx.page_count > 0

    def run(self, ctx: PdfContext) -> list[Finding]:
        try:
            import fitz  # noqa: F401 — ensure PyMuPDF is available
        except ImportError:
            return []

        findings: list[Finding] = []
        try:
            doc = ctx.fitz_doc
        except Exception as e:
            logger.debug("could not open fitz doc for contrast scan: %s", e)
            return []

        page_limit = min(ctx.page_count, self.MAX_PAGES)
        for page_idx in range(page_limit):
            try:
                self._scan_page(doc, page_idx, findings)
            except Exception as e:
                logger.debug("contrast scan failed on page %d: %s", page_idx, e)
        return findings

    def _scan_page(self, doc: Any, page_idx: int, findings: list[Finding]) -> None:
        page = doc.load_page(page_idx)
        zoom = self.DPI / 72.0
        pix = page.get_pixmap(dpi=self.DPI, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if pix.n == 4:
            img = img[:, :, :3]
        elif pix.n == 1:
            img = np.repeat(img[:, :, np.newaxis], 3, axis=2)

        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text, 1 = image
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    self._check_span(span, img, zoom, page_idx + 1, findings)

    def _check_span(
        self,
        span: dict[str, Any],
        img: np.ndarray,
        zoom: float,
        page_1based: int,
        findings: list[Finding],
    ) -> None:
        text = span.get("text", "").strip()
        if len(text) < 2:
            return
        size = float(span.get("size", 0))
        if size < MIN_FONT_PT:
            return

        flags = int(span.get("flags", 0))
        bold = bool(flags & 16)  # PyMuPDF flag bit 16 = bold
        fg = unpack_color_int(int(span.get("color", 0)))

        bbox_pdf = span["bbox"]
        x0, y0, x1, y1 = bbox_pdf
        # Slight inward inset to let the surrounding-margin sampler stay clear
        # of antialiased glyph edges.
        pad = self.SAMPLE_PADDING_PT
        bbox_px = (
            int((x0 - pad) * zoom),
            int((y0 - pad) * zoom),
            int((x1 + pad) * zoom),
            int((y1 + pad) * zoom),
        )

        bg, uniform = sample_background(img, bbox_px, margin=BG_MARGIN_PX)
        if bg is None:
            return
        if not uniform:
            # Don't trust a non-uniform background. Could be text on an image,
            # gradient header, etc. Skip rather than produce a misleading
            # finding; an OCR-driven manual review would be more accurate.
            return

        ratio = contrast_ratio(fg, bg)
        threshold = threshold_for(size, bold=bold)
        if ratio >= threshold:
            return

        # Build the finding.
        is_large = is_large_text(size, bold=bold)
        # Use Minor severity for large-text near-miss to avoid overwhelming
        # the score on documents with many display-text spans (titles, etc).
        sev = Severity.MAJOR if not is_large else Severity.MINOR
        near_miss = ratio >= threshold * NEAR_MISS_FRACTION
        findings.append(
            self.finding(
                f"Text contrast {ratio:.2f}:1 is below the {threshold}:1 threshold.",
                page=page_1based,
                location=f"text starting {text[:40]!r}",
                severity=sev,
                evidence={
                    "text_sample": text[:120],
                    "fg_rgb": list(fg),
                    "bg_rgb": list(bg),
                    "ratio": round(ratio, 2),
                    "threshold": threshold,
                    "font_size_pt": round(size, 1),
                    "is_large": is_large,
                    "is_bold": bold,
                },
                requires_manual_verification=near_miss,
            )
        )
