#!/usr/bin/env python3
"""Behavioral updater regressions, including real Windows locks/process waits."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
sys.path.insert(0, str(BASE))
import updater_safety as safety


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


updater = load("updater_808_test", REPO / "build/windows/updater_800.pyw")
policy = load("policy_808_test", BASE / "price_lists_domain/platform/exe_distribution.py")


def release(root, version="8.0.7", marker="old"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "TURTO CRM.exe").write_bytes(("main-" + marker).encode())
    (root / safety.UPDATER_EXE).write_bytes(("updater-" + marker).encode())
    (root / safety.RUNTIME_DIR).mkdir(exist_ok=True)
    (root / safety.RUNTIME_DIR / "python314.dll").write_bytes(("runtime-" + marker).encode())
    (root / "_internal").mkdir(exist_ok=True)
    (root / "_internal/python314.dll").write_bytes(b"main-runtime")
    (root / "_internal" / (marker + ".txt")).write_text(marker)
    (root / "version.json").write_text(json.dumps({"version": version, "channel": "windows", "build": "test", "updater_format": "onedir-v1"}), encoding="utf-8")


def tree_hash(root):
    return {p.relative_to(root).as_posix(): safety.digest(p) for p in safety.plain_files(root)}


class UpdaterSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turto-808-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local"), "TURTO_CRM_DATA_ROOT": str(self.root / "data")})
        self.env.start()
        self.addCleanup(self.env.stop)
        for name, value in (("data_root", self.root / "data"), ("database_path", self.root / "data/zakazky.db")):
            patch = mock.patch.object(updater.data_location, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        self.old = self.root / "installed"
        self.new = self.root / "payload"
        release(self.old)
        release(self.new, "8.0.8", "new")
        (self.old / "unins000.exe").write_bytes(b"uninstaller")
        (self.old / "unins000.dat").write_bytes(b"metadata")
        (self.root / "data").mkdir()
        (self.root / "data/zakazky.db").write_bytes(b"business-data-sentinel")
        self.before = tree_hash(self.old)
        updater._READY_PATH = None
        updater._READY_SENT = False

    def update(self):
        return updater._replace_program_with_rollback(self.new, self.old, current_version="8.0.7", expected_version="8.0.8")

    def assert_old_intact(self):
        self.assertEqual(tree_hash(self.old), self.before)
        self.assertEqual((self.root / "data/zakazky.db").read_bytes(), b"business-data-sentinel")

    def test_success_and_snapshot_preserve_data_and_uninstaller(self):
        snapshot, sha = self.update()
        self.assertEqual(safety.digest(snapshot), sha)
        self.assertEqual(updater._validate_release(self.old, installed=True), "8.0.8")
        self.assertFalse((self.old / "_internal/old.txt").exists())
        self.assertEqual((self.old / "unins000.dat").read_bytes(), b"metadata")
        self.assertEqual((self.root / "data/zakazky.db").read_bytes(), b"business-data-sentinel")
        with zipfile.ZipFile(snapshot) as z:
            self.assertFalse(any(Path(n).name.startswith("unins") for n in z.namelist()))

    def test_preparation_copy_failure_leaves_original_untouched(self):
        with mock.patch.object(updater, "_copy_release", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(RuntimeError, "nedotčená"):
                self.update()
        self.assert_old_intact()

    def test_initial_rename_failure_leaves_original_untouched(self):
        with mock.patch.object(safety, "rename_directory", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeError, "nedotčená"):
                self.update()
        self.assert_old_intact()

    def test_second_rename_failure_restores_original_directory(self):
        rename = safety.rename_directory
        def fail_new(source, target):
            if source.name == "new":
                raise PermissionError("locked")
            rename(source, target)
        with mock.patch.object(safety, "rename_directory", side_effect=fail_new):
            with self.assertRaisesRegex(RuntimeError, "automaticky obnovena"):
                self.update()
        self.assert_old_intact()

    def test_recovery_failure_preserves_original_directory(self):
        rename = safety.rename_directory
        def fail_new_and_recovery(source, target):
            if source.name in {"new", "previous"}:
                raise PermissionError("locked")
            rename(source, target)
        with mock.patch.object(safety, "rename_directory", side_effect=fail_new_and_recovery):
            with self.assertRaisesRegex(RuntimeError, "zachován"):
                self.update()
        previous = list(self.root.glob(".installed.update-*/previous"))
        self.assertEqual(len(previous), 1)
        self.assertEqual(tree_hash(previous[0]), self.before)
        safety.recover_interrupted(self.old)
        self.assert_old_intact()

    def test_snapshot_rollback_preserves_data(self):
        snapshot, sha = self.update()
        updater._verify_package_hash(snapshot, sha)
        updater._restore_program_snapshot(snapshot, self.old, "8.0.7")
        self.assert_old_intact()

    def test_data_inside_install_blocks_update(self):
        with mock.patch.object(updater.data_location, "database_path", return_value=self.old / "business.db"):
            with self.assertRaisesRegex(RuntimeError, "uvnitř instalace"):
                self.update()
        self.assert_old_intact()

    def test_bad_payload_version_leaves_original(self):
        with self.assertRaises(RuntimeError):
            updater._replace_program_with_rollback(self.new, self.old, current_version="8.0.7", expected_version="9.9.9")
        self.assert_old_intact()

    def test_missing_runtime_is_rejected(self):
        shutil.rmtree(self.new / safety.RUNTIME_DIR)
        with self.assertRaises(RuntimeError):
            self.update()
        self.assert_old_intact()

    def test_payload_cannot_overwrite_uninstaller(self):
        (self.new / "unins000.dat").write_bytes(b"bad")
        with self.assertRaisesRegex(RuntimeError, "odinstalační"):
            self.update()
        self.assert_old_intact()

    def test_payload_cannot_contain_database(self):
        (self.new / "business.sqlite3").write_bytes(b"bad")
        with self.assertRaises(RuntimeError):
            self.update()
        self.assert_old_intact()

    def test_stage_reuses_identical_files_without_copying(self):
        stage = self.root / "stage"
        root, exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        before = exe.stat().st_mtime_ns
        with mock.patch.object(shutil, "copy2", side_effect=AssertionError("must not copy")):
            again, same_exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage, copy_file=shutil.copy2)
        self.assertEqual(root, again)
        self.assertEqual(before, same_exe.stat().st_mtime_ns)

    def test_quarantined_stage_is_not_recreated(self):
        stage = self.root / "stage"
        runtime, exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        exe.unlink()
        for _ in range(2):
            with self.assertRaises(safety.UpdateBlocked):
                safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        self.assertFalse(exe.exists())

    def test_missing_dependency_is_not_recreated(self):
        stage = self.root / "stage"
        runtime, exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        dll = runtime / safety.RUNTIME_DIR / "python314.dll"
        dll.unlink()
        with self.assertRaises(safety.UpdateBlocked):
            safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        self.assertFalse(dll.exists())

    def test_modified_stage_is_not_overwritten(self):
        stage = self.root / "stage"
        _, exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        exe.write_bytes(b"changed")
        with self.assertRaises(safety.UpdateBlocked):
            safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        self.assertEqual(exe.read_bytes(), b"changed")

    def test_failed_stage_copy_is_not_retried(self):
        stage = self.root / "stage"
        with self.assertRaises(safety.UpdateBlocked):
            safety.prepare_stage(self.old / safety.UPDATER_EXE, stage, copy_file=mock.Mock(side_effect=PermissionError("security block")))
        with self.assertRaises(safety.UpdateBlocked):
            safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        self.assertFalse((stage / "runtime" / safety.UPDATER_EXE).exists())

    def test_new_official_build_can_replace_previous_stage(self):
        stage = self.root / "stage"
        _, exe = safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        exe.unlink()
        _, new_exe = safety.prepare_stage(self.new / safety.UPDATER_EXE, stage)
        self.assertEqual(new_exe.read_bytes(), (self.new / safety.UPDATER_EXE).read_bytes())

    def test_locked_stage_cannot_be_changed(self):
        stage = self.root / "stage"
        with safety.FileLock(safety.stage_lock(stage)):
            with self.assertRaises(safety.UpdateBlocked):
                safety.prepare_stage(self.old / safety.UPDATER_EXE, stage)
        self.assertFalse(stage.exists())

    def test_wait_timeout_does_not_kill_live_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            with self.assertRaises(safety.UpdateBlocked):
                safety.wait_for_process(process.pid, 0.08)
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=10)
        self.assert_old_intact()

    def test_wait_completed_process(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"])
        reaper = threading.Thread(target=process.wait)
        reaper.start()
        safety.wait_for_process(process.pid, 5)
        reaper.join(5)
        self.assertEqual(process.returncode, 0)

    def test_wait_rejects_own_pid(self):
        with self.assertRaises(safety.UpdateBlocked):
            safety.wait_for_process(os.getpid(), 0)

    def test_bad_zip_paths_duplicates_and_symlinks(self):
        for i, names in enumerate((["../escape"], ["C:/escape"], ["safe/file:stream"], ["CON.txt"], ["foo."], ["a", "A"])):
            archive = self.root / f"bad-{i}.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for name in names:
                    z.writestr(name, b"bad")
            out = self.root / f"out-{i}"
            out.mkdir()
            with self.assertRaises(RuntimeError):
                updater._safe_extract(archive, out)
            self.assertFalse(list(out.iterdir()))
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as z:
            info = zipfile.ZipInfo("link")
            info.external_attr = 0o120777 << 16
            z.writestr(info, b"outside")
        out = self.root / "link-out"
        out.mkdir()
        with self.assertRaises(RuntimeError):
            updater._safe_extract(archive, out)
        self.assert_old_intact()

    def test_hash_mismatch_is_rejected(self):
        package = self.root / "package.zip"
        package.write_bytes(b"payload")
        self.assertEqual(updater._verify_package_hash(package, safety.digest(package)), safety.digest(package))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            updater._verify_package_hash(package, "0" * 64)

    def test_manifest_rejects_untrusted_urls_paths_and_hashes(self):
        good = {"format": policy.WINDOWS_MANIFEST_FORMAT, "channel": "windows", "version": "8.0.8", "package": "TURTO_CRM_Update_8.0.8.zip", "sha256": "a" * 64}
        self.assertEqual(policy._validate_windows_manifest(good)["version"], "8.0.8")
        for change in ({"format": "legacy"}, {"channel": "legacy"}, {"package": "../bad.zip"}, {"sha256": "123"}, {"download_url": "https://example.invalid/bad.zip"}):
            with self.assertRaises(ValueError):
                policy._validate_windows_manifest({**good, **change})

    def test_downloader_independently_verifies_bytes(self):
        raw = b"official bytes"
        M = type("M", (), {"DATA_ROOT": self.root / "data"})
        updates = type("Updates", (), {"OFFICIAL_UPDATE_ROOT": "https://example.invalid"})
        good = {"format": policy.WINDOWS_MANIFEST_FORMAT, "channel": "windows", "version": "8.0.8", "package": "TURTO_CRM_Update_8.0.8.zip", "sha256": hashlib.sha256(raw).hexdigest()}
        with mock.patch.object(policy.urllib.request, "urlopen", return_value=io.BytesIO(raw)):
            path = policy._download_windows_package(M, updates, good)
        self.assertEqual(path.read_bytes(), raw)
        self.assertEqual(M._turto_windows_expected_update_sha256, good["sha256"])
        with mock.patch.object(policy.urllib.request, "urlopen", return_value=io.BytesIO(b"modified")):
            with self.assertRaises(ValueError):
                policy._download_windows_package(M, updates, good)
        self.assertEqual(path.read_bytes(), raw)

    def test_ui_waits_for_actual_readiness_before_closing(self):
        package = self.root / "download.zip"
        package.write_bytes(b"zip")
        M = type("M", (), {"ROOT": self.old, "APP_VERSION": "8.0.7", "_turto_windows_expected_update_sha256": "a" * 64, "set_setting": mock.Mock(), "messagebox": mock.Mock()})
        updates = type("Updates", (), {"OFFICIAL_UPDATE_ROOT": "https://example.invalid", "_log": mock.Mock()})
        app = type("App", (), {"after": mock.Mock(), "close_app": mock.Mock()})()
        process = mock.Mock(pid=123456, poll=mock.Mock(return_value=None))
        with mock.patch.object(policy.subprocess, "Popen", return_value=process) as spawn:
            policy._launch_frozen_updater(M, updates, app, "8.0.8", package)
        callback = app.after.call_args.args[1]
        callback()
        app.close_app.assert_not_called()
        token = spawn.call_args.args[0][-1]
        safety.write_json(policy._updater_stage_root() / ("ready-" + token + ".json"), {"status": "ready", "token": token, "pid": process.pid})
        callback()
        app.close_app.assert_called_once()

    def test_safe_channel_does_not_bootstrap_through_legacy_updater(self):
        self.assertEqual(policy.WINDOWS_MANIFEST, "latest-windows-v2.json")
        self.assertNotEqual(policy.WINDOWS_MANIFEST, policy.LEGACY_WINDOWS_MANIFEST)

    @unittest.skipUnless(os.name == "nt", "Windows file sharing semantics")
    def test_real_windows_exclusive_file_lock_aborts_before_change(self):
        import ctypes
        from ctypes import wintypes as wt
        k = safety._kernel()
        k.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
        k.CreateFileW.restype = wt.HANDLE
        handle = k.CreateFileW(str(self.old / "TURTO CRM.exe"), 0x80000000, 0, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            with self.assertRaises((RuntimeError, PermissionError)):
                self.update()
        finally:
            k.CloseHandle(handle)
        self.assert_old_intact()

    @unittest.skipUnless(os.name == "nt", "Windows directory junction")
    def test_windows_junction_is_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "sentinel.txt").write_bytes(b"keep")
        link = self.old / "junction"
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
        try:
            with self.assertRaises(safety.UpdateBlocked):
                list(safety.plain_files(self.old))
            self.assertEqual((outside / "sentinel.txt").read_bytes(), b"keep")
        finally:
            link.rmdir()


if __name__ == "__main__":
    unittest.main(verbosity=2)
