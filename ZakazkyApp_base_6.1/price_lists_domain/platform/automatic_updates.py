"""Unattended, official-channel updates for TURTO CRM.

The already installed application checks the manifest shortly after startup.  This
owner replaces the legacy confirmation dialog: a newer signed-by-hash package is
downloaded in a worker thread, the updater is launched, and CRM restarts itself.
No user file or database is stored inside the program directory.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

OFFICIAL_UPDATE_ROOT = (
    "https://raw.githubusercontent.com/"
    "jaroslavkucacz-code/TURTO-ZakazkyApp/main"
)
_RECENT_SILENT_CHECK_SECONDS = 60.0


def _exists(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return widget is not None


def _version_tuple(M, value):
    parser = getattr(M, "_version_tuple", None)
    if callable(parser):
        try:
            return parser(value)
        except Exception:
            pass
    result = []
    for part in str(value or "").replace("-", ".").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if digits:
            result.append(int(digits))
    return tuple(result) or (0,)


def _log(M, event: str, detail: str = "") -> None:
    try:
        root = Path(
            getattr(
                M,
                "DATA_ROOT",
                Path.home() / "Documents" / "TURTO Zakazky",
            )
        )
        target = root / "logs" / "automatic_updates.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {event}"
        if detail:
            line += ": " + detail.strip()
        with target.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    except Exception:
        pass


def _read_official_manifest() -> dict:
    # The cache-busting query is important for raw.githubusercontent.com: after
    # publishing a release, every workstation must see the new manifest at once.
    url = OFFICIAL_UPDATE_ROOT + "/latest.json?ts=" + str(time.time_ns())
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TURTO-CRM-Automatic-Updater",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Manifest aktualizace nemá platný formát.")
    data["_base"] = OFFICIAL_UPDATE_ROOT + "/"
    return data


def _launch_updater(M, app, remote: str, package: Path) -> bool:
    updater = Path(M.ROOT) / "crm_updater.pyw"
    if not updater.is_file():
        raise FileNotFoundError("Chybí interní aktualizátor crm_updater.pyw.")
    package = Path(package)
    if not package.is_file() or package.stat().st_size <= 0:
        raise FileNotFoundError("Stažený aktualizační balíček není dostupný.")

    try:
        M.set_setting("pending_update", remote)
        M.set_setting("update_source", OFFICIAL_UPDATE_ROOT)
        M.set_setting("company_auto_updates", "1")
    except Exception:
        pass

    command = [
        sys.executable,
        str(updater),
        str(package),
        str(M.ROOT),
        str(os.getpid()),
    ]
    kwargs = {"cwd": str(M.ROOT)}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(command, **kwargs)
    app._turto_update_launching = True
    _log(M, "install-start", f"{getattr(M, 'APP_VERSION', '')} -> {remote}")

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


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_automatic_updates_v6331", False):
        return

    def check_for_updates(self, silent=True):
        if getattr(self, "_turto_closing", False):
            return False
        if getattr(self, "_turto_update_launching", False):
            return False

        now = time.monotonic()
        last = float(getattr(self, "_turto_auto_update_last_check", 0.0) or 0.0)
        if silent and now - last < _RECENT_SILENT_CHECK_SECONDS:
            return False
        if getattr(self, "_turto_auto_update_running", False):
            return False

        self._turto_auto_update_last_check = now
        self._turto_auto_update_running = True
        try:
            M.set_setting("update_source", OFFICIAL_UPDATE_ROOT)
            M.set_setting("company_auto_updates", "1")
            variable = getattr(self, "update_source", None)
            if variable is not None:
                variable.set(OFFICIAL_UPDATE_ROOT)
        except Exception:
            pass

        def worker():
            outcome = ("current", "", None)
            try:
                manifest = _read_official_manifest()
                remote = str(manifest.get("version") or "").strip()
                if not remote:
                    raise ValueError("Manifest neobsahuje číslo verze.")
                current = str(getattr(M, "APP_VERSION", "0"))
                if _version_tuple(M, remote) > _version_tuple(M, current):
                    package = M._download_update_package(manifest)
                    outcome = ("install", remote, Path(package))
                else:
                    outcome = ("current", current, None)
            except Exception as exc:
                outcome = (
                    "error",
                    str(exc),
                    traceback.format_exc(limit=12),
                )

            def finish():
                self._turto_auto_update_running = False
                kind, value, extra = outcome
                if not _exists(self) or getattr(self, "_turto_closing", False):
                    return
                if kind == "install":
                    try:
                        _launch_updater(M, self, value, extra)
                    except Exception as exc:
                        _log(M, "install-error", traceback.format_exc(limit=12))
                        if not silent:
                            M.messagebox.showerror(
                                "Aktualizace",
                                f"Automatickou aktualizaci se nepodařilo spustit:\n\n{exc}",
                                parent=self,
                            )
                elif kind == "error":
                    _log(M, "check-error", str(extra or value))
                    if not silent:
                        M.messagebox.showerror(
                            "Aktualizace",
                            "Kontrola aktualizací se nezdařila. "
                            "Aplikace zůstává beze změny.\n\n" + value,
                            parent=self,
                        )
                elif not silent:
                    M.messagebox.showinfo(
                        "Aktualizace",
                        f"Používáte aktuální verzi {value}.",
                        parent=self,
                    )

            try:
                self.after(0, finish)
            except Exception:
                self._turto_auto_update_running = False
                if outcome[0] == "error":
                    _log(M, "check-error", str(outcome[2] or outcome[1]))

        threading.Thread(
            target=worker,
            name="TURTO-Automatic-Update",
            daemon=True,
        ).start()
        return True

    App.check_for_updates = check_for_updates

    # crm_runtime used to open a second modal offer five seconds after startup.
    # The base App already schedules check_for_updates(); suppress that duplicate
    # dialog and let this owner perform one unattended check.
    runtime = sys.modules.get("crm_runtime")
    if runtime is not None:
        runtime._live_update_checks = lambda _app: None

    old_init = App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            # Start sooner than the legacy five-second callback. The latter is
            # harmless because the recent-check guard collapses it.
            self.after(900, lambda: self.check_for_updates(silent=True))
        except Exception:
            pass
        return result

    App.__init__ = init
    App._turto_automatic_updates_v6331 = True
    M.OFFICIAL_UPDATE_ROOT = OFFICIAL_UPDATE_ROOT


__all__ = ["install", "OFFICIAL_UPDATE_ROOT"]
