# Streaming PDF Cleanup + Orphaned-Cache Sweep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the app from accumulating gigabytes of downloaded PDFs by deleting each PDF immediately after it's evaluated (processing in small chunks), and sweep orphaned caches left by killed runs at startup.

**Architecture:** `Pipeline.run()` changes from download-all → eval-all → delete-all into a chunked loop (default 10/chunk): download a chunk concurrently, evaluate each PDF sequentially (unchanged), then delete each cached file right after its eval (on by default, gated by a config flag). A startup sweep removes any `runs/*/cache/` directories stranded by past hard kills.

**Tech Stack:** Python 3.12 (`itertools.batched`), pytest, ruff, mypy, uv. FastAPI web app + Typer CLI share the `Pipeline`.

**Spec:** `docs/superpowers/specs/2026-06-12-streaming-pdf-cleanup-design.md`

---

## File Structure

- `src/pdf_a11y/config.py` — **modify.** Add `chunk_size` and `delete_cache_after_eval` to `NetworkConfig`.
- `src/pdf_a11y/pipeline.py` — **modify.** Add `_delete_cached` helper; restructure `run()` into a chunked loop with per-PDF deletion.
- `src/pdf_a11y/paths.py` — **modify.** Add `sweep_orphaned_caches()`.
- `src/pdf_a11y/webapp/app.py` — **modify.** Call the sweep at startup in `create_app()`.
- `tests/test_streaming_cleanup.py` — **create.** Pipeline chunking, streaming delete, opt-out, and `_delete_cached` guard tests.
- `tests/test_paths_sweep.py` — **create.** Orphaned-cache sweep tests.

The web runner (`webapp/runner.py`) needs **no change**: it builds config via `Config.load()`, so it inherits `delete_cache_after_eval=True` automatically, and its end-of-run `finally` rmtree remains a backstop.

---

## Task 1: Config knobs

**Files:**
- Modify: `src/pdf_a11y/config.py` (the `NetworkConfig` dataclass, around lines 35–45)
- Test: `tests/test_streaming_cleanup.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_streaming_cleanup.py`:

```python
"""Tests for streaming per-PDF cache cleanup."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pdf_a11y.acquire import AcquiredPdf
from pdf_a11y.config import Config
from pdf_a11y.pipeline import Pipeline


def test_network_config_streaming_defaults() -> None:
    cfg = Config()
    assert cfg.network.chunk_size == 10
    assert cfg.network.delete_cache_after_eval is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py::test_network_config_streaming_defaults -v`
Expected: FAIL — `AttributeError: 'NetworkConfig' object has no attribute 'chunk_size'`.

- [ ] **Step 3: Add the fields**

In `src/pdf_a11y/config.py`, add to the `NetworkConfig` dataclass after the `max_bytes` field (line ~45):

```python
    chunk_size: int = 10
    """Download+evaluate PDFs in slices of this size so peak disk stays
    ~chunk_size × avg PDF instead of the whole batch."""

    delete_cache_after_eval: bool = True
    """Delete each cached PDF immediately after its evaluation so disk never
    holds more than one chunk. On by default for both the web app and the CLI.
    Set False to keep a persistent content cache for deliberate cross-run reuse."""
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py::test_network_config_streaming_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/config.py tests/test_streaming_cleanup.py
git commit -m "feat: add chunk_size + delete_cache_after_eval config knobs"
```

