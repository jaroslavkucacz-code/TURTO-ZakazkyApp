#!/usr/bin/env python3
"""Regression checks for TURTO CRM 6.3.36 commercial workspaces."""
from __future__ import annotations

import contextlib
import pathlib
import sqlite3
import sys
import tempfile
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


class Box:
    def __init__(self):
        self.values = []

    def set_values(self, values):
        self.values = list(values)

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.values = list(kwargs["values"])


class Label:
    def __init__(self):
        self.text = ""

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)


class Tree:
    def __init__(self, columns=()):
        self.columns = tuple(columns)
        self.rows = {}
        self.selection_value = ()

    def __getitem__(self, key):
        if key == "columns":
            return self.columns
        raise KeyError(key)

    def get_children(self, _parent=""):
        return tuple(self.rows)

    def delete(self, iid):
        self.rows.pop(iid, None)

    def insert(self, _parent, _index, iid, values=(), tags=()):
        self.rows[iid] = {"values": tuple(values), "tags": tuple(tags)}
        return iid

    def selection(self):
        return self.selection_value


class Module:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False

    def __init__(self, path):
        self.path = path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation("CZECH", lambda a, b: (str(a or "") > str(b or "")) - (str(a or "") < str(b or "")))
        return con

    @staticmethod
    def fmt_date(value):
        return str(value or "")

    @staticmethod
    def fmt_history_datetime(value):
        return str(value or "")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(root))

    from price_lists_domain.platform import commercial_workspace as workspace
    from price_lists_domain.platform import database

    text = (root / "price_lists_domain/platform/commercial_workspace.py").read_text(encoding="utf-8")
    for needle in (
        "single final presentation owner", "Detail vybrané ceny", "Detail nabídky",
        "Pracovní pohled", "Cenový základ", "Nezařazených cen", "Bez zařazení produktů",
        "M.App.build_price_lists = app_build_price_lists", "M.App.build_offers = app_build_offers",
    ):
        assert needle in text, needle
    assert "old_build" not in text and "old_refresh" not in text

    platform_text = (root / "price_lists_domain/platform/__init__.py").read_text(encoding="utf-8")
    assert "install_commercial_workspace(module)" in platform_text
    assert platform_text.index("install_clarity(module)") < platform_text.index("install_commercial_workspace(module)")
    assert platform_text.index("install_commercial_workspace(module)") < platform_text.index("install_lazy_refresh(module)")

    with tempfile.TemporaryDirectory() as temp_dir:
        path = pathlib.Path(temp_dir) / "commercial.db"
        module = Module(path)
        with module.db() as con:
            con.executescript(
                """
                CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT DEFAULT '');
                CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT DEFAULT '',short_name TEXT DEFAULT '',active INTEGER DEFAULT 1);
                CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT DEFAULT '',active INTEGER DEFAULT 1,end_date TEXT DEFAULT '');
                CREATE TABLE actions(id INTEGER PRIMARY KEY,name TEXT DEFAULT '',project_id INTEGER,status TEXT DEFAULT '',created_date TEXT DEFAULT '',deadline TEXT DEFAULT '',updated_at TEXT DEFAULT '');
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,done INTEGER DEFAULT 0,due_date TEXT DEFAULT '',done_at TEXT DEFAULT '');
                CREATE TABLE requests(id INTEGER PRIMARY KEY,action_id INTEGER,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,received_date TEXT DEFAULT '',asked_date TEXT DEFAULT '');
                CREATE TABLE supplier_offers(
                    id INTEGER PRIMARY KEY,offer_date TEXT DEFAULT '',supplier_company_id INTEGER,supplier_name TEXT DEFAULT '',
                    request_id INTEGER,project_id INTEGER,action_id INTEGER,offer_number TEXT DEFAULT '',reference TEXT DEFAULT '',
                    note TEXT DEFAULT '',total_value REAL DEFAULT 0,currency TEXT DEFAULT 'CZK',status TEXT DEFAULT '',archived INTEGER DEFAULT 0
                );
                CREATE TABLE supplier_offer_items(
                    id INTEGER PRIMARY KEY,offer_id INTEGER,product_code TEXT DEFAULT '',item_key TEXT DEFAULT '',
                    original_name TEXT DEFAULT '',details TEXT DEFAULT '',category_id INTEGER,subgroup_id INTEGER,catalog_product_id INTEGER
                );
                CREATE TABLE price_lists(
                    id INTEGER PRIMARY KEY,source_offer_id INTEGER,supplier_company_id INTEGER,supplier_name TEXT DEFAULT '',
                    title TEXT DEFAULT '',valid_from TEXT DEFAULT '',valid_to TEXT DEFAULT '',product_group TEXT DEFAULT '',branch TEXT DEFAULT '',
                    update_mode TEXT DEFAULT 'partial',supersedes_id INTEGER,archived INTEGER DEFAULT 0,source_filename TEXT DEFAULT '',
                    archive_path TEXT DEFAULT '',imported_at TEXT DEFAULT '',parse_status TEXT DEFAULT '',note TEXT DEFAULT '',terms_text TEXT DEFAULT '',category_id INTEGER
                );
                CREATE TABLE price_list_items(
                    id INTEGER PRIMARY KEY,price_list_id INTEGER,active INTEGER DEFAULT 1,product_code TEXT DEFAULT '',supplier_item_code TEXT DEFAULT '',
                    item_key TEXT DEFAULT '',name TEXT DEFAULT '',description TEXT DEFAULT '',unit TEXT DEFAULT '',source_price REAL DEFAULT 0,
                    currency TEXT DEFAULT 'CZK',price_basis_qty REAL DEFAULT 1,normalized_unit_price REAL DEFAULT 0,discount_pct REAL DEFAULT 0,
                    surcharge_pct REAL DEFAULT 0,weight_unit REAL DEFAULT 0,minimum_qty REAL DEFAULT 0,package_qty REAL DEFAULT 0,
                    package_unit TEXT DEFAULT '',pallet_qty REAL DEFAULT 0,dimensions TEXT DEFAULT '',condition_text TEXT DEFAULT '',gtin TEXT DEFAULT '',
                    customs_code TEXT DEFAULT '',category_id INTEGER,subgroup_id INTEGER,catalog_product_id INTEGER
                );
                """
            )
        database.ensure_platform_schema(module)
        today = date.today()
        with module.db() as con:
            group_id = con.execute(
                "SELECT id FROM product_categories WHERE name='AKUSTICKÁ IZOLACE SCHODIŠŤ'"
            ).fetchone()[0]
            subgroup_id = con.execute(
                "SELECT id FROM product_subgroups WHERE category_id=? ORDER BY sort_order,id LIMIT 1", (group_id,)
            ).fetchone()[0]
            con.execute("UPDATE product_categories SET default_margin_pct=25,default_discount_pct=10 WHERE id=?", (group_id,))
            con.execute("UPDATE product_subgroups SET default_margin_pct=25,default_discount_pct=10 WHERE id=?", (subgroup_id,))
            con.execute("INSERT INTO companies(id,official_name,active) VALUES(1,'Leviat s.r.o.',1)")
            product_id = con.execute(
                """INSERT INTO catalog_products(manufacturer_name,internal_code,internal_name,category_id,subgroup_id,active)
                   VALUES('Leviat','T-001','HBB V-Box',?,?,1)""", (group_id, subgroup_id)
            ).lastrowid
            con.execute(
                """INSERT INTO price_lists(id,supplier_company_id,supplier_name,title,valid_from,valid_to,product_group,branch,
                   update_mode,archived,source_filename,imported_at,parse_status,category_id)
                   VALUES(1,1,'Leviat','Ceník 2026',?,?,'Akustika','CZ','partial',0,'cenik.pdf','2026-08-29 10:00:00','Připraveno',?)""",
                ((today - timedelta(days=20)).isoformat(), (today + timedelta(days=10)).isoformat(), group_id),
            )
            con.execute(
                """INSERT INTO price_list_items(
                   id,price_list_id,active,product_code,item_key,name,unit,source_price,currency,price_basis_qty,
                   normalized_unit_price,weight_unit,minimum_qty,package_qty,package_unit,dimensions,category_id,subgroup_id,catalog_product_id
                   ) VALUES(1,1,1,'1000204611','1000204611','HALFEN HBB V-Box','ks',100,'CZK',1,100,5,10,1,'ks','161x254x151',?,?,?)""",
                (group_id, subgroup_id, product_id),
            )
            con.execute(
                """INSERT INTO price_lists(id,supplier_company_id,supplier_name,title,valid_from,valid_to,product_group,branch,
                   update_mode,archived,source_filename,imported_at,parse_status,category_id)
                   VALUES(2,1,'Leviat','OCR ke kontrole',?,?,'Akustika','CZ','partial',0,'ocr.pdf','2026-08-29 11:00:00','OCR – ke kontrole',NULL)""",
                ((today - timedelta(days=5)).isoformat(), (today + timedelta(days=20)).isoformat()),
            )
            con.execute(
                """INSERT INTO price_list_items(
                   id,price_list_id,active,product_code,item_key,name,unit,source_price,currency,price_basis_qty,
                   normalized_unit_price,category_id,subgroup_id,catalog_product_id
                   ) VALUES(2,2,1,'OCR-1','OCR-1','Neověřená OCR cena','ks',999,'CZK',1,999,NULL,NULL,NULL)"""
            )
            con.execute("INSERT INTO projects(id,name,active) VALUES(1,'BD Test',1)")
            con.execute(
                """INSERT INTO supplier_offers(id,offer_date,supplier_company_id,supplier_name,project_id,action_id,
                   offer_number,reference,total_value,currency,status,archived)
                   VALUES(1,?,1,'Leviat',1,NULL,'10363193','Ceník 2026',1000,'CZK','Přijato',0)""",
                (today.isoformat(),),
            )
            con.execute(
                """INSERT INTO supplier_offer_items(id,offer_id,product_code,item_key,original_name,category_id,subgroup_id,catalog_product_id)
                   VALUES(1,1,'1000204611','1000204611','HALFEN HBB V-Box',?,?,?)""",
                (group_id, subgroup_id, product_id),
            )
            con.execute(
                """INSERT INTO supplier_offers(id,offer_date,supplier_company_id,supplier_name,offer_number,total_value,currency,status,archived)
                   VALUES(2,?,1,'Leviat','UNLINKED',500,'CZK','Přijato',0)""",
                (today.isoformat(),),
            )
            con.execute(
                "INSERT INTO supplier_offer_items(id,offer_id,product_code,item_key,original_name) VALUES(2,2,'X','X','Nezařazený produkt')"
            )
            con.commit()

        price_summary = workspace._price_summary_values(module)
        assert price_summary["items"] == 1, price_summary
        assert price_summary["active"] == 1, price_summary
        assert price_summary["review"] == 1, price_summary
        assert price_summary["expiring"] == 1, price_summary

        offer_summary = workspace._offer_summary_values(module)
        assert offer_summary["active"] == 2, offer_summary
        assert offer_summary["unassigned"] == 1, offer_summary
        assert offer_summary["uncategorized"] == 1, offer_summary

        price_columns = (
            "Interní kód", "Interní označení", "Výrobce", "Dodavatel", "Kód dodavatele", "Produkt",
            "Produktová skupina", "Podskupina", "Nákupní cena/MJ", "Cenový základ", "Marže", "Doporučená cena",
            "Sleva", "Výsledná cena", "MJ", "Min. odběr", "Balení", "Hmotnost/MJ", "Rozměry",
            "Podmínka", "Platnost", "Zdrojový ceník",
        )
        price_app = SimpleNamespace(
            price_current_tree=Tree(price_columns), price_current_rows={}, price_current_row_data={},
            price_effective_date=Var(today.isoformat()), price_q=Var(""), price_supplier_filter=Var(""),
            price_category_filter=Var("Všechny"), price_subgroup_filter=Var(""), price_group_filter=Var(""),
            price_price_scope=Var("Ověřené"), price_page_size=Var("250"), price_page=0,
            price_current_status=Var(""), price_prev_button=Button(), price_next_button=Button(),
            price_current_detail_title=Var(""), price_current_detail_subtitle=Var(""),
            price_current_detail_vars={key: Var("—") for key in (
                "Zařazení", "Dodavatel", "Nákupní cena", "Cenový základ", "Marže a sleva", "Doporučená cena",
                "Výsledná cena", "Množství / balení", "Hmotnost / rozměry", "Platnost", "Zdroj", "Podmínka",
            )},
        )
        workspace._refresh_current(module, price_app)
        assert tuple(price_app.price_current_tree.rows) == ("pc1",), price_app.price_current_tree.rows
        values = price_app.price_current_tree.rows["pc1"]["values"]
        assert values[0] == "T-001" and "112,50" in values[13], values
        assert "100,00 CZK / 1 ks" in values[9], values[9]
        assert "končí za 10" in values[20], values[20]

        price_app.price_price_scope.set("Ke kontrole")
        workspace._refresh_current(module, price_app)
        assert tuple(price_app.price_current_tree.rows) == ("pc2",), price_app.price_current_tree.rows
        assert "999,00" in price_app.price_current_tree.rows["pc2"]["values"][8]
        price_app.price_price_scope.set("Ověřené")

        evidence_columns = (
            "Stav", "Platnost", "Dodavatel", "Název", "Produktová skupina", "Položek",
            "Režim", "Platí od", "Platí do", "Rozsah / cenová řada", "Větev", "Import",
        )
        evidence_app = SimpleNamespace(
            price_list_evidence_tree=Tree(evidence_columns), price_evidence_rows={},
            price_evidence_status=Var("Končí do 30 dnů"), price_list_show_archived=Var(False),
            price_evidence_q=Var(""), price_evidence_supplier=Var(""), price_evidence_category=Var("Všechny"),
            price_evidence_page=0, price_evidence_page_size=300, price_evidence_status_text=Var(""),
            price_evidence_prev=Button(), price_evidence_next=Button(),
            price_evidence_detail_title=Var(""), price_evidence_detail_subtitle=Var(""),
            price_evidence_detail_vars={key: Var("—") for key in (
                "Stav", "Platnost", "Dodavatel", "Zařazení", "Rozsah / větev", "Položek",
                "Aktualizace", "Zdrojový soubor", "Import",
            )},
            price_metric_vars=None,
        )
        workspace._refresh_evidence(module, evidence_app)
        assert tuple(evidence_app.price_list_evidence_tree.rows) == ("pl1",), evidence_app.price_list_evidence_tree.rows
        assert "končí za 10" in evidence_app.price_list_evidence_tree.rows["pl1"]["values"][1]

        offer_columns = (
            "Datum", "Dodavatel", "Číslo nabídky", "Vazba", "Akce", "Reference", "Položek",
            "Zařazení produktů", "Hodnota", "Měna", "Typ", "Stav",
        )
        offer_app = SimpleNamespace(
            _commercial_offer_ui_ready=True, _commercial_offer_refresh_after=None,
            offer_supplier_box=Box(), offer_action_box=Box(), offer_status_box=Box(),
            offer_tree=Tree(offer_columns), offer_rows={}, offer_q=Var(""), offer_supplier_filter=Var(""),
            offer_action_filter=Var(""), offer_status_filter=Var("Všechny"), offer_type_filter=Var("Vše"),
            offer_view=Var("Nepřiřazené"), offer_page=0, offer_page_size=Var("250"), offer_status_text=Var(""),
            offer_prev_button=Button(), offer_next_button=Button(), offer_show_archived=Var(False),
            offer_selection_label=Label(), offer_detail_title=Var(""), offer_detail_subtitle=Var(""),
            offer_detail_vars={key: Var("—") for key in (
                "Datum a stav", "Vazba", "Akce", "Reference", "Položek", "Produktové skupiny", "Hodnota", "Typ dokumentu",
            )},
            offer_metric_vars=None,
        )
        workspace.refresh_offers(module, offer_app)
        assert tuple(offer_app.offer_tree.rows) == ("o2",), offer_app.offer_tree.rows
        assert offer_app.offer_tree.rows["o2"]["values"][3] == "Nepřiřazeno"
        assert "offer_unassigned" in offer_app.offer_tree.rows["o2"]["tags"]

    print("TURTO CRM 6.3.36 commercial workspace regression test: OK")


if __name__ == "__main__":
    main()
