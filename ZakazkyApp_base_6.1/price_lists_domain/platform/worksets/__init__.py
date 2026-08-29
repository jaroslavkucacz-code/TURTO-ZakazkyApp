"""Package wrapper for the SQL-first workset implementation.

A package intentionally takes precedence over the sibling ``worksets.py`` module.
It loads that reviewed implementation explicitly and ensures the compatibility
classifier is installed *after* the finalization layer, regardless of import order.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .. import compat, finalize

_IMPL_NAME = "price_lists_domain.platform._worksets_v630_impl"
_IMPL_PATH = Path(__file__).resolve().parent.parent / "worksets.py"

if _IMPL_NAME in sys.modules:
    _impl = sys.modules[_IMPL_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_IMPL_NAME, _IMPL_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Nelze načíst SQL workset implementaci: {_IMPL_PATH}")
    _impl = importlib.util.module_from_spec(_spec)
    sys.modules[_IMPL_NAME] = _impl
    _spec.loader.exec_module(_impl)

_original_finalize_install = finalize.install


def _finalize_then_compat(module):
    _original_finalize_install(module)
    compat.install(module)


finalize.install = _finalize_then_compat


def install(module):
    return _impl.install(module)


__all__ = ["install"]
