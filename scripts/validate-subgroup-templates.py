"""Subgroup columns, mixed bulk changes, real template UI and export parity."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixture844', ROOT/'scripts/validate-844-offer-workspace.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
from price_lists_domain.issued_offers import (subgroup_layout as sg, template_layout as tl,
    corporate_renderer, service, template_settings, template_bundle, preview_worker)
import fitz

OUTPUT = ROOT/'build/validation/subgroup-templates'


def data(M, d):
    fixture.sql(M,"UPDATE product_categories SET name='STAVEBNÍ PRVKY' WHERE id=?",(d['cat'],))
    fixture.sql(M,"UPDATE product_subgroups SET name='Nosníky' WHERE id=?",(d['sub'],))
    fixture.sql(M,"UPDATE product_subgroups SET name='Kotvy' WHERE id=?",(d['sub2'],))
    doc, base = template_settings.sample_offer()
    doc.update(document_number='UKÁZKA PODSKUPIN', template_id=service.default_template_id(M))
    items=[]
    for n in range(6):
        first=n<3
        items.append(service.normalize_item(dict(base[n%5],
            category_id=d['cat'],subgroup_id=d['sub'] if first else d['sub2'],
            category_name_snapshot='STAVEBNÍ PRVKY',
            subgroup_name_snapshot='Nosníky' if first else 'Kotvy',
            name=('Nosník' if first else 'Kotva')+f' {n+1}',
            internal_code_snapshot=f'TR-{n+1:03d}',
            description=f'Technický popis {n+1}; rozměry a materiál dle specifikace.',
            line_note=f'Poznámka podskupiny {n+1}', discount_pct=5,
            unit_price=base[n%5]['unit_price']*.95)))
    return doc,items


def configured(items):
    layout=tl.normalize()
    layout['subgroup_layouts']=sg.change(layout,[items[0]],{'col:image':False,'show_line_note':False})
    layout['subgroup_layouts']=sg.change(layout,[items[3]],{'col:image':False,'col:code':True,'col:discount':True,'show_description':False,'show_line_note':False})
    return layout


def pdf_checks(td):
    M,_,d=fixture.seeded(td);doc,items=data(M,d)
    before=copy.deepcopy(items)
    layout=configured(items)
    # Mixed updates preserve unrelated differences and reset only the targets.
    changed=sg.change(layout,[items[0],items[3]],{'show_code':False})
    assert changed[0]['show_description'] and not changed[1]['show_description']
    assert 'discount' not in changed[0]['columns'] and 'discount' in changed[1]['columns']
    assert not any(r['show_code'] for r in changed)
    assert len(sg.change(dict(layout,subgroup_layouts=changed),[items[0]],{},inherit=True))==1
    renamed=dict(items[0],subgroup_name_snapshot='Přejmenovaná podskupina')
    assert sg.find(layout['subgroup_layouts'],renamed) is layout['subgroup_layouts'][0]
    other=dict(items[0],category_id=999,subgroup_id=999)
    assert sg.find(layout['subgroup_layouts'],other) is None
    for bad in ([dict(sg.scope(items[0]),columns=['unit_price'])],
                [dict(sg.scope(items[0]),columns=['name','purchase_unit_price'])]):
        try:tl.normalize(dict(layout,subgroup_layouts=bad))
        except ValueError:pass
        else:raise AssertionError('Invalid/private PDF column accepted')
    template=dict(tl.builtin_template(),layout_json=json.dumps(layout))
    result=corporate_renderer.render(M,doc,items,template,OUTPUT/'subgroups-example.pdf')
    assert len(result['table_regions'])==2, result['table_regions']
    for row in result['regions']:
        headings=[h for h in result['group_regions'] if h['kind']=='subgroup' and h['page']==row['page'] and row['index'] in h['indices'] and h['y1']<=row['y0']]
        headers=[h for h in result['table_regions'] if h['page']==row['page'] and row['index'] in h['indices'] and h['y1']<=row['y0']]
        assert headings and headers and headers[-1]['y0']>=headings[-1]['y1']
    assert result['table_regions'][0]['columns']==['name','unit_price','quantity','total']
    assert 'discount' in result['table_regions'][1]['columns']
    with fitz.open(OUTPUT/'subgroups-example.pdf') as pdf:
        text=' '.join(' '.join(p.get_text() for p in pdf).split())
        assert 'Technický popis 1' in text and 'Technický popis 4' not in text
        assert 'Poznámka podskupiny' not in text
        pdf[0].get_pixmap(matrix=fitz.Matrix(1.7,1.7)).save(OUTPUT/'subgroups-example.png')
    # Continuations must retain the same subgroup columns after the grey title.
    many=[dict(items[i%6]) for i in range(75)]
    many[2]['description']='\n'.join(f'Rozměr a ověření {i}' for i in range(90))
    result=corporate_renderer.render(M,doc,many,template,OUTPUT/'subgroups-many.pdf')
    assert result['pages']>3
    for row in result['regions']:
        headers=[h for h in result['table_regions'] if h['page']==row['page'] and row['index'] in h['indices'] and h['y1']<=row['y0']]
        headings=[h for h in result['group_regions'] if h['kind']=='subgroup' and h['page']==row['page'] and row['index'] in h['indices'] and h['y1']<=row['y0']]
        assert headers and headings and headings[-1]['y1']<=headers[-1]['y0'], (row,headers,headings)
        assert headers[-1]['columns']==[c['key'] for c in sg.effective(layout,many[row['index']])['columns']]
    # A name-only presentation still calculates unchanged offer/group totals.
    narrow=copy.deepcopy(layout)
    narrow['subgroup_layouts'][0]['columns']=['name']
    r=corporate_renderer.render(M,doc,items,dict(template,layout_json=json.dumps(narrow)),OUTPUT/'name-only.pdf')
    assert r['totals']==service.calculate_totals(items,doc.get('global_discount_pct'))
    assert items==before
    service_row=service.normalize_item(dict(row_type='service',name='Montáž',quantity=1,unit='ks',unit_price=500,vat_rate=21))
    standalone=corporate_renderer.render(M,doc,[service_row],template,OUTPUT/'service-only.pdf')
    assert len(standalone['table_regions'])==1 and standalone['table_regions'][0]['columns']==[c['key'] for c in layout['columns']]
    # Persist/export/import retains the profile but never exports local row IDs.
    old_hash=hashlib.sha256((OUTPUT/'subgroups-example.pdf').read_bytes()).hexdigest()
    service.save_template(M,template,doc['template_id'],standard=True)
    saved=service.load_template(M,doc['template_id'])
    assert tl.normalize(saved['layout_json'])['subgroup_layouts']==layout['subgroup_layouts']
    template_bundle.export_template(M,saved,OUTPUT/'template.zip')
    imported=template_bundle.import_template(M,OUTPUT/'template.zip')
    portable=tl.normalize(service.load_template(M,imported)['layout_json'])
    assert all(r['subgroup_id'] is None and r['category_id'] is None for r in portable['subgroup_layouts'])
    assert sg.choices(portable,items[3])==sg.choices(layout,items[3])
    assert hashlib.sha256((OUTPUT/'subgroups-example.pdf').read_bytes()).hexdigest()==old_hash
    worker=preview_worker.Worker()
    try:
        # The worker must use DB ordering and renamed catalogue headings too.
        fixture.sql(M,"UPDATE product_subgroups SET sort_order=-10,name='Kotvy – aktuální název' WHERE id=?",(d['sub2'],))
        corporate_renderer.render(M,doc,items,template,OUTPUT/'ordered.pdf')
        answer=worker.submit(preview_worker.payload(M,doc,items,template)).result(timeout=30)
        with fitz.open(stream=answer['pdf'],filetype='pdf') as preview,fitz.open(OUTPUT/'ordered.pdf') as final:
            assert len(preview)==len(final)
            assert all(p.get_pixmap().samples==f.get_pixmap().samples for p,f in zip(preview,final))
    finally:worker.close()
    print('Subgroups: independent/mixed settings, stable IDs, portable rules, headers on continuations, unchanged totals and worker/export parity OK',flush=True)


def ui_checks(td):
    M,settle,d=fixture.seeded(td);doc,items=data(M,d)
    errors=[]
    M.messagebox.showwarning=lambda *a,**k:errors.append(a)
    M.messagebox.showerror=lambda *a,**k:errors.append(a)
    M.App.maybe_show_morning_overview=lambda self:None
    root=M.App();root.report_callback_exception=lambda *e:errors.append(str(e))
    dlg=None
    try:
        root.active_user.set('ADMIN');root.refresh_user_access();settle(root,.5)
        dlg=template_settings.TemplateEditor(M,root,doc,items,standard_only=True)
        settle(root,.5);dlg.win.state('normal');dlg.win.geometry('1540x960+0+0')
        def ready():
            deadline=time.monotonic()+25
            while not dlg.preview_valid and time.monotonic()<deadline:settle(root,.05)
            assert dlg.preview_valid,dlg.status.get()
            settle(root,.1)
        ready()
        dlg.subgroups.select_scope(items[0]);dlg.subgroups.apply_change('col:image',False)
        dlg.subgroups.select_scope(items[3]);dlg.subgroups.apply_change('col:discount',True)
        dlg.subgroups.select_scope(items[0],add=True)
        assert len(dlg.subgroups.targets())==2
        assert dlg.subgroups.variables['col:image'].get()==-1
        assert dlg.subgroups.variables['col:discount'].get()==-1
        dlg.subgroups.buttons['col:image'].invoke()
        dlg.subgroups.buttons['col:image'].invoke()
        values=dlg.subgroups.layout()
        assert not any(sg.choices(values,i)['col:image'] for i in (items[0],items[3]))
        assert sg.choices(values,items[3])['col:discount'] and not sg.choices(values,items[0])['col:discount']
        dlg.subgroups.apply_change('show_line_note',False)
        ready()
        # Actual preview click selects the subgroup; zoom uses the cached PDF.
        region=next(r for r in dlg.preview_result['table_regions'] if 3 in r['indices'])
        viewer=dlg.viewer;left,top,_,_=viewer.offsets[region['page']]
        y=top+(region['y0']+region['y1'])/2*viewer.scale
        height=float(viewer.canvas.cget('scrollregion').split()[3])
        viewer.canvas.yview_moveto(max(0,y-120)/height);settle(root,.2)
        viewer.canvas.event_generate('<Button-1>',x=int(left+(region['x0']+10)*viewer.scale),y=int(y-viewer.canvas.canvasy(0)))
        settle(root,.2)
        assert len(dlg.subgroups.targets())==1 and dlg.subgroups.targets()[0]['subgroup_id']==d['sub2']
        cached=viewer.pdf;viewer.zoom(.15);settle(root,.2);assert viewer.pdf is cached
        viewer.fit_width();settle(root,.2)
        from PIL import ImageGrab
        ImageGrab.grab(window=dlg.win.winfo_id()).save(OUTPUT/'template-editor.png')
        # Rapid changes cannot let an old worker result replace the latest one.
        dlg.subgroups.apply_change('show_description',False)
        dlg.subgroups.apply_change('show_description',True)
        dlg.subgroups.apply_change('show_description',False)
        ready()
        preview_text=' '.join(' '.join(p.get_text() for p in viewer.pdf).split())
        assert 'Technický popis 1' in preview_text and 'Technický popis 4' not in preview_text
        # Sample mode can preview catalogue groups absent from the current offer.
        dlg.preview_mode.set('Vybrané podskupiny – ukázka')
        dlg.subgroups.select_all();dlg.schedule();ready()
        assert len(dlg.last_preview_items)==16 and len(viewer.pdf)>1
        assert 'prvních 8' in dlg.status.get()
        viewer.change_page(1);settle(root,.2)
        assert viewer.page_index()>0 and len(viewer.images)<len(viewer.pdf)+1
        dlg.subgroups.search.set('Kotvy');settle(root,.1)
        assert all(t['subgroup']=='Kotvy' for t in dlg.subgroups.targets())
        dlg.subgroups.search.set('');dlg.preview_mode.set('Aktuální nabídka');dlg.schedule();ready()
        dlg.save();settle(root,.2)
        saved=tl.normalize(service.load_template(M,doc['template_id'])['layout_json'])
        assert not sg.choices(saved,items[3])['show_description'] and sg.choices(saved,items[3])['col:discount']
        dlg.close();settle(root,.2);assert not dlg.win.winfo_exists()
        assert not errors,errors
        print('Template UI: real multi-selection/mixed toggles, PDF click selection, cached zoom, async updates and save/reopen OK',flush=True)
    finally:
        if dlg is not None and dlg.win.winfo_exists():dlg.win.destroy()
        root.destroy()


if __name__=='__main__':
    OUTPUT.mkdir(parents=True,exist_ok=True)
    if '--worker' in sys.argv:(ui_checks if '--ui' in sys.argv else pdf_checks)(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-subgroup-template-') as td:
            subprocess.run([sys.executable,'-B',__file__,*sys.argv[1:],'--worker',td],check=True,timeout=150)
