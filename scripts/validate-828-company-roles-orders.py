#!/usr/bin/env python3
"""One-time roles, checked selection, independent orders and Windows UI regression."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ZakazkyApp_base_6.1"))
spec = importlib.util.spec_from_file_location("previous_checks", REPO / "scripts/validate-827-processing-catalogs.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
from price_lists_domain.platform import company_roles as roles
from price_lists_domain.received_orders import service as orders
from price_lists_domain.issued_offers import service as offers


def seed(M):
    with M.db() as con:
        customer = con.execute("INSERT INTO companies(short_name,official_name) VALUES('828 Odběratel','828 Odběratel')").lastrowid
        supplier = con.execute("INSERT INTO companies(short_name,official_name,is_customer,is_supplier) VALUES('828 Dodavatel','828 Dodavatel',0,1)").lastrowid
        both = con.execute("INSERT INTO companies(short_name,official_name,is_customer,is_supplier) VALUES('828 Obojí','828 Obojí',1,1)").lastrowid
        con.execute("INSERT INTO materials(name) VALUES('828 Nosník')")
    document = offers.offer_defaults(M)
    document.update(offers.company_snapshot(M, customer))
    document.update(issue_date="2026-09-17", offer_subject="828 Stavba", global_discount_pct=5)
    items = [dict(name="Nosník", product_code="N-828", internal_name_snapshot="Interní nosník", quantity=3,
                  unit="ks", purchase_unit_price=80, recommended_unit_price=120, discount_pct=10, unit_price=108, vat_rate=21)]
    offer_id = offers.save_document(M, document, items)
    return customer, supplier, both, offer_id


def source_checks(td):
    M = previous.prepare(td, runtime=True)
    customer, supplier, both, offer_id = seed(M)
    # Emulate upgrading the old schema: every existing company is a customer,
    # including archived companies; opening again must preserve manual roles.
    with M.db() as con:
        con.execute("ALTER TABLE companies DROP COLUMN is_customer")
        con.execute("ALTER TABLE companies DROP COLUMN is_supplier")
        roles.ensure_columns(con)
        assert all(tuple(row) == (1, 0) for row in con.execute("SELECT is_customer,is_supplier FROM companies"))
        con.execute("UPDATE companies SET is_customer=0,is_supplier=1 WHERE id=?", (supplier,))
        con.execute("UPDATE companies SET is_supplier=1 WHERE id=?", (both,))
    M.ensure_schema(); M.ensure_schema()
    with M.db() as con:
        assert set(r["id"] for r in roles.choices(con, "supplier")) == {supplier, both}
        assert supplier not in {r["id"] for r in roles.choices(con, "customer")}
        assert roles.resolve(con, "828 Dod", "supplier", supplier) is None
        assert roles.resolve(con, "828 Odběratel", "supplier", customer) is None
        assert roles.resolve(con, "828 Dodavatel", "supplier", customer) == supplier
        previous.rejects(lambda: roles.validate_request(con, {"company_id": customer}))
        previous.rejects(lambda: roles.validate_request(con, {"company_id": supplier, "requested_for_company_id": supplier}))
        roles.validate_request(con, {"company_id": supplier, "requested_for_company_id": customer})
        roles.validate_request(con, {"company_id": customer}, {"company_id": customer})
    original = offers.load_document(M, offer_id)
    draft, lines = orders.draft_from_offer(M, offer_id)
    assert orders.list_documents(M) == [], "Converting/closing a draft wrote an order"
    assert draft["source_offer_number"] == original[0]["document_number"]
    assert lines[0]["unit_price"] == original[1][0]["unit_price"]
    bad = dict(draft, company_id=supplier)
    previous.rejects(lambda: orders.save_document(M, bad, lines))
    previous.rejects(lambda: offers.save_document(M, bad, lines))
    assert orders.list_documents(M) == []
    oid = orders.save_document(M, draft, lines)
    stored, stored_lines = orders.load_document(M, oid)
    assert oid != offer_id and stored["document_number"] == "PO-2026-0001"
    assert stored["source_offer_id"] == offer_id and stored["edit_revision"] == 1
    assert stored["subtotal_net"] == original[0]["subtotal_net"]
    stale = dict(stored)
    stored_lines[0].update(quantity=5, unit_price=0)  # Explicit free price survives.
    stored.update(customer_reference="OBJ 123", due_date="30.09.2026", internal_note="Interně", status="Zpracovává se")
    orders.save_document(M, stored, stored_lines, oid)
    updated, edited = orders.load_document(M, oid)
    assert updated["due_date"] == "2026-09-30" and updated["customer_reference"] == "OBJ 123"
    assert edited[0]["quantity"] == 5 and edited[0]["unit_price"] == 0 and updated["subtotal_net"] == 0
    assert offers.load_document(M, offer_id) == original, "Editing an order mutated its offer"
    previous.rejects(lambda: orders.save_document(M, stale, stored_lines, oid))
    previous.rejects(lambda: offers.save_document(M, updated, stored_lines, oid))
    previous.rejects(lambda: offers.set_status(M, oid, "Přijato"))
    previous.rejects(lambda: orders.save_document(M, updated, stored_lines, offer_id))
    previous.rejects(lambda: orders.save_document(M, dict(updated, due_date="31.02.2026"), stored_lines, oid))
    previous.rejects(lambda: orders.save_document(M, updated, [dict(stored_lines[0], unit_price="nan")], oid))
    previous.rejects(lambda: orders.save_document(M, updated, [], oid))
    # Atomically roll back items/header if the audit write fails.
    with M.db() as con:
        con.execute("CREATE TRIGGER reject_order_history BEFORE INSERT ON business_document_history BEGIN SELECT RAISE(ABORT,'test'); END")
    previous.rejects(lambda: orders.save_document(M, dict(updated, customer_reference="WRONG"), stored_lines, oid))
    assert orders.load_document(M, oid) == (updated, edited)
    with M.db() as con:
        con.execute("DROP TRIGGER reject_order_history")
        con.execute("UPDATE companies SET is_customer=0 WHERE id=?", (customer,))
    orders.save_document(M, updated, edited, oid)  # Historical customer retained.
    previous.rejects(lambda: orders.save_document(M, draft, lines))
    with M.db() as con:
        con.execute("UPDATE companies SET is_customer=1 WHERE id=?", (customer,))
        con.execute("UPDATE business_document_items SET quantity=99 WHERE document_id=?", (offer_id,))
    previous.rejects(lambda: orders.save_document(M, draft, lines))
    offers.delete_document(M, offer_id)
    remaining, _ = orders.load_document(M, oid)
    assert remaining["source_offer_id"] is None and remaining["source_offer_number"] == draft["source_offer_number"]
    manual = orders.defaults(M); manual.update(company_id=customer, issue_date="2026-09-17")
    manual_id = orders.save_document(M, manual, lines)
    assert orders.load_document(M, manual_id)[0]["document_number"] == "PO-2026-0002"
    print("8.0.28: migration, role validation, historical links, offer isolation, order numbering, prices, stale writes and atomic audit OK", flush=True)


def ui_checks(td):
    M = previous.prepare(td, runtime=True)
    customer, supplier, both, offer_id = seed(M)
    M.App.maybe_show_morning_overview = lambda self: None
    errors, warnings = [], []
    M.messagebox.showinfo = lambda *a, **k: None
    M.messagebox.showwarning = lambda *a, **k: warnings.append(a)
    M.messagebox.showerror = lambda *a, **k: errors.append(a)
    M.messagebox.askyesnocancel = lambda *a, **k: False
    M.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    root = M.App()
    settle = previous.settle
    try:
        settle(root, 4)
        for width, height in ((1220, 800), (1920, 1080)):
            root.state("normal"); root.geometry(f"{width}x{height}"); settle(root)
            root.nav["received_orders"].invoke(); settle(root)
            assert root._current_page == "received_orders"
            assert root.tabs["received_orders"].winfo_ismapped()
            buttons = root.main_nav.pack_slaves()
            assert all(b.winfo_x() + b.winfo_width() <= root.main_nav.winfo_width() + 2 for b in buttons)
        dialog = M.CompanyDialog(root, company_id=customer); settle(root)
        assert dialog.is_customer.get() and not dialog.is_supplier.get()
        dialog.is_supplier.set(True); dialog.ok(); settle(root)
        with M.db() as con:
            assert tuple(con.execute("SELECT is_customer,is_supplier FROM companies WHERE id=?", (customer,)).fetchone()) == (1, 1)
        with M.db() as con:
            con.execute("UPDATE companies SET is_supplier=0 WHERE id=?", (customer,))
        request = M.RequestDialog(root); settle(root)
        assert supplier in {r["id"] for r in request.companies} and customer not in {r["id"] for r in request.companies}
        request.company.set("828 Odběratel"); request.company_box.selected_payload = customer
        assert request.company_id() is None
        request.company.set("828 Dodavatel"); assert request.company_id() == supplier
        request.requested_for.set("828 Dodavatel"); assert request.requested_for_id() is None
        request.requested_for.set("828 Odběratel"); assert request.requested_for_id() == customer
        request.destroy(); settle(root)
        root.show_page("issued_offers"); root.refresh_issued_offers(); settle(root)
        root.issued_offer_tree.selection_set(f"bo{offer_id}")
        editor = root.create_received_order_from_offer(); settle(root)
        assert editor and len(editor.items) == 1
        editor.win.destroy(); settle(root)
        assert orders.list_documents(M) == []
        editor = root.open_received_order_editor(source_offer_id=offer_id); settle(root)
        editor.items[0].update(quantity=7, unit_price=99, total_price=693)
        editor.vars["customer_reference"].set("OBJ-UI")
        oid = editor.save(); assert oid, warnings
        editor.win.destroy(); settle(root)
        editor = root.open_received_order_editor(oid); settle(root)
        assert editor.vars["customer_reference"].get() == "OBJ-UI" and editor.items[0]["quantity"] == 7
        assert editor.items[0]["unit_price"] == 99
        editor.win.destroy(); settle(root)
        root.show_page("received_orders"); root.refresh_received_orders(); settle(root)
        assert root.received_order_tree.exists(f"ro{oid}")
        root.show_page("companies"); root.refresh_companies(); settle(root)
        assert "Dodavatel" in root.company_tree["columns"]
        assert root.company_tree.set(f"c{supplier}", "Dodavatel") == "Ano"
        assert not errors, errors
        print("8.0.28: Windows role checkboxes, filtered autocomplete, order conversion/cancel/save/reopen, full table and navigation OK", flush=True)
    finally:
        for job in root.tk.splitlist(root.tk.call("after", "info")):
            try: root.after_cancel(job)
            except Exception: pass
        try: root.destroy()
        except (M.tk.TclError, TypeError): pass


if __name__ == "__main__":
    if "--source-worker" in sys.argv:
        source_checks(sys.argv[-1])
    elif "--ui-worker" in sys.argv:
        ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix="turto-orders-828-") as td:
            subprocess.run([sys.executable, "-B", __file__, "--source-worker", str(Path(td) / "source")], check=True)
            if "--source-only" not in sys.argv:
                subprocess.run([sys.executable, "-B", __file__, "--ui-worker", str(Path(td) / "ui")], check=True)
