"""Automatic official-channel checks; installation requires an explicit click."""
from __future__ import annotations

import json
import os
import queue
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
_PERIODIC_CHECK_MS = 10 * 60 * 1000


def _exists(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return widget is not None


def _version_tuple(M, value):
    """Compare stable and preview builds deterministically.

    Older preview builds treated ``8.0.0-preview.1`` as numerically newer than
    ``8.0.0``. 8.x uses a fixed-width tuple where stable releases sort after
    prereleases of the same numeric version.
    """
    text = str(value or "").strip().casefold()
    main, sep, prerelease = text.partition("-")
    numbers = []
    for part in main.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    numbers = (numbers + [0, 0, 0, 0])[:4]

    stable = 0 if sep else 1
    pre_number = 0
    if prerelease:
        for part in prerelease.replace("_", ".").split("."):
            digits = "".join(ch for ch in part if ch.isdigit())
            if digits:
                pre_number = int(digits)
    return tuple(numbers) + (stable, pre_number)


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
    # Cache busting is important for raw.githubusercontent.com: after publishing,
    # every workstation must see the new manifest immediately.
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


def _show_available_update(M, app):
    """A persistent, non-modal notice; startup checks never interrupt work."""
    from tkinter import ttk
    banner = getattr(app, "_turto_update_banner", None)
    manifest = getattr(app, "_turto_available_update", None)
    if not manifest:
        if _exists(banner):
            banner.destroy()
        app._turto_update_banner = None
        return
    if not _exists(banner):
        top = app.brand_logo.master.master
        banner = ttk.Frame(top, padding=(0, 8, 0, 0), style="Topbar.TFrame")
        banner.grid(row=1, column=0, columnspan=10, sticky="ew")
        banner.columnconfigure(0, weight=1)
        label = ttk.Label(banner, style="Topbar.TLabel")
        label.grid(row=0, column=0, sticky="w")
        ttk.Button(banner, text="Zobrazit aktualizaci", command=app.open_update_dialog,
                   style="Accent.TButton").grid(row=0, column=1, sticky="e")
        app._turto_update_banner = banner
        app._turto_update_banner_label = label
    app._turto_update_banner_label.configure(
        text=f"Je dostupná nová verze {manifest['version']}. Instalaci spustíte tlačítkem v nabídce aktualizace.")


def _show_update_offer(M, app):
    import tkinter as tk
    from tkinter import ttk
    manifest = getattr(app, "_turto_available_update", None)
    if not manifest:
        return
    previous = getattr(app, "_turto_update_offer", None)
    if _exists(previous):
        previous.lift()
        return
    win = tk.Toplevel(app)
    app._turto_update_offer = win
    win.title("Aktualizace TURTO CRM")
    win.transient(app)
    win.resizable(False, False)
    body = ttk.Frame(win, padding=24)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=f"Je dostupná verze {manifest['version']}",
              font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 12))
    ttk.Label(body, text="Uložte rozpracované změny. Po kliknutí na tlačítko se aktualizace stáhne, "
              "CRM se zavře a po instalaci se znovu otevře.\n\n"
              "Kontrola dostupnosti probíhá automaticky. Instalaci spouštíte vy.",
              wraplength=500, justify="left").pack(anchor="w")
    notes = str(manifest.get("notes") or "").strip()
    if notes:
        text = tk.Text(body, width=64, height=7, wrap="word", font=("Segoe UI", 10))
        text.insert("1.0", notes)
        text.configure(state="disabled")
        text.pack(fill="x", pady=(12, 0))
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(20, 0))
    ttk.Button(actions, text="Později", command=win.destroy).pack(side="left")
    ttk.Button(actions, text="Nainstalovat aktualizaci", style="Accent.TButton",
               command=lambda: app.install_available_update(dict(manifest))).pack(side="right")
    try:
        from branding import configure_window_icon
        configure_window_icon(win, M.ROOT)
    except Exception:
        pass


def _new_progress_window(app, remote):
    from update_progress import ProgressWindow
    return ProgressWindow(app, remote)


