#!/usr/bin/env python3
"""Real schema/permission transitions, shared portfolios and Outlook evidence."""
from contextlib import closing
from datetime import date
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import user_access as access, task_scope, portfolio, sales_identity, mail_tracking


def prepare(td):
    spec = importlib.util.spec_from_file_location('fixture840', REPO/'scripts/validate-834-user-access.py')
    fixture = importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    return fixture.prepare(td)


def sql(M, statement, values=()):
    with closing(M.db()) as con, con:
        return con.execute(statement, values).fetchall()


def rejects(callback):
    try:callback()
    except (ValueError, sqlite3.Error):return
    raise AssertionError('Unauthorized or stale change accepted')


def seed(M):
    with closing(M.db()) as con, con:
        for name in ('Jirka','Honza','Milan','840 Alena','840 Petr','840 Cizí'):
            con.execute('INSERT OR IGNORE INTO users(name) VALUES(?)', (name,))
        con.execute("INSERT INTO salespeople(name) VALUES('J')")
        alias = con.execute("SELECT id FROM salespeople WHERE name='J'").fetchone()[0]
        con.execute("DELETE FROM settings WHERE key='migration_sales_identity_840'")
        cid = con.execute("INSERT INTO companies(short_name,official_name,is_customer,address) VALUES('840 Sdílený','840 Sdílený zákazník',1,'Praha')").lastrowid
        other = con.execute("INSERT INTO companies(short_name,official_name,is_customer,address) VALUES('840 Druhý','840 Druhý zákazník',1,'Brno')").lastrowid
        supplier = con.execute("INSERT INTO companies(short_name,official_name,is_customer,is_supplier) VALUES('840 Dodavatel','840 Dodavatel',0,1)").lastrowid
        aid = con.execute("INSERT INTO actions(name,company_id,salesperson_id) VALUES('840 Testovací akce',?,?)", (cid, alias)).lastrowid
        rid = con.execute("INSERT INTO requests(company_id,item,mail_subject) VALUES(?,'840 Konstrukce','Poptávka TURTO - 840')", (supplier,)).lastrowid
    M.ensure_schema();M.ensure_schema()
    ids = {r['name']:r['id'] for r in sql(M,'SELECT * FROM users')}
    return dict(cid=cid,other=other,supplier=supplier,aid=aid,rid=rid,ids=ids)


