"""Transactional persistence of Ceníky and extracted data."""
from __future__ import annotations
from datetime import date,datetime,timedelta
from pathlib import Path
from . import context as ctx
from .archive import _archive_source,price_list_archive_root
from .common import UPDATE_MODES,_file_hash,_iso_date,_number
from .model import _base_item
from .schema import _resolve_company

def _save_price_list(path: Path, parsed: dict, metadata: dict) -> tuple[int, bool]:
    supplier = str(metadata.get("supplier") or parsed.get("supplier") or "").strip()
    title = str(metadata.get("title") or parsed.get("title") or path.stem).strip()
    valid_from = _iso_date(metadata.get("valid_from") or parsed.get("valid_from"))
    valid_to = _iso_date(metadata.get("valid_to") or parsed.get("valid_to"))
    source_hash = _file_hash(path)
    with ctx.M.db() as con:
        existing = con.execute("SELECT id FROM price_lists WHERE source_hash=?", (source_hash,)).fetchone()
        if existing:
            existing_id = int(existing["id"])
            source_offer_id = metadata.get("source_offer_id")
            if source_offer_id:
                con.execute(
                    "UPDATE price_lists SET source_offer_id=coalesce(source_offer_id,?) WHERE id=?",
                    (source_offer_id, existing_id),
                )
            return existing_id, False
    archived_file, archived_hash = _archive_source(path, supplier, valid_from, title)
    source_hash = archived_hash
    with ctx.M.db() as con:
        supplier_id = _resolve_company(con, supplier)
        update_mode = str(metadata.get("update_mode") or parsed.get("suggested_update_mode") or "partial")
        supersedes_id = metadata.get("supersedes_id") or None
        price_list_id = con.execute(
            """INSERT INTO price_lists(
                 source_offer_id,supplier_company_id,supplier_name,title,valid_from,valid_to,
                 product_group,branch,update_mode,supersedes_id,archived,source_hash,
                 source_filename,archive_path,source_type,currency,imported_by,note,terms_text,
                 ocr_text,ocr_layout_json,ocr_engine,parse_status
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (metadata.get("source_offer_id"), supplier_id, supplier, title, valid_from, valid_to,
             str(metadata.get("product_group") or parsed.get("product_group") or ""),
             str(metadata.get("branch") or parsed.get("branch") or ""), update_mode,
             supersedes_id, 0, source_hash, path.name, str(archived_file),
             str(parsed.get("source_type") or path.suffix.lstrip(".").upper()),
             str(metadata.get("currency") or parsed.get("currency") or "CZK"),
             ctx.M.get_setting("active_user", ""), str(metadata.get("note") or ""),
             str(parsed.get("terms_text") or ""), str(parsed.get("ocr_text") or ""),
             str(parsed.get("ocr_layout_json") or ""), str(parsed.get("ocr_engine") or ""),
             str(parsed.get("parse_status") or "Připraveno")),
        ).lastrowid
        con.execute(
            """INSERT INTO price_list_files(price_list_id,original_name,archive_path,sha256,extension,file_size,is_primary)
               VALUES(?,?,?,?,?,?,1)""",
            (price_list_id, path.name, str(archived_file), source_hash, path.suffix.lower(), path.stat().st_size),
        )
        for index, raw_item in enumerate(parsed.get("items") or [], 1):
            item = _base_item(**dict(raw_item))
            item_id = con.execute(
                """INSERT INTO price_list_items(
                     price_list_id,row_no,product_code,supplier_item_code,item_key,name,description,unit,
                     source_price,currency,price_basis_qty,normalized_unit_price,discount_pct,surcharge_pct,
                     net_price,minimum_qty,package_qty,package_unit,pallet_qty,weight_unit,weight_package,
                     weight_pallet,gtin,customs_code,dimensions,condition_text,source_row_json,
                     category_id,subgroup_id,active
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                (price_list_id, int(item.get("row_no") or index), item.get("product_code", ""),
                 item.get("supplier_item_code", ""), item.get("item_key", ""), item.get("name", ""),
                 item.get("description", ""), item.get("unit", ""), _number(item.get("source_price")),
                 item.get("currency", "CZK"), _number(item.get("price_basis_qty"), 1) or 1,
                 _number(item.get("normalized_unit_price")), _number(item.get("discount_pct")),
                 _number(item.get("surcharge_pct")), _number(item.get("net_price")),
                 _number(item.get("minimum_qty")), _number(item.get("package_qty")),
                 item.get("package_unit", ""), _number(item.get("pallet_qty")),
                 _number(item.get("weight_unit")), _number(item.get("weight_package")),
                 _number(item.get("weight_pallet")), item.get("gtin", ""), item.get("customs_code", ""),
                 item.get("dimensions", ""), item.get("condition_text", ""), item.get("source_row_json", ""),
                 item.get("category_id"), item.get("subgroup_id")),
            ).lastrowid
            for attr in item.get("attributes") or []:
                con.execute(
                    """INSERT INTO price_list_item_attributes(item_id,attribute_key,attribute_value,attribute_unit,source)
                       VALUES(?,?,?,?,?)""",
                    (item_id, str(attr.get("key") or ""), str(attr.get("value") or ""),
                     str(attr.get("unit") or ""), str(attr.get("source") or "")),
                )
        for priority, rule in enumerate(parsed.get("rules") or [], 1):
            con.execute(
                """INSERT INTO price_list_rules(
                     price_list_id,scope_type,scope_value,rule_type,percent_value,fixed_value,
                     currency,condition_text,priority,active
                   ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
                (price_list_id, str(rule.get("scope_type") or "all"),
                 str(rule.get("scope_value") or ""), str(rule.get("rule_type") or "surcharge_pct"),
                 _number(rule.get("percent_value")), _number(rule.get("fixed_value")),
                 str(rule.get("currency") or metadata.get("currency") or parsed.get("currency") or "CZK"),
                 str(rule.get("condition_text") or ""), int(rule.get("priority") or priority)),
            )
        # Only an explicitly selected replacement closes the previous list.
        if supersedes_id and update_mode in {"replace_group", "replace_all"} and valid_from:
            try:
                previous_day = (datetime.strptime(valid_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
                con.execute("UPDATE price_lists SET valid_to=? WHERE id=? AND (valid_to='' OR valid_to>?)",
                            (previous_day, supersedes_id, previous_day))
            except Exception:
                pass
    return int(price_list_id), True


def _format_price(value: object, currency: str = "CZK") -> str:
    number = _number(value)
    if not number:
        return ""
    whole, fraction = f"{number:,.4f}".split(".")
    fraction = fraction.rstrip("0")
    if len(fraction) < 2:
        fraction = fraction.ljust(2, "0")
    return f"{whole.replace(',', ' ')},{fraction} {currency}"


def _list_status(row) -> str:
    if int(row["archived"] or 0):
        return "Archivovaný"
    today = date.today().isoformat()
    if not str(row["valid_from"] or "").strip():
        return "Chybí platnost"
    if row["valid_from"] > today:
        return "Budoucí"
    if row["valid_to"] and row["valid_to"] < today:
        return "Po platnosti"
    parse_status=str(row["parse_status"] or "")
    if parse_status.startswith("Bez"):
        return "Bez rozpoznaných položek"
    if "kontrol" in parse_status.casefold() or "ocr" in parse_status.casefold():
        return "Ke kontrole"
    return "Aktuální"
