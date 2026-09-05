#!/usr/bin/env python3
"""Validate Nevoga 4+2 Excel, exact red text, metres and explicit routing."""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _load_provider(source: pathlib.Path):
    path = source / "offers_engine" / "providers" / "nevegar.py"
    spec = importlib.util.spec_from_file_location("_turto_nevoga_7610", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _inspect_xlsx(output: pathlib.Path, expected_red=("40",)) -> None:
    assert output.is_file() and output.stat().st_size > 0
    with zipfile.ZipFile(output) as book:
        sheet = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert 'ref="C9:F9"' in sheet
        assert 'ref="G9:H9"' in sheet
        assert 'ref="C10:F10"' in sheet
        assert 'ref="G10:H10"' in sheet
        assert 'ref="C9:H9"' not in sheet
        drawing_name = next(name for name in book.namelist() if name.startswith("xl/drawings/drawing") and name.endswith(".xml"))
        drawing = ET.fromstring(book.read(drawing_name))
        ns_d = {"xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}
        columns = [int(node.text) for node in drawing.findall(".//xdr:from/xdr:col", ns_d) if node.text]
        assert 6 in columns, columns
        shared_xml = book.read("xl/sharedStrings.xml")
        assert b"Cena/m" in shared_xml and b">m<" in shared_xml
        shared = ET.fromstring(shared_xml)
        ns_s = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        red_runs = []
        for run in shared.findall(".//s:r", ns_s):
            colour = run.find("./s:rPr/s:color", ns_s)
            if colour is None or not str(colour.attrib.get("rgb") or "").upper().endswith("FF0000"):
                continue
            text = "".join(node.text or "" for node in run.findall("./s:t", ns_s))
            if text:
                red_runs.append(text)
        assert red_runs == list(expected_red), red_runs


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    provider = _load_provider(source)
    values = {
        "version": "P", "type": "B", "iron": "10", "stirrup_distance": "15",
        "stirrup_width": "16", "stirrup_height": "26", "pull_out_length": "max 40",
        "dimension": "", "box_width": "18,5", "box_height": "36", "length": "80",
    }
    fields = {key: [{"text": str(value), "red": False}] for key, value in values.items() if value}
    fields["pull_out_length"] = [{"text": "max ", "red": False}, {"text": "40", "red": True}]
    description, segments = provider._technical_description(values, fields)
    assert "lü=max 40 cm" in description
    assert "".join(item["text"] for item in segments if item.get("changed")) == "40"
    assert not any(item.get("changed") and "lü=" in item.get("text", "") for item in segments)

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    data = {
        "supplier": "Nevoga", "offer_no": "2026 / 906", "date": "31.08.2026",
        "reference": "Kvilda", "net": 1003.17,
        "items": [{
            "position": 2, "product": "BWSP26/0906/02", "description": description,
            "rich_segments": segments, "quantity": 1.6, "unit": "m",
            "unit_price": 1003.17 / 1.6, "item_total": 1003.17,
            "image_bytes": png, "image_ext": "png", "plexus_type": "B",
        }],
    }
    with tempfile.TemporaryDirectory(prefix="turto7610_") as temp:
        output = pathlib.Path(temp) / "nevoga.xlsx"
        provider.export_excel(data, output)
        _inspect_xlsx(output)

    bootstrap = (source / "runtime_bootstrap.py").read_text(encoding="utf-8")
    required = (
        '"v769_nevoga_offer"', '"v7614_nevoga_canonical_export"',
        '"v7615_nevoga_meter_units"', '"v7616_requests_plexus_assets"',
        '"v770_runtime_policy"',
    )
    for token in required:
        assert token in bootstrap, token
    assert bootstrap.index(required[0]) < bootstrap.index(required[1]) < bootstrap.index(required[2]) < bootstrap.index(required[3]) < bootstrap.index(required[4])
    policy = (source / "v770_runtime_policy.py").read_text(encoding="utf-8")
    assert "_ensure_offer_plexus_images" in policy
    assert "offer_source_attachments" in policy
    print("OK 7.7: Nevoga uses metres, C:F + G:H, exact red fragments and DB-backed PLEXUS images")


if __name__ == "__main__":
    main()
