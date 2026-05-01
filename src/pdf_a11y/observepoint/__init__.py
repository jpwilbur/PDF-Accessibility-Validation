"""ObservePoint Saved Report → PDF URL list.

Public surface:

    fetch_pdf_urls(api_key, report_id) -> ObservePointFetchResult

The function performs the same two-step dance as the sibling PDFScraper:
    1. GET /v3/reports/grid/saved/{report_id}      -> saved-report config
    2. POST /v3/reports/grid/{gridEntityType}      -> paginated rows

It requires the saved report to expose a `LINK_URL` column. If that column
is missing, the function returns an `ObservePointFetchResult` with `error`
set, never a partial URL list. Callers should surface the error to the
user so they can edit the saved report rather than running on the wrong
column.
"""

from pdf_a11y.observepoint.client import (
    ObservePointError,
    ObservePointFetchResult,
    fetch_pdf_urls,
    fetch_pdf_urls_async,
)

__all__ = [
    "ObservePointError",
    "ObservePointFetchResult",
    "fetch_pdf_urls",
    "fetch_pdf_urls_async",
]
