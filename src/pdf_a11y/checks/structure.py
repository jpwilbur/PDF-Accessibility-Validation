"""Document-level structural checks (STRUCT-*).

These are the highest-leverage checks. STRUCT-001/005/008 are also the
critical-fail triggers that override the numeric score.
"""

from __future__ import annotations

from pdf_a11y.adapters import tesseract
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

# ---------------------------------------------------------------------------
# Reusable standard references
# ---------------------------------------------------------------------------

PDFUA_TAGGED = StandardRef(
    standard=Standard.PDF_UA_1,
    clause="7.1",
    title="Tagged PDF requirement",
    url="https://www.iso.org/standard/64599.html",
)
WCAG_INFO_REL = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.3.1",
    title="Info and Relationships",
    url="https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
)
WCAG_NAME_ROLE_VALUE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="4.1.2",
    title="Name, Role, Value",
    url="https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html",
)
WCAG_TITLE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="2.4.2",
    title="Page Titled",
    url="https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html",
)
WCAG_LANGUAGE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="3.1.1",
    title="Language of Page",
    url="https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html",
)
WCAG_NON_TEXT = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.1.1",
    title="Non-text Content",
    url="https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html",
)
SECTION_508 = StandardRef(
    standard=Standard.SECTION_508,
    clause="E205.4",
    title="Accessibility Standard for Electronic Content",
    url="https://www.access-board.gov/ict/#E205-electronic-content",
)
HHS_TAGGED = StandardRef(
    standard=Standard.HHS,
    clause="Tags",
    title="HHS PDF Accessibility Checklist — Tags required",
    url="https://www.hhs.gov/web/section-508/making-files-accessible/index.html",
)
MATTERHORN_01 = StandardRef(
    standard=Standard.MATTERHORN,
    clause="01",
    title="Real content tagged correctly",
)
MATTERHORN_06 = StandardRef(
    standard=Standard.MATTERHORN,
    clause="06",
    title="Metadata",
)
MATTERHORN_11 = StandardRef(
    standard=Standard.MATTERHORN,
    clause="11",
    title="Declared natural language",
)
MATTERHORN_07 = StandardRef(
    standard=Standard.MATTERHORN,
    clause="07",
    title="Document settings — accessible",
)


# ---------------------------------------------------------------------------
# STRUCT-001 — Tagged PDF
# ---------------------------------------------------------------------------


def _verapdf_will_run(ctx: PdfContext) -> bool:
    """True when veraPDF will produce its own findings for this PDF.

    When True, certain STRUCT-* checks defer to veraPDF's finer-grained rules
    (PDFUA-6-2, 6-3, 6-4, 11-1, 5-1) to avoid double-counting the same root
    cause. We intentionally fall back to STRUCT-* when veraPDF is unavailable
    so the critical-fail logic (tagged?, encrypted?) still works.
    """
    result = ctx.verapdf
    return bool(result.available and result.error is None)


@register
class TaggedPdfCheck(Check):
    id = "STRUCT-001"
    name = "Document is tagged"
    description = (
        "An accessible PDF must have a logical structure tree (StructTreeRoot) "
        "and MarkInfo /Marked = true. Without tags, assistive technology cannot "
        "convey meaning, reading order, or relationships."
    )
    severity = Severity.CRITICAL
    category = Category.STRUCTURE
    standards = [PDFUA_TAGGED, WCAG_INFO_REL, SECTION_508, MATTERHORN_01, HHS_TAGGED]
    remediation = (
        "Re-export the document from its source application with tagging enabled "
        "(Word: 'Save as PDF' with 'Document structure tags for accessibility' on; "
        "InDesign: export as 'Tagged PDF'; Acrobat Pro: Tools → Accessibility → "
        "Autotag Document, then manually verify and correct the tag tree)."
    )

    # STRUCT-001 always runs: it's a critical-fail trigger, and even when
    # veraPDF runs, having a redundant Critical finding for an untagged doc
    # costs nothing since the doc is already graded F by override.

    def run(self, ctx: PdfContext) -> list[Finding]:
        if ctx.has_tagged_structure:
            return []
        cat = ctx.catalog
        struct_root = bool(cat and "/StructTreeRoot" in cat)
        marked = False
        if cat is not None:
            mark_info = cat.get("/MarkInfo")
            try:
                marked = bool(mark_info and bool(mark_info.get("/Marked")))
            except Exception:
                marked = False
        return [
            self.finding(
                "PDF is not tagged: missing logical structure tree or /MarkInfo "
                "/Marked entry. Assistive technology cannot interpret this document.",
                evidence={"struct_tree_root_present": struct_root, "marked": marked},
            )
        ]


# ---------------------------------------------------------------------------
# STRUCT-002 — Title set + DisplayDocTitle
# ---------------------------------------------------------------------------


