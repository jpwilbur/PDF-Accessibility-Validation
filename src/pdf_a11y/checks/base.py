"""Abstract base for all checks.

A Check is a stateless evaluator: given a PdfContext, return zero or more
Findings. Checks must not mutate the context. They must be cheap to construct
(class-level metadata, no I/O in __init__).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import ClassVar

from pdf_a11y.context import PdfContext
from pdf_a11y.models import (
    Category,
    CheckResult,
    DetectionMethod,
    Finding,
    Severity,
    StandardRef,
)


class Check(ABC):
    """Subclass must define class attributes and implement :meth:`run`."""

    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    severity: ClassVar[Severity]
    category: ClassVar[Category]
    detection: ClassVar[DetectionMethod] = DetectionMethod.MACHINE
    standards: ClassVar[list[StandardRef]] = []
    remediation: ClassVar[str] = ""

    def applies_to(self, ctx: PdfContext) -> bool:  # noqa: ARG002
        """Return False if preconditions not met (excluded from max_penalty)."""
        return True

    @abstractmethod
    def run(self, ctx: PdfContext) -> list[Finding]:
        """Return findings. Empty list = no issues for this check on this PDF."""
        raise NotImplementedError

    # ---- helpers -----------------------------------------------------------

    def finding(
        self,
        message: str,
        *,
        severity: Severity | None = None,
        page: int | None = None,
        location: str | None = None,
        evidence: dict[str, object] | None = None,
        remediation: str | None = None,
        requires_manual_verification: bool = False,
    ) -> Finding:
        """Construct a Finding inheriting class metadata, with overrides."""
        return Finding(
            check_id=self.id,
            severity=severity or self.severity,
            category=self.category,
            detection=self.detection,
            message=message,
            remediation=remediation or self.remediation,
            standards=list(self.standards),
            page=page,
            location=location,
            evidence=evidence or {},
            requires_manual_verification=requires_manual_verification,
        )

    def execute(self, ctx: PdfContext) -> CheckResult:
        """Run with timing and error capture; never raises."""
        result = CheckResult(
            check_id=self.id,
            name=self.name,
            severity=self.severity,
            category=self.category,
        )
        try:
            applicable = self.applies_to(ctx)
        except Exception as e:
            result.applicable = False
            result.error = f"applies_to raised: {e!r}"
            return result

        result.applicable = applicable
        if not applicable:
            result.skipped_reason = "preconditions not met"
            return result

        start = time.perf_counter()
        try:
            result.findings = self.run(ctx)
        except Exception as e:
            result.error = f"{type(e).__name__}: {e}"
        finally:
            result.duration_ms = (time.perf_counter() - start) * 1000.0
        return result
