#!/usr/bin/env python3
"""Regression test for TURTO CRM 6.3.40 manual products and pricing rules."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
sys.path.insert(0, str(ROOT))

from price_lists_domain.platform import customer_pricing as pricing  # noqa: E402


class Module:
    def __init__(self, path: Path):
        self.path = path

    @staticmethod
    def _collate(a, b):
        a = str(a or "").casefold()
        b = str(b or "").casefold()
        return (a > b) - (a < b)

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation("CZECH", self._collate)
        con.execute("PRAGMA foreign_keys=ON")
        return con


def seed(module: Module):
    with module.db() as con:
        con.executescript(
            """
            CREATE TABLE companies(
              id INTEGER PRIMARY KEY,official_name TEXT,short_name TEXT,active INTEGER DEFAULT 1
            );
            CREATE TABLE actions(
              id INTEGER PRIMARY KEY,name TEXT,archived INTEGER DEFAULT 0
            );
            CREATE TABLE product_categories(
              id INTEGER PRIMARY KEY,name TEXT,active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 10,
              default_margin_pct REAL DEFAULT 0,default_discount_pct REAL DEFAULT 0,
              show_recommended_price INTEGER DEFAULT 1
            );
            CREATE TABLE product_subgroups(
              id INTEGER PRIMARY KEY,category_id INTEGER,name TEXT,active INTEGER DEFAULT 1,
              sort_order INTEGER DEFAULT 10,default_margin_pct REAL DEFAULT 0,
              default_discount_pct REAL DEFAULT 0
            );
            CREATE TABLE catalog_products(
              id INTEGER PRIMARY KEY AUTOINCREMENT,manufacturer_company_id INTEGER,
              manufacturer_name TEXT DEFAULT '',internal_code TEXT DEFAULT '',internal_name TEXT DEFAULT '',
              category_id INTEGER,subgroup_id INTEGER,active INTEGER DEFAULT 1,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX uq_catalog_products_internal_code
              ON catalog_products(lower(trim(internal_code)))
              WHERE trim(coalesce(internal_code,''))<>'';
            CREATE TABLE catalog_product_sources(
              id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL,
              supplier_company_id INTEGER,supplier_name TEXT DEFAULT '',supplier_name_norm TEXT DEFAULT '',
              source_key TEXT NOT NULL UNIQUE,product_identity TEXT NOT NULL,
              supplier_product_code TEXT DEFAULT '',source_name TEXT DEFAULT '',source_kind TEXT DEFAULT '',
              last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE price_lists(
              id INTEGER PRIMARY KEY,valid_from TEXT,valid_to TEXT,archived INTEGER DEFAULT 0
            );
            CREATE TABLE price_list_items(
              id INTEGER PRIMARY KEY,price_list_id INTEGER,catalog_product_id INTEGER,
              normalized_unit_price REAL,currency TEXT,unit TEXT,active INTEGER DEFAULT 1
            );
            CREATE TABLE supplier_offer_items(
              id INTEGER PRIMARY KEY,offer_id INTEGER,catalog_product_id INTEGER
            );
            CREATE TABLE business_document_items(
              id INTEGER PRIMARY KEY,document_id INTEGER,discount_pct REAL DEFAULT 0
            );
            INSERT INTO companies VALUES(1,'ODBĚRATEL A','A',1);
            INSERT INTO companies VALUES(2,'ODBĚRATEL B','B',1);
            INSERT INTO actions VALUES(10,'AKCE ALFA',0);
            INSERT INTO actions VALUES(20,'AKCE BETA',0);
            INSERT INTO product_categories VALUES(100,'IZONOSNÍKY',1,10,25,5,1);
            INSERT INTO product_subgroups VALUES(110,100,'BALKONY',1,10,25,5);
            """
        )


def close(a, b, eps=1e-8):
    assert abs(float(a) - float(b)) <= eps, (a, b)


def main():
    with tempfile.TemporaryDirectory(prefix="turto-6340-") as tmp:
        module = Module(Path(tmp) / "test.db")
        seed(module)
        pricing.ensure_customer_pricing_schema(module)

        product_id = pricing.save_manual_product(module, {
            "internal_name": "Ruční kotevní prvek",
            "internal_code": "RUC-TEST",
            "manufacturer_name": "TURTO",
            "category_id": 100,
            "subgroup_id": 110,
            "manual_purchase_unit_price": "100,00",
            "manual_currency": "CZK",
            "manual_unit": "ks",
            "default_margin_pct": "",
            "default_discount_pct": "",
            "active": True,
        })

        with module.db() as con:
            row = con.execute("SELECT * FROM catalog_products WHERE id=?", (product_id,)).fetchone()
            assert row["manual_product"] == 1
            close(row["manual_purchase_unit_price"], 100)
            assert row["manual_unit"] == "ks"
            assert con.execute(
                "SELECT source_kind FROM catalog_product_sources WHERE product_id=?", (product_id,)
            ).fetchone()[0] == "manual"
            columns = {item[1] for item in con.execute("PRAGMA table_info(business_document_items)")}
            assert {"discount_source", "discount_rule_id"}.issubset(columns)

        base = pricing.resolve_product_pricing(module, product_id)
        assert base["purchase_source"] == "Ruční cena"
        close(base["purchase_unit_price"], 100)
        close(base["margin_pct"], 25)
        close(base["discount_pct"], 5)
        close(base["recommended_unit_price"], 125)
        close(base["final_unit_price"], 118.75)

        company_rule = pricing.save_discount_rule(module, product_id, 1, 8, note="Rámcová sleva")
        assert company_rule > 0
        company = pricing.resolve_product_pricing(module, product_id, 1)
        assert company["discount_source"] == "Sleva společnosti"
        close(company["discount_pct"], 8)

        action_rule = pricing.save_discount_rule(module, product_id, 1, 12, action_id=10, note="AKCE ALFA")
        assert action_rule > company_rule
        action = pricing.resolve_product_pricing(module, product_id, 1, 10)
        assert action["discount_source"] == "Výjimka pro Akci"
        close(action["discount_pct"], 12)
        fallback = pricing.resolve_product_pricing(module, product_id, 1, 20)
        assert fallback["discount_source"] == "Sleva společnosti"
        close(fallback["discount_pct"], 8)
        other_customer = pricing.resolve_product_pricing(module, product_id, 2, 10)
        close(other_customer["discount_pct"], 5)

        # Updating an existing company rule must not create a duplicate.
        pricing.save_discount_rule(module, product_id, 1, 9)
        with module.db() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM customer_product_discounts WHERE product_id=? AND company_id=1 AND action_id IS NULL",
                (product_id,),
            ).fetchone()[0]
        assert count == 1

        # A valid imported Ceník has priority over the manual fallback.
        with module.db() as con:
            con.execute("INSERT INTO price_lists VALUES(1,'2026-01-01','2026-12-31',0)")
            con.execute(
                "INSERT INTO price_list_items VALUES(1,1,?,80,'CZK','ks',1)", (product_id,)
            )
        imported = pricing.resolve_product_pricing(module, product_id, 1, 10, "2026-08-31")
        assert imported["purchase_source"] == "Ceník"
        close(imported["purchase_unit_price"], 80)
        close(imported["discount_pct"], 12)

        payload = {
            "company_id": 1,
            "action_id": 10,
            "issue_date": "2026-08-31",
            "items": [{
                "catalog_product_id": product_id,
                "quantity": 2,
                "purchase_unit_price": 0,
                "margin_pct": 25,
                "discount_pct": 5,
            }],
        }
        priced = pricing.apply_pricing_to_document_payload(module, payload)
        item = priced["items"][0]
        close(item["purchase_unit_price"], 80)
        close(item["discount_pct"], 12)
        assert item["discount_source"] == "Výjimka pro Akci"
        close(item["recommended_unit_price"], 100)
        close(item["unit_price"], 88)
        close(item["total_price"], 176)
        # The input payload is not mutated; saved-document snapshots stay explicit.
        close(payload["items"][0]["discount_pct"], 5)

        manual = {
            "company_id": 1,
            "action_id": 10,
            "issue_date": "2026-08-31",
            "items": [{
                "catalog_product_id": product_id,
                "quantity": 2,
                "purchase_unit_price": 80,
                "margin_pct": 25,
                "discount_pct": 7,
                "discount_source": "Ruční",
            }],
        }
        manual_priced = pricing.apply_pricing_to_document_payload(module, manual)
        close(manual_priced["items"][0]["discount_pct"], 7)
        close(manual_priced["items"][0]["unit_price"], 93)

        source = (ROOT / "price_lists_domain" / "platform" / "__init__.py").read_text(encoding="utf-8")
        assert "install_customer_pricing(module)" in source
        assert source.index("install_customer_pricing(module)") < source.index("install_product_workspace(module)")

    print("OK 6.3.40: manual products, imported-price precedence and Action/company discounts")


if __name__ == "__main__":
    main()
