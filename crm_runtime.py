# TURTO Zakazky CRM - stable runtime integrations
# Windows identity/icon, automatic update checks and Overview cleanup.
import os
import sys
import subprocess
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
    for method in ("pack_forget", "grid_remove", "place_forget"):
        try:
            getattr(widget, method)()
            return
        except Exception:
            pass


def _remove_crm_focus(root):
    """Remove the obsolete CRM FOCUS banner from Overview; data stay untouched."""
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
            parent = getattr(w, "master", None)
            _hide_widget(parent if parent is not None else w)


def _schedule_focus_cleanup(app):
    for delay in (30, 150, 500, 1200):
        try:
            app.after(delay, lambda a=app: _remove_crm_focus(a))
        except Exception:
            pass


def _schedule_update_check(app):
    """Check shortly after startup; no popup when current, offer update when newer."""
    def run():
        try:
            M.set_setting("update_source", GITHUB_UPDATE)
            if hasattr(app, "update_source"):
                app.update_source.set(GITHUB_UPDATE)
            app.check_for_updates(silent=True)
        except Exception:
            # Offline GitHub must never prevent CRM startup.
            pass
    try:
        app.after(6500, run)
    except Exception:
        pass


def _ps_quote(value):
    return str(value).replace("'", "''")


def create_windows_shortcuts(app):
    """Create stable Desktop + Start Menu shortcuts with TURTO icon.
    The Start Menu shortcut can be pinned to the Windows taskbar normally.
    """
    if not sys.platform.startswith("win"):
        try:M.messagebox.showinfo("Zástupce", "Tato funkce je určena pro Windows.", parent=app)
        except Exception:pass
        return
    root = Path(M.ROOT).resolve()
    app_py = root / "app.py"
    ico = root / "turto_logo.ico"
    exe = Path(sys.executable).resolve()
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists(): exe = pyw
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "TURTO Zakázky CRM.lnk"
    start_menu = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "TURTO Zakázky CRM.lnk"
    script = f"""
$ws = New-Object -ComObject WScript.Shell
$targets = @('{_ps_quote(desktop)}','{_ps_quote(start_menu)}')
foreach ($p in $targets) {{
  $s = $ws.CreateShortcut($p)
  $s.TargetPath = '{_ps_quote(exe)}'
  $s.Arguments = '"{_ps_quote(app_py)}"'
  $s.WorkingDirectory = '{_ps_quote(root)}'
  $s.IconLocation = '{_ps_quote(ico)},0'
  $s.Description = 'TURTO Zakázky CRM'
  $s.Save()
}}
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            M.messagebox.showinfo("Zástupce", "Vytvořen zástupce na ploše i v nabídce Start s ikonou TURTO.\n\nPro připnutí na hlavní panel vyhledejte ve Startu „TURTO Zakázky CRM“, klikněte pravým tlačítkem a zvolte Připnout na hlavní panel.", parent=app)
        except Exception:pass
    except Exception as e:
        try:M.messagebox.showerror("Zástupce", f"Zástupce se nepodařilo vytvořit:\n{e}", parent=app)
        except Exception:pass


def apply(module):
    global M
    M = module
    _set_windows_app_id()

    # Existing Settings button now creates a stable pin-friendly shortcut as well.
    module.App.create_desktop_shortcut = create_windows_shortcuts

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

    # Dashboard can rebuild during use; remove the obsolete banner afterwards too.
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
