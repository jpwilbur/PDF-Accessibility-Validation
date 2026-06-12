# Design: PDF HTTP status display + `browser_logs` source support

**Date:** 2026-06-11
**Status:** Approved (pending written-spec review)

## Summary

Two feature deltas shipping together:

- **A. Surface PDF HTTP status in HTML reports.** The final HTTP status code of
  each PDF fetch is already collected (`PdfMetadata.http_status`) but is no
  longer rendered in the HTML reports. Plumb it back into the per-PDF page and
  the batch table.

- **B. Support `browser_logs` saved reports as a PDF-URL source.** ObservePoint
  currently has a bug where PDF links are not processed into the `link` grid
  entity. As an interim workaround, affected users run a custom on-page script
  that emits a console log of the form `PDF Links:["https://…pdf", …]`. The
  saved report is then a `browser_logs` grid filtered to those log lines. The
  app should detect the saved report's `gridEntityType` and, for `browser_logs`,
  parse the `LOG_MESSAGE` column to recover the PDF URLs — then run the existing
  pipeline unchanged.

The blast radius is small. One Python file changes meaningfully
(`observepoint/client.py`), two Jinja templates get small additions
(`per_pdf.html.j2`, `batch.html.j2`), one CSS block is added (`_base.css`), and
the run-detail page surfaces the detected source mode for transparency. No model
changes, no DB schema changes, no auth/API-key changes.

## Background — confirmed data shapes

Pulled live from saved report `28159` ("PDF Links - Console Method") in account
4666 (audit `2111112`):

- `gridEntityType` is **`browser_logs`** → grid URL path segment `browser-logs`
  (underscore → hyphen, same transform the client already applies).
- The message column ID is **`LOG_MESSAGE`** (display name "Log Message"). It is
  *not* `CONSOLE_MESSAGE`.
- Each matching row's `LOG_MESSAGE` value is the bare string
  `PDF Links:[<JSON array of URL strings>]` — no timestamp or level prefix; the
  bracketed payload is valid JSON.
- The sample report returned 935 rows. URLs repeat heavily across rows, so
  dedup collapses the count substantially. Some entries are direct `*.pdf`
  links; others are SharePoint `AllItems.aspx?id=…%2Epdf` viewer URLs. The
  existing magic-byte validator already buckets anything that isn't a real PDF
  as a "Non-PDF URL", so no special handling is needed for the SharePoint case.
- The saved report's own `queryDefinition` already includes a
  `LOG_MESSAGE string_contains "PDF Links"` filter, so the grid only returns
  candidate rows. The saved report is the source of truth for *which rows* are
  in scope.

For reference, the `link`-entity path uses column ID `LINK_URL` (unchanged).

## Component design

### ObservePoint client (`src/pdf_a11y/observepoint/client.py`)

**Entity detection.** `fetch_pdf_urls_async` already reads `gridEntityType`
from the saved-report response. Classify it:

| `gridEntityType` | Mode | Column | Per-row extractor |
|---|---|---|---|
| `browser_logs` | browser_log | `LOG_MESSAGE` | `_extract_browser_log_urls` |
| anything else | link | `LINK_URL` | `_extract_link_url` |

