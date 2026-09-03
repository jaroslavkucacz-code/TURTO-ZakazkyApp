# Canonical GEROtop PDF parser entry point.
#
# Newer GEROtop / PROSTUPY offers use geometry-driven rows and product codes
# such as 411-0150-030-XXX. Legacy PDFs keep using the proven original parser.
# The router registers only this module, so there is one GEROtop mechanism.
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
    rows = []
    for block in page.get_text('blocks'):
        code = clean_text(block[4])
        if PRODUCT_CODE_RE.fullmatch(code):
            rows.append((code, (block[1] + block[3]) / 2))
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
    # Keep the broad, proven GEROtop/PROSTUPY detector for both generations.
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
    for block in page.get_text('dict').get('blocks', []):
        if 'lines' not in block:
            continue

        bbox = block.get('bbox', (0, 0, 0, 0))
        center_y = (bbox[1] + bbox[3]) / 2
        if not (top <= center_y < bottom):
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
    """
    Read the numeric columns by geometry instead of PDF text-stream order.

    Current GEROtop sheets place the right-side columns at stable relative
    positions on the page:
      quantity | original price | discount | discounted price | row total
    """
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


def _extract_row_image(doc, page, top, bottom):
    candidates = []
    for image in page.get_images(full=True):
        try:
            rects = page.get_image_rects(image[0])
        except Exception:
            continue
        for rect in rects:
            center_y = (rect.y0 + rect.y1) / 2
            if not (top <= center_y < bottom):
                continue
            if rect.width < 18 or rect.height < 18:
                continue
            if rect.x0 < page.rect.width * 0.42 or rect.x1 > page.rect.width * 0.72:
                continue
            candidates.append((rect.width * rect.height, rect))
    if not candidates:
        return None, None
    _area, rect = max(candidates, key=lambda item: item[0])
    try:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
        return pixmap.tobytes('png'), 'png'
    except Exception:
        return None, None


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

                image_bytes, image_ext = _extract_row_image(
                    doc,
                    page,
                    top,
                    bottom,
                )

                items.append(
                    {
                        'position': position,
                        'product': code,
                        'description': title,
                        # Repeated placeholder product codes are allowed;
                        # the descriptive item key remains unique/stable.
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
                        'image_bytes': image_bytes,
                        'image_ext': image_ext,
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

        return {
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
    finally:
        doc.close()


def parse_offer(pdf_path):
    if _is_modern_pdf(pdf_path):
        return _parse_modern(pdf_path)
    return legacy.parse_offer(pdf_path)


# Keep the proven workbook layout but avoid Excel Place-in-Cell images,
# which can appear as #VALUE! in clients that do not support the feature.
def export_excel(data, output_path, price_alerts=None):
    try:
        from xlsxwriter.worksheet import Worksheet
        from PIL import Image
    except Exception:
        return legacy.export_excel(data, output_path, price_alerts=price_alerts)
    original_embed = getattr(Worksheet, 'embed_image', None)
    if not callable(original_embed):
        return legacy.export_excel(data, output_path, price_alerts=price_alerts)
    def compatible_embed(sheet, row, col, filename, options=None):
        opts = dict(options or {})
        image_data = opts.get('image_data')
        scale = 1.0
        if image_data is not None:
            try:
                image_data.seek(0)
                with Image.open(image_data) as image:
                    width, height = image.size
                image_data.seek(0)
                if width and height:
                    scale = min(220.0 / width, 120.0 / height, 1.0)
            except Exception:
                pass
        opts.update({'object_position': 1, 'x_scale': scale, 'y_scale': scale, 'x_offset': 4, 'y_offset': 4})
        return sheet.insert_image(row, col, filename, opts)
    Worksheet.embed_image = compatible_embed
    try:
        return legacy.export_excel(data, output_path, price_alerts=price_alerts)
    finally:
        Worksheet.embed_image = original_embed
