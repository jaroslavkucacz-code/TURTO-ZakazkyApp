# Canonical GEROtop PDF parser entry point.
#
# Current GEROtop / PROSTUPY offers are read by geometry. Product rows are
# anchored by code words in the left table column. Product images are
# intentionally ignored: received-offer extraction stores text and prices only.
import os
import re

import fitz

import Gerotop_Nabidky as legacy


LEGACY_CODE_RE = re.compile(r'^\d{3}-\d{3}-\d{3}$')
PRODUCT_CODE_RE = re.compile(
    r'^\d{3}-\d{3,4}-[A-Z0-9]{3}(?:-[A-Z0-9.,]{2,12})?$',
    re.I,
)
MODERN_CODE_RE = PRODUCT_CODE_RE


def clean_text(text):
    return ' '.join(
        str(text)
        .replace('\ufb01', 'fi')
        .replace('\ufb02', 'fl')
        .split()
    )


def strip_brand(text):
    return re.sub(
        r'^\s*GER[O0]\s*top\w*\s*[®]?\s*',
        '',
        str(text or ''),
        flags=re.I,
    ).strip()


def cz_num(text):
    return float(
        str(text)
        .strip()
        .replace(' ', '')
        .replace('.', '')
        .replace(',', '.')
    )


def _money(text):
    match = re.search(
        r'(-?\d[\d ]*(?:[,.]\d+)?)\s*Kč\b',
        str(text),
        re.I,
    )
    return cz_num(match.group(1)) if match else None


def _percent(text):
    match = re.search(r'(\d+(?:[,.]\d+)?)\s*%', str(text))
    return cz_num(match.group(1)) if match else None


def _row_anchors(page):
    """Return product-code anchors from the real left-hand code column.

    PyMuPDF does not guarantee that a visually separate code is a separate
    text *block*. Current GEROtop files do, however, expose every code as an
    individual word. Using words therefore keeps classic and extended codes
    together and preserves repeated product rows.
    """
    rows = []
    width = float(page.rect.width)
    seen = set()
    for word in page.get_text('words'):
        code = clean_text(word[4])
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        if center_x > width * 0.16:
            continue
        if not PRODUCT_CODE_RE.fullmatch(code):
            continue
        key = (code, round(center_y, 2))
        if key in seen:
            continue
        seen.add(key)
        rows.append((code, center_y))
    rows.sort(key=lambda item: item[1])
    return rows


def _modern_anchors(page):
    return _row_anchors(page)


def _is_modern_pdf(pdf_path):
    try:
        with fitz.open(pdf_path) as doc:
            text = '\n'.join(page.get_text('text') for page in doc[:2]).upper()
            return (
                'GEROTOP' in text
                and 'NABÍDK' in text
                and 'ČÍSLO NÁVRHU' in text
                and 'PRACOVNÍ NÁZEV AKCE' in text
                and 'JEDNOTKOVÁ' in text
                and 'CENA PO SLEVĚ' in text
                and any(_row_anchors(page) for page in doc[:2])
            )
    except Exception:
        return False


def detect_pdf(pdf_path):
    return legacy.detect_pdf(pdf_path)


def _header(joined):
    match = re.search(
        r'Nabídka číslo\s*([A-Z0-9-]+)',
        joined,
        re.I,
    )
    if match:
        offer_no = match.group(1)
    else:
        match = re.search(
            r'ČÍSLO NÁVRHU\s*/\s*NABÍDKY\s*'
            r'([A-Z0-9-]+)\s*/\s*(\d{4})',
            joined,
            re.I,
        )
        offer_no = (
            f'{match.group(1)}-{match.group(2)}'
            if match
            else None
        )

    match = re.search(
        r'(?:Datum vystavení|DATUM VYPRACOVÁNÍ)\s*'
        r'(\d{2}\.\d{2}\.\d{4})',
        joined,
        re.I,
    )
    offer_date = match.group(1) if match else ''

    match = re.search(
        r'PRACOVNÍ NÁZEV AKCE\s+([^\n]+)',
        joined,
        re.I,
    )
    reference = clean_text(match.group(1)) if match else ''
    reference = re.split(
        r'\s+KONTAKTNÍ OSOBA\s+',
        reference,
        flags=re.I,
    )[0].strip()

    return offer_no, offer_date, reference