def source_checks(td):
    M, settle = prepare(td);data = seed(M)
    reps = {r['pohoda_center']:r['id'] for r in sql(M,'SELECT * FROM salespeople WHERE active=1') if r['pohoda_center']}
    assert set(reps) == {'J','H','M'}
    assert sql(M,'SELECT salesperson_id FROM actions WHERE id=?',(data['aid'],))[0][0] == reps['J']
    assert len(sql(M,"SELECT * FROM salespeople WHERE active=1 AND name IN ('J','Jirka')")) == 0
    for alias, center, name in [('Jirka','J','Jiří Cír'),('Honza','H','Jan Mayer'),('Milan','M','Milan Soukup')]:
        row = sql(M,'SELECT * FROM users WHERE name=?',(alias,))[0]
        assert row['salesperson_id']==reps[center] and row['job_title']=='Obchodní zástupce'
        assert sql(M,'SELECT name,pohoda_center FROM people WHERE id=?',(row['person_id'],))[0][:] == (name,center)
    access.refresh_session(M,'Jirka')
    assert sales_identity.default_salesperson(M)==reps['J']
    portfolio.save(M,data['cid'],{reps['J'],reps['H']},set())
    portfolio.save(M,data['other'],{reps['M']},set())
    assert {r['id'] for r in portfolio.rows(M,reps['J'])}=={data['cid']}
    assert {r['id'] for r in portfolio.rows(M,reps['H'])}=={data['cid']}
    assert {r['id'] for r in portfolio.rows(M,reps['M'])}=={data['other']}
    rejects(lambda:portfolio.save(M,data['supplier'],{reps['J']},set()))
    rejects(lambda:portfolio.save(M,data['cid'],{reps['M']},set()))
    # Fresh IDs, legacy names, delegated-to-self deduplication and unknown ownership.
    access.refresh_session(M,'840 Alena')
    shared=task_scope.save(M,None,'840 Testovací akce',date.today().isoformat(),'Delegováno Petrovi','Soukromá poznámka','840 Petr','840 Alena')
    own=task_scope.save(M,None,'840 Testovací akce',date.today().isoformat(),'Jen Alena','','840 Alena','840 Alena')
    rejects(lambda:task_scope.save(M,None,'840 Testovací akce','2026-09-20','Chyba','','Neexistující','840 Alena'))
    assert {r['id'] for r in sql(M,'SELECT * FROM visible_tasks')}=={shared,own}
    access.refresh_session(M,'840 Petr')
    assert {r['id'] for r in sql(M,'SELECT * FROM visible_tasks')}=={shared}
    sql(M,'UPDATE tasks SET done=1 WHERE id=?',(shared,))
    rejects(lambda:sql(M,'UPDATE tasks SET done=1 WHERE id=?',(own,)))
    rejects(lambda:sql(M,'UPDATE tasks SET created_by=? WHERE id=?',('840 Petr',shared)))
    access.refresh_session(M,'840 Cizí')
    assert sql(M,'SELECT * FROM visible_tasks')==[]
    assert sql(M,"SELECT * FROM visible_action_history WHERE event_type LIKE 'task_%'")==[]
    rejects(lambda:sql(M,'DELETE FROM tasks WHERE id=?',(shared,)))
    rejects(lambda:task_scope.save(M,shared,'840 Testovací akce','2026-09-20','Pokus','','840 Cizí','840 Cizí'))
    with closing(M._user_access_connect()) as con,con:
        legacy = con.execute("INSERT INTO tasks(action_id,due_date,text,created_by,assigned_user) VALUES(?,'2026-09-20','Osiřelý','','')", (data['aid'],)).lastrowid
        con.execute("UPDATE users SET name='840 Petr přejmenovaný' WHERE name='840 Petr'")
    rejects(lambda:sql(M,'UPDATE tasks SET done=1 WHERE id=?',(legacy,)))
    access.refresh_session(M,'840 Petr přejmenovaný')
    assert {r['id'] for r in sql(M,'SELECT * FROM visible_tasks')}=={shared}
    access.refresh_session(M,'840 Alena')
    task_scope.save(M,shared,'840 Testovací akce','2026-09-20','Přeřazeno','','840 Cizí','840 Alena')
    access.refresh_session(M,'840 Petr přejmenovaný');assert sql(M,'SELECT * FROM visible_tasks')==[]
    access.refresh_session(M,'840 Cizí');assert {r['id'] for r in sql(M,'SELECT * FROM visible_tasks')}=={shared}
    access.refresh_session(M,'ADMIN')
    row=access.profile(M,data['ids']['840 Alena'])
    access.save_profile(M,row['id'],'Technická podpora',{'tasks':0,'portfolio':1},(row['job_title'],row['tab_permissions']))
    access.refresh_session(M,'840 Alena')
    assert sql(M,'SELECT * FROM visible_tasks')==[]
    rejects(lambda:portfolio.save(M,data['cid'],set(),{reps['J'],reps['H']}))
    rejects(lambda:sql(M,'UPDATE users SET salesperson_id=? WHERE id=?',(reps['M'],row['id'])))
    # Every attempt has a different token; renamed subjects/changed EntryIDs are irrelevant.
    token=mail_tracking.begin(M,data['rid'],'840 Alena')
    mail_tracking.draft_created(M,token,{'saved':True,'entry_id':'old-entry','store_id':'test-store'})
    assert mail_tracking.label(mail_tracking.status_rows(M)[data['rid']])=='Koncept vytvořen'
    pending=mail_tracking.pending(M,row['id']);assert len(pending)==1
    mail_tracking.record_checks(M,pending,[dict(token='wrong-token',state='sent',sent_at='2026-09-20T08:00:00Z')])
    assert mail_tracking.status_rows(M)[data['rid']]['state']=='draft'
    mail_tracking.record_checks(M,pending,[dict(token=token,state='unknown')])
    assert mail_tracking.label(mail_tracking.status_rows(M)[data['rid']])=='Odeslání neověřeno'
    mail_tracking.record_checks(M,pending,[dict(token=token,state='sent',sent_at='not-a-date')])
    assert mail_tracking.status_rows(M)[data['rid']]['state']=='unknown'
    mail_tracking.record_checks(M,pending,[dict(token=token,state='sent',sent_at='2026-09-20T08:00:00Z',entry_id='new-entry',subject='Changed')])
    assert mail_tracking.label(mail_tracking.status_rows(M)[data['rid']]).startswith('Odesláno 20.09.2026')
    mail_tracking.record_checks(M,pending,[dict(token=token,state='unknown')])
    assert mail_tracking.status_rows(M)[data['rid']]['state']=='sent'
    token2=mail_tracking.begin(M,data['rid'],'840 Alena');assert token2!=token
    mail_tracking.draft_created(M,token2,{'saved':True})
    assert mail_tracking.label(mail_tracking.status_rows(M)[data['rid']]).endswith('další koncept')
    assert [r['token'] for r in mail_tracking.pending(M,row['id'])]==[token2]
    with patch.object(mail_tracking.sys,'platform','win32'),patch.object(mail_tracking.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps([dict(token=token2,state='unknown')])) ) as run:
        assert mail_tracking.check_outlook(mail_tracking.pending(M,row['id']))[0]['state']=='unknown'
        assert run.call_args.kwargs['timeout']==40
        assert run.call_args.kwargs['env']['TURTO_MAIL_PROPERTY']==mail_tracking.PROPERTY
    # Windows PowerShell's former nested-array bug returned [null, null].
    # Invalid transport data must not crash reconciliation or confirm sending.
    for malformed in ('[null,null]', '[null]', '{"state":"sent"}', 'invalid'):
        with patch.object(mail_tracking.sys,'platform','win32'),patch.object(mail_tracking.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=malformed)):
            result=mail_tracking.check_outlook(mail_tracking.pending(M,row['id']))
            assert len(result)==1 and result[0]['token']==token2 and result[0]['state']=='unknown'
            mail_tracking.record_checks(M,mail_tracking.pending(M,row['id']),result)
    # Complete rollback if a mixed bulk mutation contains somebody else's task.
    access.refresh_session(M,'840 Cizí')
    before=sql(M,'SELECT text FROM tasks WHERE id=?',(shared,))[0][0]
    rejects(lambda:sql(M,"UPDATE tasks SET text='must rollback' WHERE id IN (?,?)",(shared,own)))
    assert sql(M,'SELECT text FROM visible_tasks WHERE id=?',(shared,))[0][0]==before
    print('8.0.40: alias migration/IDs, shared portfolios, CAS, private tasks, history, reassignments, atomic guards, Outlook attempt reconciliation OK',flush=True)


