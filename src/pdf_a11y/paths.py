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

from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "pdf-a11y"
APP_AUTHOR = "ObservePoint"


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
