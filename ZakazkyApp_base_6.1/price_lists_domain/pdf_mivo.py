"""MIVO PDF Ceník parser including dimensions and weights."""
from __future__ import annotations
import json,re
from .common import _iso_date,_number
from .model import _base_item

def _parse_mivo(text: str, pages: list[dict]) -> dict | None:
    if "MIVO" not in text or not re.search(r"CISADOR|CIBATUR", text, re.I):
        return None
    items = []
    for page in pages:
        words = list(page.get("words") or [])
        anchors = sorted(
            [word for word in words
             if float(word.get("x0") or 0) < 90
             and re.fullmatch(r"\d{1,2}\.", str(word.get("text") or ""))],
            key=lambda word: float(word.get("y0") or 0),
        )
        for index, anchor in enumerate(anchors):
            anchor_y = float(anchor.get("y0") or 0)
            next_y = float(anchors[index + 1].get("y0") or 10**9) if index + 1 < len(anchors) else anchor_y + 36
            band = [word for word in words if anchor_y - 16 <= float(word.get("y0") or 0) < next_y - 1]
            description_words = [word for word in band if 90 <= float(word.get("x0") or 0) < 285]
            if not description_words:
                continue
            y_values = sorted({round(float(word.get("y0") or 0), 1) for word in description_words})
            product_y = y_values[0]
            product_tokens = [str(word.get("text") or "") for word in sorted(description_words, key=lambda w: float(w.get("x0") or 0))
                              if abs(float(word.get("y0") or 0) - product_y) < 2]
            name = " ".join(product_tokens).strip()
            if not re.search(r"CISADOR|CIBATUR", name, re.I):
                continue
            size_tokens = [str(word.get("text") or "") for word in sorted(description_words, key=lambda w: (float(w.get("y0") or 0), float(w.get("x0") or 0)))
                           if "Velikost" in str(word.get("text") or "") or
                           (product_y + 8 <= float(word.get("y0") or 0) <= product_y + 18)]
            size_line = " ".join(size_tokens).strip()
            size_line = re.sub(r"^.*?Velikost\s+desky\s+", "", size_line, flags=re.I)
            weight_words = [word for word in description_words if product_y + 20 <= float(word.get("y0") or 0) <= product_y + 30]
            weight_text = " ".join(str(word.get("text") or "") for word in sorted(weight_words, key=lambda w: float(w.get("x0") or 0)))
            weight_match = re.search(r"Hmotnost\s+([\d.,]+)\s*kg/jednotku", weight_text, re.I)
            weight = _number(weight_match.group(1)) if weight_match else 0.0
            price_words = [word for word in words
                           if 300 <= float(word.get("x0") or 0) < 365
                           and abs(float(word.get("y0") or 0) - anchor_y) < 3]
            price_text = "".join(str(word.get("text") or "") for word in sorted(price_words, key=lambda w: float(w.get("x0") or 0)))
            price = _number(price_text)
            unit_words = [word for word in words
                          if 385 <= float(word.get("x0") or 0) < 425
                          and abs(float(word.get("y0") or 0) - anchor_y) < 3]
            unit = " ".join(str(word.get("text") or "") for word in sorted(unit_words, key=lambda w: float(w.get("x0") or 0))).strip()
            attrs = []
            if size_line:
                attrs.append({"key": "Rozměr desky", "value": size_line, "unit": "", "source": "PDF"})
            if weight:
                attrs.append({"key": "Hmotnost", "value": str(weight), "unit": "kg/jednotku", "source": "PDF"})
            items.append(_base_item(
                row_no=int(str(anchor.get("text") or "0").rstrip(".")),
                product_code=name.replace(" ", "-"), name=name, description=size_line,
                unit=unit.replace("m2", "m²") or "m²", source_price=price,
                weight_unit=weight, dimensions=size_line, attributes=attrs,
                source_row_json=json.dumps({"name": name, "size": size_line, "weight": weight, "price": price}, ensure_ascii=False),
            ))
    if not items:
        return None
    number = re.search(r"CENOVÁ\s+NABÍDKA\s+([A-Z0-9/.-]+)", text, re.I)
    period = re.search(r"J[eě]notkov[eé]\s+ceny\s+(\d{1,2})/(\d{4})", text, re.I)
    date_match = re.search(r"V\s+Praze\s+dne:\s*(\d{1,2}\.\d{1,2}\.\d{4})", text, re.I)
    period_label = f"{int(period.group(1)):02d}/{period.group(2)}" if period else ""
    valid_from = f"{period.group(2)}-{int(period.group(1)):02d}-01" if period else (_iso_date(date_match.group(1)) if date_match else "")
    return {
        "supplier": "MIVO, spol. s r.o.",
        "title": (f"Jednotkové ceny {period_label} · {number.group(1)}" if number and period_label
                  else f"Jednotkové ceny {number.group(1)}" if number
                  else f"Jednotkové ceny {period_label}" if period_label else "Jednotkové ceny MIVO"),
        "valid_from": valid_from,
        "product_group": "Akustika", "branch": "Česká republika", "currency": "CZK",
        "items": items, "terms_text": text[-1200:],
        "parse_status": "Rozpoznáno automaticky", "source_type": "PDF",
    }
