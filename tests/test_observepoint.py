"""ObservePoint client tests with mocked HTTP."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from pdf_a11y.observepoint import ObservePointFetchResult, fetch_pdf_urls_async
from pdf_a11y.observepoint.client import _unwrap_safelinks

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_unwrap_safelinks_extracts_inner_url() -> None:
    inner = "https://example.com/a.pdf"
    wrapped = (
        "https://nam12.safelinks.protection.outlook.com/?url="
        + inner.replace(":", "%3A").replace("/", "%2F")
        + "&data=foo"
    )
    assert _unwrap_safelinks(wrapped) == inner


def test_unwrap_safelinks_passthrough_for_normal_urls() -> None:
    assert _unwrap_safelinks("https://example.com/a.pdf") == "https://example.com/a.pdf"


# ---------------------------------------------------------------------------
# Mocked-API integration tests via httpx.MockTransport
# ---------------------------------------------------------------------------


def _saved_response(grid_entity: str = "web_audit_runs") -> dict[str, Any]:
    return {
        "id": 12345,
        "name": "PDF links report",
        "gridEntityType": grid_entity,
        "queryDefinition": {
            "columns": [],
            "filters": {},
            "page": 0,
            "size": 500,
        },
    }


def _grid_page(rows: list[list[Any]], *, page: int, total_pages: int) -> dict[str, Any]:
    return {
        "metadata": {
            "headers": [
                {"column": {"columnId": "FOO"}},
                {"column": {"columnId": "LINK_URL"}},
                {"column": {"columnId": "BAR"}},
            ],
            "pagination": {
                "currentPageNumber": page,
                "totalPageCount": total_pages,
                "totalCount": sum(1 for _ in rows) + page * 2,
            },
        },
        "rows": rows,
    }


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


def _make_handler(routes: dict[str, dict[str, Any]]) -> httpx.MockTransport:
    """Build an httpx MockTransport from a {url_substring: response_dict}-or-list mapping.

    For grid POSTs, the value can be a list[dict] of pages — each call advances
    through the list.
    """
    state: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        for substr, payload in routes.items():
            if substr in str(request.url):
                if isinstance(payload, list):
                    idx = state.get(substr, 0)
                    if idx >= len(payload):
                        return httpx.Response(500, json={"error": "no more mock pages"})
                    state[substr] = idx + 1
                    return httpx.Response(200, json=payload[idx])
                if callable(payload):
                    return payload(request)
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"error": f"unmatched {request.url}"})

    return httpx.MockTransport(handler)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_happy_path_paginates_and_dedupes() -> None:
    """Two pages, with one duplicate URL across them — should be deduped."""
    routes = {
        "/reports/grid/saved/42": _saved_response(),
        "/reports/grid/web-audit-runs": [
            _grid_page(
                [
                    ["x", "https://example.com/a.pdf", "y"],
                    ["x", "https://example.com/b.pdf", "y"],
                ],
                page=0,
                total_pages=2,
            ),
            _grid_page(
                [
                    ["x", "https://example.com/b.pdf", "y"],  # duplicate
                    ["x", "https://example.com/c.pdf", "y"],
                ],
                page=1,
                total_pages=2,
            ),
        ],
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")

    result: ObservePointFetchResult = _run(
        fetch_pdf_urls_async(api_key="test", report_id="42", client=client)
    )
    assert result.error is None, result.error
    assert result.urls == [
        "https://example.com/a.pdf",
        "https://example.com/b.pdf",
        "https://example.com/c.pdf",
    ]
    assert result.report_name == "PDF links report"
    assert result.grid_entity_type == "web_audit_runs"


def test_missing_link_url_column_hard_fails() -> None:
    no_link_page = {
        "metadata": {
            "headers": [
                {"column": {"columnId": "FOO"}},
                {"column": {"columnId": "BAR"}},
            ],
            "pagination": {"currentPageNumber": 0, "totalPageCount": 1, "totalCount": 0},
        },
        "rows": [],
    }
    routes = {
        "/reports/grid/saved/42": _saved_response(),
        "/reports/grid/web-audit-runs": no_link_page,
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")
    result = _run(fetch_pdf_urls_async(api_key="t", report_id="42", client=client))
    assert result.error is not None
    assert "LINK_URL" in result.error
    assert result.urls == []


def test_401_returns_clear_error() -> None:
    def saved_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    transport = _make_handler({"/reports/grid/saved/42": saved_handler})
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")
    result = _run(fetch_pdf_urls_async(api_key="bad", report_id="42", client=client))
    assert result.error is not None
    assert "401" in result.error or "API key" in result.error


def test_404_for_missing_report() -> None:
    def saved_handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Not found"})

    transport = _make_handler({"/reports/grid/saved/999": saved_handler})
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")
    result = _run(fetch_pdf_urls_async(api_key="t", report_id="999", client=client))
    assert result.error is not None
    assert "999" in result.error or "404" in result.error


def test_empty_api_key_or_report_id_returns_error() -> None:
    a = _run(fetch_pdf_urls_async(api_key="", report_id="42"))
    assert a.error is not None
    assert "API key" in a.error
    b = _run(fetch_pdf_urls_async(api_key="x", report_id=""))
    assert b.error is not None
    assert "Report ID" in b.error


def test_safelinks_unwrapped_in_results() -> None:
    inner = "https://example.com/safe.pdf"
    wrapped = (
        "https://nam12.safelinks.protection.outlook.com/?url="
        + inner.replace(":", "%3A").replace("/", "%2F")
        + "&data=foo"
    )
    routes = {
        "/reports/grid/saved/42": _saved_response(),
        "/reports/grid/web-audit-runs": _grid_page([["x", wrapped, "y"]], page=0, total_pages=1),
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")
    result = _run(fetch_pdf_urls_async(api_key="t", report_id="42", client=client))
    assert result.urls == [inner]


@pytest.mark.parametrize(
    "raw_entity",
    ["web_audit_runs", "audit_pages", "weak_audits"],
)
def test_grid_entity_underscore_to_hyphen_conversion(raw_entity: str) -> None:
    """The entity type comes back with underscores; the URL needs hyphens."""
    expected_path = f"/reports/grid/{raw_entity.replace('_', '-')}"
    routes = {
        "/reports/grid/saved/1": _saved_response(grid_entity=raw_entity),
        expected_path: _grid_page([], page=0, total_pages=1),
    }
    transport = _make_handler(routes)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.observepoint.com")
    result = _run(fetch_pdf_urls_async(api_key="t", report_id="1", client=client))
    assert result.error is None
    assert result.grid_entity_type == raw_entity


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


def test_browser_logs_skips_malformed_rows() -> None:
    good = 'PDF Links:["https://oklahoma.gov/ok.pdf"]'
    bad_json = "PDF Links:[not valid json]"  # matches [...] but fails json.loads
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
    assert result.urls == []


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
    assert result.entity_mode == "browser_log"
    assert result.total_rows == 2  # _browser_log_page with 2 messages → totalCount=2


def test_browser_logs_empty_report_no_diagnosis() -> None:
    """A genuinely empty browser_logs report (0 rows) must NOT trigger the
    zero-URL diagnosis — it's a clean empty result, not a format problem."""
    routes = {
        "/reports/grid/saved/28159": _browser_log_saved(),
        "/reports/grid/browser-logs": _browser_log_page(
            [], page=0, total_pages=1
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
    assert result.urls == []
    assert result.entity_mode == "browser_log"
