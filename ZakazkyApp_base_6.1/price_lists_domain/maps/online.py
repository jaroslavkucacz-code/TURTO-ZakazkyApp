"""Bounded, cancellable ČÚZK lookups; no country-wide download or disk cache.

GeocodeSOE supplies candidates, then QUERY resolves their current attributes
and WGS84 geometry. Object IDs from suggest are not RÚIAN codes. Only the
address/query is sent, never the CRM record, its name, notes or database ID.
"""
from __future__ import annotations

from collections import Counter
import json
import math
import re
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

BASE = 'https://ags.cuzk.gov.cz/arcgis/rest/services/RUIAN/MapServer'
SOURCE = 'ČÚZK – RÚIAN (online)'
MAX_RESULTS = 20
_request_lock = threading.Lock()
_next_request = 0.0


class Cancelled(Exception):
    pass


class ServiceError(ValueError):
    pass


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname != 'ags.cuzk.gov.cz':
            raise ServiceError('Služba ČÚZK vrátila nepovolené přesměrování.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _text(value, limit=150):
    value = ' '.join(str(value or '').split())
    if not value or len(value) > limit:
        raise ValueError(f'Vyplňte hledaný údaj (nejvýše {limit} znaků).')
    return value


def _integer(value):
    if isinstance(value, bool):
        raise ValueError('Neplatný identifikátor ČÚZK.')
    number = float(value)
    if not math.isfinite(number) or number != int(number) or not 0 < number < 2**53:
        raise ValueError('Neplatný identifikátor ČÚZK.')
    return int(number)


def _current(attributes):
    return attributes.get('platido') is None and attributes.get('nespravny') in (None, '', 'N', 0)


def _point(feature):
    geometry = feature.get('geometry') or {}
    lon, lat = float(geometry['x']), float(geometry['y'])
    if not all(math.isfinite(v) for v in (lon, lat)) or not (12 <= lon <= 19 and 48 <= lat <= 52):
        raise ValueError('ČÚZK nevrátil platnou polohu v ČR.')
    return {'gps': f'{lat:.7f}, {lon:.7f}', 'coordinates': [lon, lat]}


def address_tokens(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r'\b(\d{3})\s+(\d{2})\b', r'\1\2', value)
    value = re.sub(r'\b(?:ceska republika|czech republic|cesko|czechia)\b', '', value)
    value = re.sub(r'\bc\.?\s*p\.?\s*', '', value)
    value = re.sub(r'\bc\.?\s*ev\.?\s*', ' ev ', value)
    value = re.sub(r'\s*/\s*', '/', value)
    return Counter(re.findall(r'[a-z0-9]+(?:/[a-z0-9]+)?', value))


def exact_address(address, matches):
    """Batch writes require one current address and complete, matching numbers.

The service may add the district name. It may not add/remove any house number,
postcode or Prague district number. Partial queries are for manual review only.
"""
    if len(matches) != 1:
        return None
    requested, found = address_tokens(address), address_tokens(matches[0]['label'])
    numbers = lambda tokens: Counter({k: v for k, v in tokens.items() if any(c.isdigit() for c in k)})
    if (not any(re.fullmatch(r'\d{5}', token) for token in requested)
            or not any(re.fullmatch(r'\d+(?:/\d+[a-z]?)?', token) and len(token) != 5 for token in requested)
            or numbers(requested) != numbers(found) or requested - found
            or requested.get('ev', 0) != found.get('ev', 0)):
        return None
    return matches[0]


def parse_parcel(number, kind='auto'):
    if kind not in ('auto', 'land', 'building'):
        raise ValueError('Vyberte druh číslování parcely.')
    number = _text(number, 25).lower()
    match = re.fullmatch(r'(st\.?\s*)?(\d{1,5})(?:\s*/\s*(\d{1,5}))?', number)
    if not match or int(match[2]) == 0 or (match[3] is not None and int(match[3]) == 0):
        raise ValueError('Parcelu zadejte například 123, 123/4 nebo st. 123/4.')
    if match[1]:
        if kind == 'land':
            raise ValueError('Předpona st. označuje stavební parcelu. Změňte druh parcely.')
        kind = 'building'
    return int(match[2]), int(match[3]) if match[3] else None, {'auto': None, 'land': 2, 'building': 1}[kind]


class Client:
    def __init__(self, cancel=None):
        self.cancel = cancel or threading.Event()
        self.opener = build_opener(_SafeRedirect())

    def check_cancelled(self):
        if self.cancel.is_set():
            raise Cancelled()

    def request(self, path, **params):
        global _next_request
        if path not in ('/1/query', '/7/query', '/0/query',
                        '/exts/GeocodeSOE/tables/1/suggest', '/exts/GeocodeSOE/tables/7/suggest'):
            raise ValueError('Neplatná operace ČÚZK.')
        self.check_cancelled()
        # One in-flight request per CRM process; wait without blocking the UI.
        while not _request_lock.acquire(timeout=.1):
            self.check_cancelled()
        try:
            if self.cancel.wait(max(0, _next_request - time.monotonic())):
                raise Cancelled()
            req = Request(BASE + path + '?' + urlencode(dict(params, f='json')),
                          headers={'User-Agent': 'TURTO-CRM/8.0.36', 'Accept': 'application/json'})
            try:
                with self.opener.open(req, timeout=15) as response:
                    payload = response.read(2_000_001)
                self.check_cancelled()
                if len(payload) > 2_000_000:
                    raise ServiceError('Odpověď ČÚZK je příliš velká. Upřesněte hledání.')
                data = json.loads(payload)
                if not isinstance(data, dict) or 'error' in data:
                    raise ServiceError('ČÚZK požadavek nezpracoval. Zkuste hledání později.')
                return data
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                raise ServiceError('Online služba ČÚZK není dostupná. Zkontrolujte internet a zkuste to znovu.') from exc
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ServiceError('ČÚZK vrátil neplatnou odpověď. Zkuste hledání později.') from exc
        finally:
            _next_request = time.monotonic() + .5
            _request_lock.release()

    def _features(self, layer, **params):
        data = self.request(f'/{layer}/query', resultRecordCount=MAX_RESULTS+1, outSR=4326, **params)
        features = data.get('features')
        if not isinstance(features, list):
            raise ServiceError('ČÚZK nevrátil očekávaný seznam výsledků.')
        if data.get('exceededTransferLimit') or len(features) > MAX_RESULTS:
            raise ValueError('Nalezeno příliš mnoho možností. Upřesněte hledání.')
        return features

    def _suggest(self, layer, text):
        data = self.request(f'/exts/GeocodeSOE/tables/{layer}/suggest', text=text, maxSuggestions=MAX_RESULTS+1)
        rows = data.get('suggestions')
        if not isinstance(rows, list):
            raise ServiceError('ČÚZK nevrátil očekávaný seznam výsledků.')
        if len(rows) > MAX_RESULTS or any(row.get('isCollection') for row in rows):
            raise ValueError('Hledání je příliš obecné. Doplňte obec nebo přesnější název.')
        try:
            return ','.join(str(_integer(row['magicKey'])) for row in rows)
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError('ČÚZK vrátil neplatné identifikátory výsledků.') from exc

    def addresses(self, address):
        ids = self._suggest(1, _text(address))
        if not ids:
            return []
        features = self._features(1, objectIds=ids,
            outFields='kod,adresa,nespravny,platido', returnGeometry='true')
        result = {}
        for feature in features:
            try:
                attr = feature['attributes']
                if not _current(attr):
                    continue
                code = str(_integer(attr['kod']))
                result[code] = dict(_point(feature), code=code, label=_text(attr['adresa']), source='ruian')
            except (ValueError, KeyError, TypeError):
                raise ServiceError('ČÚZK vrátil neúplné údaje adresy; polohu nelze bezpečně uložit.') from None
        return sorted(result.values(), key=lambda row: row['label'])

    def cadastres(self, text):
        text = _text(text, 100)
        if re.fullmatch(r'\d{6}', text):
            params = {'where': f'kod={int(text)}'}
        else:
            if len(text) < 3:
                raise ValueError('Zadejte alespoň tři znaky názvu nebo šestimístný kód katastrálního území.')
            ids = self._suggest(7, text)
            if not ids:
                return []
            params = {'objectIds': ids}
        features = self._features(7, outFields='kod,nazev,obec,nespravny,platido', returnGeometry='false', **params)
        result = {}
        for feature in features:
            try:
                attr = feature['attributes']
                if _current(attr):
                    code = _integer(attr['kod'])
                    result[code] = {'code': code, 'name': _text(attr['nazev']),
                                    'label': f"{attr['nazev']} [{code}]"}
            except (ValueError, KeyError, TypeError):
                raise ServiceError('ČÚZK vrátil neúplné údaje katastrálního území.') from None
        return sorted(result.values(), key=lambda row: row['label'])

    def parcels(self, cadastre, number, kind='auto'):
        main, subdivision, kind_code = parse_parcel(number, kind)
        code = _integer(cadastre['code'])
        if not 100000 <= code <= 999999:
            raise ValueError('Neplatný kód katastrálního území.')
        where = f'katastralniuzemi={code} AND kmenovecislo={main}'
        where += f' AND poddelenicisla={subdivision}' if subdivision else ' AND (poddelenicisla IS NULL OR poddelenicisla=0)'
        if kind_code:
            where += f' AND druhcislovanikod={kind_code}'
        features = self._features(0, where=where,
            outFields='id,katastralniuzemi,kmenovecislo,poddelenicisla,druhcislovanikod,cisloparcely,nespravny,platido',
            returnGeometry='true')
        result = {}
        for feature in features:
            try:
                attr = feature['attributes']
                if not _current(attr):
                    continue
                if (attr['katastralniuzemi'] != code or attr['kmenovecislo'] != main
                        or (attr['poddelenicisla'] or None) != subdivision
                        or attr['druhcislovanikod'] not in (1, 2)
                        or (kind_code and attr['druhcislovanikod'] != kind_code)):
                    raise ValueError('Parcel identity mismatch')
                rid = str(_integer(attr['id']))
                prefix = 'st. ' if attr['druhcislovanikod'] == 1 else ''
                parcel = f'{prefix}{main}' + (f'/{subdivision}' if subdivision else '')
                result[rid] = dict(_point(feature), code=rid, source='ruian-parcel',
                    label=f"Parcela {parcel}, k. ú. {cadastre['name']} [{code}]")
            except (ValueError, KeyError, TypeError):
                raise ServiceError('ČÚZK nevrátil platný definiční bod požadované parcely.') from None
        return sorted(result.values(), key=lambda row: row['label'])


def batch_addresses(records, client, progress=lambda text: None):
    """Resolve unique queries once per job; partial results survive an outage."""
    matched, skipped, cache = [], 0, {}
    error = ''
    for index, row in enumerate(records):
        client.check_cancelled()
        progress(f"Dohledávám GPS online: {index+1}/{len(records)}…")
        address = row['address'].strip()
        try:
            if address not in cache:
                cache[address] = client.addresses(address)
            match = exact_address(address, cache[address])
            if match:
                matched.append((row, match))
            else:
                skipped += 1
        except ServiceError as exc:
            error = str(exc)
            break
        except ValueError:
            skipped += 1
    return {'matches': matched, 'skipped': skipped, 'error': error,
            'unprocessed': len(records)-len(matched)-skipped}
