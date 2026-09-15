"""Windows Shell identity shared by the running CRM and its shortcuts.

Window icons (WM_SETICON) alone do not select the icon of a pinned taskbar
group. Keep its Shell properties and existing shortcuts in sync as well.
"""
from pathlib import Path
import os
import subprocess
import sys

APP_USER_MODEL_ID = "TURTO.CRM"
TASKBAR_ICON_NAME = "turto_taskbar_transparent.ico"


def set_process_identity():
    """Call before creating the first Tk window, including the data wizard."""
    if sys.platform.startswith("win"):
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def _canonical(path):
    return os.path.normcase(str(Path(os.path.expandvars(str(path))).resolve()))


def shortcut_folders():
    from win32com.shell import shell, shellcon
    desktop = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, 0, 0))
    programs = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_PROGRAMS, 0, 0))
    roaming = Path(shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0))
    return (desktop, programs, programs / "TURTO CRM",
            roaming / "Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar")


def _notify_item(path):
    import ctypes
    # SHCNE_UPDATEITEM + SHCNF_PATHW | SHCNF_FLUSHNOWAIT: refresh only this
    # application item. Never clear the global cache or restart Explorer.
    notify = ctypes.windll.shell32.SHChangeNotify
    notify.argtypes = (ctypes.c_long, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
    notify.restype = None
    notify(0x2000, 0x2005, ctypes.c_wchar_p(str(path)), None)


def repair_shortcuts(root, icon, *, folders=None):
    """Update only links targeting this exact installation; preserve pinning.

    Names are never proof of ownership. Other TURTO tools, old installations,
    Python shortcuts and all launch arguments remain untouched.
    """
    import pythoncom
    from win32com.shell import shell
    from win32com.propsys import propsys, pscon
    root, icon = Path(root).resolve(), Path(icon).resolve()
    owned = {_canonical(root / name) for name in
             ("TURTO CRM.exe", "Spustit_Zakazky.bat", "ZakazkyCRM.pyw")}
    report = {"updated": [], "errors": []}
    for folder in shortcut_folders() if folders is None else folders:
        for path in Path(folder).glob("*.lnk"):
            try:
                link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                    pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
                persist = link.QueryInterface(pythoncom.IID_IPersistFile)
                persist.Load(str(path), pythoncom.STGM_READWRITE)
                target = link.GetPath(shell.SLGP_RAWPATH)[0]
                if not target or _canonical(target) not in owned:
                    continue
                properties = link.QueryInterface(propsys.IID_IPropertyStore)
                app_id = properties.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
                old_icon, index = link.GetIconLocation()
                if _canonical(old_icon) == _canonical(icon) and index == 0 and app_id == APP_USER_MODEL_ID:
                    continue
                link.SetIconLocation(str(icon), 0)
                properties.SetValue(pscon.PKEY_AppUserModel_ID,
                    propsys.PROPVARIANTType(APP_USER_MODEL_ID, pythoncom.VT_LPWSTR))
                properties.Commit()
                persist.Save(str(path), 0)
                _notify_item(path)
                report["updated"].append(str(path))
            except Exception as exc:
                report["errors"].append({"path": str(path), "error": str(exc)})
    return report


def initialize(root, *, repair=True):
    if not sys.platform.startswith("win"):
        return {}
    try:
        set_process_identity()
        if repair:
            from branding import taskbar_icon_path
            icon = taskbar_icon_path(root)
            if icon is not None:
                return repair_shortcuts(root, icon)
    except Exception as exc:
        # An unavailable/read-only Shell must never prevent opening the CRM.
        return {"updated": [], "errors": [{"error": str(exc)}]}
    return {}


def configure_window(win, root, icon):
    """Set the Shell's group/pinning icon before assigning the window AppID."""
    if not sys.platform.startswith("win"):
        return
    import pythoncom
    from win32com.propsys import propsys, pscon
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(root)
    command = ([str(Path(sys.executable).resolve())] if getattr(sys, "frozen", False)
               else [sys.executable, str(root / "ZakazkyCRM.pyw")])
    values = (
        (pscon.PKEY_AppUserModel_RelaunchCommand, subprocess.list2cmdline(command)),
        (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "TURTO CRM"),
        (pscon.PKEY_AppUserModel_RelaunchIconResource, str(Path(icon).resolve()) + ",0"),
        (pscon.PKEY_AppUserModel_ID, APP_USER_MODEL_ID),
    )
    hwnd = int(win.tk.call("wm", "frame", win._w), 0)
    if not hwnd:
        # One deferred attempt, no recurring sweep or global event hook.
        if not getattr(win, "_turto_shell_icon_pending", False):
            win._turto_shell_icon_pending = True
            win.after_idle(lambda: configure_window(win, root, icon))
        return
    properties = propsys.SHGetPropertyStoreForWindow(hwnd)
    for key, value in values:
        properties.SetValue(key, propsys.PROPVARIANTType(value, pythoncom.VT_LPWSTR))
    win._turto_taskbar_icon_resource = values[2][1]

    def clear(event):
        if event.widget is win:
            for key, _ in values:
                try:
                    properties.SetValue(key, propsys.PROPVARIANTType(None, pythoncom.VT_EMPTY))
                except Exception:
                    pass
    win.bind("<Destroy>", clear, add="+")
