"""TURTO CRM final contextual UI policy (7.9.3+, optimized for 7.9.4).

This module is deliberately applied after the historical UI layers.  It owns only
cross-workspace selection policy: impossible commands are disabled, archive and
restore follow the selected row state, and redundant legacy startup rebuilds are
coalesced.  Business logic and the existing row double-click owner stay intact.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.ui_cleanup_793"

# v7.5 used four delayed safety rebuilds after its immediate pass.  The build
# wrappers already configure each workspace and the immediate (0 ms) fallback is
# retained.  Later rebuilds only recreate the same menus/toolbars and can replace
# the final policy installed by this module.
V750_REDUNDANT_REBUILD_DELAYS = frozenset({80, 260, 760, 1650})

WORKSPACES = {
    "projects": {
        "tree": "project_tree",
        "tab": "projects",
        "table": "projects",
        "prefix": "p",
        "refresh": "refresh_projects",
        "state_column": "active",
        "state_default": 1,
        "archived_value": 0,
        "menu_attr": "_v760_row_menu",
        "controls_attr": "_v760_project_archive_controls",
        "single_labels": (
            "Otevřít / upravit",
            "Sloučit s jinou Akcí",
            "Smazat",
        ),
        "active_single_labels": (
            "Otevřít / upravit",
            "Sloučit s jinou Akcí",
        ),
    },
    "actions": {
        "tree": "action_tree",
        "tab": "actions",
        "table": "actions",
        "prefix": "a",
        "refresh": "refresh_actions",
        "state_column": "archived",
        "state_default": 0,
        "archived_value": 1,
        "menu_attr": "_v750_row_menu",
        "controls_attr": "_v750_actions_archive_controls",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit poptávku",
            "Přidat připomínku",
            "Smazat / zrušit",
        ),
        "active_single_labels": (),
    },
    "requests": {
        "tree": "request_tree",
        "tab": "requests",
        "table": "requests",
        "prefix": "r",
        "refresh": "refresh_requests",
        "state_column": "archived",
        "state_default": 0,
        "archived_value": 1,
        "menu_attr": "_v750_row_menu",
        "controls_attr": "_v750_requests_archive_controls",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit e-mail",
            "Obdrženo dnes",
            "Bez odezvy",
            "Trvale smazat z evidence",
        ),
        "active_single_labels": (),
    },
    "mivo": {
        "tree": "mivo_tree",
        "tab": "mivo",
        "table": "requests",
        "prefix": "r",
        "refresh": "refresh_mivo_requests",
        "state_column": "archived",
        "state_default": 0,
        "archived_value": 1,
        "menu_attr": "_v750_row_menu",
        "controls_attr": "_v750_mivo_archive_controls",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit e-mail",
            "Obdrženo dnes",
            "Bez odezvy",
            "Trvale smazat z evidence",
        ),
        "active_single_labels": (),
    },
    "tasks": {
        "tree": "task_tree",
        "tab": "tasks",
        "table": "tasks",
        "prefix": "t",
        "refresh": "refresh_tasks",
        "state_column": "archived",
        "state_default": 0,
        "archived_value": 1,
        "menu_attr": "_v760_row_menu",
        "controls_attr": "_v760_task_archive_controls",
        "single_labels": (
            "Otevřít / upravit",
            "Hotovo / znovu otevřít",
            "Smazat",
        ),
        "active_single_labels": (
            "Otevřít / upravit",
            "Hotovo / znovu otevřít",
        ),
    },
}

ARCHIVE_LABEL = "📦 Archivovat vybrané"
RESTORE_LABEL = "↩ Obnovit vybrané"
EMPTY_CAPABILITIES = {
    "ids": [],
    "single": False,
    "can_archive": False,
    "can_restore": False,
}


def _empty_capabilities() -> dict[str, Any]:
    return dict(EMPTY_CAPABILITIES)


def _widget_exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _selected_ids(tree: Any, prefix: str) -> list[int]:
    if not _widget_exists(tree):
        return []
    result: list[int] = []
    try:
        selection = tree.selection()
    except Exception:
        return []
    for iid in selection:
        token = str(iid)
        if not token.startswith(prefix):
            continue
        number = token[len(prefix):]
        if number.isdigit():
            value = int(number)
            if value not in result:
                result.append(value)
    return result


def workspace_capabilities(
    M: Any,
    tree: Any,
    table: str,
    prefix: str,
    state_column: str = "archived",
    state_default: int = 0,
    archived_value: int = 1,
) -> dict[str, Any]:
    """Describe meaningful archive actions for the current Treeview selection.

    The original four-argument API is retained for the 7.9.3 regression test.
    Project rows use ``active=0`` as their archive state; other workspaces use
    ``archived=1``.
    """
    ids = _selected_ids(tree, prefix)
    result = _empty_capabilities()
    result["ids"] = ids
    if not ids or table not in {"projects", "actions", "requests", "tasks"}:
        return result
    if state_column not in {"active", "archived"}:
        return result

    marks = ",".join("?" for _ in ids)
    try:
        with M.db() as con:
            row = con.execute(
                f'SELECT COUNT(*) AS valid_count, '
                f'SUM(CASE WHEN COALESCE("{state_column}",?)=? THEN 1 ELSE 0 END) AS archived_count '
                f'FROM "{table}" WHERE id IN ({marks})',
                tuple([int(state_default), int(archived_value), *ids]),
            ).fetchone()
        valid_count = int(row["valid_count"] if row else 0)
        archived_count = int((row["archived_count"] if row else 0) or 0)
    except Exception:
        return result

    active_count = max(0, valid_count - archived_count)
    result["single"] = len(ids) == 1 and valid_count == 1
    result["can_archive"] = active_count > 0
    result["can_restore"] = archived_count > 0
    return result


def _set_button_enabled(button: Any, enabled: bool) -> None:
    if not _widget_exists(button):
        return
    try:
        button.state(["!disabled"] if enabled else ["disabled"])
        return
    except Exception:
        pass
    try:
        button.configure(state="normal" if enabled else "disabled")
    except Exception:
        pass


def _find_button(root: Any, label: str) -> Any:
    if not _widget_exists(root):
        return None
    for widget in _walk(root):
        try:
            if (
                widget.winfo_class().endswith("Button")
                and str(widget.cget("text") or "").strip() == label
            ):
                return widget
        except Exception:
            continue
    return None


def _workspace_parts(app: Any, key: str) -> tuple[dict[str, Any] | None, Any]:
    spec = WORKSPACES.get(key)
    if not spec:
        return None, None
    return spec, getattr(app, str(spec["tree"]), None)


def _toolbar_buttons(app: Any, key: str, spec: dict[str, Any], tree: Any) -> tuple[Any, Any]:
    """Return archive/restore controls without rescanning the tab on every click."""
    cached = getattr(tree, "_turto_context_archive_buttons", None)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and all(_widget_exists(button) for button in cached)
    ):
        return cached

    controls = getattr(app, str(spec.get("controls_attr") or ""), None)
    if isinstance(controls, (tuple, list)) and len(controls) >= 3:
        archive, restore = controls[1], controls[2]
        if _widget_exists(archive) and _widget_exists(restore):
            result = (archive, restore)
            try:
                tree._turto_context_archive_buttons = result
            except Exception:
                pass
            return result

    try:
        tab = app.tabs[str(spec["tab"])]
    except Exception:
        tab = None
    archive = _find_button(tab, ARCHIVE_LABEL)
    restore = _find_button(tab, RESTORE_LABEL)
    result = (archive, restore)
    if _widget_exists(archive) or _widget_exists(restore):
        try:
            tree._turto_context_archive_buttons = result
        except Exception:
            pass
    return result


def _apply_toolbar_caps(app: Any, key: str, spec: dict[str, Any], tree: Any, caps: dict[str, Any]) -> None:
    archive, restore = _toolbar_buttons(app, key, spec, tree)
    _set_button_enabled(archive, bool(caps["can_archive"]))
    _set_button_enabled(restore, bool(caps["can_restore"]))


def _capabilities_for_spec(M: Any, tree: Any, spec: dict[str, Any]) -> dict[str, Any]:
    return workspace_capabilities(
        M,
        tree,
        str(spec["table"]),
        str(spec["prefix"]),
        str(spec.get("state_column") or "archived"),
        int(spec.get("state_default", 0)),
        int(spec.get("archived_value", 1)),
    )


def _sync_toolbar(M: Any, app: Any, key: str) -> dict[str, Any]:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return _empty_capabilities()
    caps = _capabilities_for_spec(M, tree, spec)
    _apply_toolbar_caps(app, key, spec, tree, caps)
    return caps


def _menu_entry_map(menu: Any) -> dict[str, int]:
    cached = getattr(menu, "_turto_context_entry_map", None)
    if isinstance(cached, dict):
        return cached
    result: dict[str, int] = {}
    try:
        end = menu.index("end")
    except Exception:
        end = None
    if end is not None:
        for index in range(int(end) + 1):
            try:
                label = str(menu.entrycget(index, "label") or "").strip()
            except Exception:
                continue
            if label:
                result[label] = index
    try:
        menu._turto_context_entry_map = result
    except Exception:
        pass
    return result


def _set_menu_enabled(menu: Any, label: str, enabled: bool) -> None:
    index = _menu_entry_map(menu).get(label)
    if index is None:
        return
    try:
        menu.entryconfigure(index, state="normal" if enabled else "disabled")
    except Exception:
        pass


def sync_menu_state(M: Any, app: Any, key: str) -> dict[str, Any]:
    """Update an existing row menu immediately before it opens."""
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return _empty_capabilities()

    caps = _capabilities_for_spec(M, tree, spec)
    _apply_toolbar_caps(app, key, spec, tree, caps)
    menu = getattr(tree, str(spec.get("menu_attr") or ""), None)
    if menu is None:
        return caps

    for label in tuple(spec.get("single_labels") or ()):
        _set_menu_enabled(menu, label, bool(caps["single"]))
    # Project/task edit-state wrappers currently show an informational modal for
    # archived rows.  Disable those commands instead; destructive delete stays
    # available when the legacy owner allowed it.
    for label in tuple(spec.get("active_single_labels") or ()):
        _set_menu_enabled(
            menu,
            label,
            bool(caps["single"] and caps["can_archive"]),
        )
    _set_menu_enabled(menu, "Archivovat vybrané", bool(caps["can_archive"]))
    _set_menu_enabled(menu, "Obnovit vybrané", bool(caps["can_restore"]))
    return caps


def _install_menu_postcommand(M: Any, app: Any, key: str, tree: Any, spec: dict[str, Any]) -> None:
    menu = getattr(tree, str(spec.get("menu_attr") or ""), None)
    if menu is None or getattr(menu, "_turto_context_postcommand", False):
        return

    try:
        previous = str(menu.cget("postcommand") or "").strip()
    except Exception:
        previous = ""

    def postcommand() -> None:
        if previous:
            try:
                menu.tk.eval(previous)
            except Exception:
                pass
        sync_menu_state(M, app, key)

    try:
        menu.configure(postcommand=postcommand)
        menu._turto_context_postcommand = True
    except Exception:
        pass


def _open_selected(app: Any, key: str) -> str:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return "break"
    try:
        selected = list(tree.selection())
    except Exception:
        selected = []
    if len(selected) != 1:
        return "break"

    if key == "projects":
        callback = getattr(app, "edit_project", None)
        if callable(callback):
            callback()
        return "break"
    if key == "actions":
        callback = getattr(app, "edit_action", None)
        if callable(callback):
            callback(tree)
        return "break"
    if key == "tasks":
        callback = getattr(app, "edit_task", None)
        if callable(callback):
            callback()
        return "break"

    callback = getattr(app, "edit_request", None)
    if not callable(callback):
        return "break"
    if key == "mivo":
        runner = getattr(app, "_run_on_request_tree", None)
        if callable(runner):
            runner(tree, callback)
            return "break"
    callback()
    return "break"


def _clear_selection(tree: Any) -> str | None:
    try:
        selected = list(tree.selection())
    except Exception:
        selected = []
    if not selected:
        return None
    try:
        tree.selection_remove(*selected)
    except Exception:
        try:
            tree.selection_set(())
        except Exception:
            pass
    return "break"


def _install_keyboard(app: Any, key: str, tree: Any) -> None:
    if getattr(tree, "_turto_context_keyboard", False):
        return
    try:
        existing_return = str(tree.bind("<Return>") or "").strip()
    except Exception:
        existing_return = ""
    try:
        existing_escape = str(tree.bind("<Escape>") or "").strip()
    except Exception:
        existing_escape = ""

    try:
        if not existing_return:
            tree.bind("<Return>", lambda _event: _open_selected(app, key), add="+")
        if not existing_escape:
            tree.bind("<Escape>", lambda _event: _clear_selection(tree), add="+")
        tree._turto_context_keyboard = True
    except Exception:
        pass


def _schedule_workspace_sync(M: Any, app: Any, key: str) -> None:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return
    if getattr(tree, "_turto_context_sync_after", None) is not None:
        return

    def run() -> None:
        try:
            tree._turto_context_sync_after = None
        except Exception:
            pass
        _install_workspace(M, app, key)

    try:
        tree._turto_context_sync_after = app.after_idle(run)
    except Exception:
        try:
            tree._turto_context_sync_after = None
        except Exception:
            pass
        _install_workspace(M, app, key)


def _install_workspace(M: Any, app: Any, key: str) -> None:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return

    if not getattr(tree, "_turto_context_selection_sync", False):
        try:
            tree.bind(
                "<<TreeviewSelect>>",
                lambda _event, current=key: _schedule_workspace_sync(M, app, current),
                add="+",
            )
            tree.bind(
                "<Map>",
                lambda _event, current=key: _schedule_workspace_sync(M, app, current),
                add="+",
            )
            tree._turto_context_selection_sync = True
        except Exception:
            pass

    _install_menu_postcommand(M, app, key, tree, spec)
    _install_keyboard(app, key, tree)
    _sync_toolbar(M, app, key)


def _install_refresh_wrappers(M: Any) -> None:
    for key, spec in WORKSPACES.items():
        method_name = str(spec["refresh"])
        previous = getattr(M.App, method_name, None)
        if not callable(previous) or getattr(previous, "_turto_context_refresh", False):
            continue

        def make_wrapper(function: Any, workspace_key: str, public_name: str):
            def wrapped(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                _schedule_workspace_sync(M, self, workspace_key)
                return result

            wrapped._turto_context_refresh = True
            wrapped.__name__ = getattr(function, "__name__", public_name)
            wrapped.__doc__ = getattr(function, "__doc__", None)
            return wrapped

        setattr(M.App, method_name, make_wrapper(previous, key, method_name))


def _is_redundant_v750_rebuild(delay: Any, callback: Any) -> bool:
    """Identify only the known delayed v7.5 workspace safety rebuilds."""
    try:
        milliseconds = int(delay)
    except Exception:
        return False
    if milliseconds not in V750_REDUNDANT_REBUILD_DELAYS or not callable(callback):
        return False
    code = getattr(callback, "__code__", None)
    if code is None:
        return False
    filename = str(getattr(code, "co_filename", "")).replace("\\", "/").rsplit("/", 1)[-1]
    if filename != "v750_context_filters_offer_format.py":
        return False
    names = set(getattr(code, "co_freevars", ()) or ()) | set(getattr(code, "co_names", ()) or ())
    return "configure_workspaces" in names


def _call_previous_init_optimized(instance: Any, previous_init: Any, *args: Any, **kwargs: Any) -> Any:
    """Run the historical init while coalescing four duplicate v7.5 rebuilds."""
    try:
        original_after = instance.after
    except Exception:
        return previous_init(instance, *args, **kwargs)

    state = getattr(instance, "__dict__", {})
    had_instance_after = "after" in state
    previous_instance_after = state.get("after")
    suppressed: list[int] = []

    def after_proxy(delay: Any, callback: Any = None, *callback_args: Any):
        if _is_redundant_v750_rebuild(delay, callback):
            suppressed.append(int(delay))
            # The v7.5 caller intentionally discards these IDs.
            return f"turto-coalesced-v750-{len(suppressed)}"
        return original_after(delay, callback, *callback_args)

    try:
        instance.after = after_proxy
        return previous_init(instance, *args, **kwargs)
    finally:
        try:
            if had_instance_after:
                instance.after = previous_instance_after
            else:
                instance.__dict__.pop("after", None)
            instance._turto_v750_rebuilds_coalesced = tuple(suppressed)
        except Exception:
            pass


def apply(M: Any) -> None:
    if getattr(M, "_turto_v793_ui_cleanup", False):
        return
    M._turto_v793_ui_cleanup = True

    _install_refresh_wrappers(M)

    previous_init = M.App.__init__
    if not getattr(previous_init, "_turto_context_init", False):
        def app_init(self, *args, **kwargs):
            result = _call_previous_init_optimized(self, previous_init, *args, **kwargs)
            # v7.5 keeps its single 0-ms fallback.  Tk runs it before idle, so
            # one idle synchronization below sees the final menus and binds once.
            for key in WORKSPACES:
                _schedule_workspace_sync(M, self, key)
            return result

        app_init._turto_context_init = True
        M.App.__init__ = app_init

    M.V793_UI_CLEANUP = {
        "owner": POLICY_OWNER,
        "context_actions_follow_selection": True,
        "archive_restore_mutually_contextual": True,
        "single_record_actions_require_single_selection": True,
        "return_opens_selected_row": True,
        "escape_clears_table_selection": True,
        "double_click_policy": "existing row-only owner preserved",
    }
    M.V794_UI_OPTIMIZATION = {
        "owner": POLICY_OWNER,
        "workspaces": tuple(WORKSPACES),
        "toolbar_lookup": "stored-control first, cached fallback",
        "selection_sync": "after-idle coalesced",
        "menu_index_lookup": "cached per menu",
        "legacy_v750_delayed_rebuilds_suppressed": tuple(sorted(V750_REDUNDANT_REBUILD_DELAYS)),
        "legacy_v750_zero_ms_fallback_preserved": True,
    }
