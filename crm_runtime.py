# TURTO Zakazky CRM - stable runtime integrations
# v5.8.4: stable install root migration, Windows identity/icon and automatic updates.
import os
import sys
import time
import shutil
import threading
import subprocess
from pathlib import Path

APP_USER_MODEL_ID = "TURTO.ZakazkyCRM"
GITHUB_UPDATE = "https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
M = None

LEGACY_FILES = (
    "v58_features.py", "v581_cleanup.py",
    "Spustit_Zakazky_v5.bat", "Spustit_Zakazky_v5.vbs",
    "Spustit_QT_PREVIEW.bat", "Spustit_Qt_PREVIEW.bat", "qt_preview_v5.py",
    "AUDIT_v2.22.txt", "DULEZITE_v2.8_JEDNORAZOVY_RESET.txt",
    "latest.example.json", "Vytvorit_EXE.bat", "Vytvorit_manifest_aktualizace.py",
)


def _is_legacy_install_root(root):
    return root.name.lower().startswith("zakazkyapp_v") and root.parent.name.upper() == "APP_TURTO_CRM"


def _copy_program_tree(src, dst):
    """Copy only program files to stable APP_TURTO_CRM root; user DB lives elsewhere."""
    skip = set(LEGACY_FILES) | {"__pycache__", "v5_error.log", "update_error.log", "crm_features_error.log", "crm_runtime_error.log"}
    for p in src.iterdir():
        if p.name in skip:
            continue
        target = dst / p.name
        if p.is_dir():
            if target.exists() and target.is_file():
                target.unlink()
            shutil.copytree(p, target, dirs_exist_ok=True)
        elif p.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def _launch_stable_root(root):
    vbs = root / "Spustit_Zakazky.vbs"
    pyw = root / "ZakazkyCRM.pyw"
    if sys.platform.startswith("win") and vbs.exists():
        subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(root))
    elif pyw.exists():
        subprocess.Popen([sys.executable, str(pyw)], cwd=str(root))


def _migrate_install_root_if_needed():
    """Move runtime from APP_TURTO_CRM\\ZakazkyApp_v* into APP_TURTO_CRM itself."""
    root = Path(M.ROOT).resolve()
    if not _is_legacy_install_root(root):
        return False
    stable = root.parent
    try:
        _copy_program_tree(root, stable)
        (stable / ".migrated_from_version_folder").write_text(root.name, encoding="utf-8")
        _launch_stable_root(stable)
        return True
    except Exception as e:
        try:(root / "migration_error.log").write_text(str(e), encoding="utf-8")
        except Exception:pass
        return False


def _cleanup_stable_root_later():
    """After migration, remove old version folders and stale package files from APP_TURTO_CRM."""
    root = Path(M.ROOT).resolve()
    if root.name.upper() != "APP_TURTO_CRM":
        return
    def work():
        time.sleep(4)
        for p in list(root.glob("ZakazkyApp_v*")):
            try:
                if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
                elif p.is_file() and p.suffix.lower() == ".zip": p.unlink(missing_ok=True)
            except Exception: pass
        for name in ("latest.json", "latest"):
            try:(root / name).unlink(missing_ok=True)
            except Exception:pass
        try:(root / ".migrated_from_version_folder").unlink(missing_ok=True)
        except Exception:pass
    threading.Thread(target=work, daemon=True).start()


def _cleanup_legacy_files():
    root = Path(M.ROOT).resolve()
    for name in LEGACY_FILES:
        try:(root / name).unlink(missing_ok=True)
        except Exception:pass
    try:shutil.rmtree(root / "__pycache__", ignore_errors=True)
    except Exception:pass


def _set_windows_app_id():
    if not sys.platform.startswith("win"): return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception: pass


def _set_window_icon(app):
    try:
        ico = Path(M.ROOT) / "turto_logo.ico"
        if ico.exists(): app.iconbitmap(default=str(ico))
    except Exception: pass
    try:
        import tkinter as tk
        png = Path(M.ROOT) / "turto_logo.png"
        if png.exists():
            photo = tk.PhotoImage(file=str(png)); app.iconphoto(True, photo); app._turto_iconphoto = photo
    except Exception: pass


def _schedule_update_check(app):
    def run():
        try:
            M.set_setting("update_source", GITHUB_UPDATE)
            if hasattr(app, "update_source"): app.update_source.set(GITHUB_UPDATE)
            app.check_for_updates(silent=True)
        except Exception: pass
    try: app.after(4500, run)
    except Exception: pass


def _ps_quote(value):
    return str(value).replace("'", "''")


def create_windows_shortcuts(app):
    if not sys.platform.startswith("win"):
        try:M.messagebox.showinfo("Zástupce", "Tato funkce je určena pro Windows.", parent=app)
        except Exception:pass
        return
    root = Path(M.ROOT).resolve()
    launcher = root / "ZakazkyCRM.pyw"
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
  $s.Arguments = '"{_ps_quote(launcher)}"'
  $s.WorkingDirectory = '{_ps_quote(root)}'
  $s.IconLocation = '{_ps_quote(ico)},0'
  $s.Description = 'TURTO Zakázky CRM'
  $s.Save()
}}
"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        M.messagebox.showinfo("Zástupce", "Vytvořen zástupce na ploše i v nabídce Start s ikonou TURTO.\n\nVe Startu vyhledejte „TURTO Zakázky CRM“ a zvolte Připnout na hlavní panel.", parent=app)
    except Exception as e:
        try:M.messagebox.showerror("Zástupce", f"Zástupce se nepodařilo vytvořit:\n{e}", parent=app)
        except Exception:pass


def apply(module):
    global M
    M = module
    _set_windows_app_id()

    # First start after 5.8.4 may still happen from the historical version subfolder.
    # Copy to stable root, start it there and stop this legacy process.
    if _migrate_install_root_if_needed():
        raise SystemExit(0)

    _cleanup_legacy_files()
    _cleanup_stable_root_later()
    module.App.create_desktop_shortcut = create_windows_shortcuts

    original_init = module.App.__init__
    def init(self, *args, **kwargs):
        result = original_init(self, *args, **kwargs)
        try: module.set_setting("update_source", GITHUB_UPDATE)
        except Exception: pass
        _set_window_icon(self)
        _schedule_update_check(self)
        return result
    module.App.__init__ = init
