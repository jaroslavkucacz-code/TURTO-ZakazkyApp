"""Pohoda center ownership is dated business data, never a person's initials."""
from contextlib import closing
from datetime import date
from pathlib import Path
import re
from . import user_access as access


def ensure_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS sales_center_assignments(
        id INTEGER PRIMARY KEY, center TEXT NOT NULL,
        salesperson_id INTEGER REFERENCES salespeople(id),
        valid_from TEXT NOT NULL, valid_to TEXT,
        created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(center,valid_from), CHECK(valid_to IS NULL OR valid_to>valid_from))''')
    if not con.execute("SELECT 1 FROM settings WHERE key='migration_sales_centers_841'").fetchone():
        for r in con.execute("SELECT id,pohoda_center FROM salespeople WHERE canonical_id IS NULL AND trim(pohoda_center)<>''").fetchall():
            con.execute('INSERT INTO sales_center_assignments(center,salesperson_id,valid_from) VALUES(?,?,?)',
                        (r['pohoda_center'].strip().upper(),r['id'],'0001-01-01'))
        con.execute("INSERT INTO settings(key,value) VALUES('migration_sales_centers_841','1')")


def history(con):
    return [dict(r) for r in con.execute('''SELECT a.*,s.name,s.active FROM sales_center_assignments a
        LEFT JOIN salespeople s ON s.id=a.salesperson_id ORDER BY a.center,a.valid_from''')]


def snapshot(M, expected_database=None):
    if expected_database is not None and Path(M.DB).resolve()!=Path(expected_database).resolve():
        raise ValueError('Databáze se změnila. Otevřete přehled znovu.')
    with closing(M.db()) as con:return history(con)


def current(con, when=None):
    when = when or date.today().isoformat()
    out = {}
    for r in history(con):
        if r['salesperson_id'] and r['valid_from']<=when and (not r['valid_to'] or when<r['valid_to']):
            out.setdefault(r['salesperson_id'],[]).append(r['center'])
    return {sid:', '.join(codes) for sid,codes in out.items()}


def assign(M, center, salesperson_id, valid_from, expected):
    access.require(M,'settings')
    center = str(center or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{0,19}',center):
        raise ValueError('Vyplňte kód střediska Pohody, například J, H, M nebo nový kód.')
    try: valid_from = date.fromisoformat(valid_from).isoformat()
    except (ValueError,TypeError):raise ValueError('Vyplňte platné datum účinnosti změny.')
    with closing(M.db()) as con,con:
        con.execute('BEGIN IMMEDIATE')
        rows = [r for r in history(con) if r['center']==center]
        signature = [(r['id'],r['salesperson_id'],r['valid_from'],r['valid_to']) for r in rows]
        if signature != expected:raise ValueError('Přiřazení mezitím změnil jiný uživatel. Obnovte přehled.')
        if salesperson_id is not None:
            person=con.execute('SELECT active,canonical_id FROM salespeople WHERE id=?',(salesperson_id,)).fetchone()
            if not person or not person['active'] or person['canonical_id'] is not None:
                raise ValueError('Vyberte aktivního obchodního zástupce.')
        if rows and valid_from<=rows[-1]['valid_from']:
            raise ValueError('Datum musí být pozdější než poslední změna tohoto střediska. Starší historii nelze přepsat.')
        if rows and rows[-1]['salesperson_id']==salesperson_id:raise ValueError('Středisko už má toto přiřazení.')
        if rows:
            con.execute('UPDATE sales_center_assignments SET valid_to=? WHERE id=?',(valid_from,rows[-1]['id']))
        session=getattr(M,'_user_access_session',None)
        con.execute('INSERT INTO sales_center_assignments(center,salesperson_id,valid_from,created_by) VALUES(?,?,?,?)',
                    (center,salesperson_id,valid_from,session.name if session else ''))


def save_person(M, sid, name, active, expected=None, contact=None):
    access.require(M,'settings')
    name=str(name or '').strip()
    if not name:raise ValueError('Vyplňte jméno obchodního zástupce.')
    with closing(M.db()) as con,con:
        con.execute('BEGIN IMMEDIATE')
        if contact is not None:
            access.require(M,'people')
            pid=contact.get('person_id')
            person=con.execute('SELECT name,email,phone FROM people WHERE id=?',(pid,)).fetchone() if pid else None
            if pid and not person:raise ValueError('Kontaktní osoba již neexistuje.')
            if pid and con.execute('SELECT 1 FROM salespeople WHERE person_id=? AND id<>? AND canonical_id IS NULL',(pid,sid or -1)).fetchone():
                raise ValueError('Tato osoba je již propojená s jiným obchodním zástupcem.')
            if person and tuple(person)!=tuple(contact.get('expected',())):
                raise ValueError('Kontaktní údaje se mezitím změnily. Obnovte dialog.')
        if con.execute('SELECT 1 FROM salespeople WHERE lower(trim(name))=lower(?) AND id<>?',(name,sid or -1)).fetchone():
            raise ValueError('Obchodník se stejným jménem už existuje; případně znovu aktivujte původní záznam.')
        if sid:
            old=con.execute('SELECT name,active FROM salespeople WHERE id=? AND canonical_id IS NULL',(sid,)).fetchone()
            if not old or tuple(old)!=expected:raise ValueError('Obchodník byl mezitím změněn. Obnovte přehled.')
            if contact is not None:
                if not pid:pid=con.execute("INSERT INTO people(name,email,role) VALUES(?,'','Obchodní zástupce')",(name,)).lastrowid
                con.execute('UPDATE salespeople SET person_id=? WHERE id=?',(pid,sid))
            con.execute('UPDATE salespeople SET name=?,active=? WHERE id=?',(name,int(active),sid))
        else:
            access.require(M,'people')
            if contact is None:
                matches=con.execute('SELECT id FROM people WHERE lower(trim(name))=lower(?) ORDER BY active DESC,id',(name,)).fetchall()
                if len(matches)>1:raise ValueError('V adresáři je více osob stejného jména. Vyberte konkrétní osobu.')
                pid=matches[0][0] if matches else None
            if not pid:pid=con.execute("INSERT INTO people(name,email,role) VALUES(?,'','Obchodní zástupce')",(name,)).lastrowid
            sid=con.execute('INSERT INTO salespeople(name,active) VALUES(?,?)',(name,int(active))).lastrowid
            con.execute('UPDATE salespeople SET person_id=? WHERE id=?',(pid,sid))
        if contact is not None:
            email=str(contact.get('email') or '').strip()
            phone=str(contact.get('phone') or '').strip()
            if email and con.execute('SELECT 1 FROM people WHERE lower(email)=lower(?) AND id<>?',(email,pid)).fetchone():
                raise ValueError('Tento e-mail již má jiná osoba. Vyberte její existující záznam v adresáři.')
            con.execute('UPDATE salespeople SET person_id=? WHERE id=?',(pid,sid))
            con.execute('UPDATE people SET name=?,email=?,phone=? WHERE id=?',(name,email,phone,pid))
        return sid
