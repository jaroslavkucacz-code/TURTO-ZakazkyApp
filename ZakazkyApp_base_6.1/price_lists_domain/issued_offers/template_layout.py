"""Versioned, validated PDF layout settings. Never overwrite a user's template."""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path

ENGINE = "turto-corporate-v1"
BUILTIN_KEY = "turto-corporate-790"
ASSETS = {
    "builtin:turto-offer-header": "turto_offer_header.jpg",
    "builtin:turto-offer-footer": "turto_offer_footer.jpg",
}
COLUMNS = {
    "position": ("Poz.", 5), "quantity": ("Množ.", 8),
    "name": ("Název / popis", 41), "image": ("Obrázek", 16),
    "code": ("Kód", 12), "unit": ("MJ", 5),
    "recommended": ("Doporučená cena", 14), "discount": ("Sleva", 7),
    "unit_price": ("Cena/MJ", 14), "total": ("Cena celkem", 16),
}
REQUIRED = {"quantity", "name", "unit", "unit_price", "total"}
DEFAULT = {
    "engine": ENGINE, "version": 1, "font_size": 9.0,
    "row_padding_mm": 1.6, "image_height_mm": 13.5,
    "title": "CENOVÁ NABÍDKA", "show_images": True,
    "number_in_header": True, "edit_opening_hours": False,
    "opening_hours": "Po – Čt: 7:30 – 15:30\nPá: 8:30 – 15:00",
    "show_vat_summary": False, "show_contacts": True,
    "show_salesperson": True, "closing_columns": True,
    "show_group_subtotals": False, "zebra_rows": False,
    "primary_color": "#0E354A", "section_color": "#C31F40",
    "subsection_color": "#EBEEF0", "contacts_text": "",
    "signature_path": "", "closing_note": "",
    "columns": [dict(key=k, label=COLUMNS[k][0], width=COLUMNS[k][1])
                for k in ("quantity", "name", "image", "unit", "unit_price", "total")],
}


def asset_path(value):
    value = str(value or "")
    if value in ASSETS:
        return str(Path(__file__).with_name("assets") / ASSETS[value])
    return value


def is_corporate(template):
    try:
        value = template.get("layout_json") or {}
        if isinstance(value, str):
            value = json.loads(value)
        return value.get("engine") == ENGINE
    except (TypeError, ValueError, AttributeError):
        return False


