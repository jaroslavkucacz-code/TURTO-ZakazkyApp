#!/usr/bin/env python3
"""Shared-directory offer editing, group exceptions, real search and scroll gestures."""
from contextlib import closing
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixture844', REPO/'scripts/validate-841-centers-contacts.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
from price_lists_domain.issued_offers import service, group_pricing, offer_parties, editor
from price_lists_domain.platform import portfolio, categories
sql = fixture.sql


def seeded(td):
    M, settle, d = fixture.prepare(td)
    portfolio.save(M,d['cid'],{d['reps']['J'],d['reps']['H']},set())
    portfolio.save(M,d['other'],{d['reps']['M']},set())
    sql(M,"UPDATE people SET name='Eva Šťastná',email='eva844@example.test' WHERE id=?",(d['pid'],))
    with closing(M.db()) as con, con:
        d['cat'] = con.execute("INSERT INTO product_categories(name) VALUES('844 Konstrukce')").lastrowid
        d['sub'] = con.execute("INSERT INTO product_subgroups(category_id,name) VALUES(?,'844 Nosníky')",(d['cat'],)).lastrowid
        d['sub2'] = con.execute("INSERT INTO product_subgroups(category_id,name) VALUES(?,'844 Kotvy')",(d['cat'],)).lastrowid
    return M,settle,d


def offer(M,d):
    doc = service.offer_defaults(M)
    doc.update(service.company_snapshot(M,d['cid']))
    doc.update(service.contact_snapshot(M,d['pid']))
    doc.update(offer_subject='844 Cenová nabídka',salesperson_id=d['reps']['J'],salesperson_snapshot='Jiří Cír')
    items = [dict(row_type='product',name=f'Výrobek {i:03d}',description='Technický popis '+str(i),
                  quantity=2,unit='ks',purchase_unit_price=100,margin_pct=20,discount_pct=0,
                  category_id=d['cat'],subgroup_id=d['sub'] if i%2==0 else d['sub2'],
                  category_name_snapshot='844 Konstrukce',subgroup_name_snapshot='844 Nosníky' if i%2==0 else '844 Kotvy')
             for i in range(46)]
    return doc,[service.normalize_item(i,recalculate_sale=True) for i in items]


def source_checks(td):
    M,_,d = seeded(td); doc,items = offer(M,d)
    group_pricing.apply(items,[0,2],'margin_pct',30,True)
    group_pricing.apply(items,[0],'margin_pct',50)
    group_pricing.apply(items,[0,2],'margin_pct',40,True)
    group_pricing.apply(items,[0,2],'discount_pct',10,True)
    group_pricing.apply(items,[0],'discount_pct',5)
    group_pricing.apply(items,[0,2],'discount_pct',20,True)
    assert (items[0]['margin_pct'],items[2]['margin_pct'],items[1]['margin_pct'])==(50,40,20)
    assert (items[0]['discount_pct'],items[2]['discount_pct'])==(5,20)
    assert (items[0]['unit_price'],items[2]['unit_price'])==(142.5,112)
    for bad in ('neplatné','nan','inf'):
        before=[dict(i) for i in items]
        try:group_pricing.apply(items,[0,2],'margin_pct',bad,True)
        except ValueError:pass
        else:raise AssertionError('Invalid pricing accepted')
        assert items==before
    did=service.save_document(M,doc,items)
    saved,stored=service.load_document(M,did)
    assert saved['salesperson_id']==d['reps']['J']
    assert stored[0]['margin_override']==1 and stored[0]['group_margin_pct']==40
    assert stored[0]['discount_override']==1 and stored[0]['group_discount_pct']==20
    assert group_pricing.inherit(stored,0,'margin_pct')
    assert stored[0]['margin_pct']==40 and not stored[0]['margin_override']
    assert stored[0]['discount_pct']==5 and stored[0]['discount_override']
    group_pricing.adopt_defaults(stored)
    assert stored[4]['margin_pct']==40 and stored[4]['discount_pct']==20
    assert stored[1]['margin_pct']==20
    from price_lists_domain.issued_offers import professional_workflow as workflow
    changed=[dict(i) for i in stored];changed[0]['margin_override']=1
    assert workflow.editor_fingerprint(saved,stored)!=workflow.editor_fingerprint(saved,changed)
    assert workflow.commercial_fingerprint(saved,stored)==workflow.commercial_fingerprint(saved,changed)
    portfolio.save(M,d['cid'],{d['reps']['H']},{d['reps']['J'],d['reps']['H']})
    try:service.save_document(M,doc,items)
    except ValueError:pass
    else:raise AssertionError('A stale representative was accepted for a new offer')
    service.save_document(M,saved,stored,did)  # Existing historical owner is retained.
    M.ensure_schema()
    assert service.load_document(M,did)[1][0]['margin_override']==0
    assert len(offer_parties.standard_templates(M))==1
    print('844 source: saved stable representative IDs, independent group margin/discount exceptions, atomic validation and inheritance OK',flush=True)


