#!/usr/bin/env python3
"""Company identity, explicit name decisions, real CRM merges and Windows forms."""
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.monthly_reports.company_links import CompanyLinks, ensure_schema, name_key
from price_lists_domain.monthly_reports.storage import ReportingStore


class LinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'crm.db'
        self.store = ReportingStore(self.path)
        self.reports = self.store.database
        with closing(self.connect()) as con, con:
            con.execute('''CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT,
                ico TEXT DEFAULT '',address TEXT DEFAULT '',active INTEGER DEFAULT 1,merged_into_company_id INTEGER)''')
            con.execute('''INSERT INTO companies(id,official_name) VALUES
                (1,'Česká firma, s. r. o.'),(2,'Dvojí a.s.'),(3,'DVOJÍ, a. s.'),
                (4,'Jiná firma s.r.o.'),(5,'Archiv s.r.o.')''')
            con.execute('UPDATE companies SET active=0 WHERE id=5')
            ensure_schema(con);ensure_schema(con)
        self.links = CompanyLinks(self.connect,self.reports,'Alena')
    def connect(self):
        con=sqlite3.connect(self.path);con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        return con
    def tearDown(self):self.temp.cleanup()
    def test_conservative_name_normalization(self):
        self.assertEqual(name_key(' ČESKÁ\u00a0 firma, s. r. o. '),name_key('Česká firma s.r.o.'))
        for a,b in [('AB','A B'),('Žák','Zak'),('ABC a.s.','ABC s.r.o.'),('ABC','ABC Holding'),('A-B','A B')]:
            self.assertNotEqual(name_key(a),name_key(b))
    def test_unique_ambiguous_unmatched_and_archived(self):
        rows=self.links.resolve(['česká firma s.r.o.','Dvojí a.s.','Ceska firma','Česká','Archiv s.r.o.',''])
        self.assertEqual(rows['česká firma s.r.o.']['company_id'],1)
        self.assertEqual(rows['Dvojí a.s.']['status'],'ambiguous')
        self.assertEqual(rows['Dvojí a.s.']['candidates'],[2,3])
        self.assertEqual(rows['Ceska firma']['status'],'unmatched')
        self.assertEqual(rows['Česká']['status'],'unmatched')
        self.assertEqual(rows['Archiv s.r.o.']['company_id'],5)
        self.assertEqual(rows['']['status'],'empty')
        with closing(self.connect()) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM report_company_links').fetchone()[0],2)
    def test_manual_exclusion_reset_and_stale_form(self):
        name='Dvojí a.s.'
        self.links.save(name,3,'manual',None)
        row=self.links.resolve([name])[name]
        self.assertEqual(row['company_id'],3)
        with self.assertRaises(ValueError):self.links.save(name,2,'manual',None)
        self.links.save(name,None,'ignored',row['token'])
        row=self.links.resolve([name])[name]
        self.assertEqual(row['status'],'ignored');self.assertIsNone(row['company_id'])
        self.links.save(name,None,'reset',row['token'])
        self.assertEqual(self.links.resolve([name])[name]['status'],'ambiguous')
        with self.assertRaises(ValueError):self.links.save('Nová',999,'manual',None)
        with self.assertRaises(ValueError):self.links.save('',1,'manual',None)
        with closing(self.connect()) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM companies').fetchone()[0],5)
    def test_id_survives_rename_and_import_variants(self):
        name='česká firma s.r.o.'
        self.assertEqual(self.links.resolve([name])[name]['company_id'],1)
        with closing(self.connect()) as con, con:
            con.execute("UPDATE companies SET official_name='Nový název a.s.' WHERE id=1")
        rows=self.links.resolve([name,'ČESKÁ FIRMA, s. r. o.','Nový název a.s.'])
        self.assertEqual({r['company_id'] for r in rows.values()},{1})
        self.assertTrue(all(r['company']['official_name']=='Nový název a.s.' for r in rows.values()))
    def test_deleted_company_requires_manual_resolution(self):
        name='česká firma s.r.o.'
        self.links.resolve([name])
        with closing(self.connect()) as con, con:
            con.execute('DELETE FROM companies WHERE id=1')
            con.execute("INSERT INTO companies(id,official_name) VALUES(6,'Česká firma s.r.o.')")
        row=self.links.resolve([name])[name]
        self.assertEqual(row['status'],'missing');self.assertIsNone(row['company_id'])
    def test_all_import_types_takeover_and_separate_crm(self):
        self.reports.execute("INSERT INTO delivery_notes(doc_no,doc_date,customer,base_amount) VALUES('DL1','2026-08-01','Česká firma s.r.o.',1250)")
        self.reports.execute("INSERT INTO profit_documents(doc_no,customer) VALUES('DL1','Dvojí a.s.')")
        self.reports.execute("INSERT INTO overhead_docs(invoice_no,doc_date,customer) VALUES('RE1','2026-08-01','Jiná firma s.r.o.')")
        self.reports.execute("INSERT INTO invoice_customer_snapshots(period,customer) VALUES('2026-08','Archiv s.r.o.')")
        before=self.reports.path.read_bytes()
        rows=self.links.resolve()
        self.assertEqual(len(rows),4);self.assertEqual(self.reports.path.read_bytes(),before)
        self.links.save('Dvojí a.s.',3,'manual',rows['Dvojí a.s.']['token'])
        second=ReportingStore(Path(self.temp.name)/'other.db')
        second.database.execute("INSERT INTO delivery_notes(doc_no,doc_date,customer,base_amount) VALUES('NEW','2026-08-01','Dvojí a.s.',2000)")
        self.store.take_over(second.path)
        self.assertEqual(self.links.resolve()['Dvojí a.s.']['company_id'],3)
        self.assertEqual(self.reports.scalar('SELECT sum(base_amount) FROM delivery_notes'),2000)
        # Identity mappings are not imported from the source's CRM or copied into reports.
        self.assertEqual(second.database.scalar("SELECT count(*) FROM sqlite_master WHERE name='report_company_links'"),0)
    def test_merged_names_target_one_identity_and_cycles_do_not_match(self):
        with closing(self.connect()) as con, con:
            con.execute('UPDATE companies SET merged_into_company_id=2,active=0 WHERE id=3')
        self.assertEqual(self.links.resolve(['Dvojí a.s.'])['Dvojí a.s.']['company_id'],2)
        with closing(self.connect()) as con, con:
            con.execute('UPDATE companies SET merged_into_company_id=3 WHERE id=2')
        self.assertIsNone(self.links.resolve(['Dvojí a.s.'])['Dvojí a.s.']['company_id'])


