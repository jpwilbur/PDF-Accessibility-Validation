"""Background-thread run executor + per-run progress bus.

A `RunRunner` holds:
  - the durable RunStore for history,
  - an in-memory ProgressBus for live SSE clients.

Calling `start(...)` spawns a thread that:
  1. Resolves URLs (ObservePoint or direct list).
  2. Runs the existing async Pipeline with a progress callback.
  3. Writes outputs to the run's output directory.
  4. Updates RunStore with status/counts as it goes.
  5. Pushes ProgressEvents onto the bus so the SSE handler can stream them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pdf_a11y import paths
from pdf_a11y.config import Config
from pdf_a11y.pipeline import Pipeline, ProgressEvent
from pdf_a11y.report import (
    render_batch_html,
    render_pdf_html,
    write_findings_jsonl,
    write_summary_csv,
)
from pdf_a11y.runs import RunRecord, RunStatus, RunStore, new_run_id

logger = logging.getLogger(__name__)


_BUS_QUEUE_MAXSIZE = 1024


@dataclass
class _BusState:
    last_event: dict[str, Any] | None = None
    subscribers: list[queue.Queue] = field(default_factory=list)
    finished: bool = False


class ProgressBus:
    """In-memory pub-sub keyed by run_id. Each subscriber gets its own queue."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, _BusState] = {}

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            state = self._states.setdefault(run_id, _BusState())
            state.last_event = event
            dead: list[queue.Queue] = []
            for q in state.subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                state.subscribers.remove(q)

    def finish(self, run_id: str) -> None:
        import contextlib

        with self._lock:
            state = self._states.setdefault(run_id, _BusState())
            state.finished = True
            for q in state.subscribers:
                with contextlib.suppress(queue.Full):
                    q.put_nowait({"phase": "finished", "_eos": True})

    def subscribe(self, run_id: str) -> tuple[queue.Queue, dict[str, Any] | None, bool]:
        q: queue.Queue = queue.Queue(maxsize=_BUS_QUEUE_MAXSIZE)
        with self._lock:
            state = self._states.setdefault(run_id, _BusState())
            state.subscribers.append(q)
            return q, state.last_event, state.finished

    def unsubscribe(self, run_id: str, q: queue.Queue) -> None:
        with self._lock:
            state = self._states.get(run_id)
            if state and q in state.subscribers:
                state.subscribers.remove(q)


