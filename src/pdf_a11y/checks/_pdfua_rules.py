"""Curated mapping of veraPDF PDF/UA-1 rule keys to our finding metadata.

Rule keys are `{clause}-{testNumber}` exactly as veraPDF emits them. This is
not exhaustive — veraPDF's UA-1 profile has ~100 rules. We map the most
frequently-hit and highest-impact ones explicitly so the report can give
high-quality remediation guidance, and route everything else through a
generic catch-all (`PDFUA-OTHER`).

Keys are taken from veraPDF's own corpus and rule definitions:
    https://github.com/veraPDF/veraPDF-validation-profiles
"""

from __future__ import annotations

from dataclasses import dataclass

from pdf_a11y.models import Category, Severity, Standard, StandardRef


@dataclass(frozen=True)
class RuleSpec:
    name: str
    severity: Severity
    category: Category
    standards: tuple[StandardRef, ...]
    remediation: str
    description: str = ""


# WCAG references used by multiple rules.
_WCAG_INFO_REL = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.3.1",
    title="Info and Relationships",
    url="https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html",
)
_WCAG_NON_TEXT = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="1.1.1",
    title="Non-text Content",
    url="https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html",
)
_WCAG_LANGUAGE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="3.1.1",
    title="Language of Page",
    url="https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html",
)
_WCAG_NAME_ROLE_VALUE = StandardRef(
    standard=Standard.WCAG_21_A,
    clause="4.1.2",
    title="Name, Role, Value",
    url="https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html",
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
_SECTION_508 = StandardRef(
    standard=Standard.SECTION_508,
    clause="E205.4",
    title="Accessibility Standard for Electronic Content",
    url="https://www.access-board.gov/ict/#E205-electronic-content",
)


def _ua(clause: str, title: str = "") -> StandardRef:
    return StandardRef(
        standard=Standard.PDF_UA_1,
        clause=clause,
        title=title or f"PDF/UA-1 §{clause}",
        url="https://www.iso.org/standard/64599.html",
    )


# --- Rule table ------------------------------------------------------------
# Ordering inside the table is loosely structural-then-content for readability.
RULES: dict[str, RuleSpec] = {
    # ---- Section 5: Identification ----
    "5-1": RuleSpec(
        name="PDF/UA identifier present in XMP",
        severity=Severity.MINOR,
        category=Category.STRUCTURE,
        standards=(_ua("5", "Identification"),),
        remediation=(
            "After full PDF/UA remediation, add the PDF/UA identifier "
            "(pdfuaid:part = 1) via Acrobat Pro Preflight or your remediation tool."
        ),
    ),
    # ---- Section 6: General requirements (file format) ----
    "6-1": RuleSpec(
        name="File version 1.7 or earlier (PDF/UA-1 only allows up to 1.7)",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(_ua("6", "Conforming Files"),),
        remediation=("Re-export the PDF as version 1.7 or earlier from your source application."),
    ),
    "6-2": RuleSpec(
        name="Document Catalog declares a /MarkInfo with /Marked = true",
        severity=Severity.CRITICAL,
        category=Category.STRUCTURE,
        standards=(_ua("6", "Conforming Files"), _WCAG_INFO_REL),
        remediation=(
            "Re-export with tagging enabled. The catalog must contain "
            "/MarkInfo << /Marked true >> indicating the file is fully tagged."
        ),
    ),
    "6-3": RuleSpec(
        name="Document Catalog has a /StructTreeRoot",
        severity=Severity.CRITICAL,
        category=Category.STRUCTURE,
        standards=(_ua("6", "Conforming Files"), _WCAG_INFO_REL),
        remediation=("Re-export with tagging enabled so a logical structure tree is produced."),
    ),
    "6-4": RuleSpec(
        name="Catalog /ViewerPreferences /DisplayDocTitle is true",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(
            _ua("6", "Conforming Files"),
            StandardRef(
                standard=Standard.WCAG_21_A,
                clause="2.4.2",
                title="Page Titled",
                url="https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html",
            ),
        ),
        remediation=(
            "In Acrobat Pro: File → Properties → Initial View → Show: Document Title. "
            "This sets /ViewerPreferences << /DisplayDocTitle true >>."
        ),
    ),
    # ---- Section 7.1: General content requirements ----
    "7.1-1": RuleSpec(
        name="Real content is tagged in the structure tree",
        severity=Severity.CRITICAL,
        category=Category.STRUCTURE,
        standards=(_ua("7.1"), _WCAG_INFO_REL, _SECTION_508),
        remediation=(
            "Verify in the Tag panel that every visible content stream is included "
            "in the structure tree under appropriate tags."
        ),
    ),
    "7.1-2": RuleSpec(
        name="Artifacts are not tagged as real content",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(_ua("7.1"), _WCAG_INFO_REL),
        remediation=(
            "Mark page numbers, headers/footers, and decorative graphics as /Artifact "
            "so screen readers do not announce them as part of the reading order."
        ),
    ),
    "7.1-3": RuleSpec(
        name="Content stream operators are inside marked-content sequences",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(_ua("7.1"),),
        remediation=(
            "Re-tag the document. All content must be inside /MCID-marked or "
            "/Artifact-marked content sequences."
        ),
    ),
    "7.1-4": RuleSpec(
        name="Suspects flag is false (if present)",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(_ua("7.1"),),
        remediation=(
            "Acrobat sets /Suspects = true when its tagging may be incorrect. "
            "Manually review and correct the tag tree, then clear the Suspects flag."
        ),
    ),
    "7.1-6": RuleSpec(
        name="Tags are nested correctly per the standard structure types",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.1"), _WCAG_INFO_REL),
        remediation=(
            "Use only standard structure types (Document, Sect, P, H1-H6, L, LI, "
            "Table, etc.) or correctly mapped role-mapped equivalents."
        ),
    ),
    "7.1-7": RuleSpec(
        name="Standard tags are not remapped",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.1"), _WCAG_INFO_REL),
        remediation=(
            "Don't remap standard structure tags (P, H1, Table, etc.) via "
            "/RoleMap. Custom tags must roleMap to a standard tag, but standard "
            "tags must keep their canonical meaning."
        ),
    ),
    # ---- Section 7.2: Text ----
    "7.2-1": RuleSpec(
        name="All text has a Unicode mapping (no PUA / replacement gibberish)",
        severity=Severity.MAJOR,
        category=Category.TEXT,
        standards=(_ua("7.2"), _WCAG_INFO_REL),
        remediation=(
            "Embed proper ToUnicode CMaps for all fonts, or supply /ActualText "
            "on the affected spans so screen readers and copy-paste produce real text."
        ),
    ),
    "7.2-2": RuleSpec(
        name="Stretchable characters use /ActualText",
        severity=Severity.MINOR,
        category=Category.TEXT,
        standards=(_ua("7.2"),),
        remediation=(
            "Add /ActualText to spans where glyphs are constructed from multiple "
            "character codes (e.g., stretched parentheses)."
        ),
    ),
    "7.2-3": RuleSpec(
        name="Table elements contain only TR / THead / TBody / TFoot / Caption children",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.2"), _WCAG_INFO_REL),
        remediation=(
            "Re-tag tables so <Table> only contains <TR>, <THead>, <TBody>, "
            "<TFoot>, or <Caption> children — not bare <P> or other paragraph tags."
        ),
    ),
    # ---- Section 7.3: Graphics ----
    "7.3-1": RuleSpec(
        name="Graphics that are real content are tagged with /Figure",
        severity=Severity.CRITICAL,
        category=Category.SEMANTICS,
        standards=(_ua("7.3"), _WCAG_NON_TEXT),
        remediation=(
            "Tag images conveying meaning as <Figure> in the structure tree. "
            "Decorative-only graphics must be marked as /Artifact instead."
        ),
    ),
    "7.3-2": RuleSpec(
        name="<Figure> elements have alternate text (/Alt) or /ActualText",
        severity=Severity.CRITICAL,
        category=Category.SEMANTICS,
        standards=(_ua("7.3"), _WCAG_NON_TEXT, _SECTION_508),
        remediation=(
            "Add /Alt (or /ActualText) to every <Figure> element. The alt text "
            "should describe the meaning of the graphic for someone who cannot see it."
        ),
    ),
    # ---- Section 7.4: Headings ----
    "7.4.2-1": RuleSpec(
        name="Heading levels are sequential (no jumps)",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.4.2"), _WCAG_INFO_REL, _WCAG_HEADINGS_LABELS),
        remediation=(
            "Adjust the tag tree so heading levels are not skipped (don't go from "
            "<H1> directly to <H3>)."
        ),
    ),
    "7.4.4-1": RuleSpec(
        name="Documents using strong structure use real heading tags (H1, H2, ...)",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.4.4"), _WCAG_INFO_REL),
        remediation=(
            "Use numbered heading tags (H1-H6) rather than the unnumbered <H> for "
            "documents with explicit heading hierarchy."
        ),
    ),
    "7.4.4-3": RuleSpec(
        name="Documents are either strongly or weakly structured (not both)",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.4.4"), _WCAG_INFO_REL),
        remediation=(
            "Pick one heading style: either always use numbered <H1>-<H6> "
            "(strong structure) or always use <H> with /Lvl (weak structure). "
            "Don't mix the two within the same document."
        ),
    ),
    # ---- Section 7.5: Tables ----
    "7.5-1": RuleSpec(
        name="Table header cells (<TH>) have a /Scope attribute or referenceable IDs",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.5"), _WCAG_INFO_REL),
        remediation=(
            "Either set /Scope (Row, Column, or Both) on every <TH>, or give each "
            "<TH> an /ID and reference it from the corresponding <TD> /Headers."
        ),
    ),
    "7.5-2": RuleSpec(
        name="Tables use the standard <Table>/<TR>/<TH>/<TD> structure",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.5"), _WCAG_INFO_REL),
        remediation=(
            "Replace pseudo-tables (lists, paragraphs, or bare layout) with proper "
            "<Table>/<TR>/<TH>/<TD> tags so assistive tech can navigate row/column."
        ),
    ),
    # ---- Section 7.6: Lists ----
    "7.6-1": RuleSpec(
        name="Lists use <L> with <LI>/<Lbl>/<LBody>",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.6"), _WCAG_INFO_REL),
        remediation=(
            "Re-tag bulleted and numbered lists as <L> containing <LI> elements, "
            "each with optional <Lbl> for the marker and <LBody> for the content."
        ),
    ),
    "7.6-2": RuleSpec(
        name="<L> /ListNumbering attribute matches the visual list style",
        severity=Severity.MINOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.6"),),
        remediation=(
            "Set /ListNumbering on each <L> to one of the standard values "
            "(Disc/Circle/Square/Decimal/UpperAlpha/LowerAlpha/UpperRoman/LowerRoman/None)."
        ),
    ),
    # ---- Section 7.18: Annotations / Forms / Links ----
    "7.18.1-1": RuleSpec(
        name="Annotations are referenced from the structure tree",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.18.1"), _WCAG_NAME_ROLE_VALUE),
        remediation=(
            "Every annotation (link, form field, comment) must have a corresponding "
            "structure-tree entry so it appears in the reading order."
        ),
    ),
    "7.18.1-2": RuleSpec(
        name="Annotations have /Contents or enclosing-structure /Alt as accessible name",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.18.1"), _WCAG_NAME_ROLE_VALUE),
        remediation=(
            "On each annotation (link, form field, comment), either set /Contents "
            "with descriptive text, or wrap the annotation in a structure element "
            "that has /Alt text."
        ),
    ),
    "7.18.2-1": RuleSpec(
        name="Annotations have a /Contents entry usable as an accessible name",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.18.2"), _WCAG_NAME_ROLE_VALUE),
        remediation=(
            "Set /Contents on each annotation to text that screen readers can use "
            "as a fallback accessible name."
        ),
    ),
    "7.18.3-1": RuleSpec(
        name="Tab order matches the structure tree (tabs flow naturally)",
        severity=Severity.MAJOR,
        category=Category.NAVIGATION,
        standards=(_ua("7.18.3"),),
        remediation=(
            "On every page set /Tabs = /S so tab order follows the structure tree, "
            "not the page object order."
        ),
    ),
    "7.18.4-1": RuleSpec(
        name="Link annotations are tagged with <Link>",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.18.4"), _WCAG_LINK_PURPOSE),
        remediation=(
            "Wrap each link's text in a <Link> structure element and reference the "
            "link annotation via /OBJR. Use meaningful link text — avoid 'click here'."
        ),
    ),
    "7.18.5-2": RuleSpec(
        name="Links have an alternate description via /Contents",
        severity=Severity.MAJOR,
        category=Category.SEMANTICS,
        standards=(_ua("7.18.5"), _WCAG_LINK_PURPOSE, _WCAG_NAME_ROLE_VALUE),
        remediation=(
            "Set /Contents on every link annotation with a description of the "
            "link's destination or purpose (per ISO 32000-1 §14.9.3)."
        ),
    ),
    "7.18.6-1": RuleSpec(
        name="Form widgets have /TU (tooltip) usable as accessible name",
        severity=Severity.MAJOR,
        category=Category.FORMS,
        standards=(_ua("7.18.6"), _WCAG_NAME_ROLE_VALUE),
        remediation=(
            "Set /TU on each form widget. The TU value is what screen readers "
            "announce as the field's name."
        ),
    ),
    # ---- Section 7.21: Fonts ----
    "7.21.3.1-1": RuleSpec(
        name="Embedded fonts include all glyphs used by the document",
        severity=Severity.MAJOR,
        category=Category.TEXT,
        standards=(_ua("7.21.3.1"),),
        remediation=(
            "Re-export with full font embedding. Subset embedding is fine as long "
            "as every used glyph is present in the embedded subset."
        ),
    ),
    "7.21.4.1-1": RuleSpec(
        name="Symbolic fonts have a Unicode mapping for every glyph",
        severity=Severity.MAJOR,
        category=Category.TEXT,
        standards=(_ua("7.21.4.1"), _WCAG_INFO_REL),
        remediation=(
            "Provide a ToUnicode CMap for symbolic fonts so each glyph maps to a "
            "real Unicode code point."
        ),
    ),
    # ---- Section 8: Document language ----
    "11-1": RuleSpec(
        name="Document /Lang is set in the catalog",
        severity=Severity.MAJOR,
        category=Category.STRUCTURE,
        standards=(_ua("11", "Natural language"), _WCAG_LANGUAGE),
        remediation=(
            "In Acrobat Pro: File → Properties → Advanced → Language. Set the "
            "BCP-47 tag (e.g. 'en-US')."
        ),
    ),
    "11-2": RuleSpec(
        name="/Lang values are valid BCP-47 language tags",
        severity=Severity.MINOR,
        category=Category.STRUCTURE,
        standards=(_ua("11"), _WCAG_LANGUAGE),
        remediation=("Use proper BCP-47 codes. 'en-US', 'fr-CA', 'zh-Hans-CN' — not 'English'."),
    ),
}


GENERIC_FALLBACK = RuleSpec(
    name="PDF/UA-1 rule violation (uncategorized)",
    severity=Severity.MAJOR,
    category=Category.STRUCTURE,
    standards=(_ua("various"),),
    remediation=(
        "Open the document in a PDF accessibility tool and follow the rule "
        "guidance. See the veraPDF rule description in 'Evidence' below."
    ),
)


def get_spec(rule_key: str) -> RuleSpec:
    return RULES.get(rule_key, GENERIC_FALLBACK)


__all__ = ["GENERIC_FALLBACK", "RULES", "RuleSpec", "get_spec"]
