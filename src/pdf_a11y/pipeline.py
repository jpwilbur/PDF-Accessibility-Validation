"""End-to-end orchestration: download → context → checks → score → report."""

from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import batched
from pathlib import Path

from pdf_a11y import __version__
from pdf_a11y.acquire import AcquiredPdf, Downloader
from pdf_a11y.checks import all_checks
from pdf_a11y.config import Config
from pdf_a11y.context import PdfContext
from pdf_a11y.models import (
    BatchReport,
    CheckResult,
    FileMetadata,
    Finding,
    PdfReport,
    Severity,
    ToolVersions,
)
from pdf_a11y.scoring import compute_score

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvent:
    """Emitted to the optional progress callback at each PDF and on phase changes."""

    phase: str
    """One of: 'starting', 'acquiring', 'evaluating', 'finished'."""
    n_total: int
    """Total URLs submitted to the pipeline (includes non-PDF acquisition errors)."""
    n_done: int
    """URLs processed so far. n_evaluated = n_done - n_errored."""
    n_errored: int
    """Acquisition errors (non-PDF responses, 4xx/5xx, timeouts) — these are
    NOT counted as evaluated documents and are excluded from grade
    distributions and activity logs."""
    n_critical_failed: int
    current_source: str | None = None
    last_grade: str | None = None
    last_score_pct: float | None = None
    last_is_error: bool = False
    """True when the most recently processed URL was an acquisition error
    (not a real PDF). UI surfaces should not increment grade distributions
    or write activity-log entries for these."""
    message: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]


