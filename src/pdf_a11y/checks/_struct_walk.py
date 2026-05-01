"""Structure-tree walking helpers.

PDF/UA documents store their semantics in a logical structure tree under
`/Root/StructTreeRoot`. Each node has a `/S` (structure type) field, which
may be a standard tag (P, H1, Table, ...) or a custom tag that maps via
`/Root/StructTreeRoot/RoleMap` to a standard tag.

This module flattens the tree into typed nodes and resolves role mapping so
checks can ask questions like "find all <Figure> elements" or "iterate all
heading nodes in document order" without re-implementing tree traversal.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pikepdf

from pdf_a11y.context import PdfContext

# Canonical PDF/UA standard structure types we care about. This is the closure
# we map custom tags to via /RoleMap.
HEADING_TAGS: frozenset[str] = frozenset({"H", "H1", "H2", "H3", "H4", "H5", "H6"})
NUMBERED_HEADING_TAGS: frozenset[str] = frozenset({"H1", "H2", "H3", "H4", "H5", "H6"})


@dataclass
class StructNode:
    """A flattened structure tree node."""

    tag: str
    """Resolved standard tag (after role-map). E.g. 'H2', 'Figure', 'Link'."""

    raw_tag: str
    """The tag exactly as written on the element (pre-rolemap)."""

    page: int | None
    """1-based page number, when determinable from the kid's /Pg back-reference."""

    alt: str | None = None
    """`/Alt` if present."""

    actual_text: str | None = None
    """`/ActualText` if present."""

    title: str | None = None
    """`/T` (heading number / item label) if present."""

    lang: str | None = None
    """`/Lang` declared on this element."""

    text: str = ""
    """Concatenated visible text inside this node (best-effort)."""

    attributes: dict[str, Any] = field(default_factory=dict)
    """Resolved /A attributes (e.g. /O='Table' with /Scope, /Headers)."""

    obj_num: int | None = None

    children: list[StructNode] = field(default_factory=list, repr=False)


def walk(ctx: PdfContext) -> list[StructNode]:
    """Return a flat depth-first list of all structure-tree nodes.

    Returns [] if the document has no structure tree or pikepdf cannot open it.
    Errors during traversal are swallowed — checks must tolerate partial trees.
    """
    if ctx.pike is None or not ctx.has_tagged_structure:
        return []
    cat = ctx.pike.Root
    str_root = cat.get("/StructTreeRoot")
    if str_root is None:
        return []

    role_map = _resolve_role_map(str_root)
    seen: set[int] = set()
    out: list[StructNode] = []
    try:
        roots = str_root.get("/K")
        if roots is None:
            return []
        _walk_obj(roots, parent_page=None, role_map=role_map, seen=seen, out=out, depth=0)
    except Exception:
        return out
    return out


def find_by_tag(nodes: list[StructNode], tags: set[str]) -> Iterator[StructNode]:
    for n in nodes:
        if n.tag in tags:
            yield n


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


# Maximum depth we'll descend before giving up; prevents pathological loops
# even if `seen` somehow misses a cycle.
_MAX_DEPTH = 200


def _resolve_role_map(str_root: pikepdf.Object) -> dict[str, str]:
    role_map: dict[str, str] = {}
    try:
        rm = str_root.get("/RoleMap")
        if rm is None:
            return role_map
        # /RoleMap is a dict of name → name (or chain of names → standard tag).
        for key, value in rm.items():
            try:
                role_map[str(key).lstrip("/")] = str(value).lstrip("/")
            except Exception:
                continue
    except Exception:
        pass
    return role_map


def _resolve_tag(raw: str, role_map: dict[str, str]) -> str:
    """Follow /RoleMap chains until we hit a standard tag (or stop at depth 5)."""
    seen: set[str] = set()
    cur = raw.lstrip("/")
    for _ in range(5):
        if cur in seen:
            break
        seen.add(cur)
        nxt = role_map.get(cur)
        if not nxt or nxt == cur:
            break
        cur = nxt
    return cur


