#!/usr/bin/env python3
"""Canonical map data, conservative offline geocoding and real Windows host/UI."""
from contextlib import closing
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.maps import model, ruian
from price_lists_domain.platform import user_access as access


def prepare(td):
    spec=importlib.util.spec_from_file_location('prior',REPO/'scripts/validate-827-processing-catalogs.py')
    previous=importlib.util.module_from_spec(spec); spec.loader.exec_module(previous)
    return previous.prepare(td,runtime=True), previous.settle


def rejects(callback):
    try: callback()
    except (ValueError,sqlite3.Error): return
    raise AssertionError('A stale, invalid or unauthorized write was accepted')


def seed(M):
    with closing(M.db()) as con,con:
        con.execute("INSERT INTO users(name) VALUES('835 Editor'),('835 Reader')")
        cid=con.execute("INSERT INTO companies(short_name,official_name,address,gps_coordinates) VALUES('835 Firma','835 Firma s.r.o.','Testovací 10, 11000 Praha','50.087, 14.421')").lastrowid
        cid2=con.execute("INSERT INTO companies(short_name,official_name,address) VALUES('835 Jiná','835 Jiná s.r.o.','Jiná 20, 60200 Brno')").lastrowid
        project=con.execute("INSERT INTO projects(name,address,gps_coordinates,start_date,end_date,map_phase,map_supplying) VALUES('835 Stavba','Testovací 10, 11000 Praha','50.08, 14.42','2026-10-01','2027-05-01','Probíhá',1)").lastrowid
        completed=con.execute("INSERT INTO projects(name,gps_coordinates,start_date,map_phase) VALUES('835 Ukončeno','49.2, 16.6','2026-09-01','Ukončeno')").lastrowid
        cancelled=con.execute("INSERT INTO projects(name,map_phase) VALUES('835 Zrušeno','Zrušeno')").lastrowid
        target=con.execute("INSERT INTO projects(name) VALUES('835 Cíl')").lastrowid
        action=con.execute("INSERT INTO actions(name,company_id,project_id) VALUES('835 Technika',?,?)",(cid,project)).lastrowid
        order=con.execute("INSERT INTO business_documents(document_type,direction,company_id,project_id,document_number,status) VALUES('received_order','received',?,?,'835-O1','Vyřízeno')",(cid,completed)).lastrowid
        offer=con.execute("INSERT INTO supplier_offers(supplier_company_id,project_id,offer_number) VALUES(?,?,'835-R1')",(cid,project)).lastrowid
    return dict(cid=cid,cid2=cid2,project=project,completed=completed,cancelled=cancelled,target=target,action=action,order=order,offer=offer)


