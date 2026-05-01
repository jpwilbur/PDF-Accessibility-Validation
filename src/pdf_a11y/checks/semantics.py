"""Semantic-quality checks (SEM-*).

These complement veraPDF: veraPDF verifies *structural* conformance (does a
<Figure> have /Alt at all?), but it can't judge *quality* (is the alt text
"image" or the filename?). Likewise for heading hierarchy and link text.

All SEM-* checks require a tagged PDF; they short-circuit out otherwise.
"""

from __future__ import annotations

import re

from pdf_a11y.checks._struct_walk import (
    NUMBERED_HEADING_TAGS,
    StructNode,
    find_by_tag,
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

# ---------------------------------------------------------------------------
# Reusable standards
# ---------------------------------------------------------------------------

_WCAG_NON_TEXT = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.1.1",
    title="Non-text Content",
    url="https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html",
)
_WCAG_INFO_REL = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.3.1",
    title="Info and Relationships",
    url="https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
)
_WCAG_HEADINGS_LABELS = StandardRef(
    standard=Standard.WCAG_21_AA,
    clause="2.4.6",
    title="Headings and Labels",
    url="https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html",
)
_WCAG_LINK_PURPOSE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="2.4.4",
    title="Link Purpose (In Context)",
    url="https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html",
)
_PDFUA_GRAPHICS = StandardRef(
    standard=Standard.PDF_UA_1,
    clause="7.3",
    title="Graphics",
    url="https://www.iso.org/standard/64599.html",
)
_PDFUA_HEADINGS = StandardRef(
    standard=Standard.PDF_UA_1,
    clause="7.4",
    title="Headings",
    url="https://www.iso.org/standard/64599.html",
)
_PDFUA_LINKS = StandardRef(
    standard=Standard.PDF_UA_1,
    clause="7.18.5",
    title="Links",
    url="https://www.iso.org/standard/64599.html",
)


# ---------------------------------------------------------------------------
# SEM-002 — Alt text quality
# ---------------------------------------------------------------------------


_LOW_QUALITY_ALT_PATTERNS = (
    "image",
    "picture",
    "photo",
    "graphic",
    "icon",
    "logo",
    "decorative",
    "untitled",
    "img",
    "fig",
    "figure",
    "tbd",
    "todo",
    "placeholder",
)
_FILENAME_RE = re.compile(r"^[\w\-. ]+\.(png|jpe?g|gif|tif|tiff|bmp|svg|pdf|webp)$", re.I)
_MAX_ALT_LEN = 250


