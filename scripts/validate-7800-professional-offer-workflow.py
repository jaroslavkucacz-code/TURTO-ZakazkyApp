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


def load_layer(source: Path):
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
        "payment_terms": "14 dní",
        "delivery_time": "2 až 3 týdny",
        "template_id": 1,
    }


def valid_item() -> dict:
    return {
        "row_type": "product",
        "product_code": "DOD-001",
        "name": "Kotevní prvek",
        "description": "Technické provedení dle nabídky",
        "quantity": 4,
        "unit": "ks",
        "recommended_unit_price": 1250,
        "unit_price": 1200,
        "total_price": 4800,
        "discount_pct": 4,
        "vat_rate": 21,
        "category_id": 1,
        "subgroup_id": 2,
        "category_name_snapshot": "Kotevní technika",
        "subgroup_name_snapshot": "Kotevní prvky",
        "internal_code_snapshot": "TUR-001",
        "internal_name_snapshot": "Kotevní prvek TURTO",
    }


class DbOwner:
    def __init__(self, path: Path):
        self.path = path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1")
    if not source.is_dir():
        raise SystemExit(f"Source directory not found: {source}")
    layer_path = source / "price_lists_domain" / "issued_offers" / "professional_workflow.py"
    text = layer_path.read_text(encoding="utf-8")
    layer = load_layer(source)

    # Full, clean offer passes both PDF and e-mail preflight.
    document = valid_document()
    item = valid_item()
    report = layer.offer_preflight(document, [item], for_email=True)
    assert report.ready, [check for check in report.checks if check.level == "error"]
    assert not report.errors
    assert not report.warnings

    # Core blockers are deterministic and warnings do not block PDF release.
    missing = layer.offer_preflight({}, [], for_email=False)
    assert not missing.ready
    codes = {check.code for check in missing.errors}
    assert {"customer", "subject", "issue_date", "currency", "items", "priced_items"} <= codes
    assert missing.warnings

    no_email = dict(document)
    no_email["customer_email_snapshot"] = ""
    pdf_report = layer.offer_preflight(no_email, [item], for_email=False)
    mail_report = layer.offer_preflight(no_email, [item], for_email=True)
    assert pdf_report.ready
    assert any(check.code == "email" and check.level == "warning" for check in pdf_report.checks)
    assert not mail_report.ready
    assert any(check.code == "email" and check.level == "error" for check in mail_report.checks)

    invalid = dict(document)
    invalid["valid_to"] = "2026-09-01"
    bad_item = dict(item, quantity=0, unit_price=-1, discount_pct=140)
    invalid_report = layer.offer_preflight(invalid, [bad_item])
    invalid_codes = {check.code for check in invalid_report.errors}
    assert {"validity", "quantities", "negative_prices", "discounts"} <= invalid_codes

    # Supplier-presentation rows intentionally retain the supplier name and need
    # no TURTO internal code; ordinary product rows still do.
    supplier_item = dict(item)
    supplier_item.update(
        supplier_presentation_snapshot=1,
        supplier_name_snapshot="Původní název dodavatele",
        internal_code_snapshot="",
        internal_name_snapshot="",
        name="Původní název dodavatele",
    )
    assert layer.offer_preflight(document, [supplier_item]).ready
    ordinary_missing = dict(supplier_item, supplier_presentation_snapshot=0)
    ordinary_report = layer.offer_preflight(document, [ordinary_missing])
    assert any(
        check.code == "identities" and check.level == "error"
        for check in ordinary_report.checks
    )

    # Large offers produce aggregate checks rather than thousands of Treeview
    # rows, preserving UI responsiveness.
    large_items = [dict(item, name=f"Položka {index}") for index in range(600)]
    large_report = layer.offer_preflight(document, large_items)
    assert len(large_report.checks) < 40

    # The commercial fingerprint follows customer-visible line breaks, order,
    # project identity, prices and terms, but ignores internal margin-only changes.
    base = layer.commercial_fingerprint(document, [item])
    assert base == layer.commercial_fingerprint(dict(document), [dict(item)])
    assert base != layer.commercial_fingerprint(
        dict(document, customer_note="řádek 1\nřádek 2"), [item]
    )
    assert base != layer.commercial_fingerprint(
        dict(document, project_name="Jiná akce"), [item]
    )
    assert base != layer.commercial_fingerprint(
        document, [dict(item, unit_price=1201)]
    )
    assert base != layer.commercial_fingerprint(
        document, [dict(item), dict(item, name="Druhá položka")]
    )
    assert base == layer.commercial_fingerprint(
        document, [dict(item, margin_pct=99, purchase_unit_price=1)]
    )

    # Template geometry and asset bytes participate in release freshness.
    with tempfile.TemporaryDirectory(prefix="turto_v780_validation_") as temp:
        temp_path = Path(temp)
        header = temp_path / "header.png"
        header.write_bytes(b"header-v1")
        template = {
            "id": 1,
            "name": "Standard",
            "header_path": str(header),
            "footer_path": "",
            "header_height_mm": 25,
            "footer_height_mm": 14,
            "margin_left_mm": 14,
            "margin_right_mm": 14,
            "body_top_gap_mm": 5,
            "body_bottom_gap_mm": 5,
            "header_every_page": 1,
            "footer_every_page": 1,
        }

        sys.path.insert(0, str(source))
        try:
            from price_lists_domain.issued_offers import service
        finally:
            if sys.path and sys.path[0] == str(source):
                sys.path.pop(0)

        original_load_document = service.load_document
        original_load_template = service.load_template
        original_record_revision = service.record_revision
        current_document = dict(document)
        current_items = [dict(item)]
        service.load_document = lambda _M, _document_id: (
            dict(current_document),
            [dict(row) for row in current_items],
        )
        service.load_template = lambda _M, _template_id=None: dict(template)

        first_template = layer.template_fingerprint(SimpleNamespace(), 1)
        header.write_bytes(b"header-v2")
        second_template = layer.template_fingerprint(SimpleNamespace(), 1)
        assert first_template != second_template

        database = temp_path / "test.db"
        with sqlite3.connect(database) as con:
            con.execute(
                """CREATE TABLE business_document_revisions(
                       id INTEGER PRIMARY KEY,
                       document_id INTEGER NOT NULL,
                       revision_no INTEGER NOT NULL,
                       pdf_path TEXT,
                       data_json TEXT,
                       created_at TEXT
                   )"""
            )
        owner = DbOwner(database)
        assert layer.pdf_state(owner, 1).status == "none"

        pdf = temp_path / "CN26-00001_R00.pdf"
        pdf.write_bytes(b"%PDF-1.4\nvalidation\n")
        release_hash = layer.release_fingerprint(owner, current_document, current_items)
        snapshot = {
            **current_document,
            "items": current_items,
            "_commercial_fingerprint": layer.commercial_fingerprint(
                current_document, current_items
            ),
            "_template_fingerprint": layer.template_fingerprint(owner, 1),
            "_release_fingerprint": release_hash,
        }
        with sqlite3.connect(database) as con:
            con.execute(
                """INSERT INTO business_document_revisions(
                       document_id,revision_no,pdf_path,data_json,created_at
                   ) VALUES(?,?,?,?,?)""",
                (1, 0, str(pdf), json.dumps(snapshot, ensure_ascii=False), "2026-09-05T12:00:00"),
            )
        state = layer.pdf_state(owner, 1)
        assert state.status == "current"
        assert state.revision_no == 0
        current_document["offer_subject"] = "Změněný předmět"
        assert layer.pdf_state(owner, 1).status == "stale"
        current_document["locked"] = 1
        assert layer.pdf_state(owner, 1).status == "current"
        pdf.unlink()
        assert layer.pdf_state(owner, 1).status == "missing"

        # Apply-time revision wrapper persists both commercial and template
        # fingerprints and installs the final UI/API owners without constructing Tk.
        captured: dict = {}

        def capture(_M, document_id, revision_no, pdf_path, data_snapshot):
            captured.update(data_snapshot)

        service.record_revision = capture

        class DummyApp:
            def __init__(self, *args, **kwargs):
                pass

            def build_help(self):
                pass

            def show_help_topic(self, _key):
                pass

        dummy = SimpleNamespace(App=DummyApp)
        layer.apply(dummy)
        service.record_revision(
            dummy,
            1,
            1,
            temp_path / "dummy.pdf",
            {**document, "items": [item]},
        )
        assert captured.get("_commercial_fingerprint")
        assert captured.get("_template_fingerprint")
        assert captured.get("_release_fingerprint")
        assert dummy.V780_PROFESSIONAL_OFFER_WORKFLOW["canonical_pdf_renderer"]
        assert dummy.V780_PROFESSIONAL_OFFER_WORKFLOW["explicit_sent_confirmation"]
        assert dummy.V780_PROFESSIONAL_OFFER_WORKFLOW["searchable_help_topics"] >= 15

        service.load_document = original_load_document
        service.load_template = original_load_template
        service.record_revision = original_record_revision

    required_topics = {
        "help_start",
        "help_received_offers",
        "help_catalog_pricing",
        "help_issued_offers",
        "help_offer_release",
        "help_prices_vat",
        "help_pdf_revisions",
        "help_outlook",
        "help_data_updates",
        "help_troubleshooting",
    }
    assert required_topics <= set(layer.HELP_TOPICS)
    assert len(layer.HELP_TOPICS) >= 15
    assert all(
        topic.get("title") and topic.get("summary") and topic.get("body")
        for topic in layer.HELP_TOPICS.values()
    )

    # Static contracts: no parallel renderer, no nested idle loop, no automatic
    # "Odesláno" after merely opening a draft.
    for token in (
        "Kontrola a řízené vydání",
        "Zkontrolovat a vydat…",
        "Potvrdit odeslání…",
        "Koncept není odeslaný e-mail",
        "commercial_fingerprint",
        "_release_fingerprint",
        "pdf_renderer.latest_or_render = latest_or_render",
        "M.render_issued_offer_pdf",
        "mail.Display()",
        "HELP_TOPICS",
    ):
        assert token in text, token
    assert "update_idletasks(" not in text
    draft_start = text.index("def _create_professional_outlook_draft")
    draft_end = text.index("\ndef _confirm_sent", draft_start)
    draft_source = text[draft_start:draft_end]
    assert 'service.set_status(M, int(document_id), "Odesláno")' not in draft_source
    sent_start = text.index("def _confirm_sent")
    sent_end = text.index("\ndef _find_outer_row", sent_start)
    assert 'service.set_status(M, int(document_id), "Odesláno")' in text[sent_start:sent_end]

    print(
        "OK 7.8.0: controlled offer preflight/release, canonical PDF "
        "freshness, explicit sent confirmation and searchable help centre"
    )


if __name__ == "__main__":
    main()
