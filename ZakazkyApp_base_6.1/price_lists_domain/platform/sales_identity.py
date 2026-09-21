"""Stable CRM salesperson identities and their Pohoda cost centers."""
from contextlib import closing
import unicodedata

PEOPLE = (('J', 'Jiří Cír', ('J', 'Jirka', 'Jiří Cír')),
          ('H', 'Jan Mayer', ('H', 'Honza', 'Jan Mayer')),
          ('M', 'Milan Soukup', ('M', 'Milan', 'Milan Soukup')))
CENTER_NAMES = {code: name for code, name, _ in PEOPLE}


def key(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(text or ''))
                           if not unicodedata.combining(c)).casefold().split())


def personal_key(text):
    parts=key(text).split()
    while parts and parts[0].rstrip('.') in {'ing','mgr','bc','judr','mudr','phdr','rndr','doc','prof'}:
        parts.pop(0)
    return ' '.join(parts)


def ensure_schema(con):
    for table, columns in {
        'users': (('salesperson_id', 'INTEGER'), ('person_id', 'INTEGER')),
        'people': (('pohoda_center', "TEXT NOT NULL DEFAULT ''"),),
        'salespeople': (('pohoda_center', "TEXT NOT NULL DEFAULT ''"), ('person_id', 'INTEGER'),
                        ('canonical_id', 'INTEGER')),
    }.items():
        existing = {r[1] for r in con.execute(f'PRAGMA table_info({table})')}
        for name, declaration in columns:
            if name not in existing:
                con.execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    con.execute('''CREATE TABLE IF NOT EXISTS company_salespeople(
        company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
        salesperson_id INTEGER NOT NULL REFERENCES salespeople(id),
        assigned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,assigned_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(company_id,salesperson_id))''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_company_salesperson ON company_salespeople(salesperson_id,company_id)')


def migrate(con):
    """One-time alias consolidation; preserve IDs, history, contacts and privileges."""
    if con.execute("SELECT 1 FROM settings WHERE key='migration_sales_identity_840'").fetchone():
        link_contacts(con)
        return
    for center, name, aliases in PEOPLE:
        accepted = {key(a) for a in aliases}
        matches = [dict(r) for r in con.execute('SELECT * FROM salespeople') if key(r['name']) in accepted]
        primary = next((r for r in matches if r['name'] == name), None)
        primary = primary or next((r for r in matches if r['active']), None) or next(iter(matches), None)
        if primary is None:
            sid = con.execute('INSERT INTO salespeople(name) VALUES(?)', (name,)).lastrowid
        else:
            sid = primary['id']
            con.execute('UPDATE salespeople SET name=?,active=1 WHERE id=?', (name, sid))
        for alias in matches:
            if alias['id'] == sid:
                continue
            con.execute('UPDATE actions SET salesperson_id=? WHERE salesperson_id=?', (sid, alias['id']))
            con.execute('UPDATE users SET salesperson_id=? WHERE salesperson_id=?', (sid, alias['id']))
            con.execute('''INSERT OR IGNORE INTO company_salespeople(company_id,salesperson_id,assigned_at,assigned_by)
                SELECT company_id,?,assigned_at,assigned_by FROM company_salespeople WHERE salesperson_id=?''', (sid, alias['id']))
            con.execute('DELETE FROM company_salespeople WHERE salesperson_id=?', (alias['id'],))
            con.execute("UPDATE salespeople SET active=0,canonical_id=?,pohoda_center='' WHERE id=?", (sid, alias['id']))
        # Only a full personal name identifies a directory contact, not a single letter.
        contacts = [dict(r) for r in con.execute('SELECT * FROM people') if key(r['name']) == key(name)]
        person = next((p for p in contacts if p['active']), None) or next(iter(contacts), None)
        if person is None:
            pid = con.execute("""INSERT INTO people(name,email,role,pohoda_center)
                VALUES(?,'','Obchodní zástupce',?)""", (name, center)).lastrowid
        else:
            pid = person['id']
            con.execute('UPDATE people SET pohoda_center=? WHERE id=?', (center, pid))
        con.execute('UPDATE salespeople SET pohoda_center=?,person_id=?,canonical_id=NULL WHERE id=?', (center, pid, sid))
        for user in con.execute('SELECT id,name,salesperson_id FROM users').fetchall():
            if key(user['name']) in accepted and user['salesperson_id'] is None:
                con.execute("""UPDATE users SET salesperson_id=?,person_id=?,
                    job_title=CASE WHEN trim(job_title)='' THEN 'Obchodní zástupce' ELSE job_title END WHERE id=?""", (sid, pid, user['id']))
    con.execute("INSERT INTO settings(key,value) VALUES('migration_sales_identity_840','1')")
    link_contacts(con)


def link_contacts(con):
    """Directory contacts own personal data; stable sales IDs own business links."""
    if not con.execute("SELECT 1 FROM settings WHERE key='migration_sales_contacts_845'").fetchone():
        people=[dict(r) for r in con.execute('SELECT p.*,c.official_name company FROM people p LEFT JOIN companies c ON c.id=p.company_id')]
        for rep in [dict(r) for r in con.execute('SELECT * FROM salespeople WHERE canonical_id IS NULL')]:
            current=next((p for p in people if p['id']==rep['person_id']),None)
            # A unique TURTO contact may replace an empty automatically seeded
            # contact. Ambiguous or already populated links require an explicit choice.
            candidates=[p for p in people if personal_key(p['name'])==personal_key(rep['name']) and key(p.get('company')).startswith('turto') and p['active']]
            if (current is None or (not current.get('email') and not current.get('phone') and not current.get('company_id'))) and len(candidates)==1:
                current=candidates[0]
                con.execute('UPDATE salespeople SET person_id=? WHERE id=?',(current['id'],rep['id']))
            if current is None:
                pid=con.execute("INSERT INTO people(name,email,role,active) VALUES(?,'','Obchodní zástupce',?)",(rep['name'],rep['active'])).lastrowid
                con.execute('UPDATE salespeople SET person_id=? WHERE id=?',(pid,rep['id']))
            elif current['name']!=rep['name']:
                con.execute('UPDATE salespeople SET name=? WHERE id=?',(current['name'],rep['id']))
        con.execute('UPDATE users SET person_id=(SELECT person_id FROM salespeople WHERE id=users.salesperson_id) WHERE salesperson_id IS NOT NULL')
        con.execute("INSERT INTO settings(key,value) VALUES('migration_sales_contacts_845','1')")
    # Conditions make bidirectional name synchronization safe with SQLite's
    # recursive_triggers either on or off, including edits from the address book.
    con.execute('''CREATE TRIGGER IF NOT EXISTS sales_contact_name_845 AFTER UPDATE OF name ON people
        BEGIN UPDATE salespeople SET name=NEW.name WHERE person_id=NEW.id AND canonical_id IS NULL AND name<>NEW.name; END''')
    con.execute('''CREATE TRIGGER IF NOT EXISTS sales_person_name_845 AFTER UPDATE OF name ON salespeople
        WHEN NEW.canonical_id IS NULL BEGIN
        UPDATE people SET name=NEW.name WHERE id=NEW.person_id AND name<>NEW.name; END''')
    con.execute('''CREATE TRIGGER IF NOT EXISTS sales_contact_link_845 AFTER UPDATE OF person_id ON salespeople
        WHEN NEW.canonical_id IS NULL BEGIN
        UPDATE users SET person_id=NEW.person_id WHERE salesperson_id=NEW.id; END''')


def choices(con):
    rows = [dict(r) for r in con.execute('''SELECT s.id,s.name,s.pohoda_center,s.person_id
        FROM salespeople s WHERE s.active=1 AND s.canonical_id IS NULL ORDER BY s.name COLLATE CZECH''')]
    from .sales_centers import current
    centers=current(con)
    for row in rows:row['pohoda_center']=centers.get(row['id'],'')
    return rows


def label(row):
    return row['name'] + (f" · středisko {row['pohoda_center']}" if row['pohoda_center'] else '')


def default_salesperson(M):
    session = getattr(M, '_user_access_session', None)
    if not session or not session.active:
        return None
    with closing(M.db()) as con:
        row = con.execute('''SELECT s.id FROM users u JOIN salespeople s ON s.id=u.salesperson_id
            WHERE u.id=? AND u.active=1 AND s.active=1 AND s.canonical_id IS NULL''', (session.user_id,)).fetchone()
        return row[0] if row else None
