# PDF HTTP Status + browser_logs Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface each PDF's final HTTP status code in the HTML reports, and let the app ingest ObservePoint `browser_logs` saved reports (parsing `PDF Links:[...]` console messages) in addition to the existing `LINK_URL` link reports.

**Architecture:** The ObservePoint client (`observepoint/client.py`) detects `gridEntityType`: `browser_logs` → parse the `LOG_MESSAGE` column; everything else → existing `LINK_URL` behavior (backward-compatible default, no allowlist). Both paths emit the same deduped `list[str]` of URLs, so the downloader/pipeline/scoring are untouched. HTTP status is already collected on `FileMetadata.http_status`; the work is purely rendering it in two Jinja templates plus a CSS badge. The run-detail page surfaces the detected source mode and (for browser-log runs) the console-rows→URLs collapse, server-rendered from `source_meta` so it survives page refresh.

**Tech Stack:** Python 3.12, httpx (async + MockTransport tests), Jinja2 templates, pytest, ruff, mypy, uv.

**Spec:** `docs/superpowers/specs/2026-06-11-pdf-status-and-browser-logs-design.md`

---

## File Structure

- `src/pdf_a11y/observepoint/client.py` — **modify.** Add `entity_mode` field to `ObservePointFetchResult`; add `_extract_browser_log_urls` helper; branch the paginator on entity type; mode-specific required-column check; zero-URL diagnosis.
- `tests/test_observepoint.py` — **modify.** Add browser-log fixtures and tests; keep existing link tests as regression guards.
- `src/pdf_a11y/report/templates/per_pdf.html.j2` — **modify.** Add an `HTTP status` metadata row.
- `src/pdf_a11y/report/templates/batch.html.j2` — **modify.** Add a sortable `Status` column with a colored badge.
- `src/pdf_a11y/report/templates/_base.css` — **modify.** Add `.http-badge` style variants.
- `tests/test_report_html.py` — **create.** Render-level tests for the status row and column.
- `src/pdf_a11y/webapp/runner.py` — **modify.** Thread `entity_mode` and console-row count into `source_meta`.
- `src/pdf_a11y/webapp/templates/run_detail.html` — **modify.** Show the source-mode label and the collapse line.

---

## Task 1: Client — `entity_mode` field + browser-log happy path

**Files:**
- Modify: `src/pdf_a11y/observepoint/client.py`
- Test: `tests/test_observepoint.py`

- [ ] **Step 1: Add a browser-log fixture helper to the test file**

Add near the other helpers in `tests/test_observepoint.py` (after `_grid_page`, around line 67):

```python
def _browser_log_saved() -> dict[str, Any]:
    return {
        "id": 28159,
        "name": "PDF Links - Console Method",
        "gridEntityType": "browser_logs",
        "queryDefinition": {"columns": [], "filters": {}, "page": 0, "size": 500},
    }


def _browser_log_page(
    messages: list[str], *, page: int, total_pages: int
) -> dict[str, Any]:
    return {
        "metadata": {
            "headers": [{"column": {"columnId": "LOG_MESSAGE"}}],
            "pagination": {
                "currentPageNumber": page,
                "totalPageCount": total_pages,
                "totalCount": len(messages) + page * 2,
            },
        },
        "rows": [[m] for m in messages],
    }
```

- [ ] **Step 2: Write the failing happy-path test**

Add to `tests/test_observepoint.py`:

