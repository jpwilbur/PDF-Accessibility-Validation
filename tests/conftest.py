"""Shared fixtures."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"


def _verapdf_available() -> bool:
    return shutil.which("verapdf") is not None


def _tesseract_available() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=5, check=True)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def synthetic_dir() -> Path:
    SYNTHETIC.mkdir(exist_ok=True, parents=True)
    return SYNTHETIC


@pytest.fixture(scope="session")
def has_tesseract() -> bool:
    return _tesseract_available()


@pytest.fixture(scope="session")
def has_verapdf() -> bool:
    return _verapdf_available()


@pytest.fixture(scope="session")
def scan_only_pdf(synthetic_dir: Path) -> Path:
    """Synthesize a scan-only PDF: render a text page to an image, then write
    the image into a fresh PDF with no text layer."""
    out = synthetic_dir / "synthetic-scan-only.pdf"
    if out.exists():
        return out

    import fitz  # PyMuPDF

    src = fitz.open()
    page = src.new_page(width=612, height=792)
    rect = fitz.Rect(72, 72, 540, 720)
    page.insert_textbox(
        rect,
        "This is a synthesized scan-only test fixture.\n"
        "It has been rasterized and re-imported as an image, "
        "which means there is NO real text layer. "
        "The pdf-a11y STRUCT-008 check should detect this and "
        "issue a critical-fail finding.\n\n"
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna "
        "aliqua. Ut enim ad minim veniam, quis nostrud exercitation.",
        fontsize=14,
    )
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    src.close()

    dst = fitz.open()
    page = dst.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(0, 0, 612, 792), stream=img_bytes)
    dst.save(str(out), garbage=3, deflate=True)
    dst.close()
    return out


@pytest.fixture(scope="session")
def known_good_pdf(fixtures_dir: Path) -> Path:
    return fixtures_dir / "known_good" / "verapdf-ua1-7.3-graphics-pass.pdf"


@pytest.fixture(scope="session")
def low_contrast_pdf(synthetic_dir: Path) -> Path:
    """Synthesize a PDF with deliberate low-contrast text for VIS-001 testing.

    Page 1: black on white — should NOT be flagged.
    Page 2: light gray (~#bbbbbb) on white at 12pt — ratio ~2.85, fails AA.
    Page 3: same gray at 24pt (large) — also fails (large threshold is 3:1).
    """
    out = synthetic_dir / "synthetic-low-contrast.pdf"
    if out.exists():
        return out

    import fitz

    doc = fitz.open()

    p = doc.new_page(width=612, height=792)
    p.insert_textbox(
        fitz.Rect(72, 72, 540, 720),
        "This text is solid black on white and should pass VIS-001.",
        fontsize=12,
        color=(0, 0, 0),
    )

    p = doc.new_page(width=612, height=792)
    p.insert_textbox(
        fitz.Rect(72, 72, 540, 720),
        "This text is light gray and should fail the WCAG AA contrast check.",
        fontsize=12,
        color=(0xBB / 255, 0xBB / 255, 0xBB / 255),
    )

    p = doc.new_page(width=612, height=792)
    p.insert_textbox(
        fitz.Rect(72, 72, 540, 720),
        "Large gray heading",
        fontsize=24,
        color=(0xBB / 255, 0xBB / 255, 0xBB / 255),
    )

    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    return out