def source_checks(td):
    M,_=prepare(td); ids=seed(M)
    access.refresh_session(M,'835 Editor')
    def sql(query,args=()):
        with closing(M.db()) as con,con: return con.execute(query,args).fetchall()
    before=sql('SELECT id,name,address,gps_coordinates,start_date,end_date,map_phase FROM projects ORDER BY id')
    M.ensure_schema(); M.ensure_schema()
    assert [tuple(r) for r in before]==[tuple(r) for r in sql('SELECT id,name,address,gps_coordinates,start_date,end_date,map_phase FROM projects ORDER BY id')]
    sql('UPDATE companies SET official_name=? WHERE id=?',('835 Firma s.r.o.',ids['cid2']))
    projects=model.rows(M,layer='project')
    assert len({r['key'] for r in projects})==len(projects)
    assert [r['id'] for r in model.rows(M,layer='project',supplying=True)]==[ids['project']]
    assert [r['id'] for r in model.rows(M,layer='project',phase='Ukončeno')]==[ids['completed']]
    assert [r['id'] for r in model.rows(M,layer='project',start_from='1.10.2026',start_to='1.10.2026')]==[ids['project']]
    rejects(lambda:model.rows(M,start_from='32.1.2026'))
    rejects(lambda:model.rows(M,start_from='2026-12-01',start_to='2026-01-01'))
    assert {r['id'] for r in model.rows(M,layer='project',company_id=ids['cid'])}=={ids['project'],ids['completed']}
    assert not model.rows(M,layer='project',company_id=ids['cid2']), 'Same names were joined instead of IDs'
    row=model.record(M,'company',ids['cid']); expected=model.snapshot(row)
    model.save_location(M,'company',ids['cid'],'50.09, 14.43',expected)
    rejects(lambda:model.save_location(M,'company',ids['cid'],'49.0, 15.0',expected))
    current=model.record(M,'company',ids['cid'])
    for bad in ('NaN,14','91,14','50,181','inf,14'):
        rejects(lambda value=bad:model.save_location(M,'company',ids['cid'],value,model.snapshot(current)))
    sql('UPDATE companies SET official_name=? WHERE id=?',('835 Přejmenovaná',ids['cid']))
    assert next(r for r in model.rows(M) if r['key']==f"company:{ids['cid']}")['title']=='835 Přejmenovaná'
    sql('UPDATE companies SET address=? WHERE id=?',('Nová 77, 60200 Brno',ids['cid']))
    changed=model.record(M,'company',ids['cid'])
    assert model.location_state(M,changed)[1] is None and changed['gps_coordinates']==current['gps_coordinates']
    rejects(lambda:model.save_location(M,'company',ids['cid'],'50,15',model.snapshot(current)))
    model.save_location(M,'company',ids['cid'],'49.2,16.6',model.snapshot(changed))
    assert model.location_state(M,model.record(M,'company',ids['cid']))[0]=='Umístěno'
    access.refresh_session(M,'ADMIN')
    uid=sql("SELECT id FROM users WHERE name='835 Reader'")[0][0]
    permissions={'companies':0,'projects':1,'map':1,'actions':0,'received_orders':0,'issued_offers':0}
    access.save_profile(M,uid,'',permissions,('','{}'))
    access.refresh_session(M,'835 Reader')
    rows=model.rows(M)
    assert all(r['kind']=='project' and not r['companies'] and not r['company_ids'] for r in rows)
    assert '835 Přejmenovaná' not in json.dumps(model.features(rows),ensure_ascii=False)
    rejects(lambda:model.record(M,'company',ids['cid']))
    project=model.record(M,'project',ids['project'])
    rejects(lambda:model.save_location(M,'project',ids['project'],'50,15',model.snapshot(project)))
    rejects(lambda:sql('UPDATE projects SET gps_coordinates=? WHERE id=?',('50,15',ids['project'])))
    access.refresh_session(M,'835 Editor')
    # A failed multi-table merge must roll back even the first moved link.
    access.refresh_session(M,'ADMIN')
    profile=access.profile(M,uid)
    access.save_profile(M,uid,'',{'offers':1},(profile['job_title'],profile['tab_permissions']))
    access.refresh_session(M,'835 Reader')
    rejects(lambda:model.merge_projects(M,ids['project'],ids['target']))
    assert sql('SELECT project_id FROM actions WHERE id=?',(ids['action'],))[0][0]==ids['project']
    access.refresh_session(M,'835 Editor')
    model.merge_projects(M,ids['project'],ids['target'],'835 Editor')
    assert sql('SELECT project_id FROM actions WHERE id=?',(ids['action'],))[0][0]==ids['target']
    assert sql('SELECT project_id FROM supplier_offers WHERE id=?',(ids['offer'],))[0][0]==ids['target']
    assert ids['project'] not in {r['id'] for r in model.rows(M,layer='project')}
    assert ids['target'] in {r['id'] for r in model.rows(M,layer='project',company_id=ids['cid'])}
    # Company merge must retain target coordinates/address as one coherent unit.
    M.merge_company_records(ids['cid'],ids['cid2'],'835 Editor')
    target=model.record(M,'company',ids['cid2'])
    assert not target['gps_coordinates'], 'A pin was copied from a different headquarters'
    assert sql('SELECT company_id FROM actions WHERE id=?',(ids['action'],))[0][0]==ids['cid2']
    assert len(model.rows(M,layer='company',query='835'))==1
    geocoder_checks(td)
    print('8.0.35: additive schema, stable IDs, filters, address invalidation, CAS, hidden/read-only data, atomic merges and offline RÚIAN OK',flush=True)


