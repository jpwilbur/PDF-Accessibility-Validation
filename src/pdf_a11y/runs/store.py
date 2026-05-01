"""SQLite-backed run-history index.

Each evaluation run is a row in `runs`. The actual evaluation outputs
(summary.html, summary.csv, findings.jsonl, pdfs/*) live under
`pdf_a11y.paths.run_output_dir(run_id)`. The DB only indexes them so
the web UI can list and re-open historical runs quickly.

Per the user's spec, we deliberately do NOT compute or store any
run-level aggregate score — only per-PDF scores (already in the per-run
report files). The columns kept here are simple counts.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pdf_a11y import paths


def new_run_id() -> str:
    """Sortable, URL-safe run ID. UTC date-time + short uuid suffix."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


class RunStatus:
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class RunRecord:
    id: str
    started_at: str
    finished_at: str | None
    status: str
    source_kind: str  # "observepoint" | "manual"
    source_meta: dict[str, Any]
    output_dir: str
    n_total: int
    n_done: int
    n_errored: int
    n_critical_failed: int
    error: str | None
    label: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> RunRecord:
        return cls(
            id=row["id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            status=row["status"],
            source_kind=row["source_kind"],
            source_meta=json.loads(row["source_meta"] or "{}"),
            output_dir=row["output_dir"],
            n_total=row["n_total"],
            n_done=row["n_done"],
            n_errored=row["n_errored"],
            n_critical_failed=row["n_critical_failed"],
            error=row["error"],
            label=row["label"],
        )

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)

    @property
    def progress_pct(self) -> float:
        if self.n_total <= 0:
            return 0.0
        return round(100.0 * self.n_done / self.n_total, 1)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id                 TEXT PRIMARY KEY,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT NOT NULL,
    source_kind        TEXT NOT NULL,
    source_meta        TEXT NOT NULL DEFAULT '{}',
    output_dir         TEXT NOT NULL,
    n_total            INTEGER NOT NULL DEFAULT 0,
    n_done             INTEGER NOT NULL DEFAULT 0,
    n_errored          INTEGER NOT NULL DEFAULT 0,
    n_critical_failed  INTEGER NOT NULL DEFAULT 0,
    error              TEXT,
    label              TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
"""


class RunStore:
    """Thread-safe SQLite wrapper. One connection per process; serialised via
    an internal lock since SQLite writes don't tolerate concurrent writers."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or paths.runs_db_path()
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            con = self._connect()
            try:
                cur = con.cursor()
                yield cur
            finally:
                con.close()

    # ---- public API ----

    def create(
        self,
        *,
        run_id: str,
        source_kind: str,
        source_meta: dict[str, Any],
        output_dir: Path,
        label: str | None = None,
    ) -> RunRecord:
        now = _now_iso()
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO runs (id, started_at, status, source_kind, "
                "source_meta, output_dir, label) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    now,
                    RunStatus.PENDING,
                    source_kind,
                    json.dumps(source_meta),
                    str(output_dir),
                    label,
                ),
            )
        rec = self.get(run_id)
        assert rec is not None
        return rec

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        n_total: int | None = None,
        n_done: int | None = None,
        n_errored: int | None = None,
        n_critical_failed: int | None = None,
        error: str | None = None,
        finished: bool = False,
    ) -> None:
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if n_total is not None:
            sets.append("n_total = ?")
            params.append(n_total)
        if n_done is not None:
            sets.append("n_done = ?")
            params.append(n_done)
        if n_errored is not None:
            sets.append("n_errored = ?")
            params.append(n_errored)
        if n_critical_failed is not None:
            sets.append("n_critical_failed = ?")
            params.append(n_critical_failed)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if finished:
            sets.append("finished_at = ?")
            params.append(_now_iso())
        if not sets:
            return
        params.append(run_id)
        with self._cursor() as cur:
            cur.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", params)

    def get(self, run_id: str) -> RunRecord | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cur.fetchone()
        return RunRecord.from_row(row) if row else None

    def list(
        self,
        *,
        limit: int = 200,
        status: str | None = None,
    ) -> list[RunRecord]:
        sql = "SELECT * FROM runs"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [RunRecord.from_row(r) for r in rows]

    def delete(self, run_id: str) -> None:
        with self._cursor() as cur:
            cur.execute("DELETE FROM runs WHERE id = ?", (run_id,))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Tiny helper used by tests to create a unique run_id without colliding within
# the same second. Most callers should use new_run_id() above.
def _unique_run_id() -> str:
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"


__all__ = ["RunRecord", "RunStatus", "RunStore", "new_run_id"]
