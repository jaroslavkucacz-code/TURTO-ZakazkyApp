"""Request mail attempts: a draft is not evidence of sending or delivery."""
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

PROPERTY = 'http://schemas.microsoft.com/mapi/string/{00020329-0000-0000-C000-000000000046}/TurtoRequestToken'


def ensure_schema(con):
    con.execute('''CREATE TABLE IF NOT EXISTS request_mail_attempts(
        token TEXT PRIMARY KEY,request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
        created_by_user_id INTEGER,created_by TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
        state TEXT NOT NULL DEFAULT 'unknown' CHECK(state IN ('draft','sent','unknown')),
        draft_entry_id TEXT NOT NULL DEFAULT '',store_id TEXT NOT NULL DEFAULT '',
        sent_at TEXT NOT NULL DEFAULT '',checked_at TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '')''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_request_mail_attempts_request ON request_mail_attempts(request_id,created_at)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_request_mail_attempts_pending ON request_mail_attempts(created_by_user_id,state,checked_at)')


def begin(M, request_id, user):
    from .access_controls import _request_page
    from .user_access import require
    require(M, _request_page(M, rid=request_id))
    token = str(uuid.uuid4())
    with closing(M.db()) as con, con:
        uid = con.execute('SELECT id FROM users WHERE name=? AND active=1', (user,)).fetchone()
        if not uid:raise ValueError('Přihlášený uživatel již není aktivní.')
        con.execute('''INSERT INTO request_mail_attempts(token,request_id,created_by_user_id,created_by)
            VALUES(?,?,?,?)''', (token, request_id, uid[0], user))
    return token


def draft_created(M, token, metadata):
    with closing(M.db()) as con, con:
        con.execute('''UPDATE request_mail_attempts SET state=?,draft_entry_id=?,store_id=?,detail=?
            WHERE token=? AND state<>'sent' ''',
            ('draft' if metadata.get('saved') else 'unknown', metadata.get('entry_id', ''), metadata.get('store_id', ''),
             '' if metadata.get('saved') else 'Koncept nelze propojit s klasickým Outlookem.', token))


def pending(M, user_id):
    with closing(M.db()) as con:
        return [dict(r) for r in con.execute('''SELECT * FROM request_mail_attempts WHERE created_by_user_id=?
            AND state<>'sent' ORDER BY checked_at,created_at LIMIT 100''', (user_id,))]


def check_outlook(attempts):
    """Read existing Outlook only; bounded subprocess has no Send operation."""
    if not attempts:return []
    unknown = [dict(token=r['token'], state='unknown', detail='Klasický Outlook není dostupný.') for r in attempts]
    if not sys.platform.startswith('win'):return unknown
    env = os.environ.copy()
    env['TURTO_MAIL_ATTEMPTS'] = json.dumps([{k: row[k] for k in ('token','draft_entry_id','store_id','created_at')} for row in attempts])
    env['TURTO_MAIL_PROPERTY'] = PROPERTY
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-ExecutionPolicy', 'Bypass',
            '-File', str(Path(__file__).with_name('outlook_tracking.ps1'))], env=env,
            capture_output=True, text=True, encoding='utf-8', timeout=40,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode == 0:
            data = json.loads(result.stdout.lstrip('\ufeff'))
            if isinstance(data, list):return data
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return unknown


def record_checks(M, attempts, results):
    """Only exact known tokens with positive Outlook evidence can become sent."""
    known = {r['token'] for r in attempts}
    with closing(M.db()) as con, con:
        for row in results:
            if row.get('token') not in known:continue
            state = row.get('state')
            sent_at = row.get('sent_at', '')
            if state == 'sent':
                try:
                    when = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                    if when.year < 2000 or when.year > datetime.now().year + 1:raise ValueError()
                except (TypeError, ValueError):
                    state, sent_at = 'unknown', ''
            if state not in ('sent', 'draft'):state = 'unknown'
            con.execute('''UPDATE request_mail_attempts SET state=?,sent_at=?,detail=?,
                checked_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE token=? AND state<>'sent' ''',
                (state, sent_at if state == 'sent' else '', str(row.get('detail') or '')[:250], row['token']))


def status_rows(M, request_ids=None):
    with closing(M.db()) as con:
        rows = con.execute('SELECT * FROM request_mail_attempts ORDER BY created_at, rowid').fetchall()
    result = {}
    for row in rows:
        if request_ids is not None and row['request_id'] not in request_ids:continue
        status = result.setdefault(row['request_id'], {'state': 'unknown', 'sent_at': '', 'draft_after_sent': False})
        if row['state'] == 'sent':
            status.update(state='sent', sent_at=max(status['sent_at'], row['sent_at']), draft_after_sent=False)
        elif status['state'] == 'sent':
            status['draft_after_sent'] = row['state'] == 'draft'
        else:
            status.update(state=row['state'])
    return result


def label(status):
    if not status:return 'Odeslání neověřeno'
    if status['state'] == 'sent':
        when = datetime.fromisoformat(status['sent_at'].replace('Z', '+00:00')).astimezone()
        return 'Odesláno ' + when.strftime('%d.%m.%Y %H:%M') + (' · další koncept' if status.get('draft_after_sent') else '')
    return 'Koncept vytvořen' if status['state'] == 'draft' else 'Odeslání neověřeno'
