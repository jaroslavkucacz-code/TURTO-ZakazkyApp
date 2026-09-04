#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.6 table, archive and query changes."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace


def main() -> None:
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(repository))

    import v760_table_activity_performance as layer

    # Pure helpers must preserve real date ordering even though the visible value
    # is formatted for Czech users.
    assert layer._parse_activity_datetime("01.09.2026 18:30")
    assert layer._parse_activity_datetime("2026-09-01 19:30:00")
    assert layer._parse_activity_datetime("—") is None

    class SymbolicDisplayFallbackTree:
        def __init__(self):
            self.columns = ("Název Akce", layer.LAST_ACTIVITY_COLUMN)
            self.displaycolumns = ("Název Akce",)
            self.tk = SimpleNamespace(splitlist=lambda value: tuple(value))
            self.symbolic_attempts = 0

        def cget(self, option):
            return self.columns if option == "columns" else self.displaycolumns

        def configure(self, *args, **kwargs):
            display = kwargs.get("displaycolumns")
            if display is None:
                return None
            values = (display,) if isinstance(display, str) else tuple(display)
            if any(str(value) == layer.LAST_ACTIVITY_COLUMN for value in values):
                self.symbolic_attempts += 1
                raise RuntimeError('Invalid column index "Poslední pohyb"')
            self.displaycolumns = values
            return None

    fallback_tree = SymbolicDisplayFallbackTree()
    assert layer._set_displayed_columns(
        fallback_tree, ["Název Akce", layer.LAST_ACTIVITY_COLUMN]
    )
    assert fallback_tree.symbolic_attempts == 1
    assert fallback_tree.displaycolumns == ("#all",), fallback_tree.displaycolumns

    class DummyTree:
        _turto_v760_table_polish_class = True

        def __init__(self, *args, **kwargs):
            return None

        def heading(self, *args, **kwargs):
            return None

        def column(self, *args, **kwargs):
            return "w"

        def configure(self, *args, **kwargs):
            return None

        config = configure

        def xview(self, *args, **kwargs):
            return (0.0, 1.0)

    class StubApp:
        def action_rows(self):
            return []

        def sort_tree(self, *_args, **_kwargs):
            return None

        def refresh_projects(self):
            return None

        def build_projects(self):
            return None

        def refresh_tasks(self):
            return None

        def build_tasks(self):
            return None

        def refresh_requests(self):
            return None

        def refresh_mivo_requests(self):
            return None

        def refresh_dash(self):
            return None

        def refresh_header(self):
            return None

        def build(self):
            return None

        def apply_theme(self):
            return None

        def edit_project(self):
            return None

        def merge_project(self):
            return None

        def edit_task(self):
            return None

        def complete_task(self):
            return None

        def complete_task_by_id(self, _task_id):
            return None

        def notification_count(self):
            return 0

    class Module:
        App = StubApp
        ttk = SimpleNamespace(Treeview=DummyTree)
        tk = SimpleNamespace()

        def __init__(self, root: pathlib.Path):
            self.DB = root / "test.db"
            self.messagebox = SimpleNamespace(
                showinfo=lambda *_a, **_k: None,
                askyesno=lambda *_a, **_k: True,
            )

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            return con

        def ensure_schema(self):
            with self.db() as con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS projects(
                      id INTEGER PRIMARY KEY,
                      name TEXT,
                      address TEXT DEFAULT '',
                      investor TEXT DEFAULT '',
                      general_contractor TEXT DEFAULT '',
                      start_date TEXT DEFAULT '',
                      end_date TEXT DEFAULT '',
                      active INTEGER DEFAULT 1,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      created_by TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS actions(
                      id INTEGER PRIMARY KEY,
                      name TEXT,
                      project_id INTEGER,
                      company_id INTEGER,
                      salesperson_id INTEGER,
                      status TEXT DEFAULT 'Rozpracováno',
                      updated_at TEXT DEFAULT '',
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      created_date TEXT DEFAULT '',
                      archived INTEGER DEFAULT 0,
                      deadline TEXT DEFAULT '',
                      note TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS requests(
                      id INTEGER PRIMARY KEY,
                      action_id INTEGER,
                      company_id INTEGER,
                      received_date TEXT DEFAULT '',
                      asked_date TEXT DEFAULT '',
                      updated_at TEXT DEFAULT '',
                      archived INTEGER DEFAULT 0,
                      no_response INTEGER DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS tasks(
                      id INTEGER PRIMARY KEY,
                      action_id INTEGER,
                      due_date TEXT,
                      text TEXT,
                      note TEXT DEFAULT '',
                      done INTEGER DEFAULT 0,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      created_by TEXT DEFAULT '',
                      done_at TEXT DEFAULT '',
                      done_by TEXT DEFAULT '',
                      assigned_user TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS action_history(
                      id INTEGER PRIMARY KEY,
                      action_id INTEGER,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      event_type TEXT,
                      summary TEXT,
                      details TEXT,
                      user_name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS companies(
                      id INTEGER PRIMARY KEY,
                      official_name TEXT,
                      short_name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS salespeople(
                      id INTEGER PRIMARY KEY,
                      name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS supplier_offers(
                      id INTEGER PRIMARY KEY,
                      action_id INTEGER,
                      offer_date TEXT,
                      updated_at TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS business_documents(
                      id INTEGER PRIMARY KEY,
                      project_id INTEGER,
                      action_id INTEGER,
                      updated_at TEXT DEFAULT '',
                      sent_at TEXT DEFAULT '',
                      accepted_at TEXT DEFAULT '',
                      rejected_at TEXT DEFAULT '',
                      created_at TEXT DEFAULT '',
                      issue_date TEXT DEFAULT ''
                    );
                    """
                )

        @staticmethod
        def get_setting(_key, default=""):
            return default

        @staticmethod
        def fmt_date(value):
            return str(value or "")

        @staticmethod
        def log_history(*_args, **_kwargs):
            return None

    with tempfile.TemporaryDirectory(prefix="turto7600_") as temp:
        module = Module(pathlib.Path(temp))
        module.ensure_schema()
        layer.apply(module)
        module.ensure_schema()

        with module.db() as con:
            project_columns = {
                row[1] for row in con.execute("PRAGMA table_info(projects)")
            }
            task_columns = {
                row[1] for row in con.execute("PRAGMA table_info(tasks)")
            }
            assert {"updated_at", "archived_at", "archived_by"} <= project_columns
            assert {"updated_at", "archived", "archived_at", "archived_by"} <= task_columns

            con.execute(
                "INSERT INTO projects(id,name,active,updated_at,created_at) VALUES(1,'Akce A',1,'2026-01-01 08:00:00','2026-01-01 08:00:00')"
            )
            con.execute(
                "INSERT INTO projects(id,name,active,updated_at,created_at) VALUES(2,'Akce B',1,'2026-01-01 08:00:00','2026-01-01 08:00:00')"
            )
            con.execute(
                """INSERT INTO actions(
                       id,name,project_id,company_id,status,updated_at,created_at,created_date,archived
                   ) VALUES(1,'Akce A',1,1,'Rozpracováno','2026-02-01 09:00:00','2026-01-02 08:00:00','2026-01-02',0)"""
            )
            con.execute(
                """INSERT INTO actions(
                       id,name,project_id,company_id,status,updated_at,created_at,created_date,archived
                   ) VALUES(2,'Akce B',2,1,'Rozpracováno','2026-02-01 09:00:00','2026-01-02 08:00:00','2026-01-02',1)"""
            )
            con.execute(
                "INSERT INTO companies(id,official_name,short_name) VALUES(1,'Dodavatel A','Dodavatel A')"
            )
            con.execute(
                "INSERT INTO companies(id,official_name,short_name) VALUES(2,'MIVO','MIVO')"
            )
            request_rows = (
                (1, 1, 1, '', '2026-03-01', '', 0, 0),
                (2, 1, 1, '2026-03-02', '2026-03-01', '', 0, 0),
                (3, 1, 1, '', '2026-03-01', '', 1, 0),
                (4, 1, 2, '', '2026-03-01', '', 0, 0),
            )
            con.executemany(
                """INSERT INTO requests(
                       id,action_id,company_id,received_date,asked_date,updated_at,archived,no_response
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                request_rows,
            )
            con.execute(
                "INSERT INTO action_history(id,action_id,created_at) VALUES(1,1,'2026-04-01 10:00:00')"
            )
            con.execute(
                """INSERT INTO tasks(
                       id,action_id,due_date,text,done,created_at,done_at,assigned_user
                   ) VALUES(1,1,'2026-09-02','Úkol',1,'2026-03-01 08:00:00','2026-05-01 11:00:00','TEST')"""
            )
            con.execute(
                "INSERT INTO supplier_offers(id,action_id,offer_date,updated_at) VALUES(1,1,'2026-06-01','2026-06-02 08:00:00')"
            )
            con.execute(
                """INSERT INTO business_documents(
                       id,project_id,action_id,updated_at,sent_at,created_at,issue_date
                   ) VALUES(1,1,1,'2026-06-01 08:00:00','2026-07-01 12:30:00',
                            '2026-05-01 08:00:00','2026-05-01')"""
            )

            union = layer._project_activity_union(con)
            latest = con.execute(
                f"""WITH activity(project_id,activity_at) AS ({union})
                    SELECT MAX(activity_at) FROM activity WHERE project_id=1"""
            ).fetchone()[0]
            assert latest == "2026-07-01 12:30:00", latest

            indexes = {
                row[1]
                for row in con.execute(
                    "SELECT type,name FROM sqlite_master WHERE type='index'"
                )
            }
            assert {
                "idx_v760_actions_project_archived_updated",
                "idx_v760_requests_action_archived_dates",
                "idx_v760_tasks_action_archived_due",
                "idx_v760_projects_active_updated",
            } <= indexes

        app = StubApp()
        rows = app.action_rows()
        by_id = {int(row["id"]): row for row in rows}
        assert int(by_id[1]["waiting"]) == 1
        assert 2 in by_id
        app._v760_action_rows_active_only = True
        active_rows = app.action_rows()
        assert [int(row["id"]) for row in active_rows] == [1]

    layer_text = (source / "v760_table_activity_performance.py").read_text(
        encoding="utf-8"
    )
    for token in (
        'LAST_ACTIVITY_COLUMN = "Poslední pohyb"',
        "sync_heading_anchors",
        "_set_displayed_columns",
        "_v760_separator_widgets",
        "promote_accent_button",
        'order.insert(people_index + 1, "companies")',
        "project_show_archived",
        "task_show_archived",
        "single_union_query",
        "grouped_cte",
        "request_resize_refresh",
        "notification_counts",
    ):
        assert token in layer_text, token

    app_text = (source / "app.py").read_text(encoding="utf-8")
    project_start = app_text.index("    def build_projects(self):\n")
    project_end = app_text.index("\n    def build_people(self):\n", project_start)
    project_block = app_text[project_start:project_end]
    assert "widths=(300,300,220,220,100,100,90,150)" in project_block
    assert '"Příležitostí","Poslední pohyb"' in project_block

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert "v760_table_activity_performance" in launcher
    assert launcher.index("v750_context_filters_offer_format.apply(app)") < launcher.index(
        "v760_table_activity_performance.apply(app)"
    )
    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    assert version in {"7.6.1", "7.6.2", "7.6.3", "7.6.4", "7.6.5", "7.6.6", "7.6.7", "7.6.8", "7.6.9"}, version
    publish = (repository / "scripts" / "publish-update.sh").read_text(encoding="utf-8")
    assert "validate-7600-table-activity-performance.py" in publish
    assert "v760_table_activity_performance.py" in publish
    real_ui = (repository / "scripts" / "validate-real-ui.py").read_text(encoding="utf-8")
    assert "v760_table_activity_performance.apply(app)" in real_ui
    print(
        "OK 7.6.x: Akce opens with a canonical last-activity column, "
        "legacy layouts use a safe full-view fallback and all 7.6 contracts remain valid"
    )


if __name__ == "__main__":
    main()
