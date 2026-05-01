"""Check implementations.

Importing this package triggers auto-registration of all checks via
:mod:`pdf_a11y.checks.registry` import side effects in submodules.
"""

from pdf_a11y.checks import (  # noqa: F401  (registration side effects)
    pdfua,
    semantics,
    structure,
    visual,
)
from pdf_a11y.checks.base import Check
from pdf_a11y.checks.registry import all_checks, get_check, register

__all__ = ["Check", "all_checks", "get_check", "register"]
