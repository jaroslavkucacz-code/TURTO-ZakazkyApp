# TURTO Zakazky CRM - stable runtime integrations
# Keeps Windows identity/icon stable, removes obsolete CRM FOCUS strip,
# and checks for updates automatically after application startup.
import os
import sys
from pathlib import Path

APP_USER_MODEL_ID = "TURTO.ZakazkyCRM"
GITHUB_UPDATE = "https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"

M = None


def _set_windows_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _set_window_icon(app):
    try:
        ico = Path(M.ROOT) / "turto_logo.ico"
        if ico.exists():
            app.iconbitmap(default=str(ico))
    except Exception:
        pass
    try:
        import tkinter as tk
        png = Path(M.ROOT) / "turto_logo.png"
        if png.exists():
            photo = tk.PhotoImage(file=str(png))
            app.iconphoto(True, photo)
            app._turto_iconphoto = photo
    except Exception:
        pass


def _hide_widget(widget):
    try:
        widget.pack_forget(); return
    except Exception:
        pass
    try:
        widget.grid_remove(); return
    except Exception:
        pass
    try:
        widget.place_forget()
    except Exception:
        pass


def _remove_crm_focus(root):
    """Remove the obsolete CRM FOCUS banner row from Overview only.
    No database records are touched.
    """
    try:
        children = list(root.winfo_children())
    except Exception:
        return
    for w in children:
        _remove_crm_focus(w)
        try:
            txt = str(w.cget("text") or "").strip().casefold()
        except Exception:
            txt = ""
        if txt in ("crm focus", "focus crm"):
            # The label lives inside a dedicated banner frame; remove that frame.
            parent = getattr(w, "master", None)
            target = parent if parent is not None else w
            _hide_widget(target)


def _schedule_focus_cleanup(app):
    for delay in (50, 250, 800):
        try:
            app.after(delay, lambda a=app: _remove_crm_focus(a))
        except Exception:
            pass


def _schedule_update_check(app):
    # Silent means no "you are up to date" popup. If a newer version exists,
    # the existing updater still offers it to the user.
    def run():
        try:
            M.set_setting("update_source", GITHUB_UPDATE)
            if hasattr(app, "update_source"):
                app.update_source.set(GITHUB_UPDATE)
            app.check_for_updates(silent=True)
        except Exception:
            # Startup must never fail just because GitHub is temporarily unavailable.
            pass
    try:
        app.after(6500, run)
    except Exception:
        pass


def apply(module):
    global M
    M = module
    _set_windows_app_id()

    # Patch the final constructor after all other feature layers are installed.
    original_init = module.App.__init__
    def init(self, *args, **kwargs):
        result = original_init(self, *args, **kwargs)
        try:
            module.set_setting("update_source", GITHUB_UPDATE)
        except Exception:
            pass
        _set_window_icon(self)
        _schedule_focus_cleanup(self)
        _schedule_update_check(self)
        return result
    module.App.__init__ = init

    # Dashboard can rebuild itself during use; clean the obsolete banner afterwards.
    for name in ("build_dashboard", "refresh_dashboard", "refresh_all"):
        original = getattr(module.App, name, None)
        if not callable(original):
            continue
        def make_wrapper(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                _schedule_focus_cleanup(self)
                return result
            return wrapped
        setattr(module.App, name, make_wrapper(original))
