"""Windows distribution: verified reusable onedir updater, readiness handshake.

8.0.8 uses a new manifest path. The legacy channel stays at 8.0.7 so an unsafe
old updater is NOT used to bootstrap its own repair. Install 8.0.8 once via Setup.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote
import urllib.request

import data_location
import updater_safety as safety

LEGACY_WINDOWS_MANIFEST = "latest-windows.json"
WINDOWS_MANIFEST = "latest-windows-v2.json"
WINDOWS_MANIFEST_FORMAT = "turto-crm-windows-update-v1"
WINDOWS_RELEASE_ROOT = "https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/releases/download"
UPDATER_EXE = "TURTO CRM Updater.exe"
_UPDATER_STAGE_DIR = "UpdaterRuntime"
_LEGACY_TEMP_PREFIX = "turto_crm_updater_"
_LEGACY_STALE_SECONDS = 15 * 60
_UPDATER_HEALTH_DELAY_MS = 800
_UPDATER_READY_TIMEOUT = 45.0
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")


class UpdaterLaunchBlockedError(RuntimeError):
    turto_show_user = True


def _hash_file(path: Path) -> str:
    return safety.digest(Path(path))


def _updater_stage_root() -> Path:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        return Path(local) / "TURTO CRM" / _UPDATER_STAGE_DIR
    return Path(tempfile.gettempdir()) / "turto_crm_updater_stage"


def _cleanup_stage_copy() -> bool:
    # Kept as a compatibility entry point. Never delete/recreate a verified
    # runtime on startup, failed launch, or every automatic update check.
    return True


def _cleanup_stale_legacy_updaters(now: float | None = None) -> list[str]:
    removed = []
    current = time.time() if now is None else float(now)
    for path in Path(tempfile.gettempdir()).glob(_LEGACY_TEMP_PREFIX + "*"):
        try:
            if not path.is_dir() or safety.is_link(path) or current - path.stat().st_mtime < _LEGACY_STALE_SECONDS:
                continue
            list(safety.plain_files(path))
            shutil.rmtree(path)
            removed.append(str(path))
        except Exception:
            continue
    return removed


def _prepare_updater_stage(installed_updater: Path) -> tuple[Path, Path]:
    def copy_verified(installed_updater, staged):
        shutil.copy2(installed_updater, staged)
        expected = _hash_file(installed_updater)
        actual = _hash_file(staged)
        if expected != actual:
            raise UpdaterLaunchBlockedError("Pracovní soubor neodpovídá originálu.")
    try:
        return safety.prepare_stage(Path(installed_updater), _updater_stage_root(), copy_file=copy_verified)
    except Exception as exc:
        raise UpdaterLaunchBlockedError(str(exc)) from exc


def _validate_windows_manifest(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Manifest aktualizace Windows nemá platný formát.")
    manifest_format = str(data.get("format") or "").strip()
    if manifest_format != WINDOWS_MANIFEST_FORMAT:
        raise ValueError("Manifest nepatří do podporovaného Windows update kanálu.")
    channel = str(data.get("channel") or "").strip().casefold()
    if channel != "windows":
        raise ValueError("Manifest aktualizace nemá Windows kanál.")
    version = str(data.get("version") or "").strip()
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Manifest nemá platnou verzi sestavení.")
    package = str(data.get("package") or "").strip()
    if package != f"TURTO_CRM_Update_{version}.zip" or Path(package).name != package:
        raise ValueError("Manifest odkazuje na neočekávaný Windows update balíček.")
    sha256 = str(data.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("Manifest neobsahuje platný SHA-256 otisk.")
    download_url = str(data.get("download_url") or "").strip()
    if download_url and download_url != f"{WINDOWS_RELEASE_ROOT}/v{version}/{package}":
        raise ValueError("Manifest odkazuje na nepovolený zdroj aktualizace.")
    normalized = dict(data)
    normalized.update(format=manifest_format, channel="windows", version=version, package=package, sha256=sha256, download_url=download_url)
    return normalized


def _read_windows_manifest(updates) -> dict:
    url = updates.OFFICIAL_UPDATE_ROOT + "/" + WINDOWS_MANIFEST + "?ts=" + str(time.time_ns())
    request = urllib.request.Request(url, headers={"User-Agent": "TURTO-CRM-Windows-Updater", "Cache-Control": "no-cache", "Pragma": "no-cache"})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8-sig"))
    data = _validate_windows_manifest(raw)
    data["_base"] = updates.OFFICIAL_UPDATE_ROOT + "/"
    return data


def _download_windows_package(M, updates, manifest: dict, progress=None) -> Path:
    data = _validate_windows_manifest(manifest)
    package_name, expected_sha = data["package"], data["sha256"]
    download_url = data["download_url"]
    if not download_url:
        base = str(manifest.get("_base") or (updates.OFFICIAL_UPDATE_ROOT + "/"))
        if base != updates.OFFICIAL_UPDATE_ROOT.rstrip("/") + "/":
            raise ValueError("Windows balíček nemá povolený oficiální zdroj.")
        download_url = base + quote(package_name)
    root = Path(getattr(M, "DATA_ROOT", data_location.data_root())) / "updates" / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    target = root / package_name
    partial = target.with_suffix(target.suffix + ".part")
    import storage_maintenance
    with storage_maintenance.maintenance_lock(root.parent.parent), safety.FileLock(root / (package_name + ".lock")):
        partial.unlink(missing_ok=True)
        request = urllib.request.Request(download_url, headers={"User-Agent": "TURTO-CRM-Windows-Updater", "Cache-Control": "no-cache", "Pragma": "no-cache"})
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as handle:
                total = int(response.headers.get("Content-Length", "0") or 0) if progress else 0
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    handle.write(chunk)
                    received += len(chunk)
                    if progress:
                        detail = f"Staženo {received / 1024 / 1024:.1f} MB"
                        if total > 0:
                            detail += f" z {total / 1024 / 1024:.1f} MB"
                        progress("Stahuji aktualizaci…", received / total if total > 0 else None, detail)
            if progress:
                progress("Ověřuji stažený balíček…", None, "Kontroluji úplnost a pravost souborů.")
            actual_sha = digest.hexdigest().lower()
            if actual_sha != expected_sha:
                raise ValueError("Stažený Windows balíček neodpovídá SHA-256 otisku z manifestu.")
            if partial.stat().st_size <= 0:
                raise ValueError("Stažený Windows balíček je prázdný.")
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
    M._turto_windows_expected_update_sha256 = expected_sha
    M._turto_windows_expected_update_version = data["version"]
    return target


def _show_blocked_updater(M, app, remote: str, detail: str) -> None:
    if getattr(app, "_turto_update_security_warning_shown", False):
        return
    app._turto_update_security_warning_shown = True
    try:
        M.messagebox.showerror("Aktualizace zablokována", f"Aktualizaci {remote} se nepodařilo bezpečně spustit. CRM zůstalo otevřené.\n\n{detail}\n\nNevypínejte ochranu ani neobnovujte zachycený soubor naslepo. Použijte oficiální plný instalátor nebo odešlete detekovaný soubor ESETu k analýze.", parent=app)
    except Exception:
        pass


def _launch_frozen_updater(M, updates, app, remote: str, package: Path) -> bool:
    if getattr(app, "_turto_update_launching", False):
        return True
    if getattr(app, "_turto_update_security_warning_shown", False):
        raise UpdaterLaunchBlockedError("Opakované automatické spuštění zablokovaného aktualizátoru bylo zastaveno.")
    installed_updater = Path(M.ROOT) / UPDATER_EXE
    package = Path(package)
    if not package.is_file() or package.stat().st_size == 0:
        raise FileNotFoundError("Aktualizační balíček není dostupný.")
    expected_version = str(getattr(M, "_turto_windows_expected_update_version", remote) or remote).strip()
    expected_sha = str(getattr(M, "_turto_windows_expected_update_sha256", "") or "").strip().lower()
    if expected_version != str(remote).strip() or not _SHA256_RE.fullmatch(expected_sha):
        raise ValueError("Chybí ověřené údaje Windows aktualizačního balíčku.")
    prepared = getattr(M, "_turto_prepared_update_runtime", None)
    M._turto_prepared_update_runtime = None
    stage_root, staged_updater = prepared or _prepare_updater_stage(installed_updater)
    control_root = _updater_stage_root()
    token = uuid.uuid4().hex
    ready_file = control_root / ("ready-" + token + ".json")
    cancel_file = control_root / ("cancel-" + token + ".json")
    command = [str(staged_updater), "--install", str(package), str(M.ROOT), str(os.getpid()), "update", expected_version, expected_sha, "--handshake", token]
    kwargs = {"cwd": str(stage_root)}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def mark_blocked(detail):
        safety.write_json(cancel_file, {"cancelled": True, "reason": detail})
        try:
            receipt = control_root / "receipt.json"
            record = json.loads(receipt.read_text(encoding="utf-8"))
            record["complete"] = False
            record["blocked_reason"] = detail
            safety.write_json(receipt, record)
        except Exception:
            pass

    try:
        process = subprocess.Popen(command, **kwargs)
    except Exception as exc:
        mark_blocked(str(exc))
        raise UpdaterLaunchBlockedError("Aktualizátor byl zablokován nebo odstraněn. Opakování bylo zastaveno.") from exc
    app._turto_update_launching = True
    started = time.monotonic()
    updates._log(M, "install-probe-exe", f"{getattr(M, 'APP_VERSION', '')} -> {remote}")

    def blocked(detail):
        app._turto_update_launching = False
        app._turto_update_installing = False
        mark_blocked(detail)
        updates._log(M, "install-blocked-exe", detail)
        try:
            M.set_setting("pending_update", "")
            app.title(f"TURTO CRM {getattr(M, 'APP_VERSION', '')}")
            app.configure(cursor="")
        except Exception:
            pass
        progress = getattr(app, "_turto_update_progress", None)
        if progress is not None:
            app._turto_update_security_warning_shown = True
            progress.fail("Aktualizaci se nepodařilo bezpečně spustit. CRM zůstalo otevřené.\n\n" + detail)
        else:
            _show_blocked_updater(M, app, remote, detail)

    def confirm_and_close():
        try:
            state = json.loads(ready_file.read_text(encoding="utf-8")) if ready_file.is_file() else {}
            code = process.poll()
            if state.get("status") == "error":
                blocked(str(state.get("error") or "Aktualizátor odmítl instalaci."))
                return
            if code is not None or not staged_updater.is_file():
                blocked(f"Proces aktualizátoru skončil před potvrzením (kód {code}) nebo byl odstraněn.")
                return
            if state.get("status") != "ready" or state.get("token") != token or state.get("pid") != process.pid:
                if time.monotonic() - started >= _UPDATER_READY_TIMEOUT:
                    blocked("Aktualizátor včas nepotvrdil připravenost. CRM nebylo ukončeno.")
                    return
                app.after(_UPDATER_HEALTH_DELAY_MS, confirm_and_close)
                return
            closer = getattr(app, "close_app", None) or getattr(app, "destroy", None)
            if not callable(closer):
                blocked("CRM nemá dostupné bezpečné ukončení.")
                return
            try:
                M.set_setting("pending_update", remote)
                M.set_setting("update_source", updates.OFFICIAL_UPDATE_ROOT)
                M.set_setting("company_auto_updates", "1")
            except Exception:
                pass
            updates._log(M, "install-start-exe", f"{getattr(M, 'APP_VERSION', '')} -> {remote}")
            progress = getattr(app, "_turto_update_progress", None)
            if progress is not None:
                # The standalone updater has already mapped its own window
                # before sending ready. Release the CRM-owned modal grab.
                progress.destroy()
            closer()
        except Exception as exc:
            blocked(f"Aktualizaci se nepodařilo bezpečně potvrdit: {exc}")

    try:
        app.after(_UPDATER_HEALTH_DELAY_MS, confirm_and_close)
    except Exception as exc:
        blocked(f"Nelze naplánovat potvrzení aktualizace: {exc}")
    return True


def apply(M) -> None:
    if getattr(M, "_turto_exe_distribution_800", False):
        return
    M._turto_exe_distribution_800 = True
    from price_lists_domain.platform import automatic_updates as updates
    # No stage cleanup on startup: keep the verified runtime and its receipt.
    previous_manifest_reader = updates._read_official_manifest
    previous_launcher = updates._launch_updater
    previous_downloader = getattr(M, "_download_update_package", None)

    def read_manifest():
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _read_windows_manifest(updates)
        return previous_manifest_reader()

    def download_package(manifest):
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _download_windows_package(M, updates, manifest)
        if not callable(previous_downloader):
            raise RuntimeError("Legacy downloader aktualizací není dostupný.")
        return previous_downloader(manifest)

    def launch_updater(module, app, remote: str, package: Path):
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _launch_frozen_updater(module, updates, app, remote, package)
        return previous_launcher(module, app, remote, package)

    def download_with_progress(manifest, progress):
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _download_windows_package(M, updates, manifest, progress)
        return download_package(manifest)

    def prepare_runtime():
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            M._turto_prepared_update_runtime = _prepare_updater_stage(Path(M.ROOT) / UPDATER_EXE)

    updates._read_official_manifest = read_manifest
    updates._launch_updater = launch_updater
    M._download_update_package = download_package
    M._download_update_with_progress = download_with_progress
    M._prepare_update_runtime = prepare_runtime
    M.WINDOWS_UPDATE_MANIFEST = WINDOWS_MANIFEST
    M.WINDOWS_UPDATE_MANIFEST_FORMAT = WINDOWS_MANIFEST_FORMAT
    M.EXE_UPDATER_NAME = UPDATER_EXE


__all__ = ["apply", "WINDOWS_MANIFEST", "WINDOWS_MANIFEST_FORMAT", "WINDOWS_RELEASE_ROOT", "UPDATER_EXE", "UpdaterLaunchBlockedError"]
