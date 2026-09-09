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

import data_location
import data_onboarding

# Normal first start uses the interactive data wizard. CI smoke mode supplies a
# temporary TURTO_CRM_DATA_ROOT and must never open a modal window.
if not SMOKE_TEST and not data_onboarding.ensure_data_location():
    raise SystemExit(0)

import app
import runtime_bootstrap
from price_lists_domain.platform import exe_distribution

# The source baseline keeps its historical version; the frozen launcher owns the
# 8.x product version and data-location override.
app.APP_NAME = "TURTO CRM"
app.APP_VERSION = "8.0.0-preview.1"
data_location.apply_to_app(app)
runtime_bootstrap.apply_all(app)
exe_distribution.apply(app)

app.cleanup_stale_test_session()
app.ensure_schema()
app.ensure_test_user()
app.migrate_v41_visual_once()
app.import_mail_contacts_v220_once()
app.import_mail_contacts_v221_once()
app.restore_people_from_v280_backup_once()
app.post_import_cleanup_v222_once()

if SMOKE_TEST:
    result_path = str(os.environ.get("TURTO_CRM_SMOKE_RESULT", "")).strip()
    if not result_path:
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
        raise SystemExit(3)
    target = Path(result_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "ok": True,
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
    raise SystemExit(0)

app.App().mainloop()
