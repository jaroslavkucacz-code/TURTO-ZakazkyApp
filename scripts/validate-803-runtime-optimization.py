#!/usr/bin/env python3
"""Regression checks for the low-risk TURTO CRM 8.0.3 runtime optimization."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_runtime_optimization_test", path)
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


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    module_path = base / "price_lists_domain" / "platform" / "runtime_optimization_803.py"
    bootstrap_path = base / "runtime_bootstrap.py"
    lazy_path = base / "price_lists_domain" / "platform" / "lazy_refresh.py"

    assert module_path.is_file(), "8.0.3 runtime optimization owner is missing"
    optimization = load_module(module_path)

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

    # Applying the owner must preserve the canonical navigation/refresh methods.
    original_show_page = FakeApp.show_page
    original_refresh_all = FakeApp.refresh_all
    with tempfile.TemporaryDirectory(prefix="turto-803-") as td:
        fake_module = SimpleNamespace(
            App=FakeApp,
            DATA_ROOT=Path(td),
            APP_VERSION="8.0.2-dev",
        )
        optimization.apply(fake_module)
        assert FakeApp.show_page is original_show_page
        assert FakeApp.refresh_all is original_refresh_all
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
        for token in ("app_init=", "build_total=", "build_dash=", "apply_theme="):
            assert token in log, token

    # The pre-existing lazy refresh remains the one navigation/dirty-page owner.
    lazy = lazy_path.read_text(encoding="utf-8")
    assert 'App.show_page = show_page' in lazy
    assert 'App.refresh_all = refresh_all' in lazy
    assert 'App._turto_navigation_owner = "price_lists_domain.platform.lazy_refresh"' in lazy
    assert '_turto_dirty_pages' in lazy
    assert '_schedule_page' in lazy

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    marker = '"price_lists_domain.platform.runtime_optimization_803"'
    branding = '"price_lists_domain.platform.branding_polish_802"'
    assert marker in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(branding)

    print("TURTO CRM 8.0.3 runtime optimization: OK")


if __name__ == "__main__":
    main()
