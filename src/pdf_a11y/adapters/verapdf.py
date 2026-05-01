"""veraPDF subprocess adapter.

veraPDF (https://verapdf.org/) is the reference open-source PDF/UA-1 and PDF/A
validator. We run it as a CLI subprocess against `--format xml` and parse the
resulting validation report into structured rule failures.

The adapter is conservative:
- If `verapdf` is not on PATH, or Java is missing, or the subprocess errors out,
  we return a sentinel result with `error` set; downstream checks then mark
  themselves not-applicable with a clear reason rather than silently passing.
- We never raise — a malformed report should surface as a Warning finding, not
  crash the run.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from lxml import etree

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VeraCheckLocation:
    context: str
    error_message: str


@dataclass(frozen=True)
class VeraRuleFailure:
    """A single failed veraPDF rule (which may have multiple `<check>` children)."""

    specification: str  # e.g. "ISO 14289-1:2014"
    clause: str  # e.g. "7.5"
    test_number: str  # e.g. "1"
    description: str
    object_type: str | None
    test_expression: str | None
    tags: tuple[str, ...]
    failed_checks: int
    locations: tuple[VeraCheckLocation, ...]

    @property
    def key(self) -> str:
        """Unique rule identifier we use as our check id suffix, e.g. '7.5-1'."""
        return f"{self.clause}-{self.test_number}"


@dataclass
class VeraResult:
    available: bool
    is_compliant: bool | None = None
    passed_rules: int = 0
    failed_rules: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    profile_name: str | None = None
    failures: list[VeraRuleFailure] = field(default_factory=list)
    error: str | None = None
    duration_ms: float | None = None
    raw_xml: str | None = None


@lru_cache(maxsize=1)
def is_available() -> bool:
    return shutil.which("verapdf") is not None


def run(pdf_path: Path, *, profile: str = "ua1", timeout: float = 120.0) -> VeraResult:
    """Run veraPDF against the given PDF and return parsed results.

    Always returns a VeraResult — never raises. If veraPDF is unavailable or
    fails, `available` and/or `error` will reflect that.
    """
    if not is_available():
        return VeraResult(
            available=False,
            error="verapdf binary not on PATH",
        )

    try:
        proc = subprocess.run(
            [
                "verapdf",
                "-f",
                profile,
                "--format",
                "xml",
                "--success",
                str(pdf_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return VeraResult(available=True, error=f"verapdf timed out after {timeout}s")
    except Exception as e:
        return VeraResult(available=True, error=f"verapdf invocation failed: {e!r}")

    if proc.returncode not in (0, 1):
        # 0 = compliant, 1 = non-compliant; anything else is a tool error.
        return VeraResult(
            available=True,
            error=(
                f"verapdf exited with code {proc.returncode}; stderr: "
                f"{(proc.stderr or '').strip()[:300]}"
            ),
            raw_xml=proc.stdout,
        )

    xml = proc.stdout or ""
    if not xml.strip():
        return VeraResult(
            available=True,
            error="verapdf produced no XML output",
        )

    try:
        return _parse_xml(xml)
    except Exception as e:
        return VeraResult(
            available=True,
            error=f"failed to parse verapdf XML: {e!r}",
            raw_xml=xml,
        )


def _parse_xml(xml_text: str) -> VeraResult:
    parser = etree.XMLParser(recover=True, ns_clean=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)

    job = root.find("./jobs/job")
    if job is None:
        # No job element — likely an error report.
        return VeraResult(
            available=True,
            error="no <job> element in verapdf XML",
            raw_xml=xml_text,
        )

    vr = job.find("./validationReport")
    if vr is None:
        return VeraResult(
            available=True,
            error="no <validationReport> element (verapdf may have failed to parse the PDF)",
            raw_xml=xml_text,
        )

    is_compliant_attr = vr.get("isCompliant")
    is_compliant = None if is_compliant_attr is None else is_compliant_attr.lower() == "true"
    profile = vr.get("profileName")

    details = vr.find("./details")
    if details is None:
        return VeraResult(
            available=True,
            is_compliant=is_compliant,
            profile_name=profile,
            error="no <details> element in validationReport",
            raw_xml=xml_text,
        )

    failures: list[VeraRuleFailure] = []
    for rule in details.findall("./rule"):
        if (rule.get("status") or "").lower() != "failed":
            continue
        clause = rule.get("clause") or ""
        test_number = rule.get("testNumber") or ""
        if not clause or not test_number:
            continue
        description = (rule.findtext("./description") or "").strip()
        object_type = (rule.findtext("./object") or "").strip() or None
        test_expr = (rule.findtext("./test") or "").strip() or None
        tags_attr = rule.get("tags") or ""
        tags = tuple(t.strip() for t in tags_attr.split(",") if t.strip())

        locations: list[VeraCheckLocation] = []
        for check in rule.findall("./check"):
            if (check.get("status") or "").lower() != "failed":
                continue
            context = (check.findtext("./context") or "").strip()
            err = (check.findtext("./errorMessage") or "").strip()
            locations.append(VeraCheckLocation(context=context, error_message=err))

        failures.append(
            VeraRuleFailure(
                specification=rule.get("specification") or "",
                clause=clause,
                test_number=test_number,
                description=description,
                object_type=object_type,
                test_expression=test_expr,
                tags=tags,
                failed_checks=int(rule.get("failedChecks") or len(locations) or 1),
                locations=tuple(locations),
            )
        )

    def _intattr(name: str, default: int = 0) -> int:
        v = details.get(name)
        try:
            return int(v) if v is not None else default
        except ValueError:
            return default

    return VeraResult(
        available=True,
        is_compliant=is_compliant,
        passed_rules=_intattr("passedRules"),
        failed_rules=_intattr("failedRules"),
        passed_checks=_intattr("passedChecks"),
        failed_checks=_intattr("failedChecks"),
        profile_name=profile,
        failures=failures,
        raw_xml=xml_text,
    )
