"""Acquire-layer tests: cache, magic-byte validation, local-path handling."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from pdf_a11y.acquire import Downloader, is_pdf
from pdf_a11y.acquire.downloader import _classify_http_failure, _looks_like_html
from pdf_a11y.acquire.validator import is_pdf_bytes
from pdf_a11y.config import NetworkConfig


def test_is_pdf_bytes_accepts_real_pdf_header() -> None:
    assert is_pdf_bytes(b"%PDF-1.7\nrest") is True


def test_is_pdf_bytes_rejects_html() -> None:
    assert is_pdf_bytes(b"<!DOCTYPE html><html>...") is False


def test_is_pdf_bytes_rejects_empty() -> None:
    assert is_pdf_bytes(b"") is False


def test_is_pdf_path_passes_for_fixture(known_good_pdf: Path) -> None:
    assert is_pdf(known_good_pdf) is True


def test_is_pdf_path_rejects_missing(tmp_path: Path) -> None:
    assert is_pdf(tmp_path / "nope.pdf") is False


def test_local_path_acquisition_caches_by_hash(known_good_pdf: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    dl = Downloader(cache_dir=cache, network=NetworkConfig())
    result = asyncio.run(dl.acquire(str(known_good_pdf)))
    assert result.error is None
    assert result.sha256
    assert result.local_path.exists()
    assert result.local_path.parent == cache


def test_local_path_missing_file_returns_error(tmp_path: Path) -> None:
    dl = Downloader(cache_dir=tmp_path, network=NetworkConfig())
    result = asyncio.run(dl.acquire(str(tmp_path / "missing.pdf")))
    assert result.error is not None
    assert "does not exist" in result.error


def test_local_path_non_pdf_returns_error(tmp_path: Path) -> None:
    bogus = tmp_path / "fake.pdf"
    bogus.write_bytes(b"not a pdf")
    dl = Downloader(cache_dir=tmp_path / "cache", network=NetworkConfig())
    result = asyncio.run(dl.acquire(str(bogus)))
    assert result.error is not None
    assert "magic bytes" in result.error


# ----- User-Agent policy -------------------------------------------------
#
# Regression cover for the mass.gov 403s: a bespoke UA token got every PDF
# refused at the edge (both /files/*.pdf and /doc/*/download), while httpx's
# own default was served normally. The default must stay "send no override".


def test_default_config_sends_no_user_agent_override() -> None:
    assert NetworkConfig().user_agent is None


def test_client_headers_empty_by_default(tmp_path: Path) -> None:
    dl = Downloader(cache_dir=tmp_path, network=NetworkConfig())
    assert dl._client_headers() == {}


def test_client_headers_used_when_configured(tmp_path: Path) -> None:
    dl = Downloader(cache_dir=tmp_path, network=NetworkConfig(user_agent="custom/1.0"))
    assert dl._client_headers() == {"User-Agent": "custom/1.0"}


def test_no_fallback_user_agents_by_default() -> None:
    """Rotating UAs to defeat a WAF is evasion; it must be opt-in."""
    assert NetworkConfig().fallback_user_agents == []


# ----- blocked vs missing classification --------------------------------

BLOCK_PAGE = b"<!DOCTYPE html><html><body>403 Oh no. This page is forbidden</body></html>"


def test_classify_403_is_blocked() -> None:
    message, blocked = _classify_http_failure(403, BLOCK_PAGE)
    assert blocked is True
    assert "403" in message
    assert "not an accessibility result" in message


def test_classify_403_notes_html_block_page() -> None:
    message, _ = _classify_http_failure(403, BLOCK_PAGE)
    assert "HTML block page" in message


def test_classify_429_and_451_are_blocked() -> None:
    for status in (401, 406, 429, 451):
        _, blocked = _classify_http_failure(status, b"")
        assert blocked is True, f"{status} should count as blocked"


def test_classify_404_is_not_blocked() -> None:
    message, blocked = _classify_http_failure(404, b"")
    assert blocked is False
    assert "no document at this URL" in message


def test_classify_other_4xx_is_not_blocked() -> None:
    _, blocked = _classify_http_failure(418, b"")
    assert blocked is False


def test_looks_like_html_detects_doctype_and_tag() -> None:
    assert _looks_like_html(b"<!DOCTYPE html><html>") is True
    assert _looks_like_html(b"  <html lang='en'>") is True
    assert _looks_like_html(b"%PDF-1.7") is False


# ----- end-to-end over a mock transport ---------------------------------

MINIMAL_PDF = b"%PDF-1.4\n%%EOF\n"


def _run_with_transport(handler, url: str, network: NetworkConfig, cache: Path) -> object:  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        dl = Downloader(cache_dir=cache, network=network)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await dl.acquire(url, client=client)

    return asyncio.run(go())


def test_403_response_is_flagged_blocked(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=BLOCK_PAGE, headers={"content-type": "text/html"})

    result = _run_with_transport(
        handler, "https://example.gov/doc/x/download", NetworkConfig(retries=1), tmp_path
    )
    assert result.blocked is True
    assert result.http_status == 403
    assert result.error is not None
    assert "refused" in result.error


def test_404_response_is_not_flagged_blocked(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"missing")

    result = _run_with_transport(
        handler, "https://example.gov/gone.pdf", NetworkConfig(retries=1), tmp_path
    )
    assert result.blocked is False
    assert result.http_status == 404


def test_successful_pdf_is_not_flagged_blocked(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=MINIMAL_PDF, headers={"content-type": "application/pdf"})

    result = _run_with_transport(
        handler, "https://example.gov/ok.pdf", NetworkConfig(retries=1), tmp_path
    )
    assert result.blocked is False
    assert result.error is None
    assert result.byte_size == len(MINIMAL_PDF)


def test_fallback_user_agent_retried_only_when_blocked(tmp_path: Path) -> None:
    """A blocked row retries with the operator's fallback UA; 200 then sticks."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ua = request.headers.get("user-agent", "")
        seen.append(ua)
        if ua == "rescue/1.0":
            return httpx.Response(
                200, content=MINIMAL_PDF, headers={"content-type": "application/pdf"}
            )
        return httpx.Response(403, content=BLOCK_PAGE, headers={"content-type": "text/html"})

    network = NetworkConfig(retries=1, fallback_user_agents=["rescue/1.0"])
    result = _run_with_transport(handler, "https://example.gov/x.pdf", network, tmp_path)

    assert result.blocked is False
    assert result.error is None
    assert "rescue/1.0" in seen
    assert len(seen) == 2  # one blocked attempt, then the fallback


def test_no_fallback_retry_on_404(tmp_path: Path) -> None:
    """404 won't change with a new identity, so don't spend a request on it."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(404, content=b"nope")

    network = NetworkConfig(retries=1, fallback_user_agents=["rescue/1.0"])
    _run_with_transport(handler, "https://example.gov/x.pdf", network, tmp_path)
    assert len(seen) == 1