@register
class TitleCheck(Check):
    id = "STRUCT-002"
    name = "Document title set and shown"
    description = (
        "The document must declare a meaningful title in the Info dictionary "
        "(or XMP) and set ViewerPreferences /DisplayDocTitle = true so screen "
        "readers and the window title bar use the title rather than the filename."
    )
    severity = Severity.MAJOR
    category = Category.STRUCTURE
    standards = [WCAG_TITLE, MATTERHORN_06]
    remediation = (
        "Set the document title in File → Properties → Description (Acrobat) or "
        "via the source application. Then set 'Initial View → Show: Document Title' "
        "in File → Properties → Initial View, which writes "
        "/ViewerPreferences << /DisplayDocTitle true >>."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        # PDFUA-6-4 covers DisplayDocTitle when veraPDF runs.
        return not _verapdf_will_run(ctx)

    def run(self, ctx: PdfContext) -> list[Finding]:
        findings: list[Finding] = []
        title = (ctx.title or "").strip()
        if not title:
            findings.append(self.finding("Document /Info /Title is missing or empty."))
        elif title.lower().endswith(".pdf") or len(title) < 3:
            findings.append(
                self.finding(
                    f"Document title looks like a filename or placeholder: {title!r}.",
                    severity=Severity.MINOR,
                    remediation=(
                        "Replace the title with a meaningful description of the document's content."
                    ),
                )
            )
        if not ctx.display_doc_title:
            findings.append(
                self.finding(
                    "ViewerPreferences /DisplayDocTitle is not true; viewers will "
                    "show the filename instead of the document title.",
                    severity=Severity.MAJOR,
                )
            )
        return findings


# ---------------------------------------------------------------------------
# STRUCT-003 — Document language
# ---------------------------------------------------------------------------


@register
class LanguageCheck(Check):
    id = "STRUCT-003"
    name = "Document language declared"
    description = (
        "The catalog must declare the document's primary natural language via /Lang. "
        "Without it, screen readers cannot select the correct speech synthesizer "
        "or pronunciation rules."
    )
    severity = Severity.MAJOR
    category = Category.STRUCTURE
    standards = [WCAG_LANGUAGE, MATTERHORN_11]
    remediation = (
        "In Acrobat Pro: File → Properties → Advanced → Language. Set the BCP-47 "
        "language tag (e.g., 'en-US')."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        # PDFUA-11-1 covers /Lang when veraPDF runs.
        return not _verapdf_will_run(ctx)

    def run(self, ctx: PdfContext) -> list[Finding]:
        lang = (ctx.language or "").strip()
        if not lang:
            return [self.finding("Document /Lang is not set in the catalog.")]
        if len(lang) < 2:
            return [
                self.finding(
                    f"Document /Lang value is implausibly short: {lang!r}.",
                    severity=Severity.MINOR,
                )
            ]
        return []


# ---------------------------------------------------------------------------
# STRUCT-005 — Encryption that blocks assistive technology
# ---------------------------------------------------------------------------


@register
class EncryptionAccessibilityCheck(Check):
    id = "STRUCT-005"
    name = "Encryption does not block assistive technology"
    description = (
        "If the PDF is encrypted, the permission flags must allow content "
        "extraction for accessibility (bit 10 in the /P value). Otherwise screen "
        "readers cannot read the document at all."
    )
    severity = Severity.CRITICAL
    category = Category.STRUCTURE
    standards = [PDFUA_TAGGED, WCAG_NAME_ROLE_VALUE, MATTERHORN_07]
    remediation = (
        "Open File → Properties → Security in Acrobat Pro. Under 'Permissions', "
        "ensure 'Enable text access for screen reader devices for the visually "
        "impaired' is allowed. Re-save."
    )

    def run(self, ctx: PdfContext) -> list[Finding]:
        if ctx.pike is None or not ctx.is_encrypted:
            return []
        # pikepdf exposes permissions as an Allow object on .allow
        try:
            allow = ctx.pike.allow
            blocks_at = not bool(getattr(allow, "accessibility", True))
        except Exception:
            # If we can't introspect, conservatively flag.
            blocks_at = True
        if blocks_at:
            return [
                self.finding(
                    "PDF is encrypted with permissions that disable accessibility "
                    "content extraction.",
                    evidence={"encrypted": True, "blocks_at": True},
                )
            ]
        return []


# ---------------------------------------------------------------------------
# STRUCT-006 — PDF/UA conformance claim in XMP
# ---------------------------------------------------------------------------


@register
class PdfUaIdentifierCheck(Check):
    id = "STRUCT-006"
    name = "PDF/UA conformance identifier present"
    description = (
        "Conformant PDF/UA-1 documents declare 'pdfuaid:part = 1' in XMP "
        "metadata. Absence is not itself a barrier to use, but signals the "
        "document was not produced with PDF/UA in mind."
    )
    severity = Severity.MINOR
    category = Category.STRUCTURE
    standards = [
        StandardRef(standard=Standard.PDF_UA_1, clause="5", title="Identification"),
        MATTERHORN_06,
    ]
    remediation = (
        "After full PDF/UA remediation, add the PDF/UA identifier via Acrobat Pro "
        "Preflight ('Add tags to use PDF/UA conformance') or your remediation tool."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        # PDFUA-5-1 covers this when veraPDF runs; otherwise fall back to our check.
        # In either case, only meaningful when the document is at least tagged.
        if _verapdf_will_run(ctx):
            return False
        return bool(ctx.has_tagged_structure)

    def run(self, ctx: PdfContext) -> list[Finding]:
        if ctx.claims_pdf_ua:
            return []
        return [
            self.finding(
                "Document is tagged but does not claim PDF/UA-1 conformance in XMP "
                "metadata (pdfuaid:part).",
            )
        ]


# ---------------------------------------------------------------------------
# STRUCT-008 — Scan-only PDF (no real text layer)
# ---------------------------------------------------------------------------


@register
class ScanOnlyCheck(Check):
    id = "STRUCT-008"
    name = "Document has a real text layer"
    description = (
        "If pages are images of text with no underlying text layer, the document "
        "is unreadable by screen readers. Detected by sampling pages: an image-"
        "heavy page with effectively zero extractable text and Tesseract OCR "
        "finding substantial text indicates a scan-only PDF."
    )
    severity = Severity.CRITICAL
    category = Category.STRUCTURE
    detection = DetectionMethod.HEURISTIC
    standards = [WCAG_NON_TEXT, WCAG_INFO_REL, SECTION_508]
    remediation = (
        "Run OCR on the document (Acrobat Pro: Tools → Scan & OCR → Recognize Text → "
        "In This File) and then perform full accessibility tagging. OCR alone does "
        "NOT make a document accessible — it must also be tagged."
    )

    # Sampling parameters
    SAMPLE_PAGES = 3
    SCAN_OCR_THRESHOLD_CHARS = 80
    """Min OCR chars on an empty-text-layer page to call it a scan."""

    def run(self, ctx: PdfContext) -> list[Finding]:
        if ctx.page_count == 0:
            return []

        # Step 1: cheap signal — does *any* page have meaningful extractable text?
        sample_indices = self._sample_indices(ctx.page_count, self.SAMPLE_PAGES)
        text_lengths: list[int] = []
        for i in sample_indices:
            text = ctx.page_text(i).strip()
            text_lengths.append(len(text))
        max_text = max(text_lengths) if text_lengths else 0

        if max_text >= 50:
            return []  # text layer is clearly present somewhere

        # Step 2: confirm with OCR — if Tesseract finds text where the layer is
        # empty, this is a scan-only document.
        if not tesseract.is_available():
            return [
                self.finding(
                    "Sampled pages have no extractable text. OCR confirmation is "
                    "unavailable (tesseract not installed), so this could not be "
                    "verified automatically.",
                    severity=Severity.MAJOR,
                    requires_manual_verification=True,
                    remediation=(
                        "Install Tesseract or manually open the document and verify "
                        "whether the pages are images (scan) or actual text."
                    ),
                    evidence={"sampled_text_lengths": text_lengths},
                )
            ]

        ocr_chars = 0
        ocr_sample_pages: list[int] = []
        for i in sample_indices:
            if ctx.page_text(i).strip():
                continue
            png = self._render_page_png(ctx, i)
            if not png:
                continue
            ocr = tesseract.ocr_text(png).strip()
            ocr_chars = max(ocr_chars, len(ocr))
            ocr_sample_pages.append(i + 1)
            if ocr_chars >= self.SCAN_OCR_THRESHOLD_CHARS:
                break

        if ocr_chars >= self.SCAN_OCR_THRESHOLD_CHARS:
            return [
                self.finding(
                    "Document appears to be a scan with no text layer: pages contain "
                    "no extractable text but OCR finds substantial text in the page "
                    "images.",
                    evidence={
                        "ocr_chars_max": ocr_chars,
                        "sampled_pages_1based": ocr_sample_pages,
                    },
                )
            ]
        # OCR also found nothing meaningful — likely a blank or near-blank doc, not
        # a scan. Don't flag.
        return []

    @staticmethod
    def _sample_indices(page_count: int, n: int) -> list[int]:
        if page_count <= n:
            return list(range(page_count))
        step = max(1, page_count // n)
        return [min(page_count - 1, i * step) for i in range(n)]

    @staticmethod
    def _render_page_png(ctx: PdfContext, page_index: int) -> bytes | None:
        try:
            import fitz  # noqa: F401  PyMuPDF
        except Exception:
            return None
        try:
            pix = ctx.fitz_doc.load_page(page_index).get_pixmap(dpi=150)
            return bytes(pix.tobytes("png"))
        except Exception:
            return None