@register
class AltTextQualityCheck(Check):
    id = "SEM-002"
    name = "Alt text is meaningful"
    description = (
        "Each <Figure> with alternate text should describe the image's meaning. "
        "Generic placeholders ('image', 'picture', filenames) defeat the purpose "
        "of /Alt; excessively long alt (>250 chars) belongs in surrounding body "
        "text or /ActualText, not /Alt."
    )
    severity = Severity.MAJOR
    category = Category.SEMANTICS
    detection = DetectionMethod.HEURISTIC
    standards = [_WCAG_NON_TEXT, _PDFUA_GRAPHICS]
    remediation = (
        "Replace generic alt text with a description of what the image conveys. "
        "If the image is purely decorative, mark it as /Artifact instead of <Figure>. "
        "If extensive description is needed, put it in body text and use a short /Alt."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        return bool(ctx.has_tagged_structure and ctx.struct_nodes)

    def run(self, ctx: PdfContext) -> list[Finding]:
        out: list[Finding] = []
        for node in find_by_tag(ctx.struct_nodes, {"Figure"}):
            alt = (node.alt or "").strip()
            actual = (node.actual_text or "").strip()
            if not alt and not actual:
                # veraPDF 7.3-2 already covers presence; we don't double up here.
                continue
            text = alt or actual
            issue = self._classify(text)
            if issue is None:
                continue
            out.append(
                self.finding(
                    f"<Figure> alt text {issue}: {text[:80]!r}",
                    severity=Severity.MAJOR if issue != "is suspiciously long" else Severity.MINOR,
                    location=f"object {node.obj_num}" if node.obj_num else None,
                    evidence={
                        "alt": alt,
                        "actual_text": actual,
                        "obj_num": node.obj_num,
                    },
                    remediation=self.remediation,
                )
            )
        return out

    @staticmethod
    def _classify(text: str) -> str | None:
        s = text.strip()
        if not s:
            return None
        low = s.lower()
        if _FILENAME_RE.match(s):
            return "looks like a filename"
        if low in _LOW_QUALITY_ALT_PATTERNS:
            return "is a generic placeholder"
        # Single-word or very short alt that's purely structural.
        if len(s) <= 4 and low.replace(".", "").isalpha():
            return "is too terse to be meaningful"
        if len(s) > _MAX_ALT_LEN:
            return "is suspiciously long"
        return None


# ---------------------------------------------------------------------------
# SEM-004 — Heading hierarchy is sequential
# ---------------------------------------------------------------------------


@register
class HeadingSequenceCheck(Check):
    id = "SEM-004"
    name = "Heading levels are sequential"
    description = (
        "Heading tags should not skip levels (e.g. H1 directly to H3). Skipped "
        "levels confuse screen-reader users navigating by heading shortcuts."
    )
    severity = Severity.MAJOR
    category = Category.SEMANTICS
    standards = [_WCAG_INFO_REL, _WCAG_HEADINGS_LABELS, _PDFUA_HEADINGS]
    remediation = (
        "Renumber headings so each new level is at most one greater than the "
        "previous heading's level. Use intermediate H2/H3/etc. as needed."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        return bool(ctx.has_tagged_structure and ctx.struct_nodes)

    def run(self, ctx: PdfContext) -> list[Finding]:
        levels: list[tuple[int, StructNode]] = []
        for n in ctx.struct_nodes:
            if n.tag in NUMBERED_HEADING_TAGS:
                try:
                    lvl = int(n.tag[1:])
                except ValueError:
                    continue
                levels.append((lvl, n))
        if not levels:
            return []

        out: list[Finding] = []
        prev_level = 0
        for lvl, node in levels:
            if prev_level == 0:
                # Document's first numbered heading should be H1; SEM-005 enforces that.
                pass
            elif lvl > prev_level + 1:
                out.append(
                    self.finding(
                        f"Heading level skipped: <H{prev_level}> followed directly by <H{lvl}>",
                        location=f"object {node.obj_num}" if node.obj_num else None,
                        evidence={
                            "previous_level": prev_level,
                            "this_level": lvl,
                            "title": node.title,
                        },
                    )
                )
            prev_level = lvl
        return out


# ---------------------------------------------------------------------------
# SEM-005 — At least one H1 if any headings
# ---------------------------------------------------------------------------


@register
class HasH1Check(Check):
    id = "SEM-005"
    name = "Document has an <H1> if it has any headings"
    description = (
        "Documents using numbered heading tags should start the hierarchy at H1. "
        "Missing H1 makes 'jump to top' navigation by heading less reliable."
    )
    severity = Severity.MINOR
    category = Category.SEMANTICS
    standards = [_WCAG_HEADINGS_LABELS, _PDFUA_HEADINGS]
    remediation = "Re-tag the document's main title or top-level section heading as <H1>."

    def applies_to(self, ctx: PdfContext) -> bool:
        if not (ctx.has_tagged_structure and ctx.struct_nodes):
            return False
        # Only meaningful if the doc uses numbered headings at all.
        return any(n.tag in NUMBERED_HEADING_TAGS for n in ctx.struct_nodes)

    def run(self, ctx: PdfContext) -> list[Finding]:
        levels = {n.tag for n in ctx.struct_nodes if n.tag in NUMBERED_HEADING_TAGS}
        if "H1" in levels:
            return []
        return [
            self.finding(
                f"Document has headings ({sorted(levels)}) but no <H1>.",
                evidence={"heading_levels_present": sorted(levels)},
            )
        ]


# ---------------------------------------------------------------------------
# SEM-009 — Link text is meaningful
# ---------------------------------------------------------------------------


_BAD_LINK_TEXTS = frozenset(
    {
        "click here",
        "here",
        "more",
        "read more",
        "learn more",
        "more info",
        "more information",
        "details",
        "this",
        "this link",
        "link",
        "click",
        "go",
    }
)
_BARE_URL_RE = re.compile(r"^(https?://|www\.)")


@register
class LinkTextQualityCheck(Check):
    id = "SEM-009"
    name = "Link text describes the destination"
    description = (
        "Each <Link> element should contain text that conveys the destination's "
        "purpose out of context. Phrases like 'click here', 'more', or a bare URL "
        "are useless to a screen-reader user navigating by links list."
    )
    severity = Severity.MAJOR
    category = Category.SEMANTICS
    detection = DetectionMethod.HEURISTIC
    standards = [_WCAG_LINK_PURPOSE, _PDFUA_LINKS]
    remediation = (
        "Rewrite the link text to describe where the link goes (e.g. 'View the "
        "annual report (PDF)' instead of 'click here'). Keep URLs in surrounding "
        "text only when they are short and self-describing."
    )

    def applies_to(self, ctx: PdfContext) -> bool:
        return bool(ctx.has_tagged_structure and ctx.struct_nodes)

    def run(self, ctx: PdfContext) -> list[Finding]:
        out: list[Finding] = []
        for link in find_by_tag(ctx.struct_nodes, {"Link"}):
            text = self._link_text(link)
            issue = self._classify(text)
            if issue is None:
                continue
            out.append(
                self.finding(
                    f"<Link> text {issue}: {text[:60]!r}",
                    location=f"object {link.obj_num}" if link.obj_num else None,
                    evidence={"link_text": text, "obj_num": link.obj_num},
                )
            )
        return out

    @staticmethod
    def _link_text(link: StructNode) -> str:
        # Prefer /ActualText, else /Alt, else fall through to /T (rare for Links).
        for v in (link.actual_text, link.alt, link.title):
            if v:
                return v.strip()
        return ""

    @staticmethod
    def _classify(text: str) -> str | None:
        s = text.strip()
        if not s:
            # Empty link text is a genuine accessibility failure but might be
            # the structural-tree representation of a link annotation that uses
            # the surrounding paragraph as its name. Conservative: skip.
            return None
        # Skip page-number patterns commonly used in tables of contents.
        # WCAG 2.4.4 allows context-dependent link text; TOC entries are the
        # canonical example. Plain digits or "page 54" / "p. 54" are expected.
        stripped = s.rstrip(".,)")
        if stripped.isdigit():
            return None
        low = s.lower().rstrip(".:!?")
        if re.match(r"^(p\.?|pg\.?|page)\s*\d+$", low):
            return None
        if low in _BAD_LINK_TEXTS:
            return "is a generic placeholder ('click here'-style)"
        if _BARE_URL_RE.match(s) and len(s) > 30:
            return "is a bare URL — describe the destination instead"
        if len(s) <= 2:
            return "is too short to convey purpose"
        return None
