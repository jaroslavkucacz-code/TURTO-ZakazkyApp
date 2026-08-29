"""Runtime integration for scalable Ceníky."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import categories
from .price_dialogs import metadata_dialog
from . import price_page as price_page_module


def _patch_save(M) -> None:
    from .. import importer, offer_integration, storage

    if getattr(storage, "_turto_category_save_v630", False):
        return
    old_save = storage._save_price_list

    def save(path, parsed, metadata):
        price_list_id, created = old_save(path, parsed, metadata)
        category_id = metadata.get("category_id")
        auto = bool(metadata.get("auto_category", False))
        with M.db() as con:
            con.execute("UPDATE price_lists SET category_id=? WHERE id=?", (category_id, price_list_id))
            if category_id:
                con.execute(
                    "UPDATE price_list_items SET category_id=?,subgroup_id=NULL WHERE price_list_id=?",
                    (category_id, price_list_id),
                )
        if auto:
            categories.autocategorize_price_list(M, int(price_list_id), only_empty=True)
        return price_list_id, created

    storage._save_price_list = save
    importer._save_price_list = save
    offer_integration._save_price_list = save
    importer._metadata_dialog = lambda parent, parsed, path, source_offer_id=None: metadata_dialog(
        M, parent, parsed, Path(path), source_offer_id
    )
    offer_integration._metadata_dialog = lambda parent, parsed, path, source_offer_id=None: metadata_dialog(
        M, parent, parsed, Path(path), source_offer_id
    )
    storage._turto_category_save_v630 = True


def _patch_pohlcon(M) -> None:
    from .. import pdf_pohlcon, pdf_router

    if getattr(pdf_pohlcon, "_turto_kunex_bv_v630", False):
        return
    old_parser = pdf_pohlcon._parse_pohlcon

    def parse(text: str):
        parsed = old_parser(text)
        if not parsed:
            return parsed
        rules = []
        replaced = False
        for raw in parsed.get("rules") or []:
            rule = dict(raw)
            if float(rule.get("percent_value") or 0) == 50 and "bv" in str(rule.get("condition_text") or "").casefold():
                rule.update(
                    scope_type="product_name_prefix",
                    scope_value="Kunex",
                    rule_type="informational_surcharge_pct",
                    condition_text="Pouze výrobky Kunex v provedení BV (odolné bitumenům): příplatek 50 %, není-li u konkrétní položky uvedeno jinak.",
                )
                replaced = True
            rules.append(rule)
        if not replaced:
            rules.append(
                {
                    "scope_type": "product_name_prefix",
                    "scope_value": "Kunex",
                    "rule_type": "informational_surcharge_pct",
                    "percent_value": 50,
                    "condition_text": "Pouze výrobky Kunex v provedení BV (odolné bitumenům): příplatek 50 %, není-li u konkrétní položky uvedeno jinak.",
                    "priority": 10,
                }
            )
        parsed["rules"] = rules
        return parsed

    pdf_pohlcon._parse_pohlcon = parse
    pdf_router._parse_pohlcon = parse
    pdf_pohlcon._turto_kunex_bv_v630 = True


def _patch_fert_parser(M) -> None:
    """Keep the existing FERT parser and add a conservative OCR fallback."""
    from .. import pdf_fert, pdf_router
    from ..common import _iso_date, _number
    from ..model import _base_item

    if getattr(pdf_fert, "_turto_fert_fallback_v630", False):
        return
    old_parser = pdf_fert._parse_fert_ocr

    def parse(text: str, pages: list[dict]):
        parsed = old_parser(text, pages)
        if parsed:
            return parsed
        if "FERT" not in str(text or "").upper():
            return None
        lines = []
        for page in pages or []:
            for line in page.get("lines") or []:
                value = " ".join(str(line.get("text") or "").split())
                if value:
                    lines.append(value)
        if not lines:
            lines = [" ".join(line.split()) for line in str(text or "").splitlines() if line.strip()]
        items = []
        skip_words = ("celkem", "dph", "součet", "soucet", "základ daně", "zaklad dane", "doprav")
        for index, line in enumerate(lines, 1):
            low = line.casefold()
            if any(word in low for word in skip_words):
                continue
            values = re.findall(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*[,.]\d{2,4})(?!\d)", line)
            if not values:
                continue
            price_token = values[-1]
            price = _number(price_token)
            if price <= 0:
                continue
            pos = line.rfind(price_token)
            name = line[:pos].strip(" -;|")
            name = re.sub(r"^\d{1,3}[.)\s-]+", "", name).strip()
            if len(name) < 3:
                continue
            unit_match = re.search(r"\b(ks|bal|pal|m2|m²|m|kg)\b", line, re.I)
            unit = unit_match.group(1) if unit_match else "ks"
            items.append(
                _base_item(
                    row_no=index,
                    name=name,
                    description=name,
                    unit=unit.replace("m2", "m²"),
                    source_price=price,
                    source_row_json=json.dumps({"ocr": line}, ensure_ascii=False),
                )
            )
        if not items:
            return None
        number = re.search(r"(?:číslo|cislo|nabídka|nabidka)\D*([A-Z0-9/-]{4,})", text, re.I)
        issued = re.search(r"(\d{1,2}\.\d{1,2}\.20\d{2})", text)
        return {
            "supplier": "FERT a.s.",
            "title": f"FERT {number.group(1)}" if number else "Ceník FERT",
            "valid_from": _iso_date(issued.group(1)) if issued else "",
            "valid_to": "",
            "product_group": "Distanční prvky",
            "branch": "Česká republika",
            "currency": "CZK",
            "items": items,
            "terms_text": str(text or "")[-2500:],
            "parse_status": "OCR – zkontrolovat položky",
            "source_type": "PDF/OCR",
        }

    pdf_fert._parse_fert_ocr = parse
    pdf_router._parse_fert_ocr = parse
    pdf_fert._turto_fert_fallback_v630 = True


def _install_page_methods(M) -> None:
    """Register one scalable page owner without wrapping ``App.build`` again.

    The original page builder calls its refresh function while the page is still
    hidden during startup. Guard the module-level refresh as well, so both that
    call and the Notebook event remain cheap until Ceníky are actually visible.
    """
    App = M.App
    if getattr(App, "_turto_scalable_price_page_v6331", False):
        return

    original_refresh = price_page_module.refresh_price_lists

    def visible_refresh(module, app):
        if getattr(app, "_current_page", None) != "pricelists":
            dirty = set(getattr(app, "_turto_dirty_pages", set()))
            dirty.add("pricelists")
            app._turto_dirty_pages = dirty
            return None
        return original_refresh(module, app)

    price_page_module.refresh_price_lists = visible_refresh
    App.refresh_price_lists = lambda self: visible_refresh(M, self)
    App.build_price_lists = lambda self: price_page_module.build_price_lists(M, self)
    App._turto_scalable_price_page_v6331 = True


def install(M) -> None:
    _patch_save(M)
    _patch_pohlcon(M)
    _patch_fert_parser(M)
    _install_page_methods(M)
