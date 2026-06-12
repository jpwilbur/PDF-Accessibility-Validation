# Design: Streaming per-PDF cleanup + orphaned-cache sweep

**Date:** 2026-06-12
**Status:** Approved (pending written-spec review)

## Problem

The web app's `runs/<id>/cache/` accumulated **6.7 GB** on a real machine. Two
distinct causes:

1. **Whole-batch-on-disk during a run.** `Pipeline.run()` downloads *every* PDF
   up front (`downloader.acquire_many(all sources)`), evaluates them all, then
   deletes the cache only at the very end. Peak disk = the entire batch (6.3 GB
   for a 3,677-PDF run), even though evaluation only needs one PDF at a time.

2. **Killed/crashed runs orphan their entire cache forever.** The cache cleanup
   is a `finally` block in the runner's worker thread (`runner.py`) that
   `rmtree`s `cache/` only when the run *finishes*. A hard process kill
   (Ctrl+C mid-run, crash, OOM) skips the `finally`, stranding the whole cache.
   This was 94% of the observed disk usage.

## Scope

PDF bytes only. Report artifacts (`pdfs/` HTML, `findings.jsonl`, `summary.*`)
keep their current retained behavior with manual per-run delete via History —
out of scope here.

## Solution overview

- **Chunked streaming in `Pipeline.run()`** — process `sources` in slices of
  `chunk_size` (default 10): download the chunk concurrently, evaluate each PDF
  (sequential, unchanged), then delete each cached file immediately after its
  evaluation (on by default). Peak disk drops to ~`chunk_size × avg PDF`
  (≈17 MB at 10).
- **Startup orphan sweep** — at app startup, remove every `runs/*/cache/`
  directory. Safe because no run is active at startup; reclaims orphans left by
  past hard kills/crashes.

These compose: streaming delete bounds disk during normal operation and shrinks
a killed run's leak to at most the in-flight chunk; the startup sweep mops up
anything a hard kill still managed to strand.

## Component design

### 1. Chunked pipeline (`src/pdf_a11y/pipeline.py`)

`Pipeline.run()` is restructured from *download-all → eval-all → delete-all* to:

```
for chunk_indices in batches(range(len(sources)), chunk_size):
    chunk_sources = [sources[i] for i in chunk_indices]
    acquired = await downloader.acquire_many(chunk_sources)   # concurrent within chunk
    for offset, ap in zip(chunk_indices, acquired):
        report = self._evaluate_one(sources[offset], ap, user_metadata[offset])
        reports.append(report)
        # update counters + emit "evaluating" progress (n_done across whole batch)
        if self.config.network.delete_cache_after_eval:
            self._delete_cached(ap, cache_dir)
_mark_duplicates(reports)
```

**Deletion is on by default, with an opt-out.** Per-PDF deletion after
evaluation is controlled by a `delete_cache_after_eval` flag that **defaults to
`True`** — both the web app and the CLI stream-delete by default, so neither
accumulates PDF bytes. The flag exists as a config-level opt-out (and a test
seam): setting it `False` restores a persistent content cache for callers who
deliberately want cross-run reuse. The web runner relies on the default; no
caller needs to set it `True` explicitly.

