"""Server-side HTML → PDF export via WeasyPrint.

Three flavours, each returning PDF bytes:

    render_per_pdf_pdf(report)            -> bytes
    render_executive_summary_pdf(batch)   -> bytes
    render_comprehensive_pdf(batch)       -> bytes

The HTML inputs reuse the templates that drive the web UI report
(`_base.css`, `per_pdf.html.j2`, `_per_pdf_inline.html.j2`) plus a
print-specific `_print.css` for paged-layout rules (page breaks,
counters, running headers/footers). This means visual changes to the
web reports propagate to the PDFs automatically.

Notes on portability:

- WeasyPrint needs glib/gobject/pango/cairo native libs. On macOS those
  live in `/opt/homebrew/lib`; `config.ensure_weasyprint_libs_on_path()`
  sets DYLD_FALLBACK_LIBRARY_PATH so dlopen finds them. Linux usually
  finds them automatically. Windows: install the GTK runtime per the
  WeasyPrint docs.
- We import weasyprint inside each render fn so the rest of the app
  starts fast even if WeasyPrint's lib chain isn't ready yet (and the
  error surfaces at PDF-time with a clearer message).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pdf_a11y.config import ensure_weasyprint_libs_on_path
from pdf_a11y.models import BatchReport, Finding, PdfReport, Severity

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_BASE_CSS = (_TEMPLATE_DIR / "_base.css").read_text(encoding="utf-8")
_PRINT_CSS = (_TEMPLATE_DIR / "_print.css").read_text(encoding="utf-8")

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _grade_class(grade: str) -> str:
    return {
        "A": "grade-a",
        "B": "grade-b",
        "C": "grade-c",
        "D": "grade-d",
        "F": "grade-f",
    }.get(grade, "grade-unknown")


def _severity_class(severity: Severity) -> str:
    return f"sev-{severity.value.lower()}"


_env.filters["grade_class"] = _grade_class
_env.filters["severity_class"] = _severity_class


# ---------------------------------------------------------------------------
# Public renderers
# ---------------------------------------------------------------------------


def render_per_pdf_pdf(report: PdfReport) -> bytes:
    """Single-document accessibility report as a standalone PDF."""
    body_html = _render_per_pdf_inline_html(report)
    title = report.metadata.title or report.metadata.source
    return _wrap_and_print(body_html, title=f"PDF accessibility — {title}")


def render_executive_summary_pdf(batch: BatchReport) -> bytes:
    """Run-level overview (cover page, stats, grade chart, top issues)."""
    body_html = _render_executive_html(batch)
    return _wrap_and_print(
        body_html, title=f"Executive summary — run {_short_run_label(batch)}"
    )


def render_comprehensive_pdf(batch: BatchReport) -> bytes:
    """Executive summary + every per-PDF report inline. Big document.

    We assemble the body in Python rather than via {% include %} because
    Jinja's include doesn't easily rebind the partial's `report` variable
    per iteration without context-bleed bugs. The comprehensive.html.j2
    template is kept for human reference but the Python helper below is
    what actually runs.
    """
    body_html = _render_comprehensive_with_inline(batch)
    return _wrap_and_print(
        body_html, title=f"Comprehensive report — run {_short_run_label(batch)}"
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _wrap_and_print(body_html: str, *, title: str) -> bytes:
    """Wrap body content in a full HTML doc with base + print CSS, then render."""
    ensure_weasyprint_libs_on_path()
    import weasyprint  # imported lazily so app starts fast

    doc = (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{_html_escape(title)}</title><style>"
        + _BASE_CSS
        + "\n"
        + _PRINT_CSS
        + "</style></head><body>"
        + body_html
        + "</body></html>"
    )
    return weasyprint.HTML(string=doc).write_pdf()


def _render_per_pdf_inline_html(report: PdfReport) -> str:
    template = _env.get_template("_per_pdf_inline.html.j2")
    return template.render(
        report=report,
        grouped=_group_findings(report),
        manual=[f for f in report.findings if f.requires_manual_verification],
    )


def _render_executive_html(batch: BatchReport) -> str:
    grade_counts = _grade_counts(batch.reports)
    grade_total = sum(grade_counts.values())
    template = _env.get_template("executive.html.j2")
    return template.render(
        batch=batch,
        run_label=_short_run_label(batch),
        source_summary=_source_summary(batch),
        grade_counts=grade_counts,
        grade_total=grade_total,
        worst_docs=_worst_docs(batch.reports),
        top_check_ids=_top_check_ids(batch.reports),
    )


def _render_comprehensive_with_inline(batch: BatchReport) -> str:
    """Manually concatenate exec summary + per-PDF inline blocks.

    Jinja's `{% include %}` doesn't easily let us pass a different `report`
    on each iteration without context-bleed, so we build the body in Python
    and let the parent print-CSS handle page breaks via `pdf-report-section`.
    """
    chunks: list[str] = [_render_executive_html(batch)]

    valid = [r for r in batch.reports if not r.error]
    errored = [r for r in batch.reports if r.error]

    chunks.append('<h2 class="page-break-before">All evaluated documents</h2>')
    chunks.append(
        f'<p class="muted" style="font-size:0.85em;">{len(valid)} PDFs evaluated; '
        f'{len(errored)} non-PDF URLs are listed at the end.</p>'
    )
    for i, r in enumerate(valid, start=1):
        title = _html_escape(r.metadata.title or r.metadata.source)
        chunks.append(
            f'<section class="pdf-report-section">'
            f'<h2 class="section-title doc-title-hidden">{i}. {title}</h2>'
            + _render_per_pdf_inline_html(r)
            + "</section>"
        )

    if errored:
        chunks.append('<section class="page-break-before">')
        chunks.append(
            f"<h2>URLs that did not return a valid PDF ({len(errored)})</h2>"
        )
        chunks.append(
            '<p class="muted">These rows were skipped — they returned HTML, '
            "redirects, 404s, or timed out. They are not counted in the grade "
            "distribution or per-PDF scoring.</p>"
        )
        chunks.append(
            '<table class="no-break-inside"><thead><tr>'
            "<th>URL</th><th>Error</th></tr></thead><tbody>"
        )
        for r in errored:
            src = _html_escape(r.metadata.source or "")
            err = _html_escape(r.error or "(no detail)")
            chunks.append(
                "<tr>"
                f'<td><span class="muted" style="font-size:0.82em;">{src}</span></td>'
                f'<td style="font-size:0.82em;">{err}</td>'
                "</tr>"
            )
        chunks.append("</tbody></table></section>")

    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _group_findings(report: PdfReport) -> dict[str, list[Finding]]:
    order = [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.WARNING]
    grouped: dict[str, list[Finding]] = {sev.value: [] for sev in order}
    for f in report.findings:
        grouped[f.severity.value].append(f)
    return grouped


def _grade_counts(reports: Iterable[PdfReport]) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for r in reports:
        if r.error:
            continue
        if r.score.grade in counts:
            counts[r.score.grade] += 1
    return counts


def _worst_docs(reports: Iterable[PdfReport], n: int = 10) -> list[PdfReport]:
    """Rank by (critical-fail desc, score asc) and return the top n."""
    valid = [r for r in reports if not r.error]
    valid.sort(key=lambda r: (not r.score.critical_fail, r.score.score_pct))
    return valid[:n]


def _top_check_ids(reports: Iterable[PdfReport], n: int = 10) -> list[dict]:
    """Most-hit check IDs across the batch, with a one-line description."""
    counter: Counter[str] = Counter()
    descriptions: dict[str, str] = {}
    for r in reports:
        if r.error:
            continue
        for f in r.findings:
            counter[f.check_id] += 1
            descriptions.setdefault(f.check_id, f.message)
    return [
        {"check_id": cid, "count": count, "message": descriptions.get(cid, "")}
        for cid, count in counter.most_common(n)
    ]


def _short_run_label(batch: BatchReport) -> str:
    started = batch.started_at.strftime("%Y-%m-%d %H:%M UTC")
    n = batch.total
    return f"{n} URL{'' if n == 1 else 's'} · {started}"


def _source_summary(batch: BatchReport) -> str:
    src = batch.input_summary or {}
    n = src.get("n_sources", batch.total)
    conc = src.get("concurrency", "?")
    return f"{n} URL{'' if n == 1 else 's'} (concurrency {conc})"


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


__all__ = [
    "render_comprehensive_pdf",
    "render_executive_summary_pdf",
    "render_per_pdf_pdf",
]
