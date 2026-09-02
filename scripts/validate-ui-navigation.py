#!/usr/bin/env python3
"""Headless regression test for responsive tab navigation and stale Tk widgets."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile


class FakeWidget:
    def __init__(self, exists=True):
        self.exists = exists
        self.raised = 0
        self.options = {}

    def winfo_exists(self):
        return 1 if self.exists else 0

    def grid(self, *args, **kwargs):
        self.options["grid"] = (args, kwargs)

    def tkraise(self):
        if not self.exists:
            raise RuntimeError("destroyed")
        self.raised += 1

    def configure(self, **kwargs):
        if not self.exists:
            raise RuntimeError("invalid command name")
        self.options.update(kwargs)


class FakeTree(FakeWidget):
    def __init__(self):
        super().__init__(True)
        self._active_sort = None
        self._sort_state = {}


class FakeMessagebox:
    errors = []

    @classmethod
    def showerror(cls, title, text, **kwargs):
        cls.errors.append((title, text))


class FakeApp:
    def __init__(self):
        self.tabs = {key: FakeWidget() for key in (
            "dash", "actions", "requests", "mivo", "offers", "pricelists",
            "tasks", "projects", "people", "companies", "settings", "help",
        )}
        self.nav = {key: FakeWidget() for key in self.tabs if key != "settings"}
        self.bell_button = FakeWidget(exists=False)
        self.action_tree = FakeTree()
        self.request_tree = FakeTree()
        self.mivo_tree = FakeTree()
        self.offer_tree = FakeTree()
        self.price_current_tree = FakeTree()
        self.price_list_evidence_tree = FakeTree()
        self.task_tree = FakeTree()
        self.project_tree = FakeTree()
        self.people_tree = FakeTree()
        self.company_tree = FakeTree()
        self.dash_tree = FakeTree()
        self.dash_tasks_tree = FakeTree()
        self.dash_requests_tree = FakeTree()
        self._events = {}
        self._next_event = 0
        self.refresh_counts = {}
        self.old_show_calls = 0
        self.legacy_layout_runs = 0
        self.notification_original_calls = 0
        self.closed = False
        self.exists = True
        self.cursor = ""

    def winfo_exists(self):
        return 1 if self.exists else 0

    def configure(self, **kwargs):
        self.cursor = kwargs.get("cursor", self.cursor)

    def after(self, _delay, callback):
        self._next_event += 1
        event_id = f"after-{self._next_event}"
        self._events[event_id] = callback
        return event_id

    def after_idle(self, callback):
        return self.after(0, callback)

    def after_cancel(self, event_id):
        self._events.pop(event_id, None)

    def run_all(self, limit=1000):
        count = 0
        while self._events:
            count += 1
            if count > limit:
                raise AssertionError("Callback loop did not settle")
            event_id = next(iter(self._events))
            callback = self._events.pop(event_id)
            callback()

    # Methods below represent the accumulated pre-6.3.31 owner chain.
    def show_page(self, key, *args, **kwargs):
        self.old_show_calls += 1

    def refresh_all(self, *args, **kwargs):
        raise AssertionError("legacy refresh_all must be replaced")

    def refresh_notifications(self, *args, **kwargs):
        self.notification_original_calls += 1
        self.bell_button.configure(text="bell")

    def refresh_header(self, *args, **kwargs):
        return None

    def refresh_notes_button(self, *args, **kwargs):
        return None

    def refresh_user_button(self, *args, **kwargs):
        return None

    def open_notifications(self, *args, **kwargs):
        self.refresh_notifications()

    def close_app(self, *args, **kwargs):
        self.closed = True
        self.exists = False


def _make_refresh(page_key):
    def refresh(self):
        self.refresh_counts[page_key] = self.refresh_counts.get(page_key, 0) + 1
        # Simulate post_baseline: an expensive recursive layout pass queued after
        # every refresh. The new navigation owner must cancel it.
        event_id = self.after_idle(
            lambda: setattr(self, "legacy_layout_runs", self.legacy_layout_runs + 1)
        )
        self._turto_final_layout_after = event_id
    return refresh


for _page, _method in {
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
}.items():
    setattr(FakeApp, _method, _make_refresh(_page))


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(root))
    from price_lists_domain.platform import lazy_refresh

    sort_source = (root / "v644_default_date_sort.py").read_text(encoding="utf-8")
    startup_bridge = "_turto_v762_startup_stability_bridge" in sort_source
    if startup_bridge:
        # 7.6.2 intentionally recognizes and unwraps the old closure names. The
        # dedicated startup regression verifies that this recognition removes,
        # rather than reintroduces, the obsolete whole-window callback chains.
        assert "_stabilize_legacy_owner" in sort_source
        assert "_wrap_v710" in sort_source
        assert "_wrap_v760" in sort_source
    else:
        assert "old_show" not in sort_source
        assert "old_init" not in sort_source
        assert '"refresh_all"' not in sort_source and "'refresh_all'" not in sort_source
    assert "M.apply_default_table_sort = apply_default" in sort_source

    class Module:
        App = FakeApp
        DATA_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="turto_ui_nav_"))
        messagebox = FakeMessagebox

    sort_calls = []
    Module.apply_default_table_sort = lambda app, key: sort_calls.append(key)

    try:
        lazy_refresh.install(Module)
        app = FakeApp()

        keys = list(lazy_refresh.PAGE_REFRESH)
        for index in range(100):
            app.show_page(keys[index % len(keys)])
        final_key = keys[(100 - 1) % len(keys)]

        assert app._turto_navigation_owner == "price_lists_domain.platform.lazy_refresh"
        assert app.old_show_calls == 0, "known pages must bypass the accumulated legacy show_page chain"
        assert len(app._events) == 1, f"rapid switching should leave one refresh, got {len(app._events)}"

        app.run_all()
        assert app.refresh_counts == {final_key: 1}, app.refresh_counts
        assert app.legacy_layout_runs == 0, "full-application legacy layout callback was not cancelled"
        assert sort_calls == [final_key], sort_calls
        assert app.cursor == ""

        # Reopening an already loaded clean page is immediate and query-free.
        app.show_page(final_key)
        assert not app._events
        assert app.refresh_counts[final_key] == 1

        # A dirty page refreshes once, not once per click.
        app._turto_mark_dirty({final_key})
        for _ in range(25):
            app.show_page(final_key)
        assert len(app._events) == 1
        app.run_all()
        assert app.refresh_counts[final_key] == 2
        assert app.legacy_layout_runs == 0

        # The real log showed refresh_notifications touching a destroyed bell.
        app.refresh_notifications()
        app.open_notifications()
        assert app.notification_original_calls == 0
        assert not FakeMessagebox.errors

        # Closing cancels every pending navigation/chrome callback.
        app._turto_mark_dirty({"dash"})
        app.show_page("dash")
        assert app._events
        app.close_app()
        app.run_all()
        assert app.closed
        assert not app._events

        print("TURTO CRM 6.3.31 navigation stress test: OK")
    finally:
        shutil.rmtree(Module.DATA_ROOT, ignore_errors=True)


if __name__ == "__main__":
    main()
