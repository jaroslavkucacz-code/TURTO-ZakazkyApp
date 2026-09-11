#!/usr/bin/env python3
"""Real-Tk menu lifecycle regression; all business callbacks use harmless spies.

Compare with actual 8.0.5 source supplied by --baseline. --full-app additionally
checks the fully composed application on an isolated data root (never user data).
"""
from __future__ import annotations

import argparse
import ast
import gc
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any
import tkinter as tk
from tkinter import ttk

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"


def load_helper():
    path = BASE / "price_lists_domain/platform/context_menu_lifecycle.py"
    spec = importlib.util.spec_from_file_location("menu_lifecycle_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def extract(path: Path, name: str, namespace: dict):
    source = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1, (path, name)
    program = ast.Module(body=[nodes[0]], type_ignores=[])
    exec(compile(ast.fix_missing_locations(program), str(path), "exec"), namespace)
    return namespace[name]


def menu_shape(menu):
    return [(menu.type(i), str(menu.entrycget(i, "label")) if menu.type(i) != "separator" else "")
            for i in range(int(menu.index("end")) + 1)]


def menu_children(tree):
    return [w for w in tree.winfo_children() if isinstance(w, tk.Menu)]


def isolated_case(source_root: Path, key: str, optimized: bool, helper) -> dict:
    root = tk.Tk()
    root.geometry("420x340")
    tree = ttk.Treeview(root, columns=("Stav", "Nazev"), show="headings", selectmode="extended")
    tree.pack(fill="both", expand=True)
    tree.heading("Stav", text="Stav")
    tree.heading("Nazev", text="Název")
    prefix = "a" if key == "actions" else "o" if key == "offers" else "r"
    first, second = prefix + "1", prefix + "2"
    tree.insert("", "end", iid=first, values=("Aktivní", "První"))
    tree.insert("", "end", iid=second, values=("Čeká", "Druhý"))
    tree.selection_set(first, second)
    calls, posts, errors = [], [], []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    double_id = tree.bind("<Double-1>", lambda _event: None)
    double_script = tree.bind("<Double-1>")

    def record(name):
        def call(*args, **kwargs):
            calls.append((name, tuple("tree" if arg is tree else arg for arg in args)))
        return call

    app = SimpleNamespace()
    for name in ("edit_action", "request_from_selected_action", "task_from_selected_action",
                 "delete_action", "edit_request", "mail_selected", "mark_received",
                 "mark_no_response", "hard_delete_request", "open_offer_detail", "delete_offer"):
        setattr(app, name, record(name))
    app.offer_tree = tree
    app.mivo_tree = tree if key == "mivo" else None

    def runner(current, callback):
        assert current is tree
        calls.append(("mivo-routing", ()))
        return callback()
    app._run_on_request_tree = runner
    M = SimpleNamespace(tk=tk, install_persistent_tree_layout=lambda *_a, **_k: None,
                        open_tree_columns_dialog=record("columns"))
    commercial = SimpleNamespace(
        _offer_to_issued_offer=lambda *_: record("to-issued")(),
        _offer_to_price_list=lambda *_: record("to-pricelist")(),
        _archive_offers=lambda _m, _a, restore: record("archive-offer")(restore),
        _run_after_invalidation=lambda _a, fn, **_kw: fn(),
        update_offer_selection=lambda *_: record("offer-selection")(),
    )
    namespace = {
        "Any": Any, "M": M, "commercial_workspace": commercial,
        "reuse_context_menus": helper.reuse_context_menus,
        "replace_context_menus": helper.replace_context_menus,
        "reset_tree_columns": record("reset-columns"),
        "archive_actions": lambda _app, value: record("archive-action")(value),
        "archive_requests": lambda _app, _tree, value: record("archive-request")(value),
    }
    filename = "v740_offer_defaults.py" if key == "offers" else "v750_context_filters_offer_format.py"
    path = source_root / filename
    namespace["_widget_exists"] = extract(path, "_widget_exists", namespace)
    if key == "offers":
        function = extract(path, "install_offer_context", namespace)
        install = lambda: function(app)
        stem = "_v740"
    else:
        namespace["request_action"] = extract(path, "request_action", namespace)
        function = extract(path, "install_workspace_context", namespace)
        install = lambda: function(app, key, tree)
        stem = "_v750"
    try:
        install()
        root.update()
        header, row = getattr(tree, stem + "_header_menu"), getattr(tree, stem + "_row_menu")
        shapes = [menu_shape(header), menu_shape(row)]
        formatting = [tuple(str(menu.cget(option)) for option in ("tearoff", "font")) for menu in (header, row)]
        for menu in (header, row):
            for i in range(int(menu.index("end")) + 1):
                if menu.type(i) == "command":
                    menu.invoke(i)
        callback_trace = list(calls)
        calls.clear()
        header.tk_popup = lambda *_: posts.append("header")
        row.tk_popup = lambda *_: posts.append("row")
        header.grab_release = row.grab_release = lambda: None
        tree.event_generate("<Button-3>", x=10, y=5)
        assert posts == ["header"]
        x, y, width, height = tree.bbox(first)
        tree.event_generate("<Button-3>", x=x + 6, y=y + height // 2)
        assert posts[-1] == "row" and tree.selection() == (first, second)
        tree.selection_set(second)
        tree.event_generate("<Button-3>", x=x + 6, y=y + height // 2)
        assert tree.selection() == (first,)
        posted = len(posts)
        tree.event_generate("<Button-3>", x=10, y=300)
        assert len(posts) == posted  # Empty space never opens a row action.
        commands_before = len(tree._tclCommands or ())
        for _ in range(50):
            install()
        menus_after = len(menu_children(tree))
        added_commands = len(tree._tclCommands or ()) - commands_before
        assert tree.bind("<Double-1>") == double_script
        if optimized:
            assert menus_after == 2 and added_commands == 0
            assert getattr(tree, stem + "_row_menu") is row
            assert getattr(tree, stem + "_header_menu") is header
            # Preserve final selection policy and any explicitly styled menu.
            row.entryconfigure(0, state="disabled")
            row.configure(font=("Calibri", 11), postcommand=lambda: None)
            configured = (row.cget("font"), row.cget("postcommand"))
            install()
            assert str(row.entrycget(0, "state")) == "disabled"
            assert (row.cget("font"), row.cget("postcommand")) == configured
            state = tree._turto_context_menu_binding
            command, script = state["command"], state["script"]
            foreign = tree.bind("<Button-3>", lambda _event: None)
            install()
            assert tree.bind("<Button-3>") == script
            assert tree._turto_context_menu_binding["command"] == command
            assert tree.tk.call("info", "commands", foreign)
            tree.deletecommand(foreign)
            # Lost widgets and missing Tcl callbacks rebuild exactly one pair.
            unrelated = tk.Menu(tree, tearoff=False)
            header.destroy()
            install()
            assert not row.winfo_exists() and unrelated.winfo_exists()
            assert not tree.tk.call("info", "commands", command)
            assert len(menu_children(tree)) == 3
            new_state = tree._turto_context_menu_binding
            tree.deletecommand(new_state["command"])
            install()
            assert len(menu_children(tree)) == 3 and unrelated.winfo_exists()
            state = tree._turto_context_menu_binding
            assert not helper.reuse_context_menus(tree, "another-owner", state["menus"])
            assert not helper.reuse_context_menus(tree, state["owner"], (unrelated,))
            command = state["command"]
            menu_paths = tuple(str(m) for m in state["menus"])
            tree.destroy()
            gc.collect()
            assert not root.tk.call("info", "commands", command)
            assert not root.tk.call("info", "commands", double_id)
            assert all(not root.tk.call("winfo", "exists", p) for p in menu_paths)
        else:
            assert menus_after == 102 and added_commands == 50
        assert not errors, errors
        return {"key": key, "shapes": shapes, "formatting": formatting,
                "calls": callback_trace, "menus_after_51_installs": menus_after,
                "extra_popup_commands": added_commands}
    finally:
        root.destroy()


def find_closure_function(function, wanted):
    pending, seen = [function], set()
    while pending:
        fn = pending.pop()
        if not inspect.isfunction(fn) or id(fn) in seen:
            continue
        seen.add(id(fn))
        if fn.__name__ == wanted:
            return fn
        for cell in fn.__closure__ or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if inspect.isfunction(value):
                pending.append(value)
    raise AssertionError("Missing actual runtime installer: " + wanted)


def full_app_case():
    assert os.environ.get("TURTO_CRM_DATA_ROOT"), "Full UI probe needs an isolated data root"
    os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"
    sys.path.insert(0, str(BASE))
    import app, data_location, runtime_bootstrap
    data_location.apply_to_app(app)
    app.cleanup_stale_test_session()
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.migrate_v41_visual_once()
    app.App.maybe_show_morning_overview = lambda self: None
    errors = []
    window = app.App()
    window.report_callback_exception = lambda *exc: errors.append(str(exc))
    try:
        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        offers = find_closure_function(app.App.build_offers, "install_offer_context")
        workspaces = find_closure_function(app.App.build_actions, "install_workspace_context")
        results = []
        for key, attr in (("offers", "offer_tree"), ("actions", "action_tree"),
                          ("requests", "request_tree"), ("mivo", "mivo_tree")):
            tree = getattr(window, attr)
            state = tree._turto_context_menu_binding
            old_menus, old_command = state["menus"], state["command"]
            count_before = len(menu_children(tree))
            for _ in range(30):
                offers(window) if key == "offers" else workspaces(window, key, tree)
            window.update()
            state = tree._turto_context_menu_binding
            assert state["menus"] == old_menus and state["command"] == old_command
            assert len(menu_children(tree)) == count_before
            if key != "offers":
                assert getattr(state["menus"][1], "_turto_context_postcommand", False)
            results.append({"page": key, "menu_count_before": count_before,
                            "menu_count_after_30_reinstalls": len(menu_children(tree))})
        assert not errors, errors
        return results
    finally:
        window.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--full-app", action="store_true")
    args = parser.parse_args()
    if args.full_app:
        result = {"ok": True, "full_app": full_app_case()}
    else:
        assert args.baseline and args.baseline.is_dir(), "Provide the actual 8.0.5 source"
        helper = load_helper()
        records = []
        for key in ("offers", "actions", "requests", "mivo"):
            old = isolated_case(args.baseline, key, False, helper)
            new = isolated_case(BASE, key, True, helper)
            for field in ("shapes", "formatting", "calls"):
                assert old[field] == new[field], (key, field, old[field], new[field])
            records.append({"page": key, "legacy_menus": old["menus_after_51_installs"],
                            "current_menus": new["menus_after_51_installs"],
                            "legacy_extra_callbacks": old["extra_popup_commands"],
                            "current_extra_callbacks": new["extra_popup_commands"]})
        result = {"ok": True, "cases": records, "callback_and_menu_parity": True}
    text = json.dumps(result, ensure_ascii=True, indent=2)
    output = os.environ.get("TURTO_CRM_MENU_RESULT")
    if output:
        Path(output).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
