"""Native maximize button for normal Windows dialogs; never for popup menus.

The owner/transient relationship and modal grab are retained. No window procedure
is replaced and no Tk event loop is entered recursively.
"""
from __future__ import annotations
import sys


def native_maximize_button(win):
    if not sys.platform.startswith('win'):
        return False
    try:
        if not win.winfo_exists() or win.overrideredirect():
            return False
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(win.winfo_id(), 2)  # GA_ROOT: not the owner
        getter = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
        setter = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
        getter.argtypes = [wintypes.HWND, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        old = getter(hwnd, -16)  # GWL_STYLE
        desired = old | 0x00010000 | 0x00040000 | 0x00080000
        # WS_MAXIMIZEBOX | WS_THICKFRAME | WS_SYSMENU; no extra taskbar window.
        if old != desired:
            ctypes.set_last_error(0)
            previous = setter(hwnd, -16, desired)
            if not previous and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            # Refresh non-client cache without moving, resizing or activating.
            if not user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0037):
                raise ctypes.WinError(ctypes.get_last_error())
        return True
    except Exception as exc:
        # Diagnostics stay on the widget; a native-decoration failure must not
        # prevent access to the document or interfere with the modal event flow.
        try: win._turto_chrome_error = str(exc)
        except Exception: pass
        return False


def is_maximized(win):
    try:
        if win.state() == 'zoomed' or bool(win.attributes('-fullscreen')):
            return True
        if not sys.platform.startswith('win'):
            return bool(win.attributes('-zoomed'))
    except Exception:
        pass
    return False


def prepare_dialog(win):
    try:
        if not win.winfo_exists() or win.overrideredirect():
            return
        win.resizable(True, True)
        native_maximize_button(win)
    except Exception:
        pass
