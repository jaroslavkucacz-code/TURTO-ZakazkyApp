#!/usr/bin/env python3
"""Release regressions against actual legacy functions, with no app/DB startup.

Only selected pure definitions are compiled from app.py/crm_runtime.py. All SQL
runs in memory; neither client configuration nor production data is opened.
Timing is diagnostic, not a flaky pass/fail threshold.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import random
import sqlite3
import statistics
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"


def definitions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    selected = []
    found = set()
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.Assign):
            name = next((t.id for t in node.targets if isinstance(t, ast.Name)), None)
        if name in names:
            selected.append(node)
            found.add(name)
    assert found == set(names), (path, found, names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def load(name):
    path = BASE / "price_lists_domain" / "platform" / (name + ".py")
    spec = importlib.util.spec_from_file_location("release_edges_" + name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def check_collation():
    ns = definitions(BASE / "app.py", {"_CZ_ORDER", "czech_sort_key", "_czech_collate"}, {})
    historical_key = ns["czech_sort_key"]
    legacy = ns["_czech_collate"]
    module = SimpleNamespace(czech_sort_key=historical_key, _czech_collate=legacy)
    optimization = load("runtime_optimization_803")
    assert optimization._install_czech_sort_cache(module)
    # Match 8.0.4 exactly: its original comparator calls the already cached public key.
    ns["czech_sort_key"] = module.czech_sort_key
    fast = module._czech_collate
    assert getattr(fast, "_turto_805_direct_cached_text", False)
    samples = [None, "", " ", "A", "a", "Á", "ČEZ", "Česká firma", "H", "CH", "Ch", "I",
               "Řezáč", "Škoda", "ŽPSV", "Zruč-Senec", "  Leviat  ", "MAVI Monolity s.r.o.",
               "Akce 2", "Akce 02", "Akce 10", "Akce 000", "C-2", "C-10", "č", "c\u030c"]
    for a in samples:
        for b in samples:
            assert fast(a, b) == legacy(a, b), (a, b)
    assert fast("H", "CH") < 0 and fast("CH", "I") < 0
    assert fast("Akce 2", "Akce 10") < 0 and fast("Akce 02", "Akce 2") == 0
    for value in (None, 0, 12, 3.5, False, [], {"x": 1}):
        assert module.czech_sort_key(value) == historical_key(value)

    con = sqlite3.connect(":memory:")
    try:
        con.create_collation("OLD", legacy)
        con.create_collation("NEW", fast)
        con.execute("CREATE TABLE names(id INTEGER PRIMARY KEY, value TEXT)")
        rows = [(i, value) for i, value in enumerate(samples * 3, 1)]
        con.executemany("INSERT INTO names VALUES(?,?)", rows)
        before = list(con.execute("SELECT * FROM names ORDER BY id"))
        for indexed in (False, True):
            if indexed:
                con.execute("CREATE INDEX names_old ON names(value COLLATE OLD, id)")
                con.execute("CREATE INDEX names_new ON names(value COLLATE NEW, id)")
            for direction in ("ASC", "DESC"):
                query = "SELECT id,value FROM names ORDER BY value COLLATE {} " + direction + ",id"
                assert list(con.execute(query.format("OLD"))) == list(con.execute(query.format("NEW")))
            for value in samples:
                query = "SELECT id FROM names WHERE value COLLATE {} = ? ORDER BY id"
                assert list(con.execute(query.format("OLD"), (value,))) == list(con.execute(query.format("NEW"), (value,)))
        assert list(con.execute("SELECT * FROM names ORDER BY id")) == before
        # Same-process, alternated ORDER BY benchmark; both paths share the same cache.
        con.execute("CREATE TABLE scale_names(value TEXT)")
        scaled = [f"{samples[6 + i % 10]} {i % 200}" for i in range(3000)]
        random.Random(805).shuffle(scaled)
        con.executemany("INSERT INTO scale_names VALUES(?)", ((v,) for v in scaled))
        def run(which):
            return list(con.execute("SELECT value FROM scale_names ORDER BY value COLLATE " + which + ",rowid"))
        assert run("OLD") == run("NEW")
        timings = {"OLD": [], "NEW": []}
        for i in range(8):
            for which in (("OLD", "NEW") if i % 2 == 0 else ("NEW", "OLD")):
                start = time.perf_counter()
                run(which)
                timings[which].append((time.perf_counter() - start) * 1000)
        medians = {k: round(statistics.median(v), 4) for k, v in timings.items()}
        return {"pairs": len(samples) ** 2, "indexed_and_unindexed_equivalence": True,
                "order_by_3000_rows_median_ms": medians}
    finally:
        con.close()


class Var:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


def check_restore():
    optimization = load("idle_cleanup_804")
    cases = [
        ("User A", "User A", True), ("User A", "", True),
        ("User A", "Removed", True), ("User A", None, True),
        ("User A", "Inactive", True), ("User A", "ADMIN", True),
        ("User A", "User B", True), ("User B", "User A", True),
        ("Removed", "User A", True), ("Inactive", "", True),
        ("ADMIN", "", True), ("", "", True),
        ("ADMIN", "ADMIN", False), ("Removed", "", False),
    ]
    checked = 0
    for current, last, populated in cases:
        results = []
        for use_fast in (False, True):
            con = sqlite3.connect(":memory:")
            con.row_factory = sqlite3.Row
            con.create_collation("CZECH", lambda a, b: (a > b) - (a < b))
            con.execute("CREATE TABLE users(name TEXT,active INTEGER)")
            users = [("ADMIN", 1), ("Inactive", 0)]
            if populated:
                users += [("User A", 1), ("User B", 1)]
            con.executemany("INSERT INTO users VALUES(?,?)", users)
            con.commit()
            state = {"cfg": {"last_user": last, "other": "keep"}, "settings": {"active_user": current}, "changed": 0, "legacy_calls": 0}
            @contextmanager
            def db():
                with con:
                    yield con
            def cfg():
                return dict(state["cfg"])
            def save(**values):
                state["cfg"].update(values)
            def changed():
                state["changed"] += 1
            app = SimpleNamespace(active_user=Var(current), on_user_changed=changed)
            module = SimpleNamespace(db=db, set_setting=lambda k, v: state["settings"].__setitem__(k, v))
            ns = definitions(BASE / "crm_runtime.py", {"_restore_local_user"}, {"M": module, "_cfg": cfg, "_save_cfg": save})
            def legacy(instance):
                state["legacy_calls"] += 1
                return ns["_restore_local_user"](instance)
            runtime = SimpleNamespace(_restore_local_user=legacy, _cfg=cfg, _save_cfg=save)
            try:
                if use_fast:
                    assert optimization._install_same_user_restore_fast_path(module, runtime)
                before_sql = con.total_changes
                runtime._restore_local_user(app)
                results.append((app.active_user.get(), state["cfg"], state["settings"]))
                assert con.total_changes == before_sql, "Restore must not rewrite user/business rows"
                if use_fast:
                    skipped = getattr(app, "_turto_same_user_restore_skips_804", 0)
                    assert state["changed"] == (0 if skipped else (1 if populated else 0))
                    assert state["legacy_calls"] == (0 if skipped else 1)
                    installed = runtime._restore_local_user
                    assert optimization._install_same_user_restore_fast_path(module, runtime)
                    assert runtime._restore_local_user is installed
            finally:
                con.close()
        assert results[0] == results[1], (current, last, populated, results)
        checked += 1
    # A transient failed optimization read must delegate, not silently lose restore.
    calls = []
    def bad_cfg():
        raise OSError("unavailable client configuration")
    runtime = SimpleNamespace(_restore_local_user=lambda app: calls.append(app) or "fallback", _cfg=bad_cfg)
    assert optimization._install_same_user_restore_fast_path(SimpleNamespace(), runtime)
    app = object()
    assert runtime._restore_local_user(app) == "fallback" and calls == [app]
    return {"legacy_equivalence_cases": checked, "exception_fallback": True}


if __name__ == "__main__":
    print(json.dumps({"ok": True, "collation": check_collation(), "user_restore": check_restore()}, ensure_ascii=True, indent=2))
