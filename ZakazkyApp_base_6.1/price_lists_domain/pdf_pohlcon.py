"""PohlCon PDF Ceník parser."""
from __future__ import annotations
import json,re
from .common import _iso_date,_number
from .model import _base_item

def _parse_pohlcon(text: str) -> dict | None:
    if "Ceník prvků do železobetonu" not in text or "PohlCon" not in text:
        return None
    title_match = re.search(r"Ceník prvků do železobetonu[^\n]*", text, re.I)
    valid_match = re.search(r"platn[ýy]\s+od\s+(\d{1,2}\.\d{1,2}\.\d{4})", text, re.I)
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    items = []
    buffer = ""
    row_no = 0
    unit_pattern = r"(m2|m²|m|ks|kg|role)"
    for line in lines:
        if re.match(r"^\d{10,14}\b", line):
            if buffer:
                parsed = _parse_pohlcon_row(buffer, row_no + 1, unit_pattern)
                if parsed:
                    row_no += 1
                    items.append(parsed)
            buffer = line
        elif buffer:
            buffer += " " + line
            if re.search(unit_pattern + r"\s+[\d\s.,]+\s*Kč\s*$", buffer, re.I):
                parsed = _parse_pohlcon_row(buffer, row_no + 1, unit_pattern)
                if parsed:
                    row_no += 1
                    items.append(parsed)
                    buffer = ""
    if buffer:
        parsed = _parse_pohlcon_row(buffer, row_no + 1, unit_pattern)
        if parsed:
            items.append(parsed)
    if not items:
        return None
    terms_start = text.find("Ceny u Kunexu")
    terms = text[terms_start:].strip() if terms_start >= 0 else ""
    return {
        "supplier": "PohlCon Česká republika s.r.o.",
        "title": title_match.group(0).strip() if title_match else "Ceník prvků do železobetonu",
        "valid_from": _iso_date(valid_match.group(1)) if valid_match else "",
        "product_group": "Prvky do železobetonu",
        "branch": "Česká republika",
        "currency": "CZK", "items": items, "terms_text": terms,
        "rules": [{
            "scope_type": "condition", "scope_value": "BV",
            "rule_type": "informational_surcharge_pct", "percent_value": 50,
            "condition_text": "BV (bitumenům odolný): příplatek 50 %, pokud není uvedeno jinak.",
            "priority": 10,
        }],
        "parse_status": "Rozpoznáno automaticky", "source_type": "PDF",
    }


def _parse_pohlcon_row(text: str, row_no: int, unit_pattern: str) -> dict | None:
    match = re.match(r"^(\d{10,14})\s+(.+?)\s+" + unit_pattern + r"\s+([\d\s.,]+)\s*Kč\s*$", text, re.I)
    if not match:
        return None
    code, name, unit, price = match.groups()
    condition = ""
    cond = re.search(r"(-\s*odběr\s+nad\s+.+)$", name, re.I)
    if cond:
        condition = cond.group(1).lstrip("- ")
    return _base_item(row_no=row_no, product_code=code, name=name, description=name,
                      unit=unit.replace("m2", "m²"), source_price=_number(price),
                      price_basis_qty=1, condition_text=condition,
                      source_row_json=json.dumps({"raw": text}, ensure_ascii=False))
