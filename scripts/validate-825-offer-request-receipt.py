#!/usr/bin/env python3
"""Receipt provenance, atomic assignment and the real Windows assignment dialog."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform.offer_request_receipt import assign_to_request, mail_date
from price_lists_domain.platform import project_activity


def source_checks():
    con = sqlite3.connect(':memory:')
    con.row_factory = sqlite3.Row
    con.executescript('''
        CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE actions(id INTEGER PRIMARY KEY,project_id INTEGER);
        CREATE TABLE requests(id INTEGER PRIMARY KEY,action_id INTEGER,company_id INTEGER,item TEXT,
            received_date TEXT DEFAULT '',no_response INTEGER DEFAULT 0,archived INTEGER DEFAULT 0,updated_by TEXT);
        CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,request_id INTEGER,project_id INTEGER,
            action_id INTEGER,offer_number TEXT,offer_date TEXT DEFAULT '2026-08-01',imported_at TEXT DEFAULT '2026-09-17');
        CREATE TABLE offer_source_messages(id INTEGER PRIMARY KEY,sent_at TEXT,imported_at TEXT DEFAULT '2026-09-17');
        CREATE TABLE offer_source_attachments(id INTEGER PRIMARY KEY,message_id INTEGER,offer_id INTEGER);
        CREATE TABLE action_history(id INTEGER PRIMARY KEY,action_id INTEGER,user_name TEXT,event_type TEXT,
            summary TEXT,details TEXT,related_company_id INTEGER,related_request_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO projects VALUES(1,'Akce A'),(2,'Akce B');
        INSERT INTO actions VALUES(10,1),(20,2);
        INSERT INTO requests(id,action_id,company_id,item,no_response) VALUES(100,10,1,'Izolační nosníky',1);
        INSERT INTO requests(id,action_id,item) VALUES(200,20,'Druhá poptávka'),(300,NULL,'Samostatná poptávka');
        INSERT INTO supplier_offers(id,offer_number) VALUES(1,'CN-1'),(2,'CN-2'),(3,'PDF'),(4,'Neplatné datum');
        INSERT INTO offer_source_messages(id,sent_at) VALUES(1,'2026-09-14 23:30:00'),
            (2,'2026-09-16T00:30:00+02:00'),(3,'Sat, 12 Sep 2026 23:50:00 +0200'),(4,'2026-02-30'),
            (5,'2020-01-01'),(6,'2026-09-17');
        INSERT INTO offer_source_attachments VALUES(1,1,1),(2,2,2),(3,3,2),(4,4,4),(5,5,NULL),(6,6,1);
    ''')
    project_activity.ensure_schema(con)
    con.commit()
    request = lambda rid: dict(con.execute('SELECT * FROM requests WHERE id=?', (rid,)).fetchone())
    assign = lambda oid, rid: assign_to_request(con, oid, rid, 'TEST USER')
    assert mail_date('2026-09-14T00:30:00+02:00') == '2026-09-14'
    assert mail_date('2026-09-14T23:30:00-07:00') == '2026-09-14'
    for invalid in ('', None, 'neznámé', '2026-02-30', '2026-09-99 09:00:00'):
        assert not mail_date(invalid), invalid
    with con:
        assert assign(1,100) == '2026-09-14'
    assert request(100)['no_response'] == 0 and request(100)['updated_by'] == 'TEST USER'
    assert request(200)['received_date'] == ''
    offer = con.execute('SELECT * FROM supplier_offers WHERE id=1').fetchone()
    assert (offer['request_id'],offer['project_id'],offer['action_id']) == (100,1,None)
    history = con.execute('SELECT * FROM action_history').fetchone()
    assert history['event_type'] == 'request_received' and history['related_request_id'] == 100
    assert '2026-09-14' in history['details'] and 'původního e-mailu' in history['details']
    assert con.execute('SELECT * FROM project_activity WHERE project_id=1').fetchone()
    # Repeated assignment creates neither a new receipt nor duplicate history/activity.
    with con:
        con.execute("UPDATE project_activity SET last_activity_at='2000-01-01'")
        assert assign(1,100) == '2026-09-14'
    assert con.execute('SELECT count(*) FROM action_history').fetchone()[0] == 1
    assert con.execute('SELECT last_activity_at FROM project_activity').fetchone()[0] == '2000-01-01'
    with con:
        assert assign(2,100) == '2026-09-12'  # Earliest actual mail, not import order.
        assert assign(1,100) == '2026-09-12'
        assert assign(1,200) == '2026-09-14'
    assert request(100)['received_date'] == '2026-09-12'  # Reassignment preserves prior receipt.
    with con:
        con.execute('UPDATE supplier_offers SET request_id=NULL,project_id=NULL WHERE id=1')
    assert request(200)['received_date'] == '2026-09-14'  # Unlink is not withdrawal of receipt.
    with con:
        assert assign(3,300) == ''  # PDF issue/import/today dates must never be substituted.
        assert assign(4,300) == ''  # Malformed source mail date also cannot invent receipt.
        con.execute("UPDATE requests SET received_date='2026-09-10',no_response=1 WHERE id=300")
        assert assign(3,300) == '2026-09-10'
    assert request(300)['no_response'] == 0
    # A previously manually entered import-day date is corrected from the mail.
    with con:
        con.execute("UPDATE requests SET received_date='2026-09-17' WHERE id=200")
        assert assign(1,200) == '2026-09-14'
    # Any write failure rolls back the link, receipt, history and activity together.
    before = list(con.iterdump())
    con.execute("CREATE TRIGGER fail_receipt BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'injected'); END")
    try:
        with con:
            assign(2,200)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('Receipt failure did not roll back assignment')
    con.execute('DROP TRIGGER fail_receipt')
    assert list(con.iterdump()) == before
    with con:
        con.execute('UPDATE requests SET archived=1 WHERE id=200')
    for oid,rid in ((1,999),(999,100),(1,200)):
        try:
            with con: assign(oid,rid)
        except ValueError: pass
        else: raise AssertionError('Missing/archived record accepted')
    con.close()
    print('8.0.25: source mail provenance, first receipt, date zones, no-response, repeat/reassign/unlink, missing dates, history/activity and atomic rollback OK', flush=True)


def settle(root,seconds=.4):
    end = time.monotonic()+seconds
    while time.monotonic()<end:
        root.update()
        time.sleep(.01)


def ui_checks(td):
    os.environ['TURTO_CRM_DATA_ROOT']=td
    os.environ['LOCALAPPDATA']=str(Path(td)/'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE']='1'
    import app, data_location, runtime_bootstrap, crm_features
    from price_lists_domain.platform.calm_theme_820 import walk
    data_location.apply_to_app(app)
    app.ensure_schema(); runtime_bootstrap.apply_all(app); app.ensure_schema(); app.ensure_test_user()
    app.App.maybe_show_morning_overview=lambda self:None
    errors=[]
    app.messagebox.showinfo=lambda *a,**k:None
    app.messagebox.showwarning=lambda *a,**k:None
    app.messagebox.showerror=lambda *a,**k:errors.append(str(a))
    root=app.App()
    root.report_callback_exception=lambda *exc:errors.append(str(exc))
    try:
        root.state('normal'); root.geometry('1200x850+0+0'); settle(root,4)
        with app.db() as con:
            pid=con.execute("INSERT INTO projects(name) VALUES('825 Akce')").lastrowid
            aid=con.execute("INSERT INTO actions(name,project_id) VALUES('825 Příležitost',?)",(pid,)).lastrowid
            rid=con.execute("INSERT INTO requests(action_id,item,asked_date,no_response) VALUES(?,'825 Izolační nosníky','2026-09-01',1)",(aid,)).lastrowid
            oid=con.execute("INSERT INTO supplier_offers(source_hash,offer_number,offer_date) VALUES('825-offer','CN825','2026-09-02')").lastrowid
            mid=con.execute("INSERT INTO offer_source_messages(source_hash,sent_at) VALUES('825-msg','2026-09-14 09:35:00')").lastrowid
            con.execute("INSERT INTO offer_source_attachments(message_id,offer_id,filename,content_hash) VALUES(?,?,'nabidka.pdf','825-att')",(mid,oid))
        root.show_page('requests'); settle(root)
        detail=crm_features.OfferDetailDialog(root,oid); settle(root)
        completed=[]
        def choose_request():
            try:
                dialog=next(w for w in walk(detail) if isinstance(w,app.tk.Toplevel) and w.title()=='Vazba nabídky')
                tree=next(w for w in walk(dialog) if isinstance(w,app.ttk.Treeview) and w.exists(str(rid)))
                tree.see(str(rid)); tree.selection_set(str(rid)); tree.focus(str(rid))
                tree.update_idletasks()
                box=tree.bbox(str(rid)); x,y=box[0]+30,box[1]+box[3]//2
                # Two native click sequences exercise the real double-click callback.
                for _ in range(2):
                    tree.event_generate('<ButtonPress-1>',x=x,y=y)
                    if not tree.winfo_exists():
                        break
                    tree.event_generate('<ButtonRelease-1>',x=x,y=y)
                completed.append(True)
            except Exception as exc:
                errors.append(repr(exc))
        root.after(400,choose_request)
        # A broken callback must fail this test rather than hang the Windows build.
        def timeout():
            for w in list(walk(detail)):
                if isinstance(w,app.tk.Toplevel) and w is not detail:
                    errors.append('Assignment dialog did not close'); w.destroy()
        timer=root.after(5000,timeout)
        next(w for w in walk(detail) if isinstance(w,app.ttk.Button) and str(w.cget('text'))=='Změnit přiřazení…').invoke()
        root.after_cancel(timer); settle(root)
        assert completed and not errors,errors
        with app.db() as con:
            r=con.execute('SELECT received_date,no_response FROM requests WHERE id=?',(rid,)).fetchone()
            assert tuple(r)==('2026-09-14',0),tuple(r)
        detail.destroy(); root.show_page('requests'); settle(root)
        assert root.request_tree.set('r'+str(rid),'Stav')=='Obdrženo'
        assert root.request_tree.set('r'+str(rid),'Obdrženo')==app.fmt_date('2026-09-14')
        assert not errors,errors
        print('8.0.25: real Windows offer detail -> assignment double-click -> receipt/status/history and refreshed Requests OK',flush=True)
    finally:
        root._turto_closing=True; root.destroy()


if __name__=='__main__':
    source_checks()
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-825-',ignore_cleanup_errors=True) as td:
            ui_checks(td)
