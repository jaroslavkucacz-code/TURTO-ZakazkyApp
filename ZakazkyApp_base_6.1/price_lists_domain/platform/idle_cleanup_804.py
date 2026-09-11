"""Retire legacy full-window idle polling in TURTO CRM 8.0.4.

crm_runtime predates the current v628 palette owner, v770 dialog policy and the
packaged icon reuse layer. Its App.__init__ wrapper resolves helper functions
from crm_runtime globals at runtime, so this late layer can replace only those
obsolete helpers without changing the historical wrapper chain.

The resulting behavior is deliberately conservative:
- Calibri compatibility is applied once after the UI is built instead of walking
  every widget every 1.2 seconds forever.
- Toplevel icon/group identity is applied when each child window is created/map-
  ped, instead of traversing the entire widget tree every second.
- Dialog focus protection uses weak references to actual Toplevels instead of a
  recursive full-widget scan on every main-window Map/FocusIn event.
- The old crm_runtime Treeview palette repaint becomes a no-op because the final
  v628_modernui_resize theme wrapper owns the exact 8.x status palette.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import weakref

POLICY_OWNER = "price_lists_domain.platform.idle_cleanup_804"


def _walk_existing_toplevels(root: Any, Toplevel: Any):
    """One-time compatibility scan for windows created before this late policy."""
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


def _registry(app: Any) -> list[weakref.ReferenceType]:
    refs = getattr(app, "_turto_toplevel_registry_804", None)
    if not isinstance(refs, list):
        refs = []
        try:
            app._turto_toplevel_registry_804 = refs
        except Exception:
            pass
    return refs


def _register_toplevel(app: Any, win: Any) -> int:
    """Keep creation/map order without retaining destroyed dialogs strongly."""
    refs = _registry(app)
    live: list[weakref.ReferenceType] = []
    for item in refs:
        try:
            current = item()
        except Exception:
            current = None
        if current is None or current is win:
            continue
        try:
            if current.winfo_exists():
                live.append(item)
        except Exception:
            continue
    try:
        live.append(weakref.ref(win))
    except Exception:
        pass
    try:
        app._turto_toplevel_registry_804 = live
    except Exception:
        pass
    return len(live)


def _live_toplevels(app: Any) -> list[Any]:
    """Return live dialogs in most-recently-created/mapped order and prune refs."""
    live_refs: list[weakref.ReferenceType] = []
    windows: list[Any] = []
    for item in _registry(app):
        try:
            win = item()
        except Exception:
            win = None
        if win is None:
            continue
        try:
            if not win.winfo_exists():
                continue
        except Exception:
            continue
        live_refs.append(item)
        windows.append(win)
    try:
        app._turto_toplevel_registry_804 = live_refs
    except Exception:
        pass
    return windows


def _configure_child_identity(M: Any, app: Any, win: Any) -> None:
    """Apply child-window identity once; later Map events are idempotent."""
    try:
        if getattr(win, "_turto_child_identity_804", False):
            return
    except Exception:
        return

    configured = False
    try:
        from price_lists_domain.platform import icon_assets_803

        pair = icon_assets_803._existing_icon_pair(M)
        if pair is not None:
            icon_assets_803._configure_from_pair(M, win, pair)
            configured = True
    except Exception:
        pass

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


def _install_toplevel_runtime_policy(M: Any) -> bool:
    """Register/skin each future Toplevel directly, without a global Map hook."""
    try:
        Toplevel = M.tk.Toplevel
    except Exception:
        return False
    if getattr(Toplevel, "_turto_toplevel_registry_804", False):
        return True

    previous_init = Toplevel.__init__

    def init(self: Any, *args: Any, **kwargs: Any):
        result = previous_init(self, *args, **kwargs)
        try:
            app = self._root()
            _register_toplevel(app, self)
            _configure_child_identity(M, app, self)
            win_ref = weakref.ref(self)
            app_ref = weakref.ref(app)

            def mapped(event: Any = None) -> None:
                win = win_ref()
                owner = app_ref()
                if win is None or owner is None:
                    return
                if event is not None and getattr(event, "widget", win) is not win:
                    return
                _register_toplevel(owner, win)
                _configure_child_identity(M, owner, win)

            self.bind("<Map>", mapped, add="+")
        except Exception:
            pass
        return result

    Toplevel.__init__ = init
    Toplevel._turto_toplevel_registry_804 = True
    Toplevel._turto_toplevel_registry_previous_init = previous_init
    return True


def _install_event_driven_child_identity(M: Any, app: Any) -> None:
    """Cover pre-existing children once; future Toplevels are handled at creation."""
    _install_toplevel_runtime_policy(M)
    if getattr(app, "_turto_child_identity_map_804", False):
        return
    try:
        Toplevel = M.tk.Toplevel
    except Exception:
        return

    for win in _walk_existing_toplevels(app, Toplevel):
        _register_toplevel(app, win)
        _configure_child_identity(M, app, win)
    try:
        app._turto_child_identity_map_804 = True
    except Exception:
        pass


def _raise_registered_dialog(app: Any, event: Any = None) -> None:
    """Match the legacy z-order safeguard without recursively walking the UI."""
    try:
        grabbed = app.grab_current()
        if grabbed is not None and grabbed.winfo_exists():
            grabbed.lift()
            grabbed.focus_force()
            return
    except Exception:
        pass

    for win in reversed(_live_toplevels(app)):
        try:
            if str(win.state() or "") == "withdrawn":
                continue
            win.lift()
            win.focus_force()
            return
        except Exception:
            continue


def _install_dialog_registry_focus(M: Any, crm_runtime: Any) -> bool:
    """Keep 8.0.3 event coalescing, replacing only its expensive tree scan."""
    _install_toplevel_runtime_policy(M)
    try:
        from price_lists_domain.platform import runtime_optimization_803

        coalesced = runtime_optimization_803._make_dialog_chain_coalescer(
            _raise_registered_dialog
        )
        coalesced._turto_804_dialog_registry = True
        crm_runtime._raise_dialog_chain = coalesced
        return True
    except Exception:
        try:
            _raise_registered_dialog._turto_804_dialog_registry = True
            crm_runtime._raise_dialog_chain = _raise_registered_dialog
            return True
        except Exception:
            return False


def _install_same_user_restore_fast_path(M: Any, crm_runtime: Any) -> bool:
    """Skip the second startup user/theme refresh when the user is unchanged."""
    previous = getattr(crm_runtime, "_restore_local_user", None)
    cfg_reader = getattr(crm_runtime, "_cfg", None)
    cfg_writer = getattr(crm_runtime, "_save_cfg", None)
    if not callable(previous) or getattr(previous, "_turto_804_same_user_fast", False):
        return bool(callable(previous))
    if not callable(cfg_reader):
        return False

    def restore(app: Any):
        try:
            cfg = cfg_reader() or {}
            last = str(cfg.get("last_user", "") or "").strip()
            with M.db() as con:
                valid = [
                    row["name"]
                    for row in con.execute(
                        "SELECT name FROM users WHERE active=1 AND upper(trim(name))<>'ADMIN' ORDER BY name COLLATE CZECH"
                    )
                ]
            current = str(app.active_user.get() or "").strip()
            chosen = last if last in valid else (
                current if current in valid else (valid[0] if valid else "ADMIN")
            )
            if chosen.upper() == "ADMIN" and valid:
                chosen = valid[0]
            if chosen and chosen.upper() != "ADMIN" and chosen == current:
                if last != chosen and callable(cfg_writer):
                    try:
                        cfg_writer(last_user=chosen)
                    except Exception:
                        pass
                app._turto_same_user_restore_skips_804 = int(
                    getattr(app, "_turto_same_user_restore_skips_804", 0) or 0
                ) + 1
                return None
        except Exception:
            pass
        return previous(app)

    restore._turto_804_same_user_fast = True
    restore._turto_original = previous
    crm_runtime._restore_local_user = restore
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_idle_cleanup_804", False):
        return
    M._turto_idle_cleanup_804 = True

    try:
        import crm_runtime
    except Exception:
        return

    def force_calibri_once(app: Any) -> None:
        _apply_text_fonts_once(M, app)

    def event_driven_window_identity(app: Any) -> None:
        _install_event_driven_child_identity(M, app)

    def final_palette_owned_elsewhere(app: Any) -> None:
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
    dialog_registry = _install_dialog_registry_focus(M, crm_runtime)
    same_user_restore = _install_same_user_restore_fast_path(M, crm_runtime)

    M.IDLE_CLEANUP_804 = {
        "owner": POLICY_OWNER,
        "calibri_sweep": "startup-once",
        "child_window_identity": "per-toplevel-map-event",
        "dialog_focus": "weak-toplevel-registry-coalesced" if dialog_registry else "fallback",
        "legacy_tree_palette": "retired-v628-owner",
        "local_user_restore": "skip-unchanged-user-refresh" if same_user_restore else "unchanged",
        "recurring_widget_tree_polling": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_apply_text_fonts_once",
    "_register_toplevel",
    "_live_toplevels",
    "_configure_child_identity",
    "_install_toplevel_runtime_policy",
    "_install_event_driven_child_identity",
    "_raise_registered_dialog",
    "_install_dialog_registry_focus",
    "_install_same_user_restore_fast_path",
]