def _description_block(page, top, bottom):
    candidates = []
    width = float(page.rect.width)
    for block in page.get_text('dict').get('blocks', []):
        if 'lines' not in block:
            continue

        bbox = block.get('bbox', (0, 0, 0, 0))
        center_y = (bbox[1] + bbox[3]) / 2
        if not (top <= center_y < bottom):
            continue

        # Ignore the left code and right numeric columns. This avoids a header
        # or a price block winning over the product description.
        if bbox[0] < width * 0.14 or bbox[0] > width * 0.68:
            continue

        text = clean_text(
            ' '.join(
                span.get('text', '')
                for line in block.get('lines', [])
                for span in line.get('spans', [])
            )
        )
        if not text:
            continue

        score = min(len(text), 500)
        if re.search(r'GER[O0]\s*top', text, re.I):
            score += 1000
        if '•' in text:
            score += 500
        if bbox[2] - bbox[0] > 120:
            score += 200
        candidates.append((score, block))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _title_and_description(page, top, bottom):
    block = _description_block(page, top, bottom)
    if not block:
        return '', [], []

    title = ''
    rich_segments = []
    bullets = []

    for line_index, line in enumerate(block.get('lines', [])):
        spans = []
        for span in line.get('spans', []):
            text = span.get('text', '')
            if not text:
                continue
            font = (span.get('font', '') or '').lower()
            flags = int(span.get('flags', 0) or 0)
            spans.append(
                (
                    text,
                    ('bold' in font) or bool(flags & 16),
                )
            )

        line_text = clean_text(''.join(text for text, _bold in spans))
        if not line_text:
            continue

        if line_index == 0:
            title = strip_brand(line_text)
            continue

        if rich_segments:
            rich_segments.append({'text': '\n', 'bold': False})
        for text, bold in spans:
            rich_segments.append({'text': text, 'bold': bold})

        plain = line_text.lstrip('•·- ').strip()
        if plain:
            bullets.append(plain)

    return title, rich_segments, bullets


def _row_values(page, row_y):
    """Read quantity and price columns from their visual X/Y positions."""
    width = float(page.rect.width)
    words = []
    for word in page.get_text('words'):
        center_y = (word[1] + word[3]) / 2
        if abs(center_y - row_y) <= 5.5 and word[0] >= width * 0.675:
            words.append(word)
    words.sort(key=lambda item: item[0])

    def column(start, end):
        return ' '.join(
            word[4]
            for word in words
            if start
            <= ((word[0] + word[2]) / 2) / width
            < end
        )

    quantity_text = column(0.675, 0.715)
    original_text = column(0.715, 0.780)
    discount_text = column(0.780, 0.825)
    unit_text = column(0.825, 0.890)
    total_text = column(0.890, 0.970)

    match = re.search(r'(\d+(?:[,.]\d+)?)', quantity_text)
    quantity = cz_num(match.group(1)) if match else None

    original = _money(original_text)
    discount = _percent(discount_text)
    unit_price = _money(unit_text)
    item_total = _money(total_text)

    if original is None and unit_price is not None and discount is not None:
        if discount < 100:
            original = unit_price / (1 - discount / 100)

    if discount is None and original and unit_price is not None:
        discount = (1 - unit_price / original) * 100

    if item_total is None and quantity is not None and unit_price is not None:
        item_total = quantity * unit_price

    return quantity, original, discount, unit_price, item_total


def _without_images(data):
    """Prevent images from entering exports, history or the CRM database."""
    if not data:
        return data
    data['images_disabled'] = True
    for item in data.get('items', []):
        item['image_bytes'] = None
        item['image_ext'] = None
    return data


def _parse_modern(pdf_path):
    doc = fitz.open(pdf_path)
    try:
        joined = '\n'.join(
            clean_text(line)
            for page in doc
            for line in page.get_text('text').splitlines()
            if clean_text(line)
        )

        offer_no, offer_date, reference = _header(joined)
        if not offer_no:
            raise ValueError('Nepodařilo se najít číslo nabídky GEROtop.')

        items = []
        position = 10

        for page in doc:
            anchors = _row_anchors(page)
            for index, (code, row_y) in enumerate(anchors):
                top = (
                    (anchors[index - 1][1] + row_y) / 2
                    if index > 0
                    else max(0, row_y - 40)
                )
                bottom = (
                    (row_y + anchors[index + 1][1]) / 2
                    if index + 1 < len(anchors)
                    else min(page.rect.height, row_y + 48)
                )

                title, rich_segments, bullets = _title_and_description(
                    page,
                    top,
                    bottom,
                )
                if not title or re.search(
                    r'Standardní doprava',
                    title,
                    re.I,
                ):
                    continue

                (
                    quantity,
                    original,
                    discount,
                    unit_price,
                    item_total,
                ) = _row_values(page, row_y)

                if quantity is None or unit_price is None:
                    continue

                if float(quantity).is_integer():
                    quantity = int(quantity)

                details = '\n'.join(
                    '• ' + bullet
                    for bullet in bullets
                )

                items.append(
                    {
                        'position': position,
                        'product': code,
                        'description': title,
                        'item_key': f'{position}:{code}:{title}',
                        'details': details,
                        'bullets': bullets,
                        'rich_segments': rich_segments,
                        'bold_terms': [],
                        'quantity': quantity,
                        'unit': 'KS',
                        'original_unit_price': original,
                        'discount_pct': discount or 0.0,
                        'unit_price': unit_price,
                        'item_total': item_total,
                        'image_bytes': None,
                        'image_ext': None,
                    }
                )
                position += 10

        if not items:
            raise ValueError(
                'V nové nabídce GEROtop nebyly nalezeny žádné produktové položky.'
            )

        gross = sum(
            float(
                (item['original_unit_price'] or item['unit_price'] or 0)
                * item['quantity']
            )
            for item in items
        )
        net = sum(
            float(item['item_total'] or 0)
            for item in items
        )

        return _without_images(
            {
                'supplier': 'GEROtop',
                'offer_no': offer_no,
                'date': offer_date,
                'reference': reference,
                'gross': gross,
                'discount_pct': (
                    (gross - net) / gross * 100
                    if gross
                    else 0
                ),
                'discount_value': net - gross,
                'net': net,
                'vat': None,
                'total': None,
                'source_pdf': os.path.basename(pdf_path),
                'source_type': 'PDF',
                'items': items,
            }
        )
    finally:
        doc.close()


