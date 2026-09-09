from __future__ import annotations

from datetime import datetime
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
import zipfile

import data_location

MAIN_EXE = "TURTO CRM.exe"
UPDATER_EXE = "TURTO CRM Updater.exe"
PROGRAM_DIRS = {"_internal", "_runtime", "offers_engine", "price_lists_domain", "_rollback"}
PROGRAM_FILES = {
    MAIN_EXE,
    UPDATER_EXE,
    "turto_logo.ico",
    "turto_logo.png",
    "turto_crm.ico",
    "turto_crm.png",
    "README.txt",
    "version.json",
}


def _wait_for_process(pid: int) -> None:
    if pid <= 0:
        return
    for _ in range(240):
        try:
            os.kill(pid, 0)
            time.sleep(0.25)
        except Exception:
            break


def _version_from_install(target: Path) -> str:
    manifest = target / "version.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        value = str(data.get("version") or "").strip()
        if value:
            return value
    except Exception:
        pass
    return "nezjištěná"


def _database_backup(label: str) -> Path | None:
    source = data_location.database_path()
    if not source.is_file():
        return None
    root = data_location.data_root()
    backup_dir = root / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"zakazky_{label}_{stamp}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return target


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_program(target: Path, version: str) -> tuple[Path, str] | None:
    if not target.is_dir():
        return None
    root = data_location.data_root() / "updates" / "rollback"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (version or "unknown"))
    package = root / f"TURTO_CRM_{safe}_{stamp}.zip"
    folder = f"TURTO_CRM_{safe}"

    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in target.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(target)
            if "__pycache__" in rel.parts or path.suffix.lower() == ".pyc":
                continue
            if path.name.casefold().startswith("unins"):
                # Inno Setup owns its own uninstaller metadata; program rollback
                # never replaces it.
                continue
            archive.write(path, Path(folder) / rel)
    digest = _hash_file(package)
    (root / "latest.json").write_text(
        json.dumps(
            {"version": version, "package": str(package), "sha256": digest},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return package, digest


def _source_root(package: Path, temp_root: Path) -> Path:
    with zipfile.ZipFile(package) as archive:
        archive.extractall(temp_root)
    entries = list(temp_root.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return temp_root


def _clean_program(target: Path) -> None:
    for directory in PROGRAM_DIRS:
        shutil.rmtree(target / directory, ignore_errors=True)
    for name in PROGRAM_FILES:
        path = target / name
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except FileNotFoundError:
            pass


def _copy_release(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        if "__pycache__" in rel.parts or path.suffix.lower() == ".pyc":
            continue
        destination = target / rel
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _validate_release(target: Path) -> None:
    main = target / MAIN_EXE
    updater = target / UPDATER_EXE
    version = target / "version.json"
    if not main.is_file():
        raise RuntimeError(f"Aktualizace neobsahuje {MAIN_EXE}.")
    if not updater.is_file():
        raise RuntimeError(f"Aktualizace neobsahuje {UPDATER_EXE}.")
    if not version.is_file():
        raise RuntimeError("Aktualizace neobsahuje version.json.")


def _restart(target: Path) -> None:
    executable = target / MAIN_EXE
    subprocess.Popen([str(executable)], cwd=str(target))


def _parse_arguments() -> tuple[Path, Path, int, str]:
    if len(sys.argv) >= 5 and sys.argv[1] == "--install":
        package = Path(sys.argv[2])
        target = Path(sys.argv[3])
        pid = int(sys.argv[4])
        mode = str(sys.argv[5] if len(sys.argv) > 5 else "update").strip().lower()
        return package, target, pid, mode
    raise ValueError("Neplatné parametry aktualizace TURTO CRM 8.x.")


def main() -> None:
    package, target, pid, mode = _parse_arguments()
    if not package.is_file():
        raise FileNotFoundError(package)
    _wait_for_process(pid)

    current_version = _version_from_install(target)
    label = "pred_navratem" if mode == "rollback" else "pred_aktualizaci"
    db_backup = _database_backup(label)
    program_snapshot = _snapshot_program(target, current_version)

    with tempfile.TemporaryDirectory(prefix="turto_update_payload_") as temp:
        source = _source_root(package, Path(temp))
        _clean_program(target)
        _copy_release(source, target)
        _validate_release(target)

    log_root = data_location.data_root() / "updates"
    log_root.mkdir(parents=True, exist_ok=True)
    (log_root / "last_update.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "from_version": current_version,
                "to_version": _version_from_install(target),
                "database": str(data_location.database_path()),
                "database_backup": str(db_backup) if db_backup else "",
                "program_snapshot": str(program_snapshot[0]) if program_snapshot else "",
                "installed_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    _restart(target)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            root = data_location.data_root() / "updates"
            root.mkdir(parents=True, exist_ok=True)
            (root / "update_error.log").write_text(str(exc), encoding="utf-8")
        except Exception:
            pass
        raise
