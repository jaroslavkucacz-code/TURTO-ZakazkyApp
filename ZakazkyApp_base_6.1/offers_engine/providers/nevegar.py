# Nevegar / Reinforcement Systems custom-made PLEXUS offer provider.
from __future__ import annotations

import io
import os
import re

import fitz

SUPPLIER = "Nevegar"

_DATE_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.20\d{2})\b")
_OFFER_RE = re.compile(r"\bOffer\s+(\d{4}\s*/\s*\d+)\b", re.I)
_BWSP_RE = re.compile(r"^BWSP\d+/\d+/\d+$", re.I)
_COMPACT_ITEM_RE = re.compile(r"^[A-Z]{2,}[A-Z0-9/-]{5,}$", re.I)

_VERSION_NAMES = {
    "P": "PLEXUS®",
    "A": "PLEXUS® ABZ",
    "X": "PYRAPLEX®",
    "F": "PLEXUS® FTW",
    "S": "PLEXUS® SPURGIN",
}

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

_TECH_FIELDS = (
    ("version", "verze", ""),
    ("type", "typ", ""),
    ("iron", "Ø", " mm"),
    ("stirrup_distance", "s=", " cm"),
    ("stirrup_width", "b=", " cm"),
    ("stirrup_height", "h=", " cm"),
    ("pull_out_length", "lü=", " cm"),
    ("dimension", "v/v1=", " cm"),
    ("box_width", "box b=", " cm"),
    ("box_height", "box h=", " mm"),
    ("length", "L=", " cm"),
)


def _clean(value):
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _cz_num(value):
    text = _clean(value)
    text = re.sub(r"\bCZK\b", "", text, flags=re.I).strip()
    text = text.replace(" ", "").replace(".", "").replace(",", ".")
    return float(text)


def _fmt_num(value):
    if value is None:
        return ""
    if abs(float(value) - round(float(value))) < 1e-9:
        return str(int(round(float(value))))
    return f"{float(value):.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _is_red(color):
    try:
        color = int(color or 0)
    except Exception:
        return False
    r = (color >> 16) & 255
    g = (color >> 8) & 255
    b = color & 255
    return r >= 180 and r > g * 1.5 and r > b * 1.5


def _is_item_no(text):
    text = _clean(text)
    if _BWSP_RE.fullmatch(text):
        return True
    return (
        bool(_COMPACT_ITEM_RE.fullmatch(text))
        and any(ch.isdigit() for ch in text)
        and text.upper() not in {"REINFORCEMENT", "SYSTEMS"}
    )


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
        if not (
            "reinforcement systems" in folded
            and "offer custom-made products" in folded
            and bool(_OFFER_RE.search(text))
        ):
            return False
        with fitz.open(path) as doc:
            if not doc.page_count:
                return False
            return any(
                _is_item_no(word[4]) and 80 <= word[0] <= 190
                for word in doc[0].get_text("words")
            )
    except Exception:
        return False


def _header(text):
    offer_match = _OFFER_RE.search(text)
    offer_no = _clean(offer_match.group(1)) if offer_match else ""
    dates = _DATE_RE.findall(text)
    offer_date = dates[0] if dates else ""

    project_match = re.search(r"\bProject:[ \t]*([^\r\n]*)", text, re.I)
    reference = _clean(project_match.group(1)) if project_match else ""

    customer_match = re.search(r"\bCustomer:[ \t]*([^\r\n]*)", text, re.I)
    customer = _clean(customer_match.group(1)) if customer_match else ""
    if not customer:
        lines = [_clean(x) for x in text.splitlines() if _clean(x)]
        try:
            idx = next(i for i, line in enumerate(lines) if line.casefold() == "customer:")
            if idx + 1 < len(lines) and not lines[idx + 1].endswith(":"):
                customer = lines[idx + 1]
        except StopIteration:
            pass

    return offer_no, offer_date, reference, customer


