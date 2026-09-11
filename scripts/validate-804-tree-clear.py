#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 batched Treeview clears."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_tree_clear_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTree:
    def __init__(self, count=8):
        self.rows = [f"r{i}" for i in range(count)]
        self.delete_calls = []
        self.insert_calls = []

    def get_children(self, parent=""):
        return tuple(self.rows)

    def delete(self, *items):
        self.delete_calls.append(tuple(items))
        for iid in items:
            if iid in self.rows:
                self.rows.remove(iid)

    def insert(self, parent, index, iid=None, **options):
        iid = iid or f"new-{len(self.insert_calls)}"
        self.insert_calls.append((iid, tuple(options.get("values") or ())))
        self.rows.append(iid)
        return iid


class FakeApp:
    def __init__(self):
        self.action_tree = FakeTree(12)
        self.task_tree = FakeTree(5)


def action_refresh(self):
    for iid in self.action_tree.get_children(""):
        self.action_tree.delete(iid)
    self.action_tree.insert("", "end", iid="a1", values=("one",))
    self.action_tree.insert("", "end", iid="a2", values=("two",))
    # This is deliberately after the first insert and must not be coalesced with
    # the initial clear; later archive/filter deletes must retain normal timing.
    self.action_tree.delete("a1")
    return "actions-ok"


def task_refresh(self):
    for iid in self.task_tree.get_children(""):
        self.task_tree.delete(iid)
    self.task_tree.insert("", "end", iid="t1", values=("task",))
    return "tasks-ok"


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    module = load_module(root / "price_lists_domain" / "platform" / "tree_clear_804.py")

    App = type("App", (FakeApp,), {"refresh_actions": action_refresh, "refresh_tasks": task_refresh})
    M = SimpleNamespace(App=App)
    module.apply(M)

    assert getattr(App.refresh_actions, "_turto_804_batched_tree_clear", False)
    assert getattr(App.refresh_tasks, "_turto_804_batched_tree_clear", False)
    assert M.TREE_CLEAR_804["actions"] == "batch-leading-delete"
    assert M.TREE_CLEAR_804["tasks"] == "batch-leading-delete"

    app = App()
    original_action_delete = app.action_tree.delete
    original_action_insert = app.action_tree.insert
    result = app.refresh_actions()
    assert result == "actions-ok"
    # Twelve historical one-row deletes collapse into one native delete call.
    assert len(app.action_tree.delete_calls) == 2, app.action_tree.delete_calls
    assert app.action_tree.delete_calls[0] == tuple(f"r{i}" for i in range(12))
    # The post-insert delete is deliberately left as its own operation.
    assert app.action_tree.delete_calls[1] == ("a1",)
    assert app.action_tree.rows == ["a2"]
    # Instance monkey patches are gone after the refresh.
    assert "delete" not in app.action_tree.__dict__
    assert "insert" not in app.action_tree.__dict__
    assert app.action_tree.delete.__func__ is original_action_delete.__func__
    assert app.action_tree.insert.__func__ is original_action_insert.__func__

    task_result = app.refresh_tasks()
    assert task_result == "tasks-ok"
    assert app.task_tree.delete_calls == [tuple(f"r{i}" for i in range(5))]
    assert app.task_tree.rows == ["t1"]

    # If a refresh fails before its first insert, pending rows still clear once
    # and the real methods are restored before the exception escapes.
    broken = FakeTree(4)
    owner = SimpleNamespace()

    def explode(_owner):
        for iid in broken.get_children(""):
            broken.delete(iid)
        raise RuntimeError("expected")

    try:
        module._run_with_batched_initial_clear(broken, explode, owner, (), {})
    except RuntimeError as exc:
        assert str(exc) == "expected"
    else:
        raise AssertionError("Expected failure did not propagate")
    assert broken.delete_calls == [("r0", "r1", "r2", "r3")]
    assert broken.rows == []
    assert "delete" not in broken.__dict__ and "insert" not in broken.__dict__

    bootstrap = (root / "runtime_bootstrap.py").read_text(encoding="utf-8")
    operational = '"price_lists_domain.platform.operational_refresh_804"'
    batched = '"price_lists_domain.platform.tree_clear_804"'
    assert operational in bootstrap and batched in bootstrap
    assert bootstrap.index(batched) > bootstrap.index(operational)

    print("TURTO CRM 8.0.4 batched Treeview clear: OK")


if __name__ == "__main__":
    main()
