#!/usr/bin/env python3
"""Dated ownership, shared directory edits and real Windows portfolio interaction."""
from contextlib import closing
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'ZakazkyApp_base_6.1'))
spec=importlib.util.spec_from_file_location('fixture840',REPO/'scripts/validate-840-portfolios-tasks-mail.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from price_lists_domain.platform import sales_centers as centers, portfolio_contacts as contacts, portfolio, user_access as access
from price_lists_domain.monthly_reports.db import Database
from price_lists_domain.monthly_reports.report_model import Analytics, collect_report
from price_lists_domain.monthly_reports.exports import export_excel
sql, rejects=fixture.sql,fixture.rejects


def prepare(td):
    M,settle=fixture.prepare(td);data=fixture.seed(M);access.refresh_session(M,'ADMIN')
    data['reps']={r['pohoda_center']:r['id'] for r in sql(M,'SELECT * FROM salespeople WHERE canonical_id IS NULL') if r['pohoda_center']}
    sql(M,"INSERT INTO people(name,email,phone,role,company_id) VALUES('841 Kontakt','kontakt841@example.test','123456789','',?)",(data['cid'],))
    data['pid']=sql(M,"SELECT id FROM people WHERE email='kontakt841@example.test'")[0][0]
    return M,settle,data


def signature(M,code):
    return [(r['id'],r['salesperson_id'],r['valid_from'],r['valid_to']) for r in centers.snapshot(M) if r['center']==code]


def source_checks(td):
    M,_,d=prepare(td);j,h=d['reps']['J'],d['reps']['H']
    before=centers.snapshot(M);M.ensure_schema();assert centers.snapshot(M)==before
    new=centers.save_person(M,None,'841 Nová obchodnice',True)
    assert sql(M,'SELECT person_id FROM salespeople WHERE id=?',(new,))[0][0]
    stale=signature(M,'J');centers.assign(M,'j',new,'2026-09-15',stale)
    rejects(lambda:centers.assign(M,'J',h,'2026-10-01',stale))
    rejects(lambda:centers.assign(M,'J',h,'2026-09-14',signature(M,'J')))
    centers.assign(M,'X',new,'2026-09-01',[])
    centers.assign(M,'X',None,'2026-09-25',signature(M,'X'))
    centers.assign(M,'H',new,'2027-01-01',signature(M,'H'))
    centers.save_person(M,j,'Jiří Cír',False,('Jiří Cír',1))
    mapping=centers.snapshot(M)
    with closing(M.db()) as con:
        assert centers.current(con,'2026-09-14')[j]=='J'
        assert centers.current(con,'2026-09-15')[new]=='J, X'
        assert centers.current(con,'2026-09-15')[h]=='H'
    db=Database(Path(td)/'reports.db');a=Analytics(db,center_provider=lambda:centers.snapshot(M))
    for no,day,code,value in [('old','2026-09-14','J',100),('new','2026-09-15','J',200),
                              ('extra','2026-09-20','X',300),('ended','2026-09-25','X',400),
                              ('unknown','2026-09-15','Z',500),('previous','2026-08-31','J',600),
                              ('future','2027-01-01','H',700)]:
        db.execute('INSERT INTO delivery_notes(doc_no,doc_date,center,base_amount) VALUES(?,?,?,?)',(no,day,code,value))
        db.execute('INSERT INTO profit_documents(doc_no,profit_total) VALUES(?,?)',(no,value/10))
    sales={r['name']:r for r in a.salespeople(2026,9)}
    assert sales['Jiří Cír']['revenue']==100 and sales['Jiří Cír']['profit']==10
    assert sales['841 Nová obchodnice']['revenue']==500 and sales['841 Nová obchodnice']['profit']==50
    assert sales['Nezařazené']['revenue']==900 and sales['Nezařazené']['profit']==90
    assert a.kpis(2026,9)['unassigned_revenue']==900
    assert a.kpis(2026,9)['unassigned_profit']==90
    assert sum(r['profit'] for r in a.salespeople(2026,9))==a.kpis(2026,9)['profit']
    assert next(r for r in a.salespeople(2026,8) if r['name']=='Jiří Cír')['revenue']==600
    assert next(r for r in a.salespeople(2027,1) if r['name']=='841 Nová obchodnice')['revenue']==700
    report=collect_report(a,2026,9)
    assert sum(r['revenue'] for r in report['unassigned'])==900
    assert next(r for r in report['documents'] if r['doc_no']=='old')['center_name']=='Jiří Cír · J'
    assert next(r for r in report['documents'] if r['doc_no']=='new')['center_name']=='841 Nová obchodnice · J'
    out=Path(td)/'report.xlsx';export_excel(out,a,2026,9)
    with zipfile.ZipFile(out) as z:
        xml=z.read('xl/sharedStrings.xml').decode()
        assert 'Jiří Cír · J' in xml and '841 Nová obchodnice · J' in xml
    # Legacy monthly totals must not be assigned wholesale across a mid-month handover.
    db.execute('DELETE FROM profit_documents')
    db.execute("INSERT INTO monthly_summary(period,profit_total,profit_j,profit_h,profit_m) VALUES('2026-09',120,80,30,10)")
    legacy={r['name']:r for r in a.salespeople(2026,9)}
    assert legacy['Nezařazené']['profit']==80 and legacy['Jan Mayer']['profit']==30
    assert sum(r['profit'] for r in legacy.values())==120
    assert a.kpis(2026,9)['unassigned_profit']==80
    # The address book and portfolio share IDs; stale/moved/deactivated contacts cannot be overwritten.
    original=contacts.rows(M,d['cid'])[0]
    contacts.save(M,d['cid'],d['pid'],'phone','987654321',original)
    assert sql(M,'SELECT phone FROM people WHERE id=?',(d['pid'],))[0][0]=='987654321'
    rejects(lambda:contacts.save(M,d['cid'],d['pid'],'name','Lost update',original))
    fresh=contacts.rows(M,d['cid'])[0]
    sql(M,'UPDATE people SET company_id=? WHERE id=?',(d['other'],d['pid']))
    rejects(lambda:contacts.save(M,d['cid'],d['pid'],'phone','Wrong firm',fresh))
    sql(M,'UPDATE people SET company_id=? WHERE id=?',(d['cid'],d['pid']))
    row=access.profile(M,d['ids']['840 Alena'])
    access.save_profile(M,row['id'],'Technická podpora',{'settings':1,'people':1,'portfolio':1},(row['job_title'],row['tab_permissions']))
    access.refresh_session(M,'840 Alena')
    rejects(lambda:centers.assign(M,'Y',new,'2026-09-01',[]))
    rejects(lambda:sql(M,"INSERT INTO sales_center_assignments(center,salesperson_id,valid_from) VALUES('Y',?,'2026-09-01')",(new,)))
    rejects(lambda:contacts.save(M,d['cid'],d['pid'],'phone','Denied',contacts.rows(M,d['cid'])[0]))
    access.refresh_session(M,'ADMIN');assert centers.snapshot(M)==mapping
    print('8.0.41: dated transfers/new centers/history, exact document attribution, legacy ambiguity, report/export totals, contact CAS and permissions OK',flush=True)


def ui_checks(td):
    M,settle,d=prepare(td);M.set_setting('active_user','ADMIN')
    portfolio.save(M,d['cid'],{d['reps']['J']},set())
    errors=[]
    M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.App.maybe_show_morning_overview=lambda self:None
    M.App.report_callback_exception=lambda self,*a:errors.append(str(a))
    root=M.App();root.report_callback_exception=lambda *a:errors.append(str(a))
    output=REPO/'build/validation/portfolio-841';output.mkdir(parents=True,exist_ok=True)
    def shot(name,window=root):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.3)
        ImageGrab.grab(bbox=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())).save(output/name)
    try:
        root.state('normal');root.geometry('1450x850+0+0');root.apply_theme('Světlý')
        root.show_page('portfolio');settle(root,1)
        w=root.portfolio_workspace;t=w.tree;cid=f"c{d['cid']}";pid=f"p{d['pid']}"
        assert t.get_children(cid)==(pid,)
        t.item(cid,open=True);t.selection_set(pid);t.focus(pid);t.see(pid);t.focus_force();settle(root)
        assert t.bbox(pid,'Společnost / kontakt')
        t.event_generate('<F2>');settle(root)
        assert w.editor.entry is not None
        w.editor.variable.set('841 Kontakt upravený');w.editor.entry.event_generate('<Return>');settle(root)
        assert sql(M,'SELECT name FROM people WHERE id=?',(d['pid'],))[0][0]=='841 Kontakt upravený'
        w.editor.begin(pid,'Telefon');settle(root);w.editor.variable.set('NEULOŽIT')
        w.editor.entry.event_generate('<Escape>');settle(root)
        assert sql(M,'SELECT phone FROM people WHERE id=?',(d['pid'],))[0][0]=='123456789'
        w.editor.begin(pid,'Telefon');settle(root);w.editor.variable.set('777888999')
        w.editor.entry.event_generate('<Tab>');settle(root)
        assert w.editor.column=='E-mail' and w.editor.entry is not None,(w.editor.column,w.editor.entry,root.focus_get(),errors)
        w.editor.variable.set('upraveny841@example.test');w.editor.entry.event_generate('<Return>');settle(root)
        assert sql(M,'SELECT phone,email FROM people WHERE id=?',(d['pid'],))[0][:]==('777888999','upraveny841@example.test')
        shot('contacts-light.png')
        root.apply_theme('Tmavý');settle(root);shot('contacts-dark.png');root.apply_theme('Světlý')
        # Address-book changes return into the same expanded company row.
        sql(M,"UPDATE people SET phone='111222333' WHERE id=?",(d['pid'],));w.refresh();settle(root)
        assert t.item(cid,'open') and t.set(pid,'Telefon')=='111222333'
        manager=w.manage_salespeople();settle(root)
        new=manager.edit_person();new.name_variable.set('841 Nový obchodník');new.save();settle(root)
        transfer=manager.assign_center();transfer.center_variable.set('J');transfer.rep_variable.set('841 Nový obchodník')
        transfer.date_variable.set('2026-10-01');transfer.save();settle(root)
        new_id=sql(M,"SELECT id FROM salespeople WHERE name='841 Nový obchodník'")[0][0]
        assert signature(M,'J')[-1][1:]==(new_id,'2026-10-01',None)
        shot('centers-history.png',manager);manager.destroy();settle(root)
        root.geometry('1220x720');settle(root);shot('contacts-narrow.png')
        root.show_page('reports_sales');settle(root,1)
        report_workspace=root._reports_workspace
        assert report_workspace.last_error is None
        assert report_workspace.analytics.center_display('J','2026-09-30')=='Jiří Cír · J'
        assert report_workspace.analytics.center_display('J','2026-10-01')=='841 Nový obchodník · J'
        assert not errors,errors
        print('8.0.41: real Windows expanded contacts, F2/Enter/Tab/Escape, bidirectional address-book edits, dated manager and embedded reports OK',flush=True)
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
        with tempfile.TemporaryDirectory(prefix='turto-841-') as td:
            subprocess.run([sys.executable,'-B',__file__,'--source-worker',str(Path(td)/'source')],check=True,timeout=120)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],'--ui-worker',str(Path(td)/'ui')],check=True,timeout=150)
