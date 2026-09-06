#!/usr/bin/env python3
"""End-to-end PDF/template regressions, isolated SQLite, optional real Tk."""
from __future__ import annotations
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import zipfile
from types import SimpleNamespace


class TestConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:return super().__exit__(*args)
        finally:self.close()


def owner(root):
    class M:
        DATA_ROOT=Path(root)/"data"
        def __init__(self):self.settings={};self.DATA_ROOT.mkdir(exist_ok=True)
        def db(self):
            con=sqlite3.connect(Path(root)/"test.db",factory=TestConnection);con.row_factory=sqlite3.Row
            con.create_collation("CZECH",lambda a,b:(a>b)-(a<b));con.execute("PRAGMA foreign_keys=ON");return con
        def get_setting(self,key,default=""):return self.settings.get(key,default)
        def set_setting(self,key,value):self.settings[key]=str(value)
        def fmt_date(self,value):
            value=str(value or "")
            return value[8:10]+"."+value[5:7]+"."+value[:4] if len(value)==10 and value[4]=="-" else value
    return M()


def foundation(M):
    with M.db() as con:
        con.executescript("""
        CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT,short_name TEXT,address TEXT,ico TEXT,dic TEXT);
        CREATE TABLE people(id INTEGER PRIMARY KEY,name TEXT,email TEXT,phone TEXT,company_id INTEGER);
        CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE actions(id INTEGER PRIMARY KEY,name TEXT);
        CREATE TABLE catalog_products(id INTEGER PRIMARY KEY);
        CREATE TABLE product_subgroups(id INTEGER PRIMARY KEY);
        CREATE TABLE price_list_items(id INTEGER PRIMARY KEY);
        CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,supplier_name TEXT);
        CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,image_asset_key TEXT,image_blob BLOB,original_name TEXT,item_key TEXT);
        CREATE TABLE offer_image_assets(asset_key TEXT PRIMARY KEY,image_blob BLOB);
        CREATE TABLE business_documents(id INTEGER PRIMARY KEY AUTOINCREMENT,document_type TEXT,direction TEXT,document_number TEXT,issue_date TEXT,valid_to TEXT,company_id INTEGER,project_id INTEGER,status TEXT,currency TEXT,total_value REAL,archived INTEGER DEFAULT 0,archived_at TEXT,archived_by TEXT,created_at TEXT,updated_at TEXT);
        CREATE TABLE business_document_items(id INTEGER PRIMARY KEY AUTOINCREMENT,document_id INTEGER,position INTEGER,product_code TEXT,item_key TEXT,name TEXT,description TEXT,quantity REAL,unit TEXT,unit_price REAL,discount_pct REAL,total_price REAL,category_id INTEGER);
        INSERT INTO companies VALUES(1,'Testovací odběratel','TEST','Ukázková 1','12345678','CZ12345678');
        INSERT INTO projects VALUES(1,'Testovací stavba');
        INSERT INTO supplier_offers VALUES(1,'Nevoga');
        INSERT INTO supplier_offer_items VALUES(1,1,'nevoga:plexus:B',NULL,'PLEXUS B','PLEXUS B');
        """)


def expect_error(call):
    try:call()
    except (ValueError,TypeError):return
    raise AssertionError("Invalid input was accepted")


