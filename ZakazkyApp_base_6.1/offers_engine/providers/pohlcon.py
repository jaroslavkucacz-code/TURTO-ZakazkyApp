# PohlCon Czech price-offer provider for TURTO CRM.
#
# The provider is intentionally self-contained: Nabidky_Router discovers it
# automatically from offers_engine/providers. It parses the first offer page;
# pages 2+ are PohlCon validity/terms and do not contain offer items.
import os
import re

import fitz

SUPPLIER = 'PohlCon Česká republika s.r.o.'

MONEY_RE = re.compile(r'^-?\d[\d .]*,\d{2}$')
QTY_RE = re.compile(r'^\d+(?:[.,]\d+)?$')
OFFER_RE = re.compile(r'^\d{3,6}/20\d{2}$')
DATE_RE = re.compile(r'^\d{1,2}\.\d{1,2}\.20\d{2}$')


def _clean(value):
    return ' '.join(str(value or '').replace('\xa0', ' ').split())


def _cz_num(value):
    return float(
        _clean(value)
        .replace(' ', '')
        .replace('.', '')
        .replace(',', '.')
    )


def _first_page_lines(pdf_path):
    with fitz.open(pdf_path) as doc:
        if not doc.page_count:
            return []
        return [
            _clean(line)
            for line in doc[0].get_text('text').splitlines()
            if _clean(line)
        ]


def detect(path):
    try:
        joined = '\n'.join(_first_page_lines(path)).casefold()
        return (
            'cenová nabídka' in joined
            and 'pohlcon česká republika s.r.o.' in joined
            and ('číslo nabídky' in joined or '25693221' in joined)
        )
    except Exception:
        return False


def _header(lines):
    offer_no = ''
    offer_date = ''

    try:
        idx = next(
            i for i, line in enumerate(lines)
            if line.casefold() == 'číslo nabídky'
        )
    except StopIteration:
        idx = -1

    # Restrict the first pass to the header: later pages/text contain validity
    # dates and dates of supplied documents which are not the offer date.
    search = lines[idx + 1:idx + 12] if idx >= 0 else lines[:80]
    for line in search:
        if not offer_no and OFFER_RE.fullmatch(line):
            offer_no = line
        if not offer_date and DATE_RE.fullmatch(line):
            offer_date = line

    if not offer_no:
        offer_no = next(
            (line for line in lines if OFFER_RE.fullmatch(line)),
            '',
        )
    if not offer_date:
        offer_date = next(
            (line for line in lines if DATE_RE.fullmatch(line)),
            '',
        )

    reference = ''
    for line in lines:
        match = re.search(
            r'Cenová nabídka pro akci\s*[„"“]?\s*(.*?)\s*[“"”]?\s*$',
            line,
            re.I,
        )
        if match:
            reference = match.group(1).strip(' „“"”')
            break

    return offer_no, offer_date, reference


def _product_code(description):
    text = _clean(description)

    # PohlCon writes JDA products as e.g.
    # "Jordahl JDA 3 - 14 - 235 mm - 510 mm (...)". Normalize the visible
    # product code to the form commonly used in TURTO enquiries.
    match = re.search(
        r'\bJDA\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*mm\s*-\s*(\d+)\s*mm\b',
        text,
        re.I,
    )
    if match:
        return (
            f'JDA-{match.group(1)}/{match.group(2)}/'
            f'{match.group(3)}-{match.group(4)}'
        )

    # Other PohlCon product families (e.g. H-BAU) often already use a concise
    # technical designation, which is useful directly as a code in CRM.
    return text if len(text) <= 55 else ''


def _items(lines):
    header_idx = next(
        (
            i for i, line in enumerate(lines)
            if line.casefold() == 'celkem [kč]'
            or 'celkem [kč]' in line.casefold()
        ),
        -1,
    )
    if header_idx < 0:
        raise ValueError(
            'V nabídce PohlCon nebyla nalezena tabulka položek.'
        )

    items = []
    i = header_idx + 1
    while i < len(lines):
        if lines[i].casefold().startswith('celkem:'):
            break
        if not re.fullmatch(r'\d{1,4}', lines[i]):
            i += 1
            continue

        position = int(lines[i])
        if i + 3 >= len(lines):
            break

        qty_line = lines[i + 1]
        if not QTY_RE.fullmatch(qty_line):
            i += 1
            continue
        quantity = _cz_num(qty_line)
        if quantity.is_integer():
            quantity = int(quantity)

        unit = lines[i + 2]
        j = i + 3
        description_parts = []
        while j < len(lines) and not MONEY_RE.fullmatch(lines[j]):
            if lines[j].casefold().startswith('celkem:'):
                break
            if (
                description_parts
                and re.fullmatch(r'\d{1,4}', lines[j])
                and j + 1 < len(lines)
                and QTY_RE.fullmatch(lines[j + 1])
            ):
                break
            description_parts.append(lines[j])
            j += 1

        if (
            not description_parts
            or j >= len(lines)
            or not MONEY_RE.fullmatch(lines[j])
        ):
            i += 1
            continue

        unit_price = _cz_num(lines[j])
        if (
            j + 1 >= len(lines)
            or not MONEY_RE.fullmatch(lines[j + 1])
        ):
            i += 1
            continue
        item_total = _cz_num(lines[j + 1])

        description = _clean(' '.join(description_parts))
        items.append({
            'position': position,
            'product': _product_code(description),
            'description': description,
            'item_key': description,
            'details': '',
            'quantity': quantity,
            'unit': unit.upper(),
            'original_unit_price': unit_price,
            'discount_pct': 0.0,
            'unit_price': unit_price,
            'item_total': item_total,
            'image_bytes': None,
            'image_ext': None,
        })
        i = j + 2

    if not items:
        raise ValueError(
            'V nabídce PohlCon nebyly nalezeny žádné položky.'
        )
    return items


