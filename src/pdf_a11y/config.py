"""Runtime configuration: weights, paths, network knobs.

Loaded from `weights.yaml` (and overridable via CLI flags).
"""

from __future__ import annotations

import os
import shutil
import sys
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
        cfg.java_home = _detect_java_home()

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
        sep = os.pathsep
        current = os.environ.get("PATH", "")
        if self.java_home not in current.split(sep):
            os.environ["PATH"] = f"{self.java_home}{sep}{current}"


def ensure_weasyprint_libs_on_path() -> None:
    """Set DYLD_FALLBACK_LIBRARY_PATH on macOS so WeasyPrint finds Homebrew
    native libs (glib / gobject / pango / cairo).

    Without this, `import weasyprint` raises OSError("cannot load library
    'libgobject-2.0-0'") on macOS because Apple's dynamic linker doesn't
    search /opt/homebrew/lib by default. Idempotent — safe to call from any
    entry point that imports weasyprint.

    On Linux the libs are typically in /usr/lib and resolved automatically;
    on Windows GTK must be installed via the official MSI and the
    libs are added to PATH by that installer.
    """
    if sys.platform != "darwin":
        return
    candidates = ["/opt/homebrew/lib", "/usr/local/lib"]
    var = "DYLD_FALLBACK_LIBRARY_PATH"
    current = os.environ.get(var, "")
    parts = current.split(os.pathsep) if current else []
    changed = False
    for c in candidates:
        if Path(c).is_dir() and c not in parts:
            parts.insert(0, c)
            changed = True
    if changed:
        os.environ[var] = os.pathsep.join(parts)


def _detect_java_home() -> str | None:
    """Cross-platform best-effort detection of a Java install for veraPDF.

    Order:
        1. `java` on PATH already (no shimming needed) → return None.
        2. JAVA_HOME env var.
        3. macOS Homebrew openjdk locations (Apple Silicon then Intel).
        4. Windows: common Adoptium / Eclipse Temurin install dirs.

    Returns the directory that should be prepended to PATH, or None if java
    is already callable.
    """
    if shutil.which("java"):
        return None

    env_home = os.environ.get("JAVA_HOME")
    if env_home:
        candidate = Path(env_home) / "bin"
        if (candidate / _java_exe_name()).exists():
            return str(candidate)

    if sys.platform == "darwin":
        for p in (
            Path("/opt/homebrew/opt/openjdk/bin"),
            Path("/usr/local/opt/openjdk/bin"),
        ):
            if (p / "java").exists():
                return str(p)
    elif sys.platform == "win32":
        for parent in (
            Path("C:/Program Files/Eclipse Adoptium"),
            Path("C:/Program Files/Java"),
            Path("C:/Program Files (x86)/Java"),
        ):
            if not parent.exists():
                continue
            for sub in sorted(parent.iterdir(), reverse=True):
                bin_dir = sub / "bin"
                if (bin_dir / "java.exe").exists():
                    return str(bin_dir)
    return None


def _java_exe_name() -> str:
    return "java.exe" if sys.platform == "win32" else "java"
