#!/usr/bin/env python3
import pathlib, sys

def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(source / "offers_engine"))
    import Gerotop_Parser as parser
    for code in ("202-100-300", "286-250-000", "411-0400-030-355", "411-0100-030-044,5"):
        assert parser.PRODUCT_CODE_RE.fullmatch(code), code
    class Page:
        def get_text(self, kind):
            return [(0,80,10,90,"202-100-300",0,0),(0,120,10,130,"411-0100-030-044,5",0,0),(0,170,10,180,"202-100-300",0,0)]
    assert [x[0] for x in parser._row_anchors(Page())] == ["202-100-300", "411-0100-030-044,5", "202-100-300"]
    text = (source / "offers_engine" / "Gerotop_Parser.py").read_text(encoding="utf-8")
    assert "page.get_pixmap" in text
    assert "sheet.insert_image" in text
    assert "and not LEGACY_CODE_RE.fullmatch" not in text
    print("TURTO CRM 7.6.4 GEROtop geometry validation passed")

if __name__ == "__main__": main()