Do NOT add a Co-Authored-By trailer (project owner's standing instruction).

---

## Task 2: `_delete_cached` helper

**Files:**
- Modify: `src/pdf_a11y/pipeline.py` (imports near top; add method to the `Pipeline` class)
- Test: `tests/test_streaming_cleanup.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_streaming_cleanup.py`:

```python
def test_delete_cached_removes_only_files_inside_cache(tmp_path: Path) -> None:
    cfg = Config()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cfg.paths.cache_dir = cache_dir
    pipeline = Pipeline(cfg)

    # Inside the cache → deleted.
    inside = cache_dir / "abc.pdf"
    inside.write_bytes(b"%PDF-1.4\n")
    ap_inside = AcquiredPdf(source="u", local_path=inside, sha256="a", byte_size=9)
    pipeline._delete_cached(ap_inside, cache_dir)
    assert not inside.exists()

    # Outside the cache (e.g. a user's local source) → preserved.
    outside = tmp_path / "original.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    ap_outside = AcquiredPdf(source="v", local_path=outside, sha256="b", byte_size=9)
    pipeline._delete_cached(ap_outside, cache_dir)
    assert outside.exists()

    # Missing path → no error.
    ap_missing = AcquiredPdf(
        source="w", local_path=cache_dir / "nope.pdf", sha256="", byte_size=0
    )
    pipeline._delete_cached(ap_missing, cache_dir)  # must not raise

    # Download-failure row (empty Path) → no error.
    ap_empty = AcquiredPdf(source="x", local_path=Path(), sha256="", byte_size=0)
    pipeline._delete_cached(ap_empty, cache_dir)  # must not raise
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py::test_delete_cached_removes_only_files_inside_cache -v`
Expected: FAIL — `AttributeError: 'Pipeline' object has no attribute '_delete_cached'`.

- [ ] **Step 3: Add the import and the helper**

In `src/pdf_a11y/pipeline.py`, add `from pathlib import Path` to the imports (after `from datetime import UTC, date, datetime`, line ~14):

```python
from pathlib import Path
```

Then add this method to the `Pipeline` class (place it right after `_evaluate_one`, or anywhere inside the class body):

```python
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
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py::test_delete_cached_removes_only_files_inside_cache -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/pipeline.py tests/test_streaming_cleanup.py
git commit -m "feat: _delete_cached helper (only removes files inside the cache dir)"
```

---

## Task 3: Chunked `run()` with streaming delete

**Files:**
- Modify: `src/pdf_a11y/pipeline.py` (imports + the `run()` method, lines ~82–174)
- Test: `tests/test_streaming_cleanup.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_streaming_cleanup.py`:

```python
def test_streaming_delete_empties_cache(
    known_good_pdf: Path, scan_only_pdf: Path, tmp_path: Path
) -> None:
    cfg = Config()
    cfg.paths.cache_dir = tmp_path / "cache"
    cfg.network.chunk_size = 1  # force one PDF per chunk
    cfg.network.delete_cache_after_eval = True
    pipeline = Pipeline(cfg)
    sources = [str(known_good_pdf), str(scan_only_pdf)]

    batch = asyncio.run(pipeline.run(sources))

    assert len(batch.reports) == 2
    # No cached PDFs left behind.
    cache = tmp_path / "cache"
    leftover = list(cache.glob("*.pdf")) if cache.exists() else []
    assert leftover == []
    # The user's original fixture files are untouched.
    assert known_good_pdf.exists()
    assert scan_only_pdf.exists()


def test_opt_out_keeps_cached_pdfs(known_good_pdf: Path, tmp_path: Path) -> None:
    cfg = Config()
    cfg.paths.cache_dir = tmp_path / "cache"
    cfg.network.chunk_size = 10
    cfg.network.delete_cache_after_eval = False
    pipeline = Pipeline(cfg)

    batch = asyncio.run(pipeline.run([str(known_good_pdf)]))

    assert len(batch.reports) == 1
    leftover = list((tmp_path / "cache").glob("*.pdf"))
    assert len(leftover) == 1  # persistent-cache mode keeps the file
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py -k "streaming_delete or opt_out" -v`
Expected: FAIL — `test_streaming_delete_empties_cache` finds a leftover `.pdf` (deletion not wired into `run()` yet).

- [ ] **Step 3: Add the `batched` import**

In `src/pdf_a11y/pipeline.py`, add to the imports (near the other stdlib imports, after `from datetime import UTC, date, datetime`):

```python
from itertools import batched
```

- [ ] **Step 4: Restructure `run()`**

In `src/pdf_a11y/pipeline.py`, replace the body of `run()` from the `downloader = Downloader(...)` line through the `_mark_duplicates(reports)` line (currently lines ~106–152) with this. Leave the `started`/`n_total`/initial `"starting"` emit above it and the `finished`/`"finished"` emit + `return BatchReport(...)` below it unchanged.

```python
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
```

Note: the old single `acquired = await downloader.acquire_many(sources)` line and the single pre-loop `"acquiring"` emit are removed — they're replaced by the per-chunk download + emit above. The `downloader` is created once and reused across chunks.

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_streaming_cleanup.py -k "streaming_delete or opt_out" -v`
Expected: PASS (both)

- [ ] **Step 6: Run the existing e2e tests (regression guard)**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_pipeline_e2e.py -v`
Expected: PASS — chunking with the default flag still produces identical reports (the e2e test uses the default `Config()`; its `cache_dir` is set to a tmp path, so streaming delete just empties that tmp cache — reports are unaffected).

- [ ] **Step 7: Lint**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run ruff check src/pdf_a11y/pipeline.py tests/test_streaming_cleanup.py`
Expected: clean. Fix any issues inline.

- [ ] **Step 8: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/pipeline.py tests/test_streaming_cleanup.py
git commit -m "feat: chunked pipeline with streaming per-PDF cache deletion"
```

---

## Task 4: `sweep_orphaned_caches()`

**Files:**
- Modify: `src/pdf_a11y/paths.py`
- Test: `tests/test_paths_sweep.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_paths_sweep.py`:

```python
"""Tests for the startup orphaned-cache sweep."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_a11y import paths


def test_sweep_removes_cache_dirs_but_keeps_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "runs_dir", lambda: runs)

    run1 = runs / "run1"
    (run1 / "cache").mkdir(parents=True)
    (run1 / "cache" / "a.pdf").write_bytes(b"x" * 100)
    (run1 / "cache" / "b.pdf").write_bytes(b"y" * 50)
    (run1 / "summary.html").write_text("<html></html>")
    (run1 / "findings.jsonl").write_text("{}\n")

    reclaimed = paths.sweep_orphaned_caches()

    assert reclaimed >= 150
    assert not (run1 / "cache").exists()
    assert (run1 / "summary.html").exists()
    assert (run1 / "findings.jsonl").exists()


def test_sweep_no_runs_dir_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "runs_dir", lambda: tmp_path / "does-not-exist")
    assert paths.sweep_orphaned_caches() == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_paths_sweep.py -v`
Expected: FAIL — `AttributeError: module 'pdf_a11y.paths' has no attribute 'sweep_orphaned_caches'`.

- [ ] **Step 3: Implement the sweep**

In `src/pdf_a11y/paths.py`, add the logging import at the top (after `from pathlib import Path`):

```python
import logging
import shutil

logger = logging.getLogger(__name__)
```

Then add this function at the end of the file (after `ensure_dirs`):

```python
def sweep_orphaned_caches() -> int:
    """Remove every ``runs/*/cache/`` directory; return bytes reclaimed.

    Safe to call only when no run is active (e.g. at app startup): a run's
    cache is transient working space at ``runs/<id>/cache``. Report outputs
    (``pdfs/``, ``findings.jsonl``, ``summary.*``, ``batch.json``) are never
    touched. Per-directory errors are logged and skipped (best-effort).
    """
    base = runs_dir()
    if not base.exists():
        return 0
    reclaimed = 0
    for cache in base.glob("*/cache"):
        if not cache.is_dir():
            continue
        try:
            size = sum(
                f.stat().st_size for f in cache.rglob("*") if f.is_file()
            )
        except OSError:
            size = 0
        try:
            shutil.rmtree(cache)
            reclaimed += size
        except OSError as e:
            logger.warning("could not remove orphaned cache %s: %s", cache, e)
    return reclaimed
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_paths_sweep.py -v`
Expected: PASS (both)

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/paths.py tests/test_paths_sweep.py
git commit -m "feat: sweep_orphaned_caches() to reclaim caches from killed runs"
```

---

## Task 5: Wire the sweep into startup + final verification

**Files:**
- Modify: `src/pdf_a11y/webapp/app.py` (`create_app()`, around lines 71–73)

- [ ] **Step 1: Add the startup sweep call**

In `src/pdf_a11y/webapp/app.py`, locate `create_app()`. The first line is `paths.ensure_dirs()`. Immediately after it, add:

```python
    reclaimed = paths.sweep_orphaned_caches()
    if reclaimed:
        logging.getLogger(__name__).info(
            "Reclaimed %.1f MB of orphaned PDF cache from interrupted run(s)",
            reclaimed / 1_048_576,
        )
```

If `app.py` does not already `import logging` at the top, add `import logging` to its imports. (Check the top of the file; add it only if missing.)

- [ ] **Step 2: Verify the app imports and the sweep is wired**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run ruff check src/pdf_a11y/webapp/app.py && uv run python -c "from pdf_a11y.webapp import create_app; create_app(); print('create_app OK')"`
Expected: ruff clean; prints `create_app OK` (the sweep runs against the real (likely empty of orphans) runs dir without error).

- [ ] **Step 3: Full test suite**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest -q`
Expected: all pass (existing suite + the new streaming/sweep tests). If anything fails, STOP and fix before continuing.

- [ ] **Step 4: Lint + types**

Run:
```
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run ruff check src tests
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run mypy src/pdf_a11y/checks src/pdf_a11y/models.py src/pdf_a11y/scoring.py
```
Expected: ruff clean; mypy clean. Also type-check the changed files:
```
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run mypy src/pdf_a11y/pipeline.py src/pdf_a11y/paths.py src/pdf_a11y/config.py
```
Fix any errors introduced by this feature (pre-existing third-party-stub noise, if any, may be left — note it).

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/webapp/app.py
git commit -m "feat: sweep orphaned PDF caches at web app startup"
```

---

## Self-Review Notes

- **Spec coverage:** chunked `run()` (T3), `_delete_cached` guard incl. local-source safety (T2), `chunk_size`=10 + `delete_cache_after_eval`=True (T1), startup sweep (T4) wired into `create_app()` (T5), full gate (T5). Error-handling (delete failures non-fatal: T2 helper try/except; sweep per-dir skip: T4) and the opt-out path (T3) all have tasks. The web runner needs no change (inherits the default + keeps its `finally` backstop) — noted, not a task.
- **Type consistency:** `_delete_cached(self, ap: AcquiredPdf, cache_dir: Path) -> None` (T2) is called as `self._delete_cached(ap, cache_dir)` in `run()` (T3). `sweep_orphaned_caches() -> int` (T4) is called for its `int` return in `create_app()` (T5). `chunk_size: int` / `delete_cache_after_eval: bool` (T1) are read as `self.config.network.chunk_size` / `.delete_cache_after_eval` (T3).
- **No placeholders:** every code/command step is concrete.
