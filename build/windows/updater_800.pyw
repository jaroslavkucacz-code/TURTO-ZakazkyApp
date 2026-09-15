from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

import data_location
import updater_safety as safety

MAIN_EXE = "TURTO CRM.exe"
UPDATER_EXE = "TURTO CRM Updater.exe"
WINDOWS_CHANNEL = "windows"
PROGRAM_DIRS = {"_internal", "_runtime", "_updater_runtime", "offers_engine", "price_lists_domain", "_rollback"}
PROGRAM_FILES = {MAIN_EXE, UPDATER_EXE, "turto_logo.ico", "turto_logo.png", "turto_crm.ico", "turto_crm.png", "README.txt", "version.json"}
FORBIDDEN_PAYLOAD_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".py", ".pyw", ".pyc"}
MAX_UNCOMPRESSED_PAYLOAD = 2 * 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_READY_PATH = None
_READY_SENT = False
_PROGRESS = None


def _report(stage, fraction=None, detail=None):
    if _PROGRESS is not None:
        _PROGRESS(stage, fraction, detail)


def _stage_root() -> Path:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    return Path(local) / "TURTO CRM" / "UpdaterRuntime" if local else Path(tempfile.gettempdir()) / "turto_crm_updater_stage"


def _check_cancelled() -> None:
    if _READY_PATH is not None and _READY_PATH.with_name(_READY_PATH.name.replace("ready-", "cancel-", 1)).exists():
        raise safety.UpdateBlocked("Spuštění aktualizace bylo zrušeno. Instalace zůstala nedotčená.")


def _wait_for_process(pid: int) -> None:
    _check_cancelled()
    safety.wait_for_process(pid)
    _check_cancelled()


