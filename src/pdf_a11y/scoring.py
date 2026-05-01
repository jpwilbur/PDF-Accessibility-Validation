"""Scoring engine.

Per spec:
    raw_penalty   = sum(weight × occurrence_count) for all triggered findings
    max_penalty   = sum(weight) for all applicable checks
    score_pct     = max(0, 100 × (1 - raw_penalty / max_penalty))

Critical-fail override: if any of the configured critical-fail checks triggered
at least once, the document is graded F regardless of score.

Occurrence cap: a single check's contribution to raw_penalty is capped at
`PER_CHECK_OCCURRENCE_CAP` × weight. This prevents systemic issues (one root
cause that produces dozens of findings — e.g. a footer link missing /Contents
on every page) from saturating the score and squashing per-document
discrimination. All findings still surface in the report; the cap only affects
the numeric score.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pdf_a11y.config import Config
from pdf_a11y.models import (
    CheckResult,
    Score,
    ScoreBreakdownItem,
    Severity,
)

PER_CHECK_OCCURRENCE_CAP = 10
"""Past this many occurrences of one check, additional findings are still
surfaced but stop adding penalty. Tuned so a single systemic issue doesn't
swamp the score; calibrated empirically against real-world fixtures."""


def compute_score(
    check_results: Iterable[CheckResult],
    config: Config,
) -> Score:
    weights = config.weights
    critical_fail_ids = set(config.critical_fail_check_ids)

    results = list(check_results)

    # Per-check rollup
    breakdown: list[ScoreBreakdownItem] = []
    raw_penalty = 0
    max_penalty = 0
    triggered_critical_fail: list[str] = []

    for cr in results:
        weight = weights.get(cr.severity, 0)
        applicable = cr.applicable

        finding_severities = [f.severity for f in cr.findings]
        sev_counter = Counter(finding_severities)
        check_penalty = _capped_penalty(sev_counter, weights, PER_CHECK_OCCURRENCE_CAP)

        if applicable:
            max_penalty += weight
            raw_penalty += check_penalty

        triggered = bool(cr.findings)
        if triggered and cr.check_id in critical_fail_ids:
            triggered_critical_fail.append(cr.check_id)

        breakdown.append(
            ScoreBreakdownItem(
                check_id=cr.check_id,
                name=cr.name,
                severity=cr.severity,
                weight=weight,
                occurrences=len(cr.findings),
                penalty=check_penalty,
                applicable=applicable,
                triggered=triggered,
            )
        )

    score_pct = 0.0 if max_penalty <= 0 else max(0.0, 100.0 * (1.0 - raw_penalty / max_penalty))

    grade = _letter_grade(score_pct, config.grade_thresholds)
    critical_fail = bool(triggered_critical_fail)
    if critical_fail:
        grade = "F"

    return Score(
        raw_penalty=raw_penalty,
        max_penalty=max_penalty,
        score_pct=round(score_pct, 1),
        grade=grade,
        critical_fail=critical_fail,
        critical_fail_reasons=triggered_critical_fail,
        breakdown=breakdown,
    )


def _capped_penalty(sev_counter: Counter[Severity], weights: dict[Severity, int], cap: int) -> int:
    """Sum weight×count across severities, capping the *total occurrence count*
    for the check at `cap`. Higher-severity findings consume the cap first so
    the highest-weighted contribution is always preserved.
    """
    remaining = cap
    total = 0
    # Highest severity first so the cap is spent on the worst findings.
    order = (Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.WARNING)
    for sev in order:
        n = sev_counter.get(sev, 0)
        if n <= 0 or remaining <= 0:
            continue
        used = min(n, remaining)
        total += weights.get(sev, 0) * used
        remaining -= used
    return total


def _letter_grade(score_pct: float, thresholds: dict[str, int]) -> str:
    # Apply in descending order — highest threshold wins.
    for letter in ("A", "B", "C", "D"):
        if letter in thresholds and score_pct >= thresholds[letter]:
            return letter
    return "F"


__all__ = ["Severity", "compute_score"]
