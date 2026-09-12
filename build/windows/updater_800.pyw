from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

import data_location

MAIN_EXE = "TURTO CRM.exe"
UPDATER_EXE = "TURTO CRM Updater.exe"
WINDOWS_CHANNEL = "windows"
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
FORBIDDEN_PAYLOAD_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".py", ".pyw", ".pyc"}
MAX_UNCOMPRESSED_PAYLOAD = 2 * 1024 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _wait_for_process(pid: int) -> None:
    if pid <= 0:
        return
    for _ in range(240):
        try:
            os.kill(pid, 0)
            time.sleep(0.25)
        except Exception:
            break


def _read_version_manifest(root: Path) -> dict:
    path = root / "version.json"
    if not path.is_file():
        raise RuntimeError("Aktualizace neobsahuje version.json.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        raise RuntimeError(f"version.json nemá platný formát: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("version.json nemá platný objektový formát.")
    return data


def _version_from_install(target: Path) -> str:
    try:
        value = str(_read_version_manifest(target).get("version") or "").strip()
        if value:
            return value
    except Exception:
        pass
    return "nezjištěná"


def _database_backup(label: str) -> Path | None:
    source = data_location.database_path()
    if not source.is_file():
        return None
    return data_location.backup_database(
        source,
        label=label,
        backup_root=data_location.data_root(),
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _verify_package_hash(package: Path, expected_sha256: str) -> str:
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise ValueError("Updater nedostal platný očekávaný SHA-256 otisk balíčku.")
    actual = _hash_file(package)
    if actual != expected:
        raise ValueError("Aktualizační ZIP změnil obsah nebo neodpovídá oficiálnímu SHA-256 otisku.")
    return actual


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


def _safe_extract(package: Path, temp_root: Path) -> None:
    root = temp_root.resolve()
    total = 0
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            raw_name = str(info.filename or "").replace("\\", "/")
            rel = PurePosixPath(raw_name)
            if not raw_name or rel.is_absolute() or ".." in rel.parts:
                raise RuntimeError("Aktualizační ZIP obsahuje nepovolenou cestu.")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == stat.S_IFLNK:
                raise RuntimeError("Aktualizační ZIP nesmí obsahovat symbolické odkazy.")
            total += int(info.file_size or 0)
            if total > MAX_UNCOMPRESSED_PAYLOAD:
                raise RuntimeError("Aktualizační ZIP překračuje povolenou rozbalenou velikost.")

            destination = root.joinpath(*rel.parts)
            try:
                destination.resolve().relative_to(root)
            except Exception as exc:
                raise RuntimeError("Aktualizační ZIP se pokusil zapisovat mimo pracovní složku.") from exc

            if info.is_dir() or raw_name.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def _source_root(package: Path, temp_root: Path) -> Path:
    _safe_extract(package, temp_root)
    entries = [p for p in temp_root.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return temp_root


def _allowed_offer_engine_source(path: Path, root: Path) -> bool:
    """Allow only the physical Python sources required by the frozen Offer Engine."""
    if path.suffix.lower() not in {".py", ".pyw"}:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    parts = tuple(part.casefold() for part in rel.parts)
    return len(parts) >= 3 and parts[0] == "_internal" and parts[1] == "offers_engine"


def _validate_release(
    target: Path,
    expected_version: str | None = None,
    *,
    installed: bool = False,
) -> str:
    main = target / MAIN_EXE
    updater = target / UPDATER_EXE
    if not main.is_file():
        raise RuntimeError(f"Aktualizace neobsahuje {MAIN_EXE}.")
    if not updater.is_file():
        raise RuntimeError(f"Aktualizace neobsahuje {UPDATER_EXE}.")

    manifest = _read_version_manifest(target)
    version = str(manifest.get("version") or "").strip()
    channel = str(manifest.get("channel") or "").strip().casefold()
    if not version:
        raise RuntimeError("version.json neobsahuje číslo verze.")
    if channel != WINDOWS_CHANNEL:
        raise RuntimeError("Aktualizační payload nepatří do Windows kanálu TURTO CRM 8.x.")
    if expected_version and version != str(expected_version).strip():
        raise RuntimeError(
            f"Verze payloadu {version} neodpovídá očekávané verzi {expected_version}."
        )

    for path in target.rglob("*"):
        if not path.is_file():
            continue
        # The installed application legitimately owns Inno Setup uninstaller
        # files. A downloaded/snapshot payload must never contain them.
        if path.name.casefold().startswith("unins"):
            if installed:
                continue
            raise RuntimeError("Windows payload nesmí přepisovat Inno Setup odinstalační metadata.")
        if (
            path.suffix.lower() in FORBIDDEN_PAYLOAD_SUFFIXES
            and not _allowed_offer_engine_source(path, target)
        ):
            raise RuntimeError(f"Windows payload obsahuje nepovolený soubor: {path.name}")
        if path.name.casefold() in {
            "requirements.txt",
            "spustit_zakazky.vbs",
            "nainstalovat_knihovny.bat",
        }:
            raise RuntimeError(f"Windows payload obsahuje legacy soubor: {path.name}")
    return version


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


def _restore_program_snapshot(snapshot: Path, target: Path, expected_version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="turto_restore_snapshot_") as temp:
        source = _source_root(snapshot, Path(temp))
        _validate_release(source, expected_version)
        _clean_program(target)
        _copy_release(source, target)
        _validate_release(target, expected_version, installed=True)


def _replace_program_with_rollback(
    source: Path,
    target: Path,
    *,
    current_version: str,
    expected_version: str,
) -> tuple[Path, str]:
    snapshot = _snapshot_program(target, current_version)
    if snapshot is None:
        raise RuntimeError("Před aktualizací se nepodařilo vytvořit snapshot programu.")
    snapshot_path, snapshot_sha = snapshot

    try:
        _clean_program(target)
        _copy_release(source, target)
        _validate_release(target, expected_version, installed=True)
    except BaseException as install_error:
        try:
            _restore_program_snapshot(snapshot_path, target, current_version)
        except BaseException as restore_error:
            raise RuntimeError(
                "Aktualizace selhala a automatické obnovení původního programu se také nezdařilo. "
                f"Instalace: {install_error}; obnova: {restore_error}; snapshot: {snapshot_path}"
            ) from install_error
        raise RuntimeError(
            "Aktualizace programových souborů selhala; původní verze byla automaticky obnovena. "
            f"Důvod: {install_error}"
        ) from install_error
    return snapshot_path, snapshot_sha


def _restart(target: Path) -> None:
    executable = target / MAIN_EXE
    subprocess.Popen([str(executable)], cwd=str(target))


def _parse_arguments() -> tuple[Path, Path, int, str, str, str]:
    if len(sys.argv) >= 6 and sys.argv[1] == "--install":
        package = Path(sys.argv[2])
        target = Path(sys.argv[3])
        pid = int(sys.argv[4])
        mode = str(sys.argv[5] or "update").strip().lower()
        expected_version = str(sys.argv[6] if len(sys.argv) > 6 else "").strip()
        expected_sha256 = str(sys.argv[7] if len(sys.argv) > 7 else "").strip().lower()
        if mode == "update":
            if not expected_version or not _SHA256_RE.fullmatch(expected_sha256):
                raise ValueError("Windows update vyžaduje očekávanou verzi i SHA-256.")
        elif expected_sha256 and not _SHA256_RE.fullmatch(expected_sha256):
            raise ValueError("Rollback dostal neplatný SHA-256 otisk.")
        return package, target, pid, mode, expected_version, expected_sha256
    raise ValueError("Neplatné parametry aktualizace TURTO CRM 8.x.")


def _write_failure_log(
    *,
    mode: str,
    current_version: str,
    expected_version: str,
    error: BaseException,
    package: Path,
) -> None:
    try:
        root = data_location.data_root() / "updates"
        root.mkdir(parents=True, exist_ok=True)
        (root / "last_failed_update.json").write_text(
            json.dumps(
                {
                    "mode": mode,
                    "from_version": current_version,
                    "expected_version": expected_version,
                    "package": str(package),
                    "error": str(error),
                    "failed_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def main() -> None:
    package, target, pid, mode, expected_version, expected_sha256 = _parse_arguments()
    if not package.is_file():
        raise FileNotFoundError(package)
    _wait_for_process(pid)

    current_version = _validate_release(target, installed=True)
    if expected_sha256:
        _verify_package_hash(package, expected_sha256)

    label = "pred_navratem" if mode == "rollback" else "pred_aktualizaci"

    try:
        with tempfile.TemporaryDirectory(prefix="turto_update_payload_") as temp:
            source = _source_root(package, Path(temp))
            source_version = _validate_release(source, expected_version or None)
            if mode == "update" and source_version == current_version:
                raise RuntimeError("Aktualizační payload má stejnou verzi jako aktuální instalace.")

            # No installed program files have been touched before all payload
            # validation above has completed successfully.
            db_backup = _database_backup(label)
            snapshot_path, snapshot_sha = _replace_program_with_rollback(
                source,
                target,
                current_version=current_version,
                expected_version=source_version,
            )

        try:
            _restart(target)
        except BaseException as restart_error:
            try:
                _restore_program_snapshot(snapshot_path, target, current_version)
                _restart(target)
            except BaseException as restore_error:
                raise RuntimeError(
                    "Nová verze byla nainstalována, ale nešlo ji spustit; následná obnova "
                    f"původní verze také selhala. Start: {restart_error}; obnova: {restore_error}"
                ) from restart_error
            raise RuntimeError(
                "Novou verzi se nepodařilo spustit; původní program byl automaticky obnoven a spuštěn."
            ) from restart_error

        log_root = data_location.data_root() / "updates"
        log_root.mkdir(parents=True, exist_ok=True)
        (log_root / "last_update.json").write_text(
            json.dumps(
                {
                    "mode": mode,
                    "from_version": current_version,
                    "to_version": _version_from_install(target),
                    "package_sha256": expected_sha256 or _hash_file(package),
                    "database": str(data_location.database_path()),
                    "database_backup": str(db_backup) if db_backup else "",
                    "program_snapshot": str(snapshot_path),
                    "program_snapshot_sha256": snapshot_sha,
                    "installed_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    except BaseException as exc:
        _write_failure_log(
            mode=mode,
            current_version=current_version,
            expected_version=expected_version,
            error=exc,
            package=package,
        )
        raise


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
