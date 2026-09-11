#!/usr/bin/env python3
"""Verify status auditing survives removal of the duplicate v605 snapshot."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_v611_audit_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeApp:
    def refresh_actions(self):
        return None

    def refresh_requests(self):
        return None


def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    module = load_module(base / "v611_audit.py")

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE actions(
               id INTEGER PRIMARY KEY,status TEXT,name TEXT,company_id INTEGER,
               salesperson_id INTEGER,deadline TEXT,products TEXT,note TEXT
           )"""
    )
    con.execute(
        "INSERT INTO actions VALUES(1,'Rozpracováno','Test',1,1,'2026-09-20','IZO','')"
    )
    con.commit()

    M = SimpleNamespace(
        App=FakeApp,
        db=lambda: con,
        get_setting=lambda key, default="": "Jaroslav Kučera" if key == "active_user" else default,
        _active_app=None,
    )
    module.apply(M)
    app = M.App()
    M._active_app = app

    # First refresh seeds the consolidated v611 snapshot.
    app.refresh_actions()
    assert getattr(app, "_v611_action_snapshot", {}).get(1, {}).get("status") == "Rozpracováno"

    # The next refresh must create exactly the historical status-audit contract.
    con.execute("UPDATE actions SET status='Nabídka' WHERE id=1")
    con.commit()
    app.refresh_actions()
    rows = con.execute(
        "SELECT entity_type,entity_id,action,field_name,old_value,new_value,undo_sql "
        "FROM audit_history ORDER BY id"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_type"] == "Příležitost"
    assert row["entity_id"] == "1"
    assert row["action"] == "Změna stavu"
    assert row["field_name"] == "Stav"
    assert row["old_value"] == "Rozpracováno"
    assert row["new_value"] == "Nabídka"
    assert row["undo_sql"] == "UPDATE actions SET status='Rozpracováno' WHERE id=1"

    # The stored undo must remain executable and restore the original state.
    con.execute(row["undo_sql"])
    con.commit()
    restored = con.execute("SELECT status FROM actions WHERE id=1").fetchone()["status"]
    assert restored == "Rozpracováno"

    v605 = (base / "crm_v605.py").read_text(encoding="utf-8")
    assert "SELECT id,status FROM actions" not in v605
    assert "_patch_status_audit" not in v605
    v611 = (base / "v611_audit.py").read_text(encoding="utf-8")
    assert "'status':'Stav'" in v611
    assert "'Změna stavu' if key=='status' else 'Úprava'" in v611

    print("TURTO CRM 8.0.4 consolidated action status audit: OK")


if __name__ == "__main__":
    main()
