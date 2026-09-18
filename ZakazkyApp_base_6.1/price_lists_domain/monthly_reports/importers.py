from __future__ import annotations

import hashlib
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from .xlsx_reader import XlsxReader, excel_date

MONTHS_CZ = {
    'LEDEN': 1, 'ÚNOR': 2, 'BREZEN': 3, 'BŘEZEN': 3, 'DUBEN': 4,
    'KVĚTEN': 5, 'KVETEN': 5, 'ČERVEN': 6, 'CERVEN': 6,
    'ČERVENEC': 7, 'CERVENEC': 7, 'SRPEN': 8, 'ZÁŘÍ': 9, 'ZARI': 9,
    'ŘÍJEN': 10, 'RIJEN': 10, 'LISTOPAD': 11, 'PROSINEC': 12,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _register_import(con, import_type, path, file_hash, period_year=None, period_month=None, row_count=0, status='OK', notes=''):
    cur = con.execute(
        '''INSERT INTO imports(imported_at, import_type, file_name, file_hash, period_year, period_month, row_count, status, notes)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (datetime.now().isoformat(timespec='seconds'), import_type, path.name, file_hash, period_year, period_month, row_count, status, notes),
    )
    return cur.lastrowid


def _pad(row, n):
    return row + [None] * max(0, n - len(row))


def _archive(path: Path, archive_dir: Path | None):
    if not archive_dir:
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / path.name
    if target.exists():
        stem, suffix = path.stem, path.suffix
        target = archive_dir / f'{stem}_{datetime.now():%Y%m%d_%H%M%S}{suffix}'
    shutil.copy2(path, target)


def import_xlsx(db, file_path: str | Path, archive_dir: str | Path | None = None) -> dict:
    path = Path(file_path)
    archive = Path(archive_dir) if archive_dir else None
    digest = sha256_file(path)
    result = {'file': path.name, 'components': [], 'warnings': []}

    with XlsxReader(path) as reader:
        sheets = reader.sheet_names
        with db.connect() as con:
            # Full summary workbook / POHODA export.
            if 'DATA POHODA' in sheets:
                info = _import_delivery_notes(con, reader, path, digest)
                result['components'].append(info)
            elif _looks_like_delivery_export(reader):
                info = _import_delivery_notes(con, reader, path, digest, sheet_name=reader.sheet_names[0])
                result['components'].append(info)

            if 'zdroj režijní listy' in sheets:
                info = _import_overheads(con, reader, path, digest, 'zdroj režijní listy')
                result['components'].append(info)

            if 'ZISKY' in sheets:
                info = _import_legacy_summary(con, reader, path, digest)
                result['components'].append(info)

            if _looks_like_profit_report(reader):
                info = _import_profit_report(con, reader, path, digest)
                result['components'].append(info)

            if not result['components']:
                raise ValueError('Soubor nebyl rozpoznán jako podporovaný export POHODA / TURTO.')

    _archive(path, archive)
    return result


def _looks_like_delivery_export(reader: XlsxReader):
    try:
        rows = list(reader.rows(reader.sheet_names[0]))[:3]
    except Exception:
        return False
    for _, row in rows:
        vals = {str(x).strip().lower() for x in row if x is not None}
        if {'datum', 'číslo', 'firma', 'středisko'}.issubset(vals):
            return True
    return False


def _looks_like_profit_report(reader: XlsxReader):
    for _, row in list(reader.rows(reader.sheet_names[0]))[:6]:
        if any(isinstance(v, str) and 'Zisk (zásoby)' in v for v in row):
            return True
    return False


def _import_delivery_notes(con, reader, path, digest, sheet_name='DATA POHODA'):
    rows = reader.rows(sheet_name)
    header = None
    header_row = None
    data_rows = []
    for rn, row in rows:
        lowered = [str(v).strip().lower() if v is not None else '' for v in row]
        if 'datum' in lowered and 'číslo' in lowered and ('kč základní' in lowered or 'celkem' in lowered):
            header, header_row = row, rn
            continue
        if header is not None and rn > header_row:
            data_rows.append(row)
    if header is None:
        raise ValueError(f'V listu {sheet_name} nebyla nalezena hlavička dokladů.')

    index = {str(v).strip().lower(): i for i, v in enumerate(header) if v is not None}
    ix_date = index.get('datum')
    ix_no = index.get('číslo')
    ix_base = index.get('kč základní', index.get('celkem'))
    ix_total = index.get('celkem', ix_base)
    ix_customer = index.get('firma')
    ix_text = index.get('text')
    ix_center = index.get('středisko')
    ix_project = index.get('zakázka')
    ix_note = index.get('poznámka')

    parsed = []
    dates = []
    for row in data_rows:
        row = _pad(row, max(index.values()) + 1)
        doc = row[ix_no] if ix_no is not None else None
        dt = excel_date(row[ix_date]) if ix_date is not None else None
        if not doc or not dt:
            continue
        d = dt.date().isoformat()
        dates.append(dt.date())
        parsed.append((
            str(doc).strip(), d, float(row[ix_base] or 0), float(row[ix_total] or 0),
            str(row[ix_customer] or '').strip() if ix_customer is not None else '',
            str(row[ix_text] or '').strip() if ix_text is not None else '',
            str(row[ix_center] or '').strip().upper() if ix_center is not None else '',
            str(row[ix_project] or '').strip() if ix_project is not None else '',
            str(row[ix_note] or '').strip() if ix_note is not None else '',
        ))

    year = dates[-1].year if dates else None
    month = dates[-1].month if dates else None
    imp_id = _register_import(con, 'DATA_POHODA', path, digest, year, month, len(parsed), notes=f'List: {sheet_name}')
    con.executemany(
        '''INSERT INTO delivery_notes(doc_no,doc_date,base_amount,total_amount,customer,description,center,project,note,source_import_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(doc_no) DO UPDATE SET
             doc_date=excluded.doc_date, base_amount=excluded.base_amount, total_amount=excluded.total_amount,
             customer=excluded.customer, description=excluded.description, center=excluded.center,
             project=excluded.project, note=excluded.note, source_import_id=excluded.source_import_id''',
        [r + (imp_id,) for r in parsed]
    )
    return {'type': 'DATA POHODA', 'rows': len(parsed), 'period': f'{year:04d}-{month:02d}' if year and month else ''}


def _import_overheads(con, reader, path, digest, sheet_name):
    all_rows = list(reader.rows(sheet_name))
    if not all_rows:
        return {'type': 'REŽIJNÍ LISTY', 'rows': 0, 'period': ''}
    _, header = all_rows[0]
    idx = {str(v).strip().lower(): i for i, v in enumerate(header) if v is not None}
    parsed, dates = [], []
    for _, row in all_rows[1:]:
        row = _pad(row, max(idx.values()) + 1)
        no = row[idx.get('číslo', 0)]
        dt = excel_date(row[idx.get('datum', 1)])
        if not no or not dt:
            continue
        due = excel_date(row[idx.get('splatno', 2)])
        parsed.append((
            str(no), dt.date().isoformat(), due.date().isoformat() if due else None,
            str(row[idx.get('text', 3)] or ''), str(row[idx.get('firma', 4)] or ''),
            float(row[idx.get('celkem', 5)] or 0), float(row[idx.get('k likvidaci', 6)] or 0),
            str(row[idx.get('středisko', idx.get('středisko', 7))] or '').strip().upper(),
        ))
        dates.append(dt.date())
    year = dates[-1].year if dates else None
    month = dates[-1].month if dates else None
    imp_id = _register_import(con, 'REZIJNI_LISTY', path, digest, year, month, len(parsed), notes=f'List: {sheet_name}')
    con.executemany(
        '''INSERT INTO overhead_docs(invoice_no,doc_date,due_date,description,customer,total_amount,remaining_amount,center,source_import_id)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(invoice_no) DO UPDATE SET doc_date=excluded.doc_date,due_date=excluded.due_date,
           description=excluded.description,customer=excluded.customer,total_amount=excluded.total_amount,
           remaining_amount=excluded.remaining_amount,center=excluded.center,source_import_id=excluded.source_import_id''',
        [r + (imp_id,) for r in parsed]
    )
    return {'type': 'REŽIJNÍ LISTY', 'rows': len(parsed), 'period': f'{year:04d}-{month:02d}' if year and month else ''}


def _import_profit_report(con, reader, path, digest):
    parsed_docs = {}
    current = None
    sheet = reader.sheet_names[0]
    for _, row in reader.rows(sheet):
        row = _pad(row, 16)
        date_or_code, doc_or_name = row[2], row[4]
        if isinstance(doc_or_name, str) and re.match(r'^\d{2}SV\d+$', doc_or_name.strip()):
            current = doc_or_name.strip()
            dt = excel_date(date_or_code)
            parsed_docs[current] = {
                'date': dt.date().isoformat() if dt else None,
                'customer': str(row[5] or '').strip(),
                'items': [], 'item_sum': 0.0, 'total': None,
            }
            continue
        if current is None:
            continue
        # Product row.
        if row[2] is not None and row[4] is not None and isinstance(row[15], (int, float)):
            item = (
                str(row[2] or '').strip(), str(row[4] or '').strip(), str(row[7] or '').strip(),
                float(row[9] or 0), float(row[12] or 0), float(row[15] or 0),
            )
            parsed_docs[current]['items'].append(item)
            parsed_docs[current]['item_sum'] += item[-1]
        # First subtotal after product rows = authoritative document total.
        elif row[2] is None and row[4] is None and isinstance(row[15], (int, float)):
            parsed_docs[current]['total'] = float(row[15])
            current = None

    dates = []
    for p in parsed_docs.values():
        if p['date']:
            dates.append(datetime.fromisoformat(p['date']).date())
    period = Counter((d.year, d.month) for d in dates).most_common(1)[0][0] if dates else (None, None)
    imp_id = _register_import(con, 'ZISK_ZASOBY', path, digest, period[0], period[1], len(parsed_docs))

    # Refresh only documents contained in this report.
    doc_nos = list(parsed_docs)
    if doc_nos:
        marks = ','.join('?' * len(doc_nos))
        con.execute(f'DELETE FROM profit_items WHERE doc_no IN ({marks})', doc_nos)
    for doc_no, p in parsed_docs.items():
        total = p['total'] if p['total'] is not None else p['item_sum']
        # Keep report usable even when a profit report contains a document missing in raw DL export.
        exists = con.execute('SELECT 1 FROM delivery_notes WHERE doc_no=?', (doc_no,)).fetchone()
        if not exists:
            con.execute('''INSERT OR IGNORE INTO delivery_notes(doc_no,doc_date,customer,source_import_id)
                           VALUES (?,?,?,?)''', (doc_no, p['date'] or '1900-01-01', p['customer'], imp_id))
        con.execute(
            '''INSERT INTO profit_documents(doc_no,doc_date,customer,profit_total,source_import_id)
               VALUES (?,?,?,?,?)
               ON CONFLICT(doc_no) DO UPDATE SET doc_date=excluded.doc_date,customer=excluded.customer,
               profit_total=excluded.profit_total,source_import_id=excluded.source_import_id''',
            (doc_no, p['date'], p['customer'], total, imp_id)
        )
        con.executemany(
            '''INSERT INTO profit_items(doc_no,code,name,item_text,quantity,profit_unit,profit_total,source_import_id)
               VALUES (?,?,?,?,?,?,?,?)''',
            [(doc_no, *item, imp_id) for item in p['items']]
        )
    return {'type': 'ZISK (ZÁSOBY)', 'rows': len(parsed_docs), 'period': f'{period[0]:04d}-{period[1]:02d}' if period[0] else ''}


def _parse_month_label(label):
    if not isinstance(label, str):
        return None
    parts = label.strip().upper().split()
    if len(parts) < 2:
        return None
    month = MONTHS_CZ.get(parts[0])
    try:
        year = int(parts[-1])
    except ValueError:
        return None
    return (year, month) if month else None


def _import_legacy_summary(con, reader, path, digest):
    rows = list(reader.rows('ZISKY'))
    parsed = []
    for _, row in rows:
        row = _pad(row, 20)
        period = _parse_month_label(row[0])
        if not period:
            continue
        year, month = period
        # ZISKY columns: total, M, J, V, H. Count block starts in N.
        parsed.append((
            f'{year:04d}-{month:02d}', float(row[1] or 0), float(row[2] or 0), float(row[3] or 0),
            float(row[5] or 0), float(row[4] or 0), int(row[14] or 0), int(row[15] or 0),
            int(row[16] or 0), int(row[18] or 0), 'legacy:GRAFY 2026'
        ))
    imp_id = _register_import(con, 'HISTORICKY_SOUHRN', path, digest, row_count=len(parsed), notes='Převzatý list ZISKY; nové měsíce mají být počítány z raw exportů.')
    con.executemany(
        '''INSERT INTO monthly_summary(period,profit_total,profit_m,profit_j,profit_h,profit_other,count_total,count_m,count_j,count_h,source)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(period) DO UPDATE SET profit_total=excluded.profit_total,profit_m=excluded.profit_m,
           profit_j=excluded.profit_j,profit_h=excluded.profit_h,profit_other=excluded.profit_other,
           count_total=excluded.count_total,count_m=excluded.count_m,count_j=excluded.count_j,count_h=excluded.count_h,
           source=excluded.source''', parsed
    )
    return {'type': 'HISTORICKÝ SOUHRN', 'rows': len(parsed), 'period': ''}
