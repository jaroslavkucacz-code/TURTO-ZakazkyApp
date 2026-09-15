#!/usr/bin/env python3
"""Clean Windows runner: exact release binaries, real update/rollback, DB hashes."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ZakazkyApp_base_6.1"))
import updater_safety as safety


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def run(args, env, timeout=180):
    result = subprocess.run([str(a) for a in args], env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Process failed ({result.returncode}): {args}")


def wait_file(path, process, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return read(path)
        if process.poll() is not None:
            raise RuntimeError(f"Process exited before handshake: {process.returncode}")
        time.sleep(0.1)
    raise TimeoutError(f"Missing handshake: {path}")


def wait_idle(root):
    deadline = time.monotonic() + 60
    while True:
        try:
            safety.preflight_files(root)
            return
        except safety.UpdateBlocked:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def main():
    if os.name != "nt":
        raise RuntimeError("Frozen smoke must run on Windows")
    package_dir = Path(sys.argv[1])
    manifest_path = next(package_dir.rglob("latest-windows.preview.json"))
    manifest = read(manifest_path)
    version = manifest["version"]
    setup = next(package_dir.rglob(manifest["installer"]))
    update_zip = next(package_dir.rglob(manifest["package"]))
    assert safety.digest(setup) == manifest["installer_sha256"]
    assert safety.digest(update_zip) == manifest["sha256"]
    root = Path(tempfile.mkdtemp(prefix="turto-crm-808-smoke-"))
    print(f"Smoke workspace: {root}", flush=True)
    installed, data, local = root / "installed", root / "data", root / "local"
    result_file = root / "runtime-smoke.json"
    env = {**os.environ, "TURTO_CRM_DATA_ROOT": str(data), "LOCALAPPDATA": str(local), "TURTO_DISABLE_AUTO_UPDATE": "1", "TURTO_CRM_SMOKE_RESULT": str(result_file)}
    env.pop("TURTO_CRM_DATABASE", None)
    checks = []
    try:
        run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=" + str(installed)], env)
        checks.append("clean per-user installation")
        # Both installers must deliver the exact alpha-preserving artwork that
        # passed source validation, without any retired generated logo.
        for name in ("turto_logo.png", "turto_logo.ico", "turto_icon.png"):
            assert safety.digest(installed / "_internal" / name) == safety.digest(
                REPO / "ZakazkyApp_base_6.1" / name)
        assert not list(installed.rglob("turto_crm.ico"))
        assert not list(installed.rglob("turto_crm.png"))
        checks.append("exact transparent branding in installed application")
        run([sys.executable, REPO / "scripts/validate-811-taskbar.py", installed], env)
        checks.append("Windows Shell extracts transparent icons from the installed EXE and taskbar resource")
        main_exe = installed / "TURTO CRM.exe"
        print("Cold frozen runtime first start", flush=True)
        run([main_exe, "--smoke-test"], env)
        result = read(result_file)
        assert result["ok"] and result["frozen"] and result["version"] == version
        database = Path(result["database"])
        assert database.is_relative_to(data)
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE IF NOT EXISTS updater_808_sentinel(value TEXT)")
            db.execute("INSERT INTO updater_808_sentinel VALUES (?)", ("Příležitosti, poptávky a česká data – zachovat",))
            db.commit()
        before = safety.digest(database)
        checks.append("frozen runtime, schema, TkDnD and offer parser smoke")

        stage = local / "TURTO CRM/UpdaterRuntime"
        runtime, updater = safety.prepare_stage(installed / safety.UPDATER_EXE, stage)
        self_test = root / "updater-self-test.json"
        run([updater, "--self-test", self_test], env)
        assert read(self_test)["ok"] and read(self_test)["frozen"]
        checks.append("frozen onedir updater runtime")

        extract = root / "payload"
        with zipfile.ZipFile(update_zip) as z:
            z.extractall(extract)
        source = next(p for p in extract.iterdir() if p.is_dir())
        runtime_manifest = read(source / "version.json")
        assert runtime_manifest["source_commit"] == manifest["source_commit"]
        synthetic_version = version + "-ci.1"
        runtime_manifest["version"] = synthetic_version
        safety.write_json(source / "version.json", runtime_manifest)
        synthetic_zip = root / "synthetic-update.zip"
        with zipfile.ZipFile(synthetic_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for path in source.rglob("*"):
                if path.is_file():
                    z.write(path, Path(source.name) / path.relative_to(source))
        synthetic_sha = safety.digest(synthetic_zip)

        print("Frozen updater integration", flush=True)
        stop = root / "release-parent"
        parent_code = "import time; from pathlib import Path; p=Path(" + repr(str(stop)) + ");\nwhile not p.exists(): time.sleep(0.05)"
        parent = subprocess.Popen([sys.executable, "-c", parent_code], env=env)
        token = uuid.uuid4().hex
        proc = subprocess.Popen([str(updater), "--install", str(synthetic_zip), str(installed), str(parent.pid), "update", synthetic_version, synthetic_sha, "--handshake", token], cwd=runtime, env=env)
        try:
            ready = wait_file(stage / ("ready-" + token + ".json"), proc)
            assert ready["status"] == "ready" and ready["pid"] == proc.pid, ready
            assert parent.poll() is None, "Updater killed the live parent"
            assert read(installed / "version.json")["version"] == version
            assert safety.digest(database) == before
            time.sleep(0.3)
            assert parent.poll() is None and proc.poll() is None
            stop.write_text("exit normally")
            parent.wait(timeout=15)
            assert proc.wait(timeout=180) == 0
        finally:
            if parent.poll() is None:
                stop.write_text("exit normally")
                parent.wait(timeout=15)
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
        wait_idle(installed)
        assert read(installed / "version.json")["version"] == synthetic_version
        assert safety.digest(database) == before, "Frozen updater changed business DB bytes"
        log = read(data / "updates/last_update.json")
        assert log["to_version"] == synthetic_version
        snapshot = Path(log["program_snapshot"])
        assert safety.digest(snapshot) == log["program_snapshot_sha256"]
        assert Path(log["database_backup"]).is_file()
        checks.append("ready handshake and non-destructive wait for real live parent")
        checks.append("real frozen update, program snapshot and database backup")
        checks.append("byte-identical business database after update")

        run([main_exe, "--smoke-test"], env)
        assert read(result_file)["version"] == synthetic_version and read(result_file)["ok"]
        before_rollback = safety.digest(database)
        checks.append("full frozen runtime after update")
        token = uuid.uuid4().hex
        run([updater, "--install", snapshot, installed, "0", "rollback", version, log["program_snapshot_sha256"], "--handshake", token], env)
        wait_idle(installed)
        assert read(installed / "version.json")["version"] == version
        assert safety.digest(database) == before_rollback
        checks.append("real frozen rollback without reverting business data")
        run([main_exe, "--smoke-test"], env)
        assert read(result_file)["version"] == version and read(result_file)["ok"]
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT COUNT(*) FROM updater_808_sentinel").fetchone()[0] == 1
        before_repair = safety.digest(database)
        retired_assets = [folder / name for folder in (installed, installed / "_internal")
                          for name in ("turto_crm.ico", "turto_crm.png")]
        for path in retired_assets:
            path.write_bytes(b"retired generated logo")
        run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=" + str(installed)], env)
        assert safety.digest(database) == before_repair
        assert all(not path.exists() for path in retired_assets)
        checks.append("repair install removes retired generated logo files")
        checks.append("repair install over existing installation preserves data")
        uninstaller = next(installed.glob("unins*.exe"))
        run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], env)
        assert database.exists() and safety.digest(database) == before_repair
        checks.append("uninstall preserves business database bytes")
        report = {"ok": True, "version": version, "source_commit": manifest["source_commit"], "checks": checks, "installer_sha256": manifest["installer_sha256"], "package_sha256": manifest["sha256"], "eset_tested": False}
        safety.write_json(REPO / "dist/808-smoke-report.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    except BaseException:
        for path in data.glob("updates/*"):
            if path.suffix in {".json", ".log"} and path.is_file():
                print(f"\nDIAGNOSTIC {path}:\n{path.read_text(encoding='utf-8-sig', errors='replace')}", flush=True)
        raise


if __name__ == "__main__":
    main()
