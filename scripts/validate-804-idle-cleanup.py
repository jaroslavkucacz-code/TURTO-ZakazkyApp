#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 idle/runtime cleanup."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_idle_cleanup_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeWidget:
    def __init__(self, children=None):
        self._children = list(children or [])

    def winfo_children(self):
        return list(self._children)


class FakeText(FakeWidget):
    def __init__(self, children=None):
        super().__init__(children)
        self.configured = []

    def configure(self, **kwargs):
        self.configured.append(dict(kwargs))


class FakeToplevel(FakeWidget):
    def __init__(self, children=None):
        super().__init__(children)
        self.icons = []
        self.groups = []

    def iconbitmap(self, **kwargs):
        self.icons.append(dict(kwargs))

    def group(self, owner):
        self.groups.append(owner)


class FakeApp(FakeWidget):
    def __init__(self, children=None):
        super().__init__(children)
        self.bindings = []

    def bind_all(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))
        return "bind-1"


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    cleanup_path = root / "price_lists_domain" / "platform" / "idle_cleanup_804.py"
    bootstrap_path = root / "runtime_bootstrap.py"
    v608_path = root / "v608_stability.py"

    cleanup = load_module(cleanup_path)
    cleanup_source = cleanup_path.read_text(encoding="utf-8")
    bootstrap_source = bootstrap_path.read_text(encoding="utf-8")
    v608_source = v608_path.read_text(encoding="utf-8")

    # v608 must no longer recursively repaint every Treeview. Its quick-action
    # style owner remains, but the historical LIGHT/DARK status palette is gone.
    assert "def recolor(" not in v608_source
    assert "isinstance(w,ttk.Treeview)" not in v608_source
    assert "LIGHT={'status_active'" not in v608_source
    assert "DARK={'status_active'" not in v608_source
    assert "_quick_styles" in v608_source

    # The new policy itself must be event-driven. It may walk once at startup,
    # but it must not create its own recurring after() chain.
    assert ".after(" not in cleanup_source
    assert "bind_all(\"<Map>\"" in cleanup_source
    assert "recurring_widget_tree_polling\": False" in cleanup_source

    icon_pos = bootstrap_source.index('"price_lists_domain.platform.icon_assets_803"')
    idle_pos = bootstrap_source.index('"price_lists_domain.platform.idle_cleanup_804"')
    compat_pos = bootstrap_source.index('"price_lists_domain.platform.autocomplete_event_compat_803"')
    assert icon_pos < idle_pos < compat_pos

    fake_M = SimpleNamespace(
        tk=SimpleNamespace(Text=FakeText, Toplevel=FakeToplevel),
        ROOT=root,
    )

    # Calibri compatibility is one-shot and reaches nested Text widgets.
    text_a = FakeText()
    text_b = FakeText()
    app = FakeApp([FakeWidget([text_a]), text_b])
    changed = cleanup._apply_text_fonts_once(fake_M, app)
    assert changed == 2
    assert text_a.configured == [{"font": ("Calibri", 11)}]
    assert text_b.configured == [{"font": ("Calibri", 11)}]
    assert app._turto_calibri_widgets_checked_once == 2

    # Existing Toplevels are covered once and future windows use one Map binding.
    existing = FakeToplevel()
    app = FakeApp([FakeWidget([existing])])
    cleanup._install_event_driven_child_identity(fake_M, app)
    assert app._turto_child_identity_map_804 is True
    assert len(app.bindings) == 1
    assert app.bindings[0][0] == "<Map>"
    assert existing._turto_child_identity_804 is True
    assert existing.groups == [app]

    # Installing twice must not duplicate the global Map handler.
    cleanup._install_event_driven_child_identity(fake_M, app)
    assert len(app.bindings) == 1

    future = FakeToplevel()
    _sequence, mapped, _add = app.bindings[0]
    mapped(SimpleNamespace(widget=future))
    assert future._turto_child_identity_804 is True
    assert future.groups == [app]
    mapped(SimpleNamespace(widget=future))
    assert future.groups == [app]

    # apply() replaces crm_runtime globals that its historical App.__init__
    # resolves later, without creating another App wrapper or touching the DB.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import crm_runtime

    cleanup.apply(fake_M)
    assert getattr(fake_M, "_turto_idle_cleanup_804", False) is True
    assert fake_M.IDLE_CLEANUP_804["calibri_sweep"] == "startup-once"
    assert fake_M.IDLE_CLEANUP_804["child_window_identity"] == "map-event-driven"
    assert fake_M.IDLE_CLEANUP_804["legacy_tree_palette"] == "retired-v628-owner"
    assert fake_M.IDLE_CLEANUP_804["recurring_widget_tree_polling"] is False
    assert fake_M.IDLE_CLEANUP_804["database_rows_rewritten"] is False

    palette_probe = FakeApp()
    crm_runtime._apply_tree_palette(palette_probe)
    assert palette_probe._turto_legacy_palette_repaint_skips == 1

    print("TURTO CRM 8.0.4 idle cleanup: OK")


if __name__ == "__main__":
    main()
