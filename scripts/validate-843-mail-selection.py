#!/usr/bin/env python3
"""Selected Outlook checks: real menus, scoped batches, MIVO and session guards."""
from concurrent.futures import Future
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixture840',REPO/'scripts/validate-840-portfolios-tasks-mail.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from price_lists_domain.platform import mail_tracking as tracking, user_access as access
sql=fixture.sql
LABEL='Ověřit odeslání v Outlooku'


def prepare(td):
    M,settle=fixture.prepare(td);d=fixture.seed(M)
    access.refresh_session(M,'ADMIN');M.set_setting('active_user','ADMIN')
    owner=sql(M,"SELECT id FROM users WHERE name='ADMIN'")[0][0]
    ids=[]
    for index in range(5):
        sql(M,"INSERT INTO requests(company_id,item,asked_date) VALUES(?,?,'2026-09-21')",(d['supplier'],f'843 Test {index}'))
        ids.append(sql(M,'SELECT max(id) FROM requests')[0][0])
    sql(M,"INSERT INTO companies(short_name,official_name,is_supplier) VALUES('MIVO','843 MIVO',1)")
    mivo=sql(M,'SELECT max(id) FROM companies')[0][0]
    for index in (3,4):sql(M,'UPDATE requests SET company_id=? WHERE id=?',(mivo,ids[index]))
    for index,rid in enumerate(ids):
        for attempt in range(103 if index==0 else 1):
            sql(M,"INSERT INTO request_mail_attempts(token,request_id,created_by_user_id,state) VALUES(?,?,?,'draft')",(f'test-{index}-{attempt}',rid,owner))
    return M,settle,ids,owner,d


def source_checks(td):
    M,_,ids,owner,d=prepare(td)
    assert len(tracking.pending(M,owner))==100
    assert len(tracking.pending(M,owner,[ids[1]]))==1,'Selection must be applied before background limit'
    assert len(tracking.pending(M,owner,[ids[0],ids[1],ids[0]]))==104,'Bulk selection must not be truncated'
    assert tracking.pending(M,owner,[])==[]
    assert tracking.pending(M,d['ids']['840 Alena'],ids)==[],'Other users attempts leaked'
    sql(M,"UPDATE request_mail_attempts SET state='sent',sent_at='2026-09-21T10:00:00Z' WHERE request_id=?",(ids[1],))
    assert tracking.pending(M,owner,[ids[1]])==[]
    print('8.0.43: exact request scope, 100+ selected attempts, empty selection, ownership and sent exclusion OK',flush=True)


