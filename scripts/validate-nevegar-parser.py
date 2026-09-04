#!/usr/bin/env python3
"""Regression checks for Nevoga / Reinforcement Systems offer parsing."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import zipfile

import fitz


XS = (45, 69, 102, 199, 239, 278, 318, 359, 399, 432, 480, 517, 561, 600, 636, 707, 740)


def _put(page, x, y, text, size=7, red=False):
    page.insert_text(
        (x, y),
        str(text),
        fontsize=size,
        fontname="helv",
        color=(1, 0, 0) if red else (0, 0, 0),
    )


def _header(page, offer_no, date_text, project):
    _put(page, 35, 35, "REINFORCEMENT SYSTEMS", 14)
    _put(page, 35, 55, "OFFER CUSTOM-MADE PRODUCTS", 12)
    _put(page, 660, 95, f"Offer {offer_no}", 11)
    _put(page, 660, 120, date_text, 8)
    _put(page, 35, 470, "Customer: TURTO s.r.o., Jaroslav Kucera", 8)
    _put(page, 350, 470, f"Project: {project}", 8)


def _row(page, y, values, red_indexes=()):
    for index, (x, value) in enumerate(zip(XS, values)):
        if value:
            _put(page, x, y, value, 7, red=index in set(red_indexes))


def _fixture_906(path):
    doc = fitz.open()
    page = doc.new_page(width=841.92, height=595.32)
    _header(page, "2026 / 906", "31.08.2026", "Kvilda")
    _row(
        page,
        300,
        ("1", "P", "BWSP26/0906/01", "2", "B", "10", "15", "16", "26", "50", "", "18,5", "36", "125", "614,85 CZK", "", "1 537,13 CZK"),
    )
    _row(
        page,
        312,
        ("2", "P", "BWSP26/0906/02", "2", "B", "10", "15", "16", "26", "max 40", "", "18,5", "36", "80", "626,98 CZK", "", "1 003,17 CZK"),
        red_indexes=(9,),
    )
    _put(page, 700, 455, "Total:", 8)
    _put(page, 740, 455, "2 540,29 CZK", 8)
    doc.save(path)
    doc.close()


def _fixture_alternatives(path):
    doc = fitz.open()
    page = doc.new_page(width=841.92, height=595.32)
    _header(page, "2026 / 896", "28.08.2026", "Test alternatives")
    _row(
        page,
        300,
        ("1", "P", "BK101015EBL80", "2", "B", "10", "15", "16", "26", "50", "", "18,5", "36", "100", "100,00 CZK", "+15%", "230,00 CZK"),
    )
    _row(
        page,
        312,
        ("2", "P", "BK101015EBL90", "1", "B", "10", "15", "16", "26", "50", "", "18,5", "36", "100", "200,00 CZK", "+15%", "230,00 CZK"),
    )
    _put(page, 95, 330, "Alternative: length of element short as possible", 7, red=True)
    _row(
        page,
        345,
        ("3", "P", "BK101015EBL70", "1", "B", "10", "15", "16", "26", "max 10", "", "18,5", "36", "100", "300,00 CZK", "+15%", "345,00 CZK"),
        red_indexes=(9,),
    )
    _put(page, 700, 455, "Total:", 8)
    _put(page, 740, 455, "460,00 CZK", 8)
    doc.save(path)
    doc.close()


def _load_provider(source):
    provider_path = source / "offers_engine" / "providers" / "nevegar.py"
    spec = importlib.util.spec_from_file_location("_turto_nevoga_provider_test", provider_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _red_segments(item):
    return [
        segment for segment in item.get("rich_segments") or []
        if segment.get("changed") or str(segment.get("color") or "").upper() in {"#FF0000", "FF0000"}
    ]


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    module = _load_provider(source)

    with tempfile.TemporaryDirectory(prefix="turto_nevoga_") as temp:
        temp = pathlib.Path(temp)
        pdf_906 = temp / "offer_906.pdf"
        _fixture_906(pdf_906)

        assert module.detect(pdf_906)
        data = module.parse(pdf_906)
        assert data["offer_no"] == "2026 / 906"
        assert data["date"] == "31.08.2026"
        assert data["reference"] == "Kvilda"
        assert abs(data["total"] - 2540.29) < 0.001
        assert len(data["items"]) == 2

        a, b = data["items"]
        assert a["product"] == "BWSP26/0906/01"
        assert abs(a["quantity"] - 2.5) < 0.001 and a["unit"] == "m"
        assert abs(a["original_unit_price"] - 614.85) < 0.001
        assert abs(a["unit_price"] - (1537.13 / 2.5)) < 0.001
        assert abs(a["item_total"] - 1537.13) < 0.001
        assert "PLEXUS" in a["description"]
        for token in ("typ B", "Ø10 mm", "s=15 cm", "b=16 cm", "h=26 cm", "lü=50 cm", "box b=18,5 cm", "box h=36 mm", "L=125 cm"):
            assert token in a["description"], token
        assert "Zdrojové množství: 2 ks × 1,25 m = 2,5 m" in a["details"]
        assert "Zdrojová cena: 614,85 CZK/m" in a["details"]
        assert a["image_bytes"] and a["image_ext"] == "png"

        # Technical geometry is intentionally NOT exposed as separate item/DB fields.
        for key in ("type", "iron", "stirrup_distance", "stirrup_width", "stirrup_height", "pull_out_length", "dimension", "box_width", "box_height", "length", "price_per_meter", "length_cm"):
            assert key not in a, key
            assert key not in b, key

        assert b["product"] == "BWSP26/0906/02"
        assert abs(b["quantity"] - 1.6) < 0.001 and b["unit"] == "m"
        assert abs(b["original_unit_price"] - 626.98) < 0.001
        assert abs(b["unit_price"] - (1003.17 / 1.6)) < 0.001
        assert "Zdrojové množství: 2 ks × 0,8 m = 1,6 m" in b["details"]
        assert "lü=max 40 cm" in b["description"]
        assert b["changed_fields"] == ["pull_out_length"]
        red = _red_segments(b)
        assert any("max 40" in segment["text"] for segment in red), red
        # Generated label/unit are never red merely because the supplier value is red.
        assert not any("lü=" in segment["text"] or "cm" in segment["text"] for segment in red), red

        # The standalone supplier workbook must preserve metre units, partial red formatting and image.
        xlsx = temp / "offer_906.xlsx"
        module.export_excel(data, xlsx)
        with zipfile.ZipFile(xlsx) as archive:
            names = archive.namelist()
            assert any(name.startswith("xl/media/") for name in names), names
            xml = b"\n".join(
                archive.read(name)
                for name in names
                if name.endswith(".xml")
            )
            assert b"FFFF0000" in xml or b"FF0000" in xml
            assert b"Cena/m" in xml
            assert b">m<" in xml

        pdf_alt = temp / "offer_896.pdf"
        _fixture_alternatives(pdf_alt)
        alt_data = module.parse(pdf_alt)
        assert alt_data["offer_no"] == "2026 / 896"
        assert len(alt_data["items"]) == 3
        assert abs(alt_data["total"] - 460.0) < 0.001
        main_a, main_b, alternative = alt_data["items"]
        assert abs(main_a["quantity"] - 2.0) < 0.001 and main_a["unit"] == "m"
        assert abs(main_a["original_unit_price"] - 100.0) < 0.001
        assert abs(main_a["unit_price"] - 115.0) < 0.001
        assert abs(main_a["discount_pct"] + 15.0) < 0.01
        assert abs(main_b["quantity"] - 1.0) < 0.001 and main_b["unit"] == "m"
        assert abs(main_b["unit_price"] - 230.0) < 0.001
        assert abs(main_b["discount_pct"] + 15.0) < 0.01
        assert alternative["alternative"] is True
        assert alternative["unit"] == "m"
        assert "ALTERNATIVA" in alternative["description"]
        assert "lü=max 10 cm" in alternative["description"]
        assert "pull_out_length" in alternative["changed_fields"]
        alt_red = _red_segments(alternative)
        # "ALTERNATIVA –" is TURTO-generated text and therefore must stay black.
        assert not any("ALTERNATIVA" in segment["text"] for segment in alt_red), alt_red
        # Only the supplier's actual red note and actual red parameter value stay red.
        assert any("length of element short as possible" in segment["text"] for segment in alt_red), alt_red
        assert any("max 10" in segment["text"] for segment in alt_red), alt_red
        assert "není zahrnuta do celku nabídky" in alternative["details"]

    provider_text = (source / "offers_engine" / "providers" / "nevegar.py").read_text(encoding="utf-8")
    assert "changed_fields" in provider_text
    assert "changed_fragments" in provider_text
    assert "rich_segments" in provider_text
    assert "Červený text = hodnota upravená výrobcem oproti zadání." in provider_text
    assert '"price_per_meter": price_per_meter' not in provider_text
    assert '"length_cm": length_cm' not in provider_text
    assert '"unit": "m"' in provider_text
    assert '"Cena/m"' in provider_text

    print("OK Nevoga: metre units/prices, exact supplier-red fragments, unified descriptions, alternatives, images and totals")


if __name__ == "__main__":
    main()
