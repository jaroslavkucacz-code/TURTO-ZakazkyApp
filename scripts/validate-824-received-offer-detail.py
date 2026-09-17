#!/usr/bin/env python3
"""Offer-local labels and actual Windows detail geometry/controls."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import received_item_labels as labels, project_activity
from price_lists_domain.issued_offers import service


def source_checks(td):
    # Reuse the established realistic offer/catalog separation fixture.
    spec=importlib.util.spec_from_file_location('offer_fixture',REPO/'scripts/validate-6341-offer-catalog-separation.py')
    fixture=importlib.util.module_from_spec(spec)
    argv=sys.argv; sys.argv=[argv[0]]
    try:spec.loader.exec_module(fixture)
    finally:sys.argv=argv
    M=fixture.Module(Path(td)/'labels.db'); fixture.seed(M)
    with M.db() as con:
        con.execute("UPDATE supplier_offer_items SET original_name='HIT-HP FT 1-0202-20-025',product_code='6100000066',item_key='HIT-HP FT 1-0202-20-025' WHERE id=1")
        con.execute("INSERT INTO supplier_offer_items(id,offer_id,position,original_name,product_code,item_key,quantity,unit,unit_price) VALUES(2,1,2,'Jiný výrobek','SUP2','OTHER',3,'ks',20)")
        con.execute("INSERT INTO supplier_offer_items(id,offer_id,position,original_name) VALUES(3,999,1,'Cizí nabídka')")
        project_activity.ensure_schema(con)  # Upgrade an existing 8.0.23 database.
        con.execute('DELETE FROM project_activity')
        labels.ensure_columns(con); labels.ensure_columns(con)
        assert not con.execute('SELECT * FROM project_activity').fetchall()
        before=[tuple(r) for r in con.execute('SELECT id,original_name,product_code,quantity,unit_price,catalog_product_id FROM supplier_offer_items ORDER BY id')]
        catalog=[tuple(r) for r in con.execute('SELECT * FROM catalog_products')]
    originals=labels.load_items(M,1,[1,2]); drafts=[dict(r) for r in originals]
    for row in drafts:row['internal_code'],row['internal_name']=labels.from_original(row,' - izolační nosník')
    assert drafts[0]['internal_code']=='HIT-HP FT 1-0202-20-025'
    assert drafts[0]['internal_name']=='HIT-HP FT 1-0202-20-025 - izolační nosník'
    drafts[1].update(internal_code='VLASTNÍ-002',internal_name='Vlastní název')
    labels.save_items(M,1,drafts,originals)
    with M.db() as con:
        assert [tuple(r) for r in con.execute('SELECT id,original_name,product_code,quantity,unit_price,catalog_product_id FROM supplier_offer_items ORDER BY id')]==before
        assert [tuple(r) for r in con.execute('SELECT * FROM catalog_products')]==catalog
        assert con.execute('SELECT last_activity_at FROM project_activity WHERE project_id=1000').fetchone()
    reloaded=labels.load_items(M,1,[1,2])
    assert [r['internal_name'] for r in reloaded]==[r['internal_name'] for r in drafts]
    _,copied=service.draft_from_supplier_offer(M,1)
    assert copied[0]['internal_code_snapshot']==drafts[0]['internal_code']
    assert copied[0]['internal_name_snapshot']==drafts[0]['internal_name']
    assert copied[0]['name']==drafts[0]['internal_name'] and copied[0]['product_code']=='6100000066'
    assert copied[0]['quantity']==2 and copied[0]['purchase_unit_price']==90
    assert all(r['catalog_product_id'] is None for r in copied)
    assert labels.matching_labels(reloaded,product_code='6100000066',position=20)==(drafts[0]['internal_code'],drafts[0]['internal_name'])
    assert labels.matching_labels(reloaded,original_name='Nový výrobek',product_code='NEW',position=1)==('','')
    # Stale second row rolls back an already attempted first-row write.
    with M.db() as con:con.execute("UPDATE supplier_offer_items SET internal_name='Jiný uživatel' WHERE id=2")
    changed=[dict(r,internal_name='Přepsat') for r in reloaded]
    try:labels.save_items(M,1,changed,reloaded)
    except ValueError:pass
    else:raise AssertionError('Stale edits must fail atomically')
    assert labels.load_items(M,1,[1])[0]['internal_name']==drafts[0]['internal_name']
    try:labels.load_items(M,1,[3])
    except ValueError:pass
    else:raise AssertionError('Foreign offer item accepted')
    current=labels.load_items(M,1,[1])
    labels.save_items(M,1,[dict(current[0],internal_code='',internal_name='')],current)
    assert labels.load_items(M,1,[1])[0]['internal_code']==''
    # Quick copying uses each selected row's own manufacturer name and leaves
    # unselected rows and all supplier/catalogue data untouched.
    untouched=labels.load_items(M,1,[2])
    assert labels.copy_from_manufacturer(M,1,[1],'izolační nosník')==1
    copied=labels.load_items(M,1,[1])[0]
    assert copied['internal_code']=='HIT-HP FT 1-0202-20-025'
    assert copied['internal_name']=='HIT-HP FT 1-0202-20-025 - izolační nosník'
    assert labels.load_items(M,1,[2])==untouched
    assert labels.copy_from_manufacturer(M,1,[1,2,1])==2
    copied=labels.load_items(M,1,[1,2])
    assert [r['internal_name'] for r in copied]==['HIT-HP FT 1-0202-20-025','Jiný výrobek']
    with M.db() as con:
        assert [tuple(r) for r in con.execute('SELECT id,original_name,product_code,quantity,unit_price,catalog_product_id FROM supplier_offer_items ORDER BY id')]==before
        assert [tuple(r) for r in con.execute('SELECT * FROM catalog_products')]==catalog
    print('8.0.24: migration, original-name preset, arbitrary labels, persistence, source/catalog isolation, activity, issued snapshots and atomic stale-edit protection OK',flush=True)


def settle(root,seconds=.45):
    end=time.monotonic()+seconds
    while time.monotonic()<end:root.update(); time.sleep(.01)


def ui_checks(td):
    os.environ['TURTO_CRM_DATA_ROOT']=td
    os.environ['LOCALAPPDATA']=str(Path(td)/'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE']='1'
    import app,data_location,runtime_bootstrap,crm_features
    from price_lists_domain.platform.calm_theme_820 import walk
    data_location.apply_to_app(app); app.ensure_schema(); runtime_bootstrap.apply_all(app); app.ensure_schema(); app.ensure_test_user()
    app.App.maybe_show_morning_overview=lambda self:None
    app.messagebox.showinfo=lambda *a,**k:None
    app.messagebox.showwarning=lambda *a,**k:None
    root=app.App(); errors=[]
    root.report_callback_exception=lambda *exc:errors.append(str(exc))
    app.messagebox.showerror=lambda *a,**k:errors.append(str(a))

    def button(win,text):
        return next(w for w in walk(win) if isinstance(w,app.ttk.Button) and str(w.cget('text'))==text)

    def capture(win,name):
        from PIL import ImageGrab
        target=REPO/'build/validation/received-824'; target.mkdir(parents=True,exist_ok=True)
        ImageGrab.grab().crop((win.winfo_rootx(),win.winfo_rooty(),
            win.winfo_rootx()+win.winfo_width(),win.winfo_rooty()+win.winfo_height())).save(target/name)

    def check_geometry(dialog):
        canvas=dialog._dialog_canvas
        assert dialog.f.winfo_width()<=canvas.winfo_width()+2,(dialog.f.winfo_width(),canvas.winfo_width())
        assert canvas.xview()==(0.,1.),canvas.xview()
        link=button(dialog,'Změnit přiřazení…')
        assert link.winfo_viewable()
        assert 0<=link.winfo_rootx()-dialog.winfo_rootx()<100
        assert link.winfo_rooty()+link.winfo_height()<dialog.winfo_rooty()+dialog.winfo_height()
        assert dialog.tree.winfo_width()<dialog.winfo_width()
        scroll=dialog._offer_xscroll
        assert scroll.winfo_rooty()+scroll.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height(), 'Table scrollbar must remain reachable'
        assert dialog.f.winfo_reqheight()>=canvas.winfo_height()-4, 'Table leaves unused height below the content'
        close=button(dialog,'Zavřít')
        assert close.winfo_rooty()+close.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height(), 'Close footer must remain reachable'

    try:
        root.state('normal'); root.geometry('1100x800+0+0'); settle(root,4)
        with app.db() as con:
            pid=con.execute("INSERT INTO projects(name) VALUES('824 Akce')").lastrowid
            oid=con.execute("INSERT INTO supplier_offers(source_hash,supplier_name,offer_number,project_id,offer_date) VALUES('824-labels','Leviat s.r.o.','10388907',?,'2026-09-17')",(pid,)).lastrowid
            ids=[]
            for pos,name in enumerate(('HIT-HP FT 1-0202-20-025','HIT-HP FT 2-0300'),1):
                ids.append(con.execute('INSERT INTO supplier_offer_items(offer_id,position,original_name,item_key,product_code,quantity,unit,unit_price) VALUES(?,?,?,?,?,490,\'KS\',766)',
                    (oid,pos,name,name,'610000006'+str(pos))).lastrowid)
        root.show_page('offers'); settle(root)
        dialog=crm_features.OfferDetailDialog(root,oid); settle(root,1)
        capture(dialog,'detail-initial.png')
        check_geometry(dialog)
        assert dialog.tree.column('Poz.','width')==55, 'New detail must use compact defaults, not temporary Tk widths'
        capture(dialog,'detail.png')
        tree=dialog.tree
        # The table scrolls horizontally without moving its surrounding controls.
        assert tree.xview()[1]<1,tree.xview()
        link_x=button(dialog,'Změnit přiřazení…').winfo_rootx()
        tree.xview_moveto(1); settle(root)
        assert button(dialog,'Změnit přiřazení…').winfo_rootx()==link_x
        check_geometry(dialog)
        # Native mouse drag preserves the preferred width. The last column
        # now fills the remaining viewport, per the follow-up UX request.
        visible=('Původní název','Interní kód','Interní označení')
        tree.configure(displaycolumns=visible)
        tree._turto_design_widths.update(dict(zip(visible,(220,180,200))))
        app.schedule_persistent_tree_fit(tree,0); tree.xview_moveto(0); settle(root)
        last=visible[1]; iid='i'+str(ids[0]); box=tree.bbox(iid,last)
        right=box[0]+box[2]-1
        y=next(y for y in range(1,box[1]) if tree.identify_region(right,y)=='separator')
        before=tree.column(last,'width')
        tree.event_generate('<ButtonPress-1>',x=right,y=y)
        tree.event_generate('<B1-Motion>',x=right-55,y=y)
        tree.event_generate('<ButtonRelease-1>',x=right-55,y=y); settle(root)
        width=tree.column(last,'width')
        assert width<before-25,(before,width)
        assert not tree.column(last,'stretch')
        assert tree.column(visible[-1],'stretch')
        assert abs(sum(tree.column(c,'width') for c in visible)-tree.winfo_width())<=5
        root.geometry('1500x950+0+0'); dialog.geometry('1300x800+10+10'); settle(root)
        assert tree.column(last,'width')==width
        check_geometry(dialog)
        # Use the real entry point, preset, edited fields and save button.
        tree.selection_set(tuple('i'+str(i) for i in ids))
        button(dialog,'Interní označení…').invoke(); settle(root)
        editor=next(w for w in walk(dialog) if isinstance(w,app.tk.Toplevel) and w.title()=='Interní označení položek')
        button(editor,'Izolační nosníky').invoke(); settle(root)
        capture(editor,'internal-labels.png')
        assert editor.internal_code.get()=='HIT-HP FT 1-0202-20-025'
        assert editor.internal_name.get().endswith(' - izolační nosník')
        editor.item_tree.selection_set(str(ids[1])); settle(root)
        editor.internal_code.set('VLASTNI-KOD'); editor.internal_name.set('Samostatné interní označení')
        button(editor,'Uložit').invoke(); settle(root)
        assert tree.set('i'+str(ids[1]),'Interní kód')=='VLASTNI-KOD'
        # Dirty Escape refuses to discard silently; cancellation writes nothing.
        tree.selection_set('i'+str(ids[1])); button(dialog,'Interní označení…').invoke(); settle(root)
        editor=next(w for w in walk(dialog) if isinstance(w,app.tk.Toplevel) and w.title()=='Interní označení položek')
        editor.internal_name.set('NEULOŽENO')
        prompts=[]; app.messagebox.askyesnocancel=lambda *a,**k:(prompts.append(a) or None)
        editor._turto_form_close(); assert editor.winfo_exists() and prompts
        app.messagebox.askyesnocancel=lambda *a,**k:False
        editor._turto_form_close(); settle(root)
        assert labels.load_items(app,oid,[ids[1]])[0]['internal_name']=='Samostatné interní označení'
        dialog.destroy(); settle(root)
        dialog=crm_features.OfferDetailDialog(root,oid); settle(root,.8)
        assert dialog.tree.column(last,'width')==width
        assert tuple(dialog.tree.cget('displaycolumns'))==visible
        assert dialog.tree.set('i'+str(ids[0]),'Interní označení').endswith(' - izolační nosník')
        check_geometry(dialog)
        # Assignment is the existing actual editor, now reachable from the left.
        opened=[]
        def close_assignment():
            for w in list(walk(dialog)):
                if isinstance(w,app.tk.Toplevel) and w is not dialog:
                    opened.append(w.title()); w.destroy()
        root.after(250,close_assignment)
        button(dialog,'Změnit přiřazení…').invoke(); settle(root)
        assert 'Vazba nabídky' in opened,opened
        dialog.destroy(); settle(root)
        _,copied=service.draft_from_supplier_offer(app,oid)
        assert copied[1]['internal_code_snapshot']=='VLASTNI-KOD',copied[1]
        assert copied[1]['internal_name_snapshot']=='Samostatné interní označení'
        assert not copied[1]['supplier_presentation_snapshot']
        assert service.normalize_item(copied[1])['internal_name_snapshot']=='Samostatné interní označení'
        # Inline editing follows displayed columns, including a reordered pair.
        dialog=crm_features.OfferDetailDialog(root,oid); settle(root,.7)
        tree=dialog.tree
        tree.configure(displaycolumns=('Interní označení','Původní název','Interní kód'))
        app.schedule_persistent_tree_fit(tree,0); settle(root)
        controller=dialog._inline_labels
        def double_cell(iid,column):
            tree.see(iid); settle(root,.1)
            box=tree.bbox(iid,column); assert box,(iid,column)
            x,y=box[0]+25,box[1]+box[3]//2
            # Explicit event timestamps distinguish consecutive synthetic
            # double-clicks even on a fast Windows runner.
            stamp=int(time.monotonic()*1000)%2000000000
            for offset in (0,100):
                tree.event_generate('<ButtonPress-1>',x=x,y=y,time=stamp+offset)
                tree.event_generate('<ButtonRelease-1>',x=x,y=y,time=stamp+offset+30)
            settle(root,.15)
        history=[]
        dialog.open_history=lambda:history.append(True)
        iid='i'+str(ids[0])
        double_cell(iid,'Interní označení')
        assert controller.entry is not None and not history
        controller.variable.set('Přímo v tabulce')
        controller.entry.event_generate('<Return>'); settle(root)
        assert controller.entry is None and tree.set(iid,'Interní označení')=='Přímo v tabulce'
        double_cell(iid,'Interní kód')
        assert controller.entry is not None
        controller.variable.set('NEULOŽIT')
        controller.entry.event_generate('<Escape>'); settle(root)
        assert controller.entry is None and dialog.winfo_exists()
        assert tree.set(iid,'Interní kód')=='HIT-HP FT 1-0202-20-025'
        # F2 edits the name, Tab saves it and advances to the next editable cell.
        tree.focus(iid); tree.selection_set(iid); tree.focus_set()
        tree.event_generate('<F2>'); settle(root,.15)
        assert controller.entry is not None
        controller.variable.set('Název přes F2')
        controller.entry.event_generate('<Tab>'); settle(root,.15)
        assert controller.column=='Interní kód' and tree.set(iid,'Interní označení')=='Název přes F2'
        controller.variable.set('KOD-INLINE')
        controller.entry.event_generate('<Return>'); settle(root)
        assert tree.set(iid,'Interní kód')=='KOD-INLINE'
        # Selection-based copying, optional suffix and Ctrl+A all use the table.
        tree.selection_set(iid); controller.suffix.set('izolační nosník')
        button(dialog,'Převzít od výrobce').invoke(); settle(root)
        assert tree.set(iid,'Interní označení')=='HIT-HP FT 1-0202-20-025 - izolační nosník'
        assert tree.set('i'+str(ids[1]),'Interní označení')=='Samostatné interní označení'
        tree.focus_set(); tree.event_generate('<Control-a>'); settle(root,.15)
        assert set(tree.selection())=={'i'+str(value) for value in ids}
        controller.suffix.set('')
        button(dialog,'Převzít od výrobce').invoke(); settle(root)
        assert tree.set('i'+str(ids[1]),'Interní označení')=='HIT-HP FT 2-0300'
        # A normal source cell still opens price history; label cells never do.
        double_cell(iid,'Původní název'); assert history==[True]
        dialog.geometry('1300x850+10+10'); settle(root)
        check_geometry(dialog)
        assert abs(sum(tree.column(c,'width') for c in tree.cget('displaycolumns'))-tree.winfo_width())<=5
        capture(dialog,'inline-labels-filled.png')
        # An in-progress edit is committed when the actual Close button is used.
        controller.begin(iid,'Interní kód'); controller.variable.set('ULOŽIT-PŘI-ZAVŘENÍ')
        button(dialog,'Zavřít').invoke(); settle(root)
        assert not dialog.winfo_exists()
        assert labels.load_items(app,oid,[ids[0]])[0]['internal_code']=='ULOŽIT-PŘI-ZAVŘENÍ'
        # Restore the search fixture following the deliberate bulk replacement.
        current=labels.load_items(app,oid,[ids[1]])
        labels.save_items(app,oid,[dict(current[0],internal_code='VLASTNI-KOD')],current)
        # Filtering must include the new persisted identities.
        control=root._table_searches['offers']
        control.draft.set('VLASTNI-KOD'); settle(root)
        assert root.offer_tree.exists('o'+str(oid))
        assert not errors,errors
        print('8.0.25: Windows full width/height, native column drag/reopen, inline Enter/Escape/F2/Tab/close, row/all manufacturer copy, custom labels, history routing and issued copy OK',flush=True)
    finally:
        root._turto_closing=True; root.destroy()


if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='turto-824-source-',ignore_cleanup_errors=True) as td:source_checks(td)
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-824-ui-',ignore_cleanup_errors=True) as td:ui_checks(td)