def ui_checks(td):
    M, settle=prepare(td);data=seed(M)
    M.set_setting('active_user','Jirka')
    access.refresh_session(M,'Jirka')
    reps={r['pohoda_center']:r['id'] for r in sql(M,'SELECT * FROM salespeople WHERE active=1') if r['pohoda_center']}
    portfolio.save(M,data['cid'],{reps['J'],reps['H']},set())
    portfolio.save(M,data['other'],{reps['M']},set())
    own=task_scope.save(M,None,'840 Testovací akce',date.today().isoformat(),'Zkontrolovat podklady od Honzy','','Honza','Jirka')
    access.refresh_session(M,'Milan')
    private=task_scope.save(M,None,'840 Testovací akce',date.today().isoformat(),'Milanův soukromý úkol','','Milan','Milan')
    access.refresh_session(M,'Jirka')
    token=mail_tracking.begin(M,data['rid'],'Jirka');mail_tracking.draft_created(M,token,{'saved':True})
    errors=[];M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.askyesnocancel=lambda *a,**k:False
    M.App.maybe_show_morning_overview=lambda self:None
    M.App.report_callback_exception=lambda self,*a:errors.append(str(a))
    # Never inspect the host's real Outlook in validation.
    mail_tracking.check_outlook=lambda attempts:[dict(token=r['token'],state='draft') for r in attempts]
    root=M.App();root.report_callback_exception=lambda *a:errors.append(str(a))
    output=REPO/'build/validation/portfolio-840';output.mkdir(parents=True,exist_ok=True)
    def shot(name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.3)
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(output/name)
    try:
        root.apply_theme('Světlý');root.show_page('business');settle(root,1)
        assert root._current_page=='portfolio'
        workspace=root.portfolio_workspace
        assert workspace.selection.get()=='Moje portfolio'
        assert set(workspace.tree.get_children())=={f"c{data['cid']}"}
        shot('portfolio-light.png')
        root.apply_theme('Tmavý');settle(root);shot('portfolio-dark.png')
        workspace.selection.set('Všichni obchodníci');workspace.refresh()
        assert {f"c{data['cid']}",f"c{data['other']}"}<=set(workspace.tree.get_children())
        workspace.tree.selection_set(f"c{data['cid']}");win=workspace.assign();settle(root)
        assert win.portfolio_variables[reps['J']].get() and win.portfolio_variables[reps['H']].get()
        win.destroy()
        root.apply_theme('Světlý');root.show_page('tasks');settle(root)
        assert set(root.task_tree.get_children())=={f't{own}'}
        assert all('Milanův' not in str(root.dash_tasks_tree.item(i)) for i in root.dash_tasks_tree.get_children())
        shot('delegated-task.png')
        for name,expected in [('Honza',{f't{own}'}),('Milan',{f't{private}'}),('Jirka',{f't{own}'})]:
            root.active_user.set(name);root.refresh_user_access();root.refresh_tasks();settle(root)
            assert set(root.task_tree.get_children())==expected,(name,root.task_tree.get_children())
        root.show_page('requests');root.refresh_requests();settle(root)
        assert root.request_tree.set(f"r{data['rid']}",'E-mail')=='Koncept vytvořen'
        shot('request-mail-status.png')
        root.show_page('mivo');settle(root)
        assert 'E-mail' in root.mivo_tree.cget('columns'), root.mivo_tree.cget('columns')
        for tree in (root.request_tree,root.mivo_tree,root.portfolio_tree):
            for column in tree.cget('columns'):
                assert str(tree.heading(column,'text')).strip(),(str(tree),column)
                assert str(tree.heading(column,'anchor'))==str(tree.column(column,'anchor')),(column,tree.heading(column),tree.column(column))
        assert root.request_tree.column('E-mail','width')==245
        assert root.mivo_tree.column('E-mail','width')==245
        root.geometry('1220x720');root.show_page('business');settle(root);shot('portfolio-narrow.png')
        assert not errors,errors
        print('8.0.40: real Windows portfolio navigation, user defaults, shared assignment UI, private task switching and mail status OK',flush=True)
    finally:
        root._turto_closing=True
        root._mail_executor.shutdown(wait=False,cancel_futures=True)
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--source-worker' in sys.argv:source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-840-') as td:
            subprocess.run([sys.executable,'-B',__file__,'--source-worker',str(Path(td)/'source')],check=True,timeout=120)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],'--ui-worker',str(Path(td)/'ui')],check=True,timeout=120)
