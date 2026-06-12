"""ObservePoint Grid API client.

Mirror of the working logic from the sibling PDFScraper (pdf_scraper.mjs):

    saved-report URL: https://api.observepoint.com/v3/reports/grid/saved/{id}
    grid URL:         https://api.observepoint.com/v3/reports/grid/{entity}

Auth:
    Authorization: <api_key>     (raw, no scheme prefix — that's how OP wants it)

Response shapes (observed in production):
    metadata.headers[i].column.columnId   == "LINK_URL" identifies the right col.
    metadata.pagination.totalCount        total rows.
    metadata.pagination.currentPageNumber 0-based page index.
    metadata.pagination.totalPageCount    total pages.
    rows[i]                               array, indexed by header position.

Outlook safelinks unwrapping is intentionally inherited from the JS scraper —
the same audited URLs may be wrapped in safelinks.protection.outlook.com for
Office 365 customers, and we want the actual destination.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

OBSERVEPOINT_BASE = "https://api.observepoint.com/v3"
DEFAULT_PAGE_SIZE = 500
DEFAULT_TIMEOUT = 60.0
LINK_URL_COLUMN_ID = "LINK_URL"
LOG_MESSAGE_COLUMN_ID = "LOG_MESSAGE"
BROWSER_LOGS_ENTITY = "browser_logs"
# Non-greedy capture of the first bracketed array after the "PDF Links:" marker.
# Not anchored at end-of-string, so a leading log-level prefix OR a trailing
# suffix around the array is tolerated. PDF URLs never contain a raw "]" (it
# would be percent-encoded), so the first "]" reliably closes the array.
_PDF_LINKS_RE = re.compile(r"PDF Links:\s*(\[.*?\])", re.DOTALL)


class ObservePointError(Exception):
    """Raised by callers that prefer exceptions over the result-object form."""


@dataclass
class ObservePointFetchResult:
    urls: list[str] = field(default_factory=list)
    """Deduplicated list of URLs from the LINK_URL column. Order preserved."""

    report_id: str = ""
    report_name: str | None = None
    grid_entity_type: str | None = None
    entity_mode: Literal["link", "browser_log"] | None = None
    """'browser_log' when the report entity is browser_logs; 'link' otherwise."""
    total_rows: int = 0

    error: str | None = None
    """If set, the result is invalid and callers must not use `urls`."""


def fetch_pdf_urls(
    api_key: str,
    report_id: str,
    *,
    base_url: str = OBSERVEPOINT_BASE,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
) -> ObservePointFetchResult:
    """Synchronous wrapper. Internally uses an async client."""
    import asyncio

    return asyncio.run(
        fetch_pdf_urls_async(
            api_key=api_key,
            report_id=report_id,
            base_url=base_url,
            page_size=page_size,
            timeout=timeout,
        )
    )


async def fetch_pdf_urls_async(
    api_key: str,
    report_id: str,
    *,
    base_url: str = OBSERVEPOINT_BASE,
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> ObservePointFetchResult:
    if not api_key.strip():
        return ObservePointFetchResult(report_id=report_id, error="API key is empty.")
    if not report_id.strip():
        return ObservePointFetchResult(report_id=report_id, error="Report ID is empty.")

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    own_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
    try:
        # --- Step 1: fetch saved report config ----------------------------
        saved_url = f"{base_url}/reports/grid/saved/{report_id}"
        try:
            saved_resp = await client.get(saved_url, headers=headers)
        except httpx.HTTPError as e:
            return ObservePointFetchResult(
                report_id=report_id,
                error=f"Could not reach ObservePoint API: {e}",
            )
        if saved_resp.status_code == 401:
            return ObservePointFetchResult(
                report_id=report_id,
                error="ObservePoint rejected the API key (HTTP 401).",
            )
        if saved_resp.status_code == 404:
            return ObservePointFetchResult(
                report_id=report_id,
                error=f"Saved report {report_id} was not found (HTTP 404).",
            )
        if saved_resp.status_code >= 400:
            return ObservePointFetchResult(
                report_id=report_id,
                error=(
                    f"ObservePoint saved-report fetch failed: HTTP "
                    f"{saved_resp.status_code} {saved_resp.reason_phrase}"
                ),
            )
        saved = saved_resp.json()
        report_name = saved.get("name")
        grid_entity_raw = saved.get("gridEntityType") or ""
        grid_entity = grid_entity_raw.replace("_", "-")
        if not grid_entity:
            return ObservePointFetchResult(
                report_id=report_id,
                report_name=report_name,
                error="Saved report response missing gridEntityType.",
            )

        entity_mode: Literal["link", "browser_log"] = (
            "browser_log" if grid_entity_raw == BROWSER_LOGS_ENTITY else "link"
        )
        required_col = (
            LOG_MESSAGE_COLUMN_ID
            if entity_mode == "browser_log"
            else LINK_URL_COLUMN_ID
        )

        query_def = saved.get("queryDefinition") or {}

        # --- Step 2: paginate through grid rows ---------------------------
        urls: list[str] = []
        seen: set[str] = set()
        link_col_idx = -1
        column_id_seen = False
        total_count = -1
        page = 0
        grid_url = f"{base_url}/reports/grid/{grid_entity}"

        while True:
            body = {**query_def, "page": page, "size": page_size}
            try:
                grid_resp = await client.post(grid_url, json=body, headers=headers)
            except httpx.HTTPError as e:
                return ObservePointFetchResult(
                    report_id=report_id,
                    report_name=report_name,
                    grid_entity_type=grid_entity_raw,
                    error=f"Grid page {page} fetch failed: {e}",
                )
            if grid_resp.status_code >= 400:
                return ObservePointFetchResult(
                    report_id=report_id,
                    report_name=report_name,
                    grid_entity_type=grid_entity_raw,
                    error=(
                        f"Grid page {page} returned HTTP "
                        f"{grid_resp.status_code} {grid_resp.reason_phrase}"
                    ),
                )
            data = grid_resp.json()
            metadata = data.get("metadata") or {}

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

            pagination = metadata.get("pagination") or {}
            total_count = int(pagination.get("totalCount", total_count))

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

            current_page = int(pagination.get("currentPageNumber", page))
            total_pages = int(pagination.get("totalPageCount", current_page + 1))
            if current_page + 1 >= total_pages:
                break
            page += 1

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
    finally:
        if own_client:
            await client.aclose()


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


def _unwrap_safelinks(url: str) -> str:
    """Office 365 safelinks wrap the original URL; unwrap to get the destination.

    Same behaviour as the sibling PDFScraper; cheap to do, no harm if not safelink.
    """
    try:
        parsed = urlparse(url)
        if "safelinks.protection.outlook.com" in (parsed.hostname or ""):
            qs = parse_qs(parsed.query)
            inner = qs.get("url", [None])[0]
            if inner:
                return unquote(inner)
    except (ValueError, TypeError):
        pass
    return url
