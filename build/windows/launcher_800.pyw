from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

multiprocessing.freeze_support()

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "ZakazkyApp_base_6.1"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_location
import data_onboarding

if not data_onboarding.ensure_data_location():
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
app.App().mainloop()
