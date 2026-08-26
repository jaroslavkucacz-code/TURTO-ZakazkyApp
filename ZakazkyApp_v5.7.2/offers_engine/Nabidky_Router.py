from pathlib import Path
from importlib.machinery import SourceFileLoader

BASE = Path(__file__).resolve().parent
leviat = SourceFileLoader('Leviat_Nabidky_router', str(BASE/'Leviat_Nabidky.pyw')).load_module()
import Gerotop_Nabidky as gerotop


def detect_supplier(pdf_path):
    if gerotop.detect_pdf(pdf_path):
        return 'GEROtop'
    try:
        data = leviat.parse_offer(str(pdf_path))
        if data and data.get('offer_no'):
            return 'Leviat'
    except Exception:
        pass
    return None


def parse_offer(pdf_path):
    supplier = detect_supplier(pdf_path)
    if supplier == 'GEROtop':
        return gerotop.parse_offer(pdf_path)
    if supplier == 'Leviat':
        data = leviat.parse_offer(pdf_path)
        data['supplier'] = 'Leviat'
        data['source_type'] = 'PDF'
        for item in data.get('items',[]):
            item.setdefault('item_key', item.get('description',''))
            item.setdefault('details','')
            item.setdefault('image_bytes',None)
            item.setdefault('image_ext',None)
        return data
    raise ValueError('PDF není rozpoznáno jako podporovaná cenová nabídka.')


def export_excel(data, output_path, price_alerts=None):
    if data.get('supplier') == 'GEROtop':
        return gerotop.export_excel(data, output_path, price_alerts=price_alerts)
    return leviat.export_excel(data, output_path, price_alerts=price_alerts)


def process_file(pdf_path, output_path=None, price_alerts=None):
    data = parse_offer(pdf_path)
    if output_path is None:
        output_path = str(Path(pdf_path).with_name(f'Extrakce dat CN {data["offer_no"]}.xlsx'))
    export_excel(data, output_path, price_alerts=price_alerts)
    return data, output_path
