"""Fallback adapter to existing supplier offer providers."""
from __future__ import annotations
import json,re
from pathlib import Path
from . import context as ctx
from .common import _iso_date,_number
from .model import _base_item

def _parse_offer_engine(path: Path) -> dict | None:
    fn = getattr(ctx.M, "extract_offer_pdf", None)
    if not callable(fn):
        return None
    try:
        parsed, raw = fn(path)
    except Exception:
        return None
    if not parsed or not parsed.get("items"):
        return None
    items = []
    for index, row in enumerate(parsed.get("items") or [], 1):
        description = str(row.get("description") or row.get("item_key") or row.get("product") or "")
        details = str(row.get("details") or "")
        weight = 0.0
        wm = re.search(r"(?:hmotnost|weight)\D*([\d.,]+)\s*kg", description + " " + details, re.I)
        if wm:
            weight = _number(wm.group(1))
        items.append(_base_item(
            row_no=int(row.get("position") or index), product_code=str(row.get("product") or ""),
            name=description, description=details, unit=str(row.get("unit") or ""),
            source_price=_number(row.get("original_unit_price") or row.get("unit_price")),
            normalized_unit_price=_number(row.get("unit_price")), discount_pct=_number(row.get("discount_pct")),
            minimum_qty=_number(row.get("quantity")), weight_unit=weight,
            source_row_json=json.dumps(row, ensure_ascii=False, default=str),
        ))
    supplier = str(parsed.get("supplier") or "")
    reference = str(parsed.get("reference") or "").strip()
    return {
        "supplier": supplier, "title": reference or f"Ceník {supplier}",
        "valid_from": _iso_date(parsed.get("date")), "product_group": "", "branch": "",
        "currency": "CZK", "items": items, "terms_text": str(raw or "")[-3000:],
        "parse_status": "Rozpoznáno parserem nabídky", "source_type": "PDF",
    }
