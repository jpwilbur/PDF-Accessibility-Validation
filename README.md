# pdf-a11y

Production-grade, batch PDF accessibility evaluator. Takes a list of PDF URLs (or local
files), downloads them, runs a battery of accessibility checks against PDF/UA-1,
Matterhorn Protocol, WCAG 2.1/2.2, Section 508, and the HHS PDF Accessibility
Checklist, and produces a weighted score plus a remediation-focused HTML report
per document and a sortable batch summary.

This tool **evaluates and reports**. It does not remediate.

## Quick start

```bash
# 1. Install (requires uv)
make install

# 2. Evaluate a single URL
uv run pdf-a11y evaluate https://example.gov/document.pdf

# 3. Evaluate a list, with metadata pass-through
echo 'url,owner,department
https://example.gov/a.pdf,jane@example.com,Comms
https://example.gov/b.pdf,john@example.com,Legal' > urls.csv

uv run pdf-a11y evaluate urls.csv --output-dir ./reports/

# 4. Open the report
open ./reports/summary.html
```

## CLI

- `pdf-a11y evaluate <inputs>` — evaluate one or more PDFs. Inputs can be:
  - URLs (`https://…`)
  - Local files (`./doc.pdf`)
  - Directories (recursively scans for `*.pdf`)
  - `.txt` / `.list` files (one URL per line, `#` comments allowed)
  - `.csv` files (must include a `url` column; other columns pass through as metadata)
- `pdf-a11y list-checks [--category <c>] [--prefix <p>]` — show registered checks,
  optionally filtered by category (Structure, Semantics, Visual, ...) or check-id prefix.
- `pdf-a11y gen-docs [--docs-dir docs]` — regenerate `docs/checks.md` and
  `docs/standards-mapping.md` from the current registry.

Use `--concurrency` to override download parallelism (default 3, kept low to avoid bot
detection on shared hosts). Use `--weights weights.yaml` to tune severity weights.

## Outputs

For each run, `--output-dir` will contain:

- `summary.html` — sortable, filterable batch report
- `summary.csv` — one row per PDF, severity counts, score, grade, error
- `findings.jsonl` — one JSON record per finding, ready for downstream tooling
- `pdfs/<sha12>.html` — per-PDF detailed report (also JSON sibling for machine use)

## Standards covered

- PDF/UA-1 (ISO 14289-1)
- Matterhorn Protocol v1.1
- WCAG 2.1 A and AA, WCAG 2.2 additions
- Section 508 (Revised, 2018)
- HHS PDF Accessibility Checklist

Every finding cites at least one clause. Checks classified as **Heuristic** flag
specific items for manual verification; checks classified as **Manual** are not
auto-failed — they are surfaced only when an automated signal warrants it, since
this is a lab evaluator, not a stand-in for an accessibility auditor.

## Scoring

```
raw_penalty = sum(weight × occurrence_count) for triggered findings
max_penalty = sum(weight) for applicable checks
score_pct   = max(0, 100 × (1 − raw_penalty / max_penalty))
```

Default severity weights: Critical=10, Major=4, Minor=1, Warning=0. Tune in
`weights.yaml`. Three checks trigger a critical-fail override (force grade F):
untagged document (`STRUCT-001`), accessibility-blocking encryption (`STRUCT-005`),
and scan-only document with no text layer (`STRUCT-008`).

## Development

```bash
make test       # pytest
make lint       # ruff check + format check
make typecheck  # mypy
make check      # all of the above
```

Test fixtures (real-world good/bad PDFs from W3C, US government, and consumer
sources) live in `tests/fixtures/`. Run fixtures-only tests with
`uv run pytest -m "not slow"`.

## Status

Milestone 1 (current): CLI, async downloader with cache + magic-byte validation,
six structural checks (STRUCT-001/002/003/005/006/008), scoring engine,
per-PDF and batch HTML reports, JSONL + CSV.

Roadmap: veraPDF subprocess adapter (PDF/UA + Matterhorn coverage),
semantic checks (alt text, headings, lists, tables, links), text/language
checks, color contrast, forms, navigation, multimedia.
