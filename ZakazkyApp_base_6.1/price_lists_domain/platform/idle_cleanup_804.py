"""Retire legacy full-window idle polling in TURTO CRM 8.0.4.

crm_runtime predates the current v628 palette owner, v770 dialog policy and the
packaged icon reuse layer. Its App.__init__ wrapper resolves helper functions
from crm_runtime globals at runtime, so this late layer can replace only those
obsolete helpers without changing the historical wrapper chain.

The resulting behavior is deliberately conservative:
- Calibri compatibility is applied once after the UI is built instead of walking
  every widget every 1.2 seconds forever.
- Toplevel icon/group identity is applied on Map events and once to any windows
  that already exist, instead of traversing the entire widget tree every second.
- The old crm_runtime Treeview palette repaint becomes a no-op because the final
  v628_modernui_resize theme wrapper owns the exact 8.x status palette.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.idle_cleanup_804"


def _walk_existing_toplevels(root: Any, Toplevel: Any):
    try:
        children = tuple(root.winfo_children())
    except Exception:
        return
    for child in children:
        try:
            if isinstance(child, Toplevel):
                yield child
            yield from _walk_existing_toplevels(child, Toplevel)
        except Exception:
            continue


def _apply_text_fonts_once(M: Any, app: Any) -> int:
    """Preserve the old Calibri guarantee without a permanent polling loop."""
    try:
        Text = M.tk.Text
    except Exception:
        return 0
    changed = 0
    stack = [app]
    while stack:
        widget = stack.pop()
        try:
            if isinstance(widget, Text):
                widget.configure(font=("Calibri", 11))
                changed += 1
            stack.extend(widget.winfo_children())
        except Exception:
            continue
    try:
        app._turto_calibri_widgets_checked_once = changed
    except Exception:
        pass
    return changed


def _configure_child_identity(M: Any, app: Any, win: Any) -> None:
    """Apply child-window identity once; later Map events are idempotent."""
    try:
        if getattr(win, "_turto_child_identity_804", False):
            return
    except Exception:
        return

    # Prefer the same packaged icon pair as the 8.0.3 main-window owner.
    configured = False
    try:
        from price_lists_domain.platform import icon_assets_803

        pair = icon_assets_803._existing_icon_pair(M)
        if pair is not None:
            icon_assets_803._configure_from_pair(M, win, pair)
            configured = True
    except Exception:
        pass

    # Defensive fallback for source/debug copies with only the historical ICO.
    if not configured:
        try:
            ico = Path(getattr(M, "ROOT", Path.cwd())) / "turto_logo.ico"
            if ico.is_file():
                win.iconbitmap(default=str(ico))
        except Exception:
            pass

    try:
        win.group(app)
    except Exception:
        pass
    try:
        win._turto_child_identity_804 = True
    except Exception:
        pass


def _install_event_driven_child_identity(M: Any, app: Any) -> None:
    """Replace crm_runtime's 1 s recursive window sweep with Map handling."""
    if getattr(app, "_turto_child_identity_map_804", False):
        return
    try:
        Toplevel = M.tk.Toplevel
    except Exception:
        return

    # Cover a morning/startup dialog that may have been created before the
    # crm_runtime post-init hook gets here.
    for win in _walk_existing_toplevels(app, Toplevel):
        _configure_child_identity(M, app, win)

    def mapped(event: Any = None) -> None:
        win = getattr(event, "widget", None)
        try:
            if isinstance(win, Toplevel):
                _configure_child_identity(M, app, win)
        except Exception:
            pass

    try:
        app.bind_all("<Map>", mapped, add="+")
        app._turto_child_identity_map_804 = True
        app._turto_child_identity_map_handler_804 = mapped
    except Exception:
        pass


def apply(M: Any) -> None:
    if getattr(M, "_turto_idle_cleanup_804", False):
        return
    M._turto_idle_cleanup_804 = True

    try:
        import crm_runtime
    except Exception:
        return

    # crm_runtime's already-installed App.__init__ wrapper looks up these names
    # from its module globals when App() actually starts, so replacing them here
    # prevents the recurring after() chains from ever being created.
    def force_calibri_once(app: Any) -> None:
        _apply_text_fonts_once(M, app)

    def event_driven_window_identity(app: Any) -> None:
        _install_event_driven_child_identity(M, app)

    def final_palette_owned_elsewhere(app: Any) -> None:
        # v628_modernui_resize applies the exact current light/dark status palette
        # after every real theme change. Historical crm_runtime repaint is retired.
        try:
            app._turto_legacy_palette_repaint_skips = int(
                getattr(app, "_turto_legacy_palette_repaint_skips", 0) or 0
            ) + 1
        except Exception:
            pass
        return None

    crm_runtime._force_calibri = force_calibri_once
    crm_runtime._window_identity_sweep = event_driven_window_identity
    crm_runtime._apply_tree_palette = final_palette_owned_elsewhere

    M.IDLE_CLEANUP_804 = {
        "owner": POLICY_OWNER,
        "calibri_sweep": "startup-once",
        "child_window_identity": "map-event-driven",
        "legacy_tree_palette": "retired-v628-owner",
        "recurring_widget_tree_polling": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_apply_text_fonts_once",
    "_configure_child_identity",
    "_install_event_driven_child_identity",
]
