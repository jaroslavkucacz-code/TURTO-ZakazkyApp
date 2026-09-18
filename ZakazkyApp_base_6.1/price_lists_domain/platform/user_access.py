"""Per-user tab access. Job titles describe people; they never grant privileges."""
from __future__ import annotations

from contextlib import closing
from contextvars import ContextVar
from dataclasses import dataclass, field
import json

from . import grouped_navigation as navigation

HIDDEN, READ, EDIT = 0, 1, 2
MODES = ('Skrýt', 'Jen číst', 'Číst i upravovat')
TITLES = {
    'dash': 'Přehled', 'business': 'Obchod', 'actions': 'Ke zpracování',
    'requests': 'Poptávky', 'mivo': 'MIVO', 'offers': 'Přijaté nabídky', 'tasks': 'Úkoly',
    'pricelists': 'Ceníky', 'issued_offers': 'Vydané nabídky', 'received_orders': 'Přijaté objednávky',
    'projects': 'Akce', 'companies': 'Společnosti', 'people': 'Osoby',
    **{key: 'Přehledy / ' + navigation.LABELS[key] for key in navigation.GROUPS['reports']},
    'settings': 'Nastavení CRM', 'help': 'Nápověda',
}
JOB_TITLES = ('Technická podpora', 'Obchodní zástupce', 'Jednatel', 'Ředitel')
_schema_phase = ContextVar('turto_access_schema_phase', default=False)


class AccessDenied(ValueError):
    pass


def ensure_columns(con):
    columns = {r[1] for r in con.execute('PRAGMA table_info(users)')}
    for name, declaration in (('job_title', "TEXT NOT NULL DEFAULT ''"),
                              ('tab_permissions', "TEXT NOT NULL DEFAULT '{}'")):
        if name not in columns:
            con.execute(f'ALTER TABLE users ADD COLUMN {name} {declaration}')


def decode(raw):
    data = json.loads(raw or '{}')
    if not isinstance(data, dict) or any(not isinstance(k, str) or type(v) is not int or v not in (0, 1, 2)
                                         for k, v in data.items()):
        raise ValueError('Neplatné nastavení oprávnění uživatele.')
    return data


@dataclass
class Session:
    user_id: int | None
    name: str
    permissions: dict = field(default_factory=dict)
    active: bool = True

    def level(self, page):
        if not self.active:
            return HIDDEN
        if self.name.strip().casefold() == 'admin':
            return EDIT
        if page in navigation.GROUPS:
            return max(self.level(p) for p in navigation.GROUPS[page])
        return self.permissions.get(page, EDIT)


def session_from_row(row):
    if row is None:
        return Session(None, '', active=False)
    try:
        permissions = decode(row['tab_permissions'])
    except (ValueError, TypeError):
        # Damaged permissions must not silently give full access.
        permissions = dict.fromkeys(TITLES, HIDDEN)
    return Session(row['id'], row['name'], permissions, bool(row['active']))


def refresh_session(M, name=None, con=None):
    session = getattr(M, '_user_access_session', None)
    if name is None and session is None:
        return None  # Schema/bootstrap has no interactive user yet.
    if con is None:
        with closing(M._user_access_connect()) as connection:
            return refresh_session(M, name, connection)
    if name is not None:
        row = con.execute('SELECT id,name,active,tab_permissions FROM users WHERE name=?', (name,)).fetchone()
    else:
        row = con.execute('SELECT id,name,active,tab_permissions FROM users WHERE id=?', (session.user_id,)).fetchone()
    M._user_access_session = session_from_row(row)
    return M._user_access_session


def level(M, page, fresh=False):
    session = refresh_session(M) if fresh else getattr(M, '_user_access_session', None)
    return session.level(page) if session else EDIT


def require(M, page, write=True):
    if level(M, page, fresh=True) < (EDIT if write else READ):
        title = TITLES.get(page, navigation.LABELS.get(page, page))
        raise AccessDenied(f'Záložka „{title}“: nemáte oprávnění ' + ('provádět změny.' if write else 'k zobrazení.'))


def allowed(M, parent, page, write=True):
    try:
        require(M, page, write)
        return True
    except AccessDenied as exc:
        M.messagebox.showwarning('Oprávnění', str(exc), parent=parent)
        return False


