"""Use only the supplied company artwork in historical identity wrappers."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.icon_assets_803"


def _existing_icon_pair(M: Any) -> tuple[Path, Path, str] | None:
    """Return ``(ico, png, source)`` for the first complete existing pair."""
    from branding import icon_pair
    return icon_pair(getattr(M, "ROOT", None))


def _configure_from_pair(M: Any, win: Any, pair: tuple[Path, Path, str]) -> None:
    from branding import configure_window_icon
    configure_window_icon(win, pair=pair, tk_module=M.tk)


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
        return _existing_icon_pair(module)

    def configure_identity(module: Any, win: Any) -> None:
        pair = ensure_icon_assets(module)
        if pair is not None:
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
        "preferred_existing_order": ("turto_logo",),
        "runtime_pillow_rendering": "disabled",
        "window_identity": "idempotent-per-icon-pair",
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
