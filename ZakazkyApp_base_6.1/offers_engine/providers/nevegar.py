# Nevegar / Reinforcement Systems custom-made PLEXUS offer provider.
from __future__ import annotations

import io
import os
import re

import fitz

SUPPLIER = "Nevegar"

_ITEM_RE = re.compile(r"^[A-Z]{2,}[A-Z0-9]*/[A-Z0-9]+/[A-Z0-9]+$", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.20\d{2})\b")
_OFFER_RE = re.compile(r"\bOffer\s+(\d{4}\s*/\s*\d+)\b", re.I)

_VERSION_NAMES = {
    "P": "PLEXUS®",
    "A": "PLEXUS® ABZ",
    "X": "PYRAPLEX®",
    "F": "PLEXUS® FTW",
    "S": "PLEXUS® SPURGIN",
}

# PDF-coordinate crop rectangles for the product shape catalogue printed above
# the table in this Nevegar layout.
_TYPE_RECTS = {}
for _code, _center in zip(
    ("A", "C", "D", "I", "J", "AA", "AC", "AD"),
    (58, 128, 198, 268, 338, 408, 478, 548),
):
    _TYPE_RECTS[_code] = (_center - 29, 93, _center + 29, 151)
for _code, _center in zip(
    ("B", "CC", "DD", "E", "F", "G", "H", "K", "L", "M", "O"),
    (63, 133, 203, 273, 343, 413, 483, 553, 623, 693, 763),
):
    _TYPE_RECTS[_code] = (_center - 29, 150, _center + 29, 216)

# Table x-coordinate bands (PDF points). Kept deliberately separated from
# header text because PyMuPDF's block order for this form is not visual order.
_BANDS = {
    "position": (35, 59),
    "version": (59, 88),
    "item_no": (88, 185),
    "pieces": (185, 225),
    "type": (225, 260),
    "iron": (260, 300),
    "stirrup_distance": (300, 340),
    "stirrup_width": (340, 380),
    "stirrup_height": (380, 420),
    "pull_out_length": (420, 470),
    "dimension": (470, 510),
    "box_width": (510, 545),
    "box_height": (545, 580),
    "length": (580, 620),
    "price_per_meter": (620, 700),
    "discount_surcharge": (700, 735),
    "total": (735, 810),
}


def _clean(value):
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _cz_num(value):
    text = _clean(value)
    text = re.sub(r"\bCZK\b", "", text, flags=re.I).strip()
    text = text.replace(" ", "").replace(".", "").replace(",", ".")
    return float(text)


def _first_page(pdf_path):
    doc = fitz.open(pdf_path)
    if not doc.page_count:
        doc.close()
        raise ValueError("PDF neobsahuje žádnou stránku.")
    return doc, doc[0]


def _text(pdf_path):
    with fitz.open(pdf_path) as doc:
        if not doc.page_count:
            return ""
        return doc[0].get_text("text")


def detect(path):
    try:
        text = _text(path)
        folded = text.casefold()
        return (
            "reinforcement systems" in folded
            and "offer custom-made products" in folded
            and bool(_OFFER_RE.search(text))
            and bool(re.search(r"\bBWSP\d+/\d+/\d+\b", text, re.I))
        )
    except Exception:
        return False


def _header(text):
    offer_match = _OFFER_RE.search(text)
    offer_no = _clean(offer_match.group(1)) if offer_match else ""

    dates = _DATE_RE.findall(text)
    offer_date = dates[0] if dates else ""

    reference = ""
    project = re.search(r"\bProject:\s*([^\r\n]+)", text, re.I)
    if project:
        reference = _clean(project.group(1))

    customer = ""
    customer_match = re.search(r"\bCustomer:\s*([^\r\n]+)", text, re.I)
    if customer_match:
        customer = _clean(customer_match.group(1))
    elif "Customer:" in text:
        lines = [_clean(x) for x in text.splitlines() if _clean(x)]
        try:
            idx = next(i for i, x in enumerate(lines) if x.casefold() == "customer:")
            if idx + 1 < len(lines):
                customer = lines[idx + 1]
        except StopIteration:
            pass

    return offer_no, offer_date, reference, customer


def _words_in_row(page, y, tolerance=4.5):
    out = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        cy = (y0 + y1) / 2
        if abs(cy - y) <= tolerance:
            out.append((x0, y0, x1, y1, _clean(text)))
    return sorted(out, key=lambda w: w[0])


def _band_text(row_words, name):
    x0, x1 = _BANDS[name]
    values = [
        text for wx0, _wy0, wx1, _wy1, text in row_words
        if ((wx0 + wx1) / 2) >= x0 and ((wx0 + wx1) / 2) < x1
    ]
    return _clean(" ".join(values))


