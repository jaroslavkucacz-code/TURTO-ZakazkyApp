from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import sys
import traceback
from pathlib import Path

multiprocessing.freeze_support()

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parents[2] / "ZakazkyApp_base_6.1"
)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SMOKE_TEST = "--smoke-test" in sys.argv
DATA_SETUP = "--data-setup" in sys.argv
_CI_SMOKE_RESULT_ENV = str(os.environ.get("TURTO_CRM_SMOKE_RESULT", "")).strip()
CI_RESTART_PROBE = (
    not SMOKE_TEST
    and bool(_CI_SMOKE_RESULT_ENV)
    and str(os.environ.get("TURTO_DISABLE_AUTO_UPDATE", "")).strip() == "1"
)
SMOKE_RESULT = Path(_CI_SMOKE_RESULT_ENV) if SMOKE_TEST and _CI_SMOKE_RESULT_ENV else None


def _product_version() -> str:
    """Read the single runtime version owned by the assembled Windows payload."""
    if getattr(sys, "frozen", False):
        manifest = ROOT / "version.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            raise RuntimeError(f"Chybí nebo je poškozený version.json instalace TURTO CRM: {exc}") from exc
        version = str(data.get("version") or "").strip() if isinstance(data, dict) else ""
        channel = str(data.get("channel") or "").strip().casefold() if isinstance(data, dict) else ""
        if not version or channel != "windows":
            raise RuntimeError("version.json neobsahuje platnou Windows verzi TURTO CRM.")
        return version

    version_file = Path(__file__).resolve().with_name("version.txt")
    version = version_file.read_text(encoding="utf-8-sig").strip()
    if not version:
        raise RuntimeError("build/windows/version.txt neobsahuje verzi TURTO CRM.")
    return version


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
    SMOKE_RESULT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _smoke_failure(phase: str, exc: BaseException, exit_code: int = 11, **extra) -> None:
    _smoke_checkpoint(
        phase,
        exception_type=type(exc).__name__,
        error=str(exc),
        traceback=traceback.format_exc(),
        **extra,
    )
    os._exit(exit_code)


def _run_phase(phase: str, callback):
    if not SMOKE_TEST:
        return callback()
    _smoke_checkpoint(f"{phase}-before")
    try:
        result = callback()
    except BaseException as exc:
        _smoke_failure(f"{phase}-error", exc)
    _smoke_checkpoint(f"{phase}-after")
    return result


def _baseline_schema_ready(app) -> bool:
    database = Path(app.DB)
    if not database.exists() or database.stat().st_size == 0:
        return False
    con = sqlite3.connect(str(database), timeout=5)
    try:
        names = {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        con.close()
    return {"users", "settings", "companies", "actions"}.issubset(names)


def _validate_frozen_tkdnd_payload() -> list[str]:
    """Keep the installed Windows x64 payload free of foreign TkDnD binaries."""
    if not getattr(sys, "frozen", False):
        return []
    tkdnd_root = ROOT / "_internal" / "tkinterdnd2" / "tkdnd"
    if not tkdnd_root.is_dir():
        raise RuntimeError(f"Chybí TkDnD runtime: {tkdnd_root}")
    variants = sorted(path.name for path in tkdnd_root.iterdir() if path.is_dir())
    required = {"win-x64", "win-x64-tcl9"}
    missing = sorted(required.difference(variants))
    foreign = sorted(name for name in variants if name not in required)
    if missing:
        raise RuntimeError("Chybí Windows x64 TkDnD varianty: " + ", ".join(missing))
    if foreign:
        raise RuntimeError("Windows balík obsahuje nepotřebné TkDnD varianty: " + ", ".join(foreign))
    return variants


_smoke_checkpoint("launcher-start")

import data_location
import data_onboarding

_smoke_checkpoint("data-modules-imported")

# This mode is exposed as a Start-menu shortcut so the database can be changed
# later without deleting configuration files or reinstalling the application.
if DATA_SETUP:
    data_onboarding.configure_data_location(force=True)
    raise SystemExit(0)

# Normal first start uses the interactive data wizard. CI smoke mode supplies a
# temporary TURTO_CRM_DATA_ROOT and must never open a modal window.
if not SMOKE_TEST and not CI_RESTART_PROBE and not data_onboarding.ensure_data_location():
    raise SystemExit(0)

import app
import runtime_bootstrap
from price_lists_domain.platform import exe_distribution

_smoke_checkpoint("app-runtime-imported")

# The source baseline keeps its historical version; the frozen Windows payload
# owns the 8.x product version through version.json next to TURTO CRM.exe.
app.APP_NAME = "TURTO CRM"
app.APP_VERSION = _product_version()
data_location.apply_to_app(app)
_smoke_checkpoint("data-location-applied", database=str(app.DB), version=app.APP_VERSION)

# The clean-runner integration test lets the updater perform its normal restart.
# This probe proves that the new EXE and payload manifest load, but exits before
# normal schema/migration work so a byte-level DB hash can isolate the updater's
# program replacement from a subsequent, explicitly controlled full smoke start.
# It is active only for the CI-only environment combination above.
if CI_RESTART_PROBE:
    _validate_frozen_tkdnd_payload()
    os._exit(0)

tkdnd_variants = _run_phase("tkdnd-payload", _validate_frozen_tkdnd_payload)
_run_phase("cleanup-stale-test-session", app.cleanup_stale_test_session)

# Some historical runtime layers expect the core schema to exist while they are
# being composed. Only a new/incomplete database gets this early baseline pass.
if not _baseline_schema_ready(app):
    _run_phase("baseline-schema", app.ensure_schema)

_run_phase("runtime-apply", lambda: runtime_bootstrap.apply_all(app))
_run_phase("exe-policy", lambda: exe_distribution.apply(app))

# Final idempotent schema/migration passes preserve the proven legacy startup
# sequence while keeping a new 8.0 installation self-contained.
_run_phase("schema-final", app.ensure_schema)
_run_phase("test-user", app.ensure_test_user)
_run_phase("visual-migration", app.migrate_v41_visual_once)
_run_phase("mail-v220", app.import_mail_contacts_v220_once)
_run_phase("mail-v221", app.import_mail_contacts_v221_once)
_run_phase("people-recovery", app.restore_people_from_v280_backup_once)
_run_phase("post-import-cleanup", app.post_import_cleanup_v222_once)

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
                "tkdnd_variants": tkdnd_variants,
                "frozen": bool(getattr(sys, "frozen", False)),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    # Historical compatibility owners may keep helper threads alive. The smoke
    # contract already closed SQLite and persisted its result.
    os._exit(0)

app.App().mainloop()
