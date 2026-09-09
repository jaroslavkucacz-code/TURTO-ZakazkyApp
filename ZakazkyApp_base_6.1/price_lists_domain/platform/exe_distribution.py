"""Windows EXE distribution policy for TURTO CRM 8.0+.

The frozen build uses a separate, hash-verified update channel and launches a
temporary copy of the one-file updater, because Windows cannot replace a running
executable in the installation directory.
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
from urllib.parse import quote
import urllib.request

import data_location

WINDOWS_MANIFEST = "latest-windows.json"
WINDOWS_MANIFEST_FORMAT = "turto-crm-windows-update-v1"
WINDOWS_RELEASE_ROOT = (
    "https://github.com/jaroslavkucacz-code/TURTO-ZakazkyApp/releases/download"
)
UPDATER_EXE = "TURTO CRM Updater.exe"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,63}$")


def _validate_windows_manifest(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Manifest aktualizace Windows nemá platný formát.")

    manifest_format = str(data.get("format") or "").strip()
    if manifest_format != WINDOWS_MANIFEST_FORMAT:
        raise ValueError("Manifest nepatří do podporovaného Windows update kanálu TURTO CRM 8.x.")

    channel = str(data.get("channel") or "").strip().casefold()
    if channel != "windows":
        raise ValueError("Manifest aktualizace nemá Windows kanál.")

    version = str(data.get("version") or "").strip()
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("Manifest aktualizace nemá platné číslo/verzi sestavení.")

    package = str(data.get("package") or "").strip()
    expected_package = f"TURTO_CRM_Update_{version}.zip"
    if package != expected_package or Path(package).name != package:
        raise ValueError("Manifest odkazuje na neočekávaný Windows update balíček.")

    sha256 = str(data.get("sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(sha256):
        raise ValueError("Manifest aktualizace neobsahuje platný SHA-256 otisk.")

    download_url = str(data.get("download_url") or "").strip()
    if download_url:
        expected_url = f"{WINDOWS_RELEASE_ROOT}/v{version}/{package}"
        if download_url != expected_url:
            raise ValueError("Manifest odkazuje na nepovolený zdroj Windows update balíčku.")

    normalized = dict(data)
    normalized.update(
        {
            "format": manifest_format,
            "channel": "windows",
            "version": version,
            "package": package,
            "sha256": sha256,
            "download_url": download_url,
        }
    )
    return normalized


def _read_windows_manifest(updates) -> dict:
    url = updates.OFFICIAL_UPDATE_ROOT + "/" + WINDOWS_MANIFEST + "?ts=" + str(time.time_ns())
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TURTO-CRM-Windows-Updater",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = json.loads(response.read().decode("utf-8-sig"))
    data = _validate_windows_manifest(raw)
    data["_base"] = updates.OFFICIAL_UPDATE_ROOT + "/"
    return data


def _download_windows_package(M, updates, manifest: dict) -> Path:
    data = _validate_windows_manifest(manifest)
    package_name = data["package"]
    expected_sha = data["sha256"]
    download_url = str(data.get("download_url") or "").strip()
    if not download_url:
        # Backward-compatible bridge for early 8.0 previews. Production 8.x
        # manifests point to immutable GitHub Release assets instead.
        base = str(manifest.get("_base") or (updates.OFFICIAL_UPDATE_ROOT + "/"))
        if base != updates.OFFICIAL_UPDATE_ROOT.rstrip("/") + "/":
            raise ValueError("Windows update balíček nemá povolený oficiální zdroj.")
        download_url = base + quote(package_name)

    root = Path(getattr(M, "DATA_ROOT", data_location.data_root())) / "updates" / "downloads"
    root.mkdir(parents=True, exist_ok=True)
    target = root / package_name
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)

    request = urllib.request.Request(
        download_url,
        headers={
            "User-Agent": "TURTO-CRM-Windows-Updater",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=45) as response, partial.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
        actual_sha = digest.hexdigest().lower()
        if actual_sha != expected_sha:
            raise ValueError(
                "Stažený Windows update balíček neodpovídá SHA-256 otisku z manifestu."
            )
        if partial.stat().st_size <= 0:
            raise ValueError("Stažený Windows update balíček je prázdný.")
        partial.replace(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    # The updater re-hashes the file independently after the main CRM process
    # exits. Keep the official expected values only long enough to launch it.
    M._turto_windows_expected_update_sha256 = expected_sha
    M._turto_windows_expected_update_version = data["version"]
    return target


def _launch_frozen_updater(M, updates, app, remote: str, package: Path) -> bool:
    installed_updater = Path(M.ROOT) / UPDATER_EXE
    if not installed_updater.is_file():
        raise FileNotFoundError(f"Chybí interní aktualizátor {UPDATER_EXE}.")
    package = Path(package)
    if not package.is_file() or package.stat().st_size <= 0:
        raise FileNotFoundError("Stažený aktualizační balíček není dostupný.")

    expected_version = str(
        getattr(M, "_turto_windows_expected_update_version", remote) or remote
    ).strip()
    expected_sha = str(
        getattr(M, "_turto_windows_expected_update_sha256", "") or ""
    ).strip().lower()
    if expected_version != str(remote).strip() or not _SHA256_RE.fullmatch(expected_sha):
        raise ValueError("Chybí ověřené údaje Windows aktualizačního balíčku.")

    temp_root = Path(tempfile.mkdtemp(prefix="turto_crm_updater_"))
    temp_updater = temp_root / UPDATER_EXE
    shutil.copy2(installed_updater, temp_updater)

    try:
        M.set_setting("pending_update", remote)
        M.set_setting("update_source", updates.OFFICIAL_UPDATE_ROOT)
        M.set_setting("company_auto_updates", "1")
    except Exception:
        pass

    command = [
        str(temp_updater),
        "--install",
        str(package),
        str(M.ROOT),
        str(os.getpid()),
        "update",
        expected_version,
        expected_sha,
    ]
    kwargs = {"cwd": str(temp_root)}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(command, **kwargs)
    app._turto_update_launching = True
    updates._log(M, "install-start-exe", f"{getattr(M, 'APP_VERSION', '')} -> {remote}")

    try:
        app.title(f"TURTO CRM – instaluji aktualizaci {remote}…")
        app.configure(cursor="watch")
    except Exception:
        pass

    closer = getattr(app, "close_app", None)
    if not callable(closer):
        closer = getattr(app, "destroy", None)
    if callable(closer):
        try:
            app.after(180, closer)
        except Exception:
            closer()
    return True


def apply(M) -> None:
    if getattr(M, "_turto_exe_distribution_800", False):
        return
    M._turto_exe_distribution_800 = True

    from price_lists_domain.platform import automatic_updates as updates

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

    updates._read_official_manifest = read_manifest
    updates._launch_updater = launch_updater
    M._download_update_package = download_package
    M.WINDOWS_UPDATE_MANIFEST = WINDOWS_MANIFEST
    M.WINDOWS_UPDATE_MANIFEST_FORMAT = WINDOWS_MANIFEST_FORMAT
    M.EXE_UPDATER_NAME = UPDATER_EXE


__all__ = [
    "apply",
    "WINDOWS_MANIFEST",
    "WINDOWS_MANIFEST_FORMAT",
    "WINDOWS_RELEASE_ROOT",
    "UPDATER_EXE",
]
