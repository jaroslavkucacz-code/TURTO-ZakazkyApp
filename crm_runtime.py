# TURTO Zakazky CRM - stable runtime integrations
# v5.8.3: Windows identity/icon, automatic update checks, legacy cleanup and Overview cleanup.
import os
import sys
import subprocess
from pathlib import Path

APP_USER_MODEL_ID = "TURTO.ZakazkyCRM"
GITHUB_UPDATE = "https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
M = None

LEGACY_FILES = (
    "v58_features.py", "v581_cleanup.py",
    "Spustit_Zakazky_v5.bat", "Spustit_Zakazky_v5.vbs",
    "Spustit_QT_PREVIEW.bat", "qt_preview_v5.py",
    "AUDIT_v2.22.txt", "DULEZITE_v2.8_JEDNORAZOVY_RESET.txt",
    "latest.example.json", "Vytvorit_EXE.bat", "Vytvorit_manifest_aktualizace.py",
)


def _cleanup_legacy_files():
    """Delete only known obsolete program files. Never touches DB/user data/folders."""
    try:
        root = Path(M.ROOT)
    except Exception:
        return
    for name in LEGACY_FILES:
        try:
            p = root / name
            if p.is_file():
                p.unlink()
        except Exception:
            pass
    try:
        cache = root / "__pycache__"
        if cache.is_dir():
            import shutil
            shutil.rmtree(cache, ignore_errors=True)
    except Exception:
        pass


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
    if widget is None:
        return
    for method in ("pack_forget", "grid_remove", "place_forget"):
        try:
            getattr(widget, method)()
            return
        except Exception:
            pass


def _widget_text(widget):
    for key in ("text",):
        try:
            value = str(widget.cget(key) or "").strip().casefold()
            if value:
                return value
        except Exception:
            pass
    return ""


def _remove_crm_focus(root):
    """Remove the complete obsolete CRM FOCUS banner row from Overview.
    Uses several visible markers and removes the enclosing row, not just the label.
    """
    targets = []
    try:
        stack = [root]
        while stack:
            w = stack.pop()
            try:
                stack.extend(list(w.winfo_children()))
            except Exception:
                pass
            txt = _widget_text(w)
            if txt in ("crm focus", "focus crm", "otevřít upozornění") or "poptávek bez odezvy" in txt:
                targets.append(w)
    except Exception:
        return

    for w in targets:
        # In the current dashboard the marker is nested inside the banner row.
        # Climb two levels at most; never climb into the tab/root itself.
        candidate = getattr(w, "master", None)
        parent2 = getattr(candidate, "master", None) if candidate is not None else None
        if parent2 is not None and parent2 is not root:
            candidate = parent2
        _hide_widget(candidate if candidate is not None else w)


def _schedule_focus_cleanup(app):
    for delay in (20, 100, 300, 800, 1600):
        try:
            app.after(delay, lambda a=app: _remove_crm_focus(a))
        except Exception:
            pass


def _schedule_update_check(app):
    """Check shortly after startup; stay quiet when current, offer update when newer."""
    def run():
        try:
            M.set_setting("update_source", GITHUB_UPDATE)
            if hasattr(app, "update_source"):
                app.update_source.set(GITHUB_UPDATE)
            app.check_for_updates(silent=True)
        except Exception:
            pass
    try:
        app.after(5000, run)
    except Exception:
        pass


def _ps_quote(value):
    return str(value).replace("'", "''")


def create_windows_shortcuts(app):
    """Create stable Desktop + Start Menu shortcuts with TURTO icon."""
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
            M.messagebox.showinfo("Zástupce", "Vytvořen zástupce na ploše i v nabídce Start s ikonou TURTO.\n\nV nabídce Start vyhledejte „TURTO Zakázky CRM“, klikněte pravým tlačítkem a zvolte Připnout na hlavní panel.", parent=app)
        except Exception:pass
    except Exception as e:
        try:M.messagebox.showerror("Zástupce", f"Zástupce se nepodařilo vytvořit:\n{e}", parent=app)
        except Exception:pass


def apply(module):
    global M
    M = module
    _set_windows_app_id()
    _cleanup_legacy_files()

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