- `_evaluate_one` and the `ProgressEvent` emission are **unchanged**. `n_done`
  still counts across the whole batch, so the progress bar advances smoothly
  chunk by chunk (incidentally removing the old "stuck at 0% during one giant
  download phase" UX).
- Chunking uses `itertools.batched` (Python 3.12) over indices, or equivalent
  slicing, so `sources` and `user_metadata` stay aligned by index.
- `cache_dir` is obtained from `self.config.paths.cache_dir` (the runner sets
  this to `output_dir/cache` per run).
- A per-chunk `"acquiring"` progress event MAY be emitted with a message like
  `Downloading chunk k/N…`; the primary progress signal remains the per-PDF
  `"evaluating"` events.

**`_delete_cached(ap: AcquiredPdf, cache_dir: Path) -> None`** — new private
helper. Deletes `ap.local_path` only when **both** hold:

1. `ap.local_path` exists and is a file, and
2. `ap.local_path.is_relative_to(cache_dir)`.

Rationale for (2): for local-file sources the downloader copies the user's file
*into* the cache and sets `local_path` to that cache copy, so deletion targets
the copy, never the user's original. The guard makes that explicit and also
no-ops cleanly on download-failure rows where `local_path` is an empty `Path()`.
On `OSError`, log a warning and continue — a failed delete must never fail the
run.

### 2. Config (`src/pdf_a11y/config.py`)

Add to `NetworkConfig`:

```python
chunk_size: int = 10
"""Download+evaluate PDFs in slices of this size so peak disk stays
~chunk_size × avg PDF instead of the whole batch."""

delete_cache_after_eval: bool = True
"""Delete each cached PDF immediately after its evaluation so disk never holds
more than one chunk. On by default for both the web app and the CLI. Set False
to keep a persistent content cache for deliberate cross-run reuse."""
```

`Pipeline.run()` reads `self.config.network.chunk_size` and
`self.config.network.delete_cache_after_eval`. A `chunk_size <= 0` is treated as
"all sources in one chunk" defensively (avoids `itertools.batched`'s `ValueError`
on `n < 1`), though the default is 10.

No caller needs to set `delete_cache_after_eval` — both entry points use the
`True` default. The web runner continues to set
`config.paths.cache_dir = output_dir/cache` so deletions target the ephemeral
per-run cache.

### 3. Startup orphan sweep (`src/pdf_a11y/paths.py` + `webapp/app.py`)

New function in `paths.py`:

```python
def sweep_orphaned_caches() -> int:
    """Remove every runs/*/cache/ directory and return bytes reclaimed.

    Safe to call only when no run is active (e.g. at app startup): a run's
    cache lives at runs/<id>/cache and is transient working space. Report
    outputs (pdfs/, findings.jsonl, summary.*, batch.json) are never touched.
    """
```

- Globs `runs_dir().glob("*/cache")`, sums sizes for the return value, `rmtree`s
  each. Per-directory `OSError` is logged and skipped (best-effort).
- Called from `create_app()` immediately after `paths.ensure_dirs()`. Logs a
  single info line when it reclaims a non-zero amount, e.g.
  `Reclaimed 6.3 GB of orphaned PDF cache from N interrupted run(s)`.
- Only `cache` directories are matched, so report artifacts are never at risk.

## Accepted trade-offs

- **Duplicate re-download.** Deleting after evaluation means a PDF whose
  identical content reappears in a *later* chunk re-downloads (the content cache
  no longer has it). Duplicate *marking* is unaffected — `_mark_duplicates`
  works on `sha256` in report metadata, not on files. Net effect: a little extra
  bandwidth in exchange for bounded disk. Acceptable.
- **Slight network idle.** While a chunk evaluates, downloads pause. Negligible
  for this use case and far simpler than an async producer/consumer.

## Error handling

| Condition | Behavior |
|---|---|
| Download failure (`ap.error`, empty `local_path`) | `_evaluate_one` yields an error report (unchanged); `_delete_cached` no-ops (path doesn't exist / not under cache_dir). |
| `_delete_cached` `OSError` | Log warning, continue. Never fails the run. |
| Exception mid-chunk | Propagates as today; the runner's end-of-run `finally` still `rmtree`s the whole `cache/` as a backstop. |
| Hard process kill mid-run | At most the in-flight chunk's files leak; the next startup sweep reclaims them. |
| Per-cache-dir error during sweep | Logged and skipped; sweep continues with the rest. |

## Testing

**Pipeline (`tests/`):**
- Chunked run with `chunk_size=2` (deletion on by default) over local PDF
  fixtures: all reports produced and correct, and `cache_dir` contains no `.pdf`
  files at the end.
- Opt-out: same run with `delete_cache_after_eval=False` leaves the cached
  `.pdf` files in `cache_dir` (persistent-cache mode) and still produces correct
  reports.
- `_delete_cached`: deletes a file inside `cache_dir`; no-ops on a path **outside**
  `cache_dir` (the file survives); no-ops on a non-existent path; swallows
  `OSError`.
- Local-source safety: a run over a local-path source leaves the user's original
  file on disk (only the in-cache copy is deleted), even with the flag on.
- `chunk_size` larger than the source count behaves identically to one chunk.

**Orphan sweep:**
- Given a fake `runs/<id>/cache/` with a dummy file plus a sibling run dir
  holding `summary.html`/`findings.jsonl` and no cache: `sweep_orphaned_caches()`
  removes the `cache/` dir, returns a positive byte count, and leaves the report
  files untouched.
- No `runs/` dir or no caches present → returns 0, no error.

**Gate:** full `pytest`, `ruff check src tests`, `mypy` standard set.

## Out of scope

- Report-artifact retention / auto-pruning of old runs (separate concern).
- Async producer/consumer download pipeline (chunking is sufficient).
- Changes to scoring, checks, or the ObservePoint client.