def prepare(td):
    spec=importlib.util.spec_from_file_location('previous833',REPO/'scripts/validate-827-processing-catalogs.py')
    previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)
    return previous.prepare(td,runtime=True),previous.settle


def source_integration(td):
    M,_=prepare(td)
    store=ReportingStore(M.DB)
    links=CompanyLinks(M.db,store.database,'833 Editor')
    with M.db() as con:
        source=con.execute("INSERT INTO companies(short_name,official_name) VALUES('833 Old','833 Old')").lastrowid
        target=con.execute("INSERT INTO companies(short_name,official_name) VALUES('833 Target','833 Target')").lastrowid
        con.execute("INSERT INTO business_documents(document_type,company_id,document_number,subtotal_net,currency) VALUES('issued_offer',?,'N833',100,'EUR')",(source,))
        con.execute("INSERT INTO business_documents(document_type,company_id,document_number,subtotal_net,currency) VALUES('received_order',?,'O833',200,'CZK')",(target,))
    links.resolve(['833 Old'])
    M.merge_company_records(source,target,'833 Editor')
    row=links.resolve(['833 Old'])['833 Old']
    assert row['company_id']==target
    with M.db() as con:
        assert con.execute('SELECT company_id FROM report_company_links').fetchone()[0]==target
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
    docs=links.documents(target)
    assert {(r['document_type'],r['currency']) for r in docs}=={('issued_offer','EUR'),('received_order','CZK')}
    assert store.database.scalar('SELECT count(*) FROM delivery_notes')==0
    print('8.0.33: real additive schema, company merge references and separate CRM document sources OK',flush=True)