**Critical backward-compat note.** Link-bearing reports do *not* have
`gridEntityType == "link"`. In practice they are entity types like
`web_audit_runs` (confirmed by the existing test suite, which defaults to
`web_audit_runs`) that happen to expose a `LINK_URL` column. The current code
never gates on entity type at all — it works with *any* entity exposing
`LINK_URL`. Therefore detection must be: **`browser_logs` → browser-log mode;
everything else → link mode (today's exact behavior).** There is **no allowlist
and no hard-fail on "unknown" entity types** — doing so would break every
working link report. The only new branch is the `browser_logs` one.

**Extractor helpers** replace the inline row loop:

- `_extract_link_url(raw: str) -> str | None` — current behavior: take the cell
  string, apply `_unwrap_safelinks`, return it. (Safelinks unwrap preserved.)
- `_extract_browser_log_urls(raw: str) -> list[str]` —
  1. Regex-extract the bracketed payload: `r"PDF Links:\s*(\[.*\])\s*$"`
     (anchored at end so any future prefix is tolerated).
  2. `json.loads` the matched group.
  3. Keep only `str` items that start with `http://` or `https://`.
  4. Apply `_unwrap_safelinks` to each kept URL.
  5. On regex miss, `JSONDecodeError`, or non-list payload: return `[]` and log
     at `DEBUG`. Never raise.

**Single paginator.** The existing `while True` page loop is retained. Per page,
it locates the mode's column index in `metadata.headers` and calls the right
extractor, feeding results through the existing `seen: set[str]` dedup. The
result is one flat, order-preserved `list[str]` regardless of mode.

**Mode-specific required-column check.** Today: hard-fail if no `LINK_URL`
column when headers are present. New: hard-fail if the mode's required column
(`LINK_URL` or `LOG_MESSAGE`) is absent. The browser-log message:
`"Saved report '<name>' has no Log Message column. Edit the saved-report grid to include the Log Message column and try again."`

**Result shape.** `ObservePointFetchResult` gains:

```python
entity_mode: Literal["link", "browser_log"] | None = None
```

`total_rows` keeps its meaning (grid row count). For browser-log mode that is
the console-log row count; `len(urls)` is the distinct-PDF count. Both numbers
are therefore already available to callers for the activity-log line below.

**Zero-URL diagnosis (browser-log mode only).** If the run parsed ≥1 row but
extracted 0 URLs, return a non-fatal-but-informative `error`:
`"Found <N> console-log rows but extracted 0 PDF URLs — the log format may have changed (expected 'PDF Links:[...]')."`
This is distinct from a legitimately empty report (0 rows), and gives an
actionable diagnosis instead of a silent empty run.

**Explicitly not done.** No client-side `LOG_MESSAGE contains "PDF Links"`
filter is injected — the saved report's `queryDefinition` already scopes rows,
and a client-side filter risks fighting the user's configuration. Malformed
stragglers are soft-skipped (above).

### HTTP status display

Data already collected — `PdfMetadata.http_status: int | None` (set in
`pipeline.py` from `AcquiredPdf.http_status`) and `final_url: str | None`. No
collection changes.

**Per-PDF page (`per_pdf.html.j2`).** Add one metadata `<dl>` row, immediately
after the existing `Final URL` row:

- Network source with status → the bare numeric code, e.g. `200`, `404`. No
  reason-phrase text (user preference); no `http_phrase` filter is added.
- The status reflects the *end* of any redirect chain. The existing `Final URL`
  row already communicates that a redirect happened, so no `301 → 200` chain is
  rendered — just the final status.
- Local file source (`http_status is None`) → `—`.

**Batch table (`batch.html.j2`).** Add a `Status` column between `Document` and
`Pages`:

- Sortable: `<th><button data-sort="status">Status</button></th>`; row carries
  `data-status="{{ m.http_status or 0 }}"`.
- Small colored badge `.http-badge`: 2xx green, 3xx amber, 4xx/5xx red, `—`
  grey for local/unknown.
- Errored (non-PDF) rows still render their status when present, so that when a
  user un-hides error rows they can distinguish a 404 from a "200 but returned
  HTML, not a PDF". Errored rows remain hidden by default (unchanged).

**CSS (`_base.css`).** One new block: `.http-badge` plus variants
`.http-2xx` / `.http-3xx` / `.http-4xx5xx` / `.http-none`, matching the existing
severity-pill visual language (rounded, small, bordered).

**No new run-level stat box** — status is a per-document attribute, consistent
with the project's "per-PDF only, no aggregate scoring" principle.

### Run-detail UI (`webapp/templates/run_detail.html` + runner)

**Source-mode label.** A quiet `.muted` line near the report-ID display
indicating the detected extraction mode:

- link mode → `Source: ObservePoint link report`
- browser-log mode → `Source: ObservePoint console-log report (PDF Links)`

Reads `ObservePointFetchResult.entity_mode`, threaded through the runner into
the run record / `batch.json` the same way `report_name` already is.

**Stat counter.** "URLs submitted" keeps its definition in both modes:
*distinct PDF URLs we attempted to fetch*. For browser-log mode that is the
deduped post-parse count. The row→URL collapse is surfaced in the SSE activity
log as a single line so the information isn't lost:
`Extracted <len(urls)> distinct PDF URLs from <total_rows> console-log rows`.
In link mode this line stays as it is today (or is absent). The four existing
stat boxes (URLs submitted / PDFs evaluated / Critical fails / Non-PDF URLs)
keep their meanings.

## Error handling

| Condition | Behavior |
|---|---|
| Saved-report fetch 401/404/≥400 | Existing mapping, mode-agnostic (happens before entity type is known). |
| Required column missing | Mode-specific hard-fail `error`, names the column to add. |
| Per-row parse failure (browser-log) | Soft-skip, `DEBUG` log, paginator continues. Never fatal. |
| ≥1 row parsed, 0 URLs extracted (browser-log) | Non-fatal informative `error` ("log format may have changed"). |
| HTTP-status rendering | Pure display; `None` → `—`, unknown code → number only. No new failure modes. |

## Testing

**ObservePoint client** (mocked `httpx.AsyncClient` returning canned
saved-report + grid JSON, matching the existing test pattern):

- `browser_logs` entity → extracts and dedups URLs from a multi-row
  `LOG_MESSAGE` fixture built from the three real rows captured above.
- `web_audit_runs` entity (the real link case) → unchanged behavior, defaults to
  link mode (regression guard; this is the existing default-fixture test).
- Browser-log mode, missing `LOG_MESSAGE` column → column-specific `error`.
- Per-row resilience: fixture mixing valid `PDF Links:[...]`, malformed-JSON,
  and non-matching rows → valid URLs extracted, bad rows skipped, no raise.
- Safelinks unwrap still applies in browser-log mode.
- Zero-URL diagnosis path → returns the "log format may have changed" error.
- Dedup across pages in browser-log mode.

**HTTP status rendering:**

- Per-PDF render with `http_status=200` → status row shows `200`; `None` → `—`.
- Batch render → `Status` column present, badge class matches the code band
  (2xx/3xx/4xx5xx/none).

**Gate before commit:** full `pytest`, `ruff check`, and `mypy` on the typed
modules, matching the existing dev workflow.

## Out of scope

- No new aggregate/run-level scoring.
- No UI mode-selector dropdown (auto-detect from `gridEntityType`).
- No retention of downloaded PDFs (unchanged — deleted after each run).
- No changes to the check engine, scoring, or PDF-export features.