def geocoder_checks(td):
    header=['Kód ADM','Název obce','Název ulice','Číslo domovní','Číslo orientační','Znak čísla orientačního','Typ SO','PSČ','Souřadnice Y','Souřadnice X']
    content=io.StringIO(); writer=csv.writer(content,delimiter=';',lineterminator='\n'); writer.writerow(header)
    writer.writerow(['100','Praha','Testovací','10','','','č.p.','11000','742000','1043000'])
    writer.writerow(['101','Praha','Dvojitá','12','3','','č.p.','11000','742000','1043000'])
    writer.writerow(['102','Praha','Dvojitá','12','3','','č.p.','11000','742100','1043100'])
    source=Path(td)/'ruian.zip'
    with zipfile.ZipFile(source,'w') as archive: archive.writestr('../../not-extracted.csv',content.getvalue().encode('cp1250'))
    assert ruian.import_zip(source)==3
    match=ruian.lookup('Testovací 10, 110 00 Praha, Česká republika')
    assert len(match)==1 and match[0]['code']=='100'
    lat,lon=map(float,match[0]['gps'].split(','))
    assert 50.0<lat<50.2 and 14.3<lon<14.6, 'S-JTSK axis order/sign is wrong'
    assert len(ruian.lookup('Dvojitá 12/3, Praha 11000'))==2
    assert not ruian.lookup('Dvojitá 3/12, Praha 11000'), 'House and orientation numbers reversed'
    assert not ruian.lookup('Testovací 11, 11000 Praha')
    assert not (Path(td)/'not-extracted.csv').exists()
    digest=hashlib.sha256(ruian.index_path().read_bytes()).hexdigest()
    with zipfile.ZipFile(source,'w') as archive: archive.writestr('bad.csv','Not a RUIAN dataset')
    rejects(lambda:ruian.import_zip(source))
    assert hashlib.sha256(ruian.index_path().read_bytes()).hexdigest()==digest
    assert not ruian.allowed_url('https://vdp.cuzk.gov.cz.evil.test/addresses.zip')