```python
def test_browser_logs_extracts_and_dedupes() -> None:
    """browser_logs entity: parse 'PDF Links:[...]' from LOG_MESSAGE, dedupe."""
    msg_a = (
        'PDF Links:["https://oklahoma.gov/a.pdf",'
        '"https://oklahoma.gov/b.pdf"]'
    )
    msg_b = (
        'PDF Links:["https://oklahoma.gov/b.pdf",'  # dup of msg_a
        '"https://oklahoma.gov/c.pdf"]'
    )
    routes = {
        "/reports/grid/saved/28159": _browser_log_saved(),
        "/reports/grid/browser-logs": _browser_log_page(
            [msg_a, msg_b], page=0, total_pages=1
        ),
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://api.observepoint.com"
    )
    result = _run(
        fetch_pdf_urls_async(api_key="t", report_id="28159", client=client)
    )
    assert result.error is None, result.error
    assert result.urls == [
        "https://oklahoma.gov/a.pdf",
        "https://oklahoma.gov/b.pdf",
        "https://oklahoma.gov/c.pdf",
    ]
    assert result.entity_mode == "browser_log"
    assert result.grid_entity_type == "browser_logs"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py::test_browser_logs_extracts_and_dedupes -v`
Expected: FAIL — `AttributeError: 'ObservePointFetchResult' object has no attribute 'entity_mode'` (or an assertion error on `urls`, since LINK_URL won't be found).

- [ ] **Step 4: Add the `entity_mode` field and the import**

In `src/pdf_a11y/observepoint/client.py`, update the import line (line 27 area) to add `re` and `json` and `Literal`:

```python
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse
```

Add the column constant near `LINK_URL_COLUMN_ID` (line 36):

```python
LINK_URL_COLUMN_ID = "LINK_URL"
LOG_MESSAGE_COLUMN_ID = "LOG_MESSAGE"
BROWSER_LOGS_ENTITY = "browser_logs"
_PDF_LINKS_RE = re.compile(r"PDF Links:\s*(\[.*\])\s*$", re.DOTALL)
```

Add the field to `ObservePointFetchResult` (after `grid_entity_type`, line 50):

```python
    grid_entity_type: str | None = None
    entity_mode: Literal["link", "browser_log"] | None = None
```

- [ ] **Step 5: Add the browser-log extractor helper**

Add this function in `client.py` next to `_unwrap_safelinks` (near line 232):

```python
def _extract_browser_log_urls(raw: str) -> list[str]:
    """Parse a 'PDF Links:[...]' console message into a list of PDF URLs.

    Resilient: a row that doesn't match, isn't valid JSON, or isn't a list
    yields [] (logged at DEBUG) — never raises. The saved report's own filter
    governs which rows are in scope; a malformed straggler must not sink a run.
    """
    match = _PDF_LINKS_RE.search(raw)
    if not match:
        logger.debug("browser-log row had no 'PDF Links:[...]' payload: %.80r", raw)
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.debug("browser-log row had invalid JSON payload: %s", e)
        return []
    if not isinstance(parsed, list):
        logger.debug("browser-log row payload was not a list: %.80r", raw)
        return []
    out: list[str] = []
    for item in parsed:
        if isinstance(item, str) and item.startswith(("http://", "https://")):
            out.append(_unwrap_safelinks(item))
    return out
```

- [ ] **Step 6: Branch the paginator on entity type**

In `fetch_pdf_urls_async`, after `grid_entity = grid_entity_raw.replace("_", "-")` and the empty-check (around line 133-139), add mode detection:

```python
        entity_mode: Literal["link", "browser_log"] = (
            "browser_log" if grid_entity_raw == BROWSER_LOGS_ENTITY else "link"
        )
        required_col = (
            LOG_MESSAGE_COLUMN_ID
            if entity_mode == "browser_log"
            else LINK_URL_COLUMN_ID
        )
```

Then, in the pagination loop, change the header-scan and row-extraction to use `required_col` and the mode. Replace the block that finds `link_col_idx` and the `if link_col_idx < 0 and column_id_seen` hard-fail (lines ~176-196) with:

```python
            headers_list = metadata.get("headers")
            if isinstance(headers_list, list):
                column_id_seen = True
                for i, h in enumerate(headers_list):
                    col = (h or {}).get("column") or {}
                    if col.get("columnId") == required_col:
                        link_col_idx = i
                        break

            if link_col_idx < 0 and column_id_seen:
                col_label = (
                    "Log Message" if entity_mode == "browser_log" else "Link URL"
                )
                return ObservePointFetchResult(
                    report_id=report_id,
                    report_name=report_name,
                    grid_entity_type=grid_entity_raw,
                    entity_mode=entity_mode,
                    error=(
                        f"Saved report '{report_name or report_id}' has no "
                        f"{required_col} column. Edit the saved-report grid to "
                        f"include the {col_label} column and try again."
                    ),
                )
```

Replace the row-extraction block (lines ~201-212) with a mode branch:

```python
            rows = data.get("rows")
            if isinstance(rows, list) and link_col_idx >= 0:
                for row in rows:
                    if not isinstance(row, list) or link_col_idx >= len(row):
                        continue
                    raw = row[link_col_idx]
                    if not isinstance(raw, str) or not raw:
                        continue
                    if entity_mode == "browser_log":
                        extracted = _extract_browser_log_urls(raw)
                    else:
                        extracted = [_unwrap_safelinks(raw)]
                    for url in extracted:
                        if url not in seen:
                            seen.add(url)
                            urls.append(url)
```

Finally, set `entity_mode` on the success return (line ~220):

```python
        return ObservePointFetchResult(
            urls=urls,
            report_id=report_id,
            report_name=report_name,
            grid_entity_type=grid_entity_raw,
            entity_mode=entity_mode,
            total_rows=max(total_count, 0),
        )
```

- [ ] **Step 7: Run the happy-path test to verify it passes**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py::test_browser_logs_extracts_and_dedupes -v`
Expected: PASS

- [ ] **Step 8: Run the full ObservePoint test file (regression guard)**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py -v`
Expected: PASS — all existing link tests still pass (they use `web_audit_runs`, which now maps to link mode by default).

- [ ] **Step 9: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/observepoint/client.py tests/test_observepoint.py
git commit -m "feat: support browser_logs saved reports (parse PDF Links console messages)"
```

---

## Task 2: Client — resilience, missing-column, and zero-URL diagnosis

**Files:**
- Modify: `src/pdf_a11y/observepoint/client.py`
- Test: `tests/test_observepoint.py`

- [ ] **Step 1: Write the resilience test (mixed valid/malformed rows)**

Add to `tests/test_observepoint.py`:

```python
def test_browser_logs_skips_malformed_rows() -> None:
    good = 'PDF Links:["https://oklahoma.gov/ok.pdf"]'
    bad_json = 'PDF Links:["https://oklahoma.gov/x.pdf"'  # truncated, invalid
    no_match = "Some unrelated console output with no payload"
    not_list = 'PDF Links:{"a":1}'
    routes = {
        "/reports/grid/saved/28159": _browser_log_saved(),
        "/reports/grid/browser-logs": _browser_log_page(
            [good, bad_json, no_match, not_list], page=0, total_pages=1
        ),
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://api.observepoint.com"
    )
    result = _run(
        fetch_pdf_urls_async(api_key="t", report_id="28159", client=client)
    )
    assert result.error is None, result.error
    assert result.urls == ["https://oklahoma.gov/ok.pdf"]
```

- [ ] **Step 2: Write the missing-LOG_MESSAGE-column test**

```python
def test_browser_logs_missing_log_message_column_hard_fails() -> None:
    no_col_page = {
        "metadata": {
            "headers": [{"column": {"columnId": "SOMETHING_ELSE"}}],
            "pagination": {
                "currentPageNumber": 0,
                "totalPageCount": 1,
                "totalCount": 0,
            },
        },
        "rows": [],
    }
    routes = {
        "/reports/grid/saved/28159": _browser_log_saved(),
        "/reports/grid/browser-logs": no_col_page,
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://api.observepoint.com"
    )
    result = _run(
        fetch_pdf_urls_async(api_key="t", report_id="28159", client=client)
    )
    assert result.error is not None
    assert "LOG_MESSAGE" in result.error
    assert result.entity_mode == "browser_log"
```

- [ ] **Step 3: Write the zero-URL diagnosis test**

```python
def test_browser_logs_zero_urls_returns_diagnosis() -> None:
    """Rows present but none parse to URLs → actionable diagnosis error."""
    routes = {
        "/reports/grid/saved/28159": _browser_log_saved(),
        "/reports/grid/browser-logs": _browser_log_page(
            ["totally different log format", "another non-matching line"],
            page=0,
            total_pages=1,
        ),
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://api.observepoint.com"
    )
    result = _run(
        fetch_pdf_urls_async(api_key="t", report_id="28159", client=client)
    )
    assert result.error is not None
    assert "0 PDF URLs" in result.error
    assert result.urls == []
```

- [ ] **Step 4: Run the three tests to verify failure**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py -k "malformed or missing_log_message or zero_urls" -v`
Expected: `malformed` and `missing_log_message` PASS already (Task 1 covers them); `zero_urls` FAILS — `result.error` is `None` because the paginator returns success with empty `urls`.

- [ ] **Step 5: Add the zero-URL diagnosis to the success return**

In `fetch_pdf_urls_async`, replace the success-return block (added in Task 1 Step 6) so it checks for the browser-log zero-URL case first:

```python
        if entity_mode == "browser_log" and total_count > 0 and not urls:
            return ObservePointFetchResult(
                report_id=report_id,
                report_name=report_name,
                grid_entity_type=grid_entity_raw,
                entity_mode=entity_mode,
                total_rows=max(total_count, 0),
                error=(
                    f"Found {total_count} console-log rows but extracted 0 PDF "
                    f"URLs — the log format may have changed (expected "
                    f"'PDF Links:[...]')."
                ),
            )

        return ObservePointFetchResult(
            urls=urls,
            report_id=report_id,
            report_name=report_name,
            grid_entity_type=grid_entity_raw,
            entity_mode=entity_mode,
            total_rows=max(total_count, 0),
        )
```

Note: `total_count` is derived from `pagination.totalCount`. In `_browser_log_page` the fixture sets `totalCount = len(messages)`, so two non-matching rows give `total_count == 2 > 0` with `urls == []`, triggering the diagnosis.

- [ ] **Step 6: Run the three tests to verify they pass**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py -k "malformed or missing_log_message or zero_urls" -v`
Expected: PASS (all three)

- [ ] **Step 7: Run the full ObservePoint file**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_observepoint.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/observepoint/client.py tests/test_observepoint.py
git commit -m "feat: browser_logs resilience — skip malformed rows, diagnose zero-URL runs"
```

---

## Task 3: Per-PDF HTML — HTTP status row

**Files:**
- Modify: `src/pdf_a11y/report/templates/per_pdf.html.j2`
- Create: `tests/test_report_html.py`

- [ ] **Step 1: Create the render-test file with a minimal-report helper and the per-PDF status test**

Create `tests/test_report_html.py`:

```python
"""Render-level tests for HTTP status display in HTML reports."""

from __future__ import annotations

from datetime import datetime, timezone

from pdf_a11y.models import (
    BatchReport,
    FileMetadata,
    PdfReport,
    Score,
    ToolVersions,
)
from pdf_a11y.report import render_batch_html, render_pdf_html

_NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)
_TOOLS = ToolVersions(pdf_a11y="9.9.9", python="3.12")


def _report(*, http_status: int | None, sha: str = "a" * 64) -> PdfReport:
    meta = FileMetadata(
        source="https://example.com/doc.pdf",
        local_path="/tmp/doc.pdf",
        sha256=sha,
        byte_size=1234,
        http_status=http_status,
        page_count=3,
        has_tagged_structure=True,
    )
    score = Score(raw_penalty=0, max_penalty=100, score_pct=95.0, grade="A")
    return PdfReport(
        metadata=meta,
        score=score,
        check_results=[],
        findings=[],
        tool_versions=_TOOLS,
        started_at=_NOW,
        finished_at=_NOW,
        duration_ms=1.0,
    )


def test_per_pdf_shows_numeric_http_status() -> None:
    html = render_pdf_html(_report(http_status=200))
    assert "HTTP status" in html
    assert ">200<" in html


def test_per_pdf_shows_dash_for_missing_status() -> None:
    html = render_pdf_html(_report(http_status=None))
    assert "HTTP status" in html
    # The status row renders an em-dash when there's no network status.
    assert "HTTP status" in html and "—" in html
```

- [ ] **Step 2: Run the per-PDF tests to verify failure**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_report_html.py -k per_pdf -v`
Expected: FAIL — `"HTTP status" in html` is False (the row doesn't exist yet).

- [ ] **Step 3: Add the HTTP status row to the template**

In `src/pdf_a11y/report/templates/per_pdf.html.j2`, insert after the `Final URL` row (after line 31, the `{% endif %}` that closes the final-url block):

```jinja
      <dt>HTTP status</dt>     <dd>{{ report.metadata.http_status if report.metadata.http_status is not none else '—' }}</dd>
```

- [ ] **Step 4: Run the per-PDF tests to verify they pass**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_report_html.py -k per_pdf -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/report/templates/per_pdf.html.j2 tests/test_report_html.py
git commit -m "feat: show final HTTP status on per-PDF report"
```

---

## Task 4: Batch HTML — sortable Status column + CSS badge

**Files:**
- Modify: `src/pdf_a11y/report/templates/batch.html.j2`
- Modify: `src/pdf_a11y/report/templates/_base.css`
- Test: `tests/test_report_html.py`

- [ ] **Step 1: Add a batch helper and the batch-column test**

Append to `tests/test_report_html.py`:

```python
def _batch(reports: list[PdfReport]) -> BatchReport:
    return BatchReport(
        started_at=_NOW,
        finished_at=_NOW,
        reports=reports,
        tool_versions=_TOOLS,
    )


def test_batch_has_status_column_header() -> None:
    batch = _batch([_report(http_status=200)])
    html = render_batch_html(batch, {("a" * 64): "pdfs/aaa.html"})
    assert 'data-sort="status"' in html
    assert ">Status<" in html


def test_batch_status_badge_class_by_band() -> None:
    reports = [
        _report(http_status=200, sha="2" * 64),
        _report(http_status=404, sha="4" * 64),
    ]
    html = render_batch_html(_batch(reports), {})
    assert "http-2xx" in html
    assert "http-4xx5xx" in html


def test_batch_status_dash_for_local_source() -> None:
    html = render_batch_html(_batch([_report(http_status=None, sha="0" * 64)]), {})
    assert "http-none" in html
```

- [ ] **Step 2: Run the batch tests to verify failure**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_report_html.py -k batch -v`
Expected: FAIL — no `data-sort="status"` / `http-2xx` in the output yet.

- [ ] **Step 3: Add the Status column header**

In `src/pdf_a11y/report/templates/batch.html.j2`, add a header cell immediately after the `Document` header (`<th>Document …</th>`, line 63). Insert on the next line:

```jinja
      <th><button type="button" data-sort="status">Status</button></th>
```

- [ ] **Step 4: Add `data-status` to the row and the Status cell**

In the same file, add `data-status` to the `<tr>` data attributes (after `data-score=...`, around line 93):

```jinja
        data-status="{{ m.http_status or 0 }}"
```

Then add the Status `<td>` immediately after the closing `</td>` of the Document cell (after line 122, the `</td>` that ends the document/source block) and before the Pages `<td>` (line 123). Insert:

```jinja
        <td>
          {% if m.http_status is none %}
            <span class="http-badge http-none">—</span>
          {% elif m.http_status < 300 %}
            <span class="http-badge http-2xx">{{ m.http_status }}</span>
          {% elif m.http_status < 400 %}
            <span class="http-badge http-3xx">{{ m.http_status }}</span>
          {% else %}
            <span class="http-badge http-4xx5xx">{{ m.http_status }}</span>
          {% endif %}
        </td>
```

- [ ] **Step 5: Add the CSS badge styles**

In `src/pdf_a11y/report/templates/_base.css`, add after the `a.pdf-dl` block (after line 158):

```css
.http-badge {
  display: inline-block;
  min-width: 2.4rem;
  text-align: center;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  font-size: 0.85em;
  font-weight: 600;
  border: 1px solid transparent;
}
.http-2xx     { background: #e2f3e8; color: #1a6f3c; border-color: #b6ddc4; }
.http-3xx     { background: #fef0d6; color: #7a4a00; border-color: #f1d8a3; }
.http-4xx5xx  { background: #fde8e8; color: #7a1212; border-color: #f5b5b5; }
.http-none    { background: #f0f0f0; color: #2c2c2c; border-color: #c8c8c8; }
```

- [ ] **Step 6: Run the batch tests to verify they pass**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_report_html.py -k batch -v`
Expected: PASS

- [ ] **Step 7: Run the whole render-test file**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest tests/test_report_html.py -v`
Expected: PASS (per-PDF + batch tests)

- [ ] **Step 8: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/report/templates/batch.html.j2 src/pdf_a11y/report/templates/_base.css tests/test_report_html.py
git commit -m "feat: sortable HTTP status column with colored badge on batch report"
```

---

## Task 5: Runner + run-detail — source-mode label and console-rows collapse

**Files:**
- Modify: `src/pdf_a11y/webapp/runner.py:154-173`
- Modify: `src/pdf_a11y/webapp/templates/run_detail.html:20-27`

This task is UI plumbing through `source_meta`; it is verified manually (the SSE/runner threading isn't unit-tested in the existing suite). No new automated test.

- [ ] **Step 1: Thread `entity_mode` and console-row count into `source_meta`**

In `src/pdf_a11y/webapp/runner.py`, in `start_observepoint`, extend the `source_meta` dict passed to `self._start` (lines 163-168) to include the new fields:

```python
            source_meta={
                "report_id": report_id,
                "report_name": result.report_name,
                "grid_entity_type": result.grid_entity_type,
                "entity_mode": result.entity_mode,
                "console_log_rows": result.total_rows,
                "n_urls": len(result.urls),
            },
```

(`result.total_rows` is the grid row count — for browser-log mode that's the console-log row count; for link mode it's the link-row count and simply won't be shown.)

- [ ] **Step 2: Render the source-mode label and collapse line**

In `src/pdf_a11y/webapp/templates/run_detail.html`, replace the ObservePoint branch of the Source block (lines 22-23) with:

```jinja
        {% if run.source_kind == 'observepoint' %}
          {% if run.source_meta.entity_mode == 'browser_log' %}
            ObservePoint console-log report (PDF Links) #{{ run.source_meta.report_id }}{% if run.source_meta.report_name %} — {{ run.source_meta.report_name }}{% endif %}
            {% if run.source_meta.console_log_rows %}
              <br><span class="muted">Extracted {{ run.source_meta.n_urls }} distinct PDF URLs from {{ run.source_meta.console_log_rows }} console-log rows</span>
            {% endif %}
          {% else %}
            ObservePoint link report #{{ run.source_meta.report_id }}{% if run.source_meta.report_name %} — {{ run.source_meta.report_name }}{% endif %}
          {% endif %}
```

(Leave the existing `{% else %}` Manual branch and closing `{% endif %}` intact.)

- [ ] **Step 3: Verify Python still imports and lints**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run ruff check src/pdf_a11y/webapp/runner.py && uv run python -c "import pdf_a11y.webapp.runner"`
Expected: no lint errors, clean import.

- [ ] **Step 4: Manual smoke check of the template (no live server needed)**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run python -c "
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
d = Path('src/pdf_a11y/webapp/templates')
env = Environment(loader=FileSystemLoader(str(d)))
t = env.get_template('run_detail.html')
class O: pass
run = O()
run.source_kind='observepoint'; run.label='x'; run.id='r1'
run.started_at='t'; run.finished_at=None
run.source_meta={'report_id':'28159','report_name':'PDF Links','entity_mode':'browser_log','console_log_rows':935,'n_urls':412}
html = t.render(run=run, summary_exists=False)
assert 'console-log report' in html
assert '412 distinct PDF URLs from 935' in html
print('OK')
"`
Expected: prints `OK` (template renders the browser-log label and collapse line). If the template references other undefined globals, pass them similarly — the assertions are what matter.

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add src/pdf_a11y/webapp/runner.py src/pdf_a11y/webapp/templates/run_detail.html
git commit -m "feat: show ObservePoint source mode and console-row collapse on run page"
```

---

## Task 6: Full verification gate + README note

**Files:**
- Modify: `README.md` (one short note under the existing report description, optional but recommended)

- [ ] **Step 1: Run the full test suite**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run pytest -q`
Expected: all tests pass (existing 79 + new browser-log + render tests).

- [ ] **Step 2: Run the linter**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run ruff check src tests`
Expected: no errors. (If ruff flags the regex `re.DOTALL` import order or unused imports, fix inline.)

- [ ] **Step 3: Run the type checker**

Run: `cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility" && uv run mypy src/pdf_a11y/checks src/pdf_a11y/models.py src/pdf_a11y/scoring.py`
Expected: no errors. (The client isn't in the strict-typed set per the README's mypy command, but if it were, `entity_mode: Literal[...]` and the helper are fully annotated.)

- [ ] **Step 4: Add a short README note about console-log reports**

In `README.md`, under the "Set up the saved report" section (around line 131-143), add a paragraph after the numbered list:

```markdown
> **Using a console-log report instead.** If ObservePoint isn't resolving your
> PDFs into the Link URL column, you can instead point the app at a
> `browser_logs` saved report: run an audit whose on-page action console-logs
> the PDF links as `PDF Links:["https://…","https://…"]`, then save a report on
> the **Browser Logs** grid with the **Log Message** column, filtered to rows
> containing `PDF Links`. Paste that report's ID — the app auto-detects the
> console-log format and extracts the PDF URLs the same way.
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git add README.md
git commit -m "docs: explain console-log (browser_logs) saved-report option"
```

- [ ] **Step 6: Push**

```bash
cd "/Users/jarrodwilbur/Documents/PDF Scraping/PDFAccessibility"
git push origin main
```

---

## Self-Review Notes

- **Spec coverage:** browser_logs detection (T1), extractor + dedup (T1), resilience/soft-skip (T2), missing-column (T1/T2), zero-URL diagnosis (T2), `entity_mode` field (T1), HTTP status per-PDF (T3), HTTP status batch column + badge (T4), source-mode label + collapse line (T5), test suite/lint/types gate (T6). All spec sections map to a task.
- **Deviation from spec (deliberate):** the console-rows→URLs collapse is **server-rendered on the run-detail page** (T5) rather than streamed as an SSE line. Rationale: SSE log lines don't persist across page refresh (a documented limitation in the README troubleshooting section), whereas `source_meta` rendering does. This better satisfies the spec's actual intent ("surface the info, don't lose it"). The "URLs submitted" stat definition is unchanged.
- **Type consistency:** `entity_mode` is `Literal["link", "browser_log"]` everywhere (field, local var, source_meta key, template comparison `== 'browser_log'`). Column constant `LOG_MESSAGE_COLUMN_ID = "LOG_MESSAGE"`; entity sentinel `BROWSER_LOGS_ENTITY = "browser_logs"`. Helper `_extract_browser_log_urls(raw: str) -> list[str]`.
- **No placeholders:** every code/step block contains the actual content.
