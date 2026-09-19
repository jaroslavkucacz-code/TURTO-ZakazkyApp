"""Offline Czech address lookup; CRM addresses are never sent to a geocoder.

Source: ČÚZK, RÚIAN address CSV, CC BY 4.0. Index replacement is atomic and
independent of business data. A match is usable only for one distinct ADM code.
"""
from __future__ import annotations

from contextlib import closing
import csv
from datetime import datetime, timezone
from html.parser import HTMLParser
import io
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import zipfile

PAGE = 'https://nahlizenidokn.cuzk.gov.cz/StahniAdresniMistaRUIAN.aspx'
LICENSE = 'ČÚZK – RÚIAN, CC BY 4.0'
_lock = threading.Lock()


def cache_root():
    root = Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache') / 'TURTO' / 'CRM-Maps'
    root.mkdir(parents=True, exist_ok=True)
    return root


def index_path():
    return cache_root() / 'ruian-v1.sqlite'


def key(value):
    text = unicodedata.normalize('NFKD', str(value or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'\b(\d{3})\s+(\d{2})\b', r'\1\2', text)
    text = re.sub(r'\b(c\.?\s*p\.?|ceska republika|czech republic|cesko|czechia)\b', '', text)
    # Order-independent exact tokens accommodate ARES's city/PSČ ordering.
    # No fuzzy correction, partial street match, or inferred building number.
    return ' '.join(sorted(re.findall(r'[a-z0-9]+(?:/[a-z0-9]+)?', text)))


def allowed_url(url):
    parsed = urlsplit(url)
    return parsed.scheme == 'https' and parsed.hostname in {
        'nahlizenidokn.cuzk.gov.cz', 'vdp.cuzk.gov.cz', 'vdp.cuzk.cz'}


def response(url):
    if not allowed_url(url):
        raise ValueError('Adresář lze stahovat pouze z oficiálního serveru ČÚZK.')
    result = urlopen(Request(url, headers={'User-Agent': 'TURTO-CRM/8.0 (local RUIAN address index)'}), timeout=45)
    if not allowed_url(result.url):
        result.close()
        raise ValueError('Neplatné přesměrování při stažení RÚIAN.')
    return result


def download(progress=lambda text: None):
    class Links(HTMLParser):
        urls = None
        def __init__(self):
            super().__init__(); self.urls = []
        def handle_starttag(self, tag, attrs):
            href = dict(attrs).get('href', '')
            if tag == 'a' and re.search(r'/\d{8}_OB_ADR_csv\.zip$', href, re.I):
                self.urls.append(urljoin(PAGE, href))
    progress('Zjišťuji aktuální adresář ČÚZK…')
    with response(PAGE) as stream:
        html = stream.read(2_000_001)
    if len(html) > 2_000_000:
        raise ValueError('Server vrátil neplatnou stránku adresáře.')
    parser = Links(); parser.feed(html.decode('utf-8', errors='replace'))
    if not parser.urls:
        raise ValueError('ČÚZK neposkytl odkaz na adresář. Zkuste stažení později nebo importujte oficiální ZIP.')
    url = sorted(set(parser.urls))[-1]
    with tempfile.TemporaryDirectory(prefix='ruian-', dir=cache_root()) as td:
        archive = Path(td) / 'addresses.zip'
        with response(url) as stream, archive.open('wb') as output:
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > 600 * 1024 * 1024:
                    raise ValueError('Stažený soubor překročil povolenou velikost.')
                output.write(chunk)
                progress(f'Stahuji adresář ČR: {total // (1024 * 1024)} MB…')
        return import_zip(archive, progress, source=url)


def import_zip(path, progress=lambda text: None, source='Místní soubor RÚIAN'):
    if not _lock.acquire(blocking=False):
        raise ValueError('Adresář se právě aktualizuje.')
    try:
        with tempfile.TemporaryDirectory(prefix='index-', dir=cache_root()) as td:
            destination = Path(td) / 'index.sqlite'
            count = 0
            with closing(sqlite3.connect(destination)) as con, zipfile.ZipFile(path) as archive:
                con.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
                    CREATE TABLE addresses(code TEXT PRIMARY KEY,label TEXT,y REAL,x REAL);
                    CREATE TABLE aliases(key TEXT,code TEXT);
                    CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);''')
                members = [m for m in archive.infolist() if m.filename.lower().endswith('.csv') and not m.is_dir()]
                if not members or sum(m.file_size for m in members) > 3_000_000_000:
                    raise ValueError('Neplatná velikost nebo obsah archivu RÚIAN.')
                for member in members:
                    # Stream entries, never extract user-supplied archive paths.
                    with archive.open(member) as raw:
                        stream = io.TextIOWrapper(raw, encoding='cp1250', newline='')
                        reader = csv.DictReader(stream, delimiter=';')
                        required = {'Kód ADM', 'Název obce', 'Název ulice', 'Číslo domovní', 'PSČ', 'Souřadnice Y', 'Souřadnice X'}
                        if not required.issubset(reader.fieldnames or ()):
                            raise ValueError('CSV neodpovídá oficiální struktuře adresních míst RÚIAN.')
                        values, aliases = [], []
                        for row in reader:
                            try:
                                y = float(row['Souřadnice Y'].replace(',', '.'))
                                x = float(row['Souřadnice X'].replace(',', '.'))
                            except (ValueError, TypeError):
                                continue  # RÚIAN can contain points without coordinates.
                            code = row['Kód ADM'].strip()
                            if not code.isdigit() or not (400_000 < y < 950_000 and 900_000 < x < 1_300_000):
                                continue
                            street, city = row['Název ulice'].strip(), row['Název obce'].strip()
                            part, district = row.get('Název části obce', '').strip(), row.get('Název MOMC', '').strip()
                            number = row['Číslo domovní'].strip()
                            if 'ev' in row.get('Typ SO', '').casefold():
                                number = 'č.ev. ' + number
                            orientation = row.get('Číslo orientační', '').strip() + row.get('Znak čísla orientačního', '').strip()
                            if orientation:
                                number += '/' + orientation
                            postal = row['PSČ'].replace(' ', '')
                            road = street or part or city
                            label = f'{road} {number}, {postal} {city}'
                            values.append((code, label, y, x))
                            variants = {f'{road} {number} {postal} {town}' for town in (city, district) if town}
                            if part and part not in {road, city}:
                                variants.add(f'{road} {number} {postal} {part} {city}')
                            aliases.extend((key(v), code) for v in variants)
                            count += 1
                            if len(values) >= 5000:
                                con.executemany('INSERT INTO addresses VALUES(?,?,?,?)', values)
                                con.executemany('INSERT INTO aliases VALUES(?,?)', aliases)
                                values.clear(); aliases.clear()
                                progress(f'Připravuji adresář: {count:,} adres…')
                        con.executemany('INSERT INTO addresses VALUES(?,?,?,?)', values)
                        con.executemany('INSERT INTO aliases VALUES(?,?)', aliases)
                    con.commit()
                if not count:
                    raise ValueError('Adresář neobsahuje žádné platné souřadnice.')
                progress('Dokončuji vyhledávací index…')
                con.execute('CREATE INDEX alias_lookup ON aliases(key)')
                con.executemany('INSERT INTO meta VALUES(?,?)', [
                    ('source', source), ('attribution', LICENSE), ('count', str(count)),
                    ('imported', datetime.now(timezone.utc).isoformat())])
                con.commit()
            os.replace(destination, index_path())
            return count
    finally:
        _lock.release()


def lookup(address):
    path = index_path()
    if not path.is_file():
        raise ValueError('Nejdřív stáhněte adresář ČR nebo importujte ZIP ČÚZK.')
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute('''SELECT DISTINCT a.* FROM aliases k JOIN addresses a ON a.code=k.code
                              WHERE k.key=? ORDER BY a.code LIMIT 20''', (key(address),)).fetchall()
    from pyproj import Transformer
    transformer = Transformer.from_crs('EPSG:5514', 'EPSG:4326', always_xy=True)
    result = []
    for row in rows:
        lon, lat = transformer.transform(-row['y'], -row['x'])
        if not (48 < lat < 52 and 12 < lon < 19):
            raise ValueError('Souřadnice adresního místa jsou mimo ČR.')
        result.append(dict(row, gps=f'{lat:.7f}, {lon:.7f}'))
    return result
