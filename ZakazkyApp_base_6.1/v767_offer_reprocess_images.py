# TURTO CRM 7.7.2 - reprocess offers and retain already available images.
from __future__ import annotations

import hashlib
import re
from pathlib import Path


_TYPE_RE = re.compile(r"(?:^|[|,;\s])(?:typ|type)\s*[:=\-]?\s*([A-Z]{1,3})(?=\s|[|,;]|$)", re.I)


def _get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def _norm(value):
    return ' '.join(re.sub(r'[^\w]+', ' ', str(value or '').casefold()).split())


def _type_code(*values):
    for value in values:
        match = _TYPE_RE.search(str(value or '').upper())
        if match:
            return match.group(1).upper()
    return ''


def _columns(con, table):
    try:
        return {str(row[1]) for row in con.execute(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def apply(M):
    if getattr(M, '_turto_v767_offer_reprocess_images', False):
        return
    M._turto_v767_offer_reprocess_images = True

    # Older user databases can already contain offer tables from releases where
    # updated_at did not exist. CREATE TABLE IF NOT EXISTS never upgrades an
    # existing table. The current duplicate/reprocess path writes updated_at to
    # supplier_offers, and canonical image persistence writes it to
    # offer_product_images, so both legacy tables must be migrated additively.
    previous_ensure_schema = getattr(M, 'ensure_schema', None)

    def _ensure_updated_at_column(con, table_name):
        table = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not table:
            return False
        columns = {
            str(row[1])
            for row in con.execute(f'PRAGMA table_info({table_name})').fetchall()
        }
        changed = False
        if 'updated_at' not in columns:
            # SQLite does not allow ALTER TABLE ADD COLUMN with a non-constant
            # CURRENT_TIMESTAMP default on all supported versions. Add a plain
            # text column first, then backfill legacy rows explicitly.
            con.execute(
                f"ALTER TABLE {table_name} ADD COLUMN updated_at TEXT DEFAULT ''"
            )
            changed = True
        con.execute(
            f"UPDATE {table_name} SET updated_at=CURRENT_TIMESTAMP "
            "WHERE trim(coalesce(updated_at,''))=''"
        )
        return changed

    def ensure_offer_import_schema():
        with M.db() as con:
            changed = []
            for table_name in ('supplier_offers', 'offer_product_images'):
                if _ensure_updated_at_column(con, table_name):
                    changed.append(table_name)
            return tuple(changed)

    # Compatibility name retained for any older runtime layer/tests that call it.
    def ensure_offer_product_images_schema():
        with M.db() as con:
            return _ensure_updated_at_column(con, 'offer_product_images')

    M.ensure_offer_import_schema = ensure_offer_import_schema
    M.ensure_offer_product_images_schema = ensure_offer_product_images_schema

    if callable(previous_ensure_schema):
        def ensure_schema():
            result = previous_ensure_schema()
            ensure_offer_import_schema()
            return result

        M.ensure_schema = ensure_schema

    previous_save = M.save_offer_import

    def save_offer_import(
        pdf_path,
        supplier_name='',
        customer_name='',
        action_name='',
        offer_date='',
        offer_number='',
        note='',
    ):
        """Import a new PDF or refresh extraction for an identical stored PDF.

        Source hash still prevents duplicate offer records. A matching hash is
        parsed by the current parser and its extracted rows are transactionally
        replaced under the same offer ID. If a repeated MSG/PDF pass omits image
        bytes, the previous item, canonical image or shared PLEXUS asset is reused.
        """
        ensure_offer_import_schema()

        parsed, raw = M.extract_offer_pdf(pdf_path)
        source_bytes = Path(pdf_path).read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()

        with M.db() as con:
            existing = con.execute(
                'SELECT * FROM supplier_offers WHERE source_hash=?',
                (source_hash,),
            ).fetchone()
            previous_rows = (
                con.execute(
                    'SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',
                    (int(existing['id']),),
                ).fetchall()
                if existing is not None
                else []
            )
            item_columns = _columns(con, 'supplier_offer_items')

        if existing is None:
            return previous_save(
                pdf_path,
                supplier_name=supplier_name,
                customer_name=customer_name,
                action_name=action_name,
                offer_date=offer_date,
                offer_number=offer_number,
                note=note,
            )

        items = list(parsed.get('items') or [])
        if not items:
            raise ValueError(
                'Opětovné zpracování nabídky nevrátilo žádné položky. '
                'Původní uložená data zůstala beze změny.'
            )

        oid = int(existing['id'])
        parsed_supplier = str(
            parsed.get('supplier')
            or existing['supplier_name']
            or supplier_name
            or ''
        ).strip()
        parsed_date = M._offer_date_iso(
            parsed.get('date') or existing['offer_date'] or offer_date
        )
        stored_date = str(existing['offer_date'] or parsed_date or '').strip()
        stored_number = str(
            existing['offer_number']
            or parsed.get('offer_no')
            or offer_number
            or ''
        ).strip()
        stored_supplier = str(
            existing['supplier_name'] or parsed_supplier or supplier_name or ''
        ).strip()
        parsed_reference = str(parsed.get('reference') or '').strip()
        source_type = str(
            parsed.get('source_type') or existing['source_type'] or 'PDF'
        ).strip()
        active_user = M.get_setting('active_user', '')

        gross = float(parsed.get('gross') or 0)
        discount_pct = float(parsed.get('discount_pct') or 0)
        net_value = float(parsed.get('net') or parsed.get('total') or 0)

        by_key = {str(_get(row, 'item_key') or '').casefold(): row for row in previous_rows if _get(row, 'item_key')}
        by_product = {str(_get(row, 'product_code') or '').casefold(): row for row in previous_rows if _get(row, 'product_code')}
        by_name = {_norm(_get(row, 'original_name')): row for row in previous_rows if _get(row, 'original_name')}
        by_position = {int(_get(row, 'position') or 0): row for row in previous_rows if int(_get(row, 'position') or 0)}
        by_type = {}
        for row in previous_rows:
            code = str(_get(row, 'plexus_type') or '').upper() or _type_code(
                _get(row, 'original_name'), _get(row, 'item_key'), _get(row, 'details')
            )
            if code:
                by_type.setdefault(code, row)

        def prior_row(item, key, pos):
            code = str(item.get('plexus_type') or '').upper() or _type_code(
                item.get('description'), item.get('item_key'), item.get('details')
            )
            return (
                (by_type.get(code) if code else None)
                or by_key.get(str(key or '').casefold())
                or by_product.get(str(item.get('product') or '').casefold())
                or by_name.get(_norm(item.get('description') or item.get('item_key')))
                or by_position.get(int(item.get('position') or pos))
            )

        def recover_image(con, item, key, pos):
            image = item.get('image_bytes')
            ext = str(item.get('image_ext') or '')
            code = str(item.get('plexus_type') or '').upper() or _type_code(
                item.get('description'), item.get('item_key'), item.get('details')
            )
            if image:
                return bytes(image), ext, '', code, False

            old = prior_row(item, key, pos)
            asset_key = str(_get(old, 'image_asset_key') or '') if old else ''
            code = code or (str(_get(old, 'plexus_type') or '').upper() if old else '')
            if old and _get(old, 'image_blob'):
                return bytes(old['image_blob']), str(_get(old, 'image_ext') or ext), asset_key, code, True

            if asset_key:
                try:
                    asset = con.execute(
                        'SELECT image_blob,image_ext FROM offer_image_assets WHERE asset_key=?',
                        (asset_key,),
                    ).fetchone()
                except Exception:
                    asset = None
                if asset and asset['image_blob']:
                    return bytes(asset['image_blob']), str(asset['image_ext'] or ext), asset_key, code, True

            try:
                canonical = con.execute(
                    '''SELECT image_blob,image_ext FROM offer_product_images
                       WHERE supplier=? AND item_key=? AND image_blob IS NOT NULL''',
                    (stored_supplier or parsed_supplier, key),
                ).fetchone()
            except Exception:
                canonical = None
            if canonical and canonical['image_blob']:
                return bytes(canonical['image_blob']), str(canonical['image_ext'] or ext), asset_key, code, True

            if code:
                key_by_type = f'nevoga:plexus:{code}'
                try:
                    asset = con.execute(
                        'SELECT image_blob,image_ext FROM offer_image_assets WHERE asset_key=?',
                        (key_by_type,),
                    ).fetchone()
                except Exception:
                    asset = None
                if asset and asset['image_blob']:
                    return bytes(asset['image_blob']), str(asset['image_ext'] or ext), key_by_type, code, True
            return None, ext, asset_key, code, False

        restored_images = 0
        stored_images = 0
        with M.db() as con:
            con.execute('DELETE FROM supplier_offer_items WHERE offer_id=?', (oid,))

            for pos, item in enumerate(items, 1):
                original = str(
                    item.get('description')
                    or item.get('item_key')
                    or item.get('product')
                    or ''
                ).strip()
                key = M._stable_offer_key(
                    con,
                    stored_supplier or parsed_supplier,
                    original,
                    stored_date,
                )
                qty = float(item.get('quantity') or 0)
                unit_price = float(item.get('unit_price') or 0)
                original_price = float(
                    item.get('original_unit_price') or unit_price or 0
                )
                disc = float(item.get('discount_pct') or 0)
                total = float(item.get('item_total') or (qty * unit_price))
                image, ext, asset_key, plexus_type, restored = recover_image(
                    con, item, key, pos
                )
                stored_images += int(bool(image))
                restored_images += int(bool(restored and image))

                cursor = con.execute(
                    '''INSERT INTO supplier_offer_items(
                        offer_id,position,original_name,item_key,quantity,unit,
                        unit_price,discount,net_price,total_price,
                        image_source_offer_date,image_blob,image_ext,product_code,
                        details,original_unit_price,discount_pct)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (
                        oid,
                        int(item.get('position') or pos),
                        original,
                        key,
                        qty,
                        str(item.get('unit') or ''),
                        unit_price,
                        disc,
                        unit_price,
                        total,
                        stored_date,
                        M.sqlite3.Binary(image) if image else None,
                        ext,
                        str(item.get('product') or ''),
                        str(item.get('details') or ''),
                        original_price,
                        disc,
                    ),
                )
                if asset_key and 'image_asset_key' in item_columns:
                    con.execute(
                        'UPDATE supplier_offer_items SET image_asset_key=? WHERE id=?',
                        (asset_key, int(cursor.lastrowid)),
                    )
                if plexus_type and 'plexus_type' in item_columns:
                    con.execute(
                        'UPDATE supplier_offer_items SET plexus_type=? WHERE id=?',
                        (plexus_type, int(cursor.lastrowid)),
                    )
                con.execute(
                    'INSERT OR IGNORE INTO offer_item_aliases(item_key,alias) VALUES(?,?)',
                    (key, original),
                )
                if image:
                    M._save_canonical_image(
                        con,
                        stored_supplier or parsed_supplier,
                        key,
                        image,
                        ext,
                        stored_number,
                        stored_date,
                    )

            item_total = con.execute(
                'SELECT COALESCE(SUM(total_price),0) FROM supplier_offer_items WHERE offer_id=?',
                (oid,),
            ).fetchone()[0]
            final_total = net_value if net_value > 0 else float(item_total or 0)

            con.execute(
                '''UPDATE supplier_offers SET
                       raw_text=?,
                       source_type=?,
                       reference=CASE WHEN trim(coalesce(reference,''))='' THEN ? ELSE reference END,
                       supplier_name=CASE WHEN trim(coalesce(supplier_name,''))='' THEN ? ELSE supplier_name END,
                       offer_number=CASE WHEN trim(coalesce(offer_number,''))='' THEN ? ELSE offer_number END,
                       offer_date=CASE WHEN trim(coalesce(offer_date,''))='' THEN ? ELSE offer_date END,
                       gross_value=?,discount_pct=?,net_value=?,total_value=?,
                       updated_by=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?''',
                (
                    raw,
                    source_type,
                    parsed_reference,
                    parsed_supplier,
                    stored_number,
                    parsed_date,
                    gross,
                    discount_pct,
                    net_value,
                    final_total,
                    active_user,
                    oid,
                ),
            )

        parsed['reprocessed_existing'] = True
        parsed['existing_offer_id'] = oid
        parsed['images_preserved'] = bool(stored_images)
        parsed['images_restored_from_previous'] = restored_images
        parsed['program_images_available'] = stored_images
        return oid, False, len(items), parsed

    M.save_offer_import = save_offer_import

    try:
        import v768_clean_table_markers
        v768_clean_table_markers.apply(M)
    except Exception:
        pass
