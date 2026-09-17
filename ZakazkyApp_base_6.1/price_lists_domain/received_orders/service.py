"""Received customer orders are independent, editable copies of issued offers."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
import hashlib
import json

from ..issued_offers import service as offers
from ..platform import company_roles

DOCUMENT_TYPE = "received_order"
DIRECTION = "received"
STATUSES = ("Přijato", "Zpracovává se", "Vyřízeno", "Zrušeno")
HEADER_FIELDS = (
    "company_id", "customer_contact_id", "project_id", "action_id", "issue_date", "due_date",
    "status", "currency", "offer_subject", "customer_reference", "delivery_address",
    "payment_terms", "delivery_terms", "delivery_time", "customer_note", "internal_note",
    "salesperson_snapshot", "vat_mode", "global_discount_pct", "items_subtotal", "subtotal_net",
    "vat_total", "total_gross", "total_value", "source_offer_id", "source_offer_number",
) + tuple("customer_" + key + "_snapshot" for key in ("name", "address", "ico", "dic", "contact", "email", "phone"))
ITEM_FIELDS = (
    "position", "row_type", "product_code", "item_key", "name", "description", "quantity", "unit",
    "purchase_unit_price", "purchase_currency", "margin_pct", "recommended_unit_price", "discount_pct",
    "unit_price", "total_price", "vat_rate", "show_recommended_price", "category_id", "subgroup_id",
    "catalog_product_id", "internal_code_snapshot", "internal_name_snapshot", "category_name_snapshot", "subgroup_name_snapshot", "price_source_label",
    "source_price_list_item_id", "source_supplier_offer_item_id", "line_note",
    "image_asset_key_snapshot", "image_file_snapshot",
)


def numeric(value, label="Číslo"):
    try:
        result = Decimal(str(value if value is not None else 0).replace("\u00a0", "").replace(" ", "").replace(",", "."))
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label}: vyplňte platné číslo.") from None


def normalize_item(item, position=1):
    row = {key: item.get(key) for key in ITEM_FIELDS}
    row.update(position=position, row_type=item.get("row_type") or "product")
    if row["row_type"] not in offers.ROW_TYPES:
        raise ValueError("Neplatný typ položky.")
    row["name"] = str(item.get("name") or "").strip()
    if not row["name"]:
        raise ValueError("Vyplňte název položky.")
    for key in ("quantity", "purchase_unit_price", "margin_pct", "recommended_unit_price", "discount_pct", "unit_price", "vat_rate"):
        row[key] = float(numeric(item.get(key, 0), key))
        if not isfinite(row[key]):
            raise ValueError("Číselná hodnota je příliš vysoká.")
    if row["row_type"] in {"heading", "text"}:
        row.update(quantity=0, unit_price=0, total_price=0, vat_rate=0)
    else:
        if row["quantity"] < 0 or row["unit_price"] < 0 or not 0 <= row["vat_rate"] <= 100:
            raise ValueError("Množství a cena nesmí být záporné; DPH musí být od 0 do 100 %.")
        # unit_price is the agreed price AFTER the line discount. Never reprice
        # it from purchase cost/margin, including an explicitly free line.
        row["total_price"] = row["quantity"] * row["unit_price"]
        if not isfinite(row["total_price"]):
            raise ValueError("Celková cena je příliš vysoká.")
    for key in ("description", "product_code", "item_key", "unit", "purchase_currency", "internal_code_snapshot",
                "internal_name_snapshot", "category_name_snapshot", "subgroup_name_snapshot", "price_source_label", "line_note", "image_asset_key_snapshot", "image_file_snapshot"):
        row[key] = str(row.get(key) or "")
    row["show_recommended_price"] = int(bool(row.get("show_recommended_price")))
    return row


def totals(items, discount=0):
    discount = float(numeric(discount, "Celková sleva"))
    if not -100 <= discount <= 100:
        raise ValueError("Celková sleva musí být od −100 do 100 %.")
    # Match issued-offer precision. Rounding each row to cents would change the
    # agreed amount when copying fractional quantities/prices from an offer.
    subtotal = sum(float(numeric(row["total_price"])) for row in items)
    factor = 1.0 - discount / 100.0
    net = subtotal * factor
    vat = sum(float(numeric(row["total_price"])) * factor * float(numeric(row["vat_rate"])) / 100.0
              for row in items if row["row_type"] not in {"heading", "text"})
    if not all(isfinite(value) for value in (subtotal, net, vat, net + vat)):
        raise ValueError("Celková cena je příliš vysoká.")
    return dict(items_subtotal=round(subtotal, 6), subtotal_net=round(net, 6), vat_total=round(vat, 6),
                total_gross=round(net + vat, 6), total_value=round(net, 6))


def defaults(M):
    values = {key: value for key, value in offers.offer_defaults(M).items() if key in HEADER_FIELDS}
    values.update(status="Přijato", issue_date=date.today().isoformat(), due_date="",
                  source_offer_id=None, source_offer_number="", edit_revision=0)
    return values


def fingerprint(document, items):
    # Joined display names may change without changing the underlying offer.
    data = ({key: document.get(key) for key in HEADER_FIELDS if not key.startswith("source_")},
            [{key: row.get(key) for key in ITEM_FIELDS} for row in items])
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def draft_from_offer(M, source_id):
    with M.db() as con:
        raw = con.execute("SELECT * FROM business_documents WHERE id=? AND document_type='issued_offer' AND direction='issued'", (source_id,)).fetchone()
        if not raw:
            raise ValueError("Výchozí vydaná nabídka nebyla nalezena.")
        raw_document = dict(raw)
        raw_items = [dict(row) for row in con.execute("SELECT * FROM business_document_items WHERE document_id=? ORDER BY position,id", (source_id,))]
    from ..issued_offers.customer_text import sanitize_snapshot
    document, items = sanitize_snapshot(raw_document, raw_items)
    result = defaults(M)
    result.update({key: document.get(key) for key in HEADER_FIELDS if key in document})
    result.update(issue_date=date.today().isoformat(), due_date="", status="Přijato", customer_reference="",
                  source_offer_id=int(source_id), source_offer_number=document["document_number"],
                  _source_fingerprint=fingerprint(raw_document, raw_items))
    return result, [normalize_item(dict(row), index) for index, row in enumerate(items, 1)]


def load_document(M, document_id):
    with M.db() as con:
        row = con.execute("SELECT * FROM business_documents WHERE id=? AND document_type=? AND direction=?",
                          (document_id, DOCUMENT_TYPE, DIRECTION)).fetchone()
        if not row:
            raise ValueError("Přijatá objednávka nebyla nalezena.")
        items = con.execute("SELECT * FROM business_document_items WHERE document_id=? ORDER BY position,id", (document_id,)).fetchall()
    return dict(row), [dict(item) for item in items]


def _next_number(con, issue_date):
    year = int(issue_date[:4])
    prefix = f"PO-{year}-"
    row = con.execute("SELECT last_number FROM document_sequences WHERE document_type=? AND calendar_year=?", (DOCUMENT_TYPE, year)).fetchone()
    used = [int(r[0][len(prefix):]) for r in con.execute("SELECT document_number FROM business_documents WHERE document_type=? AND document_number LIKE ?", (DOCUMENT_TYPE, prefix + "%")) if r[0][len(prefix):].isdigit()]
    number = max([int(row[0]) if row else 0] + used) + 1
    con.execute("""INSERT INTO document_sequences(document_type,calendar_year,last_number) VALUES(?,?,?)
        ON CONFLICT(document_type,calendar_year) DO UPDATE SET last_number=excluded.last_number,updated_at=CURRENT_TIMESTAMP""", (DOCUMENT_TYPE, year, number))
    return f"{prefix}{number:04d}"


def save_document(M, values, items, document_id=None):
    data = defaults(M)
    data.update(values)
    for field, label in (("issue_date", "Datum přijetí"), ("due_date", "Termín dodání")):
        raw = str(data.get(field) or "").strip()
        parsed = offers.iso_date(raw, "")
        if (raw and not parsed) or (field == "issue_date" and not parsed):
            raise ValueError(f"{label}: vyplňte platné datum.")
        data[field] = parsed
    if data.get("status") not in STATUSES:
        raise ValueError("Neplatný stav objednávky.")
    rows = [normalize_item(row, i) for i, row in enumerate(items, 1)]
    if not rows or not any(row["row_type"] not in {"heading", "text"} for row in rows):
        raise ValueError("Objednávka musí obsahovat alespoň jednu položku.")
    data.update(totals(rows, data.get("global_discount_pct", 0)))
    data["global_discount_pct"] = float(numeric(data.get("global_discount_pct", 0)))
    data["currency"] = str(data.get("currency") or "CZK").strip().upper()
    now = datetime.now().isoformat(timespec="microseconds")
    user = offers.active_user(M)
    with M.db() as con:
        con.execute("BEGIN IMMEDIATE")
        old = None
        source = None
        if document_id:
            old = con.execute("SELECT * FROM business_documents WHERE id=? AND document_type=? AND direction=?", (document_id, DOCUMENT_TYPE, DIRECTION)).fetchone()
            if not old:
                raise ValueError("Přijatá objednávka už neexistuje.")
            if int(old["edit_revision"]) != int(values.get("edit_revision", -1)):
                raise ValueError("Objednávku mezitím změnil jiný uživatel. Zavřete ji a otevřete aktuální verzi.")
            data["source_offer_id"] = old["source_offer_id"]
            data["source_offer_number"] = old["source_offer_number"]
        company_roles.require(con, data.get("company_id"), "customer", old["company_id"] if old else None)
        if not old and data.get("source_offer_id"):
            source = con.execute("SELECT * FROM business_documents WHERE id=? AND document_type='issued_offer' AND direction='issued'", (data["source_offer_id"],)).fetchone()
            if not source:
                raise ValueError("Výchozí nabídka už neexistuje. Převod objednávky nelze uložit.")
            source_items = [dict(row) for row in con.execute("SELECT * FROM business_document_items WHERE document_id=? ORDER BY position,id", (source["id"],))]
            if values.get("_source_fingerprint") != fingerprint(dict(source), source_items):
                raise ValueError("Výchozí nabídka se mezitím změnila. Spusťte převod z aktuální nabídky znovu.")
            data["source_offer_number"] = source["document_number"]
        previous_customer = old["company_id"] if old else (source["company_id"] if source else None)
        if data["company_id"] != previous_customer:
            customer = con.execute("SELECT * FROM companies WHERE id=?", (data["company_id"],)).fetchone()
            for key, field in (("name", "official_name"), ("address", "address"), ("ico", "ico"), ("dic", "dic")):
                data[f"customer_{key}_snapshot"] = customer[field] or ""
            if old or source:
                data["customer_contact_id"] = None
                for key in ("contact", "email", "phone"):
                    data[f"customer_{key}_snapshot"] = ""
        if old:
            fields = HEADER_FIELDS + ("updated_at", "updated_by", "edit_revision")
            data.update(updated_at=now, updated_by=user, edit_revision=int(old["edit_revision"]) + 1)
            con.execute(f"UPDATE business_documents SET {','.join(key+'=?' for key in fields)} WHERE id=?", tuple(data.get(key) for key in fields) + (document_id,))
            con.execute("DELETE FROM business_document_items WHERE document_id=?", (document_id,))
        else:
            data.update(document_number=_next_number(con, data["issue_date"]), document_type=DOCUMENT_TYPE, direction=DIRECTION,
                        created_at=now, updated_at=now, created_by=user, updated_by=user, edit_revision=1)
            fields = HEADER_FIELDS + ("document_number", "document_type", "direction", "created_at", "updated_at", "created_by", "updated_by", "edit_revision")
            document_id = int(con.execute(f"INSERT INTO business_documents({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", tuple(data.get(key) for key in fields)).lastrowid)
        fields = ("document_id",) + ITEM_FIELDS
        for row in rows:
            con.execute(f"INSERT INTO business_document_items({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", (document_id,) + tuple(row[key] for key in ITEM_FIELDS))
        con.execute("""INSERT INTO business_document_history(document_id,event_type,old_status,new_status,note,user_name)
            VALUES(?,?,?,?,?,?)""", (document_id, "edited" if old else "created", old["status"] if old else "", data["status"],
                "Objednávka upravena" if old else (f"Převod z nabídky {data['source_offer_number']}" if data.get("source_offer_id") else "Objednávka vytvořena"), user))
    return document_id


def list_documents(M):
    with M.db() as con:
        return [dict(row) for row in con.execute("SELECT * FROM business_documents WHERE document_type=? AND direction=? ORDER BY issue_date DESC,id DESC", (DOCUMENT_TYPE, DIRECTION))]
