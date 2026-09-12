from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

MAIN = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def excel_date(value):
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(1899, 12, 30) + timedelta(days=float(value))
    except (TypeError, ValueError):
        return None


def _column_index(cell_ref: str) -> int:
    m = re.match(r'([A-Z]+)', cell_ref or '')
    if not m:
        return 0
    n = 0
    for c in m.group(1):
        n = n * 26 + ord(c) - 64
    return n - 1


@dataclass
class SheetInfo:
    name: str
    target: str


class XlsxReader:
    """Small dependency-free XLSX reader for POHODA-style value exports.

    It deliberately reads cached formula values and does not try to calculate Excel formulas.
    This keeps the program independent from a locally installed Excel.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(self.path)
        self._shared = self._load_shared_strings()
        self._sheets = self._load_sheets()

    def close(self):
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @property
    def sheet_names(self):
        return [s.name for s in self._sheets]

    def _load_shared_strings(self):
        if 'xl/sharedStrings.xml' not in self._zip.namelist():
            return []
        root = ET.fromstring(self._zip.read('xl/sharedStrings.xml'))
        values = []
        for si in root.findall('a:si', MAIN):
            values.append(''.join((t.text or '') for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t')))
        return values

    def _load_sheets(self):
        wb = ET.fromstring(self._zip.read('xl/workbook.xml'))
        rel_root = ET.fromstring(self._zip.read('xl/_rels/workbook.xml.rels'))
        rel_map = {r.attrib['Id']: r.attrib['Target'] for r in rel_root}
        sheets = []
        for node in wb.find('a:sheets', MAIN):
            name = node.attrib['name']
            target = rel_map[node.attrib[RID]].lstrip('/')
            if not target.startswith('xl/'):
                target = 'xl/' + target
            sheets.append(SheetInfo(name=name, target=target))
        return sheets

    def rows(self, sheet_name: str | None = None):
        if sheet_name is None:
            info = self._sheets[0]
        else:
            info = next((s for s in self._sheets if s.name == sheet_name), None)
            if info is None:
                raise KeyError(f'List {sheet_name!r} nebyl nalezen.')
        root = ET.fromstring(self._zip.read(info.target))
        for row in root.findall('.//a:sheetData/a:row', MAIN):
            values = {}
            for cell in row.findall('a:c', MAIN):
                idx = _column_index(cell.attrib.get('r', 'A1'))
                typ = cell.attrib.get('t')
                value_node = cell.find('a:v', MAIN)
                value = None
                if typ == 'inlineStr':
                    is_node = cell.find('a:is', MAIN)
                    if is_node is not None:
                        value = ''.join((t.text or '') for t in is_node.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
                elif value_node is not None:
                    raw = value_node.text
                    if typ == 's':
                        try:
                            value = self._shared[int(raw)]
                        except Exception:
                            value = raw
                    elif typ == 'b':
                        value = raw == '1'
                    else:
                        try:
                            value = float(raw) if raw and ('.' in raw or 'E' in raw.upper()) else int(raw)
                        except Exception:
                            value = raw
                values[idx] = value
            if not values:
                continue
            width = max(values) + 1
            out = [None] * width
            for idx, value in values.items():
                out[idx] = value
            yield int(row.attrib.get('r', 0)), out
