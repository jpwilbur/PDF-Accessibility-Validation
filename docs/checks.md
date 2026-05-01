# Check catalog

Auto-generated from the registered check classes by `pdf-a11y gen-docs`. Generated 2026-05-01 19:44 UTC from pdf-a11y 0.1.0.

Severity legend: **Critical** (10), **Major** (4), **Minor** (1), **Warning** (0). Detection: **machine** (deterministic), **heuristic** (may produce false positives — read evidence), **manual** (surfaced for human verification only).

## Summary

- **Total registered checks:** 47
- **Forms:** 1
- **Navigation:** 1
- **Semantics:** 21
- **Structure:** 19
- **Text:** 4
- **Visual:** 1

## Forms

### `PDFUA-7.18.6-1` — Form widgets have /TU (tooltip) usable as accessible name

- **Severity:** Major · **Category:** Forms · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.6](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html)

Form widgets have /TU (tooltip) usable as accessible name

**Remediation.** Set /TU on each form widget. The TU value is what screen readers announce as the field's name.


## Navigation

### `PDFUA-7.18.3-1` — Tab order matches the structure tree (tabs flow naturally)

- **Severity:** Major · **Category:** Navigation · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.3](https://www.iso.org/standard/64599.html)

Tab order matches the structure tree (tabs flow naturally)

**Remediation.** On every page set /Tabs = /S so tab order follows the structure tree, not the page object order.


## Semantics

### `PDFUA-7.1-6` — Tags are nested correctly per the standard structure types

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Tags are nested correctly per the standard structure types

**Remediation.** Use only standard structure types (Document, Sect, P, H1-H6, L, LI, Table, etc.) or correctly mapped role-mapped equivalents.

### `PDFUA-7.1-7` — Standard tags are not remapped

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Standard tags are not remapped

**Remediation.** Don't remap standard structure tags (P, H1, Table, etc.) via /RoleMap. Custom tags must roleMap to a standard tag, but standard tags must keep their canonical meaning.

### `PDFUA-7.18.1-1` — Annotations are referenced from the structure tree

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html)

Annotations are referenced from the structure tree

**Remediation.** Every annotation (link, form field, comment) must have a corresponding structure-tree entry so it appears in the reading order.

### `PDFUA-7.18.1-2` — Annotations have /Contents or enclosing-structure /Alt as accessible name

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html)

Annotations have /Contents or enclosing-structure /Alt as accessible name

**Remediation.** On each annotation (link, form field, comment), either set /Contents with descriptive text, or wrap the annotation in a structure element that has /Alt text.

### `PDFUA-7.18.2-1` — Annotations have a /Contents entry usable as an accessible name

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.2](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html)

Annotations have a /Contents entry usable as an accessible name

**Remediation.** Set /Contents on each annotation to text that screen readers can use as a fallback accessible name.

### `PDFUA-7.18.4-1` — Link annotations are tagged with <Link>

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.4](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §2.4.4](https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html)

Link annotations are tagged with <Link>

**Remediation.** Wrap each link's text in a <Link> structure element and reference the link annotation via /OBJR. Use meaningful link text — avoid 'click here'.

### `PDFUA-7.18.5-2` — Links have an alternate description via /Contents

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.18.5](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §2.4.4](https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html)

Links have an alternate description via /Contents

**Remediation.** Set /Contents on every link annotation with a description of the link's destination or purpose (per ISO 32000-1 §14.9.3).

### `PDFUA-7.2-3` — Table elements contain only TR / THead / TBody / TFoot / Caption children

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.2](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Table elements contain only TR / THead / TBody / TFoot / Caption children

**Remediation.** Re-tag tables so <Table> only contains <TR>, <THead>, <TBody>, <TFoot>, or <Caption> children — not bare <P> or other paragraph tags.

### `PDFUA-7.3-1` — Graphics that are real content are tagged with /Figure

- **Severity:** Critical · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.3](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.1.1](https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html)

Graphics that are real content are tagged with /Figure

**Remediation.** Tag images conveying meaning as <Figure> in the structure tree. Decorative-only graphics must be marked as /Artifact instead.

