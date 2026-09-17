#!/usr/bin/env python3
"""Real SQLite/filesystem safety regressions plus Windows Tk interaction checks."""
from contextlib import closing
from datetime import datetime, timedelta
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ZakazkyApp_base_6.1"))
import data_location
import storage_maintenance as s


def seed(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as con:
        con.create_collation("CZECH", data_location._czech_collate)
        con.executescript("""
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE companies(id INTEGER PRIMARY KEY, name TEXT COLLATE CZECH);
            CREATE INDEX cz ON companies(name COLLATE CZECH);
            CREATE TABLE projects(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE archive_batches(id INTEGER PRIMARY KEY, backup_path TEXT);
            INSERT INTO companies VALUES (1, 'Česká společnost');
            INSERT INTO projects VALUES (1, 'Nesmí se změnit');
        """)


def fixture(root, db):
    for index in range(12):
        dt = datetime.now() - timedelta(days=3, minutes=index)
        p = root / "backup" / f"zakazky_pred_aktualizaci_{dt:%Y%m%d_%H%M%S}.db"
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(db, p); os.utime(p, (dt.timestamp(), dt.timestamp()))
    for index in range(5):
        dt = datetime.now() - timedelta(days=3, minutes=index)
        p = root / "updates" / "rollback" / f"TURTO_CRM_8.0.{index}_{dt:%Y%m%d_%H%M%S}.zip"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"package fixture"); os.utime(p, (dt.timestamp(), dt.timestamp()))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turto830_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "CRM česká data"
        self.db = self.root / "data" / "zakazky.db"
        seed(self.db); fixture(self.root, self.db)
        self.live_hash = s.safety.digest(self.db)

    def plan(self):
        return s.build_plan(self.root, self.db)

    def candidates(self):
        return [e for e in self.plan() if e["eligible"]]

    def unchanged(self):
        self.assertEqual(s.safety.digest(self.db), self.live_hash)
        self.assertTrue(data_location.validate_database(self.db)["ok"])

    def test_backup_wal_restorable_unique_and_closed(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.create_collation("CZECH", data_location._czech_collate)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("UPDATE projects SET name='Commit pouze ve WAL'"); con.commit()
            a = s.create_backup(self.db, self.root / "backup", "manual")
            b = data_location.backup_database(self.db, "manual", backup_root=self.root)
            self.assertNotEqual(a, b)
            with closing(sqlite3.connect(a)) as restored:
                self.assertEqual(restored.execute("SELECT name FROM projects").fetchone()[0], "Commit pouze ve WAL")
            renamed = a.with_suffix(".restored.db"); a.rename(renamed); renamed.rename(a)
            self.assertTrue(data_location.validate_database(a)["ok"])
            self.assertFalse(list((self.root / "backup").glob("*.partial*")))
            with closing(sqlite3.connect(a)) as restored:
                self.assertEqual(restored.execute("PRAGMA journal_mode").fetchone()[0], "delete")

    def test_preview_retention_protection_and_no_mutation(self):
        first = self.candidates()[0]
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("INSERT INTO archive_batches(backup_path) VALUES(?)", (str(self.root / first["relative"]),)); con.commit()
        self.live_hash = s.safety.digest(self.db)
        manual = self.root / "backup" / "zakazky_manual_20200101_000000.db"
        shutil.copyfile(self.db, manual)
        imported = self.root / "backup" / "zakazky_before_complete_import_20200101_000000.db"
        shutil.copyfile(self.db, imported)
        candidate = next(e for e in self.candidates() if e["kind"] == "záloha")
        sidecar = self.root / (candidate["relative"] + "-shm"); sidecar.write_bytes(b"keep")
        protected = {first["relative"], manual.relative_to(self.root).as_posix(), imported.relative_to(self.root).as_posix(), candidate["relative"]}
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        plan = self.plan()
        self.assertTrue(all(not e["eligible"] for e in plan if e["relative"] in protected))
        self.assertTrue(self.candidates())
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.unchanged()

    def test_calendar_boundaries(self):
        now = datetime(2026, 1, 1, 12)
        entries = []
        for day in range(500):
            for hour in (1, 2):
                dt = now - timedelta(days=day, hours=hour)
                entries.append({"relative": str(dt), "timestamp": dt.isoformat()})
        keep = s._retained(entries, now)
        self.assertLessEqual(len(keep), 5 + 7 + 8 + 12)
        self.assertTrue({e["relative"] for e in entries[:5]}.issubset(keep))
        self.assertFalse(any(datetime.fromisoformat(k) < datetime(2025, 2, 1) for k in keep))

    def test_stale_plan_and_arbitrary_targets_rejected(self):
        chosen = self.candidates()[:1]
        (self.root / chosen[0]["relative"]).write_bytes(b"changed")
        with self.assertRaises(ValueError): s.execute(self.root, self.db, chosen)
        forged = dict(self.candidates()[0], relative="data/zakazky.db")
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [forged])
        forged["relative"] = "../../outside.db"
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [forged])
        self.unchanged()

    def test_metadata_corruption_and_busy_updater_fail_closed(self):
        control = self.root / "updates" / "last_update.json"
        control.write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError): self.plan()
        control.write_text("{}", encoding="utf-8")
        chosen = self.candidates()[:1]
        with s.maintenance_lock(self.root):
            with self.assertRaises(s.safety.UpdateBlocked): s.execute(self.root, self.db, chosen)
        self.assertTrue((self.root / chosen[0]["relative"]).exists())
        self.unchanged()

    def test_restore_references_and_current_package_preserved(self):
        chosen = self.candidates()
        database = next(e for e in chosen if e["kind"] == "záloha")
        package = next(e for e in chosen if e["kind"] == "aktualizace")
        s.safety.write_json(self.root / "updates" / "last_update.json", {
            "database_backup": str(self.root / database["relative"]), "program_snapshot": str(self.root / package["relative"])})
        fresh = {e["relative"]: e for e in self.plan()}
        self.assertFalse(fresh[database["relative"]]["eligible"])
        self.assertFalse(fresh[package["relative"]]["eligible"])
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [database])

    def test_archive_verified_then_original_removed(self):
        dest = Path(self.temp.name) / "external"; dest.mkdir()
        chosen = self.candidates()[:2]
        hashes = {e["relative"]: s.safety.digest(self.root / e["relative"]) for e in chosen}
        result = s.execute(self.root, self.db, chosen, archive=dest)
        self.assertFalse(result["error"])
        self.assertEqual(len(result["completed"]), 2)
        for e in chosen:
            self.assertFalse((self.root / e["relative"]).exists())
            self.assertEqual(s.safety.digest(Path(result["archive"]) / e["relative"]), hashes[e["relative"]])
        self.assertTrue(data_location.validate_database(Path(result["backup"]))["ok"])
        self.assertTrue((Path(result["archive"]) / "manifest.json").is_file())
        self.unchanged()

    def test_copy_failure_and_backup_failure_preserve_originals(self):
        dest = Path(self.temp.name) / "external"; dest.mkdir()
        chosen = self.candidates()[:1]
        with patch.object(s.shutil, "copyfileobj", side_effect=OSError("disk full")):
            result = s.execute(self.root, self.db, chosen, archive=dest)
        self.assertIn("disk full", result["error"])
        self.assertTrue((self.root / chosen[0]["relative"]).exists())
        with patch.object(s, "create_backup", side_effect=OSError("backup failure")):
            with self.assertRaises(OSError): s.execute(self.root, self.db, chosen)
        self.assertTrue((self.root / chosen[0]["relative"]).exists())
        self.unchanged()

    def test_delete_is_selected_only_and_logs_result(self):
        chosen = self.candidates()[:1]
        other = self.candidates()[1]["relative"]
        result = s.execute(self.root, self.db, chosen)
        self.assertFalse(result["error"])
        self.assertEqual(result["bytes"], chosen[0]["size"])
        self.assertFalse((self.root / chosen[0]["relative"]).exists())
        self.assertTrue((self.root / other).exists())
        self.assertEqual(json.loads(Path(result["log"]).read_text(encoding="utf-8"))["completed"], result["completed"])
        self.unchanged()

    def test_auto_disabled_default_and_never_deletes_legacy(self):
        old = {e["relative"] for e in self.candidates()}
        self.assertIsNone(s.run_daily(self.root, self.db))
        s.save_policy(self.root, self.db, True)
        first = s.run_daily(self.root, self.db)
        self.assertTrue(Path(first["backup"]).exists())
        self.assertIsNone(s.run_daily(self.root, self.db))
        self.assertTrue(all((self.root / p).exists() for p in old))
        s.save_policy(self.root, self.db, False)
        self.assertIsNone(s.run_daily(self.root, self.db))
        self.unchanged()

    def test_auto_future_files_are_pruned_but_manual_stays(self):
        s.save_policy(self.root, self.db, True)
        settings = s.policy(self.root)
        settings["enabled_since"] = (datetime.now() - timedelta(days=5)).isoformat()
        s.safety.write_json(self.root / s.POLICY_NAME, settings)
        manual = self.root / "backup" / "zakazky_manual_20200101_000000.db"; shutil.copyfile(self.db, manual)
        old = self.candidates()
        result = s.run_daily(self.root, self.db)
        self.assertTrue(result["result"]["completed"])
        self.assertTrue(manual.exists())
        self.assertTrue(all(not (self.root / e["relative"]).exists() for e in old))
        self.unchanged()

    def test_symlinks_or_hardlinks_cannot_delete_live_db(self):
        alias = self.root / "backup" / "zakazky_pred_aktualizaci_20200101_000000.db"
        os.link(self.db, alias)
        self.assertFalse(next(e for e in self.plan() if e["relative"] == alias.relative_to(self.root).as_posix())["eligible"])
        if os.name != "nt":
            link = self.root / "backup" / "zakazky_daily_20200102_000000.db"
            link.symlink_to(self.db)
            self.assertNotIn(link.relative_to(self.root).as_posix(), {e["relative"] for e in self.plan()})
        self.unchanged()