def _type_image(page, type_code):
    rect = _TYPE_RECTS.get(_clean(type_code).upper())
    if not rect:
        return None, None
    try:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(3, 3),
            clip=fitz.Rect(*rect),
            alpha=False,
        )
        return pix.tobytes("png"), "png"
    except Exception:
        return None, None


def _discount_pct(text):
    value = _clean(text)
    m = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%", value)
    if not m:
        return 0.0
    number = float(m.group(1).replace(",", "."))
    if value.lstrip().startswith("+"):
        return -abs(number)
    if value.lstrip().startswith("-"):
        return abs(number)
    return number


def _description(values):
    version = _clean(values["version"]).upper()
    family = _VERSION_NAMES.get(version, version or "PLEXUS")
    type_code = _clean(values["type"]).upper()

    parts = [family]
    if type_code:
        parts.append(f"typ {type_code}")
    if values["iron"]:
        parts.append(f"Ø{values['iron']} mm")
    if values["stirrup_distance"]:
        parts.append(f"s={values['stirrup_distance']} cm")
    if values["stirrup_width"]:
        parts.append(f"b={values['stirrup_width']} cm")
    if values["stirrup_height"]:
        parts.append(f"h={values['stirrup_height']} cm")
    if values["pull_out_length"]:
        parts.append(f"lü={values['pull_out_length']} cm")
    if values["dimension"]:
        parts.append(f"v/v1={values['dimension']} cm")
    if values["box_width"]:
        parts.append(f"box b={values['box_width']} cm")
    if values["box_height"]:
        parts.append(f"box h={values['box_height']} mm")
    if values["length"]:
        parts.append(f"L={values['length']} cm")
    return " | ".join(parts)


def _details(values, price_per_meter):
    pairs = [
        ("Verze", values["version"]),
        ("Typ", values["type"]),
        ("Ø výztuže", f"{values['iron']} mm" if values["iron"] else ""),
        ("Rozteč třmínků s", f"{values['stirrup_distance']} cm" if values["stirrup_distance"] else ""),
        ("Šířka třmínku b", f"{values['stirrup_width']} cm" if values["stirrup_width"] else ""),
        ("Výška třmínku h", f"{values['stirrup_height']} cm" if values["stirrup_height"] else ""),
        ("Délka vytažení lü", f"{values['pull_out_length']} cm" if values["pull_out_length"] else ""),
        ("Rozměr v/v1", f"{values['dimension']} cm" if values["dimension"] else ""),
        ("Šířka boxu", f"{values['box_width']} cm" if values["box_width"] else ""),
        ("Výška boxu", f"{values['box_height']} mm" if values["box_height"] else ""),
        ("Délka", f"{values['length']} cm" if values["length"] else ""),
        ("Cena za metr", f"{price_per_meter:.2f} CZK".replace(".", ",") if price_per_meter is not None else ""),
    ]
    return "; ".join(f"{name}: {value}" for name, value in pairs if value)


def _items(page):
    anchors = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        clean = _clean(text)
        if _ITEM_RE.fullmatch(clean) and 80 <= x0 <= 190:
            anchors.append(((y0 + y1) / 2, clean))

    if not anchors:
        raise ValueError("V nabídce Nevegar nebyly nalezeny řádky položek.")

    items = []
    for y, item_no in sorted(anchors):
        row_words = _words_in_row(page, y)
        values = {name: _band_text(row_words, name) for name in _BANDS}
        values["item_no"] = item_no

        try:
            position = int(_cz_num(values["position"]))
            pieces_num = _cz_num(values["pieces"])
            pieces = int(pieces_num) if pieces_num.is_integer() else pieces_num
            total = _cz_num(values["total"])
            price_per_meter = _cz_num(values["price_per_meter"])
        except Exception as exc:
            raise ValueError(
                f"Řádek {item_no} má nečitelnou číselnou hodnotu: {exc}"
            ) from exc

        length_cm = None
        try:
            length_cm = _cz_num(values["length"]) if values["length"] else None
        except Exception:
            pass

        # CRM stores quantity and unit price so their multiplication matches the
        # row total. The source prints pieces and a price per metre, therefore
        # store pieces as quantity and calculate the finished-box unit price.
        if pieces and total:
            unit_price = total / float(pieces)
        elif length_cm is not None and price_per_meter:
            unit_price = price_per_meter * (length_cm / 100.0)
        else:
            unit_price = price_per_meter

        type_code = values["type"].upper()
        image_bytes, image_ext = _type_image(page, type_code)
        description = _description(values)
        disc = _discount_pct(values["discount_surcharge"])

        items.append({
            "position": position,
            "product": item_no,
            "description": description,
            "item_key": description,
            "details": _details(values, price_per_meter),
            "quantity": pieces,
            "unit": "ks",
            "original_unit_price": unit_price,
            "discount_pct": disc,
            "unit_price": unit_price,
            "item_total": total,
            "price_per_meter": price_per_meter,
            "length_cm": length_cm,
            "image_bytes": image_bytes,
            "image_ext": image_ext,
        })

    return items


