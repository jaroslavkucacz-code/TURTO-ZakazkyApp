"""Stable wrapper for lazy refresh plus WAL-safe SQLite backups."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

_IMPL_NAME = "price_lists_domain.platform._lazy_refresh_v630_impl"
_IMPL_PATH = Path(__file__).resolve().parent.parent / "lazy_refresh.py"

if _IMPL_NAME in sys.modules:
    _impl = sys.modules[_IMPL_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_IMPL_NAME, _IMPL_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Nelze načíst lazy-refresh implementaci: {_IMPL_PATH}")
    _impl = importlib.util.module_from_spec(_spec)
    sys.modules[_IMPL_NAME] = _impl
    _spec.loader.exec_module(_impl)


def _install_safe_backup(module) -> None:
    if getattr(module, "_turto_sqlite_backup_v630", False):
        return

    def backup_now(prefix="manual"):
        db_path = Path(module.DB)
        if not db_path.exists():
            return None
        backup_dir = Path(module.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"zakazky_{prefix}_{datetime.now():%Y%m%d_%H%M%S}.db"
        # SQLite backup API includes all committed WAL pages and produces a
        # consistent copy even while the application remains open.
        with module.sqlite3.connect(str(db_path), timeout=10.0) as source:
            with module.sqlite3.connect(str(target), timeout=10.0) as destination:
                source.backup(destination, pages=256, sleep=0.01)
        return target

    module.backup_now = backup_now
    module._turto_sqlite_backup_v630 = True


def install(module):
    _install_safe_backup(module)
    return _impl.install(module)


__all__ = ["install"]