def ui_checks(td):
    M,settle,d=seeded(td)
    M.APP_VERSION=(REPO/'build/windows/version.txt').read_text().strip()
    errors=[]
    M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.messagebox.showinfo=lambda *a,**k:None
    M.App.maybe_show_morning_overview=lambda self:None
    root=M.App(); root.report_callback_exception=lambda *e:errors.append(str(e))
    output=REPO/'build/validation/workspace-844';output.mkdir(parents=True,exist_ok=True)
    def shot(window,name):
        if '--no-screenshots' in sys.argv:return
        from PIL import ImageGrab
        settle(root,.2)
        ImageGrab.grab(bbox=(window.winfo_rootx(),window.winfo_rooty(),window.winfo_rootx()+window.winfo_width(),window.winfo_rooty()+window.winfo_height())).save(output/name)
    def walk(widget):
        yield widget
        for c in widget.winfo_children():yield from walk(c)
    try:
        root.active_user.set('ADMIN');root.refresh_user_access()
        root.state('normal');root.geometry('1550x930+0+0');root.show_page('portfolio');settle(root,1)
        w=root.portfolio_workspace;w.selection.set('Všichni obchodníci');w.refresh()
        w.tree.item(f"c{d['cid']}",open=False)
        w.search.draft.set('eva stastna');settle(root,.4)
        assert w.tree.get_children()==(f"c{d['cid']}",)
        assert w.tree.item(f"c{d['cid']}",'open') and w.tree.bbox(f"p{d['pid']}")
        w.search.confirm();w.search.draft.set('Praha');settle(root,.4)
        assert w.tree.get_children()==(f"c{d['cid']}",)
        shot(root,'portfolio-search.png')
        w.search.clear_button.invoke();settle(root,.4)
        assert not w.search.terms and len(w.tree.get_children())>=2
        print('844 UI: shared search matches hidden contacts and combines terms with parent, clear resets OK',flush=True)
        def pick():
            win=next(c for c in root.winfo_children() if hasattr(c,'taxonomy_tree'))
            win.taxonomy_search.draft.set('nosniky');win.taxonomy_search.run()
            t=win.taxonomy_tree
            assert t.exists(f"s{d['sub']}") and not t.exists(f"s{d['sub2']}")
            assert t.parent(f"s{d['sub']}")==f"c{d['cat']}"
            shot(win,'taxonomy-tree.png')
            t.selection_set(f"s{d['sub']}");win.taxonomy_finish()
        root.after(400,pick)
        assert categories.choose_taxonomy(M,root)==(d['cat'],d['sub'])
        doc,items=offer(M,d)
        view=editor.IssuedOfferEditor(M,root,initial_document=doc,initial_items=items)
        view.win.state('normal');view.win.geometry('1640x960+0+0');settle(root,1)
        panel=view._v791_pricing_panel;preview=view._v720_preview
        view._v791_metadata_button.invoke();settle(root,.3)
        labels=[str(x.cget('text')) for x in walk(view._v791_metadata_panel) if isinstance(x,M.ttk.Label)]
        assert 'Obchodní zástupce' in labels and 'Příležitost' not in labels
        assert len(view.template_map)==1 and 'TURTO' in view.template.get()
        assert set(view.salesperson_map.values())=={d['reps']['J'],d['reps']['H']}
        view.company.set('');settle(root,.2)
        assert not view.salesperson_map and not view.contact_map and view.salesperson.get()==''
        view.company.set('840 Druhý zákazník');settle(root,.2)
        assert set(view.salesperson_map.values())=={d['reps']['M']} and view.contact.get()==''
        view.company.set('840 Sdílený zákazník');view.salesperson.set('Jiří Cír');view.contact.set('Eva Šťastná');settle(root,.2)
        def contact(new):
            def finish():
                win=next(c for c in view.win.winfo_children() if isinstance(c,M.PersonDialog))
                if new:win.vars['name'].set('844 Nová osoba');win.vars['email'].set('nova844@example.test')
                win.vars['phone'].set('777123456');win.ok()
            root.after(350,finish)
            offer_parties.edit_contact(view,new)
        contact(False)
        assert sql(M,'SELECT phone FROM people WHERE id=?',(d['pid'],))[0][0]=='777123456'
        contact(True)
        pid=view.contact_map[view.contact.get()]
        assert sql(M,'SELECT company_id FROM people WHERE id=?',(pid,))[0][0]==d['cid']
        def assign():
            win=next(c for c in view.win.winfo_children() if hasattr(c,'portfolio_variables'))
            for sid,var in win.portfolio_variables.items():var.set(sid==d['reps']['H'])
            next(x for x in walk(win) if isinstance(x,M.ttk.Button) and x.cget('text')=='Uložit').invoke()
        root.after(350,assign);offer_parties.assign_salespeople(view)
        assert list(view.salesperson_map.values())==[d['reps']['H']]
        assert view.collect()['customer_contact_id']==pid
        shot(view.win,'offer-parties.png')
        print('844 UI: company-filtered representatives, shared contact create/edit and assignment edit OK',flush=True)
        view._v791_metadata_button.invoke();settle(root,.2)
        def edit(iid,col,value):
            panel.tree.see(iid);settle(root,.1);panel._open_editor(iid,col)
            assert panel.edit_widget is not None,(iid,col)
            panel.edit_variable.set(str(value));panel.commit_edit();settle(root,.3)
        edit('g0','#3',30);edit('p0','#3',50);edit('g0','#3',40);edit('g0','#4',10)
        assert view.items[0]['margin_pct']==50 and view.items[2]['margin_pct']==40 and view.items[1]['margin_pct']==20
        assert all(view.items[i]['discount_pct']==10 for i in range(0,46,2))
        preview.refresh();settle(root,.3)
        assert preview.canvas_regions,preview.status.get()
        drawn=[r['index'] for r in preview.canvas_regions]
        visible=[int(i[1:]) for i in panel.tree.get_children() if i.startswith('p')]
        assert visible==list(dict.fromkeys(drawn))
        target=next(r for r in preview.canvas_regions if r['index']==20)
        height=float(preview.canvas.cget('scrollregion').split()[3])
        preview.canvas.yview_moveto(target['y0']/height);settle(root,.3)
        first=next(panel.tree.identify_row(y) for y in range(1,65) if panel.tree.identify_row(y))
        assert first=='p20',first
        rows=panel.tree.get_children();panel.tree.yview_moveto(rows.index('p12')/len(rows));settle(root,.3)
        top=preview.canvas.canvasy(0)
        assert abs(top-next(r for r in preview.canvas_regions if r['index']==12)['y0'])<20
        stable=preview.canvas.yview();settle(root,.25);assert preview.canvas.yview()==stable
        preview.change_zoom(-20);settle(root,.4)
        target=next(r for r in preview.canvas_regions if r['index']==32)
        height=float(preview.canvas.cget('scrollregion').split()[3])
        preview.canvas.yview_moveto(target['y0']/height);settle(root,.3)
        assert panel.tree.bbox('p32')
        shot(view.win,'offer-synchronized.png')
        print('844 UI: renderer-order group pricing, both scroll directions, zoom and no feedback loop OK',flush=True)
        did=view.save(quiet=True);assert did
        stored_doc,stored=service.load_document(M,did)
        assert stored_doc['salesperson_id']==d['reps']['H'] and stored_doc['customer_contact_id']==pid
        assert stored[0]['margin_override']==1 and stored[2]['group_margin_pct']==40
        assert not errors,errors
        view.win.destroy();settle(root,.1)
    finally:
        root._turto_closing=True;root._mail_executor.shutdown(wait=False,cancel_futures=True)
        if root.map_workspace.bridge:root.map_workspace.bridge.close()
        for job in root.tk.splitlist(root.tk.call('after','info')):root.tk.call('after','cancel',job)
        root.destroy()


if __name__=='__main__':
    if '--source-worker' in sys.argv:source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:ui_checks(sys.argv[-1])
    else:
        for mode in (['--source-worker'] if '--source-only' in sys.argv else ['--source-worker','--ui-worker']):
            with tempfile.TemporaryDirectory(prefix='turto-844-') as td:
                subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],mode,td],check=True,timeout=240)
