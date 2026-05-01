"""Sanity tests for the structure-tree walker."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pdf_a11y.checks._struct_walk import HEADING_TAGS, walk
from pdf_a11y.context import PdfContext


def _ctx(path: Path) -> PdfContext:
    return PdfContext(
        path=path,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        source=str(path),
    )


def test_walk_returns_empty_for_untagged_pdf(scan_only_pdf: Path) -> None:
    with _ctx(scan_only_pdf) as ctx:
        nodes = walk(ctx)
    assert nodes == []


def test_walk_returns_nodes_for_tagged_pdf(known_good_pdf: Path) -> None:
    with _ctx(known_good_pdf) as ctx:
        nodes = walk(ctx)
    # The veraPDF UA-1 graphics fixture has at least Document + Figure tags.
    assert len(nodes) > 0
    # We can't assume specific tags but every tag should resolve to something.
    assert all(n.tag for n in nodes)
    # And no resolved tag should still have a leading slash.
    assert not any(n.tag.startswith("/") for n in nodes)


def test_role_map_resolution_for_real_world(fixtures_dir: Path) -> None:
    """A real-world doc with custom tags should still resolve to standard tags
    (or at least not crash). We just smoke-test that headings are detected."""
    pdf = fixtures_dir / "real_world" / "medicare-and-you.pdf"
    with _ctx(pdf) as ctx:
        nodes = walk(ctx)
    assert nodes
    # Medicare handbook has many headings (sections, chapters).
    assert any(n.tag in HEADING_TAGS for n in nodes)
