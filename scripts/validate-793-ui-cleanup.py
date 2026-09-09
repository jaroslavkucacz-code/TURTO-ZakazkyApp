#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.9.3 contextual UI cleanup."""
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


class Module:
    def __init__(self, db_path: pathlib.Path):
        self.path = db_path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    ui = load_module(root)

    with tempfile.TemporaryDirectory(prefix="turto793_") as td:
        db_path = pathlib.Path(td) / "test.db"
        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE actions(id INTEGER PRIMARY KEY, archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE requests(id INTEGER PRIMARY KEY, archived INTEGER NOT NULL DEFAULT 0);
            INSERT INTO actions(id,archived) VALUES(1,0),(2,1),(3,0);
            INSERT INTO requests(id,archived) VALUES(10,0),(11,1);
            """
        )
        con.commit()
        con.close()
        M = Module(db_path)

        none = ui.workspace_capabilities(M, Tree(), "actions", "a")
        assert none == {
            "ids": [], "single": False, "can_archive": False, "can_restore": False
        }

        active = ui.workspace_capabilities(M, Tree(("a1",)), "actions", "a")
        assert active["single"] and active["can_archive"] and not active["can_restore"]

        archived = ui.workspace_capabilities(M, Tree(("a2",)), "actions", "a")
        assert archived["single"] and not archived["can_archive"] and archived["can_restore"]

        mixed = ui.workspace_capabilities(M, Tree(("a1", "a2")), "actions", "a")
        assert not mixed["single"] and mixed["can_archive"] and mixed["can_restore"]

        requests = ui.workspace_capabilities(M, Tree(("r10",)), "requests", "r")
        assert requests["single"] and requests["can_archive"] and not requests["can_restore"]

        stale = ui.workspace_capabilities(M, Tree(("a999",)), "actions", "a")
        assert not stale["single"] and not stale["can_archive"] and not stale["can_restore"]

    bootstrap = (root / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert '"price_lists_domain.platform.ui_cleanup_793"' in bootstrap
    assert bootstrap.index('"v770_runtime_policy"') < bootstrap.index(
        '"price_lists_domain.platform.ui_cleanup_793"'
    )

    source = (root / "app.py").read_text(encoding="utf-8")
    assert "def bind_row_double_click" in source
    assert 'tree.identify_region(event.x,event.y)!="cell"' in source

    print("TURTO CRM 7.9.3 contextual UI cleanup: OK")


if __name__ == "__main__":
    main()
