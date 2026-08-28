"""Public Ceník source router."""
from __future__ import annotations
import csv,json
from pathlib import Path
from .common import _number
from .excel import parse_excel_price_list
from .model import _base_item
from .pdf_router import parse_pdf_price_list

def parse_price_list_file(path: Path, progress=None) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf_price_list(path, progress)
    if suffix in {".xlsx", ".xlsm"}:
        return parse_excel_price_list(path, progress)
    if suffix == ".csv":
        # Convert a simple CSV into the same generic path by reading headers.
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,\t,")
            except Exception:
                dialect = csv.excel
            rows = list(csv.DictReader(handle, dialect=dialect))
        items = []
        for index, row in enumerate(rows, 1):
            if progress and index % 100 == 0:progress(index,len(rows),f"Zpracovávám řádek {index} z {len(rows)}")
            code = str(row.get("Kód") or row.get("Code") or row.get("Item-No.") or "").strip()
            name = str(row.get("Název") or row.get("Produkt") or row.get("Product") or row.get("Description") or "").strip()
            price = _number(row.get("Cena") or row.get("Price") or row.get("Net price per unit"))
            if code or name:
                items.append(_base_item(row_no=index, product_code=code, name=name,
                                        unit=str(row.get("MJ") or row.get("Unit") or ""),
                                        source_price=price, normalized_unit_price=price,
                                        source_row_json=json.dumps(row, ensure_ascii=False)))
        return {"supplier": "", "title": path.stem, "valid_from": "", "valid_to": "",
                "product_group": "", "branch": "", "currency": "CZK", "items": items,
                "terms_text": "", "raw_text": "", "ocr_text": "", "ocr_layout_json": "", "ocr_engine": "",
                "parse_status": "Rozpoznáno automaticky" if items else "Bez rozpoznaných položek",
                "source_type": "CSV"}
    raise ValueError("Nepodporovaný formát Ceníku: " + suffix)