### `PDFUA-7.3-2` — <Figure> elements have alternate text (/Alt) or /ActualText

- **Severity:** Critical · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.3](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.1.1](https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html), [Section 508 §E205.4](https://www.access-board.gov/ict/#E205-electronic-content)

<Figure> elements have alternate text (/Alt) or /ActualText

**Remediation.** Add /Alt (or /ActualText) to every <Figure> element. The alt text should describe the meaning of the graphic for someone who cannot see it.

### `PDFUA-7.4.2-1` — Heading levels are sequential (no jumps)

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.4.2](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html), [WCAG 2.1 AA §2.4.6](https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html)

Heading levels are sequential (no jumps)

**Remediation.** Adjust the tag tree so heading levels are not skipped (don't go from <H1> directly to <H3>).

### `PDFUA-7.4.4-1` — Documents using strong structure use real heading tags (H1, H2, ...)

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.4.4](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Documents using strong structure use real heading tags (H1, H2, ...)

**Remediation.** Use numbered heading tags (H1-H6) rather than the unnumbered <H> for documents with explicit heading hierarchy.

### `PDFUA-7.4.4-3` — Documents are either strongly or weakly structured (not both)

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.4.4](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Documents are either strongly or weakly structured (not both)

**Remediation.** Pick one heading style: either always use numbered <H1>-<H6> (strong structure) or always use <H> with /Lvl (weak structure). Don't mix the two within the same document.

### `PDFUA-7.5-1` — Table header cells (<TH>) have a /Scope attribute or referenceable IDs

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.5](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Table header cells (<TH>) have a /Scope attribute or referenceable IDs

**Remediation.** Either set /Scope (Row, Column, or Both) on every <TH>, or give each <TH> an /ID and reference it from the corresponding <TD> /Headers.

### `PDFUA-7.5-2` — Tables use the standard <Table>/<TR>/<TH>/<TD> structure

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.5](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Tables use the standard <Table>/<TR>/<TH>/<TD> structure

**Remediation.** Replace pseudo-tables (lists, paragraphs, or bare layout) with proper <Table>/<TR>/<TH>/<TD> tags so assistive tech can navigate row/column.

### `PDFUA-7.6-1` — Lists use <L> with <LI>/<Lbl>/<LBody>

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.6](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Lists use <L> with <LI>/<Lbl>/<LBody>

**Remediation.** Re-tag bulleted and numbered lists as <L> containing <LI> elements, each with optional <Lbl> for the marker and <LBody> for the content.

### `PDFUA-7.6-2` — <L> /ListNumbering attribute matches the visual list style

- **Severity:** Minor · **Category:** Semantics · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.6](https://www.iso.org/standard/64599.html)

<L> /ListNumbering attribute matches the visual list style

**Remediation.** Set /ListNumbering on each <L> to one of the standard values (Disc/Circle/Square/Decimal/UpperAlpha/LowerAlpha/UpperRoman/LowerRoman/None).

### `SEM-002` — Alt text is meaningful

- **Severity:** Major · **Category:** Semantics · **Detection:** heuristic
- **Standards:** [WCAG 2.1 A §1.1.1](https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html), [PDF/UA-1 §7.3](https://www.iso.org/standard/64599.html)

Each <Figure> with alternate text should describe the image's meaning. Generic placeholders ('image', 'picture', filenames) defeat the purpose of /Alt; excessively long alt (>250 chars) belongs in surrounding body text or /ActualText, not /Alt.

**Remediation.** Replace generic alt text with a description of what the image conveys. If the image is purely decorative, mark it as /Artifact instead of <Figure>. If extensive description is needed, put it in body text and use a short /Alt.

### `SEM-004` — Heading levels are sequential

- **Severity:** Major · **Category:** Semantics · **Detection:** machine
- **Standards:** [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html), [WCAG 2.1 AA §2.4.6](https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html), [PDF/UA-1 §7.4](https://www.iso.org/standard/64599.html)

Heading tags should not skip levels (e.g. H1 directly to H3). Skipped levels confuse screen-reader users navigating by heading shortcuts.

**Remediation.** Renumber headings so each new level is at most one greater than the previous heading's level. Use intermediate H2/H3/etc. as needed.

### `SEM-005` — Document has an <H1> if it has any headings

- **Severity:** Minor · **Category:** Semantics · **Detection:** machine
- **Standards:** [WCAG 2.1 AA §2.4.6](https://www.w3.org/WAI/WCAG21/Understanding/headings-and-labels.html), [PDF/UA-1 §7.4](https://www.iso.org/standard/64599.html)

Documents using numbered heading tags should start the hierarchy at H1. Missing H1 makes 'jump to top' navigation by heading less reliable.

**Remediation.** Re-tag the document's main title or top-level section heading as <H1>.

### `SEM-009` — Link text describes the destination

- **Severity:** Major · **Category:** Semantics · **Detection:** heuristic
- **Standards:** [WCAG 2.1 A §2.4.4](https://www.w3.org/WAI/WCAG21/Understanding/link-purpose-in-context.html), [PDF/UA-1 §7.18.5](https://www.iso.org/standard/64599.html)

Each <Link> element should contain text that conveys the destination's purpose out of context. Phrases like 'click here', 'more', or a bare URL are useless to a screen-reader user navigating by links list.

**Remediation.** Rewrite the link text to describe where the link goes (e.g. 'View the annual report (PDF)' instead of 'click here'). Keep URLs in surrounding text only when they are short and self-describing.


## Structure

### `PDFUA-11-1` — Document /Lang is set in the catalog

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §11](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §3.1.1](https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html)

Document /Lang is set in the catalog

**Remediation.** In Acrobat Pro: File → Properties → Advanced → Language. Set the BCP-47 tag (e.g. 'en-US').

### `PDFUA-11-2` — /Lang values are valid BCP-47 language tags

- **Severity:** Minor · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §11](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §3.1.1](https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html)

/Lang values are valid BCP-47 language tags

**Remediation.** Use proper BCP-47 codes. 'en-US', 'fr-CA', 'zh-Hans-CN' — not 'English'.

### `PDFUA-5-1` — PDF/UA identifier present in XMP

- **Severity:** Minor · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §5](https://www.iso.org/standard/64599.html)

PDF/UA identifier present in XMP

**Remediation.** After full PDF/UA remediation, add the PDF/UA identifier (pdfuaid:part = 1) via Acrobat Pro Preflight or your remediation tool.

### `PDFUA-6-1` — File version 1.7 or earlier (PDF/UA-1 only allows up to 1.7)

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §6](https://www.iso.org/standard/64599.html)

File version 1.7 or earlier (PDF/UA-1 only allows up to 1.7)

**Remediation.** Re-export the PDF as version 1.7 or earlier from your source application.

### `PDFUA-6-2` — Document Catalog declares a /MarkInfo with /Marked = true

- **Severity:** Critical · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §6](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Document Catalog declares a /MarkInfo with /Marked = true

**Remediation.** Re-export with tagging enabled. The catalog must contain /MarkInfo << /Marked true >> indicating the file is fully tagged.

### `PDFUA-6-3` — Document Catalog has a /StructTreeRoot

- **Severity:** Critical · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §6](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Document Catalog has a /StructTreeRoot

**Remediation.** Re-export with tagging enabled so a logical structure tree is produced.

### `PDFUA-6-4` — Catalog /ViewerPreferences /DisplayDocTitle is true

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §6](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §2.4.2](https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html)

Catalog /ViewerPreferences /DisplayDocTitle is true

**Remediation.** In Acrobat Pro: File → Properties → Initial View → Show: Document Title. This sets /ViewerPreferences << /DisplayDocTitle true >>.

### `PDFUA-7.1-1` — Real content is tagged in the structure tree

- **Severity:** Critical · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html), [Section 508 §E205.4](https://www.access-board.gov/ict/#E205-electronic-content)

Real content is tagged in the structure tree

**Remediation.** Verify in the Tag panel that every visible content stream is included in the structure tree under appropriate tags.

### `PDFUA-7.1-2` — Artifacts are not tagged as real content

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Artifacts are not tagged as real content

**Remediation.** Mark page numbers, headers/footers, and decorative graphics as /Artifact so screen readers do not announce them as part of the reading order.

### `PDFUA-7.1-3` — Content stream operators are inside marked-content sequences

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html)

Content stream operators are inside marked-content sequences

**Remediation.** Re-tag the document. All content must be inside /MCID-marked or /Artifact-marked content sequences.

### `PDFUA-7.1-4` — Suspects flag is false (if present)

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html)