def _walk_obj(
    obj: pikepdf.Object,
    *,
    parent_page: int | None,
    role_map: dict[str, str],
    seen: set[int],
    out: list[StructNode],
    depth: int,
) -> None:
    if depth > _MAX_DEPTH:
        return
    # Arrays of children: walk each.
    try:
        if isinstance(obj, pikepdf.Array):
            # pikepdf.Array supports indexing; iteration via index avoids stubs
            # treating it as a non-iterable.
            for i in range(len(obj)):
                _walk_obj(
                    obj[i],
                    parent_page=parent_page,
                    role_map=role_map,
                    seen=seen,
                    out=out,
                    depth=depth + 1,
                )
            return
    except Exception:
        return

    # Dictionaries: structure element if it has /S, else descend into /K.
    try:
        # Cycle guard via object number.
        try:
            obj_num = int(obj.objgen[0])
        except Exception:
            obj_num = -1
        if obj_num in seen:
            return
        if obj_num >= 0:
            seen.add(obj_num)
    except Exception:
        obj_num = -1

    raw_s = obj.get("/S") if hasattr(obj, "get") else None
    if raw_s is None:
        # Not a struct element; if it has /K, descend.
        kids = obj.get("/K") if hasattr(obj, "get") else None
        if kids is not None:
            _walk_obj(
                kids,
                parent_page=parent_page,
                role_map=role_map,
                seen=seen,
                out=out,
                depth=depth + 1,
            )
        return

    raw_tag = str(raw_s).lstrip("/")
    tag = _resolve_tag(raw_tag, role_map)
    page_num = _page_for(obj, parent_page)
    node = StructNode(
        tag=tag,
        raw_tag=raw_tag,
        page=page_num,
        alt=_str_or_none(obj.get("/Alt")),
        actual_text=_str_or_none(obj.get("/ActualText")),
        title=_str_or_none(obj.get("/T")),
        lang=_str_or_none(obj.get("/Lang")),
        attributes=_extract_attributes(obj),
        obj_num=obj_num if obj_num >= 0 else None,
    )

    out.append(node)
    kids = obj.get("/K")
    if kids is not None:
        before_len = len(out)
        _walk_obj(
            kids,
            parent_page=page_num,
            role_map=role_map,
            seen=seen,
            out=out,
            depth=depth + 1,
        )
        node.children = out[before_len:]


def _page_for(obj: pikepdf.Object, parent_page: int | None) -> int | None:
    pg = obj.get("/Pg") if hasattr(obj, "get") else None
    if pg is None:
        return parent_page
    try:
        # We can't easily resolve page index → 1-based number without iterating
        # through Pages. Return None for now; checks rarely need precise pages
        # and can resolve via fitz from the location string.
        return parent_page
    except Exception:
        return parent_page


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    try:
        s = str(v)
    except Exception:
        return None
    s = s.strip()
    return s or None


def _extract_attributes(obj: pikepdf.Object) -> dict[str, Any]:
    """Resolve /A attributes (which may be a dict or array of dicts)."""
    attrs: dict[str, Any] = {}
    try:
        a = obj.get("/A")
        if a is None:
            return attrs
        if isinstance(a, pikepdf.Array):
            for i in range(len(a)):
                _absorb_attr_dict(a[i], attrs)
        else:
            _absorb_attr_dict(a, attrs)
    except Exception:
        return attrs
    return attrs


def _absorb_attr_dict(d: pikepdf.Object, into: dict[str, Any]) -> None:
    if not hasattr(d, "items"):
        return
    try:
        for k, v in d.items():
            try:
                into[str(k).lstrip("/")] = v
            except Exception:
                continue
    except Exception:
        return


__all__ = [
    "HEADING_TAGS",
    "NUMBERED_HEADING_TAGS",
    "StructNode",
    "find_by_tag",
    "walk",
]
