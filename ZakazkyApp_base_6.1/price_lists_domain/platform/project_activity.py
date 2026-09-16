"""Last business activity per project, recorded in the writing transaction.

Existing history supplies the baseline. Small SQLite triggers retain new edits,
deletions and both sides of a reassignment, including writes from other clients.
Reading/filtering tables and editing unrelated master data are not activities.
"""
from __future__ import annotations


def columns(con, table):
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def sources(con):
    """Known project-owned records: (columns, project SQL, historical timestamps)."""
    tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    schema = {table: columns(con, table) for table in tables if table in {
        'projects', 'actions', 'requests', 'tasks', 'action_history', 'supplier_offers',
        'supplier_offer_items', 'offer_source_attachments',
        'business_documents', 'business_document_items', 'business_document_history',
        'business_document_revisions'}}
    result = {}
    if 'projects' not in schema:
        return result
    action = '(SELECT a.project_id FROM actions a WHERE a.id={}.action_id)'
    can_action = 'project_id' in schema.get('actions', ())
    if can_action:
        result['actions'] = (schema['actions'], '{r}.project_id', ('updated_at','created_at','created_date'))
    result['projects'] = (schema['projects'], '{r}.id', ('updated_at','archived_at','created_at'))
    for table, times in (
        ('requests', ('updated_at','archived_at','created_at','received_date','asked_date')),
        ('tasks', ('updated_at','done_at','archived_at','created_at')),
        ('action_history', ('created_at','event_date','date_created')),
    ):
        if can_action and 'action_id' in schema.get(table, ()):
            result[table] = (schema[table], action.format('{r}'), times)
    for table, times in (
        ('supplier_offers', ('updated_at','archived_at','imported_at','created_at','offer_date')),
        ('business_documents', ('updated_at','archived_at','sent_at','accepted_at','rejected_at','created_at')),
    ):
        cols = schema.get(table, set())
        links = []
        if table == 'supplier_offers' and 'request_id' in cols and 'requests' in result:
            links.append('(SELECT a.project_id FROM requests q JOIN actions a ON a.id=q.action_id WHERE q.id={r}.request_id)')
        if 'project_id' in cols:
            links.append('{r}.project_id')
        # A bare legacy supplier action_id is NOT an explicit assignment in the
        # current model. Requests/direct projects are authoritative (v637).
        if can_action and 'action_id' in cols and (table == 'business_documents' or not links):
            links.append(action.format('{r}'))
        if links:
            link = links[0] if len(links)==1 else 'COALESCE('+','.join(links)+')'
            result[table] = (cols, link, times)
    for table, parent, key, times in (
        ('supplier_offer_items','supplier_offers','offer_id',('updated_at','created_at')),
        ('offer_source_attachments','supplier_offers','offer_id',('imported_at',)),
        ('business_document_items','business_documents','document_id',('updated_at','created_at')),
        ('business_document_history','business_documents','document_id',('created_at',)),
        ('business_document_revisions','business_documents','document_id',('created_at',)),
    ):
        if key in schema.get(table, ()) and parent in result:
            link = result[parent][1].format(r='owner')
            result[table] = (schema[table], f'(SELECT {link} FROM {parent} owner WHERE owner.id={{r}}.{key})', times)
    return result


def timestamp(alias, cols, candidates):
    # datetime() normalizes ISO T/space/offset forms BEFORE MAX; lexical MAX of
    # raw strings wrongly puts 01:00 with T after 23:00 with a space.
    parts = []
    for name in candidates:
        if name not in cols:
            continue
        value = f'datetime({alias}."{name}")'
        if name.endswith('_date'):
            value = f"CASE WHEN date({alias}.\"{name}\")<=date('now','localtime') THEN {value} END"
        parts.append(f"coalesce({value},'')")
    if not parts:
        return 'NULL'
    expr = parts[0] if len(parts)==1 else 'MAX('+','.join(parts)+')'
    return f"NULLIF({expr},'')"


def activity_union(con):
    definitions = sources(con)
    parts = [f'SELECT {link.format(r="s")} project_id,{timestamp("s", cols, times)} activity_at FROM "{table}" s'
             for table, (cols, link, times) in definitions.items() if cols.intersection(times)]
    if columns(con, 'project_activity'):
        parts.append('SELECT project_id,last_activity_at FROM project_activity')
    audit = columns(con, 'audit_history')
    if {'entity_type','entity_id','created_at'} <= audit:
        for entity, table in (('Akce','projects'), ('Příležitost','actions'), ('Poptávka','requests'),
                              ('Úkol','tasks'), ('Vydaná nabídka','business_documents')):
            if table in definitions:
                link = definitions[table][1].format(r='s')
                parts.append(f"SELECT {link},datetime(h.created_at) FROM audit_history h "
                             f"JOIN {table} s ON s.id=CAST(h.entity_id AS INTEGER) WHERE h.entity_type='{entity}'")
    return ' UNION ALL '.join(parts) or 'SELECT NULL project_id,NULL activity_at WHERE 0'


def ensure_schema(con):
    if not columns(con, 'projects'):
        return
    con.execute('''CREATE TABLE IF NOT EXISTS project_activity(
        project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        last_activity_at TEXT NOT NULL)''')
    existing = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for table, (cols, link, _) in sources(con).items():
        # Do not stamp a project for metadata-only writes or a no-op UPDATE.
        business_cols = sorted(cols - {'id','created_at','updated_at','updated_by','created_by',
                                        'imported_at','archived_at','archived_by'})
        changed = ' OR '.join(f'OLD."{c}" IS NOT NEW."{c}"' for c in business_cols) or '0'
        for event in ('INSERT','UPDATE','DELETE'):
            if table == 'projects' and event == 'DELETE':
                continue
            name = f'project_activity_823_{table}_{event.lower()}'
            if name in existing:
                continue
            rows = ('OLD','NEW') if event == 'UPDATE' else ('OLD',) if event == 'DELETE' else ('NEW',)
            statements = []
            for row in rows:
                target = link.format(r=row)
                statements.append(f'''INSERT INTO project_activity(project_id,last_activity_at)
                    SELECT p.id,strftime('%Y-%m-%d %H:%M:%f','now') FROM projects p WHERE p.id={target}
                    ON CONFLICT(project_id) DO UPDATE SET last_activity_at=excluded.last_activity_at
                    WHERE excluded.last_activity_at>project_activity.last_activity_at;''')
            when = f'WHEN ({changed})' if event == 'UPDATE' else ''
            timing = 'BEFORE' if event == 'DELETE' else 'AFTER'
            con.execute(f'CREATE TRIGGER "{name}" {timing} {event} ON "{table}" {when} BEGIN '+''.join(statements)+' END')
