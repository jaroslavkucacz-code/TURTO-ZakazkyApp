"""Stable package API for the SQL-first workset implementation.

The implementation stays in the sibling ``worksets.py`` module. This package
loads it explicitly, but no longer mutates another module's installer or changes
global import order.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_NAME = "price_lists_domain.platform._worksets_impl"
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


def install(module):
    return _impl.install(module)


__all__ = ["install"]
