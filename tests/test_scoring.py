"""Tests for the scoring engine."""

from __future__ import annotations

from pdf_a11y.config import Config
from pdf_a11y.models import (
    Category,
    CheckResult,
    DetectionMethod,
    Finding,
    Severity,
)
from pdf_a11y.scoring import compute_score


def _cr(
    check_id: str,
    severity: Severity,
    *,
    findings: int = 0,
    finding_severity: Severity | None = None,
    applicable: bool = True,
) -> CheckResult:
    fs = finding_severity or severity
    return CheckResult(
        check_id=check_id,
        name=check_id,
        severity=severity,
        category=Category.STRUCTURE,
        applicable=applicable,
        findings=[
            Finding(
                check_id=check_id,
                severity=fs,
                category=Category.STRUCTURE,
                detection=DetectionMethod.MACHINE,
                message="x",
                remediation="y",
            )
            for _ in range(findings)
        ],
    )


def test_perfect_document_scores_100() -> None:
    cfg = Config()
    results = [
        _cr("A", Severity.CRITICAL),
        _cr("B", Severity.MAJOR),
        _cr("C", Severity.MINOR),
    ]
    score = compute_score(results, cfg)
    assert score.score_pct == 100.0
    assert score.grade == "A"
    assert score.raw_penalty == 0
    assert score.max_penalty == 10 + 4 + 1


def test_each_severity_contributes_its_weight_per_occurrence() -> None:
    cfg = Config()
    results = [
        # Major check that triggers twice → 4 × 2 = 8 penalty.
        _cr("B", Severity.MAJOR, findings=2),
        _cr("C", Severity.MINOR),
    ]
    score = compute_score(results, cfg)
    assert score.raw_penalty == 8
    assert score.max_penalty == 4 + 1
    # 8 / 5 > 1 → score clamps at 0
    assert score.score_pct == 0.0
    assert score.grade == "F"


def test_inapplicable_check_excluded_from_max_penalty() -> None:
    cfg = Config()
    results = [
        _cr("A", Severity.CRITICAL, applicable=False),
        _cr("B", Severity.MAJOR),
    ]
    score = compute_score(results, cfg)
    assert score.max_penalty == 4
    assert score.raw_penalty == 0
    assert score.score_pct == 100.0


def test_critical_fail_override_forces_F_regardless_of_score() -> None:
    cfg = Config()
    results = [
        _cr("STRUCT-001", Severity.CRITICAL, findings=1),
        _cr("OTHER", Severity.CRITICAL),
        _cr("OTHER2", Severity.CRITICAL),
        _cr("OTHER3", Severity.CRITICAL),
    ]
    score = compute_score(results, cfg)
    # Score itself is 75% (10/40 penalty) → would be C, but critical-fail overrides.
    assert score.score_pct == 75.0
    assert score.grade == "F"
    assert score.critical_fail is True
    assert "STRUCT-001" in score.critical_fail_reasons


def test_grade_thresholds() -> None:
    """Hand-tune raw/max penalty pairs that land on each grade band."""
    cfg = Config()
    # 95+ = A, 85-94 = B, 70-84 = C, 50-69 = D, <50 = F.
    # Build a 100-weight pool from 10 Critical checks (weight 10 each).
    # Each 1 trigger costs 10 → score_pct = 100 - 10*n.
    # n=0 → 100 (A), n=1 → 90 (B), n=2 → 80 (C), n=4 → 60 (D), n=6 → 40 (F).
    cases = [(0, "A"), (1, "B"), (2, "C"), (4, "D"), (6, "F")]
    for n_findings, expected in cases:
        results = [
            _cr(f"chk-{i}", Severity.CRITICAL, findings=1 if i < n_findings else 0)
            for i in range(10)
        ]
        score = compute_score(results, cfg)
        assert score.grade == expected, f"n={n_findings} score={score.score_pct} got={score.grade}"


def test_no_applicable_checks_yields_zero() -> None:
    cfg = Config()
    score = compute_score([_cr("A", Severity.CRITICAL, applicable=False)], cfg)
    assert score.max_penalty == 0
    assert score.score_pct == 0.0
    assert score.grade == "F"


def test_breakdown_has_one_row_per_check() -> None:
    cfg = Config()
    results = [
        _cr("A", Severity.CRITICAL, findings=1),
        _cr("B", Severity.MINOR),
    ]
    score = compute_score(results, cfg)
    assert len(score.breakdown) == 2
    a, b = score.breakdown
    assert a.check_id == "A"
    assert a.triggered is True
    assert a.occurrences == 1
    assert a.penalty == 10
    assert b.triggered is False
    assert b.penalty == 0


def test_warning_severity_does_not_penalize() -> None:
    cfg = Config()
    results = [
        _cr("W", Severity.WARNING, findings=5, finding_severity=Severity.WARNING),
        _cr("M", Severity.MAJOR),
    ]
    score = compute_score(results, cfg)
    # Warnings: weight 0 → no penalty. Max penalty = 0 (W) + 4 (M) = 4.
    assert score.raw_penalty == 0
    assert score.score_pct == 100.0
