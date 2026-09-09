from __future__ import annotations

import importlib
import json
import multiprocessing
import os
import sqlite3
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

# Some historical runtime layers expect the core schema to exist while they are
# being composed (crm_runtime, for example, reads the users table in apply()).
# Existing databases keep the historical startup order; only a new/incomplete
# database receives the baseline schema before runtime composition.
def _baseline_schema_ready() -> bool:
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


app.cleanup_stale_test_session()
if not _baseline_schema_ready():
    _smoke_checkpoint("baseline-schema-required", database=str(app.DB))
    app.ensure_schema()
    _smoke_checkpoint("baseline-schema-ready", database=str(app.DB))

# Frozen smoke mode records the exact runtime layer currently being composed.
# These wrappers are intentionally active only under --smoke-test; normal
# installed startup keeps the proven runtime owners unchanged.
if SMOKE_TEST:
    _original_prime_layers = runtime_bootstrap._prime_startup_stability_layers

    def _wrap_callable(owner, attribute: str, label: str) -> None:
        original = getattr(owner, attribute, None)
        if not callable(original) or getattr(original, "_turto_smoke_trace", False):
            return

        def traced(*args, _original=original, _label=label, **kwargs):
            _smoke_checkpoint(f"{_label}-before", database=str(getattr(app, "DB", "")))
            result = _original(*args, **kwargs)
            _smoke_checkpoint(f"{_label}-after", database=str(getattr(app, "DB", "")))
            return result

        traced._turto_smoke_trace = True
        setattr(owner, attribute, traced)

    def _trace_crm_runtime_helpers(runtime_module):
        for helper_name in (
            "_activate",
            "_db_wrapper",
            "_safe_dialog_sizer",
            "_ensure",
            "_patch_users",
            "_patch_theme",
        ):
            _wrap_callable(runtime_module, helper_name, f"crm-runtime:{helper_name}")

    def _trace_price_list_helpers(runtime_module):
        # First distinguish the two public phases owned by crm_price_lists.
        _wrap_callable(runtime_module, "_apply_price_lists", "crm-price-lists:domain")
        _wrap_callable(runtime_module, "install_customer_pricing", "crm-price-lists:customer-pricing")

        # crm_price_lists already imported price_lists_domain; wrapping these
        # globals therefore adds no extra owner imports before the real apply().
        domain = importlib.import_module("price_lists_domain")
        for helper_name in (
            "_install_new_project_button",
            "_install_offer_integration",
            "_install_app_page",
            "_install_settings",
            "install_issued_offers",
        ):
            _wrap_callable(domain, helper_name, f"price-domain:{helper_name}")

        # platform.install intentionally imports its owners lazily inside the
        # function. A previous diagnostic pre-imported them and itself became the
        # blocking step. Under --smoke-test only, reproduce the same import/call
        # order with checkpoints around every lazy import and every installer.
        platform = importlib.import_module("price_lists_domain.platform")
        original_platform_install = platform.install
        if not getattr(original_platform_install, "_turto_smoke_trace", False):
            platform_steps = (
                ("price_lists_domain.platform.database", "install_fast_db", "install_fast_db"),
                ("price_lists_domain.platform.database", "patch_schema", "patch_schema"),
                ("price_lists_domain.platform.fast_ocr", "install", "install_ocr"),
                ("price_lists_domain.platform.integration", "install", "install_price_integration"),
                ("price_lists_domain.platform.product_catalog", "install", "install_product_catalog"),
                ("price_lists_domain.platform.product_workspace", "install", "install_product_workspace"),
                ("price_lists_domain.platform.offers", "install", "install_offers"),
                ("price_lists_domain.platform.archive", "install", "install_archive"),
                ("price_lists_domain.platform.worksets", "install", "install_worksets"),
                ("price_lists_domain.platform.finalize", "install", "install_finalize"),
                ("price_lists_domain.platform.compat", "install", "install_compat"),
                ("price_lists_domain.platform.clarity", "install", "install_clarity"),
                ("price_lists_domain.platform.commercial_workspace", "install", "install_commercial_workspace"),
                ("price_lists_domain.platform.lazy_refresh", "install", "install_lazy_refresh"),
                ("price_lists_domain.platform.project_table_stability", "install", "install_project_table_stability"),
                ("price_lists_domain.platform.automatic_updates", "install", "install_automatic_updates"),
            )

            def diagnostic_platform_install(module):
                _smoke_checkpoint("price-platform:install-before", database=str(getattr(module, "DB", "")))
                resolved = []
                for module_name, attribute, label in platform_steps:
                    _smoke_checkpoint(f"price-platform:import:{label}-before", database=str(getattr(module, "DB", "")))
                    owner = importlib.import_module(module_name)
                    _smoke_checkpoint(f"price-platform:import:{label}-after", database=str(getattr(module, "DB", "")))
                    resolved.append((getattr(owner, attribute), label))

                if getattr(module, "_turto_platform_v6339", False):
                    _smoke_checkpoint("price-platform:install-after", database=str(getattr(module, "DB", "")))
                    return

                for installer, label in resolved:
                    _smoke_checkpoint(f"price-platform:{label}-before", database=str(getattr(module, "DB", "")))
                    installer(module)
                    _smoke_checkpoint(f"price-platform:{label}-after", database=str(getattr(module, "DB", "")))

                module._turto_platform_v6339 = True
                _smoke_checkpoint("price-platform:install-after", database=str(getattr(module, "DB", "")))

            diagnostic_platform_install._turto_smoke_trace = True
            platform.install = diagnostic_platform_install

        # customer_pricing is already imported by crm_price_lists. Trace only its
        # helper calls; do not introduce any new import sequence here.
        customer = importlib.import_module("price_lists_domain.platform.customer_pricing")
        for helper_name in (
            "ensure_schema",
            "_patch_catalog_rows",
            "_patch_workspace",
            "_patch_document_service",
            "_patch_pickers",
        ):
            _wrap_callable(customer, helper_name, f"customer-pricing:{helper_name}")

    def _diagnostic_runtime_apply(module_name, target):
        _smoke_checkpoint(f"runtime-before-import:{module_name}", database=str(getattr(target, "DB", "")))
        runtime_module = importlib.import_module(module_name)
        _smoke_checkpoint(f"runtime-after-import:{module_name}", database=str(getattr(target, "DB", "")))
        if module_name == "crm_runtime":
            _trace_crm_runtime_helpers(runtime_module)
        elif module_name == "crm_price_lists":
            _trace_price_list_helpers(runtime_module)
        _smoke_checkpoint(f"runtime-before-apply:{module_name}", database=str(getattr(target, "DB", "")))
        runtime_module.apply(target)
        _smoke_checkpoint(f"runtime-after-apply:{module_name}", database=str(getattr(target, "DB", "")))

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

# Run the final schema pass after runtime composition too. Later compatibility
# layers may extend the baseline schema; ensure_schema is intentionally idempotent.
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
