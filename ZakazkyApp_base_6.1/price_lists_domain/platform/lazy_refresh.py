"""Lazy page refresh so hidden tabs are not rebuilt after every edit."""
from __future__ import annotations


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


def _mark_dirty(app, pages=None):
    current = set(getattr(app, "_turto_dirty_pages", set()))
    current.update(pages or PAGE_REFRESH.keys())
    app._turto_dirty_pages = current


def _refresh_page(app, key: str):
    method_name = PAGE_REFRESH.get(key)
    if not method_name:
        return
    method = getattr(app, method_name, None)
    if callable(method):
        method()
    try:
        app._turto_dirty_pages.discard(key)
    except Exception:
        pass


def _refresh_chrome(app):
    for name in ("refresh_header", "refresh_notifications", "refresh_notes_button", "refresh_user_button"):
        method = getattr(app, name, None)
        if callable(method):
            try:method()
            except Exception:pass


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_lazy_refresh_v630", False):
        return
    old_show_page = App.show_page

    def refresh_all(self, *args, **kwargs):
        _mark_dirty(self)
        current = getattr(self, "_current_page", "dash") or "dash"
        _refresh_page(self, current)
        _refresh_chrome(self)

    def show_page(self, key, *args, **kwargs):
        previous = getattr(self, "_current_page", None)
        result = old_show_page(self, key, *args, **kwargs)
        dirty = key in getattr(self, "_turto_dirty_pages", set())
        # The original show_page already reloads a page when switching to it.
        # A same-page request, however, needs the deferred refresh explicitly.
        if dirty and previous == key:
            _refresh_page(self, key)
        else:
            try:self._turto_dirty_pages.discard(key)
            except Exception:pass
        return result

    def refresh_changed(self, pages):
        _mark_dirty(self, pages)
        current = getattr(self, "_current_page", "dash")
        if current in pages:
            _refresh_page(self, current)
        _refresh_chrome(self)

    def refresh_after_action_status(self):
        refresh_changed(self, {"dash", "actions"})

    def refresh_after_request_change(self):
        refresh_changed(self, {"dash", "actions", "requests", "mivo"})

    def refresh_after_task_change(self):
        refresh_changed(self, {"dash", "tasks"})

    App.refresh_all = refresh_all
    App.show_page = show_page
    App._turto_mark_dirty = lambda self, pages=None: _mark_dirty(self, pages)
    App._turto_refresh_page = lambda self, key: _refresh_page(self, key)
    App.refresh_after_action_status = refresh_after_action_status
    App.refresh_after_request_change = refresh_after_request_change
    App.refresh_after_task_change = refresh_after_task_change
    App._turto_lazy_refresh_v630 = True
