# TURTO CRM 7.6.2 - default sorting and native Tk startup stability
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Callable


WARNING_MARKERS = ("⚠️", "⚠", "▲", "△")
PAGE_SORTS = {
    "actions": ("date", "action_tree", ("Přijato", "Datum přijetí", "Přijetí")),
    "requests": ("date", "request_tree", ("Poptáno", "Datum poptávky", "Poptávka")),
    "mivo": ("date", "mivo_tree", ("Poptáno", "Datum poptávky", "Poptávka")),
    "projects": ("alpha", "project_tree", ("Název Akce", "Název akce", "Akce", "Název")),
}

_TREE_ATTRIBUTES = (
    "dash_tree",
    "dash_tasks_tree",
    "action_tree",
    "request_tree",
    "mivo_tree",
    "project_tree",
    "offer_tree",
    "issued_offer_tree",
    "price_current_tree",
    "price_evidence_tree",
    "price_list_tree",
    "task_tree",
    "company_tree",
    "people_tree",
    "person_tree",
)

_V710_REFRESH_METHODS = (
    "refresh_dash",
    "refresh_actions",
    "refresh_requests",
    "refresh_mivo_requests",
    "refresh_projects",
    "refresh_offers",
    "refresh_issued_offers",
    "refresh_price_lists",
    "refresh_tasks",
    "refresh_companies",
    "refresh_people",
    "refresh_" + "all",
    "show_page",
)


def _closure_value(function: Any, name: str, default: Any = None) -> Any:
    try:
        cells = function.__closure__ or ()
        values = (cell.cell_contents for cell in cells)
        return dict(zip(function.__code__.co_freevars, values)).get(name, default)
    except Exception:
        return default


def _exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _known_trees(app: Any):
    seen: set[int] = set()
    for attribute in _TREE_ATTRIBUTES:
        tree = getattr(app, attribute, None)
        if not _exists(tree) or id(tree) in seen:
            continue
        seen.add(id(tree))
        yield tree


def _safe_auxiliary_redraw(app: Any) -> None:
    """Refresh only lightweight overlays on explicitly known live tables."""
    for tree in _known_trees(app):
        for attribute in ("_sync_filter_bar", "_date_cell_redraw"):
            function = getattr(tree, attribute, None)
            if callable(function):
                try:
                    function()
                except Exception:
                    pass


def _schedule_safe_auxiliary_redraw(app: Any) -> None:
    try:
        previous = getattr(app, "_turto_v762_aux_after", None)
        if previous is not None:
            try:
                app.after_cancel(previous)
            except Exception:
                pass

        def finish() -> None:
            try:
                app._turto_v762_aux_after = None
            except Exception:
                pass
            if _exists(app):
                _safe_auxiliary_redraw(app)

        app._turto_v762_aux_after = app.after_idle(finish)
    except Exception:
        if _exists(app):
            _safe_auxiliary_redraw(app)