def ui_checks(td):
    M,settle,ids,owner,d=prepare(td)
    errors=[];infos=[];calls=[]
    M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:infos.append(a)
    M.App.maybe_show_morning_overview=lambda self:None
    M.App.report_callback_exception=lambda self,*a:errors.append(str(a))
    def check(attempts):
        calls.append([r['token'] for r in attempts])
        return [dict(token=r['token'],state='sent',sent_at='2026-09-21T10:00:00Z') for r in attempts]
    tracking.check_outlook=check  # Never access the host's real Outlook.
    root=M.App();root.after_cancel(root._mail_timer)
    output=REPO/'build/validation/mail-843';output.mkdir(parents=True,exist_ok=True)
    def shot(name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.15)
        ImageGrab.grab(bbox=(root.winfo_rootx(),root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height())).save(output/name)
    def wait_check():
        for _ in range(80):
            settle(root,.05)
            if root._mail_checks is None:return
        raise AssertionError('Selected check did not finish')
    def index(menu,label):
        return next(i for i in range(menu.index('end')+1) if menu.type(i)=='command' and menu.entrycget(i,'label')==label)
    def popup(tree,iid):
        tree.see(iid);settle(root,.05)
        x,y,width,height=tree.bbox(iid)
        def post(menu,*args):
            command=menu.cget('postcommand')
            if command:menu.tk.eval(command)
        with patch.object(M.tk.Menu,'tk_popup',autospec=True,side_effect=post) as call:
            tree.event_generate('<Button-3>',x=20,y=y+height//2,rootx=tree.winfo_rootx()+20,rooty=tree.winfo_rooty()+y+height//2)
            assert call.call_count==1
        return tree._v750_row_menu
    def widgets(w):
        yield w
        for child in w.winfo_children():yield from widgets(child)
    try:
        root.active_user.set('ADMIN');root.refresh_user_access()
        root.state('normal');root.geometry('1450x850+0+0');root.apply_theme('Světlý');root.show_page('requests');settle(root,.8)
        for page in ('requests','mivo'):
            for widget in widgets(root.tabs[page]):
                if widget.winfo_class() in ('TButton','TLabel'):
                    text=str(widget.cget('text'))
                    assert text!=LABEL and 'Doručení a přečtení' not in text,'Old verification toolbar remains'
        t=root.request_tree
        assert str(t.cget('selectmode'))=='extended',str(t.cget('selectmode'))
        chosen=tuple(f'r{rid}' for rid in ids[:2]);t.selection_set(chosen)
        menu=popup(t,chosen[0]);assert set(t.selection())==set(chosen)
        assert menu.entrycget(index(menu,LABEL),'state')=='normal'
        assert menu.entrycget(index(menu,'Vytvořit e-mail'),'state')=='disabled'
        menu.invoke(index(menu,LABEL));wait_check()
        expected={f'test-0-{i}' for i in range(103)}|{'test-1-0'}
        assert {token for batch in calls for token in batch}==expected
        assert sum(map(len,calls))==104 and max(map(len,calls))<=25
        assert all(tracking.status_rows(M)[rid]['state']=='sent' for rid in ids[:2])
        assert tracking.status_rows(M)[ids[2]]['state']=='draft'
        shot('requests-verified-selection.png')
        before=len(calls);t.selection_set(chosen)
        menu=popup(t,f'r{ids[2]}');assert t.selection()==(f'r{ids[2]}',)
        menu.invoke(index(menu,LABEL));wait_check()
        assert calls[before:]==[['test-2-0']]
        before=len(calls);menu.invoke(index(menu,LABEL));settle(root)
        assert len(calls)==before and any('U vybraných' in str(info) for info in infos)
        root.show_page('mivo');settle(root,.4);t=root.mivo_tree
        chosen=tuple(f'r{rid}' for rid in ids[3:]);t.selection_set(chosen)
        menu=popup(t,chosen[1]);assert set(t.selection())==set(chosen)
        menu.invoke(index(menu,LABEL));wait_check()
        assert set(calls[-1])=={'test-3-0','test-4-0'}
        shot('mivo-verified-selection.png')
        # Results started under a different login cannot update the database.
        sql(M,"UPDATE request_mail_attempts SET state='draft',sent_at='' WHERE request_id=?",(ids[3],))
        t.selection_set(f'r{ids[3]}');future=Future()
        with patch.object(root._mail_executor,'submit',return_value=future):root.check_selected_request_mail(t)
        menu=popup(t,f'r{ids[3]}');assert menu.entrycget(index(menu,LABEL),'state')=='disabled'
        row=access.profile(M,d['ids']['840 Alena'])
        access.save_profile(M,row['id'],'Technická podpora',{'requests':1,'mivo':1},(row['job_title'],row['tab_permissions']))
        root.active_user.set('840 Alena');root.refresh_user_access();root.show_page('mivo');settle(root)
        future.set_result([dict(token='test-3-0',state='sent',sent_at='2026-09-21T10:00:00Z')]);wait_check()
        assert tracking.status_rows(M)[ids[3]]['state']=='draft'
        menu=popup(t,f'r{ids[3]}');assert menu.entrycget(index(menu,LABEL),'state')=='disabled'
        before=len(calls);root.check_selected_request_mail(t);settle(root);assert len(calls)==before
        # The shared title action uses the same layout/style as New Request.
        root.active_user.set('ADMIN');root.refresh_user_access();root.show_page('portfolio');settle(root)
        buttons={str(w.cget('text')):w for w in widgets(root.tabs['portfolio']) if w.winfo_class()=='TButton'}
        assert not {'Přiřadit obchodníky…','Otevřít detail','+ Kontakt'} & set(buttons)
        manager=buttons['Obchodníci a střediska…']
        assert str(manager.cget('style'))=='Accent.TButton' and str(manager.pack_info()['side'])=='right'
        manager.invoke();settle(root)
        dialogs=[w for w in root.winfo_children() if isinstance(w,M.tk.Toplevel) and w.title()=='Obchodníci a střediska Pohody']
        assert len(dialogs)==1;dialogs[0].destroy()
        shot('portfolio-header-light.png')
        root.apply_theme('Tmavý');settle(root);shot('portfolio-header-dark.png')
        assert not errors,errors
        print('8.0.43: real row menu preserves bulk selection, selected-only async batches, MIVO, already sent, login/permission guards and portfolio title action OK',flush=True)
    finally:
        root._turto_closing=True;root._mail_executor.shutdown(wait=False,cancel_futures=True)
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--source-worker' in sys.argv:source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-843-') as td:
            subprocess.run([sys.executable,'-B',__file__,'--source-worker',str(Path(td)/'source')],check=True,timeout=120)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],'--ui-worker',str(Path(td)/'ui')],check=True,timeout=150)
