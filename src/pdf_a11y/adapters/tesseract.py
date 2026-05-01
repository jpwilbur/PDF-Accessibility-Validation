"""Thin wrapper around Tesseract for scan-only-PDF detection.

We don't need OCR-quality output — we just need a yes/no signal: does the
rendered page contain text that the PDF text layer didn't expose?
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def is_available() -> bool:
    return shutil.which("tesseract") is not None


@lru_cache(maxsize=1)
def version() -> str | None:
    if not is_available():
        return None
    try:
        out = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        first = (out.stdout or out.stderr).splitlines()
        return first[0].strip() if first else None
    except Exception:
        return None


def ocr_text(image_bytes: bytes) -> str:
    """Run Tesseract over PNG/JPG bytes, return extracted text. Empty string on failure."""
    if not is_available():
        return ""
    try:
        proc = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6"],
            input=image_bytes,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return (proc.stdout or b"").decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("tesseract failed: %s", e)
        return ""
