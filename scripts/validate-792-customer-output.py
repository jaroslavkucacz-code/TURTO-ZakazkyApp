#!/usr/bin/env python3
"""Synthetic regressions for public text, branded variable text and real dialogs."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback


def normalized_pdf_text(value):
    # Calibri's PDF ToUnicode may map an ASCII hyphen to U+2010 and spaces to
    # NBSP on Windows. Normalize typography only; keep every number and label.
    return value.translate(str.maketrans({'\u2010':'-', '\u2011':'-', '\u00a0':' ', '\u202f':' '}))


def main():
    source=Path(sys.argv[1]).resolve()
    if '--worker' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto792_') as temp:
            subprocess.run([sys.executable,__file__,str(source),'--worker',temp],check=True,timeout=150)
        return
    temp=sys.argv[sys.argv.index('--worker')+1]
    os.environ.update(HOME=temp,USERPROFILE=temp,TURTO_DISABLE_AUTO_UPDATE='1')
    sys.path.insert(0,str(source));os.chdir(source)
    spec=importlib.util.spec_from_file_location('post_baseline',source.parent/'post_baseline.py')
    baseline=importlib.util.module_from_spec(spec);sys.modules['post_baseline']=baseline;spec.loader.exec_module(baseline)
    import app as M, runtime_bootstrap, dialog_chrome
    from price_lists_domain.issued_offers import (service,template_layout as tl,template_bundle,
        template_settings, pdf_renderer,professional_workflow as wf,customer_text,editor)
    import fitz
    M.ensure_schema();runtime_bootstrap.apply_all(M);M.ensure_schema();M.ensure_test_user()
    M.App.maybe_show_morning_overview=lambda self:None
    original_state=M.App.state
    if not sys.platform.startswith('win'):
        M.App.state=lambda self,newstate=None:original_state(self) if newstate in (None,'zoomed') else original_state(self,newstate)
    errors=[]
    for name in ('showwarning','showerror'):
        setattr(M.messagebox,name,lambda *a,**k:errors.append(str(a)))
    M.messagebox.showinfo=lambda *a,**k:None
    root=M.App();root.report_callback_exception=lambda *e:errors.append(''.join(traceback.format_exception(*e)))
    root.geometry('1500x900')
    def pump(seconds=.3):
        until=time.monotonic()+seconds
        while time.monotonic()<until:root.update();time.sleep(.01)
    def walk(widget):
        yield widget
        for child in widget.winfo_children():yield from walk(child)
    qa=Path(os.environ.get('TURTO_792_QA',temp));qa.mkdir(parents=True,exist_ok=True)
    try:
        pump(1)
        artwork={k:hashlib.sha256(Path(tl.asset_path(k)).read_bytes()).hexdigest() for k in tl.ASSETS}
        raw='Zdrojové množství: 2 ks × 1,25 m = 2,5 m; Zdrojová cena: 614,85 CZK/m'
        technical='Ø10 mm | lü=max 40 cm | L=125 cm'
        for value in [raw, 'Nákupní cena: 1 234,56 Kč/m', 'NC/MJ=1234.56', 'Zdrojová cena:\n614,85 CZK/m']:
            public,notes=customer_text.split_customer_text(value)
            assert notes and not customer_text._PRIVATE.search(public),(value,public)
            assert '614,85' not in public and '1 234,56' not in public,public
        assert customer_text.split_customer_text(technical)[0]==technical
        with M.db() as con:
            oid=con.execute("INSERT INTO supplier_offers(offer_number,offer_date,source_hash) VALUES('QA-792','2026-09-06','QA-792')").lastrowid
            con.execute('''INSERT INTO supplier_offer_items(offer_id,position,original_name,item_key,quantity,unit,unit_price,details)
                VALUES(?,1,'PLEXUS | typ B | Ø10 mm','QA-PLEXUS',2.5,'m',614.85,?)''',(oid,technical+'\n'+raw))
        draft,items=service.draft_from_supplier_offer(M,oid)
        assert len(items)==1 and items[0]['purchase_unit_price']==614.85
        assert not customer_text.has_private_text(draft,items)
        assert '614,85' in draft['internal_note']
        assert technical in items[0]['description']
        with M.db() as con:
            assert 'Zdrojová cena' in con.execute('SELECT details FROM supplier_offer_items WHERE offer_id=?',(oid,)).fetchone()[0]
        item=dict(items[0],unit_price=922.28,recommended_unit_price=922.28,margin_pct=50)
        # Direct unsaved renderer must be safe even if an old plugin supplies raw descriptions.
        item['description']=technical+'\n'+raw
        doc=service.offer_defaults(M);doc.update(customer_name_snapshot='Testovací odběratel',offer_subject='Ochrana cen',document_number='CN26-00042',internal_note='Zdrojová cena: 614,85 CZK/m')
        template=service.load_template(M)
        copy_template=dict(template);copy_template.pop('builtin_key',None);copy_template['name']='QA Vlastní 792'
        layout=tl.normalize(template['layout_json']);layout.update(edit_opening_hours=True,opening_hours='Po – Pá: 8:00 – 16:00\nSobota: zavřeno')
        copy_template['layout_json']=json.dumps(layout,ensure_ascii=False)
        tid=service.save_template(M,copy_template);copy_template=service.load_template(M,tid)
        output=qa/'offer792.pdf'
        pdf_renderer.render_offer_snapshot(M,doc,[item],copy_template,output)
        with fitz.open(output) as pdf:
            text=normalized_pdf_text('\n'.join(p.get_text() for p in pdf))
            assert 'Zdrojová cena' not in text and '614,85' not in text,text
            assert '922,28' in text and 'Ø10' in text
            assert text.count('CN26-00042')==1,text
            bounds=[fitz.Rect(word[:4]) for word in pdf[0].get_text('words')
                    if normalized_pdf_text(word[4])=='CN26-00042']
            assert len(bounds)==1 and bounds[0].y1<90,bounds
            assert '8:00' in text and 'Sobota' in text,text
            pdf[0].get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(qa/'offer792.png')
        portable=qa/'template.zip';template_bundle.export_template(M,copy_template,portable)
        imported=service.load_template(M,template_bundle.import_template(M,portable))
        assert tl.normalize(imported['layout_json'])['opening_hours']==layout['opening_hours']
        assert tl.is_original_asset(imported['header_path'],'builtin:turto-offer-header')
        pdf_renderer.render_offer_snapshot(M,doc,[item]*22,imported,qa/'multipage.pdf')
        with fitz.open(qa/'multipage.pdf') as pdf:
            assert len(pdf)>1
            for page in pdf:
                assert normalized_pdf_text(page.get_text()).count('CN26-00042')==1
                assert '614,85' not in page.get_text()
        # Existing unsanitized concept: no database mutation on read, internal preservation on save.
        doc['template_id']=tid
        did=service.save_document(M,doc,[item])
        with M.db() as con:
            con.execute('UPDATE business_document_items SET description=? WHERE document_id=?',(technical+'\n'+raw,did))
        loaded,lines=service.load_document(M,did)
        assert not customer_text.has_private_text(loaded,lines)
        assert '614,85' in loaded['internal_note']
        service.save_document(M,loaded,lines,did)
        saved=pdf_renderer.render_offer_pdf(M,did)
        with fitz.open(saved) as pdf:assert '614,85' not in '\n'.join(p.get_text() for p in pdf)
        # An unsafe legacy snapshot cannot be reused for e-mail, including locked historical offers.
        snapshot=dict(loaded,items=[dict(item,description=raw)])
        with M.db() as con:
            con.execute('UPDATE business_document_revisions SET data_json=? WHERE document_id=?',(json.dumps(snapshot),did))
            con.execute("UPDATE business_documents SET locked=1,status='Odesláno' WHERE id=?",(did,))
        assert wf.pdf_state(M,did).status=='unsafe'
        try:wf.ensure_current_pdf(M,did)
        except ValueError as exc:assert 'kopii' in str(exc)
        else:raise AssertionError('Unsafe locked archive was reused')
        # Visible real filters must accommodate their actual label/entry heights.
        count=0
        for key in ('requests','actions','mivo','offers'):
            root.show_page(key);pump(.45)
            for widget in walk(root):
                if not isinstance(widget,M.ttk.Treeview) or not widget.winfo_ismapped():continue
                frame=getattr(widget,'_filter_frame',None)
                if frame is None or not frame.winfo_ismapped():continue
                assert frame.winfo_height()>=50,(key,frame.winfo_height())
                for cell in getattr(widget,'_filter_cells',[]):
                    if not cell.winfo_ismapped():continue
                    count+=1
                    for entry in walk(cell):
                        if entry.winfo_class() not in ('TEntry','TCombobox','Entry'):continue
                        if entry.winfo_ismapped():
                            assert entry.winfo_height()>=entry.winfo_reqheight()-2,(key,entry.winfo_height(),entry.winfo_reqheight())
        assert count>=5,count
        # Normal form can maximize; the late centering callbacks must preserve it.
        dialog=M.tk.Toplevel(root);dialog.title('QA dialog 792');dialog.transient(root)
        M.enable_dialog_maximize(dialog,900,600);pump(.4)
        assert tuple(map(bool,dialog.resizable()))==(True,True)
        if sys.platform.startswith('win'):
            assert dialog_chrome.native_maximize_button(dialog),getattr(dialog,'_turto_chrome_error','')
            dialog.state('zoomed');M.center_dialog(dialog,root);pump(.5)
            assert dialog.state()=='zoomed'
            import ctypes
            from ctypes import wintypes
            u=ctypes.WinDLL('user32');u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
            g=getattr(u,'GetWindowLongPtrW',u.GetWindowLongW);g.argtypes=[wintypes.HWND,ctypes.c_int];g.restype=ctypes.c_ssize_t
            assert g(u.GetAncestor(dialog.winfo_id(),2),-16)&0x10000
            dialog.state('normal')
        popup=M.tk.Toplevel(root);popup.overrideredirect(True);popup.geometry('120x70+100+100');pump(.4)
        assert popup.winfo_width()==120 and popup.winfo_height()==70
        popup.destroy();dialog.destroy();pump(.1)
        # Real template settings expose, preserve and save the new fields.
        controller=template_settings.TemplateEditor(M,root,preview_document=doc,preview_items=[item])
        controller.load(copy_template);pump(.5)
        assert 'branding' in controller.tabs
        controller.texts['opening_hours'].delete('1.0','end')
        controller.texts['opening_hours'].insert('1.0','Po – Pá: 9:00 – 17:00')
        controller.layout_vars['edit_opening_hours'].set(True)
        controller.save();pump(.3)
        assert tl.normalize(service.load_template(M,tid)['layout_json'])['opening_hours']=='Po – Pá: 9:00 – 17:00'
        controller.close();pump(.1)
        assert artwork=={k:hashlib.sha256(Path(tl.asset_path(k)).read_bytes()).hexdigest() for k in tl.ASSETS}
        assert not errors,'\n'.join(errors)
    finally:
        root.destroy()
    print('OK 7.9.2: public price boundary, old unsafe PDF blocking, header number, portable hours, full-height filters and normal/popup dialog policy')

if __name__=='__main__':main()