def _stabilize_legacy_owner(M: Any) -> None:
    """Remove the pre-7.1 whole-window scans while preserving their useful work."""
    if getattr(M, "_turto_v762_legacy_global_scans_disabled", False):
        return

    App = M.App

    # The active root post_baseline layer wraps refresh methods only to schedule
    # a recursive whole-window geometry pass.  Newer layout owners supersede it.
    for name in (
        "refresh_dash",
        "refresh_dashboard",
        "refresh_actions",
        "refresh_requests",
        "refresh_mivo_requests",
        "refresh_mivo",
        "refresh_projects",
        "refresh_offers",
        "refresh_tasks",
        "refresh_companies",
        "refresh_people",
        "refresh_" + "all",
    ):
        current = getattr(App, name, None)
        previous = _closure_value(current, "fn")
        scheduler = _closure_value(current, "schedule_final_layout")
        if callable(previous) and callable(scheduler):
            setattr(App, name, previous)

    current_show = getattr(App, "show_page", None)
    previous_show = _closure_value(current_show, "old_" + "show")
    show_scheduler = _closure_value(current_show, "schedule_final_layout")
    if callable(previous_show) and callable(show_scheduler):
        App.show_page = previous_show

    # Replace the legacy recursive final-layout owner with named-table redraws.
    M.schedule_final_tree_layout = _schedule_safe_auxiliary_redraw

    # At this point App.__init__ is normally the v631 drop wrapper around the
    # root post_baseline initializer.  Rebuild the two wrappers without
    # normalize()/reclaim_tree_layout(), both of which recursively walk every
    # widget and can outlive a dialog.
    current_init = App.__init__
    root_init = _closure_value(current_init, "old_" + "init")
    outer_faulthandler = _closure_value(current_init, "_enable_faulthandler")
    outer_exception_guard = _closure_value(current_init, "_install_tk_exception_guard")
    outer_drop_target = _closure_value(current_init, "_install_unified_target")

    if not callable(_closure_value(root_init, "normalize")):
        root_init = current_init
        outer_faulthandler = None
        outer_exception_guard = None
        outer_drop_target = None

    normalize = _closure_value(root_init, "normalize")
    reclaim = _closure_value(root_init, "reclaim_tree_layout")
    base_init = _closure_value(root_init, "old_" + "init")
    cleanup = _closure_value(root_init, "cleanup_legacy_offer_staging")

    if callable(normalize) and callable(reclaim) and callable(base_init):
        def safe_legacy_init(self: Any, *args: Any, **kwargs: Any):
            result = base_init(self, *args, **kwargs)
            try:
                tree = getattr(self, "offer_tree", None)
                if _exists(tree):
                    tree.configure(selectmode="extended")
            except Exception:
                pass
            if callable(cleanup):
                try:
                    self.after(
                        1800,
                        lambda current=self: cleanup(current) if _exists(current) else None,
                    )
                except Exception:
                    pass
            for delay, function in (
                (1700, outer_faulthandler),
                (1800, outer_exception_guard),
                (3000, outer_drop_target),
            ):
                # Headless integration tests install their own callback capture.
                # Keep that handler intact so the exact traceback is visible.
                if function is outer_exception_guard and os.environ.get("TURTO_DISABLE_AUTO_UPDATE"):
                    continue
                if callable(function):
                    try:
                        self.after(
                            delay,
                            lambda current=self, callback=function: (
                                callback(current) if _exists(current) else None
                            ),
                        )
                    except Exception:
                        pass
            return result

        App.__init__ = safe_legacy_init

    M._turto_v762_legacy_global_scans_disabled = True


def _install_known_layouts(M: Any, app: Any, force: bool = False) -> None:
    installer = getattr(M, "install_persistent_tree_layout", None)
    for tree in _known_trees(app):
        try:
            tree._turto_configurable_columns = True
        except Exception:
            pass
        if callable(installer):
            try:
                installer(tree, force=force)
            except TypeError:
                try:
                    installer(tree)
                except Exception:
                    pass
            except Exception:
                pass
    request_tree = getattr(app, "request_tree", None)
    if _exists(request_tree):
        try:
            request_tree.configure(selectmode="extended")
        except Exception:
            pass


def _schedule_known_layouts(M: Any, app: Any, force: bool = False) -> None:
    """Install layout support once, synchronously, on stable main tables.

    The removed delayed passes were the last source of Tk calls racing with page
    and dialog teardown.  Table builders and user actions still invoke the same
    persistent-layout owner whenever a real layout change is made.
    """
    if _exists(app):
        _install_known_layouts(M, app, force=force)


def _wrap_v710(M: Any, module: Any) -> None:
    original_apply = getattr(module, "apply", None)
    if not callable(original_apply) or getattr(original_apply, "_turto_v762_safe", False):
        return

    def stable_apply(target: Any) -> Any:
        App = target.App
        app_init_before = App.__init__
        toplevel_init_before = target.tk.Toplevel.__init__
        schedule_before = getattr(target, "schedule_final_tree_layout", None)
        user_changed_before = getattr(App, "on_user_changed", None)
        methods_before = {
            name: getattr(App, name, None)
            for name in _V710_REFRESH_METHODS
        }

        result = original_apply(target)

        # Do not leave delayed recursive scans behind after a dialog is closed.
        try:
            target.tk.Toplevel.__init__ = toplevel_init_before
        except Exception:
            pass

        # v710 wraps these methods only to schedule whole-window scans.
        for name, previous in methods_before.items():
            if not callable(previous):
                continue
            current = getattr(App, name, None)
            if _closure_value(current, "function") is previous:
                setattr(App, name, previous)

        current_schedule = getattr(target, "schedule_final_tree_layout", None)
        if (
            callable(schedule_before)
            and _closure_value(current_schedule, "old_schedule") is schedule_before
        ):
            target.schedule_final_tree_layout = schedule_before

        current_user_changed = getattr(App, "on_user_changed", None)
        if (
            callable(user_changed_before)
            and _closure_value(current_user_changed, "old_user_changed")
            is user_changed_before
        ):
            def safe_user_changed(self: Any, *args: Any, **kwargs: Any):
                outcome = user_changed_before(self, *args, **kwargs)
                _schedule_known_layouts(target, self, force=False)
                return outcome

            App.on_user_changed = safe_user_changed

        current_init = App.__init__
        if _closure_value(current_init, "old_app_init") is app_init_before:
            def safe_app_init(self: Any, *args: Any, **kwargs: Any):
                outcome = app_init_before(self, *args, **kwargs)
                target._active_app = self
                # One synchronous pass only. No callback can outlive startup.
                _schedule_known_layouts(target, self, force=False)
                return outcome

            App.__init__ = safe_app_init

        target._turto_v762_v710_global_scans_disabled = True
        return result

    stable_apply._turto_v762_safe = True
    module.apply = stable_apply


