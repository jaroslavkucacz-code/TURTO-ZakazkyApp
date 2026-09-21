"""One creator/assignee scope for task lists, reminders and direct changes."""
from contextlib import closing


def ensure_schema(con):
    columns = {r[1] for r in con.execute('PRAGMA table_info(tasks)')}
    for column in ('created_by_user_id', 'assigned_user_id'):
        if column not in columns:
            con.execute(f'ALTER TABLE tasks ADD COLUMN {column} INTEGER')
    # IDs retain ownership when a display name is changed. Never rebind an ID.
    for column, name in (('created_by_user_id', 'created_by'), ('assigned_user_id', 'assigned_user')):
        con.execute(f'''UPDATE tasks SET {column}=(SELECT id FROM users WHERE name=tasks.{name})
                        WHERE {column} IS NULL AND EXISTS(SELECT 1 FROM users WHERE name=tasks.{name})''')
        con.execute(f'CREATE INDEX IF NOT EXISTS idx_tasks_{column} ON tasks({column})')
    history_columns = {r[1] for r in con.execute('PRAGMA table_info(action_history)')}
    for field in ('related_task_id','task_owner_id','task_resolver_id'):
        if field not in history_columns:
            con.execute(f'ALTER TABLE action_history ADD COLUMN {field} INTEGER')


def history(con, task_id, user, event, title, detail):
    row = con.execute('SELECT * FROM visible_tasks WHERE id=?',(task_id,)).fetchone()
    if row is None:return
    con.execute('''INSERT INTO action_history(action_id,user_name,event_type,summary,details,related_task_id,task_owner_id,task_resolver_id)
        VALUES(?,?,?,?,?,?,?,?)''',(row['action_id'],user,event,title,detail,task_id,row['created_by_user_id'],row['assigned_user_id']))


