#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.3 request refresh optimization."""
from __future__ import annotations

from datetime import date, timedelta
import importlib.util
from pathlib import Path
import sqlite3
import tempfile


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value


class FakeTree:
    def __init__(self):
        self.rows = {}
        self.tags = {}
        self.tag_options = {}
        self.selected = set()

    def selection(self):
        return tuple(self.selected)

    def get_children(self, parent=""):
        return tuple(self.rows)

    def delete(self, iid):
        self.rows.pop(iid, None)
        self.tags.pop(iid, None)
        self.selected.discard(iid)

    def tag_configure(self, tag, **kwargs):
        self.tag_options[tag] = dict(kwargs)

    def insert(self, parent, index, iid, values, tags=()):
        self.rows[iid] = tuple(values)
        self.tags[iid] = tuple(tags)

    def selection_add(self, iid):
        self.selected.add(iid)


class Module:
    def __init__(self, path: Path):
        self.path = path
        self.calls = {"fmt": 0, "wait": 0, "overdue": 0}

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def parse_date(self, value):
        return value

    def fmt_date(self, value):
        self.calls["fmt"] += 1
        if not value:
            return ""
        try:
            return date.fromisoformat(str(value)).strftime("%d.%m.%Y")
        except Exception:
            return str(value)

    def request_wait_date(self, asked, received=""):
        self.calls["wait"] += 1
        return self.fmt_date(asked)

    def request_is_overdue(self, asked, received=""):
        self.calls["overdue"] += 1
        if not asked or received:
            return False
        try:
            return (date.today() - date.fromisoformat(str(asked))).days >= 7
        except Exception:
            return False


class App:
    def __init__(self):
        self.request_tree = FakeTree()
        self.mivo_tree = FakeTree()
        self.after_idle_calls = 0
        self.req_status_filter = Var("")
        self.req_user_filter = Var("")
        self.req_action_filter = Var("")
        self.req_at_filter = Var("")
        self.req_date_mode = Var("Do data")
        self.req_date_filter = Var("")
        self.req_show_archived = Var(False)
        self.mivo_status_filter = Var("")
        self.mivo_user_filter = Var("")
        self.mivo_action_filter = Var("")
        self.mivo_date_mode = Var("Do data")
        self.mivo_date_filter = Var("")
        self.mivo_show_archived = Var(False)

    def after_idle(self, callback):
        self.after_idle_calls += 1
        raise AssertionError("optimized request refresh must not schedule a second highlight pass")

    def reapply_tree_sort(self, tree):
        return None


def load_worksets(repo: Path):
    path = repo / "ZakazkyApp_base_6.1" / "price_lists_domain" / "platform" / "worksets.py"
    spec = importlib.util.spec_from_file_location("turto_worksets_803_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_db(path: Path):
    today = date.today()
    old = (today - timedelta(days=10)).isoformat()
    recent = (today - timedelta(days=2)).isoformat()
    received = (today - timedelta(days=8)).isoformat()
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE companies(
            id INTEGER PRIMARY KEY,
            short_name TEXT DEFAULT '',
            official_name TEXT DEFAULT ''
        );
        CREATE TABLE actions(id INTEGER PRIMARY KEY,name TEXT DEFAULT '');
        CREATE TABLE requests(
            id INTEGER PRIMARY KEY,
            company_id INTEGER,
            requested_for_company_id INTEGER,
            action_id INTEGER,
            asked_date TEXT DEFAULT '',
            received_date TEXT DEFAULT '',
            item TEXT DEFAULT '',
            recipients_snapshot TEXT DEFAULT '',
            assigned_user TEXT DEFAULT '',
            archived INTEGER DEFAULT 0,
            no_response INTEGER DEFAULT 0
        );
        INSERT INTO companies(id,short_name,official_name) VALUES
            (1,'REG','Regular Supplier'),
            (2,'MIVO','MIVO'),
            (3,'CUS','Customer');
        INSERT INTO actions(id,name) VALUES(1,'Benchmark Action');
        """
    )
    rows = [
        (1, 1, 3, 1, old, "", "A", "a@example.invalid", "Jaroslav Kučera", 0, 0),
        (2, 1, 3, 1, old, "", "B", "b@example.invalid", "Jaroslav Kučera", 0, 0),
        (3, 1, 3, 1, recent, "", "C", "c@example.invalid", "Jaroslav Kučera", 0, 0),
        (4, 1, 3, 1, old, received, "D", "d@example.invalid", "Jaroslav Kučera", 0, 0),
        (5, 1, 3, 1, old, "", "E", "e@example.invalid", "Jaroslav Kučera", 0, 1),
        (6, 2, 3, 1, old, "", "M", "m@example.invalid", "Jaroslav Kučera", 0, 0),
        (7, 1, 3, 1, old, "", "ARCH", "x@example.invalid", "Jaroslav Kučera", 1, 0),
    ]
    con.executemany(
        """INSERT INTO requests(
               id,company_id,requested_for_company_id,action_id,asked_date,received_date,
               item,recipients_snapshot,assigned_user,archived,no_response
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    con.commit()
    con.close()
    return {"old": old, "recent": recent, "received": received}


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    worksets = load_worksets(repo)
    assert worksets.REQUEST_ATTENTION_TAG == "v770_request_attention"

    with tempfile.TemporaryDirectory(prefix="turto-803-request-") as td:
        db_path = Path(td) / "requests.db"
        build_db(db_path)
        M = Module(db_path)
        app = App()

        worksets.refresh_requests(M, app, False)
        assert set(app.request_tree.rows) == {"r1", "r2", "r3", "r4", "r5"}
        tagged = {
            iid for iid, tags in app.request_tree.tags.items()
            if worksets.REQUEST_ATTENTION_TAG in tags
        }
        assert tagged == {"r1", "r2"}, tagged
        assert app.request_tree.tag_options[worksets.REQUEST_ATTENTION_TAG]["font"] == (
            "Calibri", 10, "bold"
        )
        # All displayed request dates are clean; warning glyphs are not required
        # for the direct-tag path.
        for values in app.request_tree.rows.values():
            asked_display = str(values[2])
            assert "⚠" not in asked_display and "●" not in asked_display
        assert app.after_idle_calls == 0

        # Five visible regular rows contain only three unique asked/received pairs.
        # Date formatting is likewise bounded by the unique values rather than rows.
        assert M.calls["wait"] <= 3, M.calls
        assert M.calls["overdue"] <= 3, M.calls
        assert M.calls["fmt"] <= 5, M.calls

        overdue_before_mivo = M.calls["overdue"]
        worksets.refresh_requests(M, app, True)
        assert set(app.mivo_tree.rows) == {"r6"}
        assert all(
            worksets.REQUEST_ATTENTION_TAG not in tags
            for tags in app.mivo_tree.tags.values()
        )
        assert M.calls["overdue"] == overdue_before_mivo
        assert app.after_idle_calls == 0

    print("TURTO CRM 8.0.3 request refresh optimization: OK")


if __name__ == "__main__":
    main()
