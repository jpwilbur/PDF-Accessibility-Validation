"""Tests for streaming per-PDF cache cleanup."""

from __future__ import annotations

from pathlib import Path

from pdf_a11y.acquire import AcquiredPdf
from pdf_a11y.config import Config
from pdf_a11y.pipeline import Pipeline


def test_network_config_streaming_defaults() -> None:
    cfg = Config()
    assert cfg.network.chunk_size == 10
    assert cfg.network.delete_cache_after_eval is True


def test_delete_cached_removes_only_files_inside_cache(tmp_path: Path) -> None:
    cfg = Config()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cfg.paths.cache_dir = cache_dir
    pipeline = Pipeline(cfg)

    # Inside the cache → deleted.
    inside = cache_dir / "abc.pdf"
    inside.write_bytes(b"%PDF-1.4\n")
    ap_inside = AcquiredPdf(source="u", local_path=inside, sha256="a", byte_size=9)
    pipeline._delete_cached(ap_inside, cache_dir)
    assert not inside.exists()

    # Outside the cache (e.g. a user's local source) → preserved.
    outside = tmp_path / "original.pdf"
    outside.write_bytes(b"%PDF-1.4\n")
    ap_outside = AcquiredPdf(source="v", local_path=outside, sha256="b", byte_size=9)
    pipeline._delete_cached(ap_outside, cache_dir)
    assert outside.exists()

    # Missing path → no error.
    ap_missing = AcquiredPdf(
        source="w", local_path=cache_dir / "nope.pdf", sha256="", byte_size=0
    )
    pipeline._delete_cached(ap_missing, cache_dir)  # must not raise

    # Download-failure row (empty Path) → no error.
    ap_empty = AcquiredPdf(source="x", local_path=Path(), sha256="", byte_size=0)
    pipeline._delete_cached(ap_empty, cache_dir)  # must not raise