def _row_spans(page, y, tolerance=4.7):
    out = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = _clean(span.get("text", ""))
                if not text:
                    continue
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                cy = (y0 + y1) / 2
                if abs(cy - y) <= tolerance:
                    out.append(
                        {
                            "x0": float(x0),
                            "x1": float(x1),
                            "text": text,
                            "red": _is_red(span.get("color", 0)),
                        }
                    )
    return sorted(out, key=lambda s: s["x0"])


def _band_segments(row_spans, name):
    x0, x1 = _BANDS[name]
    selected = [
        span for span in row_spans
        if x0 <= (span["x0"] + span["x1"]) / 2 < x1
    ]
    return [
        {"text": _clean(span.get("text") or ""), "red": bool(span.get("red"))}
        for span in selected
        if _clean(span.get("text") or "")
    ]


def _band_value(row_spans, name):
    selected = _band_segments(row_spans, name)
    return (
        _clean(" ".join(span["text"] for span in selected)),
        any(span["red"] for span in selected),
    )


def _red_notes(page):
    notes = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = _clean(span.get("text", ""))
                if not text or not _is_red(span.get("color", 0)):
                    continue
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                notes.append(
                    {
                        "text": text,
                        "y": (float(y0) + float(y1)) / 2,
                        "x": (float(x0) + float(x1)) / 2,
                    }
                )
    return notes


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


def _technical_description(values, field_segments, alternative_note=""):
    """Build one product description while keeping supplier colour span-exact.

    Prefixes such as ``lü=`` and units such as ``cm`` are generated by TURTO and
    therefore stay black. Only source fragments whose PDF span was actually red
    receive the red format. A legacy set of red field names is still accepted so
    older regression fixtures remain compatible.
    """
    if isinstance(field_segments, set):
        legacy_red = set(field_segments)
        field_segments = {
            key: [{"text": _clean(value), "red": key in legacy_red}]
            for key, value in values.items()
            if _clean(value)
        }

    segments = []

    def push(text, changed=False, bold=False):
        text = str(text or "")
        if not text:
            return
        current = {
            "text": text,
            "bold": bool(bold),
            "color": "#FF0000" if changed else "",
            "changed": bool(changed),
        }
        if (
            segments
            and segments[-1]["bold"] == current["bold"]
            and segments[-1]["color"] == current["color"]
            and segments[-1]["changed"] == current["changed"]
        ):
            segments[-1]["text"] += current["text"]
        else:
            segments.append(current)

    def add_group(parts):
        parts = [part for part in parts if str(part[0] or "")]
        if not parts:
            return
        if segments:
            push(" | ")
        for value, changed, bold in parts:
            push(value, changed=changed, bold=bold)

    def source_parts(field, fallback=""):
        source = list((field_segments or {}).get(field) or [])
        if not source:
            value = _clean(fallback)
            return [(value, False, False)] if value else []
        parts = []
        for index, fragment in enumerate(source):
            value = _clean(fragment.get("text") or "")
            if not value:
                continue
            if parts:
                parts.append((" ", False, False))
            parts.append((value, bool(fragment.get("red")), False))
        return parts

    if alternative_note:
        # The TURTO label itself is not present in the supplier PDF, so it must
        # never be coloured. Only the supplier's original red note is red.
        add_group([
            ("ALTERNATIVA – ", False, True),
            (alternative_note, True, True),
        ])

    version = _clean(values.get("version")).upper()
    family = _VERSION_NAMES.get(version, version or "PLEXUS")
    version_red = any(
        bool(fragment.get("red"))
        for fragment in list((field_segments or {}).get("version") or [])
    )
    add_group([(family, version_red, False)])

    type_code = _clean(values.get("type")).upper()
    if type_code:
        add_group([("typ ", False, False)] + source_parts("type", type_code))

    for key, prefix, suffix in _TECH_FIELDS[2:]:
        value = _clean(values.get(key))
        if not value:
            continue
        add_group(
            [(prefix, False, False)]
            + source_parts(key, value)
            + [(suffix, False, False)]
        )

    plain = "".join(segment["text"] for segment in segments)
    return plain, segments