def _summary_total(lines):
    for i, line in enumerate(lines):
        if line.casefold().startswith('celkem:'):
            for candidate in lines[i + 1:i + 4]:
                if MONEY_RE.fullmatch(candidate):
                    return _cz_num(candidate)
    return None


def parse(pdf_path):
    lines = _first_page_lines(pdf_path)
    joined = '\n'.join(lines).casefold()
    if (
        'pohlcon česká republika s.r.o.' not in joined
        or 'cenová nabídka' not in joined
    ):
        raise ValueError(
            'PDF není rozpoznáno jako cenová nabídka PohlCon.'
        )

    offer_no, offer_date, reference = _header(lines)
    if not offer_no:
        raise ValueError(
            'V nabídce PohlCon se nepodařilo najít číslo nabídky.'
        )
    if not offer_date:
        raise ValueError(
            'V nabídce PohlCon se nepodařilo najít datum nabídky.'
        )

    items = _items(lines)
    total = _summary_total(lines)
    calculated = sum(
        float(item['item_total'] or 0)
        for item in items
    )
    if total is None:
        total = calculated

    # Fail rather than silently importing shifted columns from an unknown
    # future layout. Tolerance covers ordinary haler rounding.
    if (
        total
        and calculated
        and abs(total - calculated) > max(0.10, total * 0.002)
    ):
        raise ValueError(
            'Součet položek PohlCon '
            f'({calculated:.2f}) neodpovídá celku nabídky '
            f'({total:.2f}).'
        )

    return {
        'supplier': SUPPLIER,
        'offer_no': offer_no,
        'date': offer_date,
        'reference': reference,
        'gross': total,
        'discount_pct': 0.0,
        'discount_value': 0.0,
        'net': total,
        'vat': None,
        'total': total,
        'source_pdf': os.path.basename(str(pdf_path)),
        'source_type': 'PDF',
        'items': items,
    }


def export_excel(data, output_path, price_alerts=None):
    # Optional router-level export for standalone use. CRM itself keeps using
    # its canonical v624 exporter for all suppliers.
    import xlsxwriter

    workbook = xlsxwriter.Workbook(output_path)
    try:
        sheet = workbook.add_worksheet('Nabídka')
        title = workbook.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'font_size': 16,
        })
        label = workbook.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'border': 1,
        })
        cell = workbook.add_format({
            'font_name': 'Calibri',
            'border': 1,
        })
        money = workbook.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0.00 "Kč"',
        })
        header = workbook.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'border': 1,
            'align': 'center',
        })

        sheet.write('A1', f'Cenová nabídka {data.get("offer_no", "")}', title)
        meta = (
            ('Dodavatel', data.get('supplier') or SUPPLIER),
            ('Datum', data.get('date') or ''),
            ('Reference', data.get('reference') or ''),
            ('Celkem bez DPH', float(data.get('net') or 0)),
        )
        for row, (name, value) in enumerate(meta, 2):
            sheet.write(row - 1, 0, name, label)
            sheet.write(
                row - 1,
                1,
                value,
                money if name == 'Celkem bez DPH' else cell,
            )

        headers = (
            'Poz.', 'Kód', 'Název', 'Množství', 'MJ',
            'Cena/ks', 'Celkem',
        )
        start = 7
        for col, text in enumerate(headers):
            sheet.write(start, col, text, header)

        for offset, item in enumerate(data.get('items') or [], 1):
            row = start + offset
            values = (
                item.get('position') or offset,
                item.get('product') or '',
                item.get('description') or '',
                float(item.get('quantity') or 0),
                item.get('unit') or '',
                float(item.get('unit_price') or 0),
                float(item.get('item_total') or 0),
            )
            for col, value in enumerate(values):
                sheet.write(
                    row,
                    col,
                    value,
                    money if col in (5, 6) else cell,
                )

        sheet.set_column('A:A', 7)
        sheet.set_column('B:B', 22)
        sheet.set_column('C:C', 48)
        sheet.set_column('D:D', 12)
        sheet.set_column('E:E', 9)
        sheet.set_column('F:G', 16)
        sheet.freeze_panes(start + 1, 0)
    finally:
        workbook.close()
    return output_path
