"""Packaged TURTO artwork shared by source, frozen windows and onboarding."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

APP_USER_MODEL_ID = "TURTO.CRM"


def asset_roots(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    candidates = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS))
    # PyInstaller onedir puts data in _internal, even though app.ROOT is the
    # executable directory. Prefer the current bundle over old loose assets.
    candidates.extend((root / "_internal", root))
    return tuple(dict.fromkeys(candidates))


def logo_path(root=None):
    return next((p / "turto_logo.png" for p in asset_roots(root)
                 if (p / "turto_logo.png").is_file()), None)


def icon_pair(root=None):
    roots = asset_roots(root)
    for directory in roots:
        ico = directory / "turto_logo.ico"
        for filename in ("turto_icon.png", "turto_logo.png"):
            png = directory / filename
            if ico.is_file() and png.is_file():
                return ico, png, "packaged-logo"
    # Older generated icons are a recovery fallback, never an override of the
    # new company artwork delivered by an update.
    for directory in roots:
        ico, png = directory / "turto_crm.ico", directory / "turto_crm.png"
        if ico.is_file() and png.is_file():
            return ico, png, "legacy-generated"
    return None


def configure_window_icon(win, root=None, *, pair=None, tk_module=tk):
    pair = pair or icon_pair(root)
    if pair is None:
        return
    ico, png, source = pair
    signature = (str(ico), str(png), source)
    if getattr(win, "_turto_icon_identity_signature", None) == signature:
        win._turto_icon_identity_reuse_skips = int(
            getattr(win, "_turto_icon_identity_reuse_skips", 0) or 0) + 1
        return
    configured = False
    try:
        image = tk_module.PhotoImage(master=win, file=str(png))
        win.iconphoto(True, image)
        win._turto_crm_icon_photo = image
        configured = True
    except Exception:
        pass
    try:
        # Apply the multi-resolution ICO last on Windows: iconphoto can replace
        # the native small/large icon selected from this file.
        win.iconbitmap(default=str(ico))
        configured = True
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    if configured:
        win._turto_icon_asset_source = source
        win._turto_icon_identity_signature = signature


def create_logo_label(parent, root=None, size=64):
    """Show the exact transparent source on a light card in either UI theme."""
    label = ttk.Label(parent, text="TURTO", style="BrandAccent.TLabel")
    path = logo_path(root)
    if path is None:
        return label
    try:
        from PIL import Image, ImageTk
        pixels = max(size, min(size * 2, round(size * parent.winfo_fpixels("1i") / 96)))
        with Image.open(path) as source:
            image = source.convert("RGBA")
            image.thumbnail((pixels, pixels), Image.Resampling.LANCZOS)
        # The card is UI chrome; the original file and its colours/alpha remain
        # unchanged. Black artwork stays visible in the dark theme as well.
        card = Image.new("RGBA", image.size, "white")
        card.alpha_composite(image)
        photo = ImageTk.PhotoImage(card, master=parent)
        ttk.Style(parent).configure("TurtoLogo.TLabel", background="white", padding=2)
        label.configure(text="", image=photo, style="TurtoLogo.TLabel")
        label._turto_logo_photo = photo
        label._turto_logo_path = str(path)
    except Exception:
        pass
    return label