def require_admin(M):
    session = refresh_session(M)
    if session is None or session.name.strip().casefold() != 'admin' or not session.active:
        raise AccessDenied('Funkce a oprávnění uživatelů může měnit pouze ADMIN.')


def profile(M, uid):
    with closing(M.db()) as con:
        row = con.execute('SELECT id,name,job_title,tab_permissions FROM users WHERE id=?', (uid,)).fetchone()
        if row is None:
            raise ValueError('Uživatel už neexistuje.')
        return dict(row)


def save_profile(M, uid, job_title, permissions, expected):
    require_admin(M)
    data = decode(json.dumps(permissions, ensure_ascii=False))
    # Preserve unknown future keys when editing an older client.
    encoded = json.dumps({k: v for k, v in data.items() if v != EDIT}, ensure_ascii=False, sort_keys=True)
    with closing(M.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        current = con.execute('SELECT job_title,tab_permissions FROM users WHERE id=?', (uid,)).fetchone()
        if current is None:
            raise ValueError('Uživatel už neexistuje.')
        if tuple(current) != tuple(expected):
            raise ValueError('Nastavení mezitím změnil jiný uživatel. Otevřete okno znovu.')
        con.execute('UPDATE users SET job_title=?,tab_permissions=? WHERE id=?', (job_title.strip(), encoded, uid))


def apply(M):
    """Final runtime owner: keep guards outside legacy wrappers and shortcuts."""
    if getattr(M, '_user_access_834', False):
        return
    from .access_database import protect_connection
    from .access_controls import install_controls, refresh_controls
    M._user_access_connect = M.db
    M._user_access_session = None

    def connect():
        con = M._user_access_connect()
        if _schema_phase.get():
            return con
        session = refresh_session(M, con=con)
        if session is not None:
            protect_connection(con, session)
        return con
    M.db = connect

    previous_schema = M.ensure_schema
    def schema():
        # Only the synchronous schema owner performs additive startup upgrades.
        # An ADMIN login dialog must never temporarily disable another session's guards.
        token = _schema_phase.set(True)
        try:
            return previous_schema()
        finally:
            _schema_phase.reset(token)
    M.ensure_schema = schema

    def visible(app, key):
        return level(M, key) >= READ
    M.App._tab_visible = visible

    def sync(app):
        refresh_session(M, app.active_user.get())
        navigation.arrange(app)
        refresh_controls(M, app)
        key = getattr(app, '_current_page', 'dash')
        if key not in app.tabs or not visible(app, key):
            key = next((k for k in app.tabs if visible(app, k)), None)
            if key is not None:
                app.show_page(key)
            else:
                if not hasattr(app, '_no_access_page'):
                    app._no_access_page = M.ttk.Frame(app.pages, style='App.TFrame')
                    M.ttk.Label(app._no_access_page, text='Nemáte zpřístupněnou žádnou záložku. Obraťte se na správce.').pack(padx=20, pady=20)
                app._no_access_page.grid(row=0, column=0, sticky='nsew')
                app._no_access_page.tkraise()
                app._current_page = None
                navigation.activate(app, None)
    M.App.refresh_user_access = sync

    previous_build = M.App.build
    def build(app, *args, **kwargs):
        result = previous_build(app, *args, **kwargs)
        sync(app)
        return result
    M.App.build = build

    previous_select = M.App.select_user
    def select(app, *args, **kwargs):
        try:
            return previous_select(app, *args, **kwargs)
        finally:
            sync(app)
    M.App.select_user = select

    previous_show = M.App.show_page
    def show(app, key, *args, **kwargs):
        key = navigation.resolve_page(app, key)
        # Navigation uses the profile loaded on selection; mutation guards always
        # read a fresh profile. Hundreds of tab clicks must not open hundreds of DBs.
        if level(M, key) < READ:
            M.messagebox.showwarning('Oprávnění', f'Záložka „{TITLES.get(key, key)}“ není pro tohoto uživatele dostupná.', parent=app)
            return
        result = previous_show(app, key, *args, **kwargs)
        refresh_controls(M, app)
        return result
    M.App.show_page = show
    install_controls(M)
    M._user_access_834 = True
