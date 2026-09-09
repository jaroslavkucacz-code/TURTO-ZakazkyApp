"""Windows EXE distribution policy for TURTO CRM 8.0+.

The frozen build uses a separate update channel and launches a temporary copy of
the one-file updater, because Windows cannot replace a running executable in the
installation directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

WINDOWS_MANIFEST = "latest-windows.json"
UPDATER_EXE = "TURTO CRM Updater.exe"


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
        data = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Manifest aktualizace Windows nemá platný formát.")
    data["_base"] = updates.OFFICIAL_UPDATE_ROOT + "/"
    return data


def _launch_frozen_updater(M, updates, app, remote: str, package: Path) -> bool:
    installed_updater = Path(M.ROOT) / UPDATER_EXE
    if not installed_updater.is_file():
        raise FileNotFoundError(f"Chybí interní aktualizátor {UPDATER_EXE}.")
    package = Path(package)
    if not package.is_file() or package.stat().st_size <= 0:
        raise FileNotFoundError("Stažený aktualizační balíček není dostupný.")

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

    def read_manifest():
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _read_windows_manifest(updates)
        return previous_manifest_reader()

    def launch_updater(module, app, remote: str, package: Path):
        if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
            return _launch_frozen_updater(module, updates, app, remote, package)
        return previous_launcher(module, app, remote, package)

    updates._read_official_manifest = read_manifest
    updates._launch_updater = launch_updater
    M.WINDOWS_UPDATE_MANIFEST = WINDOWS_MANIFEST
    M.EXE_UPDATER_NAME = UPDATER_EXE


__all__ = ["apply", "WINDOWS_MANIFEST", "UPDATER_EXE"]
