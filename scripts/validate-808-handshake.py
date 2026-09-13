#!/usr/bin/env python3
"""Handshake cancellation, access-denial and cross-process lock regressions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

spec = importlib.util.spec_from_file_location("base808", Path(__file__).with_name("validate-808-updater.py"))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
u, s, p = base.updater, base.safety, base.policy


class HandshakeTests(unittest.TestCase):
    setUp = base.UpdaterSafetyTests.setUp
    assert_old_intact = base.UpdaterSafetyTests.assert_old_intact

    def test_cancellation_before_wait(self):
        u._READY_PATH = self.root / "ready-abc.json"
        s.write_json(self.root / "cancel-abc.json", {"cancelled": True})
        with mock.patch.object(s, "wait_for_process") as wait:
            with self.assertRaises(s.UpdateBlocked):
                u._wait_for_process(0)
        wait.assert_not_called()
        self.assert_old_intact()

    def test_cancellation_during_wait(self):
        u._READY_PATH = self.root / "ready-abc.json"
        def cancel(pid):
            s.write_json(self.root / "cancel-abc.json", {"cancelled": True})
        with mock.patch.object(s, "wait_for_process", side_effect=cancel):
            with self.assertRaises(s.UpdateBlocked):
                u._wait_for_process(0)
        self.assert_old_intact()

    def test_timeout_never_starts_backup_or_replacement(self):
        package = self.root / "update.zip"
        with zipfile.ZipFile(package, "w") as z:
            for path in self.new.rglob("*"):
                if path.is_file():
                    z.write(path, Path("payload") / path.relative_to(self.new))
        args = ["updater", "--install", str(package), str(self.old), "123456", "update", "8.0.8", s.digest(package), "--handshake", "a" * 32]
        with mock.patch.object(sys, "argv", args), mock.patch.object(u, "_wait_for_process", side_effect=s.UpdateBlocked("timeout")), mock.patch.object(u, "_database_backup") as backup, mock.patch.object(u, "_replace_program_with_rollback") as replace:
            with self.assertRaises(s.UpdateBlocked):
                u.main()
        backup.assert_not_called()
        replace.assert_not_called()
        self.assert_old_intact()

    def test_windows_access_denial_aborts_without_termination(self):
        k = mock.Mock()
        k.OpenProcess.return_value = None
        with mock.patch.object(s, "_kernel", return_value=k), mock.patch.object(s.os, "name", "nt"), mock.patch.object(s.ctypes, "get_last_error", return_value=5, create=True):
            with self.assertRaises(s.UpdateBlocked):
                s.wait_for_process(123456, 0.01)
        k.OpenProcess.assert_called_once_with(0x00100000, False, 123456)
        k.TerminateProcess.assert_not_called()
        k.WaitForSingleObject.assert_not_called()

    def test_windows_timeout_closes_synchronize_handle(self):
        k = mock.Mock()
        k.OpenProcess.return_value = 123
        k.WaitForSingleObject.return_value = 258
        with mock.patch.object(s, "_kernel", return_value=k), mock.patch.object(s.os, "name", "nt"):
            with self.assertRaises(s.UpdateBlocked):
                s.wait_for_process(123456, 0.01)
        k.OpenProcess.assert_called_once_with(0x00100000, False, 123456)
        k.CloseHandle.assert_called_once_with(123)
        k.TerminateProcess.assert_not_called()

    def test_os_lock_works_across_real_processes(self):
        lock = self.root / "cross-process.lock"
        code = "import sys; from pathlib import Path; sys.path.insert(0," + repr(str(base.BASE)) + "); from updater_safety import FileLock\nwith FileLock(Path(sys.argv[1])):\n print('ready', flush=True)\n sys.stdin.readline()"
        process = subprocess.Popen([sys.executable, "-c", code, str(lock)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "ready")
            with self.assertRaises(s.UpdateBlocked):
                with s.FileLock(lock):
                    pass
        finally:
            process.communicate("\n", timeout=10)
        self.assertEqual(process.returncode, 0)
        with s.FileLock(lock):
            pass

    def test_ui_timeout_cancels_without_closing_or_retrying(self):
        package = self.root / "download.zip"
        package.write_bytes(b"zip")
        M = type("M", (), {"ROOT": self.old, "APP_VERSION": "8.0.7", "_turto_windows_expected_update_sha256": "a" * 64, "set_setting": mock.Mock(), "messagebox": mock.Mock()})
        updates = type("Updates", (), {"OFFICIAL_UPDATE_ROOT": "https://example.invalid", "_log": mock.Mock()})
        app = type("App", (), {"after": mock.Mock(), "close_app": mock.Mock(), "title": mock.Mock(), "configure": mock.Mock()})()
        process = mock.Mock(pid=123456, poll=mock.Mock(return_value=None))
        with mock.patch.object(p.subprocess, "Popen", return_value=process) as spawn:
            p._launch_frozen_updater(M, updates, app, "8.0.8", package)
        token = spawn.call_args.args[0][-1]
        with mock.patch.object(p, "_UPDATER_READY_TIMEOUT", -1):
            app.after.call_args.args[1]()
        app.close_app.assert_not_called()
        self.assertTrue((p._updater_stage_root() / ("cancel-" + token + ".json")).is_file())
        receipt = json.loads((p._updater_stage_root() / "receipt.json").read_text(encoding="utf-8"))
        self.assertFalse(receipt["complete"])
        with self.assertRaises(p.UpdaterLaunchBlockedError):
            p._launch_frozen_updater(M, updates, app, "8.0.8", package)
        self.assert_old_intact()


if __name__ == "__main__":
    unittest.main(verbosity=2)