def ui_checks(td):
    M,settle=prepare(td)
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageGrab
    from price_lists_domain.monthly_reports.company_ui import CompanyLinkDialog
    M.App.maybe_show_morning_overview=lambda self:None
    errors=[];warnings=[]
    M.messagebox.showinfo=lambda *a,**k:None
    M.messagebox.showwarning=lambda *a,**k:warnings.append(str(a))
    M.messagebox.showerror=lambda *a,**k:errors.append(str(a))
    M.messagebox.askyesnocancel=lambda *a,**k:False
    M.App.report_callback_exception=lambda self,*exc:errors.append(str(exc))
    with M.db() as con:
        con.execute("INSERT INTO users(name) VALUES('833 Alena'),('833 Bára')")
        cid=con.execute("INSERT INTO companies(short_name,official_name,is_supplier,ico) VALUES('833 Alfa','833 Alfa, s. r. o.',1,'12345678')").lastrowid
        c2=con.execute("INSERT INTO companies(short_name,official_name) VALUES('833 Beta','833 Beta a.s.')").lastrowid
        con.execute("INSERT INTO materials(name) VALUES('833 Nosník')")
        con.execute("INSERT INTO actions(name) VALUES('833 Akce')")
        con.execute("INSERT INTO business_documents(document_type,company_id,document_number,subtotal_net,currency) VALUES('issued_offer',?,'833-N-1',120,'EUR'),('received_order',?,'833-O-1',300,'CZK')",(cid,cid))
    root=M.App()
    def walk(widget):
        yield widget
        for child in widget.winfo_children():yield from walk(child)
    output=REPO/'build/validation/company-links-833';output.mkdir(parents=True,exist_ok=True)
    try:
        root.state('normal');root.geometry('1220x850+0+0');settle(root,3)
        root.active_user.set('833 Alena')
        d=M.RequestDialog(root);settle(root)
        assert d.assigned.get()=='833 Alena'
        assert any(isinstance(x,ttk.Label) and x.cget('text')=='Řeší' for x in walk(d))
        assert d.assigned_box.winfo_rooty()<d.item_box.winfo_rooty()
        assert d.winfo_rooty() < d.assigned_box.entry.winfo_rooty() < d.winfo_rooty()+d.winfo_height()-40
        d.assigned_box.entry.focus_force();d.assigned.set('833 Bár');settle(root)
        d.assigned_box.entry.event_generate('<Return>');settle(root)
        assert d.assigned.get()=='833 Bára' and d.winfo_exists() and d.result is None
        ImageGrab.grab().save(output/'request-resolver.png')
        d.company.set('833 Alfa, s. r. o.');d.item.set('833 Nosník');d.action.set('833 Akce');settle(root)
        d.ok();root.save_request(d);settle(root)
        with M.db() as con:
            row=con.execute('SELECT * FROM requests WHERE company_id=? ORDER BY id DESC',(cid,)).fetchone()
            assert row['assigned_user']=='833 Bára'
        edit=M.RequestDialog(root,rid=row['id']);settle(root)
        assert edit.assigned.get()=='833 Bára' and edit.assigned_box.winfo_rooty()<edit.item_box.winfo_rooty()
        edit.destroy()
        root.show_page('reports_customers');settle(root,.7)
        w=root._reports_workspace
        w.db.execute("INSERT INTO delivery_notes(doc_no,doc_date,customer,base_amount) VALUES('A','2026-08-01','833 ALFA s.r.o.',1000),('B','2026-08-01','833 Jiné jméno',2000)")
        w._populate_periods();w.period_var.set('2026-08');w.refresh_current();settle(root)
        tree=next(x for x in walk(w.container) if isinstance(x,ttk.Treeview))
        assert len(tree.get_children())==2 and 'crm_company' in tree['columns']
        assert w.analytics.kpis(2026,8)['revenue']==3000 and w.last_error is None
        dialog=CompanyLinkDialog(w,'833 Jiné jméno');settle(root)
        assert dialog.company_box.winfo_viewable() and dialog.save_button.winfo_viewable()
        assert dialog.save_button.winfo_rooty()+dialog.save_button.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
        dialog.company_var.set('833 Al');assert not dialog.save('manual')
        assert w.company_links.resolve(['833 Jiné jméno'])['833 Jiné jméno']['company_id'] is None
        dialog.focus_force()
        dialog.company_box.event_generate('<ButtonPress-1>',x=8,y=8)
        dialog.company_box.event_generate('<ButtonRelease-1>',x=8,y=8)
        settle(root,.7)
        dialog.company_var.set('833 Alfa');settle(root)
        ImageGrab.grab().save(output/'company-before-enter.png')
        assert root.focus_get() is dialog.company_box, ('company focus',str(root.focus_get()),str(dialog.company_box),errors)
        assert dialog.company_box._matches(), ('company suggestions',dialog.company_var.get(),dialog.company_box.values,errors)
        dialog.company_box.event_generate('<Return>');settle(root)
        assert dialog.company_var.get() in dialog.labels, ('company Enter',dialog.company_var.get(),dialog.company_box.selected_value,dialog.company_box._matches(),str(root.focus_get()),errors)
        # Enter chooses an existing company without writing a link or a company.
        assert w.company_links.resolve(['833 Jiné jméno'])['833 Jiné jméno']['company_id'] is None
        dialog.save_button.invoke();settle(root)
        assert w.company_links.resolve(['833 Jiné jméno'])['833 Jiné jméno']['company_id']==cid
        for theme in ('Světlý','Tmavý'):
            dialog.close();root.apply_theme(theme);w.show_page('Zákazníci');settle(root)
            dialog=CompanyLinkDialog(w,'833 Jiné jméno');settle(root)
            ImageGrab.grab().save(output/f'company-links-{theme}.png')
        assert dialog.save('ignored');assert dialog.save('reset')
        assert w.company_links.resolve(['833 Jiné jméno'])['833 Jiné jméno']['status']=='unmatched'
        dialog.company_var.set(next(label for label,target in dialog.labels.items() if target==cid))
        assert dialog.save('manual');dialog.close();settle(root)
        w.open_customer_detail('833 ALFA s.r.o.');settle(root)
        detail=next(x for x in walk(root) if isinstance(x,tk.Toplevel) and x.title().endswith(' – historie'))
        assert any(isinstance(x,ttk.Label) and str(x.cget('text')).startswith('Adresář: 833 Alfa') for x in walk(detail))
        docs=w.open_company_documents(cid);settle(root)
        dt=next(x for x in walk(docs) if isinstance(x,ttk.Treeview))
        assert len(dt.get_children())==2
        ImageGrab.grab().save(output/'company-documents.png')
        docs.destroy();detail.destroy()
        assert w.analytics.kpis(2026,8)['revenue']==3000
        with M.db() as con:
            assert con.execute("SELECT count(*) FROM companies WHERE official_name LIKE '833 %'").fetchone()[0]==2
        # TEST changes use the separate CRM copy and cannot overwrite live mappings.
        live_db=M.DB
        root.select_user('TEST');root.show_page('reports_customers');settle(root,.7)
        tw=root._reports_workspace
        assert Path(M.DB).resolve()!=Path(live_db).resolve() and tw.company_links.imported_names()==[]
        test_row=tw.company_links.resolve(['833 Jiné jméno'])['833 Jiné jméno']
        tw.company_links.save('833 Jiné jméno',c2,'manual',test_row['token'])
        with closing(sqlite3.connect(live_db)) as con:
            assert con.execute('SELECT company_id FROM report_company_links WHERE source_key=?',(name_key('833 Jiné jméno'),)).fetchone()[0]==cid
        assert not errors,errors
        print('8.0.33: visible request resolver, autocomplete Enter, explicit link saves, both themes, CRM documents, unchanged revenue and TEST isolation OK',flush=True)
    finally:
        root._turto_closing=True
        for job in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(job)
        root.destroy()


if __name__=='__main__':
    if '--source-worker' in sys.argv:source_integration(sys.argv[-1])
    elif '--ui-worker' in sys.argv:ui_checks(sys.argv[-1])
    else:
        if not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LinkTests)).wasSuccessful():raise SystemExit(1)
        with tempfile.TemporaryDirectory(prefix='turto-links-833-') as td:
            subprocess.run([sys.executable,'-B',__file__,'--source-worker',str(Path(td)/'source')],check=True)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable,'-B',__file__,'--ui-worker',str(Path(td)/'ui')],check=True)
