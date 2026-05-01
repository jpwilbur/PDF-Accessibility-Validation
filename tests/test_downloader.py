"""Acquire-layer tests: cache, magic-byte validation, local-path handling."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pdf_a11y.acquire import Downloader, is_pdf
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
