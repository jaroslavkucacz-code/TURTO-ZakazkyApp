"""Canonical locations and project filters. No map-side copies of CRM records."""
from __future__ import annotations

from contextlib import closing
from datetime import date
import math

from ..platform import user_access as access

PHASES = ('Neurčeno', 'Plánováno', 'Probíhá', 'Ukončeno', 'Zrušeno')
TABLES = {'company': 'companies', 'project': 'projects'}
LOCATION_FIELDS = ('address', 'gps_coordinates', 'map_source', 'map_address', 'map_ruian_id')


def ensure_schema(con):
    for table in TABLES.values():
        columns = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        additions = {'gps_coordinates': "TEXT NOT NULL DEFAULT ''",
                     'map_source': "TEXT NOT NULL DEFAULT ''",
                     'map_address': "TEXT NOT NULL DEFAULT ''",
                     'map_ruian_id': "TEXT NOT NULL DEFAULT ''"}
        if table == 'projects':
            additions.update(map_phase="TEXT NOT NULL DEFAULT 'Neurčeno'",
                             map_supplying='INTEGER NOT NULL DEFAULT 0',
                             merged_into_project_id='INTEGER REFERENCES projects(id)')
        for name, declaration in additions.items():
            if name not in columns:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
        # An address edit from ANY CRM path invalidates an unchanged pin. Never
        # silently display yesterday's location as the new headquarters/site.
        con.execute(f'''CREATE TRIGGER IF NOT EXISTS map_835_{table}_address
            AFTER UPDATE OF address ON {table}
            WHEN NEW.address IS NOT OLD.address AND trim(coalesce(NEW.gps_coordinates,''))<>''
              AND NEW.gps_coordinates IS OLD.gps_coordinates
            BEGIN UPDATE {table} SET map_source='review',map_address=OLD.address WHERE id=NEW.id; END''')
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_activity'").fetchone():
        con.execute('''CREATE TRIGGER IF NOT EXISTS map_835_project_activity
            AFTER UPDATE OF map_phase,map_supplying ON projects
            WHEN OLD.map_phase IS NOT NEW.map_phase OR OLD.map_supplying IS NOT NEW.map_supplying
            BEGIN INSERT INTO project_activity(project_id,last_activity_at)
              VALUES(NEW.id,strftime('%Y-%m-%d %H:%M:%f','now'))
              ON CONFLICT(project_id) DO UPDATE SET last_activity_at=excluded.last_activity_at
              WHERE excluded.last_activity_at>project_activity.last_activity_at; END''')


