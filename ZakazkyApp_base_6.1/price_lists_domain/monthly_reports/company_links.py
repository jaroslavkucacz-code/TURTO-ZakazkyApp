"""Durable POHODA name aliases owned by the CRM database, not the import store."""
from __future__ import annotations

import re
import unicodedata
from contextlib import closing

SOURCE = 'pohoda'
STATUSES = {
    'auto': 'Automaticky', 'manual': 'Ručně', 'ignored': 'Nepárovat',
    'ambiguous': 'Více shod – vyberte', 'unmatched': 'Bez shody',
    'missing': 'Společnost již neexistuje', 'empty': 'Prázdný název',
}


def name_key(value):
    """Keep accents, words and numbers; normalize case, spaces and legal suffixes.

    No substring/fuzzy matching and no removal of legal forms or accents. In
    particular AB and A B, and ABC a.s. and ABC s.r.o., remain different names.
    """
    text = unicodedata.normalize('NFKC', str(value or '')).casefold().strip()
    text = re.sub(r'\s+', ' ', text)
    for suffix, replacement in ((r's\s*\.?\s*r\s*\.?\s*o\.?', 's.r.o.'),
                                (r'a\s*\.?\s*s\.?', 'a.s.'),
                                (r'v\s*\.?\s*o\s*\.?\s*s\.?', 'v.o.s.'),
                                (r'k\s*\.?\s*s\.?', 'k.s.')):
        text = re.sub(r'(?:[\s,]+)' + suffix + r'$', ' ' + replacement, text)
    return text


def ensure_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS report_company_links(
        source_system TEXT NOT NULL,
        source_key TEXT NOT NULL,
        source_name TEXT NOT NULL,
        company_id INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        mode TEXT NOT NULL CHECK(mode IN ('auto','manual','ignored')),
        updated_by TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(source_system,source_key)
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_report_company_links_company ON report_company_links(company_id)')


def canonical_id(companies, cid):
    seen = set()
    while cid in companies and cid not in seen:
        seen.add(cid)
        target = companies[cid].get('merged_into_company_id')
        if not target:
            return cid
        cid = target
    return None


class CompanyLinks:
    def __init__(self, connect, reports, user='', can_write=None):
        self.connect, self.reports, self.user = connect, reports, user
        self.can_write = can_write or (lambda: True)

    def imported_names(self):
        # Include suppliers in overhead imports, and customers with no DL yet.
        rows = self.reports.query('''SELECT customer FROM delivery_notes
            UNION SELECT customer FROM profit_documents
            UNION SELECT customer FROM invoice_customer_snapshots
            UNION SELECT customer FROM overhead_docs''')
        return sorted({r[0] for r in rows if name_key(r[0])}, key=str.casefold)

    def companies(self):
        with closing(self.connect()) as con, con:
            return {r['id']: dict(r) for r in con.execute(
                'SELECT id,official_name,ico,address,active,merged_into_company_id FROM companies')}

    def resolve(self, names=None):
        """Return one row per original spelling, saving only unique new matches.

        Existing links are identities: a rename or a later duplicate must not
        silently reassign an already linked import. Explicit exclusions and
        manual assignments always win over automatic matching.
        """
        names = self.imported_names() if names is None else list(dict.fromkeys(names))
        writable = self.can_write()
        companies = self.companies()
        candidates = {}
        for cid, company in companies.items():
            key = name_key(company['official_name'])
            target = canonical_id(companies, cid)
            if key and target:
                candidates.setdefault(key, set()).add(target)
        result = {}
        with closing(self.connect()) as con, con:
            saved = {r['source_key']: dict(r) for r in con.execute(
                'SELECT * FROM report_company_links WHERE source_system=?', (SOURCE,))}
            for name in names:
                key = name_key(name)
                choices = sorted(candidates.get(key, ()))
                link = saved.get(key)
                if writable and key and link is None and len(choices) == 1:
                    # Never overwrite a manual decision made by another client.
                    con.execute('''INSERT OR IGNORE INTO report_company_links
                        (source_system,source_key,source_name,company_id,mode,updated_by)
                        VALUES(?,?,?,?,'auto',?)''', (SOURCE, key, name, choices[0], self.user))
                    link = dict(con.execute('''SELECT * FROM report_company_links
                        WHERE source_system=? AND source_key=?''', (SOURCE, key)).fetchone())
                    saved[key] = link
                cid = canonical_id(companies, link['company_id']) if link else None
                if not key:
                    status = 'empty'
                elif link:
                    status = 'ignored' if link['mode'] == 'ignored' else link['mode'] if cid else 'missing'
                else:
                    status = 'ambiguous' if len(choices) > 1 else 'unmatched'
                result[name] = dict(source_name=name, source_key=key, company_id=cid,
                                    company=companies.get(cid), status=status,
                                    status_text=STATUSES[status], candidates=choices,
                                    token=self._token(link))
        return result

    @staticmethod
    def _token(row):
        return (row['company_id'], row['mode'], row['updated_by'], row['updated_at']) if row else None

    def save(self, source_name, company_id, mode, expected):
        """Explicit manual assignment/exclusion/reset; stale forms cannot overwrite."""
        if not self.can_write():
            raise ValueError('Párování firem je pro tohoto uživatele jen pro čtení.')
        key = name_key(source_name)
        if not key or mode not in ('manual', 'ignored', 'reset'):
            raise ValueError('Vyberte neprázdný název z importu a platný způsob párování.')
        with closing(self.connect()) as con, con:
            # Serialize the read/compare/write across CRM clients.
            con.execute('BEGIN IMMEDIATE')
            current = con.execute('''SELECT * FROM report_company_links
                WHERE source_system=? AND source_key=?''', (SOURCE, key)).fetchone()
            if self._token(current) != expected:
                raise ValueError('Párování mezitím změnil jiný uživatel. Obnovte seznam a zkontrolujte novou hodnotu.')
            if mode == 'reset':
                con.execute('DELETE FROM report_company_links WHERE source_system=? AND source_key=?', (SOURCE, key))
                return
            if mode == 'manual':
                company = con.execute('SELECT * FROM companies WHERE id=?', (company_id,)).fetchone()
                if company is None or company['merged_into_company_id']:
                    raise ValueError('Vyberte existující společnost z adresáře. Sloučenou společnost nelze přiřadit.')
            else:
                company_id = None
            con.execute('''INSERT INTO report_company_links
                (source_system,source_key,source_name,company_id,mode,updated_by)
                VALUES(?,?,?,?,?,?) ON CONFLICT(source_system,source_key) DO UPDATE SET
                company_id=excluded.company_id,mode=excluded.mode,updated_by=excluded.updated_by,
                updated_at=strftime('%Y-%m-%d %H:%M:%f','now')''',
                (SOURCE, key, source_name, company_id, mode, self.user))

    def documents(self, company_id):
        """CRM documents keep their own types/currencies; never add them to revenue."""
        with closing(self.connect()) as con, con:
            return [dict(r) for r in con.execute('''SELECT id,document_type,document_number,
                issue_date,status,subtotal_net,currency,offer_subject,archived
                FROM business_documents WHERE company_id=?
                AND document_type IN ('issued_offer','received_order')
                ORDER BY issue_date DESC,id DESC''', (company_id,))]