def _price_modifier(base_total, actual_total, text):
    raw = _clean(text)
    if not raw or not base_total:
        return 0.0, ""
    match = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%", raw)
    if match:
        nominal = abs(float(match.group(1).replace(",", ".")))
    else:
        nominal = abs((actual_total / base_total - 1.0) * 100.0)

    delta = actual_total - base_total
    if abs(delta) <= max(0.02, abs(base_total) * 0.001):
        return 0.0, ""
    if delta > 0:
        return -nominal, f"Příplatek {nominal:g} %"
    return nominal, f"Sleva {nominal:g} %"


def _items(page):
    anchors = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text = word[:5]
        clean = _clean(text)
        if _is_item_no(clean) and 80 <= x0 <= 190:
            anchors.append(((y0 + y1) / 2, clean))

    if not anchors:
        raise ValueError("V nabídce Nevegar nebyly nalezeny řádky položek.")

    red_notes = _red_notes(page)
    alternative_notes = [
        note for note in red_notes
        if note["text"].casefold().startswith("alternative:")
    ]
    alternative_y = min((note["y"] for note in alternative_notes), default=None)
    alternative_text = ""
    if alternative_notes:
        alternative_text = re.sub(
            r"^\s*Alternative:\s*", "", alternative_notes[0]["text"], flags=re.I
        ).strip()

    items = []
    for y, item_no in sorted(anchors):
        spans = _row_spans(page, y)
        values = {}
        field_segments = {}
        red_fields = set()
        for name in _BANDS:
            source_segments = _band_segments(spans, name)
            field_segments[name] = source_segments
            value = _clean(" ".join(segment["text"] for segment in source_segments))
            values[name] = value
            if any(segment["red"] for segment in source_segments):
                red_fields.add(name)
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

        try:
            length_cm = _cz_num(values["length"]) if values["length"] else None
        except Exception:
            length_cm = None

        if length_cm is None or length_cm <= 0:
            raise ValueError(
                f"Řádek {item_no} nemá čitelnou délku prvku; "
                "množství nelze bezpečně převést na metry."
            )
        length_m = length_cm / 100.0
        quantity_m = float(pieces) * length_m if pieces else 0.0
        if quantity_m <= 0:
            raise ValueError(
                f"Řádek {item_no} nemá kladné množství v metrech."
            )

        base_total = quantity_m * price_per_meter
        unit_price = total / quantity_m
        discount_pct, modifier_note = _price_modifier(
            base_total, total, values["discount_surcharge"]
        )

        is_alternative = alternative_y is not None and y > alternative_y
        description, rich_segments = _technical_description(
            values,
            field_segments,
            alternative_text if is_alternative else "",
        )

        details_parts = [
            "Zdrojové množství: "
            f"{_fmt_num(pieces)} ks × {_fmt_num(length_m)} m = {_fmt_num(quantity_m)} m"
        ]
        if price_per_meter is not None:
            details_parts.append(
                f"Zdrojová cena: {_fmt_num(price_per_meter)} CZK/m"
            )
        if modifier_note:
            details_parts.append(modifier_note)
        if is_alternative:
            details_parts.append("Alternativní položka – není zahrnuta do celku nabídky")
        details = "; ".join(details_parts)

        type_code = _clean(values["type"]).upper()
        image_bytes, image_ext = _type_image(page, type_code)

        items.append(
            {
                "position": position,
                "product": item_no,
                "description": description,
                "item_key": description,
                "details": details,
                "rich_segments": rich_segments,
                "changed_fields": sorted(red_fields),
                "changed_fragments": [
                    {"field": field, "text": fragment["text"]}
                    for field, fragments in field_segments.items()
                    for fragment in fragments
                    if fragment.get("red")
                ],
                "plexus_type": type_code,
                "alternative": is_alternative,
                "quantity": quantity_m,
                "unit": "m",
                "original_unit_price": price_per_meter,
                "discount_pct": discount_pct,
                "unit_price": unit_price,
                "item_total": total,
                "image_bytes": image_bytes,
                "image_ext": image_ext,
            }
        )

    return items


