"""Validated, previewed imports. Every selected batch commits in one transaction."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import math
import re
import shutil
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .xlsx_reader import XlsxReader
from .importers import sha256_file, _parse_month_label, _register_import

TITLES = {'DATA_POHODA':'Dodací listy', 'ZISK_ZASOBY':'Zisk a položky',
          'REZIJNI_LISTY':'Režijní listy', 'HISTORICKY_SOUHRN':'Historické souhrny'}
TABLES = {'DATA_POHODA':('delivery_notes','doc_no'), 'ZISK_ZASOBY':('profit_documents','doc_no'),
          'REZIJNI_LISTY':('overhead_docs','invoice_no'), 'HISTORICKY_SOUHRN':('monthly_summary','period')}


def norm(value):
    s = unicodedata.normalize('NFKD', str(value or '').strip().lower())
    return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).split())


def number(value, label, optional=False):
    if value is None or str(value).strip() == '':
        if optional: return None
        raise ValueError(f'{label}: chybí číslo (vzorec v Excelu musí mít uložený výsledek).')
    if isinstance(value, bool): raise ValueError(f'{label}: neplatné číslo.')
    try:
        s = str(value).strip().replace('\xa0','').replace('\u202f','').replace(' ','')
        if ',' in s: s = s.replace('.', '').replace(',', '.')
        result = float(s)
        if not math.isfinite(result): raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ValueError(f'{label}: neplatné číslo {value!r}.') from None


def date_value(value, label, epoch1904=False, optional=False):
    if value is None or value == '':
        if optional: return None
        raise ValueError(f'{label}: chybí datum.')
    if isinstance(value, datetime): return value.date().isoformat()
    if isinstance(value, date): return value.isoformat()
    try:
        if isinstance(value, (float,int)) and not isinstance(value,bool):
            result = (datetime(1904,1,1) if epoch1904 else datetime(1899,12,30)) + timedelta(days=float(value))
            if not 1900 <= result.year <= 2200: raise ValueError()
            return result.date().isoformat()
        for fmt in ('%Y-%m-%d','%d.%m.%Y','%d. %m. %Y','%d/%m/%Y','%Y-%m-%d %H:%M:%S'):
            try: return datetime.strptime(str(value).strip(),fmt).date().isoformat()
            except ValueError: pass
    except (ValueError,OverflowError): pass
    raise ValueError(f'{label}: neplatné datum {value!r}.')


def text(value):
    if isinstance(value,float) and value.is_integer(): return str(int(value))
    return str(value if value is not None else '').strip()


@dataclass
class Component:
    kind: str
    sheet: str
    records: dict = field(default_factory=dict)

    @property
    def periods(self):
        return sorted({r.get('doc_date',r.get('period',''))[:7] for r in self.records.values()})


@dataclass
class Source:
    path: Path
    digest: str
    components: list
    warnings: list
    duplicate: bool = False


def _add(component, key, row, where):
    if not key: raise ValueError(f'{where}: chybí číslo dokladu.')
    if key in component.records: raise ValueError(f'{where}: opakované číslo {key}.')
    component.records[key] = row


ALIASES = {
    'date':('datum','datum dokladu'), 'no':('cislo','cislo dl','doklad'),
    'base':('kc zakladni','zaklad bez dph','obrat bez dph'), 'total':('celkem','kc celkem'),
    'customer':('firma','zakaznik'), 'center':('stredisko',), 'project':('zakazka','projekt'),
    'description':('text','popis'), 'note':('poznamka',), 'due':('splatno','datum splatnosti'),
    'remaining':('k likvidaci','zbyva uhradit'), 'code':('kod','kod produktu'),
    'name':('nazev','nazev produktu','produkt'), 'quantity':('mnozstvi',),
    'profit':('zisk celkem',), 'sales':('prodej celkem bez dph',), 'cost':('naklad celkem bez dph',),
}


def _header(rows):
    for pos,(rn,row) in enumerate(rows[:25]):
        idx = {norm(v):i for i,v in enumerate(row) if v is not None}
        mapping = {key:next((idx[v] for v in choices if v in idx),None) for key,choices in ALIASES.items()}
        if mapping['no'] is not None and mapping['date'] is not None:
            return pos,mapping
    return None,None


def _table(sheet, rows, epoch1904=False):
    pos,idx = _header(rows)
    if idx is None: return None
    if idx['quantity'] is not None and idx['name'] is not None and (idx['profit'] is not None or (idx['sales'] is not None and idx['cost'] is not None)):
        kind = 'ZISK_ZASOBY'
    elif idx['remaining'] is not None and idx['due'] is not None:
        kind = 'REZIJNI_LISTY'
    elif idx['base'] is not None: kind = 'DATA_POHODA'
    else: return None
    c = Component(kind,sheet)
    for rn,row in rows[pos+1:]:
        if not any(v is not None and str(v).strip() for v in row): continue
        def get(key):
            i = idx[key]
            return row[i] if i is not None and i < len(row) else None
        # A labelled footer without a document is not a business record.
        if norm(get('no')) in ('celkem','soucet','total'): continue
        where = f'{sheet}, řádek {rn}'
        no = text(get('no'))
        if not no: raise ValueError(f'{where}: řádek bez čísla dokladu.')
        dt = date_value(get('date'),where,epoch1904)
        customer = text(get('customer'))
        if kind == 'DATA_POHODA':
            amount = number(get('base'),where+' – základ bez DPH')
            total = number(get('total'),where+' – celkem',True)
            _add(c,no,dict(doc_no=no,doc_date=dt,base_amount=amount,total_amount=total if total is not None else amount,
                          customer=customer,description=text(get('description')),center=text(get('center')).upper(),
                          project=text(get('project')),note=text(get('note'))),where)
        elif kind == 'REZIJNI_LISTY':
            _add(c,no,dict(invoice_no=no,doc_date=dt,due_date=date_value(get('due'),where,epoch1904,True),
                          description=text(get('description')),customer=customer,total_amount=number(get('total'),where),
                          remaining_amount=number(get('remaining'),where),center=text(get('center')).upper()),where)
        else:
            quantity = number(get('quantity'),where+' – množství')
            sales = number(get('sales'),where+' – prodej',True)
            cost = number(get('cost'),where+' – náklad',True)
            profit = number(get('profit'),where+' – zisk',True)
            if profit is None:
                if sales is None or cost is None: raise ValueError(f'{where}: chybí zisk nebo prodej s nákladem.')
                profit = sales-cost
            if sales is not None and cost is not None and abs(profit-(sales-cost)) > 0.02:
                raise ValueError(f'{where}: zisk nesouhlasí s prodejem minus nákladem.')
            item = dict(code=text(get('code')),name=text(get('name')),item_text=text(get('description')),
                        quantity=quantity,profit_unit=profit/quantity if quantity else 0,profit_total=profit,
                        sales_total=sales,cost_total=cost,sales_unit=sales/quantity if sales is not None and quantity else None,
                        cost_unit=cost/quantity if cost is not None and quantity else None,
                        margin_amount=profit,margin_percent=profit/sales*100 if sales is not None and sales > 0 else None)
            if not item['name']: raise ValueError(f'{where}: chybí název produktu.')
            doc = c.records.setdefault(no,dict(doc_no=no,doc_date=dt,customer=customer,profit_total=0.0,items=[]))
            if (doc['doc_date'],doc['customer']) != (dt,customer): raise ValueError(f'{where}: neshodná hlavička DL {no}.')
            doc['items'].append(item); doc['profit_total'] += profit
    if not c.records: raise ValueError(f'{sheet}: tabulka neobsahuje žádný platný doklad.')
    return c


def _profit(sheet,rows,epoch1904,warnings):
    c=Component('ZISK_ZASOBY',sheet); current=None
    for rn,values in rows:
        row=list(values)+[None]*max(0,16-len(values)); where=f'{sheet}, řádek {rn}'
        if 'zisk (zasoby)' in norm(row[1]) or (norm(row[2])=='kod' and norm(row[4])=='nazev'):
            continue
        if norm(row[6]).startswith('ic:') and norm(row[8]).startswith('rok:'):
            continue
        if current is not None and row[7] is not None and all(v is None for i,v in enumerate(row) if i!=7):
            if not current['items']: raise ValueError(f'{where}: text bez předchozí položky.')
            current['items'][-1]['item_text'] += '\n'+text(row[7])
            continue
        if re.fullmatch(r'\d{2}[A-Z]{2}\d+',text(row[4])):
            if current is not None: raise ValueError(f'{where}: u předchozího DL chybí součet.')
            no=text(row[4]); current=dict(doc_no=no,doc_date=date_value(row[2],where,epoch1904),
                                       customer=text(row[5]),profit_total=0.0,items=[])
            _add(c,no,current,where)
        elif current is not None:
            if row[4] is not None and row[9] is not None:
                q=number(row[9],where+' – množství'); pu=number(row[12],where+' – jednotkový zisk'); p=number(row[15],where+' – zisk')
                current['items'].append(dict(code=text(row[2]),name=text(row[4]),item_text=text(row[7]),
                                             quantity=q,profit_unit=pu,profit_total=p))
            elif row[2] is None and row[4] is None and row[15] is not None:
                current['profit_total']=number(row[15],where+' – součet')
                if abs(sum(x['profit_total'] for x in current['items'])-current['profit_total']) > 0.02:
                    warnings.append(f"DL {current['doc_no']}: součet položek se liší od zisku dokladu; použit součet dokladu.")
                current=None
            elif any(v is not None and str(v).strip() for v in row):
                raise ValueError(f'{where}: nerozpoznaný řádek uvnitř dokladu.')
    if current is not None: raise ValueError(f'{sheet}: poslední DL nemá součet.')
    if not c.records: raise ValueError(f'{sheet}: nebyly rozpoznány doklady reportu Zisk (zásoby).')
    return c


def _legacy(sheet,rows):
    c=Component('HISTORICKY_SOUHRN',sheet)
    for rn,values in rows:
        row=list(values)+[None]*max(0,20-len(values)); period=_parse_month_label(row[0])
        if not period: continue
        y,m=period; key=f'{y:04d}-{m:02d}'; where=f'{sheet}, řádek {rn}'
        if not 1900 <= y <= 2200: raise ValueError(f'{where}: neplatný rok.')
        rec={'period':key,'source':'legacy:ZISKY'}
        for col,field in [(1,'profit_total'),(2,'profit_m'),(3,'profit_j'),(5,'profit_h'),(4,'profit_other'),(14,'count_total'),(15,'count_m'),(16,'count_j'),(18,'count_h')]:
            value=number(row[col],where+' – '+field,optional=field!='profit_total')
            if field.startswith('count') and value is not None and (value<0 or not value.is_integer()): raise ValueError(f'{where}: neplatný počet DL.')
            rec[field]=value or 0
        _add(c,key,rec,where)
    if not c.records: raise ValueError(f'{sheet}: chybí měsíční souhrny.')
    return c


def parse_file(path):
    path=Path(path); digest=sha256_file(path); components=[]; warnings=[]
    if path.suffix.lower() == '.csv':
        raw=path.read_bytes()
        try: value=raw.decode('utf-8-sig')
        except UnicodeDecodeError: value=raw.decode('cp1250')
        sample=value[:8192]
        try: dialect=csv.Sniffer().sniff(sample,delimiters=';,\t')
        except csv.Error: raise ValueError('CSV: nelze rozpoznat oddělovač sloupců.') from None
        sheets=[(path.name,list(enumerate(csv.reader(io.StringIO(value),dialect),1)))]; epoch=False
    elif path.suffix.lower() in ('.xlsx','.xlsm'):
        with XlsxReader(path) as reader:
            sheets=[(name,list(reader.rows(name))) for name in reader.sheet_names]
            import xml.etree.ElementTree as ET
            props=ET.fromstring(reader._zip.read('xl/workbook.xml')).find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbookPr')
            epoch=props is not None and props.get('date1904') in ('1','true')
    else: raise ValueError('Podporované formáty jsou XLSX, XLSM a CSV.')
    for sheet,rows in sheets:
        if norm(sheet)=='zisky': c=_legacy(sheet,rows)
        elif any('zisk (zasoby)' in norm(v) for _,row in rows[:8] for v in row): c=_profit(sheet,rows,epoch,warnings)
        else:
            c=_table(sheet,rows,epoch)
            if c is None and norm(sheet) in ('data pohoda','zdroj rezijni listy'):
                raise ValueError(f'{sheet}: chybí povinné sloupce. U DL je nutná částka bez DPH.')
        if c is not None: components.append(c)
    if not components: raise ValueError('Nerozpoznané sloupce. Použijte podporovaný export nebo CSV podle šablony v Importech.')
    if sha256_file(path)!=digest: raise ValueError('Soubor se během kontroly změnil. Načtěte jej znovu.')
    return Source(path,digest,components,warnings)


def fingerprint(con):
    h=hashlib.sha256()
    for table in ('imports','delivery_notes','profit_documents','profit_items','overhead_docs','monthly_summary'):
        for r in con.execute(f'SELECT * FROM {table} ORDER BY rowid'):
            h.update(json.dumps(tuple(r),ensure_ascii=False,allow_nan=False).encode()); h.update(b'\n')
    return h.hexdigest()


def _existing(con,c,key,record):
    table,pk=TABLES[c.kind]
    row=con.execute(f'SELECT * FROM {table} WHERE {pk}=?',(key,)).fetchone()
    if row is None: return 'new'
    if c.kind=='DATA_POHODA' and con.execute("SELECT 1 FROM imports WHERE id=? AND import_type='ZISK_ZASOBY'", (row['source_import_id'],)).fetchone(): return 'new'
    names=[k for k in record if k not in ('items','source')]
    same=all(row[k]==record[k] for k in names)
    if same and c.kind=='ZISK_ZASOBY':
        old=con.execute('SELECT * FROM profit_items WHERE doc_no=? ORDER BY id',(key,)).fetchall()
        same=len(old)==len(record['items']) and all(all(a[k]==b[k] for k in b) for a,b in zip(old,record['items']))
    return 'same' if same else 'changed'


@dataclass
class Batch:
    sources: list
    database_fingerprint: str
    summaries: list
    warnings: list


def preview_imports(db, paths):
    sources=[parse_file(p) for p in paths]; summaries=[]; warnings=[]; seen={}; hashes=set()
    with db.connect() as con:
        con.execute('BEGIN')
        stamp=fingerprint(con)
        for source in sources:
            source.duplicate=source.digest in hashes or bool(con.execute('SELECT 1 FROM imports WHERE file_hash=? AND status=? LIMIT 1',(source.digest,'OK')).fetchone()) and all(_existing(con,c,k,r)=='same' for c in source.components for k,r in c.records.items())
            hashes.add(source.digest); warnings.extend(source.warnings)
            for c in source.components:
                counts={'new':0,'changed':0,'same':0}
                for key,record in c.records.items():
                    if not source.duplicate:
                        identity=(c.kind,key)
                        if identity in seen: raise ValueError(f'{source.path.name}: {key} se opakuje i v souboru {seen[identity]}. Vyberte pouze jeden export téhož dokladu a typu.')
                        seen[identity]=source.path.name
                    counts[_existing(con,c,key,record)]+=1
                summaries.append(dict(file=source.path.name,kind=c.kind,type=TITLES[c.kind],period=', '.join(c.periods),
                                      rows=len(c.records),duplicate=source.duplicate,**counts))
                if c.kind=='ZISK_ZASOBY' and not source.duplicate:
                    delivery_keys={k for s in sources for x in s.components if x.kind=='DATA_POHODA' for k in x.records}
                    missing=sum(key not in delivery_keys and not con.execute('SELECT 1 FROM delivery_notes WHERE doc_no=?',(key,)).fetchone() for key in c.records)
                    if missing: warnings.append(f'{source.path.name}: {missing} DL nemá export obratu. Doplníte jej později; kontrola dat je označí.')
    return Batch(sources,stamp,summaries,warnings)


def _write_record(con,c,key,r,imp):
    table,pk=TABLES[c.kind]; rec={k:v for k,v in r.items() if k!='items'}
    if c.kind!='HISTORICKY_SOUHRN': rec['source_import_id']=imp
    if c.kind=='ZISK_ZASOBY':
        con.execute('INSERT OR IGNORE INTO delivery_notes(doc_no,doc_date,customer,source_import_id) VALUES (?,?,?,?)',
                    (key,r['doc_date'],r['customer'],imp))
        con.execute('DELETE FROM profit_items WHERE doc_no=?',(key,))
    columns=list(rec)
    con.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT({pk}) DO UPDATE SET "+
                ','.join(f'{k}=excluded.{k}' for k in columns if k!=pk),tuple(rec.values()))
    if c.kind=='ZISK_ZASOBY':
        for item in r['items']:
            values=dict(doc_no=key,**item,source_import_id=imp)
            con.execute(f"INSERT INTO profit_items ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",tuple(values.values()))


def apply_imports(db,batch,archive_dir,backup_dir,update_existing=False):
    archives=[]; changed=0; skipped=0; backup=None
    with db.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if fingerprint(con)!=batch.database_fingerprint:
            raise ValueError('Databáze se od náhledu změnila. Spusťte kontrolu importu znovu.')
        for s in batch.sources:
            if sha256_file(s.path)!=s.digest: raise ValueError(f'{s.path.name}: soubor se od náhledu změnil.')
        work=[]
        # Delivery documents first, independent of selected file order.
        for s in batch.sources:
            if s.duplicate: continue
            for c in s.components:
                records=[]
                for key,r in c.records.items():
                    state=_existing(con,c,key,r)
                    if state=='new' or (state=='changed' and update_existing): records.append((key,r))
                    else: skipped+=1
                if records: work.append((s,c,records))
        if not work: return dict(changed=0,skipped=skipped,duplicates=sum(s.duplicate for s in batch.sources),backup=None)
        backup=db.backup(backup_dir)
        # Archive before writing anything, so a failed archive never leaves a half import.
        archive_dir=Path(archive_dir); archive_dir.mkdir(parents=True,exist_ok=True)
        for s in batch.sources:
            if not any(w[0] is s for w in work): continue
            target=archive_dir/(s.digest+s.path.suffix.lower())
            if not target.exists(): shutil.copy2(s.path,target); archives.append(target)
            if sha256_file(target)!=s.digest: raise ValueError('Archivní kopie neodpovídá kontrolovanému souboru.')
        order={'DATA_POHODA':0,'REZIJNI_LISTY':1,'HISTORICKY_SOUHRN':2,'ZISK_ZASOBY':3}
        for s,c,records in sorted(work,key=lambda w:order[w[1].kind]):
            periods=c.periods; y,m=map(int,periods[0].split('-')) if len(periods)==1 else (None,None)
            all_done=len(records)+sum(_existing(con,c,k,r)=='same' for k,r in c.records.items())==len(c.records)
            status='OK' if all_done else 'ČÁSTEČNĚ'
            notes=f"List: {c.sheet}; Období: {', '.join(periods)}; archiv: {s.digest+s.path.suffix.lower()}"
            imp=_register_import(con,c.kind,s.path,s.digest,y,m,len(records),status,notes)
            for key,r in records: _write_record(con,c,key,r,imp); changed+=1
        if con.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Kontrola vazeb databáze neprošla.')
    return dict(changed=changed,skipped=skipped,duplicates=sum(s.duplicate for s in batch.sources),backup=str(backup))
