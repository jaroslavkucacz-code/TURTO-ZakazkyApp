#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 deferred commercial pages."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_deferred_commercial_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Widget:
    def __init__(self):
        self.alive = True

    def winfo_exists(self):
        return self.alive


class Var:
    def get(self):
        return "Tmavý"


class App:
    def __init__(self):
        self.tabs = {"dash": Widget(), "pricelists": Widget(), "issued_offers": Widget()}
        self.theme = Var()
        self.builder_calls = []
        self.show_calls = []
        self.theme_calls = []
        self.build()

    def build_price_lists(self):
        self.builder_calls.append("pricelists")
        self.price_current_tree = Widget()

    def build_issued_offers(self):
        self.builder_calls.append("issued_offers")
        self.issued_offer_tree = Widget()

    def build(self):
        # Mirrors the two app-integration wrappers: page/nav shells already exist,
        # while these calls create the expensive inner widget bodies.
        self.build_price_lists()
        self.build_issued_offers()
        self.base_build_completed = True

    def show_page(self, key, *args, **kwargs):
        self.show_calls.append(key)
        return key

    def apply_theme(self, theme=None, save=True):
        self.theme_calls.append((theme, save))


class IdleCleanup:
    calls = 0

    @staticmethod
    def _apply_text_fonts_once(M, app):
        IdleCleanup.calls += 1


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    path = root / "price_lists_domain" / "platform" / "deferred_commercial_pages_804.py"
    module = load_module(path)

    M = SimpleNamespace(App=App, messagebox=SimpleNamespace(showerror=lambda *a, **k: None))

    # The visual helper imports idle_cleanup_804 dynamically. Keep the real import
    # available in CI; the fake App.apply_theme call is sufficient to prove that
    # late-created widgets are re-themed.
    module.apply(M)
    app = App()

    assert app.base_build_completed is True
    assert app.builder_calls == []
    assert not hasattr(app, "price_current_tree")
    assert not hasattr(app, "issued_offer_tree")
    assert set(app._turto_deferred_pages_startup_skipped_804) == {"pricelists", "issued_offers"}
    assert app._turto_deferred_pages_built_804 == set()

    # Ordinary CRM navigation remains untouched and cannot trigger a commercial builder.
    assert app.show_page("dash") == "dash"
    assert app.builder_calls == []

    assert app.show_page("pricelists") == "pricelists"
    assert app.builder_calls == ["pricelists"]
    assert app.price_current_tree.winfo_exists()
    assert app._turto_deferred_pages_built_804 == {"pricelists"}
    assert app.theme_calls[-1] == ("Tmavý", False)

    # Reopening a built page is idempotent.
    app.show_page("pricelists")
    assert app.builder_calls == ["pricelists"]

    assert app.show_page("issued_offers") == "issued_offers"
    assert app.builder_calls == ["pricelists", "issued_offers"]
    assert app.issued_offer_tree.winfo_exists()
    assert app._turto_deferred_pages_built_804 == {"pricelists", "issued_offers"}
    assert app._turto_deferred_pages_build_count_804 == 2

    # Builders must be restored on the instance after the startup suppression.
    app.build_price_lists()
    app.build_issued_offers()
    assert app.builder_calls[-2:] == ["pricelists", "issued_offers"]

    bootstrap = (root / "runtime_bootstrap.py").read_text(encoding="utf-8")
    operational = '"price_lists_domain.platform.operational_refresh_804"'
    deferred = '"price_lists_domain.platform.deferred_commercial_pages_804"'
    assert operational in bootstrap and deferred in bootstrap
    assert bootstrap.index(deferred) > bootstrap.index(operational)

    print("TURTO CRM 8.0.4 deferred commercial pages: OK")


if __name__ == "__main__":
    main()
