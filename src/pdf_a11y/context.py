"""PdfContext: parsed-once representation passed to every check.

Each check receives the same context, so we never re-open the PDF per check.
Heavyweight artifacts (page renders, OCR results) are computed lazily and cached.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)


@dataclass
class PdfContext:
    """All shared parsed state for one PDF.

    Construction is cheap. Open `pike` lazily so checks that don't need
    the full structure tree don't pay for it.
    """

    path: Path
    sha256: str
    source: str
    final_url: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    download_ms: float | None = None

    _pike: pikepdf.Pdf | None = field(default=None, init=False, repr=False)
    _open_error: Exception | None = field(default=None, init=False, repr=False)
    _fitz_doc: Any = field(default=None, init=False, repr=False)
    _page_text_cache: dict[int, str] = field(default_factory=dict, init=False, repr=False)

    # ---- pikepdf (structure-tree-aware) ----------------------------------

    @property
    def pike(self) -> pikepdf.Pdf | None:
        if self._pike is None and self._open_error is None:
            try:
                self._pike = pikepdf.open(self.path)
            except Exception as e:
                self._open_error = e
                logger.warning("pikepdf failed to open %s: %s", self.path, e)
        return self._pike

    @property
    def open_error(self) -> Exception | None:
        # Force evaluation of the lazy open if not yet attempted.
        _ = self.pike
        return self._open_error

    # ---- catalog conveniences --------------------------------------------

    @cached_property
    def catalog(self) -> pikepdf.Object | None:
        return self.pike.Root if self.pike else None

    @cached_property
    def is_encrypted(self) -> bool:
        return bool(self.pike.is_encrypted) if self.pike else False

    @cached_property
    def has_tagged_structure(self) -> bool:
        cat = self.catalog
        if cat is None:
            return False
        try:
            mark_info = cat.get("/MarkInfo")
            marked = bool(mark_info and bool(mark_info.get("/Marked", False)))
            struct_root = "/StructTreeRoot" in cat
            return marked and struct_root
        except Exception:
            return False

    @cached_property
    def language(self) -> str | None:
        cat = self.catalog
        if cat is None:
            return None
        try:
            lang = cat.get("/Lang")
            return str(lang) if lang else None
        except Exception:
            return None

    @cached_property
    def title(self) -> str | None:
        if self.pike is None:
            return None
        try:
            info = self.pike.docinfo
            title = info.get("/Title")
            return str(title) if title else None
        except Exception:
            return None

    @cached_property
    def display_doc_title(self) -> bool:
        cat = self.catalog
        if cat is None:
            return False
        try:
            vp = cat.get("/ViewerPreferences")
            return bool(vp and bool(vp.get("/DisplayDocTitle", False)))
        except Exception:
            return False

    @cached_property
    def claims_pdf_ua(self) -> bool:
        """Look for the PDF/UA identifier in raw XMP metadata.

        We deliberately avoid pikepdf's `open_metadata()` context manager because
        on entry it synchronizes XMP with the docinfo dictionary and overwrites
        Producer/CreationDate fields with pikepdf's own values, which corrupts
        any downstream metadata reads.
        """
        if self.pike is None:
            return False
        try:
            cat = self.pike.Root
            xmp_obj = cat.get("/Metadata")
            if xmp_obj is None:
                return False
            xmp = bytes(xmp_obj.read_bytes()) if hasattr(xmp_obj, "read_bytes") else b""
            return b"pdfuaid:part" in xmp
        except Exception:
            return False

    @cached_property
    def producer(self) -> str | None:
        if self.pike is None:
            return None
        try:
            return str(self.pike.docinfo.get("/Producer") or "") or None
        except Exception:
            return None

    @cached_property
    def creator(self) -> str | None:
        if self.pike is None:
            return None
        try:
            return str(self.pike.docinfo.get("/Creator") or "") or None
        except Exception:
            return None

    @cached_property
    def creation_date(self) -> str | None:
        if self.pike is None:
            return None
        try:
            v = self.pike.docinfo.get("/CreationDate")
            return str(v) if v else None
        except Exception:
            return None

    @cached_property
    def pdf_version(self) -> str | None:
        if self.pike is None:
            return None
        try:
            return str(self.pike.pdf_version)
        except Exception:
            return None

    @cached_property
    def page_count(self) -> int:
        if self.pike is None:
            return 0
        try:
            return len(self.pike.pages)
        except Exception:
            return 0

    @cached_property
    def modification_date(self) -> str | None:
        if self.pike is None:
            return None
        try:
            v = self.pike.docinfo.get("/ModDate")
            return str(v) if v else None
        except Exception:
            return None

    @cached_property
    def has_acroform(self) -> bool:
        cat = self.catalog
        if cat is None:
            return False
        try:
            af = cat.get("/AcroForm")
            if af is None:
                return False
            fields = af.get("/Fields")
            if fields is None:
                return False
            try:
                return len(fields) > 0
            except Exception:
                return True
        except Exception:
            return False

    @cached_property
    def has_xfa(self) -> bool:
        """Detect XFA forms — deprecated dynamic-form standard, often inaccessible."""
        cat = self.catalog
        if cat is None:
            return False
        try:
            af = cat.get("/AcroForm")
            return bool(af is not None and "/XFA" in af)
        except Exception:
            return False

    @cached_property
    def has_bookmarks(self) -> bool:
        cat = self.catalog
        if cat is None:
            return False
        try:
            outlines = cat.get("/Outlines")
            if outlines is None:
                return False
            return "/First" in outlines
        except Exception:
            return False

    # ---- veraPDF (cached) ------------------------------------------------

    @cached_property
    def verapdf(self) -> Any:
        """Lazy: run veraPDF UA-1 once and cache the parsed result."""
        from pdf_a11y.adapters import verapdf as vpdf_mod

        return vpdf_mod.run(self.path)

    # ---- Structure tree (cached, walked once) ----------------------------

    @cached_property
    def struct_nodes(self) -> Any:
        """Flattened list of structure-tree nodes (post role-map). Empty if untagged."""
        from pdf_a11y.checks import _struct_walk

        return _struct_walk.walk(self)

    # ---- PyMuPDF (rendering, fast text extraction) -----------------------

    @property
    def fitz_doc(self) -> Any:
        if self._fitz_doc is None:
            import fitz  # PyMuPDF, imported lazily to keep startup fast

            self._fitz_doc = fitz.open(self.path)
        return self._fitz_doc

    def page_text(self, page_index: int) -> str:
        """Cached plain-text extraction for one 0-based page index."""
        if page_index in self._page_text_cache:
            return self._page_text_cache[page_index]
        try:
            text = self.fitz_doc.load_page(page_index).get_text("text") or ""
        except Exception as e:
            logger.debug("page_text(%d) failed: %s", page_index, e)
            text = ""
        self._page_text_cache[page_index] = text
        return text

    def close(self) -> None:
        import contextlib

        if self._pike is not None:
            with contextlib.suppress(Exception):
                self._pike.close()
        if self._fitz_doc is not None:
            with contextlib.suppress(Exception):
                self._fitz_doc.close()

    def __enter__(self) -> PdfContext:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