def _read_version_manifest(root: Path) -> dict:
    try:
        value = json.loads((root / "version.json").read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"Chybí nebo je neplatný version.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("version.json nemá objektový formát.")
    return value


def _version_from_install(root: Path) -> str:
    try:
        return str(_read_version_manifest(root).get("version") or "nezjištěná")
    except Exception:
        return "nezjištěná"


def _database_backup(label: str) -> Path | None:
    source = data_location.database_path()
    if not source.is_file():
        return None
    return data_location.backup_database(source, label=label, backup_root=data_location.data_root())


def _hash_file(path: Path) -> str:
    return safety.digest(path)


def _verify_package_hash(package: Path, expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise ValueError("Updater nedostal platný očekávaný SHA-256 otisk balíčku.")
    actual = _hash_file(package)
    if expected != actual:
        raise ValueError("Aktualizační ZIP neodpovídá oficiálnímu SHA-256 otisku.")
    return actual


def _snapshot_program(target: Path, version: str) -> tuple[Path, str] | None:
    if not target.is_dir():
        return None
    root = data_location.data_root() / "updates" / "rollback"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in version)
    package = root / f"TURTO_CRM_{safe}_{datetime.now():%Y%m%d_%H%M%S_%f}.zip"
    with zipfile.ZipFile(package, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in safety.plain_files(target):
            if path.name.casefold().startswith("unins"):
                continue
            rel = path.relative_to(target)
            if "__pycache__" in rel.parts or path.suffix.lower() == ".pyc":
                continue
            archive.write(path, Path(f"TURTO_CRM_{safe}") / rel)
    sha = _hash_file(package)
    safety.write_json(root / "latest.json", {"version": version, "package": str(package), "sha256": sha})
    return package, sha


def _safe_extract(package: Path, temp_root: Path) -> None:
    root = temp_root.resolve()
    total = 0
    seen = set()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > 100000:
            raise RuntimeError("Aktualizační ZIP obsahuje příliš mnoho souborů.")
        validated = []
        for info in entries:
            raw = str(info.filename or "").replace("\\", "/")
            rel = PurePosixPath(raw)
            parts = raw.rstrip("/").split("/")
            if not raw or rel.is_absolute() or any(p in {"", ".", ".."} or ":" in p or p.endswith((".", " ")) or p.split(".")[0].upper() in reserved for p in parts):
                raise RuntimeError("Aktualizační ZIP obsahuje nepovolenou cestu.")
            key = "/".join(parts).casefold()
            if key in seen:
                raise RuntimeError("Aktualizační ZIP obsahuje kolidující názvy souborů.")
            seen.add(key)
            if ((info.external_attr >> 16) & 0o170000) == stat.S_IFLNK or info.flag_bits & 1:
                raise RuntimeError("Aktualizační ZIP obsahuje odkaz nebo šifrovaný soubor.")
            total += info.file_size
            if total > MAX_UNCOMPRESSED_PAYLOAD:
                raise RuntimeError("Aktualizační ZIP překračuje povolenou rozbalenou velikost.")
            destination = root.joinpath(*parts)
            if not destination.resolve().is_relative_to(root):
                raise RuntimeError("Aktualizační ZIP zapisuje mimo pracovní složku.")
            validated.append((info, destination))
        for info, destination in validated:
            if info.is_dir() or info.filename.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, destination.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)


def _source_root(package: Path, temp_root: Path) -> Path:
    _safe_extract(package, temp_root)
    entries = [p for p in temp_root.iterdir() if p.name != "__MACOSX"]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else temp_root


def _validate_release(target: Path, expected_version: str | None = None, *, installed: bool = False) -> str:
    for name in (MAIN_EXE, UPDATER_EXE):
        if not (target / name).is_file() or (target / name).stat().st_size == 0:
            raise RuntimeError(f"Aktualizace neobsahuje {name}.")
    manifest = _read_version_manifest(target)
    version = str(manifest.get("version") or "").strip()
    if not version or str(manifest.get("channel") or "").casefold() != WINDOWS_CHANNEL:
        raise RuntimeError("Payload nemá platnou verzi a Windows kanál TURTO CRM.")
    if expected_version and version != expected_version:
        raise RuntimeError(f"Verze payloadu {version} neodpovídá očekávané verzi {expected_version}.")
    if manifest.get("updater_format") == "onedir-v1":
        safety.bundle_files(target / UPDATER_EXE)
        if not list((target / "_internal").glob("python*.dll")):
            raise RuntimeError("Chybí Python runtime hlavního programu.")
    for path in safety.plain_files(target):
        if path.name.casefold().startswith("unins"):
            if installed:
                continue
            raise RuntimeError("Payload nesmí přepisovat Inno Setup odinstalační metadata.")
        if path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES:
            raise RuntimeError(f"Windows payload obsahuje nepovolený soubor: {path.name}")
        if path.name.casefold() in {"requirements.txt", "spustit_zakazky.vbs", "nainstalovat_knihovny.bat"}:
            raise RuntimeError(f"Windows payload obsahuje legacy soubor: {path.name}")
    return version


def _copy_release(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in safety.plain_files(source):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if _hash_file(path) != _hash_file(destination):
            raise RuntimeError(f"Kopie souboru neodpovídá zdroji: {path.name}")


def _check_data_outside_install(target: Path) -> None:
    for path in (data_location.database_path(), data_location.data_root()):
        if Path(path).resolve().is_relative_to(target.resolve()):
            raise RuntimeError("Datová složka nebo databáze leží uvnitř instalace. Automatická výměna byla bezpečně zastavena.")


def _restore_program_snapshot(snapshot: Path, target: Path, expected_version: str) -> None:
    _check_data_outside_install(target)
    with tempfile.TemporaryDirectory(prefix="turto_restore_snapshot_") as temp:
        source = _source_root(snapshot, Path(temp))
        _validate_release(source, expected_version)
        safety.replace_directory(source, target, copy_release=_copy_release, validate=_validate_release, owned=PROGRAM_DIRS | PROGRAM_FILES, expected_version=expected_version)


def _replace_program_with_rollback(source: Path, target: Path, *, current_version: str, expected_version: str) -> tuple[Path, str]:
    _check_data_outside_install(target)
    _validate_release(source, expected_version)
    _validate_release(target, current_version, installed=True)
    safety.preflight_files(target)
    _report("Zálohuji původní verzi programu…", detail="Připravuji možnost návratu k původní verzi. Počkejte prosím.")
    snapshot = _snapshot_program(target, current_version)
    if snapshot is None:
        raise RuntimeError("Nepodařilo se vytvořit zálohu programu před aktualizací.")
    _report("Instaluji novou verzi…", detail="Kopíruji a ověřuji soubory programu. Počítač nyní nevypínejte.")
    safety.replace_directory(source, target, copy_release=_copy_release, validate=_validate_release, owned=PROGRAM_DIRS | PROGRAM_FILES, expected_version=expected_version)
    return snapshot


def _restart(target: Path):
    return subprocess.Popen([str(target / MAIN_EXE)], cwd=str(target))


def _has_visible_window(pid):
    """Recognize the restarted process's mapped window, including older builds."""
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes as wt
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    found = False

    @callback_type
    def visit(hwnd, _):
        nonlocal found
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found = True
        return True

    user32.EnumWindows(visit, 0)
    return found


def _wait_for_restart(process, timeout=90):
    # The existing isolated CI probe deliberately exits without opening CRM or
    # migrating the DB. Normal installs wait for the real native CRM window.
    if os.environ.get("TURTO_CRM_SMOKE_RESULT") and os.environ.get("TURTO_DISABLE_AUTO_UPDATE") == "1":
        if process.wait(timeout=timeout) != 0:
            raise RuntimeError("Nová verze se po instalaci nepodařila spustit.")
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Aktualizace je nainstalovaná, ale CRM se nepodařilo otevřít. Spusťte CRM znovu pomocí jeho zástupce.")
        if _has_visible_window(process.pid):
            return
        time.sleep(0.1)
    # Never roll back/replace files while the newly started process is alive.
    raise RuntimeError("Aktualizace je nainstalovaná. CRM se zatím nepodařilo zobrazit; jeho spouštění může stále probíhat.")


def _parse_arguments() -> tuple[Path, Path, int, str, str, str]:
    global _READY_PATH
    if len(sys.argv) < 8 or sys.argv[1] != "--install":
        raise ValueError("Neplatné parametry aktualizace TURTO CRM.")
    package, target, pid, mode, version, sha = sys.argv[2:8]
    if mode not in {"update", "rollback"} or not version or not _SHA256_RE.fullmatch(sha):
        raise ValueError("Aktualizace i návrat verze vyžadují očekávanou verzi a SHA-256.")
    if len(sys.argv) > 8:
        if len(sys.argv) != 10 or sys.argv[8] != "--handshake" or not re.fullmatch(r"[0-9a-f]{32}", sys.argv[9]):
            raise ValueError("Neplatné potvrzení aktualizátoru.")
        _READY_PATH = _stage_root() / ("ready-" + sys.argv[9] + ".json")
    return Path(package).resolve(), Path(target).resolve(), int(pid), mode, version, sha.lower()


def _write_failure_log(*, mode: str, current_version: str, expected_version: str, error: BaseException, package: Path) -> None:
    try:
        safety.write_json(data_location.data_root() / "updates" / "last_failed_update.json", {"mode": mode, "from_version": current_version, "expected_version": expected_version, "package": str(package), "error": str(error), "failed_at": datetime.now().isoformat(timespec="seconds")})
    except Exception:
        pass


def main(progress=None) -> None:
    global _READY_SENT, _PROGRESS
    _PROGRESS = progress
    package, target, pid, mode, expected_version, expected_sha = _parse_arguments()
    current_version = _version_from_install(target)
    try:
        with safety.FileLock(safety.stage_lock(_stage_root())):
            _report("Ověřuji instalaci a aktualizační balíček…", detail="CRM je zatím otevřené. Kontroluji, zda lze bezpečně pokračovat.")
            safety.recover_interrupted(target)
            current_version = _validate_release(target, installed=True)
            _check_data_outside_install(target)
            _verify_package_hash(package, expected_sha)
            with tempfile.TemporaryDirectory(prefix="turto_update_payload_") as temp:
                _report("Rozbaluji a kontroluji aktualizaci…")
                source = _source_root(package, Path(temp))
                source_version = _validate_release(source, expected_version)
                if mode == "update" and source_version == current_version:
                    raise RuntimeError("Aktualizační payload má stejnou verzi jako instalace.")
                _check_cancelled()
                _report("Čekám na bezpečné uzavření CRM…", detail="Po uzavření programu vytvořím zálohu a nainstaluji aktualizaci.")
                if _READY_PATH is not None:
                    safety.write_json(_READY_PATH, {"status": "ready", "pid": os.getpid(), "token": sys.argv[9]})
                    _READY_SENT = True
                _wait_for_process(pid)
                safety.preflight_files(target)
                label = "pred_navratem" if mode == "rollback" else "pred_aktualizaci"
                _report("Zálohuji databázi…", detail="Ukládám zálohu vašich dat před změnou programu.")
                db_backup = _database_backup(label)
                snapshot_path, snapshot_sha = _replace_program_with_rollback(source, target, current_version=current_version, expected_version=source_version)
            try:
                _report("Spouštím TURTO CRM…", detail="Instalace je dokončená. Čekám, až se zobrazí okno programu.")
                restarted = _restart(target)
            except Exception as exc:
                _verify_package_hash(snapshot_path, snapshot_sha)
                _restore_program_snapshot(snapshot_path, target, current_version)
                _restart(target)
                raise RuntimeError("Novou verzi se nepodařilo spustit; původní verze byla automaticky obnovena.") from exc
            safety.write_json(data_location.data_root() / "updates" / "last_update.json", {"mode": mode, "from_version": current_version, "to_version": source_version, "package_sha256": expected_sha, "database": str(data_location.database_path()), "database_backup": str(db_backup) if db_backup else "", "program_snapshot": str(snapshot_path), "program_snapshot_sha256": snapshot_sha, "installed_at": datetime.now().isoformat(timespec="seconds")})
            _wait_for_restart(restarted)
    except BaseException as exc:
        _write_failure_log(mode=mode, current_version=current_version, expected_version=expected_version, error=exc, package=package)
        if _READY_PATH is not None:
            safety.write_json(_READY_PATH, {"status": "error", "pid": os.getpid(), "token": sys.argv[9], "error": str(exc)})
        raise


def run_with_progress():
    from update_progress import ProgressWindow
    ui = ProgressWindow(version=sys.argv[6] if len(sys.argv) >= 8 else "")
    failed = []

    def worker():
        try:
            main(ui.report)
        except BaseException as exc:
            failed.append(exc)
            ui.fail(str(exc))
            if os.environ.get("TURTO_CRM_SMOKE_RESULT") and os.environ.get("TURTO_DISABLE_AUTO_UPDATE") == "1":
                ui.complete()
        else:
            ui.complete()

    thread = threading.Thread(target=worker, name="TURTO-Install", daemon=False)
    thread.start()
    ui.window.mainloop()
    thread.join()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
            from update_progress import ProgressWindow
            ui = ProgressWindow()
            ui.window.update()
            visible = bool(ui.window.winfo_viewable())
            ui.destroy()
            safety.write_json(Path(sys.argv[2]), {"ok": visible, "progress_ui": visible, "frozen": bool(getattr(sys, "frozen", False)), "format": "onedir-v1", "pid": os.getpid()})
        else:
            sys.exit(run_with_progress())
    except Exception as exc:
        try:
            root = data_location.data_root() / "updates"
            root.mkdir(parents=True, exist_ok=True)
            (root / "update_error.log").write_text(str(exc), encoding="utf-8")
            ci_probe = bool(os.environ.get("TURTO_CRM_SMOKE_RESULT")) and os.environ.get("TURTO_DISABLE_AUTO_UPDATE") == "1"
            if os.name == "nt" and (_READY_PATH is None or _READY_SENT) and not ci_probe:
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, str(exc), "TURTO CRM – aktualizace nebyla dokončena", 0x10)
        except Exception:
            pass
        sys.exit(1)
