# TURTO CRM 7.6.7 - GEROtop word-anchor parser with product images restored.
#
# The 7.6.6 word-anchor logic remains authoritative for row detection. This
# wrapper restores product images and the original workbook layout, while
# converting XlsxWriter Place-in-Cell calls to classic inserted images so the
# workbook remains compatible with Excel versions that would show #VALUE!.
from __future__ import annotations

import os
import re

import fitz

import Gerotop_Nabidky as legacy
import Gerotop_Parser as base


PRODUCT_CODE_RE = base.PRODUCT_CODE_RE
MODERN_CODE_RE = base.MODERN_CODE_RE
LEGACY_CODE_RE = base.LEGACY_CODE_RE
clean_text = base.clean_text
strip_brand = base.strip_brand
cz_num = base.cz_num
_row_anchors = base._row_anchors
_modern_anchors = base._modern_anchors
_is_modern_pdf = base._is_modern_pdf
detect_pdf = base.detect_pdf


def _extract_row_image(page, top, bottom):
    """Extract the largest real product image inside one visual product row."""
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
            # Current GEROtop sheets place the product picture between the
            # description and the numeric price columns.
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

        offer_no, offer_date, reference = base._header(joined)
        if not offer_no:
            raise ValueError('Nepodařilo se najít číslo nabídky GEROtop.')

        items = []
        position = 10

        for page in doc:
            anchors = base._row_anchors(page)
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

                title, rich_segments, bullets = base._title_and_description(
                    page,
                    top,
                    bottom,
                )
                if not title or re.search(r'Standardní doprava', title, re.I):
                    continue

                (
                    quantity,
                    original,
                    discount,
                    unit_price,
                    item_total,
                ) = base._row_values(page, row_y)

                if quantity is None or unit_price is None:
                    continue
                if float(quantity).is_integer():
                    quantity = int(quantity)

                details = '\n'.join('• ' + bullet for bullet in bullets)
                image_bytes, image_ext = _extract_row_image(page, top, bottom)

                items.append(
                    {
                        'position': position,
                        'product': code,
                        'description': title,
                        # Repeated codes are legitimate. Position is kept in the
                        # parser item key while the CRM canonical name history is
                        # handled separately by save_offer_import.
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
        net = sum(float(item['item_total'] or 0) for item in items)

        return {
            'supplier': 'GEROtop',
            'offer_no': offer_no,
            'date': offer_date,
            'reference': reference,
            'gross': gross,
            'discount_pct': ((gross - net) / gross * 100 if gross else 0),
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
    if base._is_modern_pdf(pdf_path):
        return _parse_modern(pdf_path)
    # The proven legacy parser already carries product images where available.
    return legacy.parse_offer(pdf_path)


def export_excel(data, output_path, price_alerts=None):
    """Export with pictures as classic drawing objects, never Place-in-Cell."""
    try:
        from PIL import Image
        from xlsxwriter.worksheet import Worksheet
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
        opts.update(
            {
                'object_position': 1,
                'x_scale': scale,
                'y_scale': scale,
                'x_offset': 4,
                'y_offset': 4,
            }
        )
        return sheet.insert_image(row, col, filename, opts)

    Worksheet.embed_image = compatible_embed
    try:
        return legacy.export_excel(data, output_path, price_alerts=price_alerts)
    finally:
        Worksheet.embed_image = original_embed
