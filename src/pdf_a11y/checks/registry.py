"""Decorator-based check registry."""

from __future__ import annotations

from typing import TypeVar

from pdf_a11y.checks.base import Check

_REGISTRY: dict[str, type[Check]] = {}

C = TypeVar("C", bound=Check)


def register(cls: type[C]) -> type[C]:
    if not getattr(cls, "id", None):
        raise ValueError(f"Check {cls.__name__} missing class attribute `id`.")
    if cls.id in _REGISTRY:
        raise ValueError(f"Duplicate check id: {cls.id}")
    _REGISTRY[cls.id] = cls
    return cls


def all_checks() -> list[Check]:
    """Instantiate one of each registered check, ordered by id."""
    return [_REGISTRY[k]() for k in sorted(_REGISTRY)]


def get_check(check_id: str) -> Check:
    return _REGISTRY[check_id]()


def registered_ids() -> list[str]:
    return sorted(_REGISTRY)