def _queue_ui(app, callback):
    app._turto_update_events.put(callback)


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_automatic_updates_v6338", False):
        return

    def check_for_updates(self, silent=False):
        """Check only. A separate installation button owns download and restart."""
        silent = bool(silent)
        disabled = str(os.environ.get("TURTO_DISABLE_AUTO_UPDATE", "")).strip().casefold()
        if disabled in {"1", "true", "yes", "ano"}:
            if not silent:
                M.messagebox.showinfo("Aktualizace", "Kontrola aktualizací je v tomto spuštění vypnutá.", parent=self)
            return False
        if (getattr(self, "_turto_closing", False) or getattr(self, "_turto_update_launching", False)
                or getattr(self, "_turto_update_installing", False)):
            return False
        now = time.monotonic()
        last = float(getattr(self, "_turto_auto_update_last_check", 0.0) or 0.0)
        if silent and last > 0.0 and now - last < _RECENT_SILENT_CHECK_SECONDS:
            return False
        if getattr(self, "_turto_auto_update_running", False):
            # A manual click during a background check gets the same result.
            if not silent:
                self._turto_update_check_visible = True
            return False
        self._turto_auto_update_last_check = now
        self._turto_auto_update_running = True
        self._turto_update_check_visible = not silent
        _log(M, "check-start", "silent" if silent else "manual")
        try:
            M.set_setting("update_source", OFFICIAL_UPDATE_ROOT)
            M.set_setting("company_auto_updates", "1")
            variable = getattr(self, "update_source", None)
            if variable is not None:
                variable.set(OFFICIAL_UPDATE_ROOT)
        except Exception:
            pass

        def worker():
            try:
                manifest = _read_official_manifest()
                remote = str(manifest.get("version") or "").strip()
                if not remote:
                    raise ValueError("Manifest neobsahuje číslo verze.")
                current = str(getattr(M, "APP_VERSION", "0"))
                newer = _version_tuple(M, remote) > _version_tuple(M, current)
                outcome = ("available" if newer else "current", manifest if newer else current)
            except Exception as exc:
                _log(M, "check-error", traceback.format_exc(limit=12))
                outcome = ("error", str(exc))

            def finish():
                self._turto_auto_update_running = False
                if not _exists(self) or getattr(self, "_turto_closing", False):
                    return
                visible = self._turto_update_check_visible
                kind, value = outcome
                if kind == "error":
                    if visible:
                        M.messagebox.showerror("Aktualizace", "Kontrola aktualizací se nezdařila.\n\n" + value, parent=self)
                    return
                self._turto_available_update = value if kind == "available" else None
                _show_available_update(M, self)
                _log(M, "check-" + kind, str(value.get("version")) if kind == "available" else value)
                if visible:
                    if kind == "available":
                        self.open_update_dialog()
                    else:
                        M.messagebox.showinfo("Aktualizace", f"Používáte aktuální verzi {value}.", parent=self)
            _queue_ui(self, finish)

        threading.Thread(target=worker, name="TURTO-Automatic-Update", daemon=True).start()
        return True

    def open_update_dialog(self):
        if getattr(self, "_turto_update_installing", False) or getattr(self, "_turto_update_launching", False):
            return
        _show_update_offer(M, self)

    def install_available_update(self, offered_manifest=None):
        """Called exclusively by the explicit 'Nainstalovat aktualizaci' button."""
        if (getattr(self, "_turto_closing", False) or getattr(self, "_turto_update_installing", False)
                or getattr(self, "_turto_update_launching", False)):
            return False
        manifest = offered_manifest or getattr(self, "_turto_available_update", None)
        if not manifest:
            return False
        remote = str(manifest["version"])
        progress = _new_progress_window(self, remote)
        self._turto_update_progress = progress
        self._turto_update_installing = True
        offer = getattr(self, "_turto_update_offer", None)
        if _exists(offer):
            offer.destroy()
        progress.report("Stahuji aktualizaci…", detail="CRM se zavře až po stažení a ověření aktualizace.")

        def worker():
            try:
                _log(M, "download-start", remote)
                download = getattr(M, "_download_update_with_progress", None)
                package = download(manifest, progress.report) if callable(download) else M._download_update_package(manifest)
                prepare = getattr(M, "_prepare_update_runtime", None)
                if callable(prepare):
                    progress.report("Připravuji instalaci…", detail="Ověřuji aktualizátor. CRM je stále otevřené.")
                    prepare()
                outcome = (Path(package), None)
            except Exception as exc:
                _log(M, "download-error", traceback.format_exc(limit=12))
                outcome = (None, str(exc))

            def finish():
                if not _exists(self) or getattr(self, "_turto_closing", False):
                    self._turto_update_installing = False
                    return
                package, error = outcome
                if error:
                    self._turto_update_installing = False
                    progress.fail("CRM zůstalo otevřené.\n\n" + error)
                    return
                try:
                    progress.report("Spouštím aktualizátor…", detail="Čekám na potvrzení připravenosti. CRM se poté bezpečně zavře.")
                    _log(M, "download-complete", remote)
                    _launch_updater(M, self, remote, package)
                except Exception as exc:
                    self._turto_update_installing = False
                    _log(M, "install-error", traceback.format_exc(limit=12))
                    progress.fail("Aktualizaci se nepodařilo spustit. CRM zůstalo otevřené.\n\n" + str(exc))
            _queue_ui(self, finish)

        threading.Thread(target=worker, name="TURTO-Update-Download", daemon=True).start()
        return True

    App.check_for_updates = check_for_updates
    App.open_update_dialog = open_update_dialog
    App.install_available_update = install_available_update
    runtime = sys.modules.get("crm_runtime")
    if runtime is not None:
        runtime._live_update_checks = lambda _app: None
    old_init = App.__init__

    def init(self, *args, **kwargs):
        self._turto_update_events = queue.SimpleQueue()
        result = old_init(self, *args, **kwargs)

        def poll():
            if not _exists(self) or getattr(self, "_turto_closing", False):
                return
            while not self._turto_update_events.empty():
                self._turto_update_events.get()()
            if not getattr(self, "_turto_closing", False):
                self.after(100, poll)

        def periodic_check():
            if getattr(self, "_turto_closing", False) or not _exists(self):
                return
            self.check_for_updates(silent=True)
            self._turto_periodic_update_after = self.after(_PERIODIC_CHECK_MS, periodic_check)

        self.after(100, poll)
        self.after(900, lambda: self.check_for_updates(silent=True))
        self._turto_periodic_update_after = self.after(_PERIODIC_CHECK_MS, periodic_check)
        return result

    App.__init__ = init
    App._turto_automatic_updates_v6338 = True
    M.OFFICIAL_UPDATE_ROOT = OFFICIAL_UPDATE_ROOT


__all__ = ["install", "OFFICIAL_UPDATE_ROOT"]
