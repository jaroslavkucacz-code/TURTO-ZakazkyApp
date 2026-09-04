#!/usr/bin/env python3
import io
import pathlib
import sys
import tempfile
import zipfile

from PIL import Image


def _png_bytes():
    bio = io.BytesIO()
    Image.new('RGB', (80, 50), (225, 205, 145)).save(bio, format='PNG')
    return bio.getvalue()


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    sys.path.insert(0, str(source / "offers_engine"))
    import Gerotop_Parser as anchor_parser
    import Gerotop_Parser_767 as parser

    for code in (
        "202-100-300",
        "286-250-000",
        "411-0400-030-355",
        "411-0100-030-044,5",
    ):
        assert anchor_parser.PRODUCT_CODE_RE.fullmatch(code), code

    class Rect:
        width = 595.2

    class Page:
        rect = Rect()

        def get_text(self, kind):
            assert kind == "words"
            return [
                (35, 80, 70, 90, "202-100-300", 0, 0, 0),
                (35, 120, 78, 130, "411-0100-030-044,5", 0, 0, 0),
                (35, 170, 70, 180, "202-100-300", 0, 0, 0),
                (480, 170, 540, 180, "202-100-300", 0, 0, 0),
            ]

    anchors = anchor_parser._row_anchors(Page())
    assert [item[0] for item in anchors] == [
        "202-100-300",
        "411-0100-030-044,5",
        "202-100-300",
    ]

    image = _png_bytes()
    sample = {
        "supplier": "GEROtop",
        "offer_no": "PTEST-2026",
        "date": "03.09.2026",
        "reference": "TEST",
        "gross": 133.3334,
        "discount_pct": 25.0,
        "discount_value": -33.3334,
        "net": 100.0,
        "vat": None,
        "total": None,
        "items": [
            {
                "position": 10,
                "product": "202-100-300",
                "description": "Testovací výrobek",
                "item_key": "10:202-100-300:Testovací výrobek",
                "details": "• detail",
                "bullets": ["detail"],
                "rich_segments": [{"text": "• detail", "bold": False}],
                "bold_terms": [],
                "quantity": 2,
                "unit": "KS",
                "unit_price": 50.0,
                "discount_pct": 25.0,
                "original_unit_price": 66.6667,
                "item_total": 100.0,
                "image_bytes": image,
                "image_ext": "png",
            }
        ],
    }

    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "gerotop.xlsx"
        parser.export_excel(sample, out)
        assert out.exists()
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
            assert any("/media/" in name for name in names), names
            assert any("drawing" in name.lower() for name in names), names
            xml = "".join(
                archive.read(name).decode("utf-8", "ignore")
                for name in names
                if name.endswith(".xml")
            )
        assert "#VALUE!" not in xml
        assert "DISPIMG" not in xml.upper()

    anchor_text = (
        source / "offers_engine" / "Gerotop_Parser.py"
    ).read_text(encoding="utf-8")
    parser_text = (
        source / "offers_engine" / "Gerotop_Parser_767.py"
    ).read_text(encoding="utf-8")
    router_text = (
        source / "offers_engine" / "Nabidky_Router.py"
    ).read_text(encoding="utf-8")
    assert "page.get_text('words')" in anchor_text
    anchor_block = anchor_text.split("def _row_anchors", 1)[1].split(
        "def _modern_anchors", 1
    )[0]
    assert "page.get_text('blocks')" not in anchor_block
    assert "def _extract_row_image" in parser_text
    assert "insert_image" in parser_text
    assert "Gerotop_Parser_767 as gerotop" in router_text
    assert "def _strip_images" not in router_text
    assert "return _strip_images(data)" not in router_text

    print(
        "TURTO CRM 7.6.7 GEROtop word-anchor / restored-image validation passed"
    )


if __name__ == "__main__":
    main()
