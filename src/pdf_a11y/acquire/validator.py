"""Magic-byte validation: confirm a downloaded blob is actually a PDF."""

from __future__ import annotations

from pathlib import Path

PDF_MAGIC = b"%PDF-"


def is_pdf_bytes(data: bytes) -> bool:
    if not data:
        return False
    # Some PDFs have up to 1024 bytes of header noise before %PDF-.
    head = data[:1024]
    return PDF_MAGIC in head


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return is_pdf_bytes(fh.read(1024))
    except OSError:
        return False
