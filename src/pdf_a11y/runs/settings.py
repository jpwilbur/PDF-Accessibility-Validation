"""Per-user, plain-JSON settings file.

Stores the ObservePoint API key and last-used preferences. Per the user's
explicit preference for this internal tool, the API key is stored in
plaintext under the user-data dir. The file is written with mode 0o600 on
POSIX (Mac/Linux) so it's only readable by the current user; on Windows the
default ACL (which already restricts to the user account) applies.

This is intentionally simpler than `keyring` — no extra dependencies, no
prompts, and the file lives outside the repo so it cannot be accidentally
committed.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pdf_a11y import paths


@dataclass
class Settings:
    op_api_key: str = ""
    last_op_report_id: str = ""
    last_concurrency: int = 3

    extra: dict[str, str] = field(default_factory=dict)


def load_settings(path: Path | None = None) -> Settings:
    p = path or paths.settings_path()
    if not p.exists():
        return Settings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    return Settings(
        op_api_key=str(data.get("op_api_key", "")),
        last_op_report_id=str(data.get("last_op_report_id", "")),
        last_concurrency=int(data.get("last_concurrency", 3) or 3),
        extra={k: str(v) for k, v in (data.get("extra") or {}).items()},
    )


def save_settings(settings: Settings, path: Path | None = None) -> None:
    import contextlib

    p = path or paths.settings_path()
    paths.ensure_dirs()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
    tmp.replace(p)


__all__ = ["Settings", "load_settings", "save_settings"]
