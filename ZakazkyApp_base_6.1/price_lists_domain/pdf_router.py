"""PDF Ceník router with automatic local OCR fallback."""
from __future__ import annotations
from pathlib import Path
from .ocr import _ocr_pdf,_read_pdf_text,_text_is_insufficient
from .pdf_fert import _parse_fert_ocr
from .pdf_mivo import _parse_mivo
from .pdf_offer import _parse_offer_engine
from .pdf_pohlcon import _parse_pohlcon

def parse_pdf_price_list(path: Path, progress=None) -> dict:
    text, pages = _read_pdf_text(path)
    ocr_engine = ""
    if _text_is_insufficient(text):
        text, pages, ocr_engine = _ocr_pdf(path, progress)
    parsed = (_parse_pohlcon(text) or _parse_mivo(text, pages) or
              _parse_fert_ocr(text, pages) or _parse_offer_engine(path))
    if parsed is None:
        parsed = {
            "supplier": "", "title": path.stem, "valid_from": "", "valid_to": "",
            "product_group": "", "branch": "", "currency": "CZK", "items": [],
            "terms_text": text[-4000:], "parse_status": "Bez rozpoznaných položek",
            "source_type": "PDF/OCR" if ocr_engine else "PDF",
        }
    parsed["raw_text"] = text
    parsed["ocr_text"] = text if ocr_engine else ""
    if ocr_engine:
        import json
        parsed["ocr_layout_json"] = json.dumps(pages, ensure_ascii=False, separators=(",", ":"))
    else:
        parsed["ocr_layout_json"] = ""
    parsed["ocr_engine"] = ocr_engine
    return parsed
