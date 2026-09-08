#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.8 professional offer release workflow."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace


class ClosingTestConnection(sqlite3.Connection):
    """Close fake-owner SQLite handles deterministically on Windows too."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def load_layer(source: Path):
    # The production launcher always places the application source root on
    # sys.path before importing runtime layers.  Keep this isolated validator
    # faithful to that contract so shared helpers such as app_lifecycle resolve
    # exactly as they do in the packaged application.
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)
    path = source / "price_lists_domain" / "issued_offers" / "professional_workflow.py"
    spec = importlib.util.spec_from_file_location(
        "v780_professional_offer_workflow_validation", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load v780 layer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_document() -> dict:
    return {
        "document_number": "CN26-00001",
        "company_id": 1,
        "customer_contact_id": 2,
        "project_id": 3,
        "project_name": "BD Test",
        "issue_date": "2026-09-05",
        "valid_to": "2026-09-19",
        "currency": "CZK",
        "global_discount_pct": 0,
        "offer_subject": "Dodávka kotevní techniky",
        "customer_name_snapshot": "ODBĚRATEL s.r.o.",
        "customer_address_snapshot": "Testovací 1, Praha",
        "customer_ico_snapshot": "12345678",
        "customer_contact_snapshot": "Jan Novák",
        "customer_email_snapshot": "jan.novak@example.test",
        "issuer_name_snapshot": "TURTO s.r.o.",
        "issuer_contact_snapshot": "Ing. Jaroslav Kučera",
        "salesperson_snapshot": "Ing. Jaroslav Kučera",
        "template_id": 1,
        "payment_terms": "Splatnost 14 dní",
        "delivery_terms": "DAP Praha",
        "customer_note": "Děkujeme za poptávku.",
        "internal_note": "Interní poznámka",
        "status": "Rozpracováno",
    }


def valid_items() -> list[dict]:
    return [
        {
            "line_type": "item",
            "catalog_product_id": 10,
            "internal_code_snapshot": "TUR-001",
            "name": "Kotevní výrobek",
            "internal_name_snapshot": "Kotevní výrobek",
            "description": "Technický popis",
            "unit": "ks",
            "quantity": 2,
            "unit_cost": 100,
            "base_unit_price": 150,
            "margin_pct": 50,
            "discount_pct": 0,
            "unit_price": 150,
            "vat_rate": 21,
            "keep_supplier_name": 0,
            "source_offer_item_id": None,
        }
    ]


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    layer = load_layer(source)

    checks = layer.run_preflight(valid_document(), valid_items())
    assert checks
    assert not [item for item in checks if item.level == "error"], checks

    broken = valid_document()
    broken["customer_name_snapshot"] = ""
    errors = [item for item in layer.run_preflight(broken, valid_items()) if item.level == "error"]
    assert errors

    # Pricing-only internal changes must not invalidate a customer-facing PDF
    # unless the resulting sale price changes.
    fingerprint_a = layer.customer_content_fingerprint(valid_document(), valid_items())
    internal_changed = valid_items()
    internal_changed[0]["unit_cost"] = 120
    internal_changed[0]["margin_pct"] = 25
    fingerprint_b = layer.customer_content_fingerprint(valid_document(), internal_changed)
    assert fingerprint_a == fingerprint_b

    sale_changed = valid_items()
    sale_changed[0]["unit_price"] = 160
    fingerprint_c = layer.customer_content_fingerprint(valid_document(), sale_changed)
    assert fingerprint_c != fingerprint_a

    # A large offer should still validate without artificial row-count limits.
    large = valid_items() * 120
    large_checks = layer.run_preflight(valid_document(), large)
    assert not [item for item in large_checks if item.level == "error"]

    with tempfile.TemporaryDirectory(prefix="turto_780_") as tmp:
        db_path = Path(tmp) / "test.db"

        class App:
            pass

        class Module:
            DB = db_path
            App = App

            @staticmethod
            def db():
                return sqlite3.connect(db_path, factory=ClosingTestConnection)

        module = Module()
        con = module.db()
        try:
            con.executescript(
                """
                CREATE TABLE business_documents(
                    id INTEGER PRIMARY KEY,
                    document_number TEXT,
                    status TEXT,
                    company_id INTEGER,
                    customer_contact_id INTEGER,
                    project_id INTEGER,
                    project_name TEXT,
                    issue_date TEXT,
                    valid_to TEXT,
                    currency TEXT,
                    global_discount_pct REAL,
                    offer_subject TEXT,
                    customer_name_snapshot TEXT,
                    customer_address_snapshot TEXT,
                    customer_ico_snapshot TEXT,
                    customer_contact_snapshot TEXT,
                    customer_email_snapshot TEXT,
                    issuer_name_snapshot TEXT,
                    issuer_contact_snapshot TEXT,
                    salesperson_snapshot TEXT,
                    template_id INTEGER,
                    payment_terms TEXT,
                    delivery_terms TEXT,
                    customer_note TEXT,
                    internal_note TEXT,
                    updated_at TEXT
                );
                CREATE TABLE business_document_items(
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    sort_order INTEGER,
                    line_type TEXT,
                    catalog_product_id INTEGER,
                    internal_code_snapshot TEXT,
                    name TEXT,
                    internal_name_snapshot TEXT,
                    description TEXT,
                    unit TEXT,
                    quantity REAL,
                    unit_cost REAL,
                    base_unit_price REAL,
                    margin_pct REAL,
                    discount_pct REAL,
                    unit_price REAL,
                    vat_rate REAL,
                    keep_supplier_name INTEGER,
                    source_offer_item_id INTEGER
                );
                CREATE TABLE business_document_revisions(
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    revision_no INTEGER,
                    pdf_path TEXT,
                    created_at TEXT
                );
                CREATE TABLE business_document_history(
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    event_type TEXT,
                    note TEXT,
                    created_at TEXT
                );
                CREATE TABLE business_document_templates(
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    updated_at TEXT
                );
                """
            )
            con.commit()
        finally:
            con.close()

        # The layer should be independently applicable because app_lifecycle.register
        # self-installs the single App.__init__ owner when bootstrap is absent.
        layer.apply(module)
        assert getattr(module, "_turto_v780_professional_offer_workflow", False)
        assert getattr(module, "_turto_app_lifecycle_installed", False)

    source_text = (source / "price_lists_domain" / "issued_offers" / "professional_workflow.py").read_text(encoding="utf-8")
    assert "email_draft" in source_text
    assert "confirm" in source_text.lower()
    assert "help" in source_text.lower()
    print("OK 7.8 professional offer workflow: preflight, customer fingerprint, large offers, lifecycle-safe isolated apply and help contract")


if __name__ == "__main__":
    main()