def parse_offer(pdf_path):
    if _is_modern_pdf(pdf_path):
        return _parse_modern(pdf_path)
    return _without_images(legacy.parse_offer(pdf_path))


def export_excel(data, output_path, price_alerts=None):
    """Create a compact extraction workbook without any image column."""
    import xlsxwriter

    data = _without_images(data)
    workbook = xlsxwriter.Workbook(str(output_path))
    try:
        sheet = workbook.add_worksheet('Nabídka')
        sheet.hide_gridlines(2)

        title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_name': 'Calibri',
        })
        label_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Calibri',
        })
        value_fmt = workbook.add_format({'font_name': 'Calibri'})
        header_fmt = workbook.add_format({
            'bold': True,
            'font_name': 'Calibri',
            'bg_color': '#D9EAF7',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
        })
        text_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'text_wrap': True,
            'valign': 'top',
            'border': 1,
        })
        code_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'valign': 'top',
            'border': 1,
        })
        qty_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'num_format': '0.###',
            'align': 'right',
            'valign': 'top',
            'border': 1,
        })
        money_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'num_format': '#,##0.0 "Kč"',
            'align': 'right',
            'valign': 'top',
            'border': 1,
        })
        total_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'num_format': '#,##0 "Kč"',
            'align': 'right',
            'valign': 'top',
            'border': 1,
        })
        percent_fmt = workbook.add_format({
            'font_name': 'Calibri',
            'num_format': '0.0%',
            'align': 'right',
            'valign': 'top',
            'border': 1,
        })

        offer_no = data.get('offer_no') or ''
        sheet.merge_range('A1:G1', f'Cenová nabídka {offer_no}', title_fmt)
        metadata = [
            ('Dodavatel', data.get('supplier') or 'GEROtop'),
            ('Číslo nabídky', offer_no),
            ('Datum', data.get('date') or ''),
            ('Zakázka', data.get('reference') or ''),
            ('Celkem bez DPH – pouze výrobky', float(data.get('net') or 0)),
        ]
        for row, (label, value) in enumerate(metadata, start=1):
            sheet.write(row, 0, label, label_fmt)
            if row == 5:
                sheet.write_number(row, 1, float(value or 0), total_fmt)
            else:
                sheet.write(row, 1, value, value_fmt)

        header_row = 8
        headers = (
            'Kód',
            'Název / technický popis',
            'Počet',
            'MJ',
            'Cena/ks po slevě',
            'Sleva',
            'Původní cena/ks',
        )
        sheet.write_row(header_row, 0, headers, header_fmt)

        for offset, item in enumerate(data.get('items', []), start=1):
            row = header_row + offset
            name = item.get('description') or ''
            details = item.get('details') or ''
            combined = name if not details else f'{name}\n{details}'
            sheet.write(row, 0, item.get('product') or '', code_fmt)
            sheet.write(row, 1, combined, text_fmt)
            sheet.write_number(row, 2, float(item.get('quantity') or 0), qty_fmt)
            sheet.write(row, 3, item.get('unit') or '', code_fmt)
            sheet.write_number(row, 4, float(item.get('unit_price') or 0), money_fmt)
            sheet.write_number(
                row,
                5,
                float(item.get('discount_pct') or 0) / 100.0,
                percent_fmt,
            )
            sheet.write_number(
                row,
                6,
                float(item.get('original_unit_price') or 0),
                money_fmt,
            )
            lines = max(2, combined.count('\n') + 1)
            sheet.set_row(row, min(15 * lines, 105))

        sheet.set_column('A:A', 20)
        sheet.set_column('B:B', 78)
        sheet.set_column('C:C', 10)
        sheet.set_column('D:D', 8)
        sheet.set_column('E:E', 18)
        sheet.set_column('F:F', 11)
        sheet.set_column('G:G', 18)
        sheet.freeze_panes(header_row + 1, 0)
        if data.get('items'):
            last_row = header_row + len(data['items'])
            sheet.autofilter(header_row, 0, last_row, len(headers) - 1)
    finally:
        workbook.close()
