#!/usr/bin/env python3
"""Regression checks for the low-risk TURTO CRM 8.0.3 runtime optimization."""
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


def make_v628_palette_callback():
    namespace = {}
    exec(
        compile(
            "def outer():\n"
            "    def apply_modern_palette(app):\n"
            "        return app\n"
            "    app = object()\n"
            "    return lambda: apply_modern_palette(app)\n",
            "v628_modernui_resize.py",
            "exec",
        ),
        namespace,
    )
    return namespace["outer"]()


class FakeIdleApp:
    def __init__(self):
        self.idle_callbacks = []

    def after_idle(self, callback, *args):
        self.idle_callbacks.append((callback, args))
        return f"idle-{len(self.idle_callbacks)}"


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    module_path = base / "price_lists_domain" / "platform" / "runtime_optimization_803.py"
    bootstrap_path = base / "runtime_bootstrap.py"
    lazy_path = base / "price_lists_domain" / "platform" / "lazy_refresh.py"

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
    assert "refresh_palette_skips=" in source

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
    # Non-string inputs bypass the cache so historical generic-call semantics stay exact.
    before = len(sort_calls)
    assert sort_module.czech_sort_key(None) == historical_sort_key(None)
    assert len(sort_calls) == before + 2

    # v628's old refresh wrapper repaints the entire application on every table
    # refresh. Match only that exact callback and preserve all unrelated idle work.
    palette_callback = make_v628_palette_callback()
    ordinary_callback = lambda: "functional-idle-work"
    assert optimization._is_redundant_v628_refresh_palette(palette_callback) is True
    assert optimization._is_redundant_v628_refresh_palette(ordinary_callback) is False

    idle_app = FakeIdleApp()

    def historical_refresh(self):
        self.after_idle(palette_callback)
        self.after_idle(ordinary_callback)
        return "refresh-result"

    optimized_refresh = optimization._suppress_v628_refresh_palette(historical_refresh)
    assert optimized_refresh(idle_app) == "refresh-result"
    assert len(idle_app.idle_callbacks) == 1
    assert idle_app.idle_callbacks[0][0] is ordinary_callback
    assert idle_app._turto_v628_refresh_palette_skips == 1
    # The temporary method proxy must be fully restored after each call.
    assert "after_idle" not in idle_app.__dict__

    # Destroyed autocomplete widgets must leave the legacy process-wide registry
    # immediately instead of waiting for a future unrelated mouse click.
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
        SimpleNamespace(),
        chrome_app,
        methods=lazy_module.BUSINESS_CHROME_REFRESH,
    )
    chrome_app.run_pending()
    assert chrome_app.calls == ["refresh_header", "refresh_notifications"]

    # Multiple pending requests are coalesced by union. A later full refresh must
    # never be downgraded by an earlier selective request.
    chrome_app = FakeChromeApp()
    lazy_module._schedule_chrome(
        SimpleNamespace(),
        chrome_app,
        methods=lazy_module.BUSINESS_CHROME_REFRESH,
    )
    lazy_module._schedule_chrome(SimpleNamespace(), chrome_app)
    assert chrome_app.cancelled == ["after-1"]
    chrome_app.run_pending()
    assert chrome_app.calls == list(lazy_module.CHROME_REFRESH)

    # Applying the 8.0.3 owner must preserve canonical navigation/refresh methods.
    original_show_page = FakeApp.show_page
    original_refresh_all = FakeApp.refresh_all
    with tempfile.TemporaryDirectory(prefix="turto-803-") as td:
        fake_module = SimpleNamespace(
            App=FakeApp,
            DATA_ROOT=Path(td),
            APP_VERSION="8.0.2-dev",
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
            "refresh_palette_skips=",
        ):
            assert token in log, token

    # The pre-existing lazy refresh remains the one navigation/dirty-page owner.
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

    print("TURTO CRM 8.0.3 runtime optimization: OK")


if __name__ == "__main__":
    main()
