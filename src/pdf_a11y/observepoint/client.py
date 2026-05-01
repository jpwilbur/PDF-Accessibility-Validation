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

import logging
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

OBSERVEPOINT_BASE = "https://api.observepoint.com/v3"
DEFAULT_PAGE_SIZE = 500
DEFAULT_TIMEOUT = 60.0
LINK_URL_COLUMN_ID = "LINK_URL"


class ObservePointError(Exception):
    """Raised by callers that prefer exceptions over the result-object form."""


@dataclass
class ObservePointFetchResult:
    urls: list[str] = field(default_factory=list)
    """Deduplicated list of URLs from the LINK_URL column. Order preserved."""

    report_id: str = ""
    report_name: str | None = None
    grid_entity_type: str | None = None
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
                    if col.get("columnId") == LINK_URL_COLUMN_ID:
                        link_col_idx = i
                        break

            if link_col_idx < 0 and column_id_seen:
                # Headers were present but no LINK_URL column. Hard-fail per spec.
                return ObservePointFetchResult(
                    report_id=report_id,
                    report_name=report_name,
                    grid_entity_type=grid_entity_raw,
                    error=(
                        f"Saved report '{report_name or report_id}' has no "
                        f"LINK_URL column. Edit the saved-report grid to "
                        f"include the Link URL column and try again."
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
                    url = _unwrap_safelinks(raw)
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)

            current_page = int(pagination.get("currentPageNumber", page))
            total_pages = int(pagination.get("totalPageCount", current_page + 1))
            if current_page + 1 >= total_pages:
                break
            page += 1

        return ObservePointFetchResult(
            urls=urls,
            report_id=report_id,
            report_name=report_name,
            grid_entity_type=grid_entity_raw,
            total_rows=max(total_count, 0),
        )
    finally:
        if own_client:
            await client.aclose()


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
