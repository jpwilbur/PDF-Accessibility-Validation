"""PDF/UA-1 checks driven by veraPDF.

We register one `Check` per rule in our curated mapping (see :mod:`_pdfua_rules`)
plus a catch-all `PDFUA-OTHER` for any veraPDF rule we haven't mapped yet.
This keeps the spec's scoring math sane: each mapped rule contributes its
weight to `max_penalty`, so a document with many failures gets a proportional
penalty rather than blowing past the cap on a single check.
"""

from __future__ import annotations

from pdf_a11y.checks._pdfua_rules import GENERIC_FALLBACK, RULES, RuleSpec
from pdf_a11y.checks.base import Check
from pdf_a11y.checks.registry import register
from pdf_a11y.context import PdfContext
from pdf_a11y.models import Category, DetectionMethod, Finding, Severity, Standard, StandardRef


def _check_id(rule_key: str) -> str:
    return f"PDFUA-{rule_key}"


class _BaseVeraRuleCheck(Check):
    """Common applicability + run logic for all veraPDF-driven checks.

    Concrete subclasses are generated below; each one binds to a specific
    `rule_key`.
    """

    rule_key: str = ""  # set on subclass
    spec: RuleSpec = GENERIC_FALLBACK  # set on subclass

    detection = DetectionMethod.MACHINE
    description = "veraPDF-driven PDF/UA-1 rule check."

    def applies_to(self, ctx: PdfContext) -> bool:
        result = ctx.verapdf
        return bool(result.available and result.error is None)

    def run(self, ctx: PdfContext) -> list[Finding]:
        result = ctx.verapdf
        if not result.available or result.error is not None:
            return []
        findings: list[Finding] = []
        for failure in result.failures:
            if failure.key != self.rule_key:
                continue
            findings.extend(self._failure_to_findings(failure))
        return findings

    def _failure_to_findings(self, failure) -> list[Finding]:  # type: ignore[no-untyped-def]
        # Emit one finding per failed `<check>` location so users see all the
        # actual offending objects, not just one rule with N hidden under the hood.
        # If there are no individual locations, emit one rule-level finding.
        if not failure.locations:
            return [
                self.finding(
                    self._compose_message(failure, location_msg=None),
                    evidence={
                        "rule_key": failure.key,
                        "specification": failure.specification,
                        "test_expression": failure.test_expression,
                        "object_type": failure.object_type,
                        "tags": list(failure.tags),
                        "failed_checks": failure.failed_checks,
                        "verapdf_description": failure.description,
                    },
                )
            ]
        out: list[Finding] = []
        for loc in failure.locations:
            out.append(
                self.finding(
                    self._compose_message(failure, location_msg=loc.error_message or None),
                    location=_short_context(loc.context),
                    evidence={
                        "rule_key": failure.key,
                        "specification": failure.specification,
                        "test_expression": failure.test_expression,
                        "object_type": failure.object_type,
                        "tags": list(failure.tags),
                        "verapdf_description": failure.description,
                        "verapdf_context": loc.context,
                        "verapdf_error": loc.error_message,
                    },
                )
            )
        return out

    def _compose_message(self, failure, *, location_msg: str | None) -> str:  # type: ignore[no-untyped-def]
        # Lead with veraPDF's own rule description for accuracy. Our curated
        # name is used for the breakdown row label (via `self.name`) but is
        # not authoritative on rule wording — veraPDF is.
        base = (failure.description or self.spec.name or self.name).rstrip(".")
        if location_msg:
            return f"{base} — {location_msg}"
        return base


def _make_check_class(rule_key: str, spec: RuleSpec) -> type[Check]:
    cls_name = f"PdfUaRule_{rule_key.replace('.', '_').replace('-', '_')}"
    attrs = {
        "id": _check_id(rule_key),
        "name": spec.name,
        "description": spec.description or spec.name,
        "severity": spec.severity,
        "category": spec.category,
        "standards": list(spec.standards),
        "remediation": spec.remediation,
        "rule_key": rule_key,
        "spec": spec,
    }
    return type(cls_name, (_BaseVeraRuleCheck,), attrs)


# Register one Check per mapped rule.
for _rk, _sp in RULES.items():
    register(_make_check_class(_rk, _sp))


# Catch-all for veraPDF rules we haven't explicitly mapped.
@register
class PdfUaOtherCheck(_BaseVeraRuleCheck):
    id = "PDFUA-OTHER"
    name = "PDF/UA-1 — uncategorized rule failure"
    description = (
        "Catch-all for veraPDF rules not yet explicitly mapped to a remediation "
        "guide. The rule key, description, and offending object are surfaced in "
        "evidence."
    )
    severity = Severity.MAJOR
    category = Category.STRUCTURE
    standards = [
        StandardRef(
            standard=Standard.PDF_UA_1,
            clause="various",
            title="PDF/UA-1 (multiple clauses)",
            url="https://www.iso.org/standard/64599.html",
        ),
    ]
    remediation = (
        "Open the document in a PDF accessibility tool and follow the rule "
        "guidance — see 'verapdf_description' in evidence below."
    )
    rule_key = "*OTHER*"

    def run(self, ctx: PdfContext) -> list[Finding]:
        result = ctx.verapdf
        if not result.available or result.error is not None:
            return []
        mapped = set(RULES.keys())
        findings: list[Finding] = []
        for failure in result.failures:
            if failure.key in mapped:
                continue
            findings.extend(self._failure_to_findings(failure))
        return findings


# Veracity meta-finding: surface verapdf adapter errors so they appear in the
# report rather than silently disappearing.
@register
class PdfUaAdapterStatusCheck(Check):
    id = "PDFUA-ADAPTER"
    name = "PDF/UA validator availability"
    description = (
        "Surfaces veraPDF availability and adapter errors as a Warning so the "
        "user knows when UA-1 validation could not run."
    )
    severity = Severity.WARNING
    category = Category.STRUCTURE
    detection = DetectionMethod.MACHINE
    standards = [
        StandardRef(
            standard=Standard.PDF_UA_1,
            clause="—",
            title="Validator status",
        ),
    ]
    remediation = (
        "Install veraPDF (https://verapdf.org/) and ensure Java is on PATH. "
        "On macOS: `brew install verapdf openjdk`."
    )

    def applies_to(self, ctx: PdfContext) -> bool:  # noqa: ARG002
        return True

    def run(self, ctx: PdfContext) -> list[Finding]:
        result = ctx.verapdf
        if result.available and result.error is None:
            return []
        if not result.available:
            return [
                self.finding(
                    "veraPDF binary not found — PDF/UA-1 validation was skipped.",
                    requires_manual_verification=True,
                )
            ]
        return [
            self.finding(
                f"veraPDF failed to validate this PDF: {result.error}",
                evidence={"raw_xml_head": (result.raw_xml or "")[:500]},
                requires_manual_verification=True,
            )
        ]


def _short_context(context: str) -> str:
    """veraPDF contexts can be long. Trim to the last few path segments."""
    if not context:
        return ""
    parts = context.split("/")
    if len(parts) <= 4:
        return context
    return ".../" + "/".join(parts[-4:])
