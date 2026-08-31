#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.0 workflow and table UX."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
REPOSITORY = ROOT.parent
sys.path.insert(0, str(ROOT))

from v700_ux import group_offer_items  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def functional_request_checks() -> None:
    """Exercise the patched methods against an isolated real SQLite schema."""
    home = Path(tempfile.mkdtemp(prefix="turto7000_requests_"))
    original_home = os.environ.get("HOME")
    original_profile = os.environ.get("USERPROFILE")
    original_cwd = Path.cwd()
    try:
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"
        os.chdir(ROOT)

        import app
        import v700_ux

        app.cleanup_stale_test_session()
        app.ensure_schema()
        v700_ux.apply(app)
        app.ensure_schema()
        app.set_setting("active_user", "TEST")

        with app.db() as con:
            supplier_id = int(con.execute(
                "INSERT INTO companies(short_name,official_name,active) VALUES(?,?,1)",
                ("DODAVATEL 7", "DODAVATEL 7"),
            ).lastrowid)
            customer_id = int(con.execute(
                "INSERT INTO companies(short_name,official_name,active) VALUES(?,?,1)",
                ("ODBĚRATEL 7", "ODBĚRATEL 7"),
            ).lastrowid)
            action_a = int(con.execute(
                "INSERT INTO actions(name,company_id,status) VALUES(?,?,'Rozpracováno')",
                ("AKCE 7 A", customer_id),
            ).lastrowid)
            action_b = int(con.execute(
                "INSERT INTO actions(name,company_id,status) VALUES(?,?,'Rozpracováno')",
                ("AKCE 7 B", customer_id),
            ).lastrowid)
            request_a1 = int(con.execute(
                """INSERT INTO requests(
                       company_id,requested_for_company_id,action_id,asked_date,item,archived
                   ) VALUES(?,?,?,?,?,0)""",
                (supplier_id, customer_id, action_a, "2026-08-01", "Stejný materiál"),
            ).lastrowid)
            request_a2 = int(con.execute(
                """INSERT INTO requests(
                       company_id,requested_for_company_id,action_id,asked_date,item,archived
                   ) VALUES(?,?,?,?,?,0)""",
                (supplier_id, customer_id, action_a, "2026-08-02", "Jiný materiál"),
            ).lastrowid)
            request_b = int(con.execute(
                """INSERT INTO requests(
                       company_id,requested_for_company_id,action_id,asked_date,item,archived
                   ) VALUES(?,?,?,?,?,0)""",
                (supplier_id, customer_id, action_b, "2026-08-03", "Stejný materiál"),
            ).lastrowid)

        class HistoryTree:
            def __init__(self):
                self.rows = {}

            def get_children(self, _parent=""):
                return tuple(self.rows)

            def delete(self, *iids):
                for iid in iids:
                    self.rows.pop(iid, None)

            def insert(self, _parent, _position, iid=None, values=(), **_kwargs):
                self.rows[str(iid)] = tuple(values)

        class RequestLike:
            rid = None

            def __init__(self):
                self.history_tree = HistoryTree()

            @staticmethod
            def action_id():
                return action_a

        request_like = RequestLike()
        app.RequestDialog.refresh_similar(request_like)
        shown_ids = {int(iid[1:]) for iid in request_like.history_tree.rows}
        assert shown_ids == {request_a1, request_a2}, shown_ids
        assert request_b not in shown_ids

        class SelectionTree:
            @staticmethod
            def selection():
                return (f"r{request_a1}", f"r{request_a2}")

        class Flag:
            def __init__(self):
                self.value = None

            def set(self, value):
                self.value = value

        class AppLike:
            request_tree = SelectionTree()
            req_show_archived = Flag()
            master = None

            def __init__(self):
                self.refreshed = 0

            def refresh_after_request_change(self):
                self.refreshed += 1

        original_ask = app.messagebox.askyesno
        original_info = app.messagebox.showinfo
        app.messagebox.askyesno = lambda *_args, **_kwargs: True
        app.messagebox.showinfo = lambda *_args, **_kwargs: None
        try:
            fake_app = AppLike()
            app.App.archive_request(fake_app)
        finally:
            app.messagebox.askyesno = original_ask
            app.messagebox.showinfo = original_info

        with app.db() as con:
            archived = {
                int(row["id"]): int(row["archived"] or 0)
                for row in con.execute(
                    "SELECT id,archived FROM requests WHERE id IN (?,?,?)",
                    (request_a1, request_a2, request_b),
                ).fetchall()
            }
            history_count = int(con.execute(
                """SELECT COUNT(*) FROM action_history
                   WHERE event_type='request_archive' AND related_request_id IN (?,?)""",
                (request_a1, request_a2),
            ).fetchone()[0])
        assert archived == {request_a1: 1, request_a2: 1, request_b: 0}, archived
        assert history_count == 2, history_count
        assert fake_app.refreshed == 1
        assert fake_app.req_show_archived.value is False
    finally:
        os.chdir(original_cwd)
        if original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = original_home
        if original_profile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = original_profile
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    layer = read(ROOT / "v700_ux.py")
    request_section = layer.split("def request_refresh_similar", 1)[1].split(
        "def selected_request_ids", 1
    )[0]
    assert "WHERE r.action_id=?" in request_section
    assert "lower(r.item)" not in request_section
    assert "if not action_id" in request_section

    archive_section = layer.split("def archive_requests", 1)[1].split(
        "# ------------------------------------------------------------------\n    # Opportunity", 1
    )[0]
    assert "tree.selection()" in layer
    assert "WHERE r.id IN ({marks})" in archive_section
    assert "Archivovat označené poptávky" in archive_section
    assert "refresh_after_request_change" in archive_section

    assert "takefocus=False" in layer
    assert "auxiliary_prefixes" in layer
    assert '"<Tab>"' in layer and '"<Shift-Tab>"' in layer
    assert 'text="+ Nová akce"' in layer
    assert "_v700_action_wrapper" in layer

    assert "tree_layout_v700_" in layer
    assert "save_layout" in layer
    assert "displaycolumns" in layer
    assert "stretch=bool(column == last" in layer
    assert "Nastavit zobrazené sloupce" in layer
    assert "Zobrazit / skrýt" in layer
    assert "is_commercial_tree" in layer

    assert '"Skupina", "Podskupina"' in layer
    assert "category_name_snapshot" in layer
    assert "subgroup_name_snapshot" in layer
    assert "grouped_pdf_items" in layer

    rows = [
        {
            "row_type": "product",
            "name": "A1",
            "category_name_snapshot": "Skupina A",
            "subgroup_name_snapshot": "Podskupina 1",
        },
        {"row_type": "text", "description": "Poznámka"},
        {
            "row_type": "product",
            "name": "B1",
            "category_name_snapshot": "Skupina B",
            "subgroup_name_snapshot": "Podskupina 2",
        },
        {
            "row_type": "product",
            "name": "A2",
            "category_name_snapshot": "Skupina A",
            "subgroup_name_snapshot": "Podskupina 1",
        },
        {"row_type": "service", "name": "Doprava"},
    ]
    plan = group_offer_items(rows)
    headings = [token["label"] for token in plan if token["kind"] == "group"]
    assert headings == ["Skupina A › Podskupina 1", "Skupina B › Podskupina 2"]
    assert headings.count("Skupina A › Podskupina 1") == 1
    item_indices = [token["index"] for token in plan if token["kind"] == "item"]
    assert item_indices == [0, 3, 1, 2, 4], item_indices

    schema = read(ROOT / "price_lists_domain" / "issued_offers" / "schema.py")
    assert '"category_name_snapshot TEXT DEFAULT \'\'"' in schema
    assert '"subgroup_name_snapshot TEXT DEFAULT \'\'"' in schema

    launcher = read(ROOT / "ZakazkyCRM.pyw")
    assert "import v700_ux" in launcher or ",v700_ux" in launcher
    assert "v700_ux.apply(app)" in launcher

    publish = read(REPOSITORY / "scripts" / "publish-update.sh")
    assert "v700_ux.py" in publish
    assert "v700_ux.apply(app)" in publish
    assert "validate-7000-workflow-table-ux.py" in publish

    real_ui = read(REPOSITORY / "scripts" / "validate-real-ui.py")
    assert "import v700_ux" in real_ui
    assert "v700_ux.apply(app)" in real_ui

    version = read(REPOSITORY / "release_version.txt").strip()
    assert version == "7.0.0", version

    functional_request_checks()
    print("OK 7.0.0: request workflow, persistent columns and grouped issued offers")


if __name__ == "__main__":
    main()