Suspects flag is false (if present)

**Remediation.** Acrobat sets /Suspects = true when its tagging may be incorrect. Manually review and correct the tag tree, then clear the Suspects flag.

### `PDFUA-ADAPTER` — PDF/UA validator availability

- **Severity:** Warning · **Category:** Structure · **Detection:** machine
- **Standards:** PDF/UA-1 §—

Surfaces veraPDF availability and adapter errors as a Warning so the user knows when UA-1 validation could not run.

**Remediation.** Install veraPDF (https://verapdf.org/) and ensure Java is on PATH. On macOS: `brew install verapdf openjdk`.

### `PDFUA-OTHER` — PDF/UA-1 — uncategorized rule failure

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §various](https://www.iso.org/standard/64599.html)

Catch-all for veraPDF rules not yet explicitly mapped to a remediation guide. The rule key, description, and offending object are surfaced in evidence.

**Remediation.** Open the document in a PDF accessibility tool and follow the rule guidance — see 'verapdf_description' in evidence below.

### `STRUCT-001` — Document is tagged

- **Severity:** Critical · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html), [Section 508 §E205.4](https://www.access-board.gov/ict/#E205-electronic-content), Matterhorn §01, [HHS PDF Checklist §Tags](https://www.hhs.gov/web/section-508/making-files-accessible/index.html)

An accessible PDF must have a logical structure tree (StructTreeRoot) and MarkInfo /Marked = true. Without tags, assistive technology cannot convey meaning, reading order, or relationships.

**Remediation.** Re-export the document from its source application with tagging enabled (Word: 'Save as PDF' with 'Document structure tags for accessibility' on; InDesign: export as 'Tagged PDF'; Acrobat Pro: Tools → Accessibility → Autotag Document, then manually verify and correct the tag tree).

### `STRUCT-002` — Document title set and shown

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [WCAG 2.1 A §2.4.2](https://www.w3.org/WAI/WCAG21/Understanding/page-titled.html), Matterhorn §06

The document must declare a meaningful title in the Info dictionary (or XMP) and set ViewerPreferences /DisplayDocTitle = true so screen readers and the window title bar use the title rather than the filename.

**Remediation.** Set the document title in File → Properties → Description (Acrobat) or via the source application. Then set 'Initial View → Show: Document Title' in File → Properties → Initial View, which writes /ViewerPreferences << /DisplayDocTitle true >>.

### `STRUCT-003` — Document language declared

- **Severity:** Major · **Category:** Structure · **Detection:** machine
- **Standards:** [WCAG 2.1 A §3.1.1](https://www.w3.org/WAI/WCAG21/Understanding/language-of-page.html), Matterhorn §11

The catalog must declare the document's primary natural language via /Lang. Without it, screen readers cannot select the correct speech synthesizer or pronunciation rules.

**Remediation.** In Acrobat Pro: File → Properties → Advanced → Language. Set the BCP-47 language tag (e.g., 'en-US').

### `STRUCT-005` — Encryption does not block assistive technology

- **Severity:** Critical · **Category:** Structure · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §4.1.2](https://www.w3.org/WAI/WCAG21/Understanding/name-role-value.html), Matterhorn §07

If the PDF is encrypted, the permission flags must allow content extraction for accessibility (bit 10 in the /P value). Otherwise screen readers cannot read the document at all.

**Remediation.** Open File → Properties → Security in Acrobat Pro. Under 'Permissions', ensure 'Enable text access for screen reader devices for the visually impaired' is allowed. Re-save.

### `STRUCT-006` — PDF/UA conformance identifier present

- **Severity:** Minor · **Category:** Structure · **Detection:** machine
- **Standards:** PDF/UA-1 §5, Matterhorn §06

Conformant PDF/UA-1 documents declare 'pdfuaid:part = 1' in XMP metadata. Absence is not itself a barrier to use, but signals the document was not produced with PDF/UA in mind.

**Remediation.** After full PDF/UA remediation, add the PDF/UA identifier via Acrobat Pro Preflight ('Add tags to use PDF/UA conformance') or your remediation tool.

### `STRUCT-008` — Document has a real text layer

- **Severity:** Critical · **Category:** Structure · **Detection:** heuristic
- **Standards:** [WCAG 2.1 A §1.1.1](https://www.w3.org/WAI/WCAG21/Understanding/non-text-content.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html), [Section 508 §E205.4](https://www.access-board.gov/ict/#E205-electronic-content)

If pages are images of text with no underlying text layer, the document is unreadable by screen readers. Detected by sampling pages: an image-heavy page with effectively zero extractable text and Tesseract OCR finding substantial text indicates a scan-only PDF.

**Remediation.** Run OCR on the document (Acrobat Pro: Tools → Scan & OCR → Recognize Text → In This File) and then perform full accessibility tagging. OCR alone does NOT make a document accessible — it must also be tagged.


## Text

### `PDFUA-7.2-1` — All text has a Unicode mapping (no PUA / replacement gibberish)

- **Severity:** Major · **Category:** Text · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.2](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

All text has a Unicode mapping (no PUA / replacement gibberish)

**Remediation.** Embed proper ToUnicode CMaps for all fonts, or supply /ActualText on the affected spans so screen readers and copy-paste produce real text.

### `PDFUA-7.2-2` — Stretchable characters use /ActualText

- **Severity:** Minor · **Category:** Text · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.2](https://www.iso.org/standard/64599.html)

Stretchable characters use /ActualText

**Remediation.** Add /ActualText to spans where glyphs are constructed from multiple character codes (e.g., stretched parentheses).

### `PDFUA-7.21.3.1-1` — Embedded fonts include all glyphs used by the document

- **Severity:** Major · **Category:** Text · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.21.3.1](https://www.iso.org/standard/64599.html)

Embedded fonts include all glyphs used by the document

**Remediation.** Re-export with full font embedding. Subset embedding is fine as long as every used glyph is present in the embedded subset.

### `PDFUA-7.21.4.1-1` — Symbolic fonts have a Unicode mapping for every glyph

- **Severity:** Major · **Category:** Text · **Detection:** machine
- **Standards:** [PDF/UA-1 §7.21.4.1](https://www.iso.org/standard/64599.html), [WCAG 2.1 A §1.3.1](https://www.w3.org/WAI/WCAG21/Understanding/info-and-relationships.html)

Symbolic fonts have a Unicode mapping for every glyph

**Remediation.** Provide a ToUnicode CMap for symbolic fonts so each glyph maps to a real Unicode code point.


## Visual

### `VIS-001` — Text contrast meets WCAG AA

- **Severity:** Major · **Category:** Visual · **Detection:** heuristic
- **Standards:** [WCAG 2.1 AA §1.4.3](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html), [Section 508 §E207.2 / WCAG 1.4.3](https://www.access-board.gov/ict/#E207-revised-508-standards)

Heuristic check of text contrast against WCAG 2.1 §1.4.3 thresholds (4.5:1 for normal text, 3:1 for large text). For each text span, the foreground colour is read from the PDF content stream and the background is sampled from rendered pixels around the span's bounding box. Spans whose background is not uniform (e.g. text overlaid on photos) are skipped to avoid false positives.

**Remediation.** Increase the contrast between the text colour and the colour behind it. Aim for a luminance ratio of at least 4.5:1 for body text and 3:1 for large/bold display text. Tools like the WebAIM Contrast Checker can verify candidate colour pairs.
