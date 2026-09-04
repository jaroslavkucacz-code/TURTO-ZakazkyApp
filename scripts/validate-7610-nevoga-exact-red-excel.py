#!/usr/bin/env python3
"""TURTO CRM 7.6.10/7.6.11: exact Nevoga Excel output and final UI routing."""
from __future__ import annotations

import base64
import importlib.util
import pathlib
import sys
import tempfile
import types
import zipfile
import xml.etree.ElementTree as ET


def _validate_final_ui_routing(source: pathlib.Path) -> None:
    """The visible Extrakce dat command must not keep v624's legacy closure."""
    routing_path = (
        source / "price_lists_domain" / "platform" / "nevoga_export_routing.py"
    )
    assert routing_path.is_file(), routing_path
    platform_text = (
        source / "price_lists_domain" / "platform" / "__init__.py"
    ).read_text(encoding="utf-8")
    assert "install_nevoga_export_routing" in platform_text

    spec = importlib.util.spec_from_file_location(
        "_turto_nevoga_export_route_7611", routing_path
    )
    routing = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routing)

    old_v769 = sys.modules.get("v769_nevoga_offer")
    old_crm = sys.modules.get("crm_features")
    fake_v769 = types.ModuleType("v769_nevoga_offer")
    fake_crm = types.ModuleType("crm_features")
    sys.modules["v769_nevoga_offer"] = fake_v769
    sys.modules["crm_features"] = fake_crm

    calls = []

    class App:
        def _selected_offer_id(self):
            return 77

    def legacy_selected(_self):
        raise AssertionError("legacy v624 selected-export closure was still called")

    App.export_selected_offer_excel = legacy_selected
    module = types.SimpleNamespace(
        App=App,
        messagebox=types.SimpleNamespace(showinfo=lambda *args, **kwargs: None),
    )

    def original_apply(target):
        def supplier_aware_export(app, offer_id, parent=None):
            calls.append((app, offer_id, parent, "first"))
            return "supplier-aware"

        target.export_offer_excel = supplier_aware_export
        return "v769-applied"

    fake_v769.apply = original_apply

    try:
        routing.install(module)
        result = fake_v769.apply(module)
        assert result == "v769-applied"
        app = App()
        assert app.export_selected_offer_excel() == "supplier-aware"
        assert calls and calls[-1][1] == 77 and calls[-1][2] is app, calls
        assert getattr(module, "_turto_nevoga_export_selected_dynamic", False)

        # Prove the command resolves module.export_offer_excel at click time.
        # This is the regression that 7.6.10 missed: v624 had captured its local
        # legacy exporter before v769 installed the Nevoga-aware dispatcher.
        second = []

        def replacement_export(app, offer_id, parent=None):
            second.append((app, offer_id, parent))
            return "replacement"

        module.export_offer_excel = replacement_export
        assert app.export_selected_offer_excel() == "replacement"
        assert second and second[-1][1] == 77 and second[-1][2] is app, second
    finally:
        if old_v769 is None:
            sys.modules.pop("v769_nevoga_offer", None)
        else:
            sys.modules["v769_nevoga_offer"] = old_v769
        if old_crm is None:
            sys.modules.pop("crm_features", None)
        else:
            sys.modules["crm_features"] = old_crm


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
    # Simulate the supplier making only the shortened lü value red. The label
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

    _validate_final_ui_routing(source)

    print(
        "OK 7.6.11: visible Excel commands resolve the final Nevoga exporter; "
        "only the real supplier-red fragment stays red and the sheet is 4+2"
    )


if __name__ == "__main__":
    main()
