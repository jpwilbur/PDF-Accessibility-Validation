"""Tests for streaming per-PDF cache cleanup."""

from __future__ import annotations

from pdf_a11y.config import Config


def test_network_config_streaming_defaults() -> None:
    cfg = Config()
    assert cfg.network.chunk_size == 10
    assert cfg.network.delete_cache_after_eval is True
