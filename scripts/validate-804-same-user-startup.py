#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 same-user startup fast path."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import sys
import tempfile


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_idle_cleanup_same_user_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class App:
    def __init__(self, user):
        self.active_user = Var(user)


def main() -> None:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    module = load_module(base / "price_lists_domain" / "platform" / "idle_cleanup_804.py")

    with tempfile.TemporaryDirectory(prefix="turto_same_user_") as temp:
        db_path = Path(temp) / "test.db"
        con = sqlite3.connect(db_path)
        con.execute("CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,active INTEGER)")
        con.executemany(
            "INSERT INTO users(name,active) VALUES(?,1)",
            [("Jaroslav Kučera",), ("Denisa Kovalová",), ("ADMIN",)],
        )
        con.commit()
        con.close()

        def db():
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            connection.create_collation("CZECH", lambda a, b: (a > b) - (a < b))
            return connection

        M = SimpleNamespace(db=db)
        state = {"last_user": "Jaroslav Kučera"}
        writes = []
        original_calls = []

        def cfg():
            return dict(state)

        def save_cfg(**changes):
            writes.append(dict(changes))
            state.update(changes)

        def original(app):
            original_calls.append(app.active_user.get())
            return "original-result"

        runtime = SimpleNamespace(
            _cfg=cfg,
            _save_cfg=save_cfg,
            _restore_local_user=original,
        )
        assert module._install_same_user_restore_fast_path(M, runtime) is True
        optimized = runtime._restore_local_user
        assert getattr(optimized, "_turto_804_same_user_fast", False)

        same = App("Jaroslav Kučera")
        assert optimized(same) is None
        assert original_calls == []
        assert writes == []
        assert same._turto_same_user_restore_skips_804 == 1

        different = App("Denisa Kovalová")
        assert optimized(different) == "original-result"
        assert original_calls == ["Denisa Kovalová"]

        # Invalid/stale client config resolves to the already active valid user.
        # Repair only the tiny local client file; no theme/refresh cycle is needed.
        state["last_user"] = "Neexistující uživatel"
        repaired = App("Denisa Kovalová")
        assert optimized(repaired) is None
        assert original_calls == ["Denisa Kovalová"]
        assert writes[-1] == {"last_user": "Denisa Kovalová"}
        assert state["last_user"] == "Denisa Kovalová"

        # Installation is idempotent.
        installed = runtime._restore_local_user
        assert module._install_same_user_restore_fast_path(M, runtime) is True
        assert runtime._restore_local_user is installed

    print("TURTO CRM 8.0.4 same-user startup fast path: OK")


if __name__ == "__main__":
    main()
