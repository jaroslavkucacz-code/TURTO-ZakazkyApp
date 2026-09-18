#!/usr/bin/env python3
"""Real CRM migrations, denied writes, independent tabs and Windows user workflows."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import user_access as access, action_assignees


def prepare(td):
    spec = importlib.util.spec_from_file_location('prior', REPO / 'scripts/validate-827-processing-catalogs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare(td, runtime=True), module.settle


def rejects(fn):
    try:
        fn()
    except (access.AccessDenied, ValueError, sqlite3.Error):
        return
    raise AssertionError('Forbidden/stale change was accepted')


def seed(M):
    with closing(M.db()) as con, con:
        con.execute("INSERT INTO users(name) VALUES('834 Alena'),('834 Bára'),('834 Čtenář')")
        con.execute("INSERT INTO users(name,active) VALUES('834 Původní',0)")
        uids = {r['name']: r['id'] for r in con.execute('SELECT id,name FROM users')}
        cid = con.execute("INSERT INTO companies(short_name,official_name,is_supplier) VALUES('834 Firma','834 Firma s.r.o.',1)").lastrowid
        mid = con.execute("INSERT INTO companies(short_name,official_name,is_supplier) VALUES('MIVO','MIVO test s.r.o.',1)").lastrowid
        pid = con.execute("INSERT INTO projects(name) VALUES('834 Projekt')").lastrowid
        aid = con.execute("INSERT INTO actions(name,company_id,project_id) VALUES('834 Projekt',?,?)", (cid, pid)).lastrowid
        rid = con.execute("INSERT INTO requests(company_id,item) VALUES(?,'834 Nosník')", (cid,)).lastrowid
        mivo = con.execute("INSERT INTO requests(company_id,item) VALUES(?,'834 MIVO')", (mid,)).lastrowid
        offer = con.execute("INSERT INTO business_documents(document_type,direction,company_id,document_number) VALUES('issued_offer','issued',?,'834-N1')", (cid,)).lastrowid
        order = con.execute("INSERT INTO business_documents(document_type,direction,company_id,document_number) VALUES('received_order','received',?,'834-O1')", (cid,)).lastrowid
        con.execute("INSERT INTO business_document_items(document_id,name) VALUES(?,'834 Položka')", (offer,))
        received = con.execute("INSERT INTO supplier_offers(supplier_company_id,offer_number) VALUES(?,'834-R1')", (cid,)).lastrowid
        item = con.execute("INSERT INTO supplier_offer_items(offer_id,original_name,item_key) VALUES(?,'834 Nosník','834-nosnik')", (received,)).lastrowid
    return dict(uids=uids, cid=cid, mid=mid, pid=pid, aid=aid, rid=rid, mivo=mivo, offer=offer, order=order, received=received, item=item)


def source_checks(td):
    M, _ = prepare(td)
    data = seed(M)
    M.ensure_schema(); M.ensure_schema()
    def sql(query, args=()):
        with closing(M.db()) as con, con:
            return con.execute(query, args).fetchall()
    access.refresh_session(M, '834 Alena')
    assert all(access.level(M, key) == access.EDIT for key in access.TITLES)
    assert access.profile(M, data['uids']['834 Alena'])['job_title'] == ''
    rejects(lambda: access.save_profile(M, data['uids']['834 Alena'], 'Ředitel', {}, ('', '{}')))
    rejects(lambda: sql("UPDATE users SET tab_permissions='{}',job_title='Ředitel' WHERE name='834 Alena'"))
    rejects(lambda: sql("INSERT OR REPLACE INTO users(id,name) VALUES(?,'834 Alena')", (data['uids']['834 Alena'],)))

    access.refresh_session(M, 'ADMIN')
    permissions = {'actions': access.READ, 'people': access.HIDDEN, 'issued_offers': access.READ,
                   'mivo': access.READ, 'reports_imports': access.READ, 'reports_customers': access.READ}
    uid = data['uids']['834 Čtenář']
    original = access.profile(M, uid)
    access.save_profile(M, uid, 'Technická podpora', permissions, ('', '{}'))
    rejects(lambda: access.save_profile(M, uid, 'Ředitel', {}, ('', '{}')))
    access.refresh_session(M, '834 Čtenář')
    assert access.level(M, 'actions') == access.READ and access.level(M, 'people') == access.HIDDEN
    assert access.level(M, 'received_orders') == access.EDIT
    assert access.level(M, 'reports') == access.EDIT
    for query, args in (
        ('UPDATE actions SET name=? WHERE id=?', ('changed', data['aid'])),
        ('INSERT INTO actions(name) VALUES(?)', ('denied',)),
        ('DELETE FROM actions WHERE id=?', (data['aid'],)),
        ('UPDATE requests SET item=? WHERE id=?', ('denied', data['mivo'])),
        ('UPDATE requests SET company_id=? WHERE id=?', (data['mid'], data['rid'])),
        ('UPDATE business_documents SET note=? WHERE id=?', ('denied', data['offer'])),
        ('UPDATE business_document_items SET name=? WHERE document_id=?', ('denied', data['offer'])),
        ("UPDATE business_documents SET document_type='received_order',direction='received' WHERE id=?", (data['offer'],)),
        ('INSERT INTO people(name) VALUES(?)', ('denied',)),
    ):
        rejects(lambda q=query, a=args: sql(q, a))
    # Other permitted tabs keep their own write access.
    sql('UPDATE requests SET note=? WHERE id=?', ('allowed', data['rid']))
    sql("UPDATE companies SET official_name='Jiný oficiální název' WHERE id=?", (data['mid'],))
    from price_lists_domain.platform.access_controls import _request_page
    assert _request_page(M, company='Jiný oficiální název') == 'mivo'
    sql('UPDATE business_documents SET note=? WHERE id=?', ('allowed', data['order']))
    assert sql('SELECT note FROM business_documents WHERE id=?', (data['order'],))[0][0] == 'allowed'
    def atomic_change():
        with closing(M.db()) as con, con:
            con.execute("UPDATE projects SET name='must roll back' WHERE id=?", (data['pid'],))
            con.execute("UPDATE actions SET name='denied' WHERE id=?", (data['aid'],))
    rejects(atomic_change)
    assert sql('SELECT name FROM projects WHERE id=?', (data['pid'],))[0][0] == '834 Projekt'
    rejects(lambda: action_assignees.save(M, data['aid'], '[]', [data['uids']['834 Alena']]))

    from price_lists_domain.monthly_reports.storage import ReportingStore
    from price_lists_domain.monthly_reports.company_links import CompanyLinks, name_key
    store = ReportingStore(Path(td) / 'data' / 'zakazky.db')
    store.database.can_write = lambda: access.level(M, 'reports_imports', fresh=True) == access.EDIT
    rejects(lambda: store.database.execute("INSERT INTO delivery_notes(doc_no) VALUES('denied')"))
    links = CompanyLinks(M.db, store.database, '834 Čtenář', can_write=lambda: access.level(M, 'reports_customers') == access.EDIT)
    links.resolve(['834 Firma s.r.o.'])
    assert not sql('SELECT * FROM report_company_links WHERE source_key=?', (name_key('834 Firma s.r.o.'),))
    rejects(lambda: links.save('834 Firma s.r.o.', data['cid'], 'manual', None))

    # Permissions belong to stable user IDs, independently of display-name changes.
    access.refresh_session(M, 'ADMIN')
    sql("UPDATE users SET name='834 Přejmenovaný' WHERE id=?", (uid,))
    access.refresh_session(M, '834 Přejmenovaný')
    assert access.level(M, 'actions') == access.READ
    assert access.profile(M, uid)['job_title'] == 'Technická podpora'
    # A new transaction sees an administrator's changed permissions.
    with closing(M._user_access_connect()) as con, con:
        con.execute("UPDATE users SET tab_permissions='{}' WHERE id=?", (uid,))
    sql("UPDATE actions SET note='now allowed' WHERE id=?", (data['aid'],))
    assert access.level(M, 'actions') == access.EDIT
    access.refresh_session(M, '834 Bára')
    assert all(access.level(M, key) == access.EDIT for key in access.TITLES)
    print('8.0.34: additive defaults, administrator-only profiles, CAS, stable identities, atomic denied writes, MIVO/document isolation and report import guards OK', flush=True)


def ui_checks(td):
    M, settle = prepare(td)
    data = seed(M)
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageGrab
    from price_lists_domain.platform.form_behavior_817 import children
    from price_lists_domain.platform.user_access_ui import open_profile
    M.App.maybe_show_morning_overview = lambda self: None
    errors, warnings = [], []
    M.messagebox.showinfo = lambda *a, **k: None
    M.messagebox.showwarning = lambda *a, **k: warnings.append(str(a))
    M.messagebox.showerror = lambda *a, **k: errors.append(str(a))
    M.messagebox.askyesnocancel = lambda *a, **k: False
    M.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    M.set_setting('active_user', '834 Alena')
    root = M.App()
    output = REPO / 'build/validation/user-access-834'
    output.mkdir(parents=True, exist_ok=True)
    try:
        root.state('normal'); root.geometry('1220x850+0+0'); settle(root, 3)
        main_buttons = sorted(root.main_nav.place_slaves(), key=lambda w: (w.winfo_y(), w.winfo_x()))
        assert [key for widget in main_buttons for key, button in root.nav.items() if button is widget][:3] == ['dash', 'business', 'technical']
        root.show_page('business'); settle(root)
        assert root._current_page == 'business' and not root.tabs['business'].winfo_children()
        # Local logged-in user wins over another client's global preference.
        M.set_setting('active_user', '834 Bára')
        d = M.ActionDialog(root); settle(root)
        assert [uid for uid, var in d.assignee_variables.items() if var.get()] == [data['uids']['834 Alena']]
        assert data['uids']['ADMIN'] not in d.assignee_variables
        assert data['uids']['TEST'] not in d.assignee_variables
        d.assignee_variables[data['uids']['834 Bára']].set(True)
        d.name.set('834 Nová akce'); d.company.set('834 Firma s.r.o.')
        settle(root)
        ImageGrab.grab().save(output / 'processing-assignees.png')
        d.ok(); settle(root)
        assert d.result
        aid = d.result
        with M.db() as con:
            saved = con.execute('SELECT assignees_json,updated_by FROM actions WHERE id=?', (aid,)).fetchone()
        assert set(action_assignees.decode(saved[0])) == {data['uids']['834 Alena'], data['uids']['834 Bára']}
        assert saved[1] == '834 Alena'
        d = M.ActionDialog(root, aid); settle(root)
        assert all(d.assignee_variables[uid].get() for uid in action_assignees.decode(saved[0]))
        d.assignee_variables[data['uids']['834 Bára']].set(False)
        d.destroy()  # Cancel has no DB effects.
        with M.db() as con:
            assert con.execute('SELECT assignees_json FROM actions WHERE id=?', (aid,)).fetchone()[0] == saved[0]
        d = M.ActionDialog(root, data['aid']); settle(root)
        assert not any(var.get() for var in d.assignee_variables.values())  # Existing empty stays empty.
        d.destroy()
        stale = M.ActionDialog(root, aid); settle(root)
        stale.assignee_variables[data['uids']['834 Bára']].set(False)
        action_assignees.save(M, aid, saved[0], [data['uids']['834 Bára']])
        stale.name.set('834 Must not create project')
        stale.ok(); assert stale.winfo_exists() and stale.result is None
        with M.db() as con:
            assert not con.execute("SELECT 1 FROM projects WHERE name='834 Must not create project'").fetchone()
        stale.destroy()

        # Fixture represents an already authenticated administrator session.
        root.active_user.set('ADMIN'); root.refresh_user_access()
        uid = data['uids']['834 Čtenář']
        profile = open_profile(M, root, root, uid); settle(root)
        profile.job_title_variable.set('Technická podpora')
        profile.permission_variables['actions'].set(access.MODES[access.READ])
        profile.permission_variables['companies'].set(access.MODES[access.HIDDEN])
        profile.permission_variables['people'].set(access.MODES[access.HIDDEN])
        profile.permission_variables['issued_offers'].set(access.MODES[access.READ])
        profile.permission_variables['offers'].set(access.MODES[access.READ])
        profile.permission_variables['reports_imports'].set(access.MODES[access.READ])
        for theme in ('Světlý', 'Tmavý'):
            root.apply_theme(theme); settle(root)
            ImageGrab.grab().save(output / f'user-profile-{theme}.png')
        save = next(w for w in children(profile) if isinstance(w, ttk.Button) and w.cget('text') == 'Uložit')
        assert save.winfo_viewable()
        save.invoke(); settle(root)
        assert access.profile(M, uid)['job_title'] == 'Technická podpora'
        root.select_user('834 Čtenář'); settle(root)
        assert not root.nav['directory'].winfo_manager()
        root.show_page('actions'); settle(root)
        current = root._current_page
        root.show_page('companies'); assert root._current_page == current
        rejects(lambda: M.CompanyDialog(root, data['cid']))
        d = M.ActionDialog(root, aid); settle(root)
        assert 'čtení' in d.title()
        assert all(w.instate(['disabled']) for w in children(d) if isinstance(w, ttk.Checkbutton))
        with M.db() as con: before = tuple(con.execute('SELECT name,assignees_json FROM actions WHERE id=?', (aid,)).fetchone())
        d.name.set('Not saved'); d.ok()
        with M.db() as con: assert tuple(con.execute('SELECT name,assignees_json FROM actions WHERE id=?', (aid,)).fetchone()) == before
        ImageGrab.grab().save(output / 'processing-readonly.png'); d.destroy()
        # A linked offer editor remains read-only regardless of the current page.
        from price_lists_domain.issued_offers.editor import IssuedOfferEditor
        editor = IssuedOfferEditor(M, root, data['offer']); settle(root)
        editor.save(); assert 'čtení' in editor.win.title(); editor.win.destroy()
        received = M.OfferDetailDialog(root, data['received']); settle(root)
        inline = received._inline_labels
        inline.begin(f"i{data['item']}", 'Interní označení')
        assert inline.entry is None
        received.destroy()
        root.show_page('reports_imports'); settle(root, .8)
        workspace = root._reports_workspace
        assert workspace.last_error is None
        imports = [w for w in children(workspace) if w.winfo_class() in {'Button','TButton'} and 'Importovat' in str(w.cget('text'))]
        assert imports and all(str(w.cget('state')) == 'disabled' for w in imports)
        rejects(lambda: workspace.db.execute("INSERT INTO delivery_notes(doc_no) VALUES('denied')"))
        root.select_user('834 Bára'); settle(root)
        assert root.nav['directory'].winfo_manager()
        assert access.level(M, 'actions') == access.EDIT
        d = M.ActionDialog(root); settle(root)
        assert d.assignee_variables[data['uids']['834 Bára']].get()
        assert not d.assignee_variables[data['uids']['834 Alena']].get()
        d.destroy()
        # A profile with no visible page has an explicit empty state, and can be switched away from.
        with closing(M._user_access_connect()) as con, con:
            con.execute('UPDATE users SET tab_permissions=? WHERE id=?', (json.dumps(dict.fromkeys(access.TITLES, access.HIDDEN)), uid))
        root.select_user('834 Čtenář'); settle(root)
        assert root._current_page is None and root._no_access_page.winfo_viewable()
        assert not root.help_button.winfo_viewable() and not root.settings_button.winfo_viewable()
        root.select_user('834 Bára'); settle(root)
        assert root._current_page == 'dash' and root.help_button.winfo_viewable() and root.settings_button.winfo_viewable()
        assert not errors, errors
        print('8.0.34: blank Obchod, local default/multiple assignees, cancel/stale form, profiles, hidden navigation, linked read-only forms and user switching OK', flush=True)
    finally:
        root._turto_closing = True
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.tk.call('after', 'cancel', job)
        root.destroy()


if __name__ == '__main__':
    if '--source-worker' in sys.argv:
        source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:
        ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-access-834-') as td:
            subprocess.run([sys.executable, '-B', __file__, '--source-worker', str(Path(td) / 'source')], check=True)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable, '-B', __file__, '--ui-worker', str(Path(td) / 'ui')], check=True)
