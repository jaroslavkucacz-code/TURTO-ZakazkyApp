#!/usr/bin/env python3
"""TURTO CRM 7.6.10: exact supplier-red fragments and 4+2 Excel layout."""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    provider_path = source / "offers_engine" / "providers" / "nevegar.py"
    spec = importlib.util.spec_from_file_location("_turto_nevoga_7610", provider_path)
    provider = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(provider)

    values = {
        "version": "P",
        "type": "B",
        "iron": "10",
        "stirrup_distance": "15",
        "stirrup_width": "16",
        "stirrup_height": "26",
        "pull_out_length": "max 40",
        "dimension": "",
        "box_width": "18,5",
        "box_height": "36",
        "length": "80",
    }
    field_segments = {
        key: [{"text": str(value), "red": False}]
        for key, value in values.items()
        if value
    }
    # Simulate the supplier making only the shortened lü value red.  The label
    # "lü=", separators and every other product parameter must stay black.
    field_segments["pull_out_length"] = [
        {"text": "max", "red": False},
        {"text": "40", "red": True},
    ]
    description, rich_segments = provider._technical_description(
        values, field_segments
    )
    assert "lü=max 40 cm" in description
    red_text = "".join(
        segment["text"] for segment in rich_segments if segment.get("changed")
    )
    assert red_text == "40", red_text
    assert not any(
        segment.get("changed") and "lü=" in segment.get("text", "")
        for segment in rich_segments
    )

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    data = {
        "supplier": "Nevoga",
        "offer_no": "2026 / 906",
        "date": "31.08.2026",
        "reference": "Kvilda",
        "net": 1003.17,
        "items": [
            {
                "position": 2,
                "product": "BWSP26/0906/02",
                "description": description,
                "rich_segments": rich_segments,
                "quantity": 2,
                "unit": "ks",
                "unit_price": 501.585,
                "item_total": 1003.17,
                "image_bytes": png,
                "image_ext": "png",
            }
        ],
    }

    with tempfile.TemporaryDirectory(prefix="turto7610_") as temp:
        output = pathlib.Path(temp) / "nevoga.xlsx"
        provider.export_excel(data, output)
        assert output.is_file()

        with zipfile.ZipFile(output) as book:
            sheet_xml = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
            assert 'ref="C9:F9"' in sheet_xml, "Popis header must span exactly four columns"
            assert 'ref="G9:H9"' in sheet_xml, "Image header must span exactly two columns"
            assert 'ref="C10:F10"' in sheet_xml, "Item description must span C:F"
            assert 'ref="G10:H10"' in sheet_xml, "Item image area must span G:H"

            drawing_name = next(
                name for name in book.namelist()
                if name.startswith("xl/drawings/drawing") and name.endswith(".xml")
            )
            drawing = ET.fromstring(book.read(drawing_name))
            ns_d = {
                "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
            }
            from_cols = [
                int(node.text)
                for node in drawing.findall(".//xdr:from/xdr:col", ns_d)
                if node.text is not None
            ]
            assert 6 in from_cols, from_cols  # zero-based G column

            shared = ET.fromstring(book.read("xl/sharedStrings.xml"))
            ns_s = {
                "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            }
            red_runs = []
            for run in shared.findall(".//s:r", ns_s):
                colour = run.find("./s:rPr/s:color", ns_s)
                if colour is None:
                    continue
                rgb = str(colour.attrib.get("rgb") or "").upper()
                if not rgb.endswith("FF0000"):
                    continue
                text = "".join(
                    node.text or "" for node in run.findall("./s:t", ns_s)
                )
                if text:
                    red_runs.append(text)
            assert red_runs == ["40"], red_runs

    print(
        "OK 7.6.10: only the real supplier-red fragment stays red; "
        "description spans 4 columns and the type image spans the next 2"
    )


if __name__ == "__main__":
    main()
