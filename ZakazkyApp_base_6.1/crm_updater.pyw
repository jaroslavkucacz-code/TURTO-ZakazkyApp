"""TURTO CRM updater with reversible program-file updates.

The working database is never stored inside the installation directory.  Before
any update or rollback this updater creates:
1. a consistent SQLite database backup;
2. a ZIP snapshot of the currently installed program files.

The same installer code is used in both directions.  Rollback therefore changes
program files only and leaves business data in place.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

PROGRAM_DIRS = {"_runtime", "offers_engine", "price_lists_domain", "__pycache__", "_rollback"}
PROGRAM_FILES = {
    "ZakazkyCRM.pyw",
    "app.py",
    "crm_updater.pyw",
    "runtime_bootstrap.py",
    "requirements.txt",
    "Spustit_Zakazky.bat",
    "Spustit_Zakazky.vbs",
    "Nainstalovat_knihovny.bat",
    "turto_logo.ico",
    "turto_logo.png",
    "turto_crm.ico",
    "turto_crm.png",
    "README.txt",
}
STALE_ROOT_FILES = {
    "crm_features.py", "crm_runtime.py", "crm_v605.py", "post_baseline.py", "post_fix_613.py",
    "v606_features.py", "v608_stability.py", "v611_audit.py", "v613_ui.py", "v614_next.py",
    "v615_input.py", "v616_stability.py", "v617_offerhub.py", "v618_inputfix.py", "v619_fixes.py",
    "v620_outlookdrop.py", "v621_prices.py", "v622_palette.py", "v623_exports.py", "v624_legacy_exports.py",
    "v625_stability.py", "v626_smoothui.py", "v627_fastui_dropfix.py", "v628_modernui_resize.py",
    "v630_safeofferdrop.py", "v631_diskdrop.py", "v632_offerlinks.py", "v633_offerassign_deadlines.py",
    "v634_assignment_search.py", "v635_actions_sort.py", "v636_action_offers_stabletable.py",
    "v637_project_offer_model.py", "v638_table_updatefix.py", "v640_warning_cleanup.py",
    "v641_fill_tables.py", "v642_exact_table_fill.py", "v644_default_date_sort.py", "v645_project_table_fill.py",
    "v710_cleanup.py", "v720_visual_offer.py", "v730_polish.py", "v740_offer_defaults.py",
    "v750_context_filters_offer_format.py", "v760_table_activity_performance.py",
    "v7614_nevoga_canonical_export.py", "v7615_nevoga_meter_units.py",
    "v7616_requests_plexus_assets.py", "v767_offer_reprocess_images.py",
    "v768_clean_table_markers.py", "v769_nevoga_offer.py", "v770_runtime_policy.py",
    "Spustit_Zakazky_v5.bat", "Spustit_Zakazky_v5.vbs", "Spustit_DIAGNOSTIKA.bat", "Spustit_Qt_PREVIEW.bat",
    "Vytvorit_EXE.bat", "Vytvorit_manifest_aktualizace.py", "latest.example.json",
}


def _documents_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "TURTO Zakazky"
    return Path.home() / "Documents" / "TURTO Zakazky"


def _wait_for_process(pid: int) -> None:
    if pid <= 0:
        return
    for _ in range(160):
        try:
            os.kill(pid, 0)
            time.sleep(0.25)
        except Exception:
            break


def _version_from_install(target: Path) -> str:
    candidates = [target / "app.py", target / "_runtime" / "app.py"]
    for path in candidates:
        try:
            match = re.search(
                r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]",
                path.read_text(encoding="utf-8", errors="replace"),
            )
            if match:
                return match.group(1).strip()
        except Exception:
            pass
    return "nezjištěná"


def _database_backup(label: str) -> Path | None:
    root = _documents_root()
    source = root / "data" / "zakazky.db"
    if not source.is_file():
        return None
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
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_program(target: Path, version: str) -> tuple[Path, str] | None:
    if not target.is_dir():
        return None
    root = _documents_root() / "updates" / "rollback"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "_", version or "unknown")
    package = root / f"TURTO_CRM_{safe_version}_{stamp}.zip"
    folder_name = f"TURTO_CRM_{safe_version}"

    def excluded(relative: Path) -> bool:
        if not relative.parts:
            return False
        if relative.parts[0] in {"_rollback", "data", "backup", "test_session"}:
            return True
        if "__pycache__" in relative.parts:
            return True
        if relative.name in {"update_error.log", "v5_error.log"} or relative.suffix.lower() == ".pyc":
            return True
        return False

    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in target.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(target)
            if excluded(relative):
                continue
            archive.write(path, Path(folder_name) / relative)
    digest = _hash_file(package)
    (root / "latest.json").write_text(
        json.dumps(
            {
                "version": version,
                "package": str(package),
                "sha256": digest,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return package, digest


def _source_root(package: Path, temp_root: Path) -> Path:
    with zipfile.ZipFile(package) as archive:
        archive.extractall(temp_root)
    roots = [path for path in temp_root.iterdir() if path.is_dir()]
    return roots[0] if len(roots) == 1 else temp_root


def _clean_program(target: Path) -> None:
    for directory in PROGRAM_DIRS | {"ZakazkyApp_v5.7", "original_source"}:
        try:
            shutil.rmtree(target / directory, ignore_errors=True)
        except Exception:
            pass
    for name in PROGRAM_FILES | STALE_ROOT_FILES:
        path = target / name
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except Exception:
            pass


def _copy_release(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or path.suffix.lower() == ".pyc":
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if path.name == "v5_error.log":
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, destination)
        except Exception:
            time.sleep(0.5)
            shutil.copy2(path, destination)


def _validate_release(target: Path) -> None:
    launcher = target / "ZakazkyCRM.pyw"
    parser = target / "offers_engine" / "Gerotop_Parser.py"
    if not launcher.is_file():
        raise RuntimeError("Aktualizace neobsahuje ZakazkyCRM.pyw")
    if not parser.is_file():
        raise RuntimeError("Aktualizace neobsahuje offers_engine/Gerotop_Parser.py")
    parser_text = parser.read_text(encoding="utf-8", errors="replace")
    if "PRODUCT_CODE_RE" not in parser_text or "anchors = _row_anchors(page)" not in parser_text:
        raise RuntimeError("GEROtop parser nebyl při aktualizaci správně nahrazen.")


def _restart(target: Path) -> None:
    vbs = target / "Spustit_Zakazky.vbs"
    if sys.platform.startswith("win") and vbs.is_file():
        subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(target))
    else:
        subprocess.Popen([sys.executable, str(target / "ZakazkyCRM.pyw")], cwd=str(target))


def _parse_arguments() -> tuple[Path, Path, int, str]:
    # New form: crm_updater.pyw --install PACKAGE TARGET PID [update|rollback]
    if len(sys.argv) >= 5 and sys.argv[1] == "--install":
        package = Path(sys.argv[2])
        target = Path(sys.argv[3])
        pid = int(sys.argv[4])
        mode = str(sys.argv[5] if len(sys.argv) > 5 else "update").strip().lower()
        return package, target, pid, mode
    # Backward-compatible form used by TURTO CRM 7.6.16.
    if len(sys.argv) >= 4:
        return Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), "update"
    raise ValueError("Neplatné parametry aktualizace.")


def main() -> None:
    package, target, pid, mode = _parse_arguments()
    if not package.is_file():
        raise FileNotFoundError(package)
    _wait_for_process(pid)

    current_version = _version_from_install(target)
    label = "pred_navratem" if mode == "rollback" else "pred_aktualizaci"
    db_backup = _database_backup(label)
    program_snapshot = _snapshot_program(target, current_version)

    with tempfile.TemporaryDirectory(prefix="turto_update_") as temp:
        source = _source_root(package, Path(temp))
        _clean_program(target)
        _copy_release(source, target)
        _validate_release(target)

    log_root = _documents_root() / "updates"
    log_root.mkdir(parents=True, exist_ok=True)
    (log_root / "last_update.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "from_version": current_version,
                "to_version": _version_from_install(target),
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
            target = Path(sys.argv[3] if len(sys.argv) > 3 and sys.argv[1] == "--install" else sys.argv[2])
            (target / "update_error.log").write_text(str(exc), encoding="utf-8")
        except Exception:
            pass