def _summary_total(page):
    labels = []
    monies = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                value = _clean(span.get("text", ""))
                if not value:
                    continue
                x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                cy = (float(y0) + float(y1)) / 2
                if value.casefold() == "total:":
                    labels.append((cy, float(x0)))
                elif re.fullmatch(r"\d[\d .]*,\d{2}\s*CZK", value, re.I):
                    monies.append((cy, float(x0), value))
    for label_y, _label_x in labels:
        candidates = [
            (abs(cy - label_y), x, value)
            for cy, x, value in monies
            if x >= 720 and abs(cy - label_y) <= 3.5
        ]
        if candidates:
            return _cz_num(min(candidates)[2])
    return None


def parse(pdf_path):
    doc, page = _first_page(pdf_path)
    try:
        text = page.get_text("text")
        folded = text.casefold()
        if (
            "reinforcement systems" not in folded
            or "offer custom-made products" not in folded
        ):
            raise ValueError(
                "PDF není rozpoznáno jako nabídka Nevegar / Reinforcement Systems."
            )

        offer_no, offer_date, reference, customer = _header(text)
        if not offer_no:
            raise ValueError("V nabídce Nevegar nebylo nalezeno číslo nabídky.")
        if not offer_date:
            raise ValueError("V nabídce Nevegar nebylo nalezeno datum nabídky.")

        items = _items(page)
        calculated = sum(
            float(item.get("item_total") or 0)
            for item in items
            if not item.get("alternative")
        )
        total = _summary_total(page)
        if total is None:
            total = calculated

        if total and calculated and abs(total - calculated) > max(0.10, total * 0.002):
            raise ValueError(
                f"Součet položek Nevegar ({calculated:.2f}) "
                f"neodpovídá celku nabídky ({total:.2f})."
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


def _write_rich_description(sheet, row, col, item, formats):
    segments = list(item.get("rich_segments") or [])
    if not segments:
        sheet.write(row, col, item.get("description") or "", formats["wrap"])
        return

    args = []
    for segment in segments:
        text = str(segment.get("text") or "")
        if not text:
            continue
        changed = bool(segment.get("changed")) or str(segment.get("color") or "").upper() in {
            "#FF0000", "FF0000"
        }
        bold = bool(segment.get("bold"))
        key = "red_bold" if changed and bold else "red" if changed else "bold" if bold else "normal"
        args.extend([formats[key], text])

    if len(args) < 4:
        sheet.write(row, col, item.get("description") or "", formats["wrap"])
        return
    try:
        sheet.write_rich_string(row, col, *args, formats["wrap"])
    except Exception:
        sheet.write(row, col, item.get("description") or "", formats["wrap"])


def export_excel(data, output_path, price_alerts=None):
    import xlsxwriter

    workbook = xlsxwriter.Workbook(output_path)
    try:
        sheet = workbook.add_worksheet("Nabídka")
        sheet.hide_gridlines(2)

        formats = {
            "title": workbook.add_format(
                {"font_name": "Calibri", "bold": True, "font_size": 16}
            ),
            "label": workbook.add_format(
                {"font_name": "Calibri", "bold": True, "border": 1}
            ),
            "cell": workbook.add_format(
                {"font_name": "Calibri", "border": 1, "valign": "top"}
            ),
            "wrap": workbook.add_format(
                {
                    "font_name": "Calibri",
                    "border": 1,
                    "text_wrap": True,
                    "valign": "top",
                }
            ),
            "money": workbook.add_format(
                {
                    "font_name": "Calibri",
                    "border": 1,
                    "num_format": '#,##0.00 "Kč"',
                    "valign": "top",
                }
            ),
            "head": workbook.add_format(
                {
                    "font_name": "Calibri",
                    "bold": True,
                    "border": 1,
                    "align": "center",
                    "valign": "vcenter",
                }
            ),
            "normal": workbook.add_format({"font_name": "Calibri"}),
            "bold": workbook.add_format({"font_name": "Calibri", "bold": True}),
            "red": workbook.add_format(
                {"font_name": "Calibri", "font_color": "#FF0000"}
            ),
            "red_bold": workbook.add_format(
                {"font_name": "Calibri", "font_color": "#FF0000", "bold": True}
            ),
        }

        sheet.write("A1", f"Cenová nabídka {data.get('offer_no', '')}", formats["title"])
        meta = (
            ("Dodavatel", data.get("supplier") or SUPPLIER),
            ("Datum", data.get("date") or ""),
            ("Akce / projekt", data.get("reference") or ""),
            ("Celkem bez DPH", float(data.get("net") or 0)),
        )
        for row, (name, value) in enumerate(meta, 2):
            sheet.write(row - 1, 0, name, formats["label"])
            sheet.write(
                row - 1,
                1,
                value,
                formats["money"] if name == "Celkem bez DPH" else formats["cell"],
            )

        sheet.write(
            6,
            0,
            "Červený text = hodnota upravená výrobcem oproti zadání.",
            formats["red_bold"],
        )

        start = 8
        sheet.write(start, 0, "Poz.", formats["head"])
        sheet.write(start, 1, "Kód", formats["head"])
        sheet.merge_range(start, 2, start, 5, "Popis výrobku", formats["head"])
        sheet.merge_range(start, 6, start, 7, "Obrázek PLEXUS", formats["head"])
        for col, label in (
            (8, "Množství"),
            (9, "MJ"),
            (10, "Cena/m"),
            (11, "Celkem"),
        ):
            sheet.write(start, col, label, formats["head"])

        for offset, item in enumerate(data.get("items") or [], 1):
            row = start + offset
            sheet.write(row, 0, item.get("position") or offset, formats["cell"])
            sheet.write(row, 1, item.get("product") or "", formats["cell"])

            # Four Excel columns belong to the single Popis výrobku value.
            sheet.merge_range(row, 2, row, 5, "", formats["wrap"])
            _write_rich_description(sheet, row, 2, item, formats)

            # The next two columns are reserved exclusively for the exact shape
            # image selected from the supplier's PLEXUS type catalogue.
            sheet.merge_range(row, 6, row, 7, "", formats["cell"])
            image = item.get("image_bytes")
            if image:
                image_data = io.BytesIO(image)
                sheet.insert_image(
                    row,
                    6,
                    f"plexus-{item.get('plexus_type') or 'type'}.{item.get('image_ext') or 'png'}",
                    {
                        "image_data": image_data,
                        "x_scale": 0.55,
                        "y_scale": 0.55,
                        "x_offset": 7,
                        "y_offset": 4,
                        "object_position": 1,
                    },
                )

            sheet.write_number(row, 8, float(item.get("quantity") or 0), formats["cell"])
            sheet.write(row, 9, item.get("unit") or "m", formats["cell"])
            sheet.write_number(row, 10, float(item.get("unit_price") or 0), formats["money"])
            sheet.write_number(row, 11, float(item.get("item_total") or 0), formats["money"])
            sheet.set_row(row, 88)

        sheet.set_column("A:A", 7)
        sheet.set_column("B:B", 22)
        sheet.set_column("C:F", 15)
        sheet.set_column("G:H", 12)
        sheet.set_column("I:J", 11)
        sheet.set_column("K:L", 16)
        sheet.freeze_panes(start + 1, 0)
    finally:
        workbook.close()
    return output_path