def _collect_v760_helpers(*functions: Any) -> dict[str, Callable[..., Any]]:
    names = (
        "repack_navigation",
        "configure_project_workspace",
        "configure_task_workspace",
        "promote_accent_button",
        "install_resize_guard",
        "install_tree_polish",
    )
    result: dict[str, Callable[..., Any]] = {}
    for function in functions:
        for name in names:
            candidate = _closure_value(function, name)
            if callable(candidate):
                result.setdefault(name, candidate)
    return result


def _finalize_v760_known(M: Any, app: Any, helpers: dict[str, Callable[..., Any]]) -> None:
    if not _exists(app):
        return

    repack = helpers.get("repack_navigation")
    if callable(repack):
        try:
            repack(app)
        except Exception:
            pass

    for name in ("configure_project_workspace", "configure_task_workspace"):
        function = helpers.get(name)
        if callable(function):
            try:
                function(app)
            except Exception:
                pass

    promote = helpers.get("promote_accent_button")
    if callable(promote):
        for page_key, needle in (
            ("offers", "Zpracovat nabídku"),
            ("pricelists", "Importovat Ceník"),
            ("issued_offers", "Nová nabídka"),
        ):
            try:
                promote(app, page_key, needle)
            except Exception:
                pass

    # The legacy resize guard triggered full table refreshes from Configure
    # events. Persistent widths already own resize handling, so do not compose a
    # second event-driven refresh owner here.

    polish = helpers.get("install_tree_polish") or getattr(
        M, "install_v760_tree_polish", None
    )
    if callable(polish):
        for tree in _known_trees(app):
            try:
                polish(tree)
            except Exception:
                pass


def _wrap_v760(M: Any, module: Any) -> None:
    original_apply = getattr(module, "apply", None)
    if not callable(original_apply) or getattr(original_apply, "_turto_v762_safe", False):
        return

    def stable_apply(target: Any) -> Any:
        App = target.App
        app_init_before = App.__init__
        build_before = getattr(App, "build", None)
        theme_before = getattr(App, "apply_theme", None)
        native_treeview = target.ttk.Treeview
        layout_apis_before = {
            name: getattr(target, name, None)
            for name in (
                "save_persistent_tree_layout",
                "install_persistent_tree_layout",
                "open_tree_columns_dialog",
            )
        }

        # v760 may construct all local helpers, but it may not replace native
        # ttk.Treeview methods process-wide. A disposable subclass contains the
        # old hook implementation and is discarded before App is instantiated.
        proxy_treeview = type(
            "_TurtoV762TreeviewHookSandbox",
            (native_treeview,),
            {"__module__": __name__},
        )
        target.ttk.Treeview = proxy_treeview
        try:
            result = original_apply(target)
        finally:
            target.ttk.Treeview = native_treeview

        current_init = App.__init__
        current_build = getattr(App, "build", None)
        current_theme = getattr(App, "apply_theme", None)
        helpers = _collect_v760_helpers(current_init, current_build, current_theme)

        # Do not retain wrappers that call table-polish code as a side effect of
        # saving a width or opening the columns dialog. The one installed main-
        # table binding is enough and avoids re-entrant heading work.
        for name, previous in layout_apis_before.items():
            if callable(previous):
                setattr(target, name, previous)

        if (
            callable(build_before)
            and _closure_value(current_build, "previous_build") is build_before
        ):
            def safe_build(self: Any, *args: Any, **kwargs: Any):
                outcome = build_before(self, *args, **kwargs)
                _finalize_v760_known(target, self, helpers)
                return outcome

            App.build = safe_build

        # Theme and App.__init__ wrappers in v760 only repeated the same whole-
        # application finalizer. Restore the pre-v760 owners. The build wrapper
        # above performs one deterministic pass after all main widgets exist.
        if callable(theme_before):
            App.apply_theme = theme_before
        App.__init__ = app_init_before

        target._turto_v762_native_treeview = native_treeview
        target._turto_v762_global_treeview_hooks_disabled = True
        target._turto_v762_reentrant_table_refresh_disabled = True
        return result

    stable_apply._turto_v762_safe = True
    module.apply = stable_apply


