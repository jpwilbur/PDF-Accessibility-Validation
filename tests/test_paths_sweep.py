"""Tests for the startup orphaned-cache sweep."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdf_a11y import paths


def test_sweep_removes_cache_dirs_but_keeps_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setattr(paths, "runs_dir", lambda: runs)

    run1 = runs / "run1"
    (run1 / "cache").mkdir(parents=True)
    (run1 / "cache" / "a.pdf").write_bytes(b"x" * 100)
    (run1 / "cache" / "b.pdf").write_bytes(b"y" * 50)
    (run1 / "summary.html").write_text("<html></html>")
    (run1 / "findings.jsonl").write_text("{}\n")

    reclaimed = paths.sweep_orphaned_caches()

    assert reclaimed >= 150
    assert not (run1 / "cache").exists()
    assert (run1 / "summary.html").exists()
    assert (run1 / "findings.jsonl").exists()


def test_sweep_no_runs_dir_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paths, "runs_dir", lambda: tmp_path / "does-not-exist")
    assert paths.sweep_orphaned_caches() == 0
