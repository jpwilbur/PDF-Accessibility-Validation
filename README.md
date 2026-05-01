# pdf-a11y

A local web app + CLI for batch PDF accessibility evaluation. Pulls a list of
PDF URLs from an ObservePoint saved report (or a manual list), downloads each,
runs every PDF through PDF/UA-1 (veraPDF), Matterhorn, WCAG 2.1 A/AA, Section
508, and HHS-checklist checks, and produces a remediation-focused HTML report
per document. A history page lets you re-open earlier runs.

Per-PDF scores only — there is no aggregate run-level score, by design.

## Quickstart (current development setup)

You already have what you need on this machine. To run:

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
uv run pdf-a11y serve
```

That:
1. Boots a local FastAPI server on `http://127.0.0.1:8765/`
2. Auto-opens your browser
3. Stores everything (run history, cache, settings) under
   `~/Library/Application Support/pdf-a11y/` on macOS

Stop with `Ctrl+C`.

### What you can do in the browser

- **Run new** — paste an ObservePoint API key + saved report ID and click
  "Start run". The saved report **must** include a `LINK_URL` column. There's
  also a "Paste URLs / paths" tab if you'd rather drop a list directly.
- **History** — every run is recorded with status, counts, and a link to its
  HTML report. Delete unwanted runs from there.
- **Run detail** — live progress while running (status pill, progress bar,
  per-PDF event log), then the full report appears in an iframe when it's
  done. Direct links to `summary.html`, `findings.jsonl`, `summary.csv`.

### CLI commands (still available)

```bash
pdf-a11y serve                                # web app (default 127.0.0.1:8765)
pdf-a11y evaluate <urls-or-files>             # one-shot CLI run
pdf-a11y evaluate --op-report-id 12345 \      # ObservePoint via CLI
                  --op-api-key XXX
pdf-a11y list-checks [--prefix PDFUA]         # show registered checks
pdf-a11y gen-docs                             # regenerate docs/checks.md
```

## Standards covered

- PDF/UA-1 (ISO 14289-1) — via veraPDF, ~30 mapped rules + catch-all
- Matterhorn Protocol — via veraPDF rule mapping
- WCAG 2.1 A and AA, WCAG 2.2 deltas
- Section 508 (Revised, 2018)
- HHS PDF Accessibility Checklist
- Plus our own SEM-* (alt-text quality, heading sequence, has-H1, link text)
  and VIS-001 (color contrast, heuristic).

Run `pdf-a11y list-checks` for the full list. `docs/checks.md` and
`docs/standards-mapping.md` are auto-generated catalogs.

## Scoring (per PDF only)

```
raw_penalty = sum(weight × occurrence_count) for triggered findings
              (per check, capped at 10 occurrences)
max_penalty = sum(weight) for applicable checks
score_pct   = max(0, 100 × (1 − raw_penalty / max_penalty))
```

Severity weights default to Critical=10, Major=4, Minor=1, Warning=0
(tunable in `weights.yaml`). Three checks force a critical-fail (grade F):
untagged document (`STRUCT-001`), accessibility-blocking encryption
(`STRUCT-005`), scan-only with no text layer (`STRUCT-008`).

## Where the data lives

Everything stays on your machine, under `platformdirs`:

| OS        | Path |
|-----------|------|
| macOS     | `~/Library/Application Support/pdf-a11y/` |
| Linux     | `~/.local/share/pdf-a11y/` |
| Windows   | `%LOCALAPPDATA%\pdf-a11y\` |

That directory contains:
- `runs.db` — SQLite index of every run
- `runs/<run_id>/` — each run's `summary.html`, `summary.csv`,
  `findings.jsonl`, and per-PDF reports
- `cache/` — downloaded PDFs (deduped by SHA-256)
- `settings.json` — your saved API key and last-used report ID
  (stored in plaintext per your spec; mode 0o600 on macOS/Linux)

Delete the directory to wipe everything.

## System dependencies

These are required for full functionality. The home page shows a green/red
status panel for each.

- **veraPDF** — PDF/UA-1 conformance checking. Without it, ~33 PDFUA-* checks
  skip and the document only gets the structural / semantic / contrast checks.
- **Java** — required by veraPDF.
- **Tesseract** — optional, used to confirm scan-only PDFs via OCR. Without
  it, scan detection falls back to a heuristic.

### Mac

Already done on this machine. Anyone fresh:

```bash
brew install verapdf openjdk tesseract uv
```

### Windows

Not yet automated — see the home-page hint when running on Windows. Manual
install: `winget install EclipseAdoptium.Temurin.21.JDK`,
`winget install UB-Mannheim.TesseractOCR`, and download the veraPDF Windows
installer from <https://github.com/veraPDF/veraPDF-apps/releases>.

## Status of this iteration

Done:
- M1 — pipeline, downloader, structural checks, scoring, reports
- M2 — PDFScraper-superset metadata columns, veraPDF integration, dedup
- M3 — structure-tree walk + SEM checks (alt quality, headings, link text)
- M4 — VIS-001 contrast (heuristic), auto-generated docs
- M5 — ObservePoint client, run history, web app, `serve` command

Not yet done in this iteration:
- Windows bootstrap script (manual install per above for now)
- Push to GitHub repo (deferred to next iteration per your call)
- One-line `uvx --from git+...` install (depends on remote repo)

## Development

```bash
make test          # 79 tests
make lint          # ruff
make typecheck     # mypy --strict on checks/, models.py, scoring.py
```

Test fixtures (real-world good/bad PDFs from W3C, US gov, consumer sources)
live in `tests/fixtures/`. The synthetic ones (scan-only, low-contrast) are
generated on first test run.