def _install_startup_stability_bridge(M: Any) -> None:
    if getattr(M, "_turto_v762_startup_stability_bridge", False):
        return
    _stabilize_legacy_owner(M)
    v710 = sys.modules.get("v710_cleanup")
    v760 = sys.modules.get("v760_table_activity_performance")
    if v710 is not None:
        _wrap_v710(M, v710)
    if v760 is not None:
        _wrap_v760(M, v760)
    M._turto_v762_startup_stability_bridge = True


def apply(M):
    if getattr(M, "_turto_default_sort_v6331", False):
        return

    _install_startup_stability_bridge(M)

    def widget_exists(widget):
        try:
            return widget is not None and bool(widget.winfo_exists())
        except Exception:
            return widget is not None

    def parse_date(value):
        # Keep the 6.3.21 regression fix: a temporary visual warning marker must
        # never make a real date sort as an empty value.
        text = str(value or "").strip()
        for marker in WARNING_MARKERS:
            text = text.replace(marker, "")
        text = " ".join(text.split())
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                pass
        return datetime.min

    def reset_sort_state(tree):
        try:
            tree._sort_state = {}
            tree._active_sort = None
        except Exception:
            pass

    def sort_date(tree, candidates):
        if not widget_exists(tree):
            return
        try:
            columns = list(tree.cget("columns"))
            column = next((candidate for candidate in candidates if candidate in columns), None)
            if not column:
                return
            rows = [(parse_date(tree.set(iid, column)), iid) for iid in tree.get_children("")]
            rows.sort(key=lambda pair: pair[0], reverse=True)
            for position, (_value, iid) in enumerate(rows):
                tree.move(iid, "", position)
            reset_sort_state(tree)
        except Exception:
            pass

    def sort_alpha(tree, candidates):
        if not widget_exists(tree):
            return
        try:
            columns = list(tree.cget("columns"))
            column = next((candidate for candidate in candidates if candidate in columns), None)
            if not column:
                return
            key = getattr(M, "czech_sort_key", lambda value: str(value or "").strip().casefold())
            rows = list(tree.get_children(""))
            rows.sort(key=lambda iid: key(tree.set(iid, column)))
            for position, iid in enumerate(rows):
                tree.move(iid, "", position)
            reset_sort_state(tree)
        except Exception:
            pass

    def apply_default(app, page_key=None):
        # No global sort sweep. Only the table that has just been refreshed is
        # touched, so switching tabs cannot repeatedly sort unrelated datasets.
        key = page_key or getattr(app, "_current_page", None)
        spec = PAGE_SORTS.get(key)
        if not spec:
            return
        mode, attribute, candidates = spec
        tree = getattr(app, attribute, None)
        if mode == "date":
            sort_date(tree, candidates)
        else:
            sort_alpha(tree, candidates)

    def schedule_default(app, page_key):
        if getattr(app, "_turto_closing", False):
            return
        jobs = getattr(app, "_turto_default_sort_jobs", None)
        if jobs is None:
            jobs = {}
            app._turto_default_sort_jobs = jobs
        previous = jobs.pop(page_key, None)
        if previous is not None:
            try:
                app.after_cancel(previous)
            except Exception:
                pass

        def run():
            jobs.pop(page_key, None)
            if getattr(app, "_turto_closing", False):
                return
            if getattr(app, "_current_page", None) != page_key:
                return
            apply_default(app, page_key)

        try:
            jobs[page_key] = app.after_idle(run)
        except Exception:
            apply_default(app, page_key)

    for method_name, page_key in (
        ("refresh_actions", "actions"),
        ("refresh_requests", "requests"),
        ("refresh_mivo_requests", "mivo"),
        ("refresh_mivo", "mivo"),
        ("refresh_projects", "projects"),
    ):
        original = getattr(M.App, method_name, None)
        if not callable(original):
            continue

        def make(function, key):
            def wrapped(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                if not getattr(self, "_turto_page_refresh_running", False):
                    schedule_default(self, key)
                return result
            return wrapped

        setattr(M.App, method_name, make(original, page_key))

    M.apply_default_table_sort = apply_default
    M._turto_default_sort_v6331 = True
