#!/usr/bin/env python3
"""PDF typography, grouped totals, shared identity and offer-local row movement."""
import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('fixture844',ROOT/'scripts/validate-844-offer-workspace.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
from price_lists_domain.issued_offers import service, row_drag, group_pricing, template_layout, corporate_renderer, offer_parties
from price_lists_domain.platform import sales_centers, sales_identity
import fitz


def checks(td):
    M,_,d=fixture.seeded(td);doc,items=fixture.offer(M,d)
    before=copy.deepcopy(items)
    at=row_drag.move(items,0,dict(index=4),after=True)
    assert items[at]['name']==before[0]['name']
    assert all({k:v for k,v in i.items() if k!='position'}=={k:v for k,v in next(p for p in before if p['name']==i['name']).items() if k!='position'} for i in items)
    group_pricing.apply(items,[i for i,r in enumerate(items) if r['subgroup_id']==d['sub2']],'margin_pct',40,True)
    source=next(i for i,r in enumerate(items) if r['name']==before[0]['name'])
    target=next(i for i,r in enumerate(items) if r['subgroup_id']==d['sub2'])
    old=copy.deepcopy(items[source]);moved=row_drag.move(items,source,dict(index=target),after=True)
    assert items[moved]['subgroup_id']==d['sub2']
    assert items[moved]['unit_price']==old['unit_price'] and items[moved]['margin_pct']==old['margin_pct']
    assert items[moved]['group_margin_pct']==40 and items[moved]['margin_override']==1
    did=service.save_document(M,doc,items)
    stored_doc,stored=service.load_document(M,did)
    assert [r['name'] for r in stored]==[r['name'] for r in items]
    assert stored[moved]['margin_override']==1 and stored[moved]['subgroup_id']==d['sub2']
    moved=row_drag.move(items,moved,dict(indices=[target],kind='category'))
    assert items[moved]['subgroup_id'] is None and not items[moved]['subgroup_name_snapshot']
    print('845 source: reorder, taxonomy move, explicit retained prices and save/reopen OK',flush=True)

    sid=d['reps']['J']
    with closing(M.db()) as con:
        rep=dict(con.execute('SELECT * FROM salespeople WHERE id=?',(sid,)).fetchone())
        person=dict(con.execute('SELECT * FROM people WHERE id=?',(rep['person_id'],)).fetchone())
    contact=dict(person_id=person['id'],email='845-rep@example.test',phone='+420 777 111 222',expected=tuple(person[k] for k in ('name','email','phone')))
    sales_centers.save_person(M,sid,'845 Zástupce',True,(rep['name'],rep['active']),contact)
    with closing(M.db()) as con,con:
        assert con.execute('SELECT name,email FROM people WHERE id=?',(person['id'],)).fetchone()[0]=='845 Zástupce'
        con.execute("UPDATE people SET name='845 Jméno z adresáře' WHERE id=?",(person['id'],))
        assert con.execute('SELECT name FROM salespeople WHERE id=?',(sid,)).fetchone()[0]=='845 Jméno z adresáře'
    values={'salesperson_id':sid,'issuer_email_snapshot':'OLD','issuer_phone_snapshot':'OLD'}
    editor=SimpleNamespace(M=M,document_id=did,document=stored_doc,locked=False)
    offer_parties.salesperson_snapshot(editor,values)
    assert values['issuer_email_snapshot']=='845-rep@example.test' and values['issuer_contact_snapshot']=='845 Jméno z adresáře'
    editor.locked=True; historical={'salesperson_id':sid,'issuer_email_snapshot':'HISTORIC'}
    offer_parties.salesperson_snapshot(editor,historical);assert historical['issuer_email_snapshot']=='HISTORIC'
    with closing(M.db()) as con,con:con.execute("UPDATE people SET email='',phone='' WHERE id=?",(person['id'],))
    editor.locked=False;offer_parties.salesperson_snapshot(editor,values)
    assert values['issuer_email_snapshot']==values['issuer_phone_snapshot']==''
    centers=sales_centers.snapshot(M);M.ensure_schema();assert sales_centers.snapshot(M)==centers
    print('845 source: directory/code-list identity, fresh draft contacts, cleared stale contacts and historical snapshots OK',flush=True)
    with closing(M.db()) as con,con:
        cid=con.execute("INSERT INTO companies(official_name,short_name) VALUES('TURTO 845 s.r.o.','TURTO 845')").lastrowid
        pid=con.execute("INSERT INTO people(name,email,phone,company_id) VALUES('Ing. Milan Soukup','milan845@example.test','777000111',?)",(cid,)).lastrowid
        con.execute("DELETE FROM settings WHERE key='migration_sales_contacts_845'")
        sales_identity.link_contacts(con)
        assert con.execute('SELECT person_id FROM salespeople WHERE id=?',(d['reps']['M'],)).fetchone()[0]==pid
    assert sales_centers.snapshot(M)==centers or all(a['salesperson_id']==b['salesperson_id'] and a['valid_from']==b['valid_from'] for a,b in zip(sales_centers.snapshot(M),centers))

    template=offer_parties.standard_templates(M)[0];layout=template_layout.normalize(template['layout_json'])
    assert [c['key'] for c in layout['columns']]==['name','image','unit_price','quantity','total']
    assert (layout['font_size'],layout['subgroup_font_size'],layout['category_font_size'])==(9,10,14)
    assert layout['show_group_subtotals']
    from v710_cleanup import group_offer_items
    interleaved=[dict(items[0],category_name_snapshot='A',subgroup_name_snapshot='A1'),
                 dict(items[0],category_name_snapshot='B',subgroup_name_snapshot='B1'),
                 dict(items[0],category_name_snapshot='A',subgroup_name_snapshot='A2')]
    assert [t['index'] for t in group_offer_items(interleaved) if t['kind']=='item']==[0,2,1]
    # Category spans two subgroups and several pages. Subtotals include every line once.
    lines=[service.normalize_item(dict(row_type='product',name=f'845 Řádek {i}',quantity=12.5,unit='m²' if i%2 else 'KS',
        purchase_unit_price=100,margin_pct=20,discount_pct=10,category_name_snapshot='845 SKUPINA',
        subgroup_name_snapshot='845 PODSKUPINA A' if i<38 else '845 PODSKUPINA B'),recalculate_sale=True) for i in range(80)]
    doc.update(salesperson_id=None,salesperson_snapshot='',issuer_contact_snapshot='',issuer_email_snapshot='')
    result=corporate_renderer.render(M,doc,lines,template,Path(td)/'845.pdf')
    from price_lists_domain.issued_offers import preview_worker
    worker=preview_worker.Worker()
    try:
        reply=worker.submit(preview_worker.payload(M,doc,lines,template)).result(timeout=30)
        with fitz.open(stream=reply['pdf'],filetype='pdf') as preview,fitz.open(Path(td)/'845.pdf') as final:
            assert len(preview)==len(final)
            assert all(preview[i].get_pixmap().samples==final[i].get_pixmap().samples for i in range(len(final)))
    finally:worker.close()
    with fitz.open(Path(td)/'845.pdf') as pdf:
        text=' '.join(' '.join(p.get_text().split()) for p in pdf)
        assert '108,00 Kč/ks' in text and '108,00 Kč/m²' in text and '12,5 ks' in text and '12,5 m²' in text
        assert text.count('Mezisoučet skupiny bez DPH')==1
        assert '108 000,00 Kč' in text
        spans=[s for p in pdf for b in p.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans']]
        def sizes(prefix):return {round(s['size']) for s in spans if s['text'].replace('\xa0',' ').startswith(prefix)}
        assert sizes('845 SKUPINA')=={14} and sizes('845 PODSKUPINA')=={10} and sizes('845 Řádek')=={9}
        for r in result['regions']:
            label=lines[r['index']]['subgroup_name_snapshot']
            assert label in ' '.join(pdf[r['page']].get_text().split())
    layout.update(font_size=8,subgroup_font_size=11,category_font_size=16,show_group_subtotals=False)
    template['layout_json']=json.dumps(layout)
    service.save_template(M,template,template['id'],standard=True)
    M.ensure_schema()
    assert template_layout.normalize(offer_parties.standard_templates(M)[0]['layout_json'])==layout
    start=time.perf_counter()
    large=corporate_renderer.render(M,doc,lines*6,dict(template,_preview_fast=True),Path(td)/'large.pdf')
    elapsed=time.perf_counter()-start
    assert large['pages']>10
    print(f'845 PDF: units, 9/10/14pt, repeated headings, category sum and editable standard settings OK; 480 rows / {large["pages"]} pages laid out in {elapsed:.2f}s',flush=True)


if __name__=='__main__':
    if '--worker' in sys.argv:checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-845-') as td:
            subprocess.run([sys.executable,'-B',__file__,'--worker',td],check=True,timeout=240)