def main():
    source=Path(sys.argv[1] if len(sys.argv)>1 else 'ZakazkyApp_base_6.1').resolve();sys.path.insert(0,str(source))
    import fitz
    from PIL import Image
    from price_lists_domain.issued_offers import (schema,service,template_layout as tl,
        pdf_renderer,template_bundle,professional_workflow as wf,template_settings,offer_images)
    from v710_cleanup import group_offer_items
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);M=owner(root);foundation(M);schema.ensure_business_documents_schema(M)
        M.group_issued_offer_items=group_offer_items
        original=service.load_template(M);assert tl.is_corporate(original)
        original_id=original['id']
        assert service.load_template(M,1)['layout_json']=='{}', 'Legacy template rewritten'
        for _ in range(3):schema.ensure_business_documents_schema(M)
        assert len(service.list_templates(M))==2
        expect_error(lambda:service.save_template(M,{'name':'Do not overwrite'},original_id))
        expect_error(lambda:service.deactivate_template(M,original_id))
        values=dict(original);values['name']='Vlastní šablona';values['is_default']=1;values.pop('builtin_key')
        tid=service.save_template(M,values)
        schema.ensure_business_documents_schema(M)
        assert service.default_template_id(M)==tid
        layout=tl.normalize(values['layout_json']);layout['font_size']=8.5
        values['layout_json']=json.dumps(layout);service.save_template(M,values,tid)
        assert tl.normalize(service.load_template(M,tid)['layout_json'])['font_size']==8.5
        expect_error(lambda:tl.normalize({'font_size':'nan'}))
        expect_error(lambda:tl.normalize({'columns':layout['columns'][:-1]}))
        expect_error(lambda:tl.normalize({'columns':[layout['columns'][0]]*6}))
        expect_error(lambda:tl.validate_geometry({'margin_left_mm':90},layout))
        small=copy.deepcopy(layout);small['columns'][1]['width']=1
        expect_error(lambda:tl.validate_geometry(values,small))
        # Original embedded artwork bytes, not generated/retouched substitutes.
        assert hashlib.sha256(Path(tl.asset_path('builtin:turto-offer-header')).read_bytes()).hexdigest()=='5cba9ba1a6fd3f22ac8208f54b30e59f0c443e5677b9a230c174da017ef0b9b9'
        assert hashlib.sha256(Path(tl.asset_path('builtin:turto-offer-footer')).read_bytes()).hexdigest()=='4ba2ac34e25f3a9d4496322e4053ff7f91e2d3eb557d712041b5c52e74fa5c56'
        image=Image.new('RGB',(120,90),'white');image.paste('black',(30,10,90,80));buffer=io.BytesIO();image.save(buffer,format='PNG');blob=buffer.getvalue()
        with M.db() as con:con.execute('INSERT INTO offer_image_assets VALUES(?,?)',('nevoga:plexus:B',blob))
        doc,items=template_settings.sample_offer();doc.update(company_id=1,project_id=1,template_id=tid,status='Rozpracováno')
        items[0].update(source_supplier_offer_item_id=1,unit='m',quantity=2.5,purchase_unit_price=9876543,margin_pct=9876)
        did=service.save_document(M,doc,items)
        document,stored=service.load_document(M,did)
        assert stored[0]['image_asset_key_snapshot']=='nevoga:plexus:B'
        assert not stored[0]['image_file_snapshot']
        assert offer_images.resolve(M,stored[0])==blob
        a=pdf_renderer.render_offer_snapshot(M,document,stored,service.load_template(M,tid),root/'preview.pdf')
        assert len(a['regions'])==5 and a['pages']==1,a
        # Only preview, no sequence reservation/revision mutation.
        with M.db() as con:
            assert con.execute('SELECT COUNT(*) FROM business_document_revisions').fetchone()[0]==0
        target=pdf_renderer.render_offer_pdf(M,did)
        with fitz.open(target) as final,fitz.open(root/'preview.pdf') as preview:
            assert final[0].get_text()==preview[0].get_text()
            assert final[0].get_pixmap().samples==preview[0].get_pixmap().samples
            text=''.join(p.get_text() for p in final)
            assert '9876543' not in text and '9876' not in text and 'Marže' not in text
            # Wrapped headings remain complete; OS font metrics can change line breaks.
            normalized_text=' '.join(text.split())
            for heading in ('Název / popis','Cena celkem','Množ.'):
                assert heading in normalized_text, (ascii(heading),ascii(text),final[0].get_fonts())
            assert len(final[0].get_images())>=3
        old_hash=hashlib.sha256(target.read_bytes()).hexdigest()
        fp1=wf.template_fingerprint(M,tid)
        changed=service.load_template(M,tid);changed_layout=tl.normalize(changed['layout_json']);changed_layout['row_padding_mm']=2
        changed['layout_json']=json.dumps(changed_layout);service.save_template(M,changed,tid)
        assert wf.template_fingerprint(M,tid)!=fp1
        assert hashlib.sha256(target.read_bytes()).hexdigest()==old_hash
        fp1=wf.release_fingerprint(M,document,stored)
        with M.db() as con:con.execute("UPDATE offer_image_assets SET image_blob=?",(blob+b' ',))
        assert wf.release_fingerprint(M,document,stored)!=fp1
        with M.db() as con:con.execute("UPDATE offer_image_assets SET image_blob=?",(blob,))
        # Portable import/export preserves artwork; new copy, never another default.
        archive=root/'template.zip';template_bundle.export_template(M,changed,archive)
        imported=template_bundle.import_template(M,archive);assert imported!=tid
        imported_template=service.load_template(M,imported)
        assert not imported_template['is_default']
        assert Path(imported_template['header_path']).read_bytes()==Path(tl.asset_path(original['header_path'])).read_bytes()
        evil=root/'evil.zip'
        with zipfile.ZipFile(evil,'w') as z:z.writestr('../escape.txt','unsafe')
        expect_error(lambda:template_bundle.import_template(M,evil));assert not (root/'escape.txt').exists()
        # Long words, many rows, closing notes and reordering must stay within A4.
        many=[dict(stored[i%len(stored)],name=f'Řádek {i} Žluťoučký kůň') for i in range(100)]
        many[7]['description']='VelmiDlouhéOznačeníVýrobku'*400
        large=pdf_renderer.render_offer_snapshot(M,document,many,changed,root/'large.pdf')
        assert large['pages']>3
        assert set(r['index'] for r in large['regions'])==set(range(100))
        assert all(0<=r['page']<large['pages'] and r['y0']<r['y1']<790 for r in large['regions'])
        with fitz.open(root/'large.pdf') as pdf:
            for page in pdf:
                assert page.rect.width<596 and page.rect.height<843
                for x0,y0,x1,y1,text,*_ in page.get_text('blocks'):
                    assert x0>=0 and x1<=596 and y0>=0 and y1<=843,(x0,y0,x1,y1,text)
        edge=dict(changed);edge_layout=tl.normalize(edge['layout_json'])
        edge_layout.update(font_size=12,image_height_mm=35,row_padding_mm=6,contacts_text='Kontakt: ukazka@example.invalid',show_vat_summary=True)
        edge['layout_json']=json.dumps(edge_layout)
        edge_items=[dict(stored[0],subgroup_name_snapshot='Oddíl '+str(i)) for i in range(9)]
        extreme=pdf_renderer.render_offer_snapshot(M,document,edge_items,edge,root/'extreme.pdf')
        assert len(extreme['regions'])==9
        with fitz.open(root/'extreme.pdf') as pdf:
            for i,r in enumerate(extreme['regions']):
                assert 'Oddíl '+str(i) in pdf[r['page']].get_text(),'Orphaned group heading'
        longheading=[dict(stored[0],subgroup_name_snapshot='Dlouhý název oddílu '*300)]
        longres=pdf_renderer.render_offer_snapshot(M,document,longheading,changed,root/'heading.pdf')
        with fitz.open(root/'heading.pdf') as pdf:
            for page in pdf:
                for x0,y0,x1,y1,text,*_ in page.get_text('blocks'):
                    assert x0>=0 and x1<=596 and y0>=0 and y1<=843
        # Snapshot fallback works even when the source offer row is unavailable.
        assert offer_images.resolve(M,dict(stored[0],source_supplier_offer_item_id=None))==blob
        # Geometry matches source indices after grouping, not row order in the table.
        regroup=[dict(stored[0],category_name_snapshot='B'),dict(stored[1],category_name_snapshot='A'),dict(stored[2],category_name_snapshot='B')]
        res=pdf_renderer.render_offer_snapshot(M,document,regroup,changed,root/'grouped.pdf')
        assert [r['index'] for r in res['regions']]==[0,2,1]
        assert 'help_templates' in wf.HELP_TOPICS
        if '--ui' in sys.argv:
            import tkinter as tk
            from tkinter import ttk,messagebox,filedialog,simpledialog
            errors=[]
            app=tk.Tk();app.geometry('1400x850')
            app.report_callback_exception=lambda *e:errors.append(e)
            M.tk,M.ttk,M.messagebox,M.filedialog,M.simpledialog=tk,ttk,messagebox,filedialog,simpledialog
            M.enable_dialog_maximize=lambda win,w,h:win.geometry(f'{w}x{h}')
            dlg=template_settings.TemplateEditor(M,app)
            dlg.load(service.load_template(M,tid))
            app.update();dlg.render_preview();app.update()
            assert dlg.preview_images,dlg.status.get()
            dlg.layout_vars['font_size'].set('9.5');dlg.render_preview();app.update()
            assert dlg.signature()!=dlg.baseline
            # Direct save is guarded for built-ins, user templates persist edits.
            dlg.save();assert tl.normalize(service.load_template(M,tid)['layout_json'])['font_size']==9.5
            app.update();dlg.close();app.update();app.destroy()
            assert not errors,errors
    print('OK 7.9: original artwork, protected templates, roundtrip, shared images, snapshot PDF parity, pagination, exact hit regions and real Tk' if '--ui' in sys.argv else 'OK 7.9: original artwork, protected templates, roundtrip, shared images, snapshot PDF parity, pagination and exact hit regions')


if __name__=='__main__':main()
