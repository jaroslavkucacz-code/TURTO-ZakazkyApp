"""Business services for TURTO CRM issued offers.

The service owns numbering, snapshots, calculations, persistence, archive paths,
revisions and status history. UI and PDF rendering call this module instead of
writing business-document tables directly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

DOCUMENT_TYPE = "issued_offer"
DOCUMENT_DIRECTION = "issued"
STATUSES = (
    "Rozpracováno",
    "Připraveno",
    "Odesláno",
    "Přijato",
    "Zamítnuto",
    "Zrušeno",
)
TERMINAL_STATUSES = {"Odesláno", "Přijato", "Zamítnuto", "Zrušeno"}
ROW_TYPES = {
    "product": "Produkt",
    "service": "Služba",
    "delivery": "Doprava",
    "heading": "Nadpis oddílu",
    "text": "Textová poznámka",
}


@dataclass(frozen=True)
class Totals:
    items_subtotal: float
    global_discount: float
    subtotal_net: float
    vat_total: float
    total_gross: float


def number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value or 0)
    except Exception:
        return float(default)


def iso_date(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return default
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except Exception:
            pass
    return default


def active_user(M) -> str:
    try:
        app = getattr(M, "_active_app", None)
        variable = getattr(app, "active_user", None)
        if variable is not None:
            value = str(variable.get() or "").strip()
            if value:
                return value
    except Exception:
        pass
    try:
        return str(M.get_setting("active_user", "") or "").strip()
    except Exception:
        return ""


def get_setting(M, key: str, default: str = "") -> str:
    try:
        return str(M.get_setting(key, default) or default)
    except Exception:
        return str(default)


def set_setting(M, key: str, value: Any) -> None:
    M.set_setting(key, str(value if value is not None else ""))


def archive_root(M) -> Path:
    configured = get_setting(M, "issued_offer_archive_root", "").strip()
    root = Path(configured) if configured else Path(M.DATA_ROOT) / "Vydane nabidky"
    root.mkdir(parents=True, exist_ok=True)
    return root


def template_assets_root(M) -> Path:
    root = Path(M.DATA_ROOT) / "Sablony" / "Vydane nabidky"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_filename(value: Any, fallback: str = "dokument", max_length: int = 90) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", " ", text)
    text = " ".join(text.split()).strip(" .")
    if not text:
        text = fallback
    return text[:max_length].rstrip(" .") or fallback


def copy_template_asset(M, source: str | Path, label: str) -> Path:
    path = Path(source)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"}:
        raise ValueError("Podporované formáty jsou PNG, JPG a jednostránkové PDF.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    target = template_assets_root(M) / f"{safe_filename(label, 'sablona', 45)}_{digest}{path.suffix.lower()}"
    if not target.exists():
        shutil.copy2(path, target)
    return target


def issuer_defaults(M) -> dict[str, str]:
    return {
        "issuer_name_snapshot": get_setting(M, "issued_offer_issuer_name", "TURTO s.r.o."),
        "issuer_address_snapshot": get_setting(M, "issued_offer_issuer_address", "Kaprova 42/14, 110 00 Praha 1"),
        "issuer_ico_snapshot": get_setting(M, "issued_offer_issuer_ico", "24196231"),
        "issuer_dic_snapshot": get_setting(M, "issued_offer_issuer_dic", "CZ24196231"),
        "issuer_contact_snapshot": get_setting(M, "issued_offer_issuer_contact", active_user(M)),
        "issuer_email_snapshot": get_setting(M, "issued_offer_issuer_email", "info@turto.cz"),
        "issuer_phone_snapshot": get_setting(M, "issued_offer_issuer_phone", ""),
        "issuer_bank_snapshot": get_setting(M, "issued_offer_issuer_bank", ""),
    }


def offer_defaults(M) -> dict[str, Any]:
    today = date.today()
    validity = max(1, int(number(get_setting(M, "issued_offer_default_validity_days", "14"), 14)))
    result: dict[str, Any] = {
        "document_type": DOCUMENT_TYPE,
        "direction": DOCUMENT_DIRECTION,
        "document_number": "",
        "issue_date": today.isoformat(),
        "valid_to": (today + timedelta(days=validity)).isoformat(),
        "status": "Rozpracováno",
        "currency": get_setting(M, "issued_offer_default_currency", "CZK") or "CZK",
        "vat_mode": "without",
        "global_discount_pct": 0.0,
        "offer_subject": "",
        "customer_reference": "",
        "payment_terms": get_setting(M, "issued_offer_default_payment_terms", "Splatnost 30 dní."),
        "delivery_terms": get_setting(M, "issued_offer_default_delivery_terms", ""),
        "delivery_time": get_setting(M, "issued_offer_default_delivery_time", ""),
        "customer_note": get_setting(M, "issued_offer_default_customer_note", ""),
        "internal_note": "",
        "salesperson_snapshot": active_user(M),
        "template_id": default_template_id(M),
        "company_id": None,
        "customer_contact_id": None,
        "project_id": None,
        "action_id": None,
        "delivery_address": "",
    }
    result.update(issuer_defaults(M))
    return result


def default_template_id(M) -> int | None:
    with M.db() as con:
        row = con.execute(
            """SELECT id FROM business_document_templates
               WHERE document_type=? AND active=1
               ORDER BY is_default DESC,id LIMIT 1""",
            (DOCUMENT_TYPE,),
        ).fetchone()
    return int(row[0]) if row else None


def load_template(M, template_id: int | None = None) -> dict[str, Any]:
    with M.db() as con:
        if template_id:
            row = con.execute("SELECT * FROM business_document_templates WHERE id=?", (template_id,)).fetchone()
        else:
            row = con.execute(
                """SELECT * FROM business_document_templates
                   WHERE document_type=? AND active=1
                   ORDER BY is_default DESC,id LIMIT 1""",
                (DOCUMENT_TYPE,),
            ).fetchone()
    return dict(row) if row else {
        "id": None,
        "name": "Standardní nabídka TURTO",
        "header_path": "",
        "footer_path": "",
        "header_height_mm": 25.0,
        "footer_height_mm": 14.0,
        "margin_left_mm": 14.0,
        "margin_right_mm": 14.0,
        "body_top_gap_mm": 5.0,
        "body_bottom_gap_mm": 5.0,
        "header_every_page": 1,
        "footer_every_page": 1,
    }


def list_templates(M, include_inactive: bool = False) -> list[dict[str, Any]]:
    with M.db() as con:
        rows = con.execute(
            """SELECT * FROM business_document_templates
               WHERE document_type=? AND (?=1 OR active=1)
               ORDER BY is_default DESC,active DESC,name COLLATE CZECH,id""",
            (DOCUMENT_TYPE, 1 if include_inactive else 0),
        ).fetchall()
    return [dict(row) for row in rows]


def save_template(M, values: dict[str, Any], template_id: int | None = None) -> int:
    name = str(values.get("name") or "").strip()
    if not name:
        raise ValueError("Vyplňte název šablony.")
    fields = (
        "name", "active", "is_default", "header_path", "footer_path",
        "header_height_mm", "footer_height_mm", "margin_left_mm", "margin_right_mm",
        "body_top_gap_mm", "body_bottom_gap_mm", "header_every_page", "footer_every_page",
    )
    data = {
        "name": name,
        "active": 1 if values.get("active", True) else 0,
        "is_default": 1 if values.get("is_default", False) else 0,
        "header_path": str(values.get("header_path") or ""),
        "footer_path": str(values.get("footer_path") or ""),
        "header_height_mm": max(0.0, number(values.get("header_height_mm"), 25)),
        "footer_height_mm": max(0.0, number(values.get("footer_height_mm"), 14)),
        "margin_left_mm": max(5.0, number(values.get("margin_left_mm"), 14)),
        "margin_right_mm": max(5.0, number(values.get("margin_right_mm"), 14)),
        "body_top_gap_mm": max(0.0, number(values.get("body_top_gap_mm"), 5)),
        "body_bottom_gap_mm": max(0.0, number(values.get("body_bottom_gap_mm"), 5)),
        "header_every_page": 1 if values.get("header_every_page", True) else 0,
        "footer_every_page": 1 if values.get("footer_every_page", True) else 0,
    }
    with M.db() as con:
        if template_id:
            assignments = ",".join(f"{field}=?" for field in fields)
            con.execute(
                f"UPDATE business_document_templates SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=?",
                tuple(data[field] for field in fields) + (int(template_id),),
            )
            result = int(template_id)
        else:
            columns = ",".join(fields)
            placeholders = ",".join("?" for _ in fields)
            result = int(con.execute(
                f"INSERT INTO business_document_templates({columns}) VALUES({placeholders})",
                tuple(data[field] for field in fields),
            ).lastrowid)
        if data["is_default"]:
            con.execute(
                """UPDATE business_document_templates
                   SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END
                   WHERE document_type=?""",
                (result, DOCUMENT_TYPE),
            )
    return result


def deactivate_template(M, template_id: int) -> None:
    with M.db() as con:
        used = con.execute("SELECT COUNT(*) FROM business_documents WHERE template_id=?", (template_id,)).fetchone()[0]
        if used:
            con.execute(
                "UPDATE business_document_templates SET active=0,is_default=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (template_id,),
            )
        else:
            con.execute("DELETE FROM business_document_templates WHERE id=?", (template_id,))
        default_row = con.execute(
            """SELECT id FROM business_document_templates
               WHERE document_type=? AND active=1 ORDER BY is_default DESC,id LIMIT 1""",
            (DOCUMENT_TYPE,),
        ).fetchone()
        if default_row:
            con.execute(
                """UPDATE business_document_templates
                   SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END
                   WHERE document_type=?""",
                (default_row[0], DOCUMENT_TYPE),
            )


def company_snapshot(M, company_id: int | None) -> dict[str, Any]:
    if not company_id:
        return {
            "company_id": None,
            "customer_name_snapshot": "",
            "customer_address_snapshot": "",
            "customer_ico_snapshot": "",
            "customer_dic_snapshot": "",
        }
    with M.db() as con:
        row = con.execute("SELECT * FROM companies WHERE id=?", (int(company_id),)).fetchone()
    if not row:
        return company_snapshot(M, None)
    values = dict(row)
    name = str(values.get("official_name") or values.get("short_name") or "").strip()
    return {
        "company_id": int(company_id),
        "customer_name_snapshot": name,
        "customer_address_snapshot": str(values.get("address") or ""),
        "customer_ico_snapshot": str(values.get("ico") or ""),
        "customer_dic_snapshot": str(values.get("dic") or ""),
    }


def contact_snapshot(M, contact_id: int | None) -> dict[str, Any]:
    if not contact_id:
        return {
            "customer_contact_id": None,
            "customer_contact_snapshot": "",
            "customer_email_snapshot": "",
            "customer_phone_snapshot": "",
        }
    with M.db() as con:
        row = con.execute("SELECT * FROM people WHERE id=?", (int(contact_id),)).fetchone()
    if not row:
        return contact_snapshot(M, None)
    values = dict(row)
    return {
        "customer_contact_id": int(contact_id),
        "customer_contact_snapshot": str(values.get("name") or ""),
        "customer_email_snapshot": str(values.get("email") or ""),
        "customer_phone_snapshot": str(values.get("phone") or ""),
    }


def normalize_item(raw: dict[str, Any], position: int | None = None, recalculate_sale: bool = False) -> dict[str, Any]:
    item = dict(raw or {})
    row_type = str(item.get("row_type") or "product").strip().lower()
    if row_type not in ROW_TYPES:
        row_type = "product"
    item["row_type"] = row_type
    if position is not None:
        item["position"] = int(position)
    item["quantity"] = max(0.0, number(item.get("quantity"), 1 if row_type in {"product", "service", "delivery"} else 0))
    item["purchase_unit_price"] = number(item.get("purchase_unit_price"))
    item["margin_pct"] = number(item.get("margin_pct"))
    item["recommended_unit_price"] = number(item.get("recommended_unit_price"))
    item["discount_pct"] = number(item.get("discount_pct"))
    item["unit_price"] = number(item.get("unit_price"))
    item["vat_rate"] = max(0.0, number(item.get("vat_rate"), 21))
    item["show_recommended_price"] = 1 if item.get("show_recommended_price", 1) else 0

    if row_type in {"heading", "text"}:
        item["quantity"] = 0.0
        item["purchase_unit_price"] = 0.0
        item["recommended_unit_price"] = 0.0
        item["discount_pct"] = 0.0
        item["unit_price"] = 0.0
        item["total_price"] = 0.0
        return item

    recommended = item["purchase_unit_price"] * (1.0 + item["margin_pct"] / 100.0)
    if recalculate_sale or item["recommended_unit_price"] <= 0:
        item["recommended_unit_price"] = recommended
    if recalculate_sale or item["unit_price"] <= 0:
        item["unit_price"] = item["recommended_unit_price"] * (1.0 - item["discount_pct"] / 100.0)
    item["total_price"] = item["quantity"] * item["unit_price"]
    return item


def calculate_totals(items: Iterable[dict[str, Any]], global_discount_pct: Any = 0) -> Totals:
    normalized = [normalize_item(dict(item)) for item in items]
    items_subtotal = sum(number(item.get("total_price")) for item in normalized)
    discount_pct = min(100.0, max(-100.0, number(global_discount_pct)))
    global_discount = items_subtotal * discount_pct / 100.0
    factor = 1.0 - discount_pct / 100.0
    subtotal_net = items_subtotal * factor
    vat_total = sum(
        number(item.get("total_price")) * factor * number(item.get("vat_rate"), 21) / 100.0
        for item in normalized
        if item.get("row_type") not in {"heading", "text"}
    )
    return Totals(
        items_subtotal=round(items_subtotal, 6),
        global_discount=round(global_discount, 6),
        subtotal_net=round(subtotal_net, 6),
        vat_total=round(vat_total, 6),
        total_gross=round(subtotal_net + vat_total, 6),
    )



def draft_from_supplier_offer(M, offer_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build an unsaved issued-offer draft from one received supplier offer.

    The source rows are copied as immutable purchase-price snapshots. Even when
    an older database row still has a legacy ``catalog_product_id`` linkage, the
    new issued line deliberately stores ``catalog_product_id=None``. This action
    therefore never creates, updates, or depends on a catalogue product.
    """
    offer_id = int(offer_id)
    with M.db() as con:
        offer_row = con.execute(
            """SELECT o.*,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),
                               nullif(trim(o.supplier_name),''),'') supplier
                 FROM supplier_offers o
                 LEFT JOIN companies c ON c.id=o.supplier_company_id
                WHERE o.id=?""",
            (offer_id,),
        ).fetchone()
        if not offer_row:
            raise ValueError("Přijatá nabídka už v databázi neexistuje.")

        item_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(supplier_offer_items)")}
        order_sql = "position,id" if "position" in item_columns else "id"
        item_rows = con.execute(
            f"SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY {order_sql}",
            (offer_id,),
        ).fetchall()

        offer = dict(offer_row)
        action_id = int(offer["action_id"]) if offer.get("action_id") else None
        project_id = int(offer["project_id"]) if offer.get("project_id") else None
        request_id = int(offer["request_id"]) if offer.get("request_id") else None

        if request_id and not action_id:
            request_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(requests)")}
            if "action_id" in request_columns:
                request = con.execute("SELECT action_id FROM requests WHERE id=?", (request_id,)).fetchone()
                if request and request[0]:
                    action_id = int(request[0])

        action_name = ""
        if action_id:
            action_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(actions)")}
            select_parts = ["name" if "name" in action_columns else "'' name"]
            select_parts.append("project_id" if "project_id" in action_columns else "NULL project_id")
            action = con.execute(
                f"SELECT {','.join(select_parts)} FROM actions WHERE id=?",
                (action_id,),
            ).fetchone()
            if action:
                action_name = str(action["name"] or "")
                if not project_id and action["project_id"]:
                    project_id = int(action["project_id"])

        project_name = ""
        if project_id:
            project_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(projects)")}
            if "name" in project_columns:
                project = con.execute("SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
                if project:
                    project_name = str(project[0] or "")

    supplier = str(offer.get("supplier") or "").strip()
    source_reference = str(offer.get("offer_number") or offer.get("reference") or f"ID {offer_id}").strip()
    currency = str(offer.get("currency") or "CZK").strip().upper() or "CZK"
    source_label = f"Přijatá nabídka {source_reference}"

    document = offer_defaults(M)
    document.update(
        company_id=None,
        customer_contact_id=None,
        customer_name_snapshot="",
        customer_contact_snapshot="",
        project_id=project_id,
        action_id=action_id,
        project_name=project_name,
        action_name=action_name,
        currency=currency,
        offer_subject=project_name or action_name or "",
        customer_reference="",
        internal_note=(
            f"Zdroj: {source_label}"
            + (f" · dodavatel {supplier}" if supplier else "")
            + f" · interní ID {offer_id}. Položky byly převzaty bez zápisu do Katalogu produktů."
        ),
    )

    from ..platform import product_catalog

    items: list[dict[str, Any]] = []
    for position, source_row in enumerate(item_rows, 1):
        row = dict(source_row)
        purchase = number(row.get("unit_price"))
        if purchase <= 0:
            purchase = number(row.get("original_unit_price"))
        quantity = number(row.get("quantity"), 1)
        if quantity <= 0:
            quantity = 1.0
        category_id = int(row["category_id"]) if row.get("category_id") else None
        subgroup_id = int(row["subgroup_id"]) if row.get("subgroup_id") else None
        policy = product_catalog.pricing_policy(M, category_id, subgroup_id)
        recommended, sale = product_catalog.calculate_prices(
            purchase, policy["margin_pct"], policy["discount_pct"]
        )
        product_code = str(row.get("product_code") or row.get("item_key") or "").strip()
        item_key = str(row.get("item_key") or product_code).strip()
        name = str(row.get("original_name") or item_key or product_code or "Položka").strip()
        description = str(row.get("details") or "").strip()
        item = normalize_item(
            {
                "position": position,
                "row_type": "product",
                "product_code": product_code,
                "item_key": item_key,
                "name": name,
                "description": description,
                "quantity": quantity,
                "unit": str(row.get("unit") or "ks").strip() or "ks",
                "purchase_unit_price": purchase,
                "purchase_currency": currency,
                "margin_pct": policy["margin_pct"],
                "recommended_unit_price": recommended,
                "discount_pct": policy["discount_pct"],
                "unit_price": sale,
                "total_price": quantity * sale,
                "vat_rate": 21.0,
                "show_recommended_price": 1 if policy.get("show_recommended_price", True) else 0,
                "category_id": category_id,
                "subgroup_id": subgroup_id,
                "catalog_product_id": None,
                "internal_code_snapshot": product_code,
                "internal_name_snapshot": name,
                "price_source_label": source_label + (f" · {supplier}" if supplier else ""),
                "source_price_list_item_id": None,
                "source_supplier_offer_item_id": row.get("id"),
                "line_note": "",
            },
            position,
        )
        items.append(item)
    return document, items


def _sequence_number(con, M, issue_date: str) -> str:
    parsed = iso_date(issue_date, date.today().isoformat())
    year = int(parsed[:4])
    prefix = get_setting(M, "issued_offer_number_prefix", "CN").strip() or "CN"
    width = max(3, min(8, int(number(get_setting(M, "issued_offer_number_width", "4"), 4))))
    row = con.execute(
        "SELECT last_number FROM document_sequences WHERE document_type=? AND calendar_year=?",
        (DOCUMENT_TYPE, year),
    ).fetchone()
    next_value = int(row[0] if row else 0) + 1
    con.execute(
        """INSERT INTO document_sequences(document_type,calendar_year,last_number,updated_at)
           VALUES(?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(document_type,calendar_year) DO UPDATE SET
             last_number=excluded.last_number,updated_at=CURRENT_TIMESTAMP""",
        (DOCUMENT_TYPE, year, next_value),
    )
    return f"{prefix}-{year}-{next_value:0{width}d}"


def save_document(M, values: dict[str, Any], items: Iterable[dict[str, Any]], document_id: int | None = None) -> int:
    data = offer_defaults(M)
    data.update(values or {})
    data["document_type"] = DOCUMENT_TYPE
    data["direction"] = DOCUMENT_DIRECTION
    data["issue_date"] = iso_date(data.get("issue_date"), date.today().isoformat())
    data["valid_to"] = iso_date(data.get("valid_to"), "")
    data["status"] = str(data.get("status") or "Rozpracováno")
    if data["status"] not in STATUSES:
        data["status"] = "Rozpracováno"
    data["currency"] = str(data.get("currency") or "CZK").strip().upper()
    data["global_discount_pct"] = number(data.get("global_discount_pct"))
    data["locked"] = 1 if data["status"] in TERMINAL_STATUSES else 0
    data["vat_mode"] = str(data.get("vat_mode") or "without")
    normalized_items = [normalize_item(dict(item), index) for index, item in enumerate(items, 1)]
    totals = calculate_totals(normalized_items, data["global_discount_pct"])
    data.update(
        items_subtotal=totals.items_subtotal,
        subtotal_net=totals.subtotal_net,
        vat_total=totals.vat_total,
        total_gross=totals.total_gross,
        total_value=totals.subtotal_net,
    )
    user = active_user(M)
    now = datetime.now().isoformat(timespec="seconds")
    data["updated_at"] = now
    if data["status"] == "Odesláno" and not data.get("sent_at"):
        data["sent_at"] = now
    if data["status"] == "Přijato" and not data.get("accepted_at"):
        data["accepted_at"] = now
    if data["status"] == "Zamítnuto" and not data.get("rejected_at"):
        data["rejected_at"] = now

    fields = (
        "document_type", "direction", "document_number", "issue_date", "valid_to",
        "company_id", "customer_contact_id", "project_id", "action_id", "status", "currency",
        "offer_subject", "customer_name_snapshot", "customer_address_snapshot",
        "customer_ico_snapshot", "customer_dic_snapshot", "customer_contact_snapshot",
        "customer_email_snapshot", "customer_phone_snapshot", "issuer_name_snapshot",
        "issuer_address_snapshot", "issuer_ico_snapshot", "issuer_dic_snapshot",
        "issuer_contact_snapshot", "issuer_email_snapshot", "issuer_phone_snapshot",
        "issuer_bank_snapshot", "salesperson_snapshot", "customer_reference", "delivery_address",
        "payment_terms", "delivery_terms", "delivery_time", "customer_note", "internal_note",
        "vat_mode", "global_discount_pct", "items_subtotal", "subtotal_net", "vat_total",
        "total_gross", "total_value", "template_id", "locked", "sent_at", "accepted_at",
        "rejected_at", "created_by", "updated_by", "updated_at",
    )

    with M.db() as con:
        old_status = ""
        if document_id:
            old = con.execute("SELECT status,document_number,created_by FROM business_documents WHERE id=?", (document_id,)).fetchone()
            if not old:
                raise ValueError("Vydaná nabídka už v databázi neexistuje.")
            old_status = str(old["status"] or "")
            data["document_number"] = str(old["document_number"] or data.get("document_number") or "")
            data["created_by"] = str(old["created_by"] or user)
            assignments = ",".join(f"{field}=?" for field in fields)
            con.execute(
                f"UPDATE business_documents SET {assignments} WHERE id=?",
                tuple(data.get(field) for field in fields) + (int(document_id),),
            )
            result = int(document_id)
            con.execute("DELETE FROM business_document_items WHERE document_id=?", (result,))
        else:
            data["document_number"] = _sequence_number(con, M, data["issue_date"])
            data["created_by"] = user
            columns = ",".join(fields + ("created_at",))
            placeholders = ",".join("?" for _ in fields + ("created_at",))
            result = int(con.execute(
                f"INSERT INTO business_documents({columns}) VALUES({placeholders})",
                tuple(data.get(field) for field in fields) + (now,),
            ).lastrowid)

        item_fields = (
            "document_id", "position", "row_type", "product_code", "item_key", "name", "description",
            "quantity", "unit", "purchase_unit_price", "purchase_currency", "margin_pct",
            "recommended_unit_price", "discount_pct", "unit_price", "total_price", "vat_rate",
            "show_recommended_price", "category_id", "subgroup_id", "catalog_product_id",
            "internal_code_snapshot", "internal_name_snapshot", "price_source_label",
            "source_price_list_item_id", "source_supplier_offer_item_id", "line_note",
        )
        placeholders = ",".join("?" for _ in item_fields)
        for item in normalized_items:
            row = dict(item)
            row["document_id"] = result
            con.execute(
                f"INSERT INTO business_document_items({','.join(item_fields)}) VALUES({placeholders})",
                tuple(row.get(field) for field in item_fields),
            )

        if old_status != data["status"]:
            con.execute(
                """INSERT INTO business_document_history(
                       document_id,event_type,old_status,new_status,note,user_name
                   ) VALUES(?,?,?,?,?,?)""",
                (result, "status", old_status, data["status"], "", user),
            )
        elif not document_id:
            con.execute(
                """INSERT INTO business_document_history(
                       document_id,event_type,old_status,new_status,note,user_name
                   ) VALUES(?,?,?,?,?,?)""",
                (result, "created", "", data["status"], "Vydaná nabídka vytvořena", user),
            )
    return result


def load_document(M, document_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with M.db() as con:
        row = con.execute(
            """SELECT d.*,coalesce(c.official_name,c.short_name,d.customer_name_snapshot,'') company_name,
                      p.name project_name,a.name action_name,t.name template_name
               FROM business_documents d
               LEFT JOIN companies c ON c.id=d.company_id
               LEFT JOIN projects p ON p.id=d.project_id
               LEFT JOIN actions a ON a.id=d.action_id
               LEFT JOIN business_document_templates t ON t.id=d.template_id
               WHERE d.id=? AND d.document_type=? AND d.direction=?""",
            (int(document_id), DOCUMENT_TYPE, DOCUMENT_DIRECTION),
        ).fetchone()
        items = con.execute(
            "SELECT * FROM business_document_items WHERE document_id=? ORDER BY position,id",
            (int(document_id),),
        ).fetchall()
    if not row:
        raise ValueError("Vydaná nabídka nebyla nalezena.")
    return dict(row), [dict(item) for item in items]


def next_revision_no(M, document_id: int) -> int:
    with M.db() as con:
        row = con.execute(
            "SELECT coalesce(MAX(revision_no),-1)+1 FROM business_document_revisions WHERE document_id=?",
            (int(document_id),),
        ).fetchone()
    return int(row[0] or 0)


def document_archive_dir(M, document: dict[str, Any]) -> Path:
    issue = iso_date(document.get("issue_date"), date.today().isoformat())
    year = issue[:4]
    label = " - ".join(
        part for part in (
            str(document.get("document_number") or ""),
            str(document.get("customer_name_snapshot") or document.get("company_name") or ""),
            str(document.get("project_name") or document.get("action_name") or document.get("offer_subject") or ""),
        ) if part.strip()
    )
    target = archive_root(M) / year / safe_filename(label, str(document.get("document_number") or "nabidka"), 140)
    target.mkdir(parents=True, exist_ok=True)
    return target


def record_revision(M, document_id: int, revision_no: int, pdf_path: Path, data_snapshot: dict[str, Any]) -> None:
    payload = pdf_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    user = active_user(M)
    status = str(data_snapshot.get("status") or "")
    with M.db() as con:
        con.execute(
            """INSERT INTO business_document_revisions(
                   document_id,revision_no,pdf_path,pdf_sha256,file_size,status_snapshot,data_json,created_by
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (int(document_id), int(revision_no), str(pdf_path), digest, len(payload), status,
             json.dumps(data_snapshot, ensure_ascii=False, default=str), user),
        )
        con.execute(
            """UPDATE business_documents
               SET revision_no=?,last_pdf_path=?,last_pdf_sha256=?,updated_at=CURRENT_TIMESTAMP,updated_by=?
               WHERE id=?""",
            (int(revision_no), str(pdf_path), digest, user, int(document_id)),
        )
        con.execute(
            """INSERT INTO business_document_history(document_id,event_type,note,user_name)
               VALUES(?,?,?,?)""",
            (int(document_id), "pdf", f"Vytvořeno PDF revize R{revision_no:02d}", user),
        )


def set_archived(M, document_id: int, archived: bool) -> None:
    user = active_user(M)
    with M.db() as con:
        con.execute(
            """UPDATE business_documents SET archived=?,archived_at=?,archived_by=?,updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND document_type=?""",
            (1 if archived else 0, datetime.now().isoformat(timespec="seconds") if archived else "", user if archived else "", int(document_id), DOCUMENT_TYPE),
        )
        con.execute(
            "INSERT INTO business_document_history(document_id,event_type,note,user_name) VALUES(?,?,?,?)",
            (int(document_id), "archive" if archived else "restore", "", user),
        )


def delete_draft(M, document_id: int) -> bool:
    with M.db() as con:
        row = con.execute(
            "SELECT status,revision_no FROM business_documents WHERE id=? AND document_type=?",
            (int(document_id), DOCUMENT_TYPE),
        ).fetchone()
        if not row:
            return False
        if str(row["status"] or "") != "Rozpracováno" or int(row["revision_no"] if row["revision_no"] is not None else -1) >= 0:
            raise ValueError("Odstranit lze pouze rozpracovaný koncept bez vytvořeného PDF.")
        con.execute("DELETE FROM business_documents WHERE id=?", (int(document_id),))
    return True


def duplicate_document(M, document_id: int) -> int:
    document, items = load_document(M, document_id)
    today = date.today()
    validity = max(1, int(number(get_setting(M, "issued_offer_default_validity_days", "14"), 14)))
    keep = dict(document)
    for key in (
        "id", "document_number", "created_at", "updated_at", "last_pdf_path", "last_pdf_sha256",
        "revision_no", "sent_at", "accepted_at", "rejected_at", "archived", "archived_at", "archived_by",
    ):
        keep.pop(key, None)
    keep.update(
        issue_date=today.isoformat(), valid_to=(today + timedelta(days=validity)).isoformat(),
        status="Rozpracováno", locked=0, created_by=active_user(M), updated_by=active_user(M),
    )
    for item in items:
        item.pop("id", None)
        item.pop("document_id", None)
    return save_document(M, keep, items, None)


def set_status(M, document_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError("Neplatný stav vydané nabídky.")
    now = datetime.now().isoformat(timespec="seconds")
    user = active_user(M)
    with M.db() as con:
        row = con.execute("SELECT status FROM business_documents WHERE id=?", (int(document_id),)).fetchone()
        if not row:
            raise ValueError("Vydaná nabídka nebyla nalezena.")
        old = str(row[0] or "")
        sent = now if status == "Odesláno" else None
        accepted = now if status == "Přijato" else None
        rejected = now if status == "Zamítnuto" else None
        con.execute(
            """UPDATE business_documents SET status=?,locked=?,
                   sent_at=CASE WHEN ? IS NULL THEN sent_at ELSE ? END,
                   accepted_at=CASE WHEN ? IS NULL THEN accepted_at ELSE ? END,
                   rejected_at=CASE WHEN ? IS NULL THEN rejected_at ELSE ? END,
                   updated_at=CURRENT_TIMESTAMP,updated_by=? WHERE id=?""",
            (status, 1 if status in TERMINAL_STATUSES else 0,
             sent, sent, accepted, accepted, rejected, rejected, user, int(document_id)),
        )
        if old != status:
            con.execute(
                """INSERT INTO business_document_history(
                       document_id,event_type,old_status,new_status,user_name
                   ) VALUES(?,?,?,?,?)""",
                (int(document_id), "status", old, status, user),
            )


def list_companies(M) -> list[tuple[int, str]]:
    with M.db() as con:
        rows = con.execute(
            """SELECT id,coalesce(nullif(trim(official_name),''),short_name) name
               FROM companies WHERE active=1 ORDER BY name COLLATE CZECH,id"""
        ).fetchall()
    return [(int(row[0]), str(row[1] or "")) for row in rows]


def list_people(M, company_id: int | None = None) -> list[tuple[int, str]]:
    with M.db() as con:
        if company_id:
            rows = con.execute(
                "SELECT id,name FROM people WHERE active=1 AND company_id=? ORDER BY name COLLATE CZECH,id",
                (int(company_id),),
            ).fetchall()
        else:
            rows = con.execute("SELECT id,name FROM people WHERE active=1 ORDER BY name COLLATE CZECH,id").fetchall()
    return [(int(row[0]), str(row[1] or "")) for row in rows]


def list_projects(M) -> list[tuple[int, str]]:
    with M.db() as con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(projects)")}
        where = "WHERE coalesce(active,1)=1" if "active" in columns else ""
        rows = con.execute(f"SELECT id,name FROM projects {where} ORDER BY name COLLATE CZECH,id").fetchall()
    return [(int(row[0]), str(row[1] or "")) for row in rows]


def list_actions(M) -> list[tuple[int, str, int | None]]:
    with M.db() as con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(actions)")}
        project_expr = "project_id" if "project_id" in columns else "NULL"
        archived = "AND coalesce(archived,0)=0" if "archived" in columns else ""
        rows = con.execute(
            f"""SELECT id,name,{project_expr} project_id FROM actions
                WHERE status NOT IN ('Hotovo','Zrušeno') {archived}
                ORDER BY name COLLATE CZECH,id"""
        ).fetchall()
    return [(int(row[0]), str(row[1] or ""), int(row[2]) if row[2] is not None else None) for row in rows]


def catalog_products(M, query: str = "", limit: int = 500) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    q = str(query or "").strip().casefold()
    where = ["cp.active=1"]
    where_params: list[Any] = []
    if q:
        where.append(
            "lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||"
            "coalesce(cp.manufacturer_name,'')||' '||coalesce(src.supplier_product_code,'')||' '||"
            "coalesce(src.source_name,'')) LIKE ?"
        )
        where_params.append("%" + q + "%")
    params: list[Any] = [today, today, today, today, today, today, today] + where_params + [int(limit)]
    with M.db() as con:
        rows = con.execute(
            f"""SELECT cp.id,cp.internal_code,cp.internal_name,cp.manufacturer_name,
                       cp.category_id,cp.subgroup_id,cat.name category,sg.name subgroup,
                       src.supplier_product_code,src.source_name,
                       coalesce(
                         (SELECT i.normalized_unit_price FROM price_list_items i
                          JOIN price_lists p ON p.id=i.price_list_id
                          WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                            AND trim(coalesce(p.valid_from,''))<>'' AND p.valid_from<=?
                            AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                            AND lower(coalesce(p.parse_status,'')) NOT LIKE '%ocr%'
                            AND lower(coalesce(p.parse_status,'')) NOT LIKE '%kontrol%'
                          ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1),
                         (SELECT i.unit_price FROM supplier_offer_items i
                          JOIN supplier_offers o ON o.id=i.offer_id
                          WHERE i.catalog_product_id=cp.id AND coalesce(o.archived,0)=0
                            AND trim(coalesce(o.offer_date,''))<>'' AND o.offer_date<=?
                          ORDER BY o.offer_date DESC,o.id DESC,i.id DESC LIMIT 1),0
                       ) purchase_price,
                       coalesce(
                         (SELECT i.unit FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                          WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                            AND p.valid_from<=? AND (p.valid_to='' OR p.valid_to>=?)
                          ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1),'ks'
                       ) unit,
                       coalesce(sg.default_margin_pct,cat.default_margin_pct,0) margin_pct,
                       coalesce(sg.default_discount_pct,cat.default_discount_pct,0) discount_pct,
                       coalesce(cat.show_recommended_price,1) show_recommended_price,
                       coalesce(
                         (SELECT p.title FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                          WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                            AND p.valid_from<=? AND (p.valid_to='' OR p.valid_to>=?)
                          ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1),
                         'Poslední cenová nabídka'
                       ) price_source_label
                FROM catalog_products cp
                LEFT JOIN product_categories cat ON cat.id=cp.category_id
                LEFT JOIN product_subgroups sg ON sg.id=cp.subgroup_id
                LEFT JOIN (
                    SELECT s1.* FROM catalog_product_sources s1
                    JOIN (SELECT product_id,MIN(id) id FROM catalog_product_sources GROUP BY product_id) x ON x.id=s1.id
                ) src ON src.product_id=cp.id
                WHERE {' AND '.join(where)}
                ORDER BY coalesce(nullif(cp.internal_name,''),src.source_name,'') COLLATE CZECH,cp.id
                LIMIT ?""",
            params,
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        purchase = number(item.get("purchase_price"))
        margin = number(item.get("margin_pct"))
        discount = number(item.get("discount_pct"))
        recommended = purchase * (1 + margin / 100)
        item.update(
            row_type="product", catalog_product_id=int(item["id"]),
            product_code=str(item.get("supplier_product_code") or item.get("internal_code") or ""),
            item_key=str(item.get("supplier_product_code") or item.get("internal_code") or item.get("internal_name") or ""),
            name=str(item.get("internal_name") or item.get("source_name") or ""),
            description=str(item.get("source_name") or ""), quantity=1.0,
            purchase_unit_price=purchase, purchase_currency="CZK", recommended_unit_price=recommended,
            unit_price=recommended * (1 - discount / 100),
            internal_code_snapshot=str(item.get("internal_code") or ""),
            internal_name_snapshot=str(item.get("internal_name") or ""),
            vat_rate=number(get_setting(M, "issued_offer_default_vat_rate", "21"), 21),
        )
        result.append(normalize_item(item))
    return result


def latest_pdf_path(M, document_id: int) -> Path | None:
    with M.db() as con:
        row = con.execute("SELECT last_pdf_path FROM business_documents WHERE id=?", (int(document_id),)).fetchone()
    path = Path(str(row[0] or "")) if row else None
    return path if path and path.is_file() else None


def open_path(path: str | Path) -> None:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)
    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])


__all__ = [
    "DOCUMENT_TYPE", "DOCUMENT_DIRECTION", "STATUSES", "TERMINAL_STATUSES", "ROW_TYPES",
    "Totals", "number", "iso_date", "active_user", "get_setting", "set_setting", "archive_root",
    "template_assets_root", "copy_template_asset", "issuer_defaults", "offer_defaults",
    "default_template_id", "load_template", "list_templates", "save_template", "deactivate_template",
    "company_snapshot", "contact_snapshot", "normalize_item", "calculate_totals", "save_document",
    "load_document", "next_revision_no", "document_archive_dir", "record_revision", "set_archived",
    "delete_draft", "duplicate_document", "set_status", "list_companies", "list_people",
    "list_projects", "list_actions", "catalog_products", "latest_pdf_path", "open_path",
]