def point(M, value):
    raw = M.normalize_gps(value or '')
    if not raw:
        return None
    lat, lon = (float(part.strip()) for part in raw.split(','))
    if not all(math.isfinite(v) for v in (lat, lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError('GPS musí obsahovat zeměpisnou šířku a délku ve stupních.')
    return [lon, lat]


def location_state(M, row):
    if row.get('map_source') == 'review' or (row.get('map_address') and row['map_address'] != row.get('address', '')):
        return 'Ověřit po změně adresy', None
    try:
        coordinates = point(M, row.get('gps_coordinates'))
    except (ValueError, TypeError):
        return 'Neplatné GPS', None
    return ('Umístěno', coordinates) if coordinates else ('Chybí poloha', None)


def snapshot(row):
    return tuple(row.get(k, '') for k in LOCATION_FIELDS)


def form_snapshot(row, project=False):
    fields = ('address', 'gps_coordinates') + (('map_phase', 'map_supplying') if project else ())
    return tuple(row.get(k, 'Neurčeno' if k == 'map_phase' else 0 if k == 'map_supplying' else '') for k in fields)


def check_form(con, table, rid, expected):
    if table not in TABLES.values():
        raise ValueError('Neplatný typ záznamu.')
    con.execute('BEGIN IMMEDIATE')
    row = con.execute(f'SELECT * FROM {table} WHERE id=?', (rid,)).fetchone()
    if row is None or form_snapshot(dict(row), table == 'projects') != tuple(expected):
        raise ValueError('Adresa, poloha nebo stav se mezitím změnily. Zavřete formulář a otevřete jej znovu.')


def manual_form_location(con, table, rid, old_gps, gps, address):
    if old_gps != gps:
        con.execute(f'UPDATE {table} SET map_source=?,map_address=?,map_ruian_id=? WHERE id=?',
                    ('manual' if gps else '', address if gps else '', '', rid))


def preserve_gps_format(M, old, gps):
    try:
        if point(M,old) == point(M,gps): return old
    except (ValueError,TypeError):
        pass
    return gps


def record(M, kind, rid):
    table = TABLES[kind]
    access.require(M, table, write=False)
    with closing(M.db()) as con:
        row = con.execute(f'SELECT * FROM {table} WHERE id=? AND active=1', (int(rid),)).fetchone()
    if row is None:
        raise ValueError('Záznam už neexistuje nebo je archivovaný. Obnovte mapu.')
    return dict(row)


def save_location(M, kind, rid, gps, expected, source='manual', ruian_id=''):
    access.require(M, 'map')
    table = TABLES[kind]
    access.require(M, table)
    coordinates = point(M, gps)
    normalized = f'{coordinates[1]:.7f}, {coordinates[0]:.7f}' if coordinates else ''
    if source not in ('manual', 'ruian'):
        raise ValueError('Neplatný zdroj polohy.')
    with closing(M.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute(f'SELECT * FROM {table} WHERE id=? AND active=1', (int(rid),)).fetchone()
        if row is None or snapshot(dict(row)) != tuple(expected):
            raise ValueError('Poloha nebo adresa se mezitím změnila. Obnovte mapu a zkuste to znovu.')
        con.execute(f'''UPDATE {table} SET gps_coordinates=?,map_source=?,map_address=?,map_ruian_id=? WHERE id=?''',
                    (normalized, source if normalized else '', row['address'] if normalized else '',
                     str(ruian_id) if normalized and source == 'ruian' else '', int(rid)))


def parse_bound(value):
    value = (value or '').strip()
    if not value:
        return ''
    try:
        if '.' in value:
            day, month, year = value.rstrip('.').split('.')
            return date(int(year), int(month), int(day)).isoformat()
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ValueError('Datum zadejte jako DD.MM.RRRR.') from None


def rows(M, *, layer='both', phase='', supplying=False, start_from='', start_to='', query='', company_id=None):
    access.require(M, 'map', write=False)
    start_from, start_to = parse_bound(start_from), parse_bound(start_to)
    if start_from and start_to and start_from > start_to:
        raise ValueError('Datum „od“ musí být nejpozději datum „do“.')
    if phase and phase not in PHASES:
        raise ValueError('Neplatný stav Akce.')
    result = []
    # Read the current profile before selecting any layer. Hidden records never
    # cross the bridge into WebView2, even when a user switches on an open map.
    company_access = access.level(M, 'companies') >= access.READ
    project_access = access.level(M, 'projects') >= access.READ
    with closing(M.db()) as con:
        links = {}
        if company_access and project_access:
            if access.level(M, 'actions') >= access.READ:
                for row in con.execute('SELECT project_id,company_id FROM actions WHERE project_id IS NOT NULL AND company_id IS NOT NULL'):
                    links.setdefault(row[0], set()).add(row[1])
            allowed_types = []
            if access.level(M, 'issued_offers') >= access.READ:
                allowed_types.append('issued_offer')
            if access.level(M, 'received_orders') >= access.READ:
                allowed_types.append('received_order')
            if allowed_types:
                marks = ','.join('?' for _ in allowed_types)
                for row in con.execute(f'''SELECT COALESCE(d.project_id,a.project_id),d.company_id
                    FROM business_documents d LEFT JOIN actions a ON a.id=d.action_id
                    WHERE d.document_type IN ({marks}) AND d.company_id IS NOT NULL''', allowed_types):
                    if row[0] is not None:
                        links.setdefault(row[0], set()).add(row[1])
        companies = {}
        if company_access:
            companies = {r['id']: dict(r) for r in con.execute('SELECT * FROM companies WHERE active=1 AND merged_into_company_id IS NULL')}
        if layer in ('both', 'company'):
            for cid, row in companies.items():
                if company_id is None or cid == company_id:
                    result.append(dict(row, kind='company', title=row['official_name'] or row['short_name'],
                                       company_ids=[cid], companies='', phase='', supplying=False))
        if project_access and layer in ('both', 'project'):
            for raw in con.execute('SELECT * FROM projects WHERE active=1 AND merged_into_project_id IS NULL'):
                row = dict(raw)
                ids = sorted(cid for cid in links.get(row['id'], ()) if cid in companies)
                if company_id is not None and company_id not in ids:
                    continue
                if phase and row['map_phase'] != phase:
                    continue
                if supplying and (not row['map_supplying'] or row['map_phase'] in ('Ukončeno', 'Zrušeno')):
                    continue
                if start_from or start_to:
                    try:
                        start = parse_bound(row['start_date'])
                    except ValueError:
                        continue
                    if not start or (start_from and start < start_from) or (start_to and start > start_to):
                        continue
                result.append(dict(row, kind='project', title=row['name'], company_ids=ids,
                                   companies='; '.join(companies[cid]['official_name'] or companies[cid]['short_name'] for cid in ids),
                                   phase=row['map_phase'], supplying=bool(row['map_supplying'])))
    needle = query.strip().casefold()
    visible = []
    for row in result:
        if needle and needle not in ' '.join(str(row.get(k) or '') for k in ('title', 'address', 'companies', 'ico')).casefold():
            continue
        state, coordinates = location_state(M, row)
        row.update(key=f"{row['kind']}:{row['id']}", location_state=state, coordinates=coordinates)
        visible.append(row)
    return sorted(visible, key=lambda r: (r['kind'], r['title'].casefold(), r['id']))


def features(records):
    # An explicit projection: notes, prices, contacts, and snapshots stay in CRM.
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'id': row['key'],
         'geometry': {'type': 'Point', 'coordinates': row['coordinates']},
         'properties': {k: row[k] for k in ('key', 'title', 'kind', 'address', 'phase', 'supplying')}}
        for row in records if row['coordinates'] is not None]}


def merge_projects(M, source, target, user=''):
    access.require(M, 'projects')
    if int(source) == int(target):
        raise ValueError('Vyberte jinou cílovou Akci.')
    with closing(M.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        valid = con.execute('SELECT id FROM projects WHERE id IN (?,?) AND active=1 AND merged_into_project_id IS NULL',
                            (source, target)).fetchall()
        if len(valid) != 2:
            raise ValueError('Jedna Akce už není aktivní. Otevřete sloučení znovu.')
        # Move current ID links together; exported documents/revisions and their
        # historical text snapshots are not rewritten. Access guards are atomic.
        con.execute('UPDATE actions SET project_id=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE project_id=?',
                    (target, user, source))
        for table in ('business_documents', 'supplier_offers'):
            con.execute(f'UPDATE {table} SET project_id=? WHERE project_id=?', (target, source))
        con.execute('UPDATE projects SET active=0,merged_into_project_id=? WHERE id=?', (target, source))
