#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import pathlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

from PIL import Image


def png_bytes():
    bio = io.BytesIO()
    Image.new('RGB', (24, 18), (240, 220, 140)).save(bio, format='PNG')
    return bio.getvalue()


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else 'ZakazkyApp_base_6.1'
    ).resolve()
    module_path = source / 'v767_offer_reprocess_images.py'
    spec = importlib.util.spec_from_file_location('v767_offer_reprocess_images_test', module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        db_path = td / 'test.db'
        pdf_path = td / 'offer.pdf'
        pdf_path.write_bytes(b'same-pdf-source-for-reprocess')
        source_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

        con = sqlite3.connect(db_path)
        con.executescript(
            '''
            CREATE TABLE supplier_offers(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              offer_date TEXT DEFAULT '', supplier_company_id INTEGER,
              customer_company_id INTEGER, action_id INTEGER,
              offer_number TEXT DEFAULT '', source_pdf TEXT DEFAULT '',
              source_hash TEXT NOT NULL UNIQUE, raw_text TEXT DEFAULT '',
              note TEXT DEFAULT '', updated_by TEXT DEFAULT '',
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
              supplier_name TEXT DEFAULT '', source_type TEXT DEFAULT 'PDF',
              reference TEXT DEFAULT '', gross_value REAL DEFAULT 0,
              discount_pct REAL DEFAULT 0, net_value REAL DEFAULT 0,
              total_value REAL DEFAULT 0
            );
            CREATE TABLE supplier_offer_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              offer_id INTEGER NOT NULL, position INTEGER DEFAULT 0,
              original_name TEXT DEFAULT '', item_key TEXT DEFAULT '',
              quantity REAL DEFAULT 0, unit TEXT DEFAULT '',
              unit_price REAL DEFAULT 0, discount REAL DEFAULT 0,
              net_price REAL DEFAULT 0, total_price REAL DEFAULT 0,
              image_path TEXT DEFAULT '', image_source_offer_date TEXT DEFAULT '',
              image_blob BLOB, image_ext TEXT DEFAULT '',
              product_code TEXT DEFAULT '', details TEXT DEFAULT '',
              original_unit_price REAL DEFAULT 0, discount_pct REAL DEFAULT 0
            );
            CREATE TABLE offer_item_aliases(
              item_key TEXT NOT NULL, alias TEXT NOT NULL,
              PRIMARY KEY(item_key, alias)
            );
            -- Exact legacy schema that caused 7.6.11 imports to fail:
            -- current SQL writes updated_at, but an existing older table did not
            -- receive that column from CREATE TABLE IF NOT EXISTS.
            CREATE TABLE offer_product_images(
              supplier TEXT NOT NULL, item_key TEXT NOT NULL,
              image_blob BLOB NOT NULL, image_ext TEXT DEFAULT '',
              source_offer_no TEXT DEFAULT '', source_offer_date TEXT DEFAULT '',
              image_hash TEXT DEFAULT '',
              PRIMARY KEY(supplier,item_key)
            );
            INSERT INTO offer_product_images(
              supplier,item_key,image_blob,image_ext,source_offer_no,
              source_offer_date,image_hash
            ) VALUES('LEGACY','legacy-key',X'00','png','OLD','2026-01-01','oldhash');
            '''
        )
        cur = con.execute(
            '''INSERT INTO supplier_offers(
                 offer_date,supplier_company_id,customer_company_id,action_id,
                 offer_number,source_pdf,source_hash,raw_text,note,updated_by,
                 supplier_name,source_type,reference,gross_value,discount_pct,
                 net_value,total_value)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                '2026-09-01', 11, 22, 33, 'P12196', 'old-path.pdf', source_hash,
                'old raw', 'RUČNÍ POZNÁMKA', 'Jaroslav', 'GEROtop', 'PDF',
                'RUČNĚ NAVÁZANÁ AKCE', 50, 25, 37.5, 37.5,
            ),
        )
        offer_id = cur.lastrowid
        con.execute(
            '''INSERT INTO supplier_offer_items(
                 offer_id,position,original_name,item_key,quantity,unit,
                 unit_price,total_price,product_code)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (offer_id, 10, 'STARÁ CHYBNÁ POLOŽKA', 'STARÁ CHYBNÁ POLOŽKA', 1, 'KS', 1, 1, '411-OLD'),
        )
        con.commit()
        con.close()

        image = png_bytes()
        parsed = {
            'supplier': 'GEROtop',
            'offer_no': 'P12196',
            'date': '03.09.2026',
            'reference': 'NOVÁ PARSOVANÁ REFERENCE',
            'source_type': 'PDF',
            'gross': 400.0,
            'discount_pct': 25.0,
            'net': 300.0,
            'items': [
                {
                    'position': 10,
                    'product': '202-100-300',
                    'description': 'Pažnice Typ A 100/300',
                    'details': 'detail A',
                    'quantity': 2,
                    'unit': 'KS',
                    'original_unit_price': 100.0,
                    'discount_pct': 25.0,
                    'unit_price': 75.0,
                    'item_total': 150.0,
                    'image_bytes': image,
                    'image_ext': 'png',
                },
                {
                    'position': 20,
                    'product': '286-250-000',
                    'description': 'Těsnicí vložka 250',
                    'details': 'detail B',
                    'quantity': 1,
                    'unit': 'KS',
                    'original_unit_price': 200.0,
                    'discount_pct': 25.0,
                    'unit_price': 150.0,
                    'item_total': 150.0,
                    'image_bytes': image,
                    'image_ext': 'png',
                },
            ],
        }

        calls = {'old_save': 0, 'ensure_schema': 0}

        def db():
            c = sqlite3.connect(db_path)
            c.row_factory = sqlite3.Row
            return c

        def ensure_schema():
            calls['ensure_schema'] += 1

        def extract_offer_pdf(_path):
            return parsed, 'fresh raw text'

        def stable_key(_con, _supplier, name, _date):
            return name

        def save_image(c, supplier, item_key, image_bytes, image_ext, offer_no, offer_date):
            if not image_bytes:
                return
            ih = hashlib.sha1(bytes(image_bytes)).hexdigest()
            # This intentionally mirrors the current production statement that
            # failed with "no such column: updated_at" on the legacy table.
            c.execute(
                '''INSERT INTO offer_product_images(
                     supplier,item_key,image_blob,image_ext,source_offer_no,
                     source_offer_date,image_hash,updated_at)
                   VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(supplier,item_key) DO UPDATE SET
                     image_blob=excluded.image_blob,image_ext=excluded.image_ext,
                     source_offer_no=excluded.source_offer_no,
                     source_offer_date=excluded.source_offer_date,
                     image_hash=excluded.image_hash,updated_at=CURRENT_TIMESTAMP''',
                (supplier, item_key, sqlite3.Binary(image_bytes), image_ext, offer_no, offer_date, ih),
            )

        def old_save(*args, **kwargs):
            calls['old_save'] += 1
            return 999, True, 0, {}

        M = SimpleNamespace(
            ensure_schema=ensure_schema,
            save_offer_import=old_save,
            extract_offer_pdf=extract_offer_pdf,
            db=db,
            _offer_date_iso=lambda value: '2026-09-03' if value else '',
            _stable_offer_key=stable_key,
            _save_canonical_image=save_image,
            get_setting=lambda key, default='': 'Jaroslav' if key == 'active_user' else default,
            sqlite3=sqlite3,
        )

        mod.apply(M)
        M.ensure_schema()

        with db() as c:
            image_cols = {
                row[1] for row in c.execute('PRAGMA table_info(offer_product_images)')
            }
            legacy_stamp = c.execute(
                "SELECT updated_at FROM offer_product_images WHERE supplier='LEGACY' AND item_key='legacy-key'"
            ).fetchone()[0]
        assert 'updated_at' in image_cols
        assert str(legacy_stamp or '').strip(), 'Legacy image rows must be backfilled.'
        assert calls['ensure_schema'] >= 1

        result = M.save_offer_import(pdf_path)
        assert result[0] == offer_id
        assert result[1] is False
        assert result[2] == 2
        assert result[3]['reprocessed_existing'] is True
        assert result[3]['images_preserved'] is True
        assert calls['old_save'] == 0, 'Duplicate source must be refreshed, not delegated.'

        with db() as c:
            offer = c.execute('SELECT * FROM supplier_offers WHERE id=?', (offer_id,)).fetchone()
            rows = c.execute(
                'SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',
                (offer_id,),
            ).fetchall()
            images = c.execute(
                "SELECT * FROM offer_product_images WHERE supplier='GEROtop' ORDER BY item_key"
            ).fetchall()

        assert len(rows) == 2
        assert [r['product_code'] for r in rows] == ['202-100-300', '286-250-000']
        assert all(r['image_blob'] for r in rows)
        assert all(r['image_ext'] == 'png' for r in rows)
        assert len(images) == 2
        assert all(str(r['updated_at'] or '').strip() for r in images)
        assert offer['action_id'] == 33
        assert offer['supplier_company_id'] == 11
        assert offer['customer_company_id'] == 22
        assert offer['note'] == 'RUČNÍ POZNÁMKA'
        assert offer['reference'] == 'RUČNĚ NAVÁZANÁ AKCE'
        assert offer['raw_text'] == 'fresh raw text'
        assert abs(float(offer['total_value']) - 300.0) < 1e-9

        # Different content must still use the original new-offer creation path.
        new_pdf = td / 'new.pdf'
        new_pdf.write_bytes(b'brand-new-source')
        M.save_offer_import(new_pdf)
        assert calls['old_save'] == 1

    launcher = (source / 'ZakazkyCRM.pyw').read_text(encoding='utf-8')
    layer = (source / 'v767_offer_reprocess_images.py').read_text(encoding='utf-8')
    assert 'v767_offer_reprocess_images.apply(app)' in launcher
    assert "DELETE FROM supplier_offer_items WHERE offer_id=?" in layer
    assert "source_hash=?" in layer
    assert "M._save_canonical_image" in layer
    assert "PRAGMA table_info(offer_product_images)" in layer
    assert "ADD COLUMN updated_at TEXT DEFAULT ''" in layer
    assert 'import v768_clean_table_markers' in layer
    assert 'v768_clean_table_markers.apply(M)' in layer
    assert 'import v769_nevoga_offer' in layer
    assert 'v769_nevoga_offer.apply(M)' in layer

    print(
        'TURTO CRM 7.6.12 legacy offer-image schema migration / '
        'reprocess / packaged Nevoga layer validation passed'
    )


if __name__ == '__main__':
    main()