class RunRunner:
    def __init__(self, store: RunStore, bus: ProgressBus | None = None) -> None:
        self.store = store
        self.bus = bus or ProgressBus()

    def start_manual(
        self,
        *,
        urls: Iterable[str],
        user_metadata: list[dict[str, str]] | None = None,
        concurrency: int | None = None,
        label: str | None = None,
    ) -> RunRecord:
        return self._start(
            source_kind="manual",
            source_meta={"n_inputs": len(list(urls))},
            urls=list(urls),
            user_metadata=user_metadata,
            concurrency=concurrency,
            label=label,
        )

    async def start_observepoint(
        self,
        *,
        api_key: str,
        report_id: str,
        concurrency: int | None = None,
        label: str | None = None,
    ) -> RunRecord:
        """Resolve URLs from ObservePoint (awaitable: caller may already be
        inside an event loop) then kick off the pipeline thread.

        We deliberately fetch URLs *before* starting the worker thread so the
        user sees an early error if the report ID/API key is wrong.
        """
        from pdf_a11y.observepoint import fetch_pdf_urls_async

        result = await fetch_pdf_urls_async(api_key=api_key, report_id=report_id)
        if result.error:
            # Create a record so it shows up in history with the error.
            run_id = new_run_id()
            output_dir = paths.run_output_dir(run_id)
            output_dir.mkdir(parents=True, exist_ok=True)
            rec = self.store.create(
                run_id=run_id,
                source_kind="observepoint",
                source_meta={"report_id": report_id, "report_name": result.report_name},
                output_dir=output_dir,
                label=label or f"ObservePoint #{report_id}",
            )
            self.store.update(run_id, status=RunStatus.FAILED, error=result.error, finished=True)
            self.bus.publish(
                run_id,
                {"phase": "failed", "message": result.error, "n_total": 0, "n_done": 0},
            )
            self.bus.finish(run_id)
            return rec

        meta = [
            {
                "op_report_id": report_id,
                "op_report_name": result.report_name or "",
            }
            for _ in result.urls
        ]
        return self._start(
            source_kind="observepoint",
            source_meta={
                "report_id": report_id,
                "report_name": result.report_name,
                "grid_entity_type": result.grid_entity_type,
                "n_urls": len(result.urls),
            },
            urls=result.urls,
            user_metadata=meta,
            concurrency=concurrency,
            label=label or f"ObservePoint #{report_id} — {result.report_name or ''}",
        )

    # ------------------------------------------------------------------

    def _start(
        self,
        *,
        source_kind: str,
        source_meta: dict[str, Any],
        urls: list[str],
        user_metadata: list[dict[str, str]] | None,
        concurrency: int | None,
        label: str | None,
    ) -> RunRecord:
        run_id = new_run_id()
        output_dir = paths.run_output_dir(run_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        rec = self.store.create(
            run_id=run_id,
            source_kind=source_kind,
            source_meta=source_meta,
            output_dir=output_dir,
            label=label,
        )

        thread = threading.Thread(
            target=self._run_thread,
            args=(run_id, urls, user_metadata, concurrency, output_dir),
            name=f"pdf-a11y-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return rec

    def _run_thread(
        self,
        run_id: str,
        urls: list[str],
        user_metadata: list[dict[str, str]] | None,
        concurrency: int | None,
        output_dir: Path,
    ) -> None:
        self.store.update(run_id, status=RunStatus.RUNNING, n_total=len(urls))
        self.bus.publish(
            run_id,
            {
                "phase": "starting",
                "n_total": len(urls),
                "n_done": 0,
                "n_errored": 0,
                "n_critical_failed": 0,
                "message": f"Starting evaluation of {len(urls)} PDF(s)",
            },
        )

        # Per-run cache: PDFs download under the run's own dir and are deleted
        # at the end so disk doesn't grow unboundedly. The report files
        # (summary.html, findings.jsonl, etc.) are kept; only the bytes go.
        cache_dir = output_dir / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        try:
            config = Config.load()
            config.paths.output_dir = output_dir
            config.paths.cache_dir = cache_dir
            if concurrency is not None:
                config.network.concurrency = concurrency

            def on_progress(event: ProgressEvent) -> None:
                payload = asdict(event)
                self.bus.publish(run_id, payload)
                self.store.update(
                    run_id,
                    n_total=event.n_total,
                    n_done=event.n_done,
                    n_errored=event.n_errored,
                    n_critical_failed=event.n_critical_failed,
                )

            pipeline = Pipeline(config, on_progress=on_progress)
            batch = asyncio.run(pipeline.run(urls, user_metadata))
            _write_outputs(batch, output_dir)

            self.store.update(
                run_id,
                status=RunStatus.DONE,
                n_total=batch.total,
                n_done=batch.total,
                n_errored=batch.errored,
                n_critical_failed=batch.critical_failed,
                finished=True,
            )
            self.bus.publish(
                run_id,
                {
                    "phase": "done",
                    "n_total": batch.total,
                    "n_done": batch.total,
                    "n_errored": batch.errored,
                    "n_critical_failed": batch.critical_failed,
                    "summary_url": "report/summary.html",
                },
            )
        except Exception as e:
            logger.exception("run %s failed", run_id)
            self.store.update(run_id, status=RunStatus.FAILED, error=str(e), finished=True)
            self.bus.publish(
                run_id,
                {"phase": "failed", "message": str(e)},
            )
        finally:
            # Reclaim disk: drop the cached PDF bytes now that the report is built.
            import shutil as _sh

            try:
                if cache_dir.exists():
                    _sh.rmtree(cache_dir)
            except OSError as e:
                logger.warning("failed to clean cache for run %s: %s", run_id, e)
            self.bus.finish(run_id)


def _write_outputs(batch, output_dir: Path) -> None:  # type: ignore[no-untyped-def]
    output_dir.mkdir(parents=True, exist_ok=True)
    pdfs_dir = output_dir / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)

    per_pdf_links: dict[str, str] = {}
    for report in batch.reports:
        if not report.metadata.sha256:
            continue
        short = report.metadata.sha256[:12]
        html_path = pdfs_dir / f"{short}.html"
        json_path = pdfs_dir / f"{short}.json"
        html_path.write_text(render_pdf_html(report), encoding="utf-8")
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        per_pdf_links[report.metadata.sha256] = str(html_path.relative_to(output_dir))

    (output_dir / "summary.html").write_text(
        render_batch_html(batch, per_pdf_links), encoding="utf-8"
    )
    write_findings_jsonl(batch, output_dir / "findings.jsonl")
    write_summary_csv(batch, output_dir / "summary.csv")

    # Grade distribution — written here so the run-detail page can re-hydrate
    # the chart on refresh. We exclude errored (non-PDF) reports for the same
    # reason the live UI does: those URLs aren't real PDFs and shouldn't
    # appear in any grade bucket.
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
    for r in batch.reports:
        if r.error:
            continue
        if r.score.grade in grade_counts:
            grade_counts[r.score.grade] += 1

    (output_dir / "batch.json").write_text(
        json.dumps(
            {
                "started_at": batch.started_at.isoformat(),
                "finished_at": batch.finished_at.isoformat(),
                "total": batch.total,
                "errored": batch.errored,
                "critical_failed": batch.critical_failed,
                "grade_counts": grade_counts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
