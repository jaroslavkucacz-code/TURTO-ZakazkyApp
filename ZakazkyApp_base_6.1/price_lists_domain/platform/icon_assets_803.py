"""Reuse packaged TURTO icon assets before falling back to runtime rendering.

TURTO CRM's Windows package already ships ``turto_logo.ico`` and
``turto_logo.png`` and the executable itself uses the same ICO. Historical v770
also knows how to render ``turto_crm.*`` with Pillow when no icon files are
available. On a clean packaged start that rendering is redundant. This late
compatibility layer keeps the historical fallback intact while preferring files
that already exist on disk.
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

POLICY_OWNER = "price_lists_domain.platform.icon_assets_803"


def _existing_icon_pair(M: Any) -> tuple[Path, Path, str] | None:
    """Return ``(ico, png, source)`` for the first complete existing pair."""
    root = Path(getattr(M, "ROOT", Path.cwd()))
    for stem, source in (("turto_crm", "legacy-generated"), ("turto_logo", "packaged-logo")):
        ico = root / f"{stem}.ico"
        png = root / f"{stem}.png"
        if ico.is_file() and png.is_file():
            return ico, png, source
    return None


def _configure_from_pair(M: Any, win: Any, pair: tuple[Path, Path, str]) -> None:
    ico, png, source = pair
    try:
        win.iconbitmap(default=str(ico))
    except Exception:
        pass
    try:
        image = M.tk.PhotoImage(file=str(png))
        win.iconphoto(True, image)
        win._turto_crm_icon_photo = image
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TURTO.CRM")
        except Exception:
            pass
    try:
        win._turto_icon_asset_source = source
    except Exception:
        pass


def _install_v770_icon_reuse(M: Any) -> bool:
    """Patch v770 globals used by its already-installed identity wrappers."""
    try:
        import v770_runtime_policy as v770
    except Exception:
        return False

    previous_ensure = getattr(v770, "_ensure_icon_assets", None)
    previous_configure = getattr(v770, "_configure_identity", None)
    if not callable(previous_ensure) or not callable(previous_configure):
        return False
    if getattr(previous_configure, "_turto_803_packaged_icon_reuse", False):
        return True

    def ensure_icon_assets(module: Any):
        pair = _existing_icon_pair(module)
        if pair is not None:
            return pair
        # Preserve the historical Pillow renderer only for genuinely missing
        # assets (source/debug copies or an incomplete installation).
        previous_ensure(module)
        return _existing_icon_pair(module)

    def configure_identity(module: Any, win: Any) -> None:
        pair = ensure_icon_assets(module)
        if pair is None:
            # Defensive compatibility fallback: if the historical renderer failed,
            # let its original configuration path attempt whatever remains usable.
            return previous_configure(module, win)
        _configure_from_pair(module, win, pair)

    ensure_icon_assets._turto_803_packaged_icon_reuse = True
    ensure_icon_assets._turto_original_ensure_icon_assets = previous_ensure
    configure_identity._turto_803_packaged_icon_reuse = True
    configure_identity._turto_original_configure_identity = previous_configure
    v770._ensure_icon_assets = ensure_icon_assets
    v770._configure_identity = configure_identity
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_icon_assets_803", False):
        return
    M._turto_icon_assets_803 = True
    installed = _install_v770_icon_reuse(M)
    M.ICON_ASSET_OPTIMIZATION_803 = {
        "owner": POLICY_OWNER,
        "installed": bool(installed),
        "preferred_existing_order": ("turto_crm", "turto_logo"),
        "runtime_pillow_rendering": "fallback-only",
        "application_user_model_id": "TURTO.CRM",
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_existing_icon_pair",
    "_configure_from_pair",
    "_install_v770_icon_reuse",
]
