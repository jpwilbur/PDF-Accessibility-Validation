"""Cross-platform user-data and config paths.

`platformdirs` resolves the conventional location per OS:

    macOS:    ~/Library/Application Support/pdf-a11y/
    Linux:    ~/.local/share/pdf-a11y/
    Windows:  C:\\Users\\<user>\\AppData\\Local\\pdf-a11y\\

The CLI's `--output-dir` and `--cache-dir` defaults stay relative to the
current directory (so `pdf-a11y evaluate` outputs land where the user expects).
The web app, however, persists runs under the user-data dir so they survive
between cwds and shells.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "pdf-a11y"
APP_AUTHOR = "ObservePoint"

logger = logging.getLogger(__name__)


def app_data_dir() -> Path:
    return Path(user_data_dir(APP_NAME, APP_AUTHOR))


def runs_dir() -> Path:
    return app_data_dir() / "runs"


def runs_db_path() -> Path:
    return app_data_dir() / "runs.db"


def run_output_dir(run_id: str) -> Path:
    return runs_dir() / run_id


def settings_path() -> Path:
    """Plain-JSON settings file (API keys, last-used IDs, prefs).

    Per user request: API key may be stored in plaintext here. The file is
    placed under the user-data dir which is per-user on all supported OSes.
    """
    return app_data_dir() / "settings.json"


def ensure_dirs() -> None:
    app_data_dir().mkdir(parents=True, exist_ok=True)
    runs_dir().mkdir(parents=True, exist_ok=True)


def sweep_orphaned_caches() -> int:
    """Remove every ``runs/*/cache/`` directory; return bytes reclaimed.

    Safe to call only when no run is active (e.g. at app startup): a run's
    cache is transient working space at ``runs/<id>/cache``. Report outputs
    (``pdfs/``, ``findings.jsonl``, ``summary.*``, ``batch.json``) are never
    touched. Per-directory errors are logged and skipped (best-effort).
    """
    base = runs_dir()
    if not base.exists():
        return 0
    reclaimed = 0
    for cache in base.glob("*/cache"):
        if not cache.is_dir():
            continue
        try:
            size = sum(
                f.stat().st_size for f in cache.rglob("*") if f.is_file()
            )
        except OSError:
            size = 0
        try:
            shutil.rmtree(cache)
            reclaimed += size
        except OSError as e:
            logger.warning("could not remove orphaned cache %s: %s", cache, e)
    return reclaimed
