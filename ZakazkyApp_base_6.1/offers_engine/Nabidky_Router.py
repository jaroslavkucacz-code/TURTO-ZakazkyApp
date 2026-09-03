from pathlib import Path
from importlib.machinery import SourceFileLoader
import importlib.util

BASE = Path(__file__).resolve().parent
leviat = SourceFileLoader('Leviat_Nabidky_router', str(BASE/'Leviat_Nabidky.pyw')).load_module()
import Gerotop_Parser_767 as gerotop

# Built-in parsers migrated from the original TURTO offer-processing program.
# Future suppliers can be added as small provider modules in offers_engine/providers
# exposing: SUPPLIER, detect(path)->bool, parse(path)->dict, optional export_excel(...).
BUILTINS=[]
PROVIDERS=[]


class UnsupportedOfferPDF(ValueError):
    """No registered offer parser recognized this PDF.

    This is a normal condition for PDF attachments inside e-mails: technical
    sheets, drawings and certificates are still preserved, but are not offers.
    """

    benign_offer_attachment = True


def _register_builtin(name,detect,parse,export=None):
    BUILTINS.append({'supplier':name,'detect':detect,'parse':parse,'export':export})


def _leviat_detect(path):
    try:
        d=leviat.parse_offer(str(path));return bool(d and d.get('offer_no'))
    except Exception:return False


def _leviat_parse(path):
    data=leviat.parse_offer(str(path));data['supplier']='Leviat';data['source_type']='PDF'
    for item in data.get('items',[]):
        item.setdefault('item_key',item.get('description',''));item.setdefault('details','');item.setdefault('image_bytes',None);item.setdefault('image_ext',None)
    return data


_register_builtin('GEROtop',gerotop.detect_pdf,gerotop.parse_offer,gerotop.export_excel)
_register_builtin('Leviat',_leviat_detect,_leviat_parse,leviat.export_excel)


def _load_providers():
    if PROVIDERS:return
    folder=BASE/'providers'
    if not folder.exists():return
    for p in sorted(folder.glob('*.py')):
        if p.name.startswith('_'):continue
        try:
            name=f'_turto_offer_provider_{p.stem}'
            spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            if getattr(m,'SUPPLIER',None) and callable(getattr(m,'detect',None)) and callable(getattr(m,'parse',None)):
                PROVIDERS.append({'supplier':m.SUPPLIER,'detect':m.detect,'parse':m.parse,'export':getattr(m,'export_excel',None),'module':m})
        except Exception:
            pass


def parsers():
    _load_providers();return BUILTINS+PROVIDERS


def detect_supplier(pdf_path):
    for p in parsers():
        try:
            if p['detect'](pdf_path):return p['supplier']
        except Exception:pass
    return None


def parse_offer(pdf_path):
    matched_errors=[]
    for p in parsers():
        try:
            detected=bool(p['detect'](pdf_path))
        except Exception:
            detected=False
        if not detected:
            continue
        try:
            data=p['parse'](pdf_path)
            if data:
                data.setdefault('supplier',p['supplier']);data.setdefault('source_type','PDF')
                for item in data.get('items',[]):
                    item.setdefault('item_key',item.get('description',''));item.setdefault('details','');item.setdefault('image_bytes',None);item.setdefault('image_ext',None)
                return data
        except Exception as exc:
            matched_errors.append(f"{p['supplier']}: {exc}")
    if matched_errors:
        raise ValueError('PDF bylo rozpoznáno jako cenová nabídka, ale parser ji nedokázal načíst. ' + ' | '.join(matched_errors))
    raise UnsupportedOfferPDF('PDF není rozpoznáno jako podporovaná cenová nabídka.')


def export_excel(data, output_path, price_alerts=None):
    supplier=data.get('supplier')
    for p in parsers():
        if p['supplier']==supplier and p.get('export'):
            return p['export'](data,output_path,price_alerts=price_alerts)
    raise ValueError(f'Pro dodavatele {supplier or "?"} není definován Excel export.')


def process_file(pdf_path, output_path=None, price_alerts=None):
    data=parse_offer(pdf_path)
    if output_path is None:output_path=str(Path(pdf_path).with_name(f'Extrakce dat CN {data["offer_no"]}.xlsx'))
    export_excel(data,output_path,price_alerts=price_alerts);return data,output_path
