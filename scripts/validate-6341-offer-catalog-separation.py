#!/usr/bin/env python3
"""Regression test for TURTO CRM 6.3.41 offer/catalog separation."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
sys.path.insert(0, str(ROOT))

from price_lists_domain.issued_offers import service as issued_service  # noqa: E402
from price_lists_domain.platform import product_catalog  # noqa: E402


class Module:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False

    def __init__(self, path):
        self.path = Path(path)

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation(
            "CZECH",
            lambda a, b: (str(a or "").casefold() > str(b or "").casefold())
            - (str(a or "").casefold() < str(b or "").casefold()),
        )
        con.execute("PRAGMA foreign_keys=ON")
        return con

    @staticmethod
    def get_setting(_key, default=""):
        return default


def close(a, b, eps=1e-8):
    assert abs(float(a) - float(b)) <= eps, (a, b)


def seed(M):
    with M.db() as con:
        con.executescript(
            """
            CREATE TABLE companies(
              id INTEGER PRIMARY KEY, official_name TEXT, short_name TEXT, active INTEGER DEFAULT 1
            );
            CREATE TABLE product_categories(
              id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 10,
              default_margin_pct REAL DEFAULT 0, default_discount_pct REAL DEFAULT 0,
              show_recommended_price INTEGER DEFAULT 1
            );
            CREATE TABLE product_subgroups(
              id INTEGER PRIMARY KEY, category_id INTEGER, name TEXT, active INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 10, default_margin_pct REAL DEFAULT 0,
              default_discount_pct REAL DEFAULT 0
            );
            CREATE TABLE catalog_products(
              id INTEGER PRIMARY KEY AUTOINCREMENT, manufacturer_company_id INTEGER,
              manufacturer_name TEXT DEFAULT '', internal_code TEXT DEFAULT '', internal_name TEXT DEFAULT '',
              category_id INTEGER, subgroup_id INTEGER, active INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE catalog_product_sources(
              id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
              supplier_company_id INTEGER, supplier_name TEXT DEFAULT '', supplier_name_norm TEXT DEFAULT '',
              source_key TEXT NOT NULL UNIQUE, product_identity TEXT NOT NULL,
              supplier_product_code TEXT DEFAULT '', source_name TEXT DEFAULT '',
              source_kind TEXT DEFAULT '', last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE price_lists(
              id INTEGER PRIMARY KEY, supplier_company_id INTEGER, supplier_name TEXT,
              valid_from TEXT, valid_to TEXT, archived INTEGER DEFAULT 0
            );
            CREATE TABLE price_list_items(
              id INTEGER PRIMARY KEY, price_list_id INTEGER, category_id INTEGER, subgroup_id INTEGER,
              catalog_product_id INTEGER, active INTEGER DEFAULT 1, product_code TEXT,
              supplier_item_code TEXT, item_key TEXT, name TEXT, description TEXT,
              normalized_unit_price REAL, currency TEXT, unit TEXT
            );
            CREATE TABLE projects(
              id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1
            );
            CREATE TABLE actions(
              id INTEGER PRIMARY KEY, name TEXT, project_id INTEGER, status TEXT DEFAULT 'Řeší se',
              archived INTEGER DEFAULT 0
            );
            CREATE TABLE requests(
              id INTEGER PRIMARY KEY, action_id INTEGER
            );
            CREATE TABLE supplier_offers(
              id INTEGER PRIMARY KEY, supplier_company_id INTEGER, supplier_name TEXT,
              offer_date TEXT, currency TEXT, offer_number TEXT, reference TEXT,
              request_id INTEGER, project_id INTEGER, action_id INTEGER, archived INTEGER DEFAULT 0
            );
            CREATE TABLE supplier_offer_items(
              id INTEGER PRIMARY KEY, offer_id INTEGER, position INTEGER, product_code TEXT,
              item_key TEXT, original_name TEXT, details TEXT, quantity REAL, unit TEXT,
              original_unit_price REAL, unit_price REAL, discount_pct REAL,
              category_id INTEGER, subgroup_id INTEGER, catalog_product_id INTEGER
            );

            INSERT INTO companies VALUES(1,'DODAVATEL A','DODAVATEL',1);
            INSERT INTO product_categories VALUES(1,'SKUPINA A',1,10,20,5,1);
            INSERT INTO product_categories VALUES(2,'SKUPINA B',1,20,30,0,1);
            INSERT INTO product_subgroups VALUES(11,1,'PODSKUPINA A',1,10,20,5);

            INSERT INTO price_lists VALUES(1,1,'DODAVATEL A','2026-01-01','',0);
            INSERT INTO price_list_items(
              id,price_list_id,category_id,subgroup_id,product_code,supplier_item_code,
              item_key,name,description,normalized_unit_price,currency,unit
            ) VALUES(1,1,1,11,'CAT-1','CAT-1','CAT-1','Ceníkový výrobek','',100,'CZK','ks');

            INSERT INTO projects VALUES(1000,'AKCE TEST',1);
            INSERT INTO actions VALUES(100,'PŘÍLEŽITOST TEST',1000,'Řeší se',0);
            INSERT INTO requests VALUES(10,100);
            INSERT INTO supplier_offers(
              id,supplier_company_id,supplier_name,offer_date,currency,offer_number,reference,
              request_id,project_id,action_id,archived
            ) VALUES(1,1,'DODAVATEL A','2026-08-31','CZK','DN-2026-77','REF-77',10,NULL,NULL,0);
            INSERT INTO supplier_offer_items(
              id,offer_id,position,product_code,item_key,original_name,details,quantity,unit,
              original_unit_price,unit_price,discount_pct,category_id,subgroup_id,catalog_product_id
            ) VALUES(1,1,1,'OFFER-X','OFFER-X','Zakázkový prvek','Rozměr podle projektu',
                     2,'ks',120,90,25,1,11,NULL);
            """
        )


def main():
    catalog_source = (ROOT / "price_lists_domain/platform/product_catalog.py").read_text(encoding="utf-8")
    workspace_source = (ROOT / "price_lists_domain/platform/product_workspace.py").read_text(encoding="utf-8")
    commercial_source = (ROOT / "price_lists_domain/platform/commercial_workspace.py").read_text(encoding="utf-8")
    service_source = (ROOT / "price_lists_domain/issued_offers/service.py").read_text(encoding="utf-8")
    editor_source = (ROOT / "price_lists_domain/issued_offers/editor.py").read_text(encoding="utf-8")

    assert "old_save_offer = getattr" not in catalog_source
    assert "received supplier offers are intentionally ignored" in catalog_source.casefold()
    assert "Přijaté nabídky zůstanou beze změny" in workspace_source
    assert "Dosynchronizovat Ceníky" in workspace_source
    assert "Překlopit do Vydané nabídky" in commercial_source
    assert "def draft_from_supplier_offer" in service_source
    assert "initial_document=None, initial_items=None" in editor_source

    with tempfile.TemporaryDirectory(prefix="turto-6341-") as tmp:
        M = Module(Path(tmp) / "test.db")
        seed(M)

        result = product_catalog.sync_all_unlinked(M, max_documents=None)
        assert result == {"documents": 1, "items": 1, "remaining": 0}, result
        with M.db() as con:
            assert con.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0] == 1
            product_id = int(con.execute("SELECT id FROM catalog_products").fetchone()[0])
            assert con.execute(
                "SELECT catalog_product_id FROM price_list_items WHERE id=1"
            ).fetchone()[0] == product_id
            assert con.execute(
                "SELECT catalog_product_id FROM supplier_offer_items WHERE id=1"
            ).fetchone()[0] is None

        assert product_catalog.sync_supplier_offer(M, 1) == 0
        assert product_catalog.propagate_taxonomy_from_items(M, "supplier_offer_items", [1]) == 0
        with M.db() as con:
            assert con.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0] == 1
            assert con.execute(
                "SELECT catalog_product_id FROM supplier_offer_items WHERE id=1"
            ).fetchone()[0] is None

        product_catalog.set_product_taxonomy(M, [product_id], 2, None)
        with M.db() as con:
            assert tuple(con.execute(
                "SELECT category_id,subgroup_id FROM catalog_products WHERE id=?", (product_id,)
            ).fetchone()) == (2, None)
            assert tuple(con.execute(
                "SELECT category_id,subgroup_id FROM price_list_items WHERE id=1"
            ).fetchone()) == (2, None)
            assert tuple(con.execute(
                "SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=1"
            ).fetchone()) == (1, 11)

            # Simulate a legacy link from an older version. Transfer must ignore it.
            con.execute(
                "UPDATE supplier_offer_items SET catalog_product_id=? WHERE id=1", (product_id,)
            )

        with M.db() as con:
            before = con.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0]
        document, items = issued_service.draft_from_supplier_offer(M, 1)
        with M.db() as con:
            assert con.execute("SELECT COUNT(*) FROM catalog_products").fetchone()[0] == before

        assert document["company_id"] is None
        assert document["project_id"] == 1000
        assert document["action_id"] == 100
        assert document["project_name"] == "AKCE TEST"
        assert document["action_name"] == "PŘÍLEŽITOST TEST"
        assert "bez zápisu do Katalogu produktů" in document["internal_note"]
        assert len(items) == 1
        item = items[0]
        assert item["catalog_product_id"] is None
        assert item["source_supplier_offer_item_id"] == 1
        assert item["category_id"] == 1 and item["subgroup_id"] == 11
        close(item["quantity"], 2)
        close(item["purchase_unit_price"], 90)
        close(item["margin_pct"], 20)
        close(item["discount_pct"], 5)
        close(item["recommended_unit_price"], 108)
        close(item["unit_price"], 102.6)
        close(item["total_price"], 205.2)
        assert item["price_source_label"].startswith("Přijatá nabídka DN-2026-77")

    print("OK 6.3.41: received offers stay outside catalogue and copy safely to issued offers")


if __name__ == "__main__":
    main()