def connect(con, session=None):
    """Read-only TEMP views never change persisted records or schema."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'tasks' not in tables:
        return
    con.execute('DROP VIEW IF EXISTS temp.visible_tasks')
    if session is None:
        condition = '1'
    else:
        con.create_function('turto_task_user_id', 0, lambda: session.user_id if session.active else -1)
        con.create_function('turto_task_user_name', 0, lambda: session.name if session.active else '')
        con.create_function('turto_task_read', 0, lambda: int(session.active and session.level('tasks') >= 1))
        condition = '''turto_task_read() AND (
            created_by_user_id=turto_task_user_id() OR assigned_user_id=turto_task_user_id()
            OR (created_by_user_id IS NULL AND created_by=turto_task_user_name() AND created_by<>'')
            OR (assigned_user_id IS NULL AND assigned_user=turto_task_user_name() AND assigned_user<>''))'''
    if session is None:
        con.execute('CREATE TEMP VIEW visible_tasks AS SELECT * FROM main.tasks')
    else:
        fields = []
        for row in con.execute('PRAGMA main.table_info(tasks)'):
            column = row[1]
            if column == 'created_by':fields.append('coalesce(creator.name,t.created_by) AS created_by')
            elif column == 'assigned_user':fields.append('coalesce(resolver.name,t.assigned_user) AS assigned_user')
            else:fields.append('t."'+column+'"')
        con.execute(f'CREATE TEMP VIEW visible_tasks AS SELECT {",".join(fields)} FROM main.tasks t '
                    f'LEFT JOIN users creator ON creator.id=t.created_by_user_id '
                    f'LEFT JOIN users resolver ON resolver.id=t.assigned_user_id WHERE {condition}')
    for view, table in (('visible_action_history','action_history'), ('visible_audit_history','audit_history')):
        if table not in tables:continue
        con.execute(f'DROP VIEW IF EXISTS temp.{view}')
        where = '1'
        if session is not None:
            where = ("coalesce(event_type,'') NOT LIKE 'task_%' OR (turto_task_read() AND "
                     "(EXISTS(SELECT 1 FROM visible_tasks t WHERE t.id=related_task_id) "
                     "OR (related_task_id IS NULL AND user_name=turto_task_user_name()) OR (NOT EXISTS(SELECT 1 FROM main.tasks t WHERE t.id=related_task_id) AND (task_owner_id=turto_task_user_id() OR task_resolver_id=turto_task_user_id()))))") if table == 'action_history' else (
                     "coalesce(entity_type,'')<>'Úkol' OR (turto_task_read() AND "
                     "(EXISTS(SELECT 1 FROM visible_tasks t WHERE t.id=CAST(entity_id AS INTEGER)) "
                     "OR user_name=turto_task_user_name()))")
        con.execute(f'CREATE TEMP VIEW {view} AS SELECT * FROM main.{table} WHERE {where}')
    if session is None:
        return
    visible = lambda row: f'''turto_task_read() AND (
        {row}.created_by_user_id=turto_task_user_id() OR {row}.assigned_user_id=turto_task_user_id()
        OR ({row}.created_by_user_id IS NULL AND {row}.created_by=turto_task_user_name() AND {row}.created_by<>'')
        OR ({row}.assigned_user_id IS NULL AND {row}.assigned_user=turto_task_user_name() AND {row}.assigned_user<>''))'''
    for operation in ('UPDATE', 'DELETE'):
        con.execute(f'''CREATE TEMP TRIGGER task_scope_{operation} BEFORE {operation} ON main.tasks
            WHEN NOT coalesce(({visible('OLD')}),0) BEGIN
            SELECT RAISE(ABORT, 'Tento úkol není určen vám ani jste ho nezadali.'); END''')
    con.execute('''CREATE TEMP TRIGGER task_creator_immutable BEFORE UPDATE ON main.tasks
        WHEN NEW.created_by_user_id IS NOT OLD.created_by_user_id OR NEW.created_by IS NOT OLD.created_by
        BEGIN SELECT RAISE(ABORT, 'Zadavatele úkolu nelze změnit.'); END''')
    con.execute('''CREATE TEMP TRIGGER task_creator_insert BEFORE INSERT ON main.tasks
        WHEN NOT coalesce((NEW.created_by=turto_task_user_name() AND NEW.created_by<>''
            AND (NEW.created_by_user_id IS NULL OR NEW.created_by_user_id=turto_task_user_id())),0)
        BEGIN SELECT RAISE(ABORT, 'Úkol musí být založen pod přihlášeným uživatelem.'); END''')


def save(M, task_id, action_name, due, text, note, assigned, user):
    """Resolve identities and check stale ownership inside the write transaction."""
    with closing(M.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        creator = con.execute('SELECT id,name FROM users WHERE name=? AND active=1', (user,)).fetchone()
        resolver = con.execute('SELECT id,name FROM users WHERE name=? AND active=1', (assigned,)).fetchone()
        if not creator or not resolver:
            raise ValueError('Vyberte aktivního uživatele do pole Řeší.')
        action = con.execute('SELECT MIN(id) FROM actions WHERE lower(trim(name))=lower(trim(?))', (action_name,)).fetchone()[0]
        if action is None:
            raise ValueError('Vyberte existující Akci.')
        editing = bool(task_id)
        if task_id:
            old = con.execute('SELECT * FROM visible_tasks WHERE id=?', (task_id,)).fetchone()
            if old is None:
                raise ValueError('Úkol už neexistuje nebo k němu nemáte přístup.')
            con.execute('''UPDATE tasks SET action_id=?,due_date=?,text=?,note=?,assigned_user=?,assigned_user_id=?
                           WHERE id=?''', (action, due, text, note, resolver['name'], resolver['id'], task_id))
        else:
            task_id = con.execute('''INSERT INTO tasks(action_id,due_date,text,note,created_by,assigned_user,
                                    created_by_user_id,assigned_user_id) VALUES(?,?,?,?,?,?,?,?)''',
                                  (action, due, text, note, creator['name'], resolver['name'], creator['id'], resolver['id'])).lastrowid
        history(con, task_id, user, 'task_edit' if editing else 'task_create',
                'Upravil úkol' if editing else 'Přidal úkol', f'{due} · {text} · Řeší: {assigned}')
        return task_id
