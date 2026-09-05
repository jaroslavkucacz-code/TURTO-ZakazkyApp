import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "_runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import app
import runtime_bootstrap

runtime_bootstrap.apply_all(app)
app.cleanup_stale_test_session()
app.ensure_schema()
app.ensure_test_user()
app.migrate_v41_visual_once()
app.import_mail_contacts_v220_once()
app.import_mail_contacts_v221_once()
app.restore_people_from_v280_backup_once()
app.post_import_cleanup_v222_once()
app.App().mainloop()
