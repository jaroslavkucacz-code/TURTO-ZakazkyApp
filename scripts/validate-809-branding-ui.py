#!/usr/bin/env python3
"""Inspect the real application header/dialog in both themes on isolated data."""
import os
from pathlib import Path
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
sys.path.insert(0, str(BASE))
os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def main():
    from PIL import ImageGrab
    with tempfile.TemporaryDirectory(prefix="turto-brand-ui-") as td:
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
                assert window._turto_icon_asset_source == "packaged-logo"
                for widget in (label, window.user_button, window.notes_button, window.bell_button):
                    assert widget.winfo_rootx() + widget.winfo_width() <= window.winfo_rootx() + window.winfo_width(), str(widget)
                dialog = app.tk.Toplevel(window)
                dialog.title("TURTO CRM – kontrola ikony")
                window.update()
                assert dialog._turto_icon_asset_source == "packaged-logo"
                dialog.destroy()
                window.update()
                ImageGrab.grab(bbox=(window.winfo_rootx(), window.winfo_rooty(),
                                    window.winfo_rootx() + window.winfo_width(),
                                    window.winfo_rooty() + window.winfo_height())).save(destination / filename)
            assert not errors, errors
        finally:
            window.destroy()
    print("TURTO CRM 8.0.9 real header and dialog branding: OK")


if __name__ == "__main__":
    main()