def _summary_total(text):
    values = []
    for raw in re.findall(r"\b\d[\d ]*,\d{2}\s*CZK\b", text, re.I):
        try:
            values.append(_cz_num(raw))
        except Exception:
            pass
    return max(values) if values else None


def parse(pdf_path):
    doc, page = _first_page(pdf_path)
    try:
        text = page.get_text("text")
        folded = text.casefold()
        if (
            "reinforcement systems" not in folded
            or "offer custom-made products" not in folded
        ):
            raise ValueError("PDF není rozpoznáno jako nabídka Nevegar / Reinforcement Systems.")

        offer_no, offer_date, reference, customer = _header(text)
        if not offer_no:
            raise ValueError("V nabídce Nevegar nebylo nalezeno číslo nabídky.")
        if not offer_date:
            raise ValueError("V nabídce Nevegar nebylo nalezeno datum nabídky.")

        items = _items(page)
        calculated = sum(float(item.get("item_total") or 0) for item in items)
        total = _summary_total(text)
        if total is None:
            total = calculated

        if total and calculated and abs(total - calculated) > max(0.10, total * 0.002):
            raise ValueError(
                f"Součet položek Nevegar ({calculated:.2f}) neodpovídá celku nabídky ({total:.2f})."
            )

        return {
            "supplier": SUPPLIER,
            "offer_no": offer_no,
            "date": offer_date,
            "reference": reference,
            "customer": customer,
            "gross": total,
            "discount_pct": 0.0,
            "discount_value": 0.0,
            "net": total,
            "vat": None,
            "total": total,
            "currency": "CZK",
            "source_pdf": os.path.basename(str(pdf_path)),
            "source_type": "PDF",
            "items": items,
        }
    finally:
        doc.close()


def export_excel(data, output_path, price_alerts=None):
    import xlsxwriter

    workbook = xlsxwriter.Workbook(output_path)
    try:
        sheet = workbook.add_worksheet("Nabídka")
        title = workbook.add_format({"font_name": "Calibri", "bold": True, "font_size": 16})
        label = workbook.add_format({"font_name": "Calibri", "bold": True, "border": 1})
        cell = workbook.add_format({"font_name": "Calibri", "border": 1, "valign": "top"})
        wrap = workbook.add_format({"font_name": "Calibri", "border": 1, "text_wrap": True, "valign": "top"})
        money = workbook.add_format({"font_name": "Calibri", "border": 1, "num_format": '#,##0.00 "Kč"'})
        header = workbook.add_format({"font_name": "Calibri", "bold": True, "border": 1, "align": "center", "valign": "vcenter"})

        sheet.write("A1", f'Nabídka {data.get("offer_no", "")}', title)
        meta = (
            ("Dodavatel", data.get("supplier") or SUPPLIER),
            ("Datum", data.get("date") or ""),
            ("Akce / projekt", data.get("reference") or ""),
            ("Celkem", float(data.get("total") or 0)),
        )
        for row, (name, value) in enumerate(meta, 2):
            sheet.write(row - 1, 0, name, label)
            sheet.write(row - 1, 1, value, money if name == "Celkem" else cell)

        headers = ("Poz.", "Kód", "Název", "Množství", "MJ", "Cena/ks", "Cena za metr", "Celkem", "Obrázek")
        start = 7
        for col, text in enumerate(headers):
            sheet.write(start, col, text, header)

        for offset, item in enumerate(data.get("items") or [], 1):
            row = start + offset
            sheet.set_row(row, 86)
            values = (
                item.get("position") or offset,
                item.get("product") or "",
                item.get("description") or "",
                float(item.get("quantity") or 0),
                item.get("unit") or "",
                float(item.get("unit_price") or 0),
                float(item.get("price_per_meter") or 0),
                float(item.get("item_total") or 0),
            )
            for col, value in enumerate(values):
                sheet.write(row, col, value, money if col in (5, 6, 7) else (wrap if col == 2 else cell))
            image = item.get("image_bytes")
            if image:
                sheet.insert_image(
                    row, 8, "typ.png",
                    {"image_data": io.BytesIO(image), "x_scale": 0.38, "y_scale": 0.38, "x_offset": 3, "y_offset": 3, "object_position": 1},
                )

        sheet.set_column("A:A", 7)
        sheet.set_column("B:B", 22)
        sheet.set_column("C:C", 66)
        sheet.set_column("D:E", 11)
        sheet.set_column("F:H", 16)
        sheet.set_column("I:I", 18)
        sheet.freeze_panes(start + 1, 0)
    finally:
        workbook.close()
    return output_path
