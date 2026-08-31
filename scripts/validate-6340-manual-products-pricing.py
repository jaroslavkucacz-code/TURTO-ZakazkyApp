#!/usr/bin/env python3
"""Regression checks for manual catalogue products and contextual discounts."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
from datetime import date


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(source))

    from price_lists_domain.platform import database, pricing_profiles, product_catalog
    from price_lists_domain.issued_offers import schema as issued_schema, service

    class M:
        sqlite3 = sqlite3
        PRICE_FTS_AVAILABLE = False
        CC_ALWAYS = "info@turto.cz"

        def __init__(self, root):
            self.root = pathlib.Path(root)
            self.DB = self.root / "test.db"
            self.DATA_ROOT = self.root / "Documents" / "TURTO Zakazky"
            self.DATA_ROOT.mkdir(parents=True)
            self._settings = {"active_user": "TEST", "issued_offer_default_vat_rate": "21"}

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            con.create_collation("CZECH", lambda a, b: (str(a) > str(b)) - (str(a) < str(b)))
            con.execute("PRAGMA foreign_keys=ON")
            return con

        def get_setting(self, key, default=""):
            return self._settings.get(key, default)

        def set_setting(self, key, value):
            self._settings[key] = str(value)

    with tempfile.TemporaryDirectory(prefix="turto6340_") as tmp:
        Mx = M(tmp)
        with Mx.db() as con:
            con.executescript(
                """
                CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT DEFAULT '');
                CREATE TABLE companies(
                  id INTEGER PRIMARY KEY,short_name TEXT,official_name TEXT,ico TEXT,dic TEXT,address TEXT,
                  active INTEGER DEFAULT 1
                );
                CREATE TABLE people(
                  id INTEGER PRIMARY KEY,name TEXT,email TEXT,phone TEXT,company_id INTEGER,active INTEGER DEFAULT 1
                );
                CREATE TABLE projects(
                  id INTEGER PRIMARY KEY,name TEXT,active INTEGER DEFAULT 1,end_date TEXT
                );
                CREATE TABLE actions(
                  id INTEGER PRIMARY KEY,name TEXT,company_id INTEGER,status TEXT DEFAULT 'Rozpracováno',
                  project_id INTEGER,archived INTEGER DEFAULT 0,created_date TEXT,deadline TEXT,updated_at TEXT
                );
                CREATE TABLE product_categories(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE COLLATE CZECH,parent_id INTEGER,
                  keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE product_subgroups(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,category_id INTEGER NOT NULL,name TEXT NOT NULL,
                  keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  UNIQUE(category_id,name)
                );
                CREATE TABLE price_lists(
                  id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,category_id INTEGER,
                  archived INTEGER DEFAULT 0,valid_from TEXT,valid_to TEXT,parse_status TEXT,title TEXT,
                  product_group TEXT,branch TEXT,source_filename TEXT,imported_at TEXT
                );
                CREATE TABLE price_list_items(
                  id INTEGER PRIMARY KEY,price_list_id INTEGER,category_id INTEGER,subgroup_id INTEGER,
                  active INTEGER DEFAULT 1,product_code TEXT,supplier_item_code TEXT,item_key TEXT,name TEXT,
                  description TEXT,condition_text TEXT,normalized_unit_price REAL,currency TEXT,unit TEXT
                );
                CREATE TABLE supplier_offers(
                  id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,archived INTEGER DEFAULT 0,
                  offer_date TEXT,currency TEXT,offer_number TEXT,reference TEXT
                );
                CREATE TABLE supplier_offer_items(
                  id INTEGER PRIMARY KEY,offer_id INTEGER,category_id INTEGER,subgroup_id INTEGER,
                  product_code TEXT,item_key TEXT,original_name TEXT,details TEXT,unit_price REAL
                );
                CREATE TABLE tasks(
                  id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,done INTEGER DEFAULT 0,due_date TEXT,done_at TEXT
                );
                CREATE TABLE requests(
                  id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,
                  received_date TEXT,asked_date TEXT
                );
                INSERT INTO companies VALUES(1,'Zákazník A','Zákazník A s.r.o.','','','Praha',1);
                INSERT INTO companies VALUES(2,'Dodavatel X','Dodavatel X s.r.o.','','','Brno',1);
                INSERT INTO companies VALUES(3,'Zákazník B','Zákazník B s.r.o.','','','Plzeň',1);
                INSERT INTO projects VALUES(10,'Akce Alfa',1,'');
                INSERT INTO projects VALUES(11,'Akce Beta',1,'');
                INSERT INTO actions VALUES(20,'Příležitost Alfa',1,'Rozpracováno',10,0,'','','');
                INSERT INTO actions VALUES(21,'Příležitost B',3,'Rozpracováno',11,0,'','','');
                """
            )

        database.ensure_platform_schema(Mx)
        issued_schema.ensure_business_documents_schema(Mx)

        with Mx.db() as con:
            group = int(con.execute(
                "SELECT id FROM product_categories WHERE name='Kotevní technika'"
            ).fetchone()[0])
            con.execute(
                "UPDATE product_categories SET default_margin_pct=25,default_discount_pct=5 WHERE id=?",
                (group,),
            )

        product_id = pricing_profiles.save_manual_product(Mx, {
            "internal_code": "TUR-R-001",
            "internal_name": "Ručně založená kotva",
            "manufacturer_name": "Výrobce ruční",
            "manual_purchase_price": "100,00",
            "manual_purchase_currency": "CZK",
            "manual_unit": "ks",
            "default_vat_rate": 21,
            "manual_price_note": "Výchozí cena bez importovaného ceníku",
            "category_id": group,
            "supplier_company_id": 2,
            "supplier_product_code": "DX-001",
            "source_name": "Kotva DX 001",
            "active": True,
        })
        assert product_id > 0

        with Mx.db() as con:
            product = con.execute("SELECT * FROM catalog_products WHERE id=?", (product_id,)).fetchone()
            assert product["manual_product"] == 1
            assert product["manual_purchase_price"] == 100
            assert product["manual_unit"] == "ks"
            source_row = con.execute(
                "SELECT * FROM catalog_product_sources WHERE product_id=?", (product_id,)
            ).fetchone()
            assert source_row and source_row["supplier_product_code"] == "DX-001"
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "catalog_product_discount_rules" in tables

        base = service.catalog_products(Mx)
        assert len([row for row in base if row["catalog_product_id"] == product_id]) == 1
        item = next(row for row in base if row["catalog_product_id"] == product_id)
        assert item["purchase_unit_price"] == 100
        assert item["purchase_currency"] == "CZK"
        assert item["unit"] == "ks"
        assert item["standard_discount_pct"] == 5
        assert item["discount_pct"] == 5
        assert item["discount_source_snapshot"] == "Standard skupiny / podskupiny"
        assert round(item["recommended_unit_price"], 2) == 125
        assert round(item["unit_price"], 2) == 118.75

        company_rule = pricing_profiles.save_discount_rule(Mx, product_id, 1, 10, note="Běžná sleva odběratele")
        action_rule = pricing_profiles.save_discount_rule(
            Mx, product_id, 1, 15, action_id=20, note="Sleva pro Příležitost"
        )
        project_rule = pricing_profiles.save_discount_rule(
            Mx, product_id, 1, 22, project_id=10, note="Sleva pro konkrétní Akci"
        )
        assert len({company_rule, action_rule, project_rule}) == 3

        resolved_company = pricing_profiles.resolve_discount(
            Mx, product_id, company_id=1, standard_discount_pct=5
        )
        resolved_action = pricing_profiles.resolve_discount(
            Mx, product_id, company_id=1, action_id=20, standard_discount_pct=5
        )
        resolved_project = pricing_profiles.resolve_discount(
            Mx, product_id, company_id=1, action_id=20, project_id=10, standard_discount_pct=5
        )
        other_company = pricing_profiles.resolve_discount(
            Mx, product_id, company_id=3, action_id=21, project_id=11, standard_discount_pct=5
        )
        assert resolved_company["discount_pct"] == 10 and resolved_company["scope"] == "company"
        assert resolved_action["discount_pct"] == 15 and resolved_action["scope"] == "action"
        assert resolved_project["discount_pct"] == 22 and resolved_project["scope"] == "project"
        assert other_company["discount_pct"] == 5 and other_company["scope"] == "standard"

        project_items = service.catalog_products(Mx, company_id=1, action_id=20, project_id=10)
        contextual = next(row for row in project_items if row["catalog_product_id"] == product_id)
        assert contextual["discount_pct"] == 22
        assert contextual["discount_source_snapshot"] == "Akce: Akce Alfa"
        assert round(contextual["unit_price"], 2) == 97.50

        manually_overridden = dict(contextual, discount_pct=7, unit_price=116.25,
                                   discount_manual_override=1,
                                   discount_source_snapshot="Ruční úprava řádku")
        unchanged, applied = service.apply_pricing_context(
            Mx, manually_overridden, company_id=1, action_id=20, project_id=10
        )
        assert not applied and unchanged["discount_pct"] == 7

        company_item, applied = service.apply_pricing_context(
            Mx, dict(contextual, discount_manual_override=0), company_id=1
        )
        assert applied and company_item["discount_pct"] == 10
        assert company_item["discount_source_snapshot"].startswith("Společnost:")

        values = service.offer_defaults(Mx)
        values.update(service.company_snapshot(Mx, 1))
        values.update(company_id=1, action_id=20, project_id=10, offer_subject="Akce Alfa")
        document_id = service.save_document(Mx, values, [dict(contextual, quantity=3)])
        document, stored = service.load_document(Mx, document_id)
        assert document["company_id"] == 1 and document["project_id"] == 10
        assert stored[0]["discount_pct"] == 22
        assert stored[0]["discount_rule_id"] == project_rule
        assert stored[0]["discount_source_snapshot"] == "Akce: Akce Alfa"
        assert stored[0]["pricing_company_id_snapshot"] == 1
        assert stored[0]["pricing_project_id_snapshot"] == 10

        pricing_profiles.save_discount_rule(
            Mx, product_id, 1, 30, project_id=10, rule_id=project_rule
        )
        _doc_again, stored_again = service.load_document(Mx, document_id)
        assert stored_again[0]["discount_pct"] == 22, "Historical issued-offer snapshot was rewritten"

        # A later imported price list with the same supplier/code links to the
        # existing manual product and takes precedence over the manual fallback.
        with Mx.db() as con:
            con.execute(
                """INSERT INTO price_lists(
                       id,supplier_company_id,supplier_name,valid_from,valid_to,parse_status,title,archived
                   ) VALUES(100,2,'Dodavatel X s.r.o.',?,'','Připraveno','Ceník Dodavatel X',0)""",
                (date.today().isoformat(),),
            )
            con.execute(
                """INSERT INTO price_list_items(
                       id,price_list_id,product_code,item_key,name,normalized_unit_price,currency,unit,active
                   ) VALUES(100,100,'DX-001','DX-001','Kotva DX 001',140,'CZK','ks',1)"""
            )
        assert product_catalog.sync_price_list(Mx, 100) == 1
        with Mx.db() as con:
            linked = con.execute(
                "SELECT catalog_product_id FROM price_list_items WHERE id=100"
            ).fetchone()[0]
        assert linked == product_id
        imported = next(
            row for row in service.catalog_products(Mx, company_id=1)
            if row["catalog_product_id"] == product_id
        )
        assert imported["purchase_unit_price"] == 140
        assert imported["price_source_label"] == "Ceník Dodavatel X"

        # Duplicate rules at the same scope update the existing row, not create ambiguity.
        same_company_rule = pricing_profiles.save_discount_rule(Mx, product_id, 1, 12)
        assert same_company_rule == company_rule
        with Mx.db() as con:
            count = con.execute(
                """SELECT COUNT(*) FROM catalog_product_discount_rules
                   WHERE catalog_product_id=? AND company_id=1
                     AND action_id IS NULL AND project_id IS NULL""",
                (product_id,),
            ).fetchone()[0]
            assert count == 1
            item_columns = {row[1] for row in con.execute("PRAGMA table_info(business_document_items)")}
            assert {
                "standard_discount_pct", "discount_source_snapshot", "discount_rule_id",
                "discount_manual_override", "pricing_company_id_snapshot",
                "pricing_action_id_snapshot", "pricing_project_id_snapshot",
            } <= item_columns

        platform_init = (source / "price_lists_domain" / "platform" / "__init__.py").read_text(encoding="utf-8")
        editor_text = (source / "price_lists_domain" / "issued_offers" / "editor.py").read_text(encoding="utf-8")
        workspace_text = (source / "price_lists_domain" / "platform" / "product_workspace.py").read_text(encoding="utf-8")
        assert "install_pricing_profiles(module)" in platform_init
        assert "+ Nový výrobek…" in editor_text and "Načíst slevy odběratele / Akce" in editor_text
        assert "+ Nový výrobek…" in workspace_text and "Cena a slevy…" in workspace_text

    print("TURTO CRM 6.3.40 manual products and contextual pricing checks passed")


if __name__ == "__main__":
    main()
