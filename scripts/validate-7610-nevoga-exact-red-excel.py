#!/usr/bin/env python3
"""TURTO CRM 7.6.10+ / 7.6.14: exact Nevoga Excel and automatic archive routing."""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import sqlite3
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _validate_final_ui_routing(source: pathlib.Path) -> None:
    """Visible and automatic extraction must both resolve the final exporter."""
    legacy_text = (source / "v624_legacy_exports.py").read_text(encoding="utf-8")
    assert "exporter = getattr(M, 'export_offer_excel', None)" in legacy_text
    assert "return exporter(self, offer_id, self)" in legacy_text
    assert "M, 'export_offer_excel', export_legacy" in legacy_text
    assert "command=lambda: export_legacy(" not in legacy_text

    nevoga_text = (source / "v769_nevoga_offer.py").read_text(encoding="utf-8")
    assert "M.export_offer_excel = export_offer_excel" in nevoga_text
    assert 'provider["export"](data, path, price_alerts=None)' in nevoga_text

    route_text = (source / "v7614_nevoga_canonical_export.py").read_text(encoding="utf-8")
    assert 'exporter = getattr(M, "export_offer_excel", None)' in route_text
    assert "previous_process_msg" in route_text
    assert "previous_process_pdf" in route_text
    assert "refresh_automatic_excel" in route_text
    assert "v624_legacy_exports" not in route_text

    bridge = (source / "v768_clean_table_markers.py").read_text(encoding="utf-8")
    assert "v769_nevoga_offer.apply(M)" in bridge
    assert "v7614_nevoga_canonical_export.apply(M)" in bridge
    assert bridge.index("v769_nevoga_offer.apply(M)") < bridge.index(
        "v7614_nevoga_canonical_export.apply(M)"
    )


def _inspect_xlsx(output: pathlib.Path, expected_red=("40",)) -> None:
    assert output.is_file() and output.stat().st_size > 0
    with zipfile.ZipFile(output) as book:
        sheet_xml = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert 'ref="C9:F9"' in sheet_xml, "Popis header must span exactly four columns"
        assert 'ref="G9:H9"' in sheet_xml, "Image header must span exactly two columns"
        assert 'ref="C10:F10"' in sheet_xml, "Item description must span C:F"
        assert 'ref="G10:H10"' in sheet_xml, "Item image area must span G:H"
        assert 'ref="C9:H9"' not in sheet_xml, "Legacy six-column description must never survive"

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
        ns_s = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        red_runs = []
        for run in shared.findall(".//s:r", ns_s):
            colour = run.find("./s:rPr/s:color", ns_s)
            if colour is None:
                continue
            rgb = str(colour.attrib.get("rgb") or "").upper()
            if not rgb.endswith("FF0000"):
                continue
            text = "".join(node.text or "" for node in run.findall("./s:t", ns_s))
            if text:
                red_runs.append(text)
        assert red_runs == list(expected_red), red_runs


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
    # Only the supplier's genuinely red source fragment is allowed to be red.
    field_segments["pull_out_length"] = [
        {"text": "max", "red": False},
        {"text": "40", "red": True},
    ]
    description, rich_segments = provider._technical_description(values, field_segments)
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
        root = pathlib.Path(temp)
        direct_output = root / "nevoga-direct.xlsx"
        provider.export_excel(data, direct_output)
        _inspect_xlsx(direct_output)

        # Reproduce the real 7.6.13 failure mode: the old automatic MSG layer
        # first writes a legacy file. The 7.6.14 layer must overwrite the same
        # target by resolving the final Nevoga exporter at CALL TIME.
        route_path = source / "v7614_nevoga_canonical_export.py"
        route_spec = importlib.util.spec_from_file_location("_turto_nevoga_7614", route_path)
        route = importlib.util.module_from_spec(route_spec)
        route_spec.loader.exec_module(route)

        target = root / "Extrakce dat CN 2026 _ 906_Kvilda.xlsx"
        db_path = root / "route.db"
        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE companies(
              id INTEGER PRIMARY KEY, official_name TEXT, short_name TEXT
            );
            CREATE TABLE supplier_offers(
              id INTEGER PRIMARY KEY, supplier_name TEXT, supplier_company_id INTEGER
            );
            INSERT INTO companies(id,official_name,short_name)
              VALUES(1,'Nevoga s.r.o.','Nevoga');
            INSERT INTO supplier_offers(id,supplier_name,supplier_company_id)
              VALUES(906,'Nevoga',1);
            """
        )
        con.commit()
        con.close()

        class Module:
            def __init__(self):
                self.export_offer_excel = self.final_export
                self.process_offer_msg = self.legacy_msg
                self.process_offer_pdf = self.legacy_pdf
                self.offer_export_filename = lambda _offer_id: target.name

            def db(self):
                db = sqlite3.connect(db_path)
                db.row_factory = sqlite3.Row
                return db

            def final_export(self, _app, _offer_id, parent=None):
                from tkinter import filedialog
                output = pathlib.Path(filedialog.asksaveasfilename(parent=parent))
                provider.export_excel(data, output)
                return str(output)

            def legacy_msg(self, _app, *_args, **_kwargs):
                target.write_bytes(b"LEGACY-V624-SIX-COLUMN-EXPORT")
                return {
                    "offers": [{"offer_id": 906}],
                    "excel_files": [str(target)],
                    "archive_folder": str(root),
                    "errors": [],
                }

            def legacy_pdf(self, _app, *_args, **_kwargs):
                target.write_bytes(b"LEGACY-V624-SIX-COLUMN-EXPORT")
                return {
                    "offer_id": 906,
                    "excel_files": [str(target)],
                    "archive_folder": str(root),
                    "errors": [],
                }

        module = Module()
        route.apply(module)
        msg_result = module.process_offer_msg(object(), "fixture.msg")
        assert not msg_result.get("errors"), msg_result.get("errors")
        assert msg_result["excel_files"] == [str(target)]
        _inspect_xlsx(target)

        target.unlink()
        pdf_result = module.process_offer_pdf(object(), "fixture.pdf")
        assert not pdf_result.get("errors"), pdf_result.get("errors")
        _inspect_xlsx(target)

    _validate_final_ui_routing(source)

    print(
        "OK 7.6.14: manual + automatic PDF/MSG Nevoga extraction uses the final "
        "4+2 exporter with PLEXUS image and only exact supplier-red fragments"
    )


if __name__ == "__main__":
    main()
