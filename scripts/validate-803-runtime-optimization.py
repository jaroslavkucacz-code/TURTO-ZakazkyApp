#!/usr/bin/env python3
"""Regression checks for the low-risk TURTO CRM 8.0.3/8.0.4 runtime optimization."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeWidget:
    def __init__(self, manager: str = ""):
        self.manager = manager

    def winfo_exists(self):
        return 1

    def winfo_manager(self):
        return self.manager


class FakePage:
    def __init__(self):
        self.removed = 0

    def winfo_exists(self):
        return 1

    def grid_remove(self):
        self.removed += 1


class FakeApp:
    def __init__(self):
        self.header_calls = 0
        self.date_label = FakeWidget("")
        self.today_summary = FakeWidget("")
        self.build()
        self.apply_theme()

    def build(self):
        self.build_dash()
        return "build-result"

    def build_dash(self):
        return "dash-result"

    def apply_theme(self):
        return "theme-result"

    def refresh_header(self):
        self.header_calls += 1
        return "header-result"

    def show_page(self, key):
        return key

    def refresh_all(self):
        return "refresh-all"


class FakeAutocompleteEntry:
    registry = None

    def __init__(self):
        self.destroy_callback = None
        self.registry.append(self)

    def bind(self, sequence, callback, add=None):
        assert sequence == "<Destroy>"
        assert add == "+"
        self.destroy_callback = callback


class FakeChromeApp:
    def __init__(self):
        self.callbacks = {}
        self.cancelled = []
        self.next_id = 0
        self.calls = []

    def winfo_exists(self):
        return 1

    def after(self, delay, callback):
        self.next_id += 1
        token = f"after-{self.next_id}"
        self.callbacks[token] = (delay, callback)
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)
        self.callbacks.pop(token, None)

    def refresh_header(self):
        self.calls.append("refresh_header")

    def refresh_notifications(self):
        self.calls.append("refresh_notifications")

    def refresh_notes_button(self):
        self.calls.append("refresh_notes_button")

    def refresh_user_button(self):
        self.calls.append("refresh_user_button")

    def run_pending(self):
        assert self.callbacks
        _token, (_delay, callback) = list(self.callbacks.items())[-1]
        self.callbacks.clear()
        callback()


class FakeGrab:
    def __init__(self):
        self.lifts = 0
        self.focuses = 0

    def winfo_exists(self):
        return 1

    def lift(self):
        self.lifts += 1

    def focus_force(self):
        self.focuses += 1


class FakeDialogApp:
    def __init__(self, grabbed=None):
        self.grabbed = grabbed
        self.pending = []

    def grab_current(self):
        return self.grabbed

    def after_idle(self, callback):
        token = f"dialog-idle-{len(self.pending) + 1}"
        self.pending.append((token, callback))
        return token

    def run_idle(self):
        assert self.pending
        _token, callback = self.pending.pop(0)
        callback()


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    module_path = base / "price_lists_domain" / "platform" / "runtime_optimization_803.py"
    bootstrap_path = base / "runtime_bootstrap.py"
    lazy_path = base / "price_lists_domain" / "platform" / "lazy_refresh.py"
    v628_path = base / "v628_modernui_resize.py"

    assert module_path.is_file(), "8.0.3 runtime optimization owner is missing"
    optimization = load_module(module_path, "turto_runtime_optimization_test")
    lazy_module = load_module(lazy_path, "turto_lazy_refresh_test")

    # Header optimization is dynamic: today's hidden widgets skip the historical
    # DB summary, while any future mapped header widget automatically restores it.
    hidden = SimpleNamespace(date_label=FakeWidget(""), today_summary=FakeWidget(""))
    visible = SimpleNamespace(date_label=FakeWidget("grid"), today_summary=FakeWidget(""))
    legacy = SimpleNamespace()
    assert optimization._header_refresh_needed(hidden) is False
    assert optimization._header_refresh_needed(visible) is True
    assert optimization._header_refresh_needed(legacy) is True

    source = module_path.read_text(encoding="utf-8")
    for forbidden in ("ALTER TABLE", "INSERT INTO", "UPDATE ", "DELETE FROM"):
        assert forbidden not in source, f"runtime optimization must not mutate business DB: {forbidden}"
    assert "App.show_page =" not in source
    assert "App.refresh_all =" not in source
    assert "performance.log" in source
    assert "time.perf_counter()" in source
    assert 'self.bind("<Destroy>", unregister, add="+")' in source
    assert "dialog_raise_coalesced=" in source
    assert "hidden_pages_detached=" in source

    # 8.0.4 moved palette ownership back to the actual theme layer. The runtime
    # optimizer must no longer proxy self.after_idle on every data refresh just
    # to suppress a callback that v628 no longer creates.
    for obsolete in (
        "_is_redundant_v628_refresh_palette",
        "_suppress_v628_refresh_palette",
        "_turto_803_palette_suppressed",
        "after_idle_proxy",
        "refresh_palette_skips=",
    ):
        assert obsolete not in source, obsolete

    v628 = v628_path.read_text(encoding="utf-8")
    assert "#CFE7FA" in v628 and "#173A55" in v628
    assert "apply_theme_modern" in v628
    for method_name in (
        "refresh_dash", "refresh_actions", "refresh_requests",
        "refresh_mivo_requests", "refresh_offers", "refresh_tasks",
        "refresh_projects", "refresh_people", "refresh_companies", "refresh_all",
    ):
        assert f"M.App.{method_name} =" not in v628, method_name

    # All pages still exist; only geometry for non-current pages is removed.
    pages = {key: FakePage() for key in ("dash", "actions", "requests", "settings")}
    page_app = SimpleNamespace(tabs=pages, _current_page="dash")
    detached = optimization._detach_hidden_pages_now(page_app)
    assert detached == ("actions", "requests", "settings")
    assert pages["dash"].removed == 0
    assert pages["actions"].removed == 1
    assert pages["requests"].removed == 1
    assert pages["settings"].removed == 1
    assert page_app._turto_hidden_pages_detached_immediately == detached
    assert optimization._detach_hidden_pages_now(
        SimpleNamespace(tabs=pages, _current_page="")
    ) == ()

    # SQLite repeatedly compares the same string values while sorting. The cache
    # must preserve the exact historical result and only avoid repeated work.
    sort_calls = []

    def historical_sort_key(value):
        sort_calls.append(value)
        return tuple(str(value or "").strip().casefold())

    sort_module = SimpleNamespace(czech_sort_key=historical_sort_key)
    assert optimization._install_czech_sort_cache(sort_module) is True
    samples = ["Česká firma", "CH Projekt 10", "ŽPSV", "  Leviat  "]
    for sample in samples:
        expected = tuple(sample.strip().casefold())
        assert sort_module.czech_sort_key(sample) == expected
        assert sort_module.czech_sort_key(sample) == expected
    assert len(sort_calls) == len(samples)
    info = sort_module.czech_sort_key.cache_info()
    assert info.hits == len(samples)
    assert info.misses == len(samples)
    assert info.currsize == len(samples)
    before = len(sort_calls)
    assert sort_module.czech_sort_key(None) == historical_sort_key(None)
    assert len(sort_calls) == before + 2

    # Hundreds of descendant Map/FocusIn events collapse into one idle sweep.
    sweeps = []

    def historical_dialog_sweep(app, event=None):
        sweeps.append((app, event))

    dialog_app = FakeDialogApp()
    coalesced = optimization._make_dialog_chain_coalescer(historical_dialog_sweep)
    tokens = [coalesced(dialog_app) for _ in range(500)]
    assert len(dialog_app.pending) == 1
    assert len(sweeps) == 0
    assert len(set(tokens)) == 1
    assert dialog_app._turto_dialog_raise_events_coalesced == 499
    dialog_app.run_idle()
    assert len(sweeps) == 1
    assert dialog_app._turto_dialog_raise_after is None
    coalesced(dialog_app)
    assert len(dialog_app.pending) == 1
    dialog_app.run_idle()
    assert len(sweeps) == 2

    # Modal grabs keep immediate focus protection and bypass the recursive sweep.
    grabbed = FakeGrab()
    modal_app = FakeDialogApp(grabbed=grabbed)
    assert coalesced(modal_app) is None
    assert grabbed.lifts == 1 and grabbed.focuses == 1
    assert modal_app.pending == []
    assert len(sweeps) == 2

    # Destroyed autocomplete widgets leave the legacy process-wide registry.
    registry = []
    FakeAutocompleteEntry.registry = registry
    autocomplete_module = SimpleNamespace(
        AutocompleteEntry=FakeAutocompleteEntry,
        _AUTOCOMPLETE_ENTRIES=registry,
    )
    assert optimization._install_autocomplete_cleanup(autocomplete_module) is True
    entry = FakeAutocompleteEntry()
    assert registry == [entry]
    assert callable(entry.destroy_callback)
    entry.destroy_callback(SimpleNamespace(widget=entry))
    assert registry == []

    # Business changes update only chrome that can actually become stale.
    chrome_app = FakeChromeApp()
    lazy_module._schedule_chrome(
        SimpleNamespace(), chrome_app, methods=lazy_module.BUSINESS_CHROME_REFRESH,
    )
    chrome_app.run_pending()
    assert chrome_app.calls == ["refresh_header", "refresh_notifications"]

    chrome_app = FakeChromeApp()
    lazy_module._schedule_chrome(
        SimpleNamespace(), chrome_app, methods=lazy_module.BUSINESS_CHROME_REFRESH,
    )
    lazy_module._schedule_chrome(SimpleNamespace(), chrome_app)
    assert chrome_app.cancelled == ["after-1"]
    chrome_app.run_pending()
    assert chrome_app.calls == list(lazy_module.CHROME_REFRESH)

    # Applying the 8.0.3 owner preserves canonical navigation/refresh methods.
    original_show_page = FakeApp.show_page
    original_refresh_all = FakeApp.refresh_all
    with tempfile.TemporaryDirectory(prefix="turto-803-") as td:
        fake_module = SimpleNamespace(
            App=FakeApp,
            DATA_ROOT=Path(td),
            APP_VERSION="8.0.4-dev",
            czech_sort_key=lambda value: tuple(str(value or "").casefold()),
        )
        optimization.apply(fake_module)
        assert FakeApp.show_page is original_show_page
        assert FakeApp.refresh_all is original_refresh_all
        assert callable(getattr(fake_module.czech_sort_key, "cache_info", None))
        app = FakeApp()
        assert app.refresh_header() is None
        assert app.header_calls == 0
        assert app._turto_hidden_header_refresh_skips == 1
        app.date_label.manager = "grid"
        assert app.refresh_header() == "header-result"
        assert app.header_calls == 1
        log_path = Path(td) / "logs" / "performance.log"
        assert log_path.is_file()
        log = log_path.read_text(encoding="utf-8")
        for token in (
            "app_init=", "build_total=", "build_dash=", "apply_theme=",
            "czech_cache_hits=", "czech_cache_misses=", "czech_cache_size=",
            "dialog_raise_coalesced=", "hidden_pages_detached=",
        ):
            assert token in log, token
        assert "refresh_palette_skips=" not in log

    # The pre-existing lazy refresh remains the navigation/dirty-page owner.
    lazy = lazy_path.read_text(encoding="utf-8")
    assert 'App.show_page = show_page' in lazy
    assert 'App.refresh_all = refresh_all' in lazy
    assert 'App._turto_navigation_owner = "price_lists_domain.platform.lazy_refresh"' in lazy
    assert '_turto_dirty_pages' in lazy
    assert '_schedule_page' in lazy
    assert 'methods=BUSINESS_CHROME_REFRESH' in lazy
    assert 'refresh_notes_button' not in lazy_module.BUSINESS_CHROME_REFRESH
    assert 'refresh_user_button' not in lazy_module.BUSINESS_CHROME_REFRESH

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    marker = '"price_lists_domain.platform.runtime_optimization_803"'
    branding = '"price_lists_domain.platform.branding_polish_802"'
    assert marker in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(branding)

    print("TURTO CRM 8.0.3/8.0.4 runtime optimization: OK")


if __name__ == "__main__":
    main()
