#!/usr/bin/env python3
"""Legacy SQLite backup sets: retention, races, Windows locks and WAL restore."""
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
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("storage830", REPO / "scripts/validate-830-storage.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
s = old.s


class LegacyTests(old.StorageTests):
    # Reuse fixtures, not inherited test execution below.
    def setUp(self):
        super().setUp()
        for db in (self.root / "backup").glob("*.db"):
            dt = db.stat().st_mtime
            shm = db.with_name(db.name + "-shm")
            shm.write_bytes(b"old shared memory")
            os.utime(shm, (dt, dt))

    def legacy(self):
        return s.build_plan(self.root, self.db, include_legacy=True)

    def groups(self):
        return [e for e in self.legacy() if e["eligible"] and e.get("members")]

    def preserve(self, entry):
        for m in entry["members"]:
            self.assertTrue((self.root / m["relative"]).exists(), m)

    def test_831_explicit_preview_counts_retains_and_does_not_mutate(self):
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertFalse(any(e["eligible"] and e["kind"] == "záloha" for e in self.plan()))
        plan = self.legacy()
        backups = [e for e in plan if e["kind"] == "záloha"]
        self.assertEqual(len(backups), 12)
        self.assertEqual(sum(e["eligible"] for e in backups), 7)
        self.assertEqual(sum(e["size"] for e in backups), sum(p.stat().st_size for p in (self.root / "backup").iterdir()))
        self.assertFalse(any(e["relative"].endswith("-shm") for e in plan))
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()})
        with self.assertRaises(ValueError):
            s.execute(self.root, self.db, self.groups()[:1])

    def test_831_changed_new_and_missing_sidecars_reject_stale_preview(self):
        e = self.groups()[0]
        side = self.root / e["members"][1]["relative"]
        side.write_bytes(b"changed")
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [e], include_legacy=True)
        self.preserve(e)
        e = self.groups()[0]
        (self.root / (e["relative"] + "-wal")).write_bytes(b"new")
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [e], include_legacy=True)
        e = self.groups()[0]
        (self.root / e["members"][1]["relative"]).unlink()
        with self.assertRaises(ValueError): s.execute(self.root, self.db, [e], include_legacy=True)

    def test_831_member_references_and_hardlinks_protect_entire_backup(self):
        e = self.groups()[0]
        s.safety.write_json(self.root / "updates" / "last_update.json", {"database_backup": e["members"][1]["relative"]})
        self.assertFalse(next(v for v in self.legacy() if v["relative"] == e["relative"])["eligible"])
        e = self.groups()[0]
        os.link(self.root / e["members"][1]["relative"], self.root / "alias-shm")
        self.assertFalse(next(v for v in self.legacy() if v["relative"] == e["relative"])["eligible"])
        e = self.groups()[0]
        manual = self.root / "backup" / "zakazky_manual_20200101_000000.db"
        shutil.copyfile(self.db, manual)
        manual.with_name(manual.name + "-shm").write_bytes(b"manual")
        self.assertFalse(next(v for v in self.legacy() if v["relative"] == manual.relative_to(self.root).as_posix())["eligible"])

    def test_831_automatic_policy_never_includes_legacy_groups(self):
        selected = self.groups()
        s.save_policy(self.root, self.db, True)
        policy = s.policy(self.root)
        policy["enabled_since"] = (datetime.now() - timedelta(days=10)).isoformat()
        s.safety.write_json(self.root / s.POLICY_NAME, policy)
        s.run_daily(self.root, self.db)
        for e in selected: self.preserve(e)

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_open_member_or_live_sqlite_connection_prevents_any_deletion(self):
        e = self.groups()[0]
        for member in e["members"]:
            with (self.root / member["relative"]).open("rb"):
                result = s.execute(self.root, self.db, [e], include_legacy=True)
            self.assertTrue(result["error"])
            self.assertEqual(result["completed"], [])
            self.preserve(e)
        with closing(sqlite3.connect(self.root / e["relative"])) as con:
            con.execute("SELECT * FROM projects").fetchall()
            result = s.execute(self.root, self.db, [e], include_legacy=True)
        self.assertTrue(result["error"])
        self.preserve(e)
        self.unchanged()

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_new_opens_from_another_process_blocked_until_release(self):
        e = self.groups()[0]
        paths = [self.root / m["relative"] for m in e["members"]]
        code = "import sys; f=open(sys.argv[1], 'rb'); f.close()"
        with s.LockedBackup(paths):
            for path in paths:
                result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
        for path in paths:
            with path.open("rb") as stream: self.assertTrue(stream.read(1))

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_deletion_groups_and_durable_member_log(self):
        e = self.groups()[0]
        result = s.execute(self.root, self.db, [e], include_legacy=True)
        self.assertFalse(result["error"], result)
        self.assertEqual(result["bytes"], e["size"])
        self.assertEqual({m["relative"] for m in result["completed"]}, {m["relative"] for m in e["members"]})
        for m in e["members"]: self.assertFalse((self.root / m["relative"]).exists())
        self.assertTrue(old.data_location.validate_database(Path(result["backup"]))["ok"])
        self.unchanged()

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_archive_preserves_nonempty_wal_and_restores_committed_data(self):
        e = self.groups()[0]
        target = self.root / e["relative"]
        stamp = target.stat().st_mtime
        staging = Path(self.temp.name) / "source.db"
        old.seed(staging)
        with closing(sqlite3.connect(staging)) as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
            con.execute("UPDATE projects SET name='Změna pouze ve WAL'"); con.commit()
            for suffix in ("", "-wal", "-shm"):
                out = target.with_name(target.name + suffix)
                shutil.copyfile(staging.with_name(staging.name + suffix), out)
                os.utime(out, (stamp, stamp))
        e = next(v for v in self.groups() if v["relative"] == e["relative"])
        expected = {m["relative"]: s.safety.digest(self.root / m["relative"]) for m in e["members"]}
        dest = Path(self.temp.name) / "external"; dest.mkdir()
        result = s.execute(self.root, self.db, [e], archive=dest, include_legacy=True)
        self.assertFalse(result["error"], result)
        for m in result["completed"]:
            self.assertEqual(s.safety.digest(Path(result["archive"]) / m["relative"]), expected[m["relative"]])
            self.assertEqual(m["sha256"], expected[m["relative"]])
        with closing(sqlite3.connect(Path(result["archive"]) / e["relative"])) as restored:
            self.assertEqual(restored.execute("SELECT name FROM projects").fetchone()[0], "Změna pouze ve WAL")
        self.unchanged()

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_copy_failure_or_new_reference_preserves_whole_group(self):
        e = self.groups()[0]
        dest = Path(self.temp.name) / "external"; dest.mkdir()
        original = s._archive_locked
        def fail_second(locked, source, target):
            if str(source).endswith("-shm"): raise OSError("simulated disk full")
            return original(locked, source, target)
        with patch.object(s, "_archive_locked", side_effect=fail_second):
            result = s.execute(self.root, self.db, [e], archive=dest, include_legacy=True)
        self.assertTrue(result["error"]); self.assertEqual(result["completed"], [])
        self.preserve(e)
        def add_reference(locked, source, target):
            sha = original(locked, source, target)
            s.safety.write_json(self.root / "updates" / "last_update.json", {"database_backup": e["relative"]})
            return sha
        with patch.object(s, "_archive_locked", side_effect=add_reference):
            result = s.execute(self.root, self.db, [e], archive=dest, include_legacy=True)
        self.assertTrue(result["error"]); self.assertEqual(result["completed"], [])
        self.preserve(e)

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_corrupt_archive_and_unwritable_log_preserve_originals(self):
        e = self.groups()[0]
        dest = Path(self.temp.name) / "external"; dest.mkdir()
        digest = s.safety.digest
        def corrupt(path):
            return "bad hash" if str(path).endswith(".partial") else digest(path)
        with patch.object(s.safety, "digest", side_effect=corrupt):
            result = s.execute(self.root, self.db, [e], archive=dest, include_legacy=True)
        self.assertTrue(result["error"]); self.assertEqual(result["completed"], [])
        self.preserve(e)
        write = s.safety.write_json
        def fail_pending(path, data):
            if data.get("pending_group"): raise OSError("log write denied")
            return write(path, data)
        with patch.object(s.safety, "write_json", side_effect=fail_pending):
            with self.assertRaises(OSError): s.execute(self.root, self.db, [e], include_legacy=True)
        self.preserve(e)

    @unittest.skipUnless(os.name == "nt", "Requires real Windows exclusive handles")
    def test_831_partial_delete_never_leaves_main_database_without_its_sidecars(self):
        e = self.groups()[0]
        original = s.LockedBackup.mark_delete
        def fail_sidecar(locked, path):
            if str(path).endswith("-shm"): raise OSError("simulated sidecar delete failure")
            return original(locked, path)
        with patch.object(s.LockedBackup, "mark_delete", fail_sidecar):
            result = s.execute(self.root, self.db, [e], include_legacy=True)
        self.assertTrue(result["error"])
        self.assertFalse((self.root / e["relative"]).exists())
        self.assertTrue((self.root / e["members"][1]["relative"]).exists())
        self.assertEqual(result["completed"][0]["relative"], e["relative"])
        self.assertIn("pending_group", json.loads(Path(result["log"]).read_text(encoding="utf-8")))
        self.unchanged()


if __name__ == "__main__":
    suite = unittest.TestSuite(LegacyTests(name) for name in sorted(vars(LegacyTests)) if name.startswith("test_831_"))
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful(): raise SystemExit(1)
