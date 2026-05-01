"""Runtime configuration: weights, paths, network knobs.

Loaded from `weights.yaml` (and overridable via CLI flags).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pdf_a11y.models import Severity

DEFAULT_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 10,
    Severity.MAJOR: 4,
    Severity.MINOR: 1,
    Severity.WARNING: 0,
}

DEFAULT_GRADE_THRESHOLDS: dict[str, int] = {
    "A": 95,
    "B": 85,
    "C": 70,
    "D": 50,
}

DEFAULT_CRITICAL_FAIL_IDS: list[str] = ["STRUCT-001", "STRUCT-005", "STRUCT-008"]


@dataclass
class NetworkConfig:
    concurrency: int = 3
    """Default low concurrency to be polite and avoid bot-detection trips."""

    timeout_seconds: float = 60.0
    retries: int = 3
    backoff_base_seconds: float = 1.5
    user_agent: str = "pdf-a11y/0.1 (+accessibility-evaluator; polite-bot; contact your site admin)"
    follow_redirects: bool = True
    max_bytes: int = 200 * 1024 * 1024  # 200 MB hard cap per file


@dataclass
class Paths:
    output_dir: Path = field(default_factory=lambda: Path("./reports"))
    cache_dir: Path = field(default_factory=lambda: Path("./.cache/pdfs"))


@dataclass
class Config:
    weights: dict[Severity, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    grade_thresholds: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_GRADE_THRESHOLDS))
    critical_fail_check_ids: list[str] = field(
        default_factory=lambda: list(DEFAULT_CRITICAL_FAIL_IDS)
    )
    network: NetworkConfig = field(default_factory=NetworkConfig)
    paths: Paths = field(default_factory=Paths)
    java_home: str | None = None
    """If set, prepended to PATH so veraPDF can find Java."""

    @classmethod
    def load(cls, weights_path: Path | None = None) -> Config:
        cfg = cls()
        # Auto-detect Homebrew openjdk so veraPDF works out of the box on macOS.
        homebrew_java = Path("/opt/homebrew/opt/openjdk/bin/java")
        if homebrew_java.exists():
            cfg.java_home = "/opt/homebrew/opt/openjdk/bin"

        if weights_path and weights_path.exists():
            data = yaml.safe_load(weights_path.read_text()) or {}
            sev_map = {s.value.lower(): s for s in Severity}
            for k, v in (data.get("severities") or {}).items():
                key = sev_map.get(k.lower())
                if key is not None:
                    cfg.weights[key] = int(v)
            for grade, threshold in (data.get("grades") or {}).items():
                cfg.grade_thresholds[grade.upper()] = int(threshold)
            ids = data.get("critical_fail_check_ids")
            if ids:
                cfg.critical_fail_check_ids = list(ids)
        return cfg

    def ensure_java_on_path(self) -> None:
        """Prepend java_home to PATH if not already present (for veraPDF subprocess)."""
        if not self.java_home:
            return
        current = os.environ.get("PATH", "")
        if self.java_home not in current.split(":"):
            os.environ["PATH"] = f"{self.java_home}:{current}"
