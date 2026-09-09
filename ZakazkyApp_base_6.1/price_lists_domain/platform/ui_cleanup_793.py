"""TURTO CRM 7.9.3 – contextual action and keyboard cleanup.

Applied after the historical UI layers.  It does not create another workspace or
replace business logic; it only makes existing commands reflect the current
selection so impossible actions are disabled instead of producing modal
"select a row" messages.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.ui_cleanup_793"

WORKSPACES = {
    "actions": {
        "tree": "action_tree",
        "tab": "actions",
        "table": "actions",
        "prefix": "a",
        "refresh": "refresh_actions",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit poptávku",
            "Přidat připomínku",
            "Smazat / zrušit",
        ),
    },
    "requests": {
        "tree": "request_tree",
        "tab": "requests",
        "table": "requests",
        "prefix": "r",
        "refresh": "refresh_requests",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit e-mail",
            "Obdrženo dnes",
            "Bez odezvy",
            "Trvale smazat z evidence",
        ),
    },
    "mivo": {
        "tree": "mivo_tree",
        "tab": "mivo",
        "table": "requests",
        "prefix": "r",
        "refresh": "refresh_mivo_requests",
        "single_labels": (
            "Otevřít / upravit",
            "Vytvořit e-mail",
            "Obdrženo dnes",
            "Bez odezvy",
            "Trvale smazat z evidence",
        ),
    },
}

ARCHIVE_LABEL = "📦 Archivovat vybrané"
RESTORE_LABEL = "↩ Obnovit vybrané"


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


def workspace_capabilities(M: Any, tree: Any, table: str, prefix: str) -> dict[str, Any]:
    """Describe actions that are meaningful for the current Treeview selection."""
    ids = _selected_ids(tree, prefix)
    result = {
        "ids": ids,
        "single": False,
        "can_archive": False,
        "can_restore": False,
    }
    if not ids or table not in {"actions", "requests"}:
        return result

    marks = ",".join("?" for _ in ids)
    try:
        with M.db() as con:
            rows = con.execute(
                f'SELECT id, coalesce(archived,0) AS archived FROM "{table}" '
                f"WHERE id IN ({marks})",
                tuple(ids),
            ).fetchall()
        states = {int(row["id"]): bool(row["archived"]) for row in rows}
    except Exception:
        return result

    valid_ids = [value for value in ids if value in states]
    result["single"] = len(ids) == 1 and len(valid_ids) == 1
    result["can_archive"] = any(not states[value] for value in valid_ids)
    result["can_restore"] = any(states[value] for value in valid_ids)
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


def _menu_entry_index(menu: Any, label: str) -> int | None:
    try:
        end = menu.index("end")
    except Exception:
        return None
    if end is None:
        return None
    for index in range(int(end) + 1):
        try:
            if str(menu.entrycget(index, "label") or "").strip() == label:
                return index
        except Exception:
            continue
    return None


def _set_menu_enabled(menu: Any, label: str, enabled: bool) -> None:
    index = _menu_entry_index(menu, label)
    if index is None:
        return
    try:
        menu.entryconfigure(index, state="normal" if enabled else "disabled")
    except Exception:
        pass


def _workspace_parts(app: Any, key: str) -> tuple[dict[str, Any] | None, Any]:
    spec = WORKSPACES.get(key)
    if not spec:
        return None, None
    return spec, getattr(app, str(spec["tree"]), None)


def _sync_toolbar(M: Any, app: Any, key: str) -> dict[str, Any]:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return {"ids": [], "single": False, "can_archive": False, "can_restore": False}

    caps = workspace_capabilities(M, tree, str(spec["table"]), str(spec["prefix"]))
    try:
        tab = app.tabs[str(spec["tab"])]
    except Exception:
        tab = None
    archive = _find_button(tab, ARCHIVE_LABEL)
    restore = _find_button(tab, RESTORE_LABEL)
    _set_button_enabled(archive, bool(caps["can_archive"]))
    _set_button_enabled(restore, bool(caps["can_restore"]))
    return caps


def sync_menu_state(M: Any, app: Any, key: str) -> dict[str, Any]:
    """Update the already existing v7.5 row menu immediately before it opens."""
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return {"ids": [], "single": False, "can_archive": False, "can_restore": False}

    caps = _sync_toolbar(M, app, key)
    menu = getattr(tree, "_v750_row_menu", None)
    if menu is None:
        return caps

    for label in tuple(spec["single_labels"]):
        _set_menu_enabled(menu, label, bool(caps["single"]))
    _set_menu_enabled(menu, "Archivovat vybrané", bool(caps["can_archive"]))
    _set_menu_enabled(menu, "Obnovit vybrané", bool(caps["can_restore"]))
    return caps


def _install_menu_postcommand(M: Any, app: Any, key: str, tree: Any) -> None:
    menu = getattr(tree, "_v750_row_menu", None)
    if menu is None or getattr(menu, "_turto_v793_postcommand", False):
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
        menu._turto_v793_postcommand = True
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

    if key == "actions":
        callback = getattr(app, "edit_action", None)
        if callable(callback):
            callback(tree)
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
    if getattr(tree, "_turto_v793_keyboard", False):
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
        tree._turto_v793_keyboard = True
    except Exception:
        pass


def _install_workspace(M: Any, app: Any, key: str) -> None:
    spec, tree = _workspace_parts(app, key)
    if not spec or not _widget_exists(tree):
        return

    if not getattr(tree, "_turto_v793_selection_sync", False):
        try:
            tree.bind(
                "<<TreeviewSelect>>",
                lambda _event, current=key: _sync_toolbar(M, app, current),
                add="+",
            )
            tree.bind(
                "<Map>",
                lambda _event, current=key: _sync_toolbar(M, app, current),
                add="+",
            )
            tree._turto_v793_selection_sync = True
        except Exception:
            pass

    _install_menu_postcommand(M, app, key, tree)
    _install_keyboard(app, key, tree)
    _sync_toolbar(M, app, key)


def _schedule_workspace_sync(M: Any, app: Any, key: str) -> None:
    try:
        app.after_idle(lambda: _install_workspace(M, app, key))
    except Exception:
        _install_workspace(M, app, key)


def _install_refresh_wrappers(M: Any) -> None:
    for key, spec in WORKSPACES.items():
        method_name = str(spec["refresh"])
        previous = getattr(M.App, method_name, None)
        if not callable(previous) or getattr(previous, "_turto_v793_refresh", False):
            continue

        def make_wrapper(function: Any, workspace_key: str):
            def wrapped(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                _schedule_workspace_sync(M, self, workspace_key)
                return result

            wrapped._turto_v793_refresh = True
            wrapped.__name__ = getattr(function, "__name__", method_name)
            return wrapped

        setattr(M.App, method_name, make_wrapper(previous, key))


def apply(M: Any) -> None:
    if getattr(M, "_turto_v793_ui_cleanup", False):
        return
    M._turto_v793_ui_cleanup = True

    _install_refresh_wrappers(M)

    previous_init = M.App.__init__
    if not getattr(previous_init, "_turto_v793_init", False):
        def app_init(self, *args, **kwargs):
            result = previous_init(self, *args, **kwargs)
            for key in WORKSPACES:
                _install_workspace(M, self, key)
                _schedule_workspace_sync(M, self, key)
            return result

        app_init._turto_v793_init = True
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
