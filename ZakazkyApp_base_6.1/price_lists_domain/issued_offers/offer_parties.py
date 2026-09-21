"""Offer choices and directory actions use shared company/person identities."""
from contextlib import closing
from ..platform import portfolio, sales_identity, user_access as access
from . import template_layout


def contact_choices(M, company_id):
    if not company_id: return {}
    with closing(M.db()) as con:
        rows = [dict(r) for r in con.execute(
            'SELECT id,name,email FROM people WHERE company_id=? AND active=1 ORDER BY name COLLATE CZECH,id', (company_id,))]
    result = {}
    for row in rows:
        name = row['name']
        if sum(r['name']==name for r in rows)>1:
            name += ' · '+str(row['email'] or row['id'])
        result[name] = row['id']
    return result


def salesperson_snapshot(editor, values):
    sid = values.get('salesperson_id')
    if not sid:
        if editor.document.get('salesperson_id'):
            for field in ('contact','email','phone'): values['issuer_'+field+'_snapshot']=''
        return
    if editor.document_id and getattr(editor,'locked',False) and sid == editor.document.get('salesperson_id'):
        return  # Issued documents retain their historical issuer contact snapshot.
    with closing(editor.M.db()) as con:
        row = con.execute('''SELECT s.name,p.email,p.phone FROM salespeople s
            LEFT JOIN people p ON p.id=s.person_id WHERE s.id=?''', (sid,)).fetchone()
    if row:
        values['salesperson_snapshot'] = row['name']
        values['issuer_contact_snapshot'] = row['name']
        for field in ('email','phone'):
            values['issuer_'+field+'_snapshot'] = row[field] or ''


def standard_templates(M):
    with closing(M.db()) as con:
        return [dict(r) for r in con.execute(
            'SELECT * FROM business_document_templates WHERE builtin_key=? AND active=1',
            (template_layout.BUILTIN_KEY,))]


def refresh_salespeople(editor, preserve=False):
    if getattr(editor,'locked',False) and editor.document_id:
        saved=str(editor.document.get('salesperson_snapshot') or '')
        editor.salesperson_map={saved:editor.document.get('salesperson_id')} if saved else {}
        editor.salesperson.set(saved)
        editor.salesperson_box.configure(values=tuple(editor.salesperson_map))
        return
    cid = editor.company_map.get(editor.company.get().strip())
    previous = editor.salesperson_map.get(editor.salesperson.get()) if hasattr(editor, 'salesperson_map') else None
    with closing(editor.M.db()) as con:
        rows = [dict(r) for r in con.execute('''SELECT s.id,s.name FROM salespeople s
            JOIN company_salespeople c ON c.salesperson_id=s.id
            WHERE c.company_id=? AND s.active=1 AND s.canonical_id IS NULL
            ORDER BY s.name COLLATE CZECH''', (cid,))]
    editor.salesperson_map = {r['name']:r['id'] for r in rows}
    wanted = previous or (editor.document.get('salesperson_id') if preserve else None)
    if preserve and editor.document_id and cid == editor.document.get('company_id'):
        saved = str(editor.document.get('salesperson_snapshot') or '')
        if saved and saved not in editor.salesperson_map:
            editor.salesperson_map[saved] = editor.document.get('salesperson_id')
        if not wanted and saved in editor.salesperson_map:
            editor.salesperson.set(saved)
            editor.salesperson_box.configure(values=('', *editor.salesperson_map))
            return
    chosen = next((name for name, sid in editor.salesperson_map.items() if wanted and sid == wanted), None)
    if chosen is None:
        default = sales_identity.default_salesperson(editor.M)
        chosen = next((r['name'] for r in rows if r['id'] == default), None)
        if chosen is None and len(rows) == 1: chosen = rows[0]['name']
    editor.salesperson.set(chosen or '')
    editor.salesperson_box.configure(values=('', *editor.salesperson_map))


def edit_contact(editor, new=False):
    if editor.locked or not access.allowed(editor.M, editor.win, 'people'): return
    cid = editor.company_map.get(editor.company.get().strip())
    if not cid:
        return editor.M.messagebox.showinfo('Kontaktní osoba', 'Nejprve vyberte odběratele.', parent=editor.win)
    pid = None if new else editor.contact_map.get(editor.contact.get().strip())
    if not new and not pid:
        return editor.M.messagebox.showinfo('Kontaktní osoba', 'Vyberte osobu, kterou chcete upravit.', parent=editor.win)
    win = editor.M.PersonDialog(editor.win, pid=pid, pre_company_id=cid)
    editor.win.wait_window(win)
    if not editor.win.winfo_exists(): return
    editor.win.grab_set()
    editor.refresh_contacts()
    if win.result:
        with closing(editor.M.db()) as con:
            if not pid:
                found = con.execute('SELECT id FROM people WHERE company_id=? AND email=? AND active=1',
                    (cid, win.vars['email'].get().strip())).fetchone()
                pid = found[0] if found else None
        name = next((n for n, i in editor.contact_map.items() if i == pid), '')
        editor.contact.set(name)
        editor.app.refresh_people()
        refresh = getattr(editor.app, 'refresh_portfolio', None)
        if refresh: refresh()
    preview = getattr(editor, '_v720_preview', None)
    if preview: preview.schedule()


def assign_salespeople(editor):
    if editor.locked: return
    cid = editor.company_map.get(editor.company.get().strip())
    if not cid:
        return editor.M.messagebox.showinfo('Obchodní zástupci', 'Nejprve vyberte odběratele.', parent=editor.win)
    win = portfolio.assign_dialog(editor.M, editor.win, cid)
    if win is None: return
    editor.win.wait_window(win)
    if not editor.win.winfo_exists(): return
    editor.win.grab_set()
    refresh_salespeople(editor)
    refresh = getattr(editor.app, 'refresh_portfolio', None)
    if refresh: refresh()
