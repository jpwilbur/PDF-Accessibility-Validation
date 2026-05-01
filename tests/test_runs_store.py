"""Run-history SQLite store + settings file tests."""

from __future__ import annotations

import time
from pathlib import Path

from pdf_a11y.runs.settings import Settings, load_settings, save_settings
from pdf_a11y.runs.store import RunStatus, RunStore, new_run_id


def test_create_and_get_run(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "runs.db")
    rid = new_run_id()
    rec = store.create(
        run_id=rid,
        source_kind="manual",
        source_meta={"inputs": ["a.pdf"]},
        output_dir=tmp_path / "out" / rid,
        label="test",
    )
    assert rec.id == rid
    assert rec.status == RunStatus.PENDING
    assert rec.source_kind == "manual"
    assert rec.source_meta == {"inputs": ["a.pdf"]}

    fetched = store.get(rid)
    assert fetched is not None
    assert fetched.id == rid


def test_update_progresses_and_marks_done(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "runs.db")
    rid = new_run_id()
    store.create(
        run_id=rid,
        source_kind="observepoint",
        source_meta={"report_id": "42"},
        output_dir=tmp_path / "out" / rid,
    )
    store.update(rid, status=RunStatus.RUNNING, n_total=10)
    rec = store.get(rid)
    assert rec is not None
    assert rec.status == RunStatus.RUNNING
    assert rec.n_total == 10
    assert rec.progress_pct == 0.0

    store.update(rid, n_done=3)
    rec = store.get(rid)
    assert rec is not None
    assert rec.progress_pct == 30.0

    store.update(rid, status=RunStatus.DONE, n_done=10, n_critical_failed=2, finished=True)
    rec = store.get(rid)
    assert rec is not None
    assert rec.status == RunStatus.DONE
    assert rec.finished_at is not None
    assert rec.n_critical_failed == 2


def test_list_returns_all_runs(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "runs.db")
    ids = set()
    for _ in range(3):
        rid = new_run_id()
        # Sleep enough that started_at second precision differs.
        time.sleep(0.001)
        ids.add(rid)
        store.create(
            run_id=rid,
            source_kind="manual",
            source_meta={},
            output_dir=tmp_path / "out" / rid,
        )
    runs = store.list()
    assert len(runs) == 3
    assert {r.id for r in runs} == ids


def test_delete_run(tmp_path: Path) -> None:
    store = RunStore(db_path=tmp_path / "runs.db")
    rid = new_run_id()
    store.create(
        run_id=rid,
        source_kind="manual",
        source_meta={},
        output_dir=tmp_path / "out" / rid,
    )
    assert store.get(rid) is not None
    store.delete(rid)
    assert store.get(rid) is None


# ---------- Settings ----------


def test_settings_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    s = Settings(op_api_key="abc123", last_op_report_id="42", last_concurrency=5)
    save_settings(s, path=p)
    loaded = load_settings(path=p)
    assert loaded.op_api_key == "abc123"
    assert loaded.last_op_report_id == "42"
    assert loaded.last_concurrency == 5


def test_settings_load_returns_defaults_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "doesnotexist.json"
    s = load_settings(path=p)
    assert s.op_api_key == ""
    assert s.last_concurrency == 3


def test_settings_load_returns_defaults_for_corrupt_json(tmp_path: Path) -> None:
    p = tmp_path / "settings.json"
    p.write_text("{not valid json")
    assert load_settings(path=p).op_api_key == ""


def test_new_run_id_is_unique() -> None:
    assert new_run_id() != new_run_id()
