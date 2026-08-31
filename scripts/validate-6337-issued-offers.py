#!/usr/bin/env python3
"""Regression checks for TURTO CRM 6.3.37 issued offers."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import tempfile
from datetime import date, timedelta


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(source))

    import fitz
    from price_lists_domain.issued_offers import pdf_renderer, schema, service

    class M:
        sqlite3 = sqlite3
        CC_ALWAYS = "info@turto.cz"

        def __init__(self, root):
            self.root = pathlib.Path(root)
            self.DATA_ROOT = self.root / "Documents" / "TURTO Zakazky"
            self.DATA_ROOT.mkdir(parents=True)
            self.DB = self.root / "test.db"
            self._settings = {"active_user": "TEST"}

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

        @staticmethod
        def fmt_date(value):
            text = str(value or "")
            if len(text) >= 10 and text[4:5] == "-":
                return f"{text[8:10]}.{text[5:7]}.{text[:4]}"
            return text

    with tempfile.TemporaryDirectory(prefix="turto6337_") as tmp:
        Mx = M(tmp)
        with Mx.db() as con:
            con.executescript(
                """
                CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT DEFAULT '');
                CREATE TABLE companies(
                  id INTEGER PRIMARY KEY,short_name TEXT,official_name TEXT,ico TEXT,dic TEXT,address TEXT,active INTEGER DEFAULT 1
                );
                CREATE TABLE people(
                  id INTEGER PRIMARY KEY,name TEXT,email TEXT,phone TEXT,company_id INTEGER,active INTEGER DEFAULT 1
                );
                CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT,active INTEGER DEFAULT 1);
                CREATE TABLE actions(
                  id INTEGER PRIMARY KEY,name TEXT,status TEXT DEFAULT 'Rozpracováno',project_id INTEGER,archived INTEGER DEFAULT 0
                );
                CREATE TABLE product_categories(
                  id INTEGER PRIMARY KEY,name TEXT,default_margin_pct REAL DEFAULT 0,
                  default_discount_pct REAL DEFAULT 0,show_recommended_price INTEGER DEFAULT 1
                );
                CREATE TABLE product_subgroups(
                  id INTEGER PRIMARY KEY,category_id INTEGER,name TEXT,default_margin_pct REAL DEFAULT 0,
                  default_discount_pct REAL DEFAULT 0
                );
                CREATE TABLE catalog_products(
                  id INTEGER PRIMARY KEY,manufacturer_name TEXT,internal_code TEXT,internal_name TEXT,
                  category_id INTEGER,subgroup_id INTEGER,active INTEGER DEFAULT 1
                );
                CREATE TABLE catalog_product_sources(
                  id INTEGER PRIMARY KEY,product_id INTEGER,supplier_product_code TEXT,source_name TEXT,
                  supplier_name TEXT,source_kind TEXT
                );
                CREATE TABLE price_lists(
                  id INTEGER PRIMARY KEY,title TEXT,valid_from TEXT,valid_to TEXT,archived INTEGER DEFAULT 0,parse_status TEXT
                );
                CREATE TABLE price_list_items(
                  id INTEGER PRIMARY KEY,price_list_id INTEGER,catalog_product_id INTEGER,normalized_unit_price REAL,
                  unit TEXT,active INTEGER DEFAULT 1
                );
                CREATE TABLE supplier_offers(
                  id INTEGER PRIMARY KEY,offer_date TEXT,archived INTEGER DEFAULT 0
                );
                CREATE TABLE supplier_offer_items(
                  id INTEGER PRIMARY KEY,offer_id INTEGER,catalog_product_id INTEGER,unit_price REAL
                );
                CREATE TABLE business_documents(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,document_type TEXT NOT NULL,direction TEXT NOT NULL DEFAULT 'issued',
                  document_number TEXT DEFAULT '',issue_date TEXT DEFAULT '',due_date TEXT DEFAULT '',valid_to TEXT DEFAULT '',
                  company_id INTEGER,project_id INTEGER,status TEXT DEFAULT 'Rozpracováno',currency TEXT DEFAULT 'CZK',
                  total_value REAL DEFAULT 0,note TEXT DEFAULT '',source_path TEXT DEFAULT '',archived INTEGER DEFAULT 0,
                  archived_at TEXT DEFAULT '',archived_by TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE business_document_items(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,document_id INTEGER NOT NULL,position INTEGER DEFAULT 0,
                  product_code TEXT DEFAULT '',item_key TEXT DEFAULT '',name TEXT DEFAULT '',description TEXT DEFAULT '',
                  quantity REAL DEFAULT 0,unit TEXT DEFAULT '',unit_price REAL DEFAULT 0,discount_pct REAL DEFAULT 0,
                  total_price REAL DEFAULT 0,category_id INTEGER
                );
                INSERT INTO companies VALUES(1,'Hinton','Hinton, a.s.','12345678','CZ12345678','Praha 1',1);
                INSERT INTO people VALUES(1,'Jan Novák','jan.novak@example.cz','777 000 111',1,1);
                INSERT INTO projects VALUES(1,'BD Petruškova',1);
                INSERT INTO actions VALUES(1,'Izolační nosníky','Rozpracováno',1,0);
                INSERT INTO product_categories VALUES(1,'PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK',30,10,1);
                INSERT INTO product_subgroups VALUES(1,1,'TEPELNĚ IZOLAČNÍ NOSNÍK',30,10);
                INSERT INTO catalog_products VALUES(1,'Leviat','TUR-001','Izolační nosník',1,1,1);
                INSERT INTO catalog_product_sources VALUES(1,1,'HIT-001','HIT HP MV','Leviat','Ceník');
                INSERT INTO price_lists VALUES(1,'Ceník Leviat 2026','2026-01-01','',0,'Připraveno');
                INSERT INTO price_list_items VALUES(1,1,1,1000,'ks',1);
                """
            )

        schema.ensure_business_documents_schema(Mx)
        with Mx.db() as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"document_sequences", "business_document_templates", "business_document_revisions", "business_document_history"} <= tables
            doc_cols = {row[1] for row in con.execute("PRAGMA table_info(business_documents)")}
            item_cols = {row[1] for row in con.execute("PRAGMA table_info(business_document_items)")}
            assert {"customer_name_snapshot", "issuer_name_snapshot", "subtotal_net", "total_gross", "template_id", "last_pdf_path"} <= doc_cols
            assert {"row_type", "catalog_product_id", "purchase_unit_price", "margin_pct", "recommended_unit_price", "vat_rate"} <= item_cols

        products = service.catalog_products(Mx)
        assert len(products) == 1, products
        product = products[0]
        assert round(product["purchase_unit_price"], 2) == 1000
        assert round(product["recommended_unit_price"], 2) == 1300
        assert round(product["unit_price"], 2) == 1170
        assert product["internal_code_snapshot"] == "TUR-001"

        values = service.offer_defaults(Mx)
        values.update(service.company_snapshot(Mx, 1))
        values.update(service.contact_snapshot(Mx, 1))
        values.update(
            project_id=1,
            action_id=1,
            offer_subject="Izolační nosníky",
            customer_reference="REF-2026-001",
            issue_date=date.today().isoformat(),
            valid_to=(date.today() + timedelta(days=14)).isoformat(),
            status="Připraveno",
        )
        items = [dict(product, quantity=12)]
        items.append(service.normalize_item({
            "row_type": "delivery", "name": "Doprava na stavbu", "quantity": 1, "unit": "kpl",
            "purchase_unit_price": 1200, "margin_pct": 25, "discount_pct": 0, "vat_rate": 21,
        }, recalculate_sale=True))
        for index in range(45):
            items.append(service.normalize_item({
                "row_type": "product", "name": f"Doplňkový výrobek {index + 1}", "quantity": 2,
                "unit": "ks", "purchase_unit_price": 50 + index, "margin_pct": 20,
                "discount_pct": 5, "vat_rate": 21,
            }, recalculate_sale=True))

        document_id = service.save_document(Mx, values, items)
        document, stored_items = service.load_document(Mx, document_id)
        assert document["document_number"].startswith(f"CN-{date.today().year}-")
        assert document["customer_name_snapshot"] == "Hinton, a.s."
        assert document["customer_email_snapshot"] == "jan.novak@example.cz"
        assert len(stored_items) == len(items)
        assert document["subtotal_net"] > 0 and document["total_gross"] > document["subtotal_net"]

        copy_id = service.duplicate_document(Mx, document_id)
        copy_doc, copy_items = service.load_document(Mx, copy_id)
        assert copy_doc["document_number"] != document["document_number"]
        assert copy_doc["status"] == "Rozpracováno"
        assert len(copy_items) == len(stored_items)

        pdf_path = pdf_renderer.render_offer_pdf(Mx, document_id)
        assert pdf_path.is_file() and pdf_path.stat().st_size > 3000
        pdf = fitz.open(pdf_path)
        assert pdf.page_count >= 2, pdf.page_count
        text = "\n".join(page.get_text() for page in pdf)
        pdf.close()
        assert "CENOVÁ NABÍDKA" in text
        assert document["document_number"] in text
        assert "Hinton, a.s." in text
        assert "Izolační nosník" in text
        assert "Nákupní" not in text and "Marže" not in text
        assert "18 803,40" not in text  # Total changed by the added rows; no stale hard-coded total.

        with Mx.db() as con:
            revision = con.execute("SELECT * FROM business_document_revisions WHERE document_id=?", (document_id,)).fetchone()
            assert revision and revision["revision_no"] == 0
            assert len(revision["pdf_sha256"]) == 64
            updated = con.execute("SELECT revision_no,last_pdf_path,last_pdf_sha256 FROM business_documents WHERE id=?", (document_id,)).fetchone()
            assert updated["revision_no"] == 0 and pathlib.Path(updated["last_pdf_path"]).is_file()
            assert updated["last_pdf_sha256"] == revision["pdf_sha256"]

        try:
            service.delete_draft(Mx, document_id)
        except ValueError:
            pass
        else:
            raise AssertionError("A document with PDF revision must not be deleted as a draft")

        domain = (source / "price_lists_domain" / "__init__.py").read_text(encoding="utf-8")
        assert "install_issued_offers(module)" in domain
        assert "from .issued_offers import apply" in domain
        print("TURTO CRM 6.3.37 issued offers regression checks passed")


if __name__ == "__main__":
    main()
