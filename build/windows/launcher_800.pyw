from __future__ import annotations

import json
import multiprocessing
import os
import sys
from pathlib import Path

multiprocessing.freeze_support()

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "ZakazkyApp_base_6.1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SMOKE_TEST = "--smoke-test" in sys.argv
SMOKE_RESULT = Path(str(os.environ.get("TURTO_CRM_SMOKE_RESULT", "")).strip()) if SMOKE_TEST and str(os.environ.get("TURTO_CRM_SMOKE_RESULT", "")).strip() else None


def _smoke_checkpoint(phase: str, **extra) -> None:
    if not SMOKE_TEST or SMOKE_RESULT is None:
        return
    payload = {
        "ok": False,
        "phase": phase,
        "frozen": bool(getattr(sys, "frozen", False)),
        **extra,
    }
    SMOKE_RESULT.parent.mkdir(parents=True, exist_ok=True)
    SMOKE_RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


_smoke_checkpoint("launcher-start")

import data_location
import data_onboarding

_smoke_checkpoint("data-modules-imported")

# Normal first start uses the interactive data wizard. CI smoke mode supplies a
# temporary TURTO_CRM_DATA_ROOT and must never open a modal window.
if not SMOKE_TEST and not data_onboarding.ensure_data_location():
    raise SystemExit(0)

import app
import runtime_bootstrap
from price_lists_domain.platform import exe_distribution

_smoke_checkpoint("app-runtime-imported")

# The source baseline keeps its historical version; the frozen launcher owns the
# 8.x product version and data-location override.
app.APP_NAME = "TURTO CRM"
app.APP_VERSION = "8.0.0-preview.1"
data_location.apply_to_app(app)
_smoke_checkpoint("data-location-applied", database=str(app.DB))

# Frozen smoke mode records the exact runtime layer currently being composed.
# This diagnostic wrapper is intentionally local to the launcher and only active
# under --smoke-test, so the normal installed application keeps the proven
# runtime bootstrap implementation unchanged.
if SMOKE_TEST:
    _original_runtime_apply = runtime_bootstrap._apply
    _original_prime_layers = runtime_bootstrap._prime_startup_stability_layers

    def _diagnostic_runtime_apply(module_name, target):
        _smoke_checkpoint(f"runtime-before:{module_name}", database=str(getattr(target, "DB", "")))
        _original_runtime_apply(module_name, target)
        _smoke_checkpoint(f"runtime-after:{module_name}", database=str(getattr(target, "DB", "")))

    def _diagnostic_prime_layers():
        _smoke_checkpoint("runtime-before:stability-prime", database=str(app.DB))
        _original_prime_layers()
        _smoke_checkpoint("runtime-after:stability-prime", database=str(app.DB))

    runtime_bootstrap._apply = _diagnostic_runtime_apply
    runtime_bootstrap._prime_startup_stability_layers = _diagnostic_prime_layers

runtime_bootstrap.apply_all(app)
_smoke_checkpoint("runtime-applied", database=str(app.DB))
exe_distribution.apply(app)
_smoke_checkpoint("exe-policy-applied", database=str(app.DB))

app.cleanup_stale_test_session()
app.ensure_schema()
_smoke_checkpoint("schema-ready", database=str(app.DB))
app.ensure_test_user()
_smoke_checkpoint("test-user-ready", database=str(app.DB))
app.migrate_v41_visual_once()
_smoke_checkpoint("visual-migration-ready", database=str(app.DB))
app.import_mail_contacts_v220_once()
_smoke_checkpoint("mail-v220-ready", database=str(app.DB))
app.import_mail_contacts_v221_once()
_smoke_checkpoint("mail-v221-ready", database=str(app.DB))
app.restore_people_from_v280_backup_once()
_smoke_checkpoint("people-recovery-ready", database=str(app.DB))
app.post_import_cleanup_v222_once()
_smoke_checkpoint("post-import-cleanup-ready", database=str(app.DB))

if SMOKE_TEST:
    if SMOKE_RESULT is None:
        raise SystemExit(2)
    con = app.db()
    try:
        quick = con.execute("PRAGMA quick_check").fetchone()
        tables = sorted(
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        )
    finally:
        con.close()
    if not quick or str(quick[0]).strip().casefold() != "ok":
        _smoke_checkpoint("database-quick-check-failed", database=str(app.DB))
        raise SystemExit(3)
    SMOKE_RESULT.write_text(
        json.dumps(
            {
                "ok": True,
                "phase": "complete",
                "version": app.APP_VERSION,
                "database": str(app.DB),
                "tables": tables,
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    # A historical compatibility layer may own a non-daemon helper thread. The
    # smoke contract has already closed SQLite and persisted its result, so force
    # process termination instead of letting unrelated helpers keep CI alive.
    os._exit(0)

app.App().mainloop()
