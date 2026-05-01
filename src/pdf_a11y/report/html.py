"""HTML report rendering.

The reports are themselves accessible: semantic landmarks, real headings,
WCAG-AA contrast, keyboard-navigable filters on the batch page.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pdf_a11y.models import BatchReport, PdfReport, Severity

_TEMPLATE_DIR = Path(__file__).parent / "templates"

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


def render_pdf_html(report: PdfReport) -> str:
    template = _env.get_template("per_pdf.html.j2")
    grouped = _group_findings(report)
    manual = [f for f in report.findings if f.requires_manual_verification]
    return template.render(report=report, grouped=grouped, manual=manual)


def render_batch_html(batch: BatchReport, per_pdf_links: dict[str, str]) -> str:
    template = _env.get_template("batch.html.j2")
    rows = []
    for r in batch.reports:
        top = ", ".join(f.check_id for f in r.top_findings) or "—"
        link = per_pdf_links.get(r.metadata.sha256, "")
        rows.append(
            {
                "report": r,
                "top": top,
                "link": link,
            }
        )
    return template.render(batch=batch, rows=rows)


def _group_findings(report: PdfReport) -> dict[str, list]:
    order = [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.WARNING]
    grouped = {sev.value: [] for sev in order}
    for f in report.findings:
        grouped[f.severity.value].append(f)
    return grouped
