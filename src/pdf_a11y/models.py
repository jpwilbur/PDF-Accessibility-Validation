"""Strict pydantic models for the entire pipeline.

These types are the contract between checks, scoring, reporting, and any
downstream consumers (BI, ticketing). Treat changes here as breaking.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    CRITICAL = "Critical"
    MAJOR = "Major"
    MINOR = "Minor"
    WARNING = "Warning"


class Category(str, Enum):
    STRUCTURE = "Structure"
    SEMANTICS = "Semantics"
    TEXT = "Text"
    VISUAL = "Visual"
    NAVIGATION = "Navigation"
    FORMS = "Forms"
    MULTIMEDIA = "Multimedia"


class DetectionMethod(str, Enum):
    MACHINE = "machine"
    HEURISTIC = "heuristic"
    MANUAL = "manual"


class Standard(str, Enum):
    PDF_UA_1 = "PDF/UA-1"
    MATTERHORN = "Matterhorn"
    WCAG_21_A = "WCAG 2.1 A"
    WCAG_21_AA = "WCAG 2.1 AA"
    WCAG_22 = "WCAG 2.2"
    SECTION_508 = "Section 508"
    HHS = "HHS PDF Checklist"


class StandardRef(BaseModel):
    """A specific clause within a standard."""

    model_config = ConfigDict(frozen=True)

    standard: Standard
    clause: str = Field(..., description="e.g., '7.1', '1.1.1', 'Matterhorn 01-006'")
    title: str | None = None
    url: str | None = None


class Finding(BaseModel):
    """One concrete failure or warning produced by a check."""

    model_config = ConfigDict(frozen=True)

    check_id: str
    severity: Severity
    category: Category
    detection: DetectionMethod
    message: str = Field(..., description="One-sentence problem statement.")
    remediation: str = Field(..., description="How to fix it.")
    standards: list[StandardRef] = Field(default_factory=list)
    page: int | None = Field(None, description="1-based page number, when applicable.")
    location: str | None = Field(None, description="Free-text location detail.")
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary check-specific data (object refs, measured values).",
    )
    requires_manual_verification: bool = Field(
        False,
        description="True for heuristic findings that need a human to confirm.",
    )


class CheckResult(BaseModel):
    """Outcome of running one check against one PDF."""

    check_id: str
    name: str
    severity: Severity
    category: Category
    applicable: bool = True
    skipped_reason: str | None = None
    error: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    duration_ms: float = 0.0


class FileMetadata(BaseModel):
    """Per-PDF metadata captured during acquisition + parse."""

    source: str = Field(..., description="Original URL or local path provided as input.")
    final_url: str | None = None
    local_path: str
    sha256: str
    byte_size: int
    http_status: int | None = None
    content_type: str | None = None
    download_ms: float | None = None

    page_count: int | None = None
    pdf_version: str | None = None
    title: str | None = None
    language: str | None = None
    producer: str | None = None
    creator: str | None = None
    creation_date: str | None = None
    modification_date: str | None = None
    days_between_created_modified: int | None = None
    days_since_modified: int | None = None
    has_tagged_structure: bool | None = None
    has_xmp: bool | None = None
    claims_pdf_ua: bool | None = None
    encrypted: bool | None = None
    encryption_blocks_at: bool | None = None

    has_acroform: bool | None = None
    has_xfa: bool | None = None
    has_fillable_form: bool | None = None
    has_bookmarks: bool | None = None

    is_duplicate: bool = Field(
        False,
        description="True if this sha256 also appeared on another input in the same batch.",
    )

    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def byte_size_mb(self) -> float:
        return round(self.byte_size / 1_000_000, 2)


class ScoreBreakdownItem(BaseModel):
    check_id: str
    name: str
    severity: Severity
    weight: int
    occurrences: int
    penalty: int
    applicable: bool
    triggered: bool


class Score(BaseModel):
    raw_penalty: int
    max_penalty: int
    score_pct: float
    grade: str
    critical_fail: bool = False
    critical_fail_reasons: list[str] = Field(default_factory=list)
    breakdown: list[ScoreBreakdownItem] = Field(default_factory=list)


class ToolVersions(BaseModel):
    pdf_a11y: str
    python: str
    pikepdf: str | None = None
    pymupdf: str | None = None
    pdfplumber: str | None = None
    verapdf: str | None = None
    tesseract: str | None = None


class PdfReport(BaseModel):
    """Complete evaluation result for a single PDF."""

    metadata: FileMetadata
    score: Score
    check_results: list[CheckResult]
    findings: list[Finding] = Field(
        default_factory=list,
        description="Flat list across all checks, sorted by severity then check_id.",
    )
    user_metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Pass-through metadata from input row (owner, department, etc).",
    )
    tool_versions: ToolVersions
    started_at: datetime
    finished_at: datetime
    duration_ms: float

    error: str | None = Field(
        None, description="Pipeline-level error if the PDF could not be evaluated at all."
    )

    @property
    def top_findings(self) -> list[Finding]:
        """Top findings by (severity, check_id) for the 'fix first' UI."""
        order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.WARNING: 3}
        return sorted(self.findings, key=lambda f: (order[f.severity], f.check_id))[:5]


class BatchReport(BaseModel):
    """Aggregate over many PdfReports."""

    started_at: datetime
    finished_at: datetime
    reports: list[PdfReport]
    input_summary: dict[str, Any] = Field(default_factory=dict)
    tool_versions: ToolVersions

    @property
    def total(self) -> int:
        return len(self.reports)

    @property
    def errored(self) -> int:
        return sum(1 for r in self.reports if r.error)

    @property
    def critical_failed(self) -> int:
        return sum(1 for r in self.reports if r.score.critical_fail)


def report_paths_for(output_dir: Path, sha256: str) -> tuple[Path, Path]:
    """Conventional per-PDF report paths derived from sha256."""
    short = sha256[:12]
    html_path = output_dir / "pdfs" / f"{short}.html"
    json_path = output_dir / "pdfs" / f"{short}.json"
    return html_path, json_path
