#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 idle/runtime cleanup."""
from __future__ import annotations

import gc
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import weakref


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_idle_cleanup_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeWidget:
    def __init__(self, children=None):
        self._children = list(children or [])
        self._exists = True

    def winfo_children(self):
        return list(self._children)

    def winfo_exists(self):
        return bool(self._exists)


class FakeText(FakeWidget):
    def __init__(self, children=None):
        super().__init__(children)
        self.configured = []

    def configure(self, **kwargs):
        self.configured.append(dict(kwargs))


class FakeApp(FakeWidget):
    def __init__(self, children=None):
        super().__init__(children)
        self.grabbed = None

    def grab_current(self):
        return self.grabbed


class FakeToplevel(FakeWidget):
    def __init__(self, root=None, children=None):
        super().__init__(children)
        self._root_owner = root
        self.icons = []
        self.groups = []
        self.bindings = []
        self._state = "normal"
        self.lifts = 0
        self.focuses = 0

    def _root(self):
        return self._root_owner

    def iconbitmap(self, **kwargs):
        self.icons.append(dict(kwargs))

    def group(self, owner):
        self.groups.append(owner)

    def bind(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))
        return f"bind-{len(self.bindings)}"

    def state(self):
        return self._state

    def lift(self):
        self.lifts += 1

    def focus_force(self):
        self.focuses += 1


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    cleanup_path = root / "price_lists_domain" / "platform" / "idle_cleanup_804.py"
    bootstrap_path = root / "runtime_bootstrap.py"
    v608_path = root / "v608_stability.py"
    v623_path = root / "v623_exports.py"

    cleanup = load_module(cleanup_path)
    cleanup_source = cleanup_path.read_text(encoding="utf-8")
    bootstrap_source = bootstrap_path.read_text(encoding="utf-8")
    v608_source = v608_path.read_text(encoding="utf-8")
    v623_source = v623_path.read_text(encoding="utf-8")

    # v608 must no longer recursively repaint every Treeview. Its quick-action
    # style owner remains, but the historical LIGHT/DARK status palette is gone.
    assert "def recolor(" not in v608_source
    assert "isinstance(w,ttk.Treeview)" not in v608_source
    assert "LIGHT={'status_active'" not in v608_source
    assert "DARK={'status_active'" not in v608_source
    assert "_quick_styles" in v608_source

    # The monitor-under-cursor policy must not flush the complete pending Tk
    # idle queue during its delayed startup callback. Native SetWindowPos keeps
    # the original multi-monitor behavior without that expensive re-entrancy.
    maximize_start = v623_source.index("    def maximize_current_monitor(app):")
    maximize_end = v623_source.index("    # ------------------------------------------------------------------\n    # 4) Excel export helpers.", maximize_start)
    maximize_source = v623_source[maximize_start:maximize_end]
    assert "app.update_idletasks()" not in maximize_source
    assert "SetWindowPos" in maximize_source
    assert "MonitorFromPoint" in maximize_source
    assert "app.state('zoomed')" in maximize_source

    # The cleanup policy must not create another recurring after() chain or a
    # global Map hook. New child windows are handled by wrapping Toplevel once.
    assert ".after(" not in cleanup_source
    assert "bind_all(" not in cleanup_source
    assert "Toplevel.__init__ = init" in cleanup_source
    assert "weakref.ref(win)" in cleanup_source
    assert "weak-toplevel-registry-coalesced" in cleanup_source
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

    # One compatibility scan covers a child created before the Toplevel wrapper
    # is installed. Every future child registers itself and owns one local Map
    # callback, rather than installing a bind_all callback on the application.
    app = FakeApp()
    existing = FakeToplevel(root=app)
    app._children.append(existing)
    cleanup._install_event_driven_child_identity(fake_M, app)
    assert app._turto_child_identity_map_804 is True
    assert existing._turto_child_identity_804 is True
    assert existing.groups == [app]
    assert len(cleanup._live_toplevels(app)) == 1

    future = FakeToplevel(root=app)
    assert future._turto_child_identity_804 is True
    assert future.groups == [app]
    assert len(future.bindings) == 1
    assert future.bindings[0][0] == "<Map>"
    assert cleanup._live_toplevels(app)[-1] is future

    _sequence, mapped, _add = future.bindings[0]
    mapped(SimpleNamespace(widget=future))
    assert future.groups == [app]  # identity is idempotent
    assert cleanup._live_toplevels(app)[-1] is future

    # The registry must not keep a destroyed/forgotten dialog alive.
    transient = FakeToplevel(root=app)
    transient_ref = weakref.ref(transient)
    assert transient_ref() is transient
    del transient
    gc.collect()
    assert transient_ref() is None
    cleanup._live_toplevels(app)
    assert all(item is not None for item in cleanup._live_toplevels(app))

    # Focus protection now inspects only registered Toplevels. Most recently
    # mapped visible dialog wins, matching the old z-order safeguard semantics.
    cleanup._raise_registered_dialog(app)
    assert future.lifts == 1 and future.focuses == 1
    future._state = "withdrawn"
    cleanup._raise_registered_dialog(app)
    assert existing.lifts == 1 and existing.focuses == 1

    # apply() replaces crm_runtime globals that its historical App.__init__
    # resolves later, without touching the DB. It keeps 8.0.3's coalescing but
    # swaps its recursive scan for the weak Toplevel registry.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import crm_runtime

    cleanup.apply(fake_M)
    assert getattr(fake_M, "_turto_idle_cleanup_804", False) is True
    assert fake_M.IDLE_CLEANUP_804["calibri_sweep"] == "startup-once"
    assert fake_M.IDLE_CLEANUP_804["child_window_identity"] == "per-toplevel-map-event"
    assert fake_M.IDLE_CLEANUP_804["dialog_focus"] == "weak-toplevel-registry-coalesced"
    assert fake_M.IDLE_CLEANUP_804["legacy_tree_palette"] == "retired-v628-owner"
    assert fake_M.IDLE_CLEANUP_804["recurring_widget_tree_polling"] is False
    assert fake_M.IDLE_CLEANUP_804["database_rows_rewritten"] is False
    assert getattr(crm_runtime._raise_dialog_chain, "_turto_803_dialog_chain", False) is True
    assert getattr(crm_runtime._raise_dialog_chain, "_turto_804_dialog_registry", False) is True

    palette_probe = FakeApp()
    crm_runtime._apply_tree_palette(palette_probe)
    assert palette_probe._turto_legacy_palette_repaint_skips == 1

    print("TURTO CRM 8.0.4 idle cleanup: OK")


if __name__ == "__main__":
    main()