def ui_checks():
    spec = importlib.util.spec_from_file_location("previous830", REPO / "scripts/validate-827-processing-catalogs.py")
    previous = importlib.util.module_from_spec(spec); spec.loader.exec_module(previous)
    from price_lists_domain.platform import storage_ui
    with tempfile.TemporaryDirectory(prefix="turto830_ui_") as td:
        M = previous.prepare(str(Path(td) / "crm"), runtime=True)
        fixture(Path(M.DATA_ROOT), Path(M.DB))
        M.App.maybe_show_morning_overview = lambda self: None
        errors, info = [], []
        M.messagebox.showerror = lambda *a, **k: errors.append(a)
        M.messagebox.showinfo = lambda *a, **k: info.append(a)
        M.messagebox.showwarning = lambda *a, **k: info.append(a)
        M.messagebox.askyesno = lambda *a, **k: False
        root = M.App()
        root.report_callback_exception = lambda *exc: errors.append(exc)
        def settle(win):
            end = time.monotonic() + 30
            while time.monotonic() < end:
                root.update(); time.sleep(.02)
                if not win._storage["state"]["busy"]:
                    return
            raise AssertionError("Storage worker did not finish")
        try:
            root.show_page("settings"); root.update()
            win = root.open_storage_maintenance(); settle(win)
            ui = win._storage
            assert not ui["auto"].get()
            assert ui["tree"].winfo_width() > 750
            assert any(e["eligible"] for e in ui["state"]["entries"].values())
            ui["select"].invoke(); root.update()
            assert all(ui["state"]["entries"][i]["eligible"] for i in ui["tree"].selection())
            before = {p.name for p in (Path(M.DATA_ROOT) / "backup").iterdir()}
            ui["delete"].invoke(); root.update()  # Cancel is not deletion.
            assert before == {p.name for p in (Path(M.DATA_ROOT) / "backup").iterdir()}
            ui["auto"].set(True); ui["save"].invoke(); root.update()
            assert not s.policy(Path(M.DATA_ROOT)).get("enabled")
            M.messagebox.askyesno = lambda *a, **k: True
            ui["save"].invoke(); settle(win)
            assert s.policy(Path(M.DATA_ROOT))["enabled"] is True
            ui["auto"].set(False); ui["save"].invoke(); settle(win)
            assert s.policy(Path(M.DATA_ROOT))["enabled"] is False
            chosen = ui["tree"].selection()[:1]; ui["tree"].selection_set(chosen)
            entry = ui["state"]["entries"][chosen[0]]
            ui["delete"].invoke(); settle(win)
            assert not (Path(M.DATA_ROOT) / entry["relative"]).exists()
            assert not errors, errors
            win.destroy()
            M.TEST_MODE = True
            assert storage_ui.open_storage(M, root) is None
            M.TEST_MODE = False
            print("8.0.30 Windows UI: real settings/dialog, asynchronous preview, selection, cancel, explicit policy, confirmed cleanup and TEST guard OK", flush=True)
        finally:
            root.destroy()


if __name__ == "__main__":
    if "--ui-worker" in sys.argv:
        ui_checks()
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(StorageTests)
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
            raise SystemExit(1)
        if "--source-only" not in sys.argv:
            subprocess.run([sys.executable, "-B", __file__, "--ui-worker"], check=True)
