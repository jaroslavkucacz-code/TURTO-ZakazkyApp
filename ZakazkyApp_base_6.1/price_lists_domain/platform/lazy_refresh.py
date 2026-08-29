"""Single owner of responsive page navigation and deferred refreshes.

A page is raised immediately. Rapid clicks collapse into one refresh of the final
visible page; hidden pages stay dirty until the user opens them.
"""
from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

PAGE_REFRESH = {
    "dash": "refresh_dash",
    "actions": "refresh_actions",
    "requests": "refresh_requests",
    "mivo": "refresh_mivo_requests",
    "offers": "refresh_offers",
    "pricelists": "refresh_price_lists",
    "tasks": "refresh_tasks",
    "projects": "refresh_projects",
    "people": "refresh_people",
    "companies": "refresh_companies",
}
PAGE_TREES = {
    "dash": ("dash_tree", "dash_tasks_tree", "dash_requests_tree"),
    "actions": ("action_tree",),
    "requests": ("request_tree",),
    "mivo": ("mivo_tree",),
    "offers": ("offer_tree",),
    "pricelists": ("price_current_tree", "price_list_evidence_tree"),
    "tasks": ("task_tree",),
    "projects": ("project_tree",),
    "people": ("people_tree",),
    "companies": ("company_tree",),
}


