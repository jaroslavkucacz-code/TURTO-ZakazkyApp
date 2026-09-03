#!/usr/bin/env python3
import pathlib
import sys
import tempfile
import zipfile


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    sys.path.insert(0, str(source / "offers_engine"))
    import Gerotop_Parser as parser

    for code in (
        "202-100-300",
        "286-250-000",
        "411-0400-030-355",
        "411-0100-030-044,5",
    ):
        assert parser.PRODUCT_CODE_RE.fullmatch(code), code

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

    anchors = parser._row_anchors(Page())
    assert [item[0] for item in anchors] == [
        "202-100-300",
        "411-0100-030-044,5",
        "202-100-300",
    ]

    sample = {
        "supplier": "GEROtop",
        "offer_no": "PTEST-2026",
        "date": "03.09.2026",
        "reference": "TEST",
        "net": 100.0,
        "items": [
            {
                "product": "202-100-300",
                "description": "Testovací výrobek",
                "details": "• detail",
                "quantity": 2,
                "unit": "KS",
                "unit_price": 50.0,
                "discount_pct": 25.0,
                "original_unit_price": 66.6667,
                "item_total": 100.0,
                "image_bytes": b"should disappear",
                "image_ext": "png",
            }
        ],
    }
    parser._without_images(sample)
    assert sample["items"][0]["image_bytes"] is None
    assert sample["items"][0]["image_ext"] is None

    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "gerotop.xlsx"
        parser.export_excel(sample, out)
        assert out.exists()
        with zipfile.ZipFile(out) as archive:
            names = archive.namelist()
            assert not any("/media/" in name for name in names), names
            assert not any("drawing" in name.lower() for name in names), names
            xml = "".join(
                archive.read(name).decode("utf-8", "ignore")
                for name in names
                if name.endswith(".xml")
            )
        assert "#VALUE!" not in xml
        assert "Obrázek" not in xml

    parser_text = (
        source / "offers_engine" / "Gerotop_Parser.py"
    ).read_text(encoding="utf-8")
    router_text = (
        source / "offers_engine" / "Nabidky_Router.py"
    ).read_text(encoding="utf-8")
    assert "page.get_text('words')" in parser_text
    anchor_block = parser_text.split("def _row_anchors", 1)[1].split(
        "def _modern_anchors", 1
    )[0]
    assert "page.get_text('blocks')" not in anchor_block
    assert "_extract_row_image" not in parser_text
    assert "insert_image" not in parser_text
    assert "embed_image" not in parser_text
    assert "def _strip_images" in router_text
    assert "return _strip_images(data)" in router_text

    print(
        "TURTO CRM 7.6.6 GEROtop word-anchor / no-image validation passed"
    )


if __name__ == "__main__":
    main()
