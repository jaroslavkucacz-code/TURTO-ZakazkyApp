#!/usr/bin/env python3
"""Pure regression checks for TURTO CRM 8.0.3 deferred secondary pages."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeDeferredApp:
    def __init__(self):
        self.tabs = {
            "pricelists": object(),
            "issued_offers": object(),
            "settings": object(),
        }
        self.calls = []
        self.build()

    def build(self):
        self.build_price_lists()
        self.build_issued_offers()
        self.build_settings()
        return "full-build"

    def build_price_lists(self):
        self.calls.append("pricelists")
        self.price_current_tree = object()
        return "price-built"

    def build_issued_offers(self):
        self.calls.append("issued_offers")
        self.issued_offer_tree = object()
        return "issued-built"

    def build_settings(self):
        self.calls.append("settings")
        self.theme = object()
        return "settings-built"

    def show_page(self, key):
        return key

    def refresh_all(self):
        return "refresh"


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    module_path = base / "price_lists_domain" / "platform" / "deferred_page_build_803.py"
    bootstrap_path = base / "runtime_bootstrap.py"
    lazy_path = base / "price_lists_domain" / "platform" / "lazy_refresh.py"

    deferred = load_module(module_path, "turto_deferred_page_test")
    assert deferred.DEFERRED_PAGE_BUILD_METHODS == {
        "pricelists": "build_price_lists",
        "issued_offers": "build_issued_offers",
        "settings": "build_settings",
    }
    for forbidden in ("actions", "requests", "mivo", "offers", "tasks", "projects"):
        assert forbidden not in deferred.DEFERRED_PAGE_BUILD_METHODS

    original_show = FakeDeferredApp.show_page
    original_refresh = FakeDeferredApp.refresh_all
    fake_module = SimpleNamespace(App=FakeDeferredApp)
    deferred.apply(fake_module)
    assert FakeDeferredApp.show_page is original_show
    assert FakeDeferredApp.refresh_all is original_refresh

    # The initial composed build sees only placeholders for the selected pages.
    app = FakeDeferredApp()
    assert app.calls == []
    assert not hasattr(app, "price_current_tree")
    assert not hasattr(app, "issued_offer_tree")
    assert not hasattr(app, "theme")

    ensure = app._turto_ensure_deferred_page
    assert ensure("pricelists") is True
    assert app.calls == ["pricelists"]
    assert hasattr(app, "price_current_tree")
    assert ensure("pricelists") is False
    assert app.calls == ["pricelists"]

    assert ensure("issued_offers") is True
    assert app.calls == ["pricelists", "issued_offers"]
    assert hasattr(app, "issued_offer_tree")

    assert ensure("settings") is True
    assert app.calls == ["pricelists", "issued_offers", "settings"]
    assert hasattr(app, "theme")
    assert set(app._turto_deferred_built_pages) == {
        "pricelists", "issued_offers", "settings"
    }

    # A deliberate direct rebuild after startup keeps the original public method
    # semantics rather than becoming a permanent no-op.
    assert app.build_settings() == "settings-built"
    assert app.calls[-1] == "settings"

    # Unknown/non-deferred pages are untouched.
    assert ensure("actions") is False

    lazy = lazy_path.read_text(encoding="utf-8")
    assert 'App._turto_navigation_owner = "price_lists_domain.platform.lazy_refresh"' in lazy
    assert 'getattr(self, "_turto_ensure_deferred_page", None)' in lazy
    assert "page-build-error" in lazy

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    runtime_marker = '"price_lists_domain.platform.runtime_optimization_803"'
    deferred_marker = '"price_lists_domain.platform.deferred_page_build_803"'
    assert deferred_marker in bootstrap
    assert bootstrap.index(deferred_marker) > bootstrap.index(runtime_marker)

    print("TURTO CRM 8.0.3 deferred pages: OK")


if __name__ == "__main__":
    main()