def _exists(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return False


def _log(M, event: str, detail: str = "") -> None:
    try:
        root = Path(getattr(M, "DATA_ROOT", Path.home() / "Documents" / "TURTO Zakazky"))
        path = root / "logs" / "ui_navigation.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {event}"
        if detail:
            line += f": {detail}"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    except Exception:
        pass


def _state(app) -> None:
    if not hasattr(app, "_turto_dirty_pages"):
        app._turto_dirty_pages = set(PAGE_REFRESH)
    if not hasattr(app, "_turto_loaded_pages"):
        app._turto_loaded_pages = set()
    if not hasattr(app, "_turto_page_refresh_token"):
        app._turto_page_refresh_token = 0
    if not hasattr(app, "_turto_page_refresh_after"):
        app._turto_page_refresh_after = None
    if not hasattr(app, "_turto_chrome_refresh_after"):
        app._turto_chrome_refresh_after = None
    if not hasattr(app, "_turto_page_refresh_running"):
        app._turto_page_refresh_running = False
    if not hasattr(app, "_turto_closing"):
        app._turto_closing = False


def _cancel(app, attribute: str) -> None:
    event_id = getattr(app, attribute, None)
    if event_id is not None:
        try:
            app.after_cancel(event_id)
        except Exception:
            pass
    try:
        setattr(app, attribute, None)
    except Exception:
        pass


def _mark_dirty(app, pages=None) -> None:
    _state(app)
    app._turto_dirty_pages.update(pages or PAGE_REFRESH.keys())


def _reset_manual_sort(app, key: str) -> bool:
    changed = False
    for attribute in PAGE_TREES.get(key, ()):
        tree = getattr(app, attribute, None)
        if not _exists(tree):
            continue
        try:
            changed = changed or getattr(tree, "_active_sort", None) is not None
            tree._sort_state = {}
            tree._active_sort = None
        except Exception:
            pass
    return changed


def _raise_page(app, key: str) -> None:
    page = getattr(app, "tabs", {}).get(key)
    if not _exists(page):
        raise KeyError(f"Neznámá nebo zrušená záložka: {key}")
    try:
        page.grid(row=0, column=0, sticky="nsew")
    except Exception:
        pass
    page.tkraise()
    for name, button in list(getattr(app, "nav", {}).items()):
        if _exists(button):
            try:
                button.configure(style="TopNavActive.TButton" if name == key else "TopNav.TButton")
            except Exception:
                pass
    app._current_page = key


def _schedule_chrome(M, app, delay: int = 80) -> None:
    _state(app)
    _cancel(app, "_turto_chrome_refresh_after")

    def run():
        app._turto_chrome_refresh_after = None
        if getattr(app, "_turto_closing", False) or not _exists(app):
            return
        for name in ("refresh_header", "refresh_notifications", "refresh_notes_button", "refresh_user_button"):
            method = getattr(app, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    _log(M, f"chrome-error {name}", traceback.format_exc(limit=6))

    try:
        app._turto_chrome_refresh_after = app.after(delay, run)
    except Exception:
        pass


def _finish_visible(app, key: str) -> None:
    # Cancel post_baseline's old recursive walk of every hidden page.
    _cancel(app, "_turto_final_layout_after")
    for attribute in PAGE_TREES.get(key, ()):
        tree = getattr(app, attribute, None)
        if not _exists(tree):
            continue
        for hook_name in ("_sync_filter_bar", "_date_cell_redraw"):
            hook = getattr(tree, hook_name, None)
            if callable(hook):
                try:
                    hook()
                except Exception:
                    pass


def _schedule_page(M, app, key: str, delay: int = 35, force: bool = False) -> None:
    _state(app)
    if key not in PAGE_REFRESH:
        return
    if not force and key not in app._turto_dirty_pages and key in app._turto_loaded_pages:
        return
    app._turto_page_refresh_token += 1
    token = app._turto_page_refresh_token
    _cancel(app, "_turto_page_refresh_after")

    def run():
        app._turto_page_refresh_after = None
        if getattr(app, "_turto_closing", False) or not _exists(app):
            return
        if token != getattr(app, "_turto_page_refresh_token", 0):
            return
        if getattr(app, "_current_page", None) != key:
            app._turto_dirty_pages.add(key)
            return
        if app._turto_page_refresh_running:
            _schedule_page(M, app, key, 40, True)
            return

        method = getattr(app, PAGE_REFRESH[key], None)
        if not callable(method):
            app._turto_dirty_pages.discard(key)
            app._turto_loaded_pages.add(key)
            return

        app._turto_page_refresh_running = True
        try:
            if _exists(app):
                app.configure(cursor="watch")
        except Exception:
            pass
        started = datetime.now()
        success = False
        try:
            method()
            _finish_visible(app, key)
            success = True
        except Exception:
            _log(M, f"page-error {key}", traceback.format_exc(limit=12))
            try:
                M.messagebox.showerror(
                    "Načtení záložky",
                    f"Záložku „{key}“ se nepodařilo načíst. Podrobnosti jsou v logs\\ui_navigation.log.",
                    parent=app,
                )
            except Exception:
                pass
        finally:
            elapsed = (datetime.now() - started).total_seconds()
            app._turto_page_refresh_running = False
            try:
                if _exists(app):
                    app.configure(cursor="")
            except Exception:
                pass
            if elapsed >= 0.75:
                _log(M, f"slow-page {key}", f"{elapsed:.3f} s")

        if success and token == getattr(app, "_turto_page_refresh_token", 0):
            app._turto_dirty_pages.discard(key)
            app._turto_loaded_pages.add(key)
            sorter = getattr(M, "apply_default_table_sort", None)
            if callable(sorter):
                try:
                    app.after_idle(
                        lambda current=key: sorter(app, current)
                        if getattr(app, "_current_page", None) == current else None
                    )
                except Exception:
                    sorter(app, key)

    try:
        app._turto_page_refresh_after = app.after(delay, run)
    except Exception:
        pass


def _safe_chrome(M, App) -> None:
    if getattr(App, "_turto_safe_chrome_v6331", False):
        return
    for name in ("refresh_notifications", "refresh_header", "refresh_notes_button", "refresh_user_button"):
        original = getattr(App, name, None)
        if not callable(original):
            continue

        def make(function, method_name):
            def safe(self, *args, **kwargs):
                if getattr(self, "_turto_closing", False) or not _exists(self):
                    return None
                if method_name == "refresh_notifications":
                    button = getattr(self, "bell_button", None)
                    if button is not None and not _exists(button):
                        return None
                try:
                    return function(self, *args, **kwargs)
                except Exception:
                    _log(M, f"safe-chrome {method_name}", traceback.format_exc(limit=8))
                    return None
            return safe
        setattr(App, name, make(original, name))

    original_open = getattr(App, "open_notifications", None)
    if callable(original_open):
        def open_notifications(self, *args, **kwargs):
            if getattr(self, "_turto_closing", False) or not _exists(self):
                return None
            try:
                return original_open(self, *args, **kwargs)
            except Exception:
                _log(M, "notification-window", traceback.format_exc(limit=8))
                return None
        App.open_notifications = open_notifications

    original_close = getattr(App, "close_app", None)
    if callable(original_close):
        def close_app(self, *args, **kwargs):
            _state(self)
            self._turto_closing = True
            self._turto_page_refresh_token += 1
            _cancel(self, "_turto_page_refresh_after")
            _cancel(self, "_turto_chrome_refresh_after")
            return original_close(self, *args, **kwargs)
        App.close_app = close_app
    App._turto_safe_chrome_v6331 = True


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_lazy_refresh_v6331", False):
        return
    fallback_show_page = getattr(App, "show_page", None)
    _safe_chrome(M, App)

    def show_page(self, key, *args, **kwargs):
        _state(self)
        if getattr(self, "_turto_closing", False):
            return None
        if key not in getattr(self, "tabs", {}):
            return fallback_show_page(self, key, *args, **kwargs) if callable(fallback_show_page) else None
        previous = getattr(self, "_current_page", None)
        try:
            _raise_page(self, key)
        except Exception:
            _log(M, f"navigation-error {key}", traceback.format_exc(limit=8))
            return None
        if previous is not None and previous != key and _reset_manual_sort(self, key):
            self._turto_dirty_pages.add(key)
        if previous != key:
            self._turto_page_refresh_token += 1
            _cancel(self, "_turto_page_refresh_after")
        if key in PAGE_REFRESH:
            _schedule_page(M, self, key)
        return None

    def refresh_all(self, *args, **kwargs):
        _mark_dirty(self)
        _schedule_page(M, self, getattr(self, "_current_page", None) or "dash", 20, True)
        _schedule_chrome(M, self)

    def refresh_changed(self, pages):
        pages = set(pages or ())
        _mark_dirty(self, pages)
        current = getattr(self, "_current_page", None)
        if current in pages:
            _schedule_page(M, self, current, 20, True)
        _schedule_chrome(M, self)

    App.show_page = show_page
    App.refresh_all = refresh_all
    App._turto_mark_dirty = lambda self, pages=None: _mark_dirty(self, pages)
    App._turto_refresh_page = lambda self, key: _schedule_page(M, self, key, 0, True)
    App._turto_force_refresh_current = lambda self: (
        _mark_dirty(self, {self._current_page}), _schedule_page(M, self, self._current_page, 0, True)
    ) if getattr(self, "_current_page", None) in PAGE_REFRESH else None
    App.refresh_after_action_status = lambda self: refresh_changed(self, {"dash", "actions"})
    App.refresh_after_request_change = lambda self: refresh_changed(self, {"dash", "actions", "requests", "mivo"})
    App.refresh_after_task_change = lambda self: refresh_changed(self, {"dash", "tasks"})
    App._turto_navigation_owner = "price_lists_domain.platform.lazy_refresh"
    App._turto_lazy_refresh_v6331 = True


__all__ = ["install", "PAGE_REFRESH", "PAGE_TREES"]
