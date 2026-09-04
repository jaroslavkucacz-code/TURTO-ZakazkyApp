# TURTO CRM 7.6.7 - reprocess an already imported offer with the current parser.
from __future__ import annotations

import hashlib
from pathlib import Path


def apply(M):
    if getattr(M, '_turto_v767_offer_reprocess_images', False):
        return
    M._turto_v767_offer_reprocess_images = True

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

        Source hash still prevents duplicate offer records. The important
        difference is that a matching hash no longer returns immediately with
        stale supplier_offer_items: the PDF is parsed by the current parser and
        its extracted rows are transactionally replaced under the same offer ID.
        Offer/customer/action links and user-entered offer metadata stay intact.
        """
        parsed, raw = M.extract_offer_pdf(pdf_path)
        source_bytes = Path(pdf_path).read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()

        with M.db() as con:
            existing = con.execute(
                'SELECT * FROM supplier_offers WHERE source_hash=?',
                (source_hash,),
            ).fetchone()

        if existing is None:
            # New source: keep the proven original creation path. It will parse
            # once more, which is preferable to duplicating all new-offer logic.
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
            # Never destroy a previously usable offer because a newer parser
            # unexpectedly returned an empty result.
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

        # One transaction: either every freshly parsed row replaces the stale
        # extraction, or SQLite rolls the whole refresh back on any error.
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
                image = item.get('image_bytes')
                ext = str(item.get('image_ext') or '')

                con.execute(
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
                con.execute(
                    'INSERT OR IGNORE INTO offer_item_aliases(item_key,alias) VALUES(?,?)',
                    (key, original),
                )
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
        parsed['images_preserved'] = any(
            bool(item.get('image_bytes')) for item in items
        )
        return oid, False, len(items), parsed

    M.save_offer_import = save_offer_import
