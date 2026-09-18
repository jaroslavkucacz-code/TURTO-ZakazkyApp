"""Consistent SQLite snapshots, strict type checks and content verification."""
from contextlib import closing
import hashlib
import math
from pathlib import Path
import sqlite3
import struct
import time

from data_location import _register_sqlite_collations

CORE = {'users', 'settings', 'companies', 'people', 'projects', 'actions', 'requests', 'tasks'}
TYPES = {'INTEGER': 'bigint', 'INT': 'bigint', 'TEXT': 'text', 'REAL': 'double precision', 'BLOB': 'bytea'}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def readonly(path):
    path = Path(path).resolve(strict=True)
    con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    _register_sqlite_collations(con)
    con.execute('PRAGMA query_only=ON')
    return con


def snapshot(source, target, timeout=60):
    """Backup includes committed WAL data; never opens the source for writing."""
    source, target = Path(source).resolve(strict=True), Path(target).resolve()
    if source == target:
        raise ValueError('Kopie nesmí přepsat zdrojovou databázi.')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also refuses symlinks and existing target files.
    with target.open('xb'):
        pass
    target.chmod(0o600)
    try:
        deadline = time.monotonic() + timeout
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('Vytvoření kopie překročilo časový limit.')
        with closing(readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
            _register_sqlite_collations(dst)
            src.backup(dst, pages=256, progress=progress)
            dst.execute('PRAGMA journal_mode=DELETE')
            if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Kopie databáze neprošla kontrolou integrity.')
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def file_digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def inventory(con):
    integrity = con.execute('PRAGMA integrity_check').fetchall()
    if integrity != [('ok',)]:
        raise ValueError('Zdrojová databáze neprošla kontrolou integrity.')
    violations = con.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        # Table names/count only: business values never appear in diagnostics.
        raise ValueError(f'Zdroj obsahuje {len(violations)} porušených vazeb. Převod byl zastaven.')
    objects = [dict(zip(('type', 'name', 'table', 'sql'), r)) for r in con.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")]
    kinds = {r[1]: r[2] for r in con.execute('PRAGMA table_list') if r[0] == 'main'}
    virtual = [o for o in objects if kinds.get(o['name']) == 'virtual' and o['type'] == 'table']
    if any(o['name'] != 'price_list_items_fts' or 'fts5' not in o['sql'].lower() or
           "content='price_list_items'" not in o['sql'].replace(' ', '') for o in virtual):
        raise ValueError('Neznámá virtuální tabulka; je nutné doplnit převodník.')
    names = {o['name'] for o in objects if o['type'] == 'table' and kinds.get(o['name']) == 'table'}
    if not CORE <= names:
        raise ValueError('Soubor není úplná databáze CRM; chybí základní tabulky.')
    if '_turto_pilot_manifest' in names:
        raise ValueError('Zdroj obsahuje rezervovaný název tabulky.')
    tables = []
    def identifier(value):
        if '\x00' in value or len(value.encode('utf-8')) > 63:
            raise ValueError('Název tabulky nebo sloupce není kompatibilní s PostgreSQL.')
    for name in sorted(names):
        identifier(name)
        q = quote(name)
        columns = [dict(zip(('cid', 'name', 'type', 'notnull', 'default', 'pk', 'hidden'), r))
                   for r in con.execute(f'PRAGMA table_xinfo({q})')]
        for column in columns:
            identifier(column['name'])
            if column['hidden'] or column['type'].upper() not in TYPES:
                raise ValueError(f'Nepodporovaný sloupec {name}.{column["name"]}; převod zastaven.')
        foreign_keys = [list(r) for r in con.execute(f'PRAGMA foreign_key_list({q})')]
        unique = []
        for idx in con.execute(f'PRAGMA index_list({q})'):
            if idx[2] and idx[3] != 'pk':
                terms = [list(r) for r in con.execute(f'PRAGMA index_xinfo({quote(idx[1])})') if r[5]]
                # Expression / partial indexes remain explicit release blockers,
                # recorded verbatim, instead of being silently reinterpreted.
                unique.append({'name': idx[1], 'partial': bool(idx[4]), 'terms': terms})
        pk = [c for c in sorted(columns, key=lambda c: c['pk']) if c['pk']]
        identity = pk[0]['name'] if len(pk) == 1 and pk[0]['type'].upper() == 'INTEGER' else None
        high_water = None
        if 'sqlite_sequence' in kinds:
            row = con.execute('SELECT seq FROM sqlite_sequence WHERE name=?', (name,)).fetchone()
            high_water = row[0] if row else None
        tables.append({'name': name, 'columns': columns, 'foreign_keys': foreign_keys,
                       'unique': unique, 'identity': identity, 'sequence': high_water})
    return {'tables': tables, 'source_schema': objects,
            'excluded_derived_tables': sorted(n for n, k in kinds.items() if k in ('virtual', 'shadow')),
            'application_ready': False,
            'blockers': [
                'GUI stále používá SQLite; pilot nelze otevřít v produkční aplikaci.',
                'SQL dotazy, triggery, CHECK/default výrazy, české řazení a úplné indexy čekají na převod.',
                'Serverové přihlášení, oprávnění a souběžné změny všech agend čekají na implementaci.',
                'Externí přílohy a samostatná databáze Přehledů vyžadují samostatné převedení.'
            ]}


def row_hash(row, columns):
    h = hashlib.sha256()
    for value, column in zip(row, columns, strict=True):
        kind = column['type'].upper()
        if value is None:
            if column['notnull'] or column['pk']:
                raise ValueError(f'NULL v povinném sloupci {column["name"]}; převod zastaven.')
            encoded = b'N'
        elif kind in ('INTEGER', 'INT'):
            if type(value) is not int or not -(2**63) <= value < 2**63:
                raise ValueError(f'Neplatná celočíselná hodnota ve sloupci {column["name"]}.')
            encoded = b'I' + struct.pack('>q', value)
        elif kind == 'REAL':
            if not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f'Neplatné reálné číslo ve sloupci {column["name"]}.')
            encoded = b'R' + struct.pack('>d', float(value))
        elif kind == 'TEXT':
            if not isinstance(value, str) or '\x00' in value:
                raise ValueError(f'Neplatný text ve sloupci {column["name"]}.')
            encoded = b'T' + value.encode('utf-8')
        else:
            if not isinstance(value, (bytes, memoryview)):
                raise ValueError(f'Neplatná příloha ve sloupci {column["name"]}.')
            encoded = b'B' + bytes(value)
        h.update(struct.pack('>Q', len(encoded)))
        h.update(encoded)
    return h.digest()


def content_digest(rows, columns):
    # Order-independent multiset; duplicate rows still count. At 50k rows this
    # uses a few MB, independent of the total size of attached binary files.
    hashes = sorted(row_hash(row, columns) for row in rows)
    h = hashlib.sha256()
    for digest in hashes:
        h.update(digest)
    return {'rows': len(hashes), 'sha256': h.hexdigest()}


def inspect(path):
    with closing(readonly(path)) as con:
        con.execute('BEGIN')
        plan = inventory(con)
        for table in plan['tables']:
            table['content'] = content_digest(con.execute(f'SELECT * FROM {quote(table["name"])}'), table['columns'])
        return plan
