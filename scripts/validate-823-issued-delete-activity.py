#!/usr/bin/env python3
"""Transactional offer deletion, project-wide activity and real Windows controls."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import project_activity as activity
from price_lists_domain.issued_offers import service


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def source_checks(td):
    def db():
        con = sqlite3.connect(Path(td)/'source.db', factory=Connection)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con
    M = SimpleNamespace(db=db, get_setting=lambda key, default='': 'TEST')
    pdf = Path(td)/'retained.pdf'
    pdf.write_bytes(b'%PDF-1.4 retained exported document')
    with db() as con:
        con.executescript('''
            CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT,created_at TEXT,updated_at TEXT,start_date TEXT,end_date TEXT);
            CREATE TABLE actions(id INTEGER PRIMARY KEY,project_id INTEGER,name TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,action_id INTEGER,item TEXT,asked_date TEXT,received_date TEXT,updated_at TEXT);
            CREATE TABLE tasks(id INTEGER PRIMARY KEY,action_id INTEGER,text TEXT,due_date TEXT,done INTEGER,created_at TEXT,updated_at TEXT);
            CREATE TABLE action_history(id INTEGER PRIMARY KEY,action_id INTEGER,user_name TEXT,event_type TEXT,summary TEXT,details TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,project_id INTEGER,request_id INTEGER,action_id INTEGER,note TEXT,imported_at TEXT,updated_at TEXT,offer_date TEXT);
            CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,quantity REAL);
            CREATE TABLE business_documents(id INTEGER PRIMARY KEY,document_type TEXT,direction TEXT,document_number TEXT,
                project_id INTEGER,action_id INTEGER,customer_name_snapshot TEXT,status TEXT,revision_no INTEGER,archived INTEGER,
                created_at TEXT,updated_at TEXT,last_pdf_path TEXT);
            CREATE TABLE business_document_items(id INTEGER PRIMARY KEY,document_id INTEGER REFERENCES business_documents(id) ON DELETE CASCADE,name TEXT,quantity REAL);
            CREATE TABLE business_document_revisions(id INTEGER PRIMARY KEY,document_id INTEGER REFERENCES business_documents(id) ON DELETE CASCADE,
                revision_no INTEGER,pdf_path TEXT,pdf_sha256 TEXT,created_at TEXT);
            CREATE TABLE business_document_history(id INTEGER PRIMARY KEY,document_id INTEGER REFERENCES business_documents(id) ON DELETE CASCADE,note TEXT,created_at TEXT);
            CREATE TABLE audit_history(id INTEGER PRIMARY KEY,user_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,old_value TEXT,new_value TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE document_sequences(document_type TEXT,calendar_year INTEGER,last_number INTEGER);
            INSERT INTO projects VALUES(1,'Akce A','2000-01-01','','2099-01-01','2099-12-31');
            INSERT INTO projects VALUES(2,'Akce B','2000-01-01','','','');
            INSERT INTO projects VALUES(3,'Nesouvisející','2000-01-01','','','');
            INSERT INTO actions VALUES(1,1,'Příležitost A','2001-01-01','');
            INSERT INTO actions VALUES(2,2,'Příležitost B','2001-01-01','');
            INSERT INTO requests VALUES(1,1,'Poptávka A','2002-01-01','','');
            INSERT INTO requests VALUES(2,2,'Poptávka B','2002-01-01','','');
            INSERT INTO tasks VALUES(1,1,'Úkol','2099-01-01',0,'2003-01-01','');
            INSERT INTO supplier_offers VALUES(1,1,NULL,2,'Přímá vazba','2004-01-01','2007-01-01','2099-01-01');
            INSERT INTO supplier_offers VALUES(2,1,2,NULL,'Poptávka rozhoduje','2004-01-01','2008-01-01','');
            INSERT INTO supplier_offers VALUES(3,NULL,NULL,2,'Pouze neautoritativní stará vazba','2010-01-01','','');
            INSERT INTO supplier_offer_items VALUES(1,1,2);
            INSERT INTO business_documents VALUES(8,'issued_offer','issued','CN26-00008',1,1,'Odběratel','Odesláno',2,1,'2005-01-01','','');
            INSERT INTO business_documents VALUES(9,'issued_offer','received','OTHER',3,NULL,'Jiný','Hotovo',0,0,'2000-01-01','','');
            INSERT INTO business_documents VALUES(10,'issued_order','issued','ORDER',3,NULL,'Jiný','Hotovo',0,0,'2000-01-01','','');
            INSERT INTO business_document_items VALUES(1,8,'Položka',5);
            INSERT INTO business_document_history VALUES(1,8,'Odesláno','2006-01-01');
            INSERT INTO document_sequences VALUES('issued_offer',2026,8);
        ''')
        con.execute("INSERT INTO business_document_revisions VALUES(1,8,2,?,'hash','2006-09-16T01:00:00')", (str(pdf),))
        con.execute("UPDATE business_documents SET updated_at='2006-09-16 23:00:00' WHERE id=8")
        # Before upgrade: direct supplier projects and request ownership count;
        # bare legacy action links and future business/planning dates do not.
        union = activity.activity_union(con)
        latest = lambda pid: con.execute(f'WITH a AS ({union}) SELECT MAX(activity_at) FROM a WHERE project_id=?',(pid,)).fetchone()[0]
        assert latest(1) == '2007-01-01 00:00:00', latest(1)
        assert latest(2) == '2008-01-01 00:00:00', latest(2)
        ts = activity.timestamp('d', activity.columns(con,'business_documents'), ('created_at','updated_at'))
        assert con.execute(f'SELECT {ts} FROM business_documents d WHERE id=8').fetchone()[0] == '2006-09-16 23:00:00'
        activity.ensure_schema(con)
        activity.ensure_schema(con)
        assert not con.execute('SELECT * FROM project_activity').fetchall(), 'migration invented activity'
        assert latest(1) == '2007-01-01 00:00:00'

    marker = '1999-01-01 00:00:00'
    def reset():
        with db() as con:
            con.executemany('INSERT OR REPLACE INTO project_activity VALUES(?,?)',[(i,marker) for i in (1,2,3)])
    def changed():
        with db() as con:
            return {r['project_id'] for r in con.execute('SELECT * FROM project_activity') if r['last_activity_at'] != marker}
    for sql, expected in (
        ("UPDATE projects SET name='Akce A upravená' WHERE id=1", {1}),
        ("UPDATE actions SET name='Příležitost upravená' WHERE id=1", {1}),
        ("UPDATE requests SET item='Poptávka upravená' WHERE id=1", {1}),
        ("UPDATE tasks SET done=1 WHERE id=1", {1}),
        ("UPDATE supplier_offers SET note='Upravená přímá nabídka' WHERE id=1", {1}),
        ("UPDATE supplier_offer_items SET quantity=3 WHERE id=1", {1}),
        ("UPDATE business_document_items SET quantity=6 WHERE id=1", {1}),
        ("INSERT INTO business_document_history VALUES(2,8,'Změna','2006-01-02')", {1}),
        ("UPDATE business_document_revisions SET pdf_sha256='new' WHERE id=1", {1}),
        ("UPDATE supplier_offers SET project_id=2 WHERE id=1", {1,2}),
        ("UPDATE requests SET action_id=2 WHERE id=1", {1,2}),
        ("DELETE FROM tasks WHERE id=1", {1}),
    ):
        reset()
        with db() as con: con.execute(sql)
        assert changed() == expected, (sql, changed())
    reset()
    with db() as con:
        con.execute('UPDATE projects SET name=name WHERE id=1')
        con.execute('SELECT * FROM business_documents').fetchall()
        con.execute("UPDATE projects SET updated_at='2000-01-01' WHERE id=1")
    assert not changed(), 'no-op/read/metadata stamped ledger'
    reset()
    try:
        with db() as con:
            con.execute("UPDATE projects SET name='rolled back' WHERE id=1")
            raise ValueError('rollback')
    except ValueError:
        pass
    assert not changed()

    # A failure after child deletion must restore the document, every child,
    # audit entries and activity stamps in the same transaction.
    with db() as con:
        con.execute("CREATE TRIGGER block_delete BEFORE DELETE ON business_documents BEGIN SELECT RAISE(ABORT,'test failure'); END")
    try:
        service.delete_document(M, 8)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('injected deletion failure did not abort')
    with db() as con:
        assert con.execute('SELECT count(*) FROM business_document_items WHERE document_id=8').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM business_document_revisions WHERE document_id=8').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM business_document_history WHERE document_id=8').fetchone()[0] == 2
        assert not con.execute('SELECT * FROM audit_history').fetchall()
        con.execute('DROP TRIGGER block_delete')
    assert not changed()
    assert not service.delete_document(M, 9) and not service.delete_document(M, 10)
    assert service.delete_document(M, 8) and not service.delete_document(M, 8)
    assert changed() == {1}
    with db() as con:
        for table in ('business_document_items','business_document_history','business_document_revisions'):
            assert not con.execute(f'SELECT * FROM {table} WHERE document_id=8').fetchall()
        assert len(con.execute('SELECT * FROM business_documents').fetchall()) == 2
        assert con.execute('SELECT last_number FROM document_sequences').fetchone()[0] == 8
        audit = con.execute('SELECT * FROM audit_history').fetchone()
        assert audit['entity_type'] == 'Vydaná nabídka' and json.loads(audit['old_value'])['document_number'] == 'CN26-00008'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
        assert con.execute('SELECT count(*) FROM supplier_offers').fetchone()[0] == 3
    assert pdf.read_bytes() == b'%PDF-1.4 retained exported document'
    for i, status in enumerate(service.STATUSES, 20):
        with db() as con:
            con.execute("INSERT INTO business_documents(id,document_type,direction,document_number,project_id,status,revision_no,archived) VALUES(?,'issued_offer','issued',?,1,?,2,1)", (i,'CN'+str(i),status))
        assert service.delete_document(M,i), status
    print('8.0.23: canonical ownership/history, no false migration/reads, transactional activity, reassignment/deletion, all offer statuses, rollback, audit/PDF/sequence preservation OK', flush=True)


def settle(root, seconds=.35):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        root.update()
        time.sleep(.01)


def ui_checks(td):
    os.environ['TURTO_CRM_DATA_ROOT']=td
    os.environ['LOCALAPPDATA']=str(Path(td)/'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE']='1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.issued_offers import page
    from price_lists_domain.platform.calm_theme_820 import walk
    from v760_table_activity_performance import LAST_ACTIVITY_COLUMN, LAST_ACTIVITY_LABEL
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview=lambda self:None
    app.messagebox.showinfo=lambda *a,**k:None
    app.messagebox.showwarning=lambda *a,**k:None
    root=app.App()
    errors=[]
    root.report_callback_exception=lambda *exc:errors.append(str(exc))
    try:
        root.state('normal'); root.geometry('1240x840+0+0'); settle(root,4)
        with app.db() as con:
            pid=con.execute("INSERT INTO projects(name) VALUES('823 Aktivita')").lastrowid
            oid=con.execute("INSERT INTO business_documents(document_type,direction,document_number,project_id,status,revision_no,locked) VALUES('issued_offer','issued','CN823-DELETE',?,'Odesláno',2,1)",(pid,)).lastrowid
        root.show_page('projects'); settle(root,.7)
        t=root.project_tree
        assert t.heading(LAST_ACTIVITY_COLUMN,'text').rstrip(' ▲▼')==LAST_ACTIVITY_LABEL
        assert t.set('p'+str(pid),LAST_ACTIVITY_COLUMN) != '—'
        for col in (LAST_ACTIVITY_COLUMN,'Název Akce',LAST_ACTIVITY_COLUMN):
            root.sort_tree(t,col); settle(root,.1)
            assert t.heading(LAST_ACTIVITY_COLUMN,'text').rstrip(' ▲▼')==LAST_ACTIVITY_LABEL
        # The legacy ID must still own saved widths/visibility, and the column
        # settings surface must show only the new user-facing label.
        t._turto_design_widths[LAST_ACTIVITY_COLUMN]=237
        visible=tuple(c for c in t.cget('columns') if c!=LAST_ACTIVITY_COLUMN)
        t.configure(displaycolumns=visible)
        app.save_persistent_tree_layout(t); root.refresh_projects(); settle(root,.7)
        assert t.heading(LAST_ACTIVITY_COLUMN,'text').rstrip(' ▲▼')==LAST_ACTIVITY_LABEL
        assert LAST_ACTIVITY_COLUMN not in t.cget('displaycolumns')
        assert t._turto_design_widths[LAST_ACTIVITY_COLUMN]==237
        before=set(w for w in walk(root) if isinstance(w,app.tk.Toplevel))
        app.open_tree_columns_dialog(t); settle(root)
        dialog=next(w for w in walk(root) if isinstance(w,app.tk.Toplevel) and w not in before)
        listing=next(w for w in walk(dialog) if isinstance(w,app.ttk.Treeview))
        labels=[str(listing.item(i,'values')[1]) for i in listing.get_children()]
        assert LAST_ACTIVITY_LABEL in labels and LAST_ACTIVITY_COLUMN not in labels,labels
        dialog.destroy()

        root.show_page('issued_offers'); settle(root)
        tree=root.issued_offer_tree; iid='bo'+str(oid)
        tree.selection_set(iid)
        button=next(w for w in walk(root.tabs['issued_offers']) if isinstance(w,app.ttk.Button) and w.cget('text')=='Smazat nabídku…')
        prompts=[]
        app.messagebox.askyesno=lambda *a,**k:(prompts.append((a,k)) or False)
        button.invoke(); settle(root)
        assert tree.exists(iid) and 'CN823-DELETE' in prompts[-1][0][1]
        assert prompts[-1][1]['default']=='no'
        menu=root._v780_issued_context_menu
        index=next(i for i in range(menu.index('end')+1) if menu.type(i)=='command' and menu.entrycget(i,'label')=='Smazat nabídku…')
        app.messagebox.askyesno=lambda *a,**k:True
        menu.invoke(index); settle(root)
        assert not tree.exists(iid)
        with app.db() as con:
            assert not con.execute('SELECT 1 FROM business_documents WHERE id=?',(oid,)).fetchone()
            assert con.execute('SELECT last_activity_at FROM project_activity WHERE project_id=?',(pid,)).fetchone()
            before_activity=list(con.execute('SELECT * FROM project_activity ORDER BY project_id'))
        root.refresh_projects(); root.refresh_issued_offers(); settle(root)
        with app.db() as con:
            assert list(map(tuple,con.execute('SELECT * FROM project_activity ORDER BY project_id')))==list(map(tuple,before_activity))
        assert not errors,errors
        print('8.0.23: Windows label/sort/column settings and saved layout, cancel/confirm issued-offer deletion via live button/context menu, immediate refresh and idle activity OK',flush=True)
    finally:
        root._turto_closing=True
        root.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='turto-823-source-',ignore_cleanup_errors=True) as td:
        source_checks(td)
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-823-ui-',ignore_cleanup_errors=True) as td:
            ui_checks(td)