class Pipeline:
    def __init__(
        self,
        config: Config,
        on_progress: ProgressCallback | None = None,
    ):
        self.config = config
        self.config.ensure_java_on_path()
        self.checks = all_checks()
        self.tool_versions = _detect_tool_versions()
        self._on_progress = on_progress

    def _emit(self, event: ProgressEvent) -> None:
        if self._on_progress is not None:
            try:
                self._on_progress(event)
            except Exception as e:
                logger.debug("progress callback raised: %s", e)

    async def run(
        self,
        sources: list[str],
        user_metadata: list[dict[str, str]] | None = None,
    ) -> BatchReport:
        if user_metadata is None:
            user_metadata = [{} for _ in sources]
        if len(user_metadata) != len(sources):
            raise ValueError("user_metadata length must match sources length")

        started = datetime.now(UTC)
        n_total = len(sources)

        self._emit(
            ProgressEvent(
                phase="starting",
                n_total=n_total,
                n_done=0,
                n_errored=0,
                n_critical_failed=0,
                message=f"Starting evaluation of {n_total} PDF(s)",
            )
        )

        downloader = Downloader(
            cache_dir=self.config.paths.cache_dir,
            network=self.config.network,
        )
        cache_dir = self.config.paths.cache_dir
        delete_after = self.config.network.delete_cache_after_eval
        chunk_size = self.config.network.chunk_size
        # itertools.batched requires n >= 1; <= 0 means "one big chunk".
        batch_n = chunk_size if chunk_size and chunk_size > 0 else max(n_total, 1)

        reports: list[PdfReport] = []
        n_errored = 0
        n_critical_failed = 0

        for chunk in batched(range(n_total), batch_n):
            self._emit(
                ProgressEvent(
                    phase="acquiring",
                    n_total=n_total,
                    n_done=len(reports),
                    n_errored=n_errored,
                    n_critical_failed=n_critical_failed,
                    message="Downloading…",
                )
            )
            chunk_sources = [sources[i] for i in chunk]
            acquired = await downloader.acquire_many(chunk_sources)
            for i, ap in zip(chunk, acquired, strict=True):
                report = self._evaluate_one(sources[i], ap, user_metadata[i])
                reports.append(report)
                if report.error:
                    n_errored += 1
                if report.score.critical_fail:
                    n_critical_failed += 1
                is_error = report.error is not None
                self._emit(
                    ProgressEvent(
                        phase="evaluating",
                        n_total=n_total,
                        n_done=len(reports),
                        n_errored=n_errored,
                        n_critical_failed=n_critical_failed,
                        current_source=sources[i],
                        last_grade=None if is_error else report.score.grade,
                        last_score_pct=None if is_error else report.score.score_pct,
                        last_is_error=is_error,
                    )
                )
                if delete_after:
                    self._delete_cached(ap, cache_dir)

        _mark_duplicates(reports)

        finished = datetime.now(UTC)
        self._emit(
            ProgressEvent(
                phase="finished",
                n_total=n_total,
                n_done=len(reports),
                n_errored=n_errored,
                n_critical_failed=n_critical_failed,
                message="Done",
            )
        )
        return BatchReport(
            started_at=started,
            finished_at=finished,
            reports=reports,
            input_summary={
                "n_sources": len(sources),
                "concurrency": self.config.network.concurrency,
            },
            tool_versions=self.tool_versions,
        )

    # ------------------------------------------------------------------

    def _evaluate_one(
        self,
        source: str,
        ap: AcquiredPdf,
        user_metadata: dict[str, str],
    ) -> PdfReport:
        started = datetime.now(UTC)
        t0 = time.perf_counter()

        if ap.error:
            metadata = FileMetadata(
                source=source,
                final_url=ap.final_url,
                local_path=str(ap.local_path),
                sha256=ap.sha256 or "",
                byte_size=ap.byte_size,
                http_status=ap.http_status,
                content_type=ap.content_type,
                download_ms=ap.download_ms,
                blocked=ap.blocked,
            )
            score = compute_score([], self.config)
            return PdfReport(
                metadata=metadata,
                score=score,
                check_results=[],
                findings=[],
                user_metadata=user_metadata,
                tool_versions=self.tool_versions,
                started_at=started,
                finished_at=datetime.now(UTC),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                # A blocked URL isn't an acquisition bug on our side, and the
                # message already explains itself — don't bury it under a prefix
                # that reads like the document was at fault.
                error=ap.error if ap.blocked else f"acquisition failed: {ap.error}",
            )

        with PdfContext(
            path=ap.local_path,
            sha256=ap.sha256,
            source=source,
            final_url=ap.final_url,
            http_status=ap.http_status,
            content_type=ap.content_type,
            download_ms=ap.download_ms,
        ) as ctx:
            check_results: list[CheckResult] = []
            for check in self.checks:
                check_results.append(check.execute(ctx))

            findings = _flatten_findings(check_results)
            score = compute_score(check_results, self.config)
            metadata = self._build_metadata(source, ap, ctx)

        finished = datetime.now(UTC)
        return PdfReport(
            metadata=metadata,
            score=score,
            check_results=check_results,
            findings=findings,
            user_metadata=user_metadata,
            tool_versions=self.tool_versions,
            started_at=started,
            finished_at=finished,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def _delete_cached(self, ap: AcquiredPdf, cache_dir: Path) -> None:
        """Delete a downloaded PDF from the cache once it's been evaluated.

        Guarded so it only ever removes files *inside* cache_dir — never a
        user's original local source (which lives outside the cache), and a
        no-op on download-failure rows whose local_path is an empty Path().
        """
        path = ap.local_path
        try:
            if (
                path.is_file()
                and path.resolve().is_relative_to(cache_dir.resolve())
            ):
                path.unlink()
        except OSError as e:
            logger.warning("could not delete cached PDF %s: %s", path, e)

    def _build_metadata(self, source: str, ap: AcquiredPdf, ctx: PdfContext) -> FileMetadata:
        encryption_blocks_at = False
        if ctx.is_encrypted and ctx.pike is not None:
            try:
                encryption_blocks_at = not bool(getattr(ctx.pike.allow, "accessibility", True))
            except Exception:
                encryption_blocks_at = True

        creation_iso = _normalize_pdf_date(ctx.creation_date)
        mod_iso = _normalize_pdf_date(ctx.modification_date)
        days_between, days_since = _date_deltas(creation_iso, mod_iso)

        has_acroform = ctx.has_acroform
        has_xfa = ctx.has_xfa
        return FileMetadata(
            source=source,
            final_url=ap.final_url,
            local_path=str(ap.local_path),
            sha256=ap.sha256,
            byte_size=ap.byte_size,
            http_status=ap.http_status,
            content_type=ap.content_type,
            download_ms=ap.download_ms,
            blocked=ap.blocked,
            page_count=ctx.page_count,
            pdf_version=ctx.pdf_version,
            title=ctx.title,
            language=ctx.language,
            producer=ctx.producer,
            creator=ctx.creator,
            creation_date=creation_iso or ctx.creation_date,
            modification_date=mod_iso or ctx.modification_date,
            days_between_created_modified=days_between,
            days_since_modified=days_since,
            has_tagged_structure=ctx.has_tagged_structure,
            claims_pdf_ua=ctx.claims_pdf_ua,
            encrypted=ctx.is_encrypted,
            encryption_blocks_at=encryption_blocks_at,
            has_acroform=has_acroform,
            has_xfa=has_xfa,
            has_fillable_form=bool(has_acroform or has_xfa),
            has_bookmarks=ctx.has_bookmarks,
            extra={},
        )


def _mark_duplicates(reports: list[PdfReport]) -> None:
    """Set is_duplicate=True on any report whose sha256 appears more than once."""
    counts: Counter[str] = Counter(r.metadata.sha256 for r in reports if r.metadata.sha256)
    for r in reports:
        if r.metadata.sha256 and counts[r.metadata.sha256] > 1:
            r.metadata.is_duplicate = True


_PDF_DATE_RE = re.compile(r"D?:?(\d{4})(\d{2})(\d{2})")


def _normalize_pdf_date(raw: str | None) -> str | None:
    """PDF dates look like 'D:20210406140523-04'00''. Return ISO-like 'YYYY-MM-DD' or None."""
    if not raw:
        return None
    m = _PDF_DATE_RE.match(str(raw).strip())
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def _date_deltas(creation_iso: str | None, mod_iso: str | None) -> tuple[int | None, int | None]:
    days_between: int | None = None
    days_since: int | None = None
    today = datetime.now(UTC).date()
    cd = _parse_iso_date(creation_iso) if creation_iso else None
    md = _parse_iso_date(mod_iso) if mod_iso else None
    if cd and md:
        days_between = (md - cd).days
    if md:
        days_since = (today - md).days
    return days_between, days_since


def _parse_iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _flatten_findings(check_results: list[CheckResult]) -> list[Finding]:
    out: list[Finding] = []
    # Surface check-execution errors as a Warning-severity meta finding.
    for cr in check_results:
        if cr.error:
            out.append(
                Finding(
                    check_id=cr.check_id,
                    severity=Severity.WARNING,
                    category=cr.category,
                    detection=cr.findings[0].detection if cr.findings else _default_detection(),
                    message=f"Check did not complete: {cr.error}",
                    remediation="Re-run the evaluator. If the error persists, file an issue.",
                    standards=[],
                )
            )
        out.extend(cr.findings)
    order = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2, Severity.WARNING: 3}
    out.sort(key=lambda f: (order[f.severity], f.check_id))
    return out


def _default_detection():  # type: ignore[no-untyped-def]
    from pdf_a11y.models import DetectionMethod

    return DetectionMethod.MACHINE


def _detect_tool_versions() -> ToolVersions:
    pikepdf_ver = _pkg_version("pikepdf")
    pymupdf_ver = _pkg_version("pymupdf") or _pkg_version("PyMuPDF")
    pdfplumber_ver = _pkg_version("pdfplumber")

    verapdf_ver = _binary_version("verapdf", ["--version"], take_line=0)
    tesseract_ver = _binary_version("tesseract", ["--version"], take_line=0)

    return ToolVersions(
        pdf_a11y=__version__,
        python=platform.python_version(),
        pikepdf=pikepdf_ver,
        pymupdf=pymupdf_ver,
        pdfplumber=pdfplumber_ver,
        verapdf=verapdf_ver,
        tesseract=tesseract_ver,
    )


def _pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _binary_version(binary: str, args: list[str], take_line: int = 0) -> str | None:
    if not shutil.which(binary):
        return None
    try:
        out = subprocess.run(
            [binary, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = (out.stdout or out.stderr).strip()
        lines = text.splitlines()
        return lines[take_line].strip() if lines else None
    except Exception:
        return None


__all__ = ["Pipeline"]