def ui_checks(td):
    import faulthandler
    faulthandler.dump_traceback_later(140,exit=True)
    M,settle=prepare(td); ids=seed(M)
    M.set_setting('active_user','835 Editor')
    M.App.maybe_show_morning_overview=lambda self:None
    errors=[]; warnings=[]
    M.messagebox.showerror=lambda *a,**k:errors.append(str(a))
    M.messagebox.showwarning=lambda *a,**k:warnings.append(str(a))
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.askyesno=lambda *a,**k:True
    print('835 UI: constructing CRM',flush=True)
    root=M.App(); root.geometry('1420x980+0+0')
    root.report_callback_exception=lambda kind,value,tb:errors.append(str(value))
    output=REPO/'build/validation/map-835'; output.mkdir(parents=True,exist_ok=True)
    try:
        root.select_user('835 Editor'); settle(root,.5)
        print('835 UI: opening map',flush=True)
        root.show_page('map'); workspace=root.map_workspace
        deadline=time.monotonic()+70
        while time.monotonic()<deadline and workspace.last_applied_count is None:
            settle(root,.1)
        assert workspace.bridge is not None, workspace.status.get()
        assert workspace.last_applied_count is not None, workspace.status.get()
        assert workspace.embedded
        print('835 UI: native host embedded and JSON delivered',flush=True)
        assert len(workspace.records)>=6
        workspace.tree.selection_set(f"project:{ids['project']}"); settle(root)
        workspace.gps.set('50.1, 14.5'); workspace.save_gps(); settle(root)
        assert model.point(M,model.record(M,'project',ids['project'])['gps_coordinates'])==[14.5,50.1]
        # Existing forms and map read and write exactly the same columns.
        dialog=M.ProjectDialog(root,ids['project']); settle(root)
        print('835 UI: editing original project form',flush=True)
        assert model.point(M,dialog.vars['gps_coordinates'].get())==[14.5,50.1]
        dialog.vars['map_phase'].set('Ukončeno'); dialog.map_supplying.set(False); dialog.ok(); settle(root)
        assert not dialog.winfo_exists()
        workspace.phase.set('Ukončeno'); workspace.layer.set('Akce'); workspace.refresh(); settle(root)
        assert set(workspace.records)=={f"project:{ids['project']}",f"project:{ids['completed']}"}
        workspace.reset(); workspace.layer.set('Obojí'); workspace.refresh()
        dialog=M.CompanyDialog(root,ids['cid']); settle(root)
        print('835 UI: editing original company form',flush=True)
        dialog.vars['gps_coordinates'].set('49.21, 16.61'); dialog.ok(); settle(root)
        assert not dialog.winfo_exists()
        assert model.point(M,model.record(M,'company',ids['cid'])['gps_coordinates'])==[16.61,49.21]
        # A stale form cannot undo a map edit made after it opened.
        dialog=M.ProjectDialog(root,ids['project']); settle(root)
        project=model.record(M,'project',ids['project'])
        model.save_location(M,'project',ids['project'],'50.2,14.6',model.snapshot(project))
        dialog.ok(); assert dialog.winfo_exists(); dialog.destroy(); warnings.clear()
        root.show_page('map'); settle(root,1)
        deadline=time.monotonic()+30
        while not workspace.loaded and time.monotonic()<deadline: settle(root,.1)
        online_loaded=workspace.loaded
        from PIL import ImageGrab
        ImageGrab.grab().save(output/'map-workspace.png')
        assert online_loaded, 'Online OpenFreeMap did not render: '+workspace.status.get()
        print('835 UI: online map rendered; switching user',flush=True)
        # User switch destroys the previous renderer and empties inaccessible data.
        old_host=workspace.bridge.process
        with closing(M._user_access_connect()) as con,con:
            con.execute("UPDATE users SET tab_permissions=? WHERE name='835 Reader'",(json.dumps({'companies':0,'projects':1,'map':1}),))
        root.select_user('835 Reader'); settle(root,.8)
        assert old_host.poll() is not None
        assert all(r['kind']=='project' for r in workspace.records.values())
        workspace.tree.selection_set(f"project:{ids['project']}"); settle(root)
        assert str(workspace.save_button.cget('state'))=='disabled'
        root.show_page('dash'); settle(root)
        assert root._current_page=='dash'
        assert not errors,errors
        assert not warnings,warnings
        print('8.0.35: real Tk tab, embedded WebView2/MapLibre bridge, original dialogs, stale save, permissions, user switch and cleanup OK',flush=True)
        (output/'map-report.json').write_text(json.dumps({'ok':True,'online_basemap_loaded':online_loaded},indent=2),encoding='utf-8')
    finally:
        if root.map_workspace.bridge: root.map_workspace.bridge.close()
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')): root.tk.call('after','cancel',job)
        root.destroy()
        faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':
    if '--source-worker' in sys.argv: source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv: ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-map-835-') as td:
            subprocess.run([sys.executable,__file__,'--source-worker',td],check=True)
        if '--source-only' not in sys.argv:
            with tempfile.TemporaryDirectory(prefix='turto-map-ui-835-') as td:
                subprocess.run([sys.executable,__file__,'--ui-worker',td],check=True,timeout=155)
