#!/usr/bin/env python3
"""Regression guard for TURTO CRM 7.6.2 Windows/Tk startup stability."""
from __future__ import annotations

import importlib
import pathlib
import sys
import types
from types import SimpleNamespace


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(source))
    layer = importlib.import_module("v644_default_date_sort")

    bootstrap = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert bootstrap.index("v644_default_date_sort.apply(app)") < bootstrap.index("v710_cleanup.apply(app)")
    assert bootstrap.index("v644_default_date_sort.apply(app)") < bootstrap.index("v760_table_activity_performance.apply(app)")

    class Widget:
        def __init__(self, *_a, **_k):
            self.exists = True
            self.callbacks = []
            self.settings = {}
        def winfo_exists(self): return int(self.exists)
        def after(self, delay, callback):
            self.callbacks.append((int(delay), callback)); return len(self.callbacks)
        def after_idle(self, callback): return self.after(0, callback)
        def after_cancel(self, _handle): return None
        def configure(self, **kwargs): self.settings.update(kwargs)
        config = configure
        def update_idletasks(self): return None

    class NativeTreeview(Widget):
        def heading(self, *_a, **_k): return "native-heading"
        def column(self, *_a, **_k): return "w"
        def xview(self, *_a, **_k): return (0.0, 1.0)

    class NativeToplevel(Widget):
        pass

    native_heading = NativeTreeview.heading
    native_column = NativeTreeview.column
    native_configure = NativeTreeview.configure
    native_toplevel_init = NativeToplevel.__init__

    class App(Widget):
        def __init__(self):
            super().__init__()
            for name in ("request_tree", "mivo_tree", "project_tree", "task_tree", "offer_tree"):
                setattr(self, name, NativeTreeview())
            self.build()
        def build(self): self.build_count = getattr(self, "build_count", 0) + 1
        def apply_theme(self): self.theme_count = getattr(self, "theme_count", 0) + 1
        def on_user_changed(self): self.user_change_count = getattr(self, "user_change_count", 0) + 1

    method_names = set(layer._V710_REFRESH_METHODS) | {"refresh_dashboard", "refresh_mivo"}
    for method_name in method_names:
        setattr(App, method_name, lambda self, *a, **k: None)

    M = SimpleNamespace(
        App=App,
        ttk=SimpleNamespace(Treeview=NativeTreeview),
        tk=SimpleNamespace(Toplevel=NativeToplevel),
        layout_calls=[], polish_calls=[], recursive_scan_count=0,
        cleanup_count=0, faulthandler_count=0,
        exception_guard_count=0, drop_target_count=0,
    )

    # Simulate root post_baseline and v631, which are already applied when v644 runs.
    def normalize(_app): M.recursive_scan_count += 1
    def reclaim_tree_layout(_app): M.recursive_scan_count += 1
    def cleanup_legacy_offer_staging(_app): M.cleanup_count += 1

    def make_legacy_init(old_init):
        def legacy_init(self, *args, **kwargs):
            result = old_init(self, *args, **kwargs)
            self.update_idletasks(); normalize(self)
            self.after(1200, lambda: reclaim_tree_layout(self))
            self.after(1800, lambda: cleanup_legacy_offer_staging(self))
            return result
        return legacy_init
    M.App.__init__ = make_legacy_init(M.App.__init__)

    def _enable_faulthandler(_app): M.faulthandler_count += 1
    def _install_tk_exception_guard(_app): M.exception_guard_count += 1
    def _install_unified_target(_app): M.drop_target_count += 1

    def make_diskdrop_init(old_init):
        def diskdrop_init(self, *args, **kwargs):
            result = old_init(self, *args, **kwargs)
            self.after(1700, lambda: _enable_faulthandler(self))
            self.after(1800, lambda: _install_tk_exception_guard(self))
            self.after(3000, lambda: _install_unified_target(self))
            return result
        return diskdrop_init
    M.App.__init__ = make_diskdrop_init(M.App.__init__)

    def schedule_final_layout(app): app.after(0, lambda: normalize(app))
    M.schedule_final_tree_layout = schedule_final_layout

    for name in method_names - {"show_page"}:
        fn = getattr(M.App, name)
        def make_refresh(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs); schedule_final_layout(self); return result
            return wrapped
        setattr(M.App, name, make_refresh(fn))
    old_show = M.App.show_page
    def show_page(self, *args, **kwargs):
        result = old_show(self, *args, **kwargs); schedule_final_layout(self); return result
    M.App.show_page = show_page

    fake_v710 = types.ModuleType("v710_cleanup")
    def v710_apply(target):
        def install(tree, force=False): target.layout_calls.append((tree, bool(force)))
        target.install_persistent_tree_layout = install
        old_top = target.tk.Toplevel.__init__
        def toplevel_init(self, *args, **kwargs):
            old_top(self, *args, **kwargs)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
        target.tk.Toplevel.__init__ = toplevel_init
        for name in layer._V710_REFRESH_METHODS:
            function = getattr(target.App, name, None)
            if not callable(function): continue
            def make_wrapper(function):
                def wrapped(self, *args, **kwargs):
                    result = function(self, *args, **kwargs)
                    self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
                    return result
                return wrapped
            setattr(target.App, name, make_wrapper(function))
        old_schedule = target.schedule_final_tree_layout
        def schedule_final_tree_layout(app):
            result = old_schedule(app)
            app.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
            return result
        target.schedule_final_tree_layout = schedule_final_tree_layout
        old_user_changed = target.App.on_user_changed
        def on_user_changed(self, *args, **kwargs):
            result = old_user_changed(self, *args, **kwargs)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
            return result
        target.App.on_user_changed = on_user_changed
        old_app_init = target.App.__init__
        def app_init(self, *args, **kwargs):
            result = old_app_init(self, *args, **kwargs)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
            return result
        target.App.__init__ = app_init
    fake_v710.apply = v710_apply

    fake_v760 = types.ModuleType("v760_table_activity_performance")
    def v760_apply(target):
        Treeview = target.ttk.Treeview
        original_init, original_column = Treeview.__init__, Treeview.column
        original_configure, original_xview = Treeview.configure, Treeview.xview
        Treeview.__init__ = lambda self, *a, **k: original_init(self, *a, **k)
        Treeview.heading = lambda self, *a, **k: "globally-patched-heading"
        Treeview.column = lambda self, *a, **k: original_column(self, *a, **k)
        Treeview.configure = lambda self, *a, **k: original_configure(self, *a, **k)
        Treeview.config = Treeview.configure
        Treeview.xview = lambda self, *a, **k: original_xview(self, *a, **k)
        def install_tree_polish(tree): target.polish_calls.append(tree)
        target.install_v760_tree_polish = install_tree_polish
        def repack_navigation(app): app.repack_count = getattr(app, "repack_count", 0) + 1
        def configure_project_workspace(app): app.project_configuration_count = getattr(app, "project_configuration_count", 0) + 1
        def configure_task_workspace(app): app.task_configuration_count = getattr(app, "task_configuration_count", 0) + 1
        def promote_accent_button(_app, _key, _text): return None
        def install_resize_guard(_app, _tree, _method, _token): return None
        previous_build = target.App.build
        def build(self, *args, **kwargs):
            result = previous_build(self, *args, **kwargs)
            repack_navigation(self); configure_project_workspace(self); configure_task_workspace(self)
            promote_accent_button(self, "offers", "Zpracovat nabídku")
            install_resize_guard(self, None, "", "")
            if False: install_tree_polish(None)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1))
            return result
        target.App.build = build
        previous_apply_theme = target.App.apply_theme
        def apply_theme(self, *args, **kwargs):
            result = previous_apply_theme(self, *args, **kwargs); install_tree_polish(self.project_tree)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1)); return result
        target.App.apply_theme = apply_theme
        previous_app_init = target.App.__init__
        def app_init(self, *args, **kwargs):
            result = previous_app_init(self, *args, **kwargs)
            repack_navigation(self); configure_project_workspace(self); configure_task_workspace(self)
            promote_accent_button(self, "offers", "Zpracovat nabídku")
            install_resize_guard(self, None, "", ""); install_tree_polish(self.project_tree)
            self.after(100, lambda: setattr(target, "recursive_scan_count", target.recursive_scan_count + 1)); return result
        target.App.__init__ = app_init
    fake_v760.apply = v760_apply

    saved = {name: sys.modules.get(name) for name in ("v710_cleanup", "v760_table_activity_performance")}
    sys.modules["v710_cleanup"], sys.modules["v760_table_activity_performance"] = fake_v710, fake_v760
    try:
        layer.apply(M)
        assert getattr(fake_v710.apply, "_turto_v762_safe", False)
        assert getattr(fake_v760.apply, "_turto_v762_safe", False)

        probe = object.__new__(M.App); Widget.__init__(probe)
        probe.refresh_actions()
        for _delay, callback in list(probe.callbacks): callback()
        assert M.recursive_scan_count == 0

        fake_v710.apply(M)
        assert M.tk.Toplevel.__init__ is native_toplevel_init
        assert M._turto_v762_v710_global_scans_disabled

        fake_v760.apply(M)
        assert M.ttk.Treeview is NativeTreeview
        assert NativeTreeview.heading is native_heading
        assert NativeTreeview.column is native_column
        assert NativeTreeview.configure is native_configure
        assert M._turto_v762_global_treeview_hooks_disabled

        app = M.App()
        for _ in range(20):
            pending, app.callbacks = list(app.callbacks), []
            if not pending: break
            for _delay, callback in pending: callback()

        assert M.recursive_scan_count == 0
        assert (M.cleanup_count, M.faulthandler_count, M.exception_guard_count, M.drop_target_count) == (1, 1, 1, 1)
        assert M.layout_calls and M.polish_calls
        assert getattr(app, "project_configuration_count", 0) > 0
        assert getattr(app, "task_configuration_count", 0) > 0
    finally:
        for name, previous in saved.items():
            if previous is None: sys.modules.pop(name, None)
            else: sys.modules[name] = previous

    print("TURTO CRM 7.6.2 startup stability validation passed.")


if __name__ == "__main__":
    main()
