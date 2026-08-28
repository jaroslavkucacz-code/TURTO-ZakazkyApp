"""FERT scanned-PDF OCR parser."""
from __future__ import annotations
import json,re
from .common import _iso_date,_number
from .model import _base_item

def _parse_fert_ocr(text: str, pages: list[dict]) -> dict | None:
    if "FERT" not in text.upper() or not re.search(r"Cenov[áa]\s+nab[íi]dka", text, re.I):
        return None
    lines = []
    for page in pages:
        for line in page.get("lines") or []:
            value = " ".join(str(line.get("text") or "").split())
            if value:
                lines.append(value)
    if not lines:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    items = []
    current = None
    for line in lines:
        match = re.match(r"^(\d{1,2})\s+(.+)$", line)
        if match:
            if current:
                parsed = _finish_fert_row(current)
                if parsed:
                    items.append(parsed)
            current = {"row": int(match.group(1)), "parts": [match.group(2)]}
        elif current:
            current["parts"].append(line)
    if current:
        parsed = _finish_fert_row(current)
        if parsed:
            items.append(parsed)
    # OCR may miss row numbers. Recover product/price pairs from individual lines.
    if len(items) < 5:
        items = []
        for idx, line in enumerate(lines, 1):
            if not (re.search(r"\bD\s*\d{2,3}", line, re.I) or "Paleta" in line):
                continue
            nums = re.findall(r"\d+[.,]\d{2,4}", line)
            if not nums:
                continue
            price = _number(nums[-1])
            name = line[:line.rfind(nums[-1])].strip(" -")
            items.append(_base_item(row_no=idx, product_code="", name=name, description=name,
                                    unit="ks", source_price=price,
                                    source_row_json=json.dumps({"ocr": line}, ensure_ascii=False)))
    if not items:
        return None
    offer_no = re.search(r"(?:číslo|cislo)\s+([A-Z]{1,4}/\d{4}/\d+)", text, re.I)
    issued = re.search(r"(?:Zaevidováno|V\s+Soběslavi\s+dne)\D+(\d{1,2}\.\d{1,2}\.\d{4})", text, re.I)
    valid = re.search(r"platn[áa]\s+do\s+(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)", text, re.I)
    issued_iso=_iso_date(issued.group(1)) if issued else ""
    valid_iso=""
    if valid:
        token=valid.group(1).replace("/", ".")
        if token.count(".")==1 and issued_iso:
            token += "." + issued_iso[:4]
        valid_iso=_iso_date(token)
    title = f"FERT {offer_no.group(1)}" if offer_no else "Ceník FERT"
    return {
        "supplier": "FERT a.s.", "title": title,
        "valid_from": issued_iso,
        "valid_to": valid_iso,
        "product_group": "Distanční prvky", "branch": "Česká republika",
        "currency": "CZK", "items": items, "terms_text": text[-1800:],
        "parse_status": "OCR – zkontrolovat položky", "source_type": "PDF/OCR",
    }


def _finish_fert_row(current: dict) -> dict | None:
    raw = " ".join(current.get("parts") or [])
    numbers = re.findall(r"\d+[.,]\d{2,4}", raw)
    if not numbers:
        return None
    price = _number(numbers[-1])
    pos = raw.rfind(numbers[-1])
    name = raw[:pos].strip(" -")
    if not name or price <= 0:
        return None
    return _base_item(row_no=current.get("row") or 0, name=name, description=name,
                      unit="ks", source_price=price,
                      source_row_json=json.dumps({"ocr": raw}, ensure_ascii=False))
