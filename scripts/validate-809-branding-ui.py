#!/usr/bin/env python3
"""Inspect the real application header/dialog in both themes on isolated data."""
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
sys.path.insert(0, str(BASE))
os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def check_native_icons(window, destination, prefix):
    """Compare actual Windows caption/task-switch icons with the supplied ICO.

    Tk's iconbitmap query returns a bitmap name only for legacy X bitmaps; it
    returns an empty string for a successfully loaded native Windows icon.
    """
    import win32api
    import win32con
    import win32gui
    import win32ui
    from PIL import Image

    hwnd = int(window.tk.call("wm", "frame", window._w), 0)

    def render(icon, size, color):
        screen = win32gui.GetDC(0)
        source = win32ui.CreateDCFromHandle(screen)
        dc = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, size, size)
        previous = dc.SelectObject(bitmap)
        try:
            dc.FillSolidRect((0, 0, size, size), color)
            win32gui.DrawIconEx(dc.GetSafeHdc(), 0, 0, icon, size, size, 0, None, win32con.DI_NORMAL)
            return Image.frombytes("RGB", (size, size), bitmap.GetBitmapBits(True), "raw", "BGRX")
        finally:
            dc.SelectObject(previous)
            win32gui.DeleteObject(bitmap.GetHandle())
            dc.DeleteDC()
            win32gui.ReleaseDC(0, screen)

    for kind, metric in ((win32con.ICON_SMALL, win32con.SM_CXSMICON),
                         (win32con.ICON_BIG, win32con.SM_CXICON)):
        size = win32api.GetSystemMetrics(metric)
        actual = win32gui.SendMessage(hwnd, win32con.WM_GETICON, kind, 0)
        assert actual, (prefix, kind, "missing native icon")
        expected = win32gui.LoadImage(0, str(BASE / "turto_logo.ico"), win32con.IMAGE_ICON,
                                     size, size, win32con.LR_LOADFROMFILE)
        try:
            for color in (0xFFFFFF, 0x242424):
                image = render(actual, size, color)
                image.save(destination / f"{prefix}-icon-{size}-{color}.png")
                assert image.tobytes() == render(expected, size, color).tobytes(), (prefix, size, color)
        finally:
            win32gui.DestroyIcon(expected)


def run_ui(td):
    from PIL import ImageGrab, ImageTk
    os.environ["TURTO_CRM_DATA_ROOT"] = td
    os.environ["LOCALAPPDATA"] = str(Path(td) / "local")
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform import exe_distribution
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    exe_distribution.apply(app)
    app.APP_VERSION = (REPO / "build/windows/version.txt").read_text().strip()
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    window = app.App()
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(str(exc))
    destination = REPO / "dist" / "branding-preview"
    destination.mkdir(parents=True, exist_ok=True)
    try:
        for theme, filename in (("Tmavý", "dark.png"), ("Světlý", "light.png")):
            window.apply_theme(theme)
            window.state("normal")
            window.geometry("1220x720+0+0")
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                window.update()
                time.sleep(0.02)
            label = window.brand_logo
            assert label.winfo_ismapped() and label.cget("image")
            assert Path(label._turto_logo_path) == BASE / "turto_logo.png"
            rendered = ImageTk.getimage(label._turto_logo_photo)
            alpha = rendered.getchannel("A")
            assert sum(alpha.histogram()[:16]) > rendered.width * rendered.height * 0.65
            style = app.ttk.Style(window)
            assert style.lookup(label.cget("style"), "background") == style.lookup(
                label.master.cget("style"), "background")
            assert window._turto_icon_asset_source == "packaged-logo"
            check_native_icons(window, destination, theme + "-main")
            for widget in (label, window.user_button, window.notes_button, window.bell_button):
                assert widget.winfo_rootx() + widget.winfo_width() <= window.winfo_rootx() + window.winfo_width(), str(widget)
            dialog = app.tk.Toplevel(window)
            dialog.title("TURTO CRM – kontrola ikony")
            window.update()
            assert dialog._turto_icon_asset_source == "packaged-logo"
            check_native_icons(dialog, destination, theme + "-dialog")
            dialog.destroy()
            window.update()
            ImageGrab.grab(bbox=(window.winfo_rootx(), window.winfo_rooty(),
                                window.winfo_rootx() + window.winfo_width(),
                                window.winfo_rooty() + window.winfo_height())).save(destination / filename)
            # Small preview includes the actual native caption and the full logo.
            ImageGrab.grab(bbox=(window.winfo_rootx(), max(0, window.winfo_rooty() - 30),
                                window.winfo_rootx() + 360,
                                label.winfo_rooty() + label.winfo_height() + 12)).save(
                                    destination / ("header-" + filename))
        assert not errors, errors
    finally:
        window.destroy()
    print("TURTO CRM 8.0.10 transparent header and native window icons: OK")


def main():
    # SQLite connections owned by legacy runtime layers live until process exit.
    # Clean the isolated fixture only after the UI child has released its handles.
    with tempfile.TemporaryDirectory(prefix="turto-brand-ui-") as td:
        subprocess.run([sys.executable, str(Path(__file__).resolve()), "--data-root", td],
                       check=True, timeout=120)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--data-root":
        run_ui(sys.argv[2])
    else:
        main()