def _finite(value, label, minimum, maximum):
    try:
        n = float(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        raise ValueError(f"{label}: zadejte číslo.") from None
    if not math.isfinite(n) or not minimum <= n <= maximum:
        raise ValueError(f"{label}: povolený rozsah je {minimum:g}–{maximum:g}.")
    return n


def normalize(value=None):
    import re
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except ValueError:
            raise ValueError("Neplatný formát nastavení šablony.") from None
    if value is not None and not isinstance(value, dict):
        raise ValueError("Nastavení šablony musí být objekt.")
    source = value or {}
    result = copy.deepcopy(DEFAULT)
    # Ignore unknown fields on import; no code, paths or expressions are executed.
    result.update({k: v for k, v in source.items() if k in DEFAULT})
    if result["engine"] != ENGINE or result["version"] != 1:
        raise ValueError("Tato verze formátu šablony není podporovaná.")
    for key, label, lo, hi in (("font_size", "Písmo [pt]", 7.5, 12),
        ("row_padding_mm", "Odsazení řádku [mm]", 1, 6),
        ("image_height_mm", "Výška obrázku [mm]", 8, 35)):
        result[key] = _finite(result[key], label, lo, hi)
    for key in ("primary_color", "section_color", "subsection_color"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(result[key])):
            raise ValueError("Barva musí být zapsaná jako #RRGGBB.")
    for key in ("title", "contacts_text", "closing_note", "signature_path", "opening_hours"):
        result[key] = str(result[key] or "").strip()
        if len(result[key]) > 6000:
            raise ValueError("Text šablony je příliš dlouhý (max. 6000 znaků).")
    if len(result["opening_hours"].splitlines()) > 4 or len(result["opening_hours"]) > 160:
        raise ValueError("Otevírací doba: nejvýše 4 řádky a 160 znaků.")
    if not result["title"] or len(result["title"]) > 100:
        raise ValueError("Nadpis nabídky musí mít 1 až 100 znaků.")
    for key in ("show_images", "show_vat_summary", "show_contacts", "show_salesperson",
                "closing_columns", "show_group_subtotals", "zebra_rows",
                "number_in_header", "edit_opening_hours"):
        if result[key] not in (True, False, 0, 1):
            raise ValueError(f"Neplatná volba: {key}")
        result[key] = bool(result[key])
    rows = result["columns"]
    if not isinstance(rows, list) or not 5 <= len(rows) <= len(COLUMNS):
        raise ValueError("Vyberte 5 až 10 sloupců tabulky.")
    seen = set()
    clean = []
    for row in rows:
        key = row.get("key") if isinstance(row, dict) else None
        if key not in COLUMNS or key in seen:
            raise ValueError("Neplatný nebo opakovaný sloupec tabulky.")
        seen.add(key)
        label = str(row.get("label") or COLUMNS[key][0]).strip()
        if len(label) > 45:
            raise ValueError("Záhlaví sloupce smí mít nejvýše 45 znaků.")
        clean.append(dict(key=key, label=label, width=_finite(row.get("width"), label, 1, 100)))
    if not REQUIRED <= seen:
        raise ValueError("Nelze skrýt popis, množství, MJ ani prodejní ceny.")
    result["columns"] = clean
    return result


def columns_for(layout, width_pt):
    rows = [dict(c) for c in layout["columns"]
            if c["key"] != "image" or layout["show_images"]]
    total = sum(c["width"] for c in rows)
    for c in rows:
        c["width_pt"] = width_pt * c["width"] / total
        minimum = 105 if c["key"] == "name" else 36 if c["key"] in {"unit_price", "total", "recommended"} else 18
        if c["width_pt"] < minimum:
            raise ValueError(f"Sloupec {c['label']} je příliš úzký. Zvětšete jeho poměrnou šířku nebo skryjte jiný sloupec.")
    return rows


def validate_geometry(template, layout):
    specs = (("margin_left_mm", "Levý okraj", 5, 40, 14),
             ("margin_right_mm", "Pravý okraj", 5, 40, 14),
             ("header_height_mm", "Výška záhlaví", 0, 50, 20),
             ("footer_height_mm", "Výška zápatí", 0, 35, 16),
             ("body_top_gap_mm", "Mezera pod záhlavím", 0, 20, 5),
             ("body_bottom_gap_mm", "Mezera nad zápatím", 0, 20, 5))
    result = dict(template)
    for key, label, lo, hi, default in specs:
        result[key] = _finite(result.get(key, default), label + " [mm]", lo, hi)
    if result["header_height_mm"] + result["footer_height_mm"] + result["body_top_gap_mm"] + result["body_bottom_gap_mm"] > 90:
        raise ValueError("Záhlaví, zápatí a mezery zabírají příliš velkou část stránky.")
    columns_for(layout, (210 - result["margin_left_mm"] - result["margin_right_mm"]) * 72 / 25.4)
    return result


def builtin_template():
    return dict(name="TURTO – Standard", active=1, is_default=0,
        header_path="builtin:turto-offer-header", footer_path="builtin:turto-offer-footer",
        header_height_mm=20.5, footer_height_mm=16, margin_left_mm=14, margin_right_mm=14,
        body_top_gap_mm=5, body_bottom_gap_mm=5, header_every_page=1, footer_every_page=1,
        layout_json=json.dumps(DEFAULT, ensure_ascii=False), builtin_key=BUILTIN_KEY)


def ensure_builtin(con):
    """Seed once, retaining every existing template and document assignment."""
    if con.execute("SELECT id FROM business_document_templates WHERE builtin_key=?", (BUILTIN_KEY,)).fetchone():
        return
    old = con.execute("SELECT name,header_path,footer_path FROM business_document_templates WHERE is_default=1 AND active=1 AND document_type='issued_offer' LIMIT 1").fetchone()
    promote = not old or (old[0] == "Standardní nabídka TURTO" and not old[1] and not old[2])
    data = builtin_template()
    # Avoid a name collision with a user's unrelated template.
    while con.execute("SELECT 1 FROM business_document_templates WHERE name=? AND document_type='issued_offer'", (data["name"],)).fetchone():
        data["name"] += " (7.9)"
    data["is_default"] = int(promote)
    if promote:
        con.execute("UPDATE business_document_templates SET is_default=0 WHERE document_type='issued_offer'")
    keys = tuple(data)
    con.execute(f"INSERT INTO business_document_templates({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", tuple(data[k] for k in keys))


def is_original_asset(value, key):
    """Only overlay known TURTO art, never an unrelated user's graphic."""
    import hashlib
    if value == key:
        return True
    try:
        original = Path(asset_path(key)).read_bytes()
        return hashlib.sha256(Path(asset_path(value)).read_bytes()).digest() == hashlib.sha256(original).digest()
    except (OSError, TypeError):
        return False
