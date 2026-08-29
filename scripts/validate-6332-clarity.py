#!/usr/bin/env python3
"""Regression checks for TURTO CRM 6.3.32 price-list clarity and MIVO ageing."""
from __future__ import annotations

import contextlib
import inspect
import pathlib
import sqlite3
import sys
from datetime import date, timedelta
from types import SimpleNamespace


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Button:
    def __init__(self):
        self.states = []

    def state(self, values):
        self.states = list(values)


class Tree:
    def __init__(self, columns=()):
        self.columns = list(columns)
        self.rows = {}
        self.tag_options = {}

    def __getitem__(self, key):
        if key == "columns":
            return tuple(self.columns)
        raise KeyError(key)

    def cget(self, key):
        return self[key]

    def configure(self, **kwargs):
        if "columns" in kwargs:
            self.columns = list(kwargs["columns"])

    config = configure

    def heading(self, *_args, **_kwargs):
        return None

    def column(self, *_args, **_kwargs):
        return None

    def tag_configure(self, name, **kwargs):
        self.tag_options[name] = dict(kwargs)

    def get_children(self, _parent=""):
        return tuple(self.rows)

    def delete(self, iid):
        self.rows.pop(iid, None)

    def insert(self, _parent, _index, iid, values=(), tags=()):
        self.rows[iid] = {"values": tuple(values), "tags": tuple(tags)}
        return iid

    def exists(self, iid):
        return iid in self.rows

    def item(self, iid, option=None, **kwargs):
        row = self.rows[iid]
        if "values" in kwargs:
            row["values"] = tuple(kwargs["values"])
        if "tags" in kwargs:
            row["tags"] = tuple(kwargs["tags"])
        if option:
            return row[option]
        return dict(row)

    def set(self, iid, column, value=None):
        index = self.columns.index(column)
        values = list(self.rows[iid]["values"])
        if value is None:
            return values[index]
        while len(values) <= index:
            values.append("")
        values[index] = value
        self.rows[iid]["values"] = tuple(values)


class Module:
    sqlite3 = sqlite3

    def __init__(self, connection):
        self.connection = connection

    def db(self):
        return contextlib.nullcontext(self.connection)

    @staticmethod
    def fmt_date(value):
        return str(value or "")

    @staticmethod
    def fmt_history_datetime(value):
        return str(value or "")


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(source))

    from price_lists_domain.platform import clarity

    signature = tuple(inspect.signature(clarity._refresh_evidence).parameters)
    assert signature == ("M", "app"), signature

    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE companies(
            id INTEGER PRIMARY KEY,
            official_name TEXT,
            short_name TEXT
        );
        CREATE TABLE product_categories(
            id INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE price_lists(
            id INTEGER PRIMARY KEY,
            supplier_company_id INTEGER,
            supplier_name TEXT,
            category_id INTEGER,
            title TEXT,
            valid_from TEXT,
            valid_to TEXT,
            product_group TEXT,
            branch TEXT,
            update_mode TEXT,
            archived INTEGER DEFAULT 0,
            source_filename TEXT,
            imported_at TEXT,
            parse_status TEXT
        );
        CREATE TABLE price_list_items(
            id INTEGER PRIMARY KEY,
            price_list_id INTEGER,
            category_id INTEGER,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE requests(
            id INTEGER PRIMARY KEY,
            asked_date TEXT,
            received_date TEXT,
            no_response INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0
        );
        """
    )
    today = date.today()
    connection.execute("INSERT INTO companies(id,official_name) VALUES(1,'PohlCon Česká republika s.r.o.')")
    connection.execute("INSERT INTO product_categories(id,name) VALUES(1,'PVC pásy (Kunex)')")
    connection.execute(
        """INSERT INTO price_lists(
               id,supplier_company_id,category_id,title,valid_from,valid_to,product_group,
               branch,update_mode,archived,source_filename,imported_at,parse_status
           ) VALUES(1,1,1,'Ceník Kunex',?,?,?,?,?,0,'kunex.pdf','2026-08-29 10:00:00','Připraveno')""",
        (
            (today - timedelta(days=40)).isoformat(),
            (today + timedelta(days=12)).isoformat(),
            "Kunex",
            "Česká republika",
            "partial",
        ),
    )
    connection.execute("INSERT INTO price_list_items(id,price_list_id,category_id,active) VALUES(1,1,1,1)")
    connection.execute(
        "INSERT INTO requests(id,asked_date,received_date,no_response,archived) VALUES(7,?,?,0,0)",
        ((today - timedelta(days=10)).isoformat(), ""),
    )
    connection.commit()
    module = Module(connection)

    evidence_columns = (
        "Stav", "Platí od", "Platí do", "Dodavatel", "Kategorie", "Název",
        "Skupina", "Větev", "Režim", "Položek", "Soubor", "Import", "Platnost",
    )
    evidence_tree = Tree(evidence_columns)
    evidence_app = SimpleNamespace(
        price_list_evidence_tree=evidence_tree,
        price_evidence_status=Var("Všechny"),
        price_list_show_archived=Var(False),
        price_evidence_q=Var(""),
        price_evidence_supplier=Var(""),
        price_evidence_category=Var("Všechny"),
        price_evidence_page=0,
        price_evidence_page_size=300,
        price_evidence_status_text=Var(""),
        price_evidence_prev=Button(),
        price_evidence_next=Button(),
    )
    clarity._refresh_evidence(module, evidence_app)
    assert tuple(evidence_tree.rows) == ("pl1",), evidence_tree.rows
    evidence_row = evidence_tree.rows["pl1"]
    assert len(evidence_row["values"]) == len(evidence_columns), evidence_row
    assert evidence_row["values"][-1].startswith("končí za 12"), evidence_row["values"][-1]
    assert "price_expiring" in evidence_row["tags"], evidence_row["tags"]

    evidence_app.price_evidence_status.set("Končí do 30 dnů")
    clarity._refresh_evidence(module, evidence_app)
    assert tuple(evidence_tree.rows) == ("pl1",), evidence_tree.rows
    assert "filtr: Končí do 30 dnů" in evidence_app.price_evidence_status_text.get()

    mivo_tree = Tree(("Stav", "Řeší", "Poptáno"))
    mivo_tree.insert("", "end", iid="r7", values=("Čekám", "", (today - timedelta(days=10)).isoformat()), tags=("req_fresh",))
    mivo_app = SimpleNamespace(mivo_tree=mivo_tree, mivo_age_summary=Var(""))
    clarity._apply_mivo_ageing(module, mivo_app)
    assert "mivo_wait_7" in mivo_tree.item("r7", "tags"), mivo_tree.item("r7", "tags")
    assert "7+ dní: 1" in mivo_app.mivo_age_summary.get(), mivo_app.mivo_age_summary.get()

    connection.execute("UPDATE requests SET received_date=? WHERE id=7", (today.isoformat(),))
    connection.commit()
    clarity._apply_mivo_ageing(module, mivo_app)
    assert "mivo_wait_7" not in mivo_tree.item("r7", "tags"), mivo_tree.item("r7", "tags")

    platform_text = (source / "price_lists_domain" / "platform" / "__init__.py").read_text(encoding="utf-8")
    assert "install_clarity(module)" in platform_text
    assert platform_text.index("install_compat(module)") < platform_text.index("install_clarity(module)")
    assert platform_text.index("install_clarity(module)") < platform_text.index("install_lazy_refresh(module)")

    print("TURTO CRM 6.3.32 MIVO and price-list clarity regression test: OK")


if __name__ == "__main__":
    main()
