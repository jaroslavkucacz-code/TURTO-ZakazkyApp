"""Normalized price-list item model."""
from __future__ import annotations
from .common import _number

def _base_item(**values) -> dict:
    item = {
        "row_no": 0, "product_code": "", "supplier_item_code": "", "item_key": "",
        "name": "", "description": "", "unit": "", "source_price": 0.0,
        "currency": "CZK", "price_basis_qty": 1.0, "normalized_unit_price": 0.0,
        "discount_pct": 0.0, "surcharge_pct": 0.0, "net_price": 0.0,
        "minimum_qty": 0.0, "package_qty": 0.0, "package_unit": "",
        "pallet_qty": 0.0, "weight_unit": 0.0, "weight_package": 0.0,
        "weight_pallet": 0.0, "gtin": "", "customs_code": "", "dimensions": "",
        "condition_text": "", "source_row_json": "", "attributes": [],
    }
    item.update(values)
    item["name"] = str(item.get("name") or "").strip()
    item["description"] = str(item.get("description") or "").strip()
    item["product_code"] = str(item.get("product_code") or "").strip()
    item["item_key"] = str(item.get("item_key") or item["product_code"] or item["name"]).strip()
    basis = _number(item.get("price_basis_qty"), 1.0) or 1.0
    item["price_basis_qty"] = basis
    source = _number(item.get("source_price"))
    adjustment = _number(item.get("surcharge_pct")) - _number(item.get("discount_pct"))
    normalized = _number(item.get("normalized_unit_price"))
    if not normalized and source:
        normalized = source * (1 + adjustment / 100.0) / basis
    item["source_price"] = source
    item["normalized_unit_price"] = normalized
    if not _number(item.get("net_price")):
        item["net_price"] = normalized
    return item
