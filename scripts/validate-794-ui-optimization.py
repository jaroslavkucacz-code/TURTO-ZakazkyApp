#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.9.4 UI cleanup/optimization."""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
import tempfile


def load_module(root: pathlib.Path):
    path = root / "price_lists_domain" / "platform" / "ui_cleanup_793.py"
    spec = importlib.util.spec_from_file_location("ui_cleanup_793", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Tree:
    def __init__(self, selection=()):
        self._selection = tuple(selection)

    def winfo_exists(self):
        return 1

    def selection(self):
        return self._selection


class Button:
    def __init__(self):
        self.enabled = True

    def winfo_exists(self):
        return 1

    def state(self, values):
        self.enabled = "disabled" not in values


class Module:
    def __init__(self, db_path: pathlib.Path):
        self.path = db_path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


def make_v750_callback():
    namespace = {"configure_workspaces": lambda _current: None}
    code = compile(
        "lambda current=None: configure_workspaces(current)",
        "v750_context_filters_offer_format.py",
        "eval",
    )
    return eval(code, namespace)


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    ui = load_module(root)

    assert set(ui.WORKSPACES) == {"projects", "actions", "requests", "mivo", "tasks"}

    with tempfile.TemporaryDirectory(prefix="turto794_") as td:
        db_path = pathlib.Path(td) / "test.db"
        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE projects(id INTEGER PRIMARY KEY, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE actions(id INTEGER PRIMARY KEY, archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE requests(id INTEGER PRIMARY KEY, archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE tasks(id INTEGER PRIMARY KEY, archived INTEGER NOT NULL DEFAULT 0);
            INSERT INTO projects(id,active) VALUES(1,1),(2,0);
            INSERT INTO actions(id,archived) VALUES(10,0),(11,1),(12,0);
            INSERT INTO requests(id,archived) VALUES(20,0),(21,1);
            INSERT INTO tasks(id,archived) VALUES(30,0),(31,1);
            """
        )
        con.commit()
        con.close()
        M = Module(db_path)

        # Preserve the original v7.9.3 four-argument contract.
        action = ui.workspace_capabilities(M, Tree(("a10",)), "actions", "a")
        assert action["single"] and action["can_archive"] and not action["can_restore"]
        mixed = ui.workspace_capabilities(M, Tree(("a10", "a11")), "actions", "a")
        assert not mixed["single"] and mixed["can_archive"] and mixed["can_restore"]

        project_active = ui.workspace_capabilities(
            M, Tree(("p1",)), "projects", "p", "active", 1, 0
        )
        assert project_active["single"] and project_active["can_archive"] and not project_active["can_restore"]
        project_archived = ui.workspace_capabilities(
            M, Tree(("p2",)), "projects", "p", "active", 1, 0
        )
        assert project_archived["single"] and not project_archived["can_archive"] and project_archived["can_restore"]

        task_archived = ui.workspace_capabilities(
            M, Tree(("t31",)), "tasks", "t", "archived", 0, 1
        )
        assert task_archived["single"] and not task_archived["can_archive"] and task_archived["can_restore"]

        stale = ui.workspace_capabilities(M, Tree(("r999",)), "requests", "r")
        assert not stale["single"] and not stale["can_archive"] and not stale["can_restore"]

    # Stored toolbar controls must be used without a recursive tab walk and then
    # cached on the Treeview for subsequent selection changes.
    archive = Button()
    restore = Button()
    checkbox = Button()
    tree = Tree(("a10",))
    app = type("App", (), {})()
    app._v750_actions_archive_controls = (checkbox, archive, restore)
    spec = ui.WORKSPACES["actions"]
    first = ui._toolbar_buttons(app, "actions", spec, tree)
    assert first == (archive, restore)
    del app._v750_actions_archive_controls
    second = ui._toolbar_buttons(app, "actions", spec, tree)
    assert second == first

    # Only the known later v7.5 safety rebuilds are coalesced.  The 0-ms fallback
    # and unrelated callbacks must still reach Tk.
    v750_callback = make_v750_callback()
    assert not ui._is_redundant_v750_rebuild(0, v750_callback)
    for delay in (80, 260, 760, 1650):
        assert ui._is_redundant_v750_rebuild(delay, v750_callback)
    assert not ui._is_redundant_v750_rebuild(90, v750_callback)
    assert not ui._is_redundant_v750_rebuild(80, lambda: None)

    class Instance:
        def __init__(self):
            self.calls = []

        def after(self, delay, callback=None, *args):
            self.calls.append((int(delay), callback, args))
            return f"after-{len(self.calls)}"

    instance = Instance()

    def previous_init(current):
        for delay in (0, 80, 260, 760, 1650):
            current.after(delay, v750_callback)
        current.after(125, lambda: None)
        return "ok"

    result = ui._call_previous_init_optimized(instance, previous_init)
    assert result == "ok"
    assert [delay for delay, _callback, _args in instance.calls] == [0, 125]
    assert instance._turto_v750_rebuilds_coalesced == (80, 260, 760, 1650)

    bootstrap = (root / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert '"price_lists_domain.platform.ui_cleanup_793"' in bootstrap
    assert bootstrap.index('"v770_runtime_policy"') < bootstrap.index(
        '"price_lists_domain.platform.ui_cleanup_793"'
    )

    print("TURTO CRM 7.9.4 UI cleanup/optimization: OK")


if __name__ == "__main__":
    main()
