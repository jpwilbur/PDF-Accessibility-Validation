"""Async, polite, deduplicating PDF downloader.

- Configurable concurrency (default 3) and per-URL timeout.
- Exponential backoff on 5xx and connection errors.
- SHA-256 content cache: if we already have bytes whose hash matches, skip re-download.
- Magic-byte validation: rejects HTML error pages or login redirects.
- Records HTTP status, content-type, final URL, byte size, and download time.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from pdf_a11y.acquire.validator import is_pdf_bytes
from pdf_a11y.config import NetworkConfig

logger = logging.getLogger(__name__)


@dataclass
class AcquiredPdf:
    source: str
    """The original input string (URL or path)."""

    local_path: Path
    sha256: str
    byte_size: int

    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    download_ms: float | None = None
    from_cache: bool = False
    error: str | None = None


class Downloader:
    def __init__(self, cache_dir: Path, network: NetworkConfig):
        self.cache_dir = cache_dir
        self.network = network
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ----- public API ------------------------------------------------------

    async def acquire_many(self, sources: list[str]) -> list[AcquiredPdf]:
        sem = asyncio.Semaphore(self.network.concurrency)

        async with httpx.AsyncClient(
            follow_redirects=self.network.follow_redirects,
            timeout=self.network.timeout_seconds,
            headers={"User-Agent": self.network.user_agent},
        ) as client:

            async def _bounded(src: str) -> AcquiredPdf:
                async with sem:
                    # Light jitter to avoid thundering-herd on the same host.
                    await asyncio.sleep(random.uniform(0.05, 0.35))
                    return await self.acquire(src, client=client)

            return await asyncio.gather(*(_bounded(s) for s in sources))

    async def acquire(self, source: str, *, client: httpx.AsyncClient | None = None) -> AcquiredPdf:
        # Local path? Just hash and return.
        if not _looks_like_url(source):
            return self._acquire_local(source)

        own_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                follow_redirects=self.network.follow_redirects,
                timeout=self.network.timeout_seconds,
                headers={"User-Agent": self.network.user_agent},
            )
        try:
            return await self._acquire_url(source, client)
        finally:
            if own_client:
                await client.aclose()

    # ----- internals -------------------------------------------------------

    def _acquire_local(self, source: str) -> AcquiredPdf:
        path = Path(source).expanduser().resolve()
        if not path.exists() or not path.is_file():
            return AcquiredPdf(
                source=source,
                local_path=path,
                sha256="",
                byte_size=0,
                error=f"local path does not exist: {path}",
            )
        data = path.read_bytes()
        if not is_pdf_bytes(data):
            return AcquiredPdf(
                source=source,
                local_path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                byte_size=len(data),
                error="local file is not a PDF (missing %PDF- magic bytes)",
            )
        sha = hashlib.sha256(data).hexdigest()
        cache_path = self._cache_path(sha)
        if not cache_path.exists():
            cache_path.write_bytes(data)
        return AcquiredPdf(
            source=source,
            local_path=cache_path,
            sha256=sha,
            byte_size=len(data),
            from_cache=False,
            content_type="application/pdf",
        )

    async def _acquire_url(self, url: str, client: httpx.AsyncClient) -> AcquiredPdf:
        start = time.perf_counter()
        last_err: str | None = None
        for attempt in range(1, self.network.retries + 1):
            try:
                async with client.stream("GET", url) as resp:
                    final_url = str(resp.url)
                    status = resp.status_code
                    content_type = resp.headers.get("content-type")
                    if status >= 500:
                        last_err = f"HTTP {status}"
                        await self._sleep_backoff(attempt)
                        continue
                    if status >= 400:
                        return AcquiredPdf(
                            source=url,
                            local_path=Path(),
                            sha256="",
                            byte_size=0,
                            final_url=final_url,
                            http_status=status,
                            content_type=content_type,
                            error=f"HTTP {status}",
                        )

                    chunks: list[bytes] = []
                    total = 0
                    too_big = False
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > self.network.max_bytes:
                            too_big = True
                            break
                        chunks.append(chunk)
                    if too_big:
                        return AcquiredPdf(
                            source=url,
                            local_path=Path(),
                            sha256="",
                            byte_size=total,
                            final_url=final_url,
                            http_status=status,
                            content_type=content_type,
                            error=f"file exceeds max_bytes ({self.network.max_bytes})",
                        )
                    data = b"".join(chunks)

                    if not is_pdf_bytes(data):
                        return AcquiredPdf(
                            source=url,
                            local_path=Path(),
                            sha256=hashlib.sha256(data).hexdigest(),
                            byte_size=len(data),
                            final_url=final_url,
                            http_status=status,
                            content_type=content_type,
                            error=(
                                "response is not a PDF (no %PDF- magic bytes); "
                                "likely an HTML error page or login redirect"
                            ),
                        )
                    sha = hashlib.sha256(data).hexdigest()
                    cache_path = self._cache_path(sha)
                    from_cache = cache_path.exists()
                    if not from_cache:
                        cache_path.write_bytes(data)
                    elapsed_ms = (time.perf_counter() - start) * 1000.0
                    return AcquiredPdf(
                        source=url,
                        local_path=cache_path,
                        sha256=sha,
                        byte_size=len(data),
                        final_url=final_url,
                        http_status=status,
                        content_type=content_type,
                        download_ms=elapsed_ms,
                        from_cache=from_cache,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = f"{type(e).__name__}: {e}"
                logger.debug("download attempt %d for %s failed: %s", attempt, url, e)
                await self._sleep_backoff(attempt)
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                break

        return AcquiredPdf(
            source=url,
            local_path=Path(),
            sha256="",
            byte_size=0,
            error=last_err or "unknown download error",
        )

    async def _sleep_backoff(self, attempt: int) -> None:
        # Exponential with jitter; capped at 30s.
        base = self.network.backoff_base_seconds
        delay = min(30.0, base * (2 ** (attempt - 1)))
        delay += random.uniform(0, base)
        await asyncio.sleep(delay)

    def _cache_path(self, sha256: str) -> Path:
        return self.cache_dir / f"{sha256}.pdf"


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))
