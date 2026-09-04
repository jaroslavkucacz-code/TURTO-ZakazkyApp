#!/usr/bin/env python3
"""Regression check for the Nevegar / Reinforcement Systems offer provider."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

import fitz


def _put(page, x, y, text, size=7):
    page.insert_text((x, y), str(text), fontsize=size, fontname="helv")


def _fixture(path):
    doc = fitz.open()
    page = doc.new_page(width=841.92, height=595.32)
    _put(page, 35, 35, "REINFORCEMENT SYSTEMS", 14)
    _put(page, 35, 55, "OFFER CUSTOM-MADE PRODUCTS", 12)
    _put(page, 660, 95, "Offer 2026 / 906", 11)
    _put(page, 660, 120, "31.08.2026", 8)
    _put(page, 35, 470, "Customer: TURTO s.r.o., Jaroslav Kucera", 8)
    _put(page, 350, 470, "Project: Kvilda", 8)

    rows = [
        (300, ("1", "P", "BWSP26/0906/01", "2", "B", "10", "15", "16", "26", "50", "", "18,5", "36", "125", "614,85 CZK", "", "1 537,13 CZK")),
        (312, ("2", "P", "BWSP26/0906/02", "2", "B", "10", "15", "16", "26", "max 40", "", "18,5", "36", "80", "626,98 CZK", "", "1 003,17 CZK")),
    ]
    xs = (45, 69, 102, 199, 239, 278, 318, 359, 399, 432, 480, 517, 561, 600, 636, 707, 740)
    for y, values in rows:
        for x, value in zip(xs, values):
            if value:
                _put(page, x, y, value, 7)

    _put(page, 730, 455, "Total: 2 540,29 CZK", 8)
    doc.save(path)
    doc.close()


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    provider_path = source / "offers_engine" / "providers" / "nevegar.py"
    spec = importlib.util.spec_from_file_location("_turto_nevegar_provider_test", provider_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with tempfile.TemporaryDirectory(prefix="turto_nevegar_") as temp:
        pdf = pathlib.Path(temp) / "offer.pdf"
        _fixture(pdf)

        assert module.detect(pdf)
        data = module.parse(pdf)
        assert data["supplier"] == "Nevegar"
        assert data["offer_no"] == "2026 / 906"
        assert data["date"] == "31.08.2026"
        assert data["reference"] == "Kvilda"
        assert abs(data["total"] - 2540.29) < 0.001
        assert len(data["items"]) == 2

        a, b = data["items"]
        assert a["product"] == "BWSP26/0906/01"
        assert a["quantity"] == 2 and a["unit"] == "ks"
        assert abs(a["price_per_meter"] - 614.85) < 0.001
        assert abs(a["unit_price"] - 768.565) < 0.001
        assert abs(a["item_total"] - 1537.13) < 0.001
        assert "typ B" in a["description"]
        assert "lü=50 cm" in a["description"]
        assert a["image_bytes"] and a["image_ext"] == "png"

        assert b["product"] == "BWSP26/0906/02"
        assert abs(b["price_per_meter"] - 626.98) < 0.001
        assert abs(b["unit_price"] - 501.585) < 0.001
        assert "lü=max 40 cm" in b["description"]

    print("OK Nevegar: 2 items, geometry, per-metre pricing, totals and type image")


if __name__ == "__main__":
    main()
