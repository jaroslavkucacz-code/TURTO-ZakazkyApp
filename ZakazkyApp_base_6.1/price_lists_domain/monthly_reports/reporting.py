"""Paginated management report. Local HTML/SVG only; no external resources."""
from __future__ import annotations
from html import escape
from datetime import date
from .constants import APP_NAME, APP_VERSION, center_display
from .analytics import MONTH_NAMES, period_bounds
from .chart_geometry import money, percent, count, number
from .report_model import collect_report
from . import report_svg as charts

CSS='''
@page { size:A4 landscape; margin:10mm 11mm; }
*{box-sizing:border-box}body{margin:0;background:white;color:#172B43;font:12px/1.38 Calibri,Carlito,Arial,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.page{height:187mm;position:relative;break-after:page;page-break-after:always;padding-bottom:9mm}.page:last-child{break-after:auto;page-break-after:auto}
.header{height:58px;display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #159F86;margin-bottom:12px;padding-bottom:9px}
.brand{font-weight:800;font-size:23px;letter-spacing:1px}.eyebrow{font-size:10px;letter-spacing:1.1px;text-transform:uppercase;color:#61738A}
.header .period{text-align:right;font-size:12px}.header .period b{display:block;font-size:17px}
h1{font-size:24px;line-height:1.18;margin:0 0 4px;letter-spacing:-.4px}h2{font-size:15px;margin:0 0 4px}h3{font-size:13px;margin:0 0 4px}p{margin:0 0 7px}
.subtitle{color:#61738A;font-size:11px;margin-bottom:12px}.muted{color:#61738A}.tiny{font-size:10px}.nowrap{white-space:nowrap}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.kpi{border:1px solid #DCE5ED;border-top:3px solid #159F86;border-radius:6px;padding:9px 12px;min-height:79px}
.kpi .label{font-size:11px;color:#61738A}.kpi .value{font-size:23px;line-height:1.25;font-weight:700;white-space:nowrap;margin:3px 0}.kpi .note{font-size:10px;color:#61738A}
.card{border:1px solid #DFE7EF;border-radius:7px;padding:10px 12px;break-inside:avoid;page-break-inside:avoid;min-width:0}.card+.card{margin-top:10px}.grid>.card+.card{margin-top:0}
.card .subtitle{margin:0 0 6px}.notice{padding:9px 12px;background:#EFF7F5;border-left:3px solid #159F86;border-radius:0 4px 4px 0;font-size:11px;line-height:1.4;margin-top:10px}
.warning{background:#FBF6EB;border-color:#B67A16}.legend{display:flex;gap:19px;align-items:center;font-size:11px;margin:4px 0;color:#61738A}.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}.legend .bar{height:9px;width:9px;background:#159F86}.legend .profit{background:#B67A16}.legend .margin{height:0;border-top:2px dashed #3572BB}
table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:11px}thead{display:table-header-group}tr{break-inside:avoid;page-break-inside:avoid}th{color:#fff;background:#172B43;padding:6px 7px;text-align:left;line-height:1.2;font-size:10.5px}td{border-bottom:1px solid #E4EBF1;padding:6px 7px;vertical-align:top;line-height:1.28;overflow-wrap:anywhere}tr:nth-child(even) td{background:#F6F8FB}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;overflow-wrap:normal}.compact td{padding:4px 6px;font-size:10.5px}
.footer{position:absolute;bottom:0;left:0;right:0;border-top:1px solid #DFE7EF;padding-top:5px;display:flex;justify-content:space-between;font-size:9px;color:#61738A}
.stat{padding:10px 12px;background:#F4F7FA;border-radius:5px}.stat b{display:block;font-size:20px;margin:3px 0}.break{margin-top:12px}.meta{font-size:11px;line-height:1.5}.positive{color:#137D69}.negative{color:#BE4C55}
'''


def esc(value):return escape(str(value if value is not None else '—'))


def period_label(data):
    names={'month':'Měsíc','ytd':'Od začátku roku','year':'Rok','rolling12':'Posledních 12 měsíců'}
    a=date.fromisoformat(data['start']);b=date.fromisoformat(data['end'])
    title=f'{MONTH_NAMES[data["month"]-1]} {data["year"]}' if data['mode']=='month' else (str(data['year']) if data['mode']=='year' else names[data['mode']])
    return title, f'{a:%d.%m.%Y} – {b:%d.%m.%Y}'


def table(headings,rows,widths=None,numeric=(),compact=False):
    cls='compact' if compact else ''
    cols='<colgroup>'+''.join(f'<col style="width:{w}%">' for w in widths)+'</colgroup>' if widths else ''
    out=[f'<table class="{cls}">{cols}<thead><tr>']
    out.extend(f'<th class="{"num" if i in numeric else ""}">{esc(x)}</th>' for i,x in enumerate(headings));out.append('</tr></thead><tbody>')
    for row in rows:out.append('<tr>'+''.join(f'<td class="{"num" if i in numeric else ""}">{esc(x)}</td>' for i,x in enumerate(row))+'</tr>')
    if not rows:out.append(f'<tr><td colspan="{len(headings)}" class="muted">Pro toto období nejsou dostupné záznamy.</td></tr>')
    out.append('</tbody></table>');return ''.join(out)


def card(title,body,subtitle=''):
    return f'<div class="card"><h2>{esc(title)}</h2><div class="subtitle">{esc(subtitle)}</div>{body}</div>'


def notice(text,warning=False):return f'<div class="notice {"warning" if warning else ""}">{esc(text)}</div>'


def profit(row,key='profit'):
    return money(row.get(key))+(' *' if not row.get('profit_complete',True) else '') if row.get('profit_available',True) else '—'


def legacy_note(data):
    c=data['kpis']['coverage']
    msg=f"Zisk spárovaný na jednotlivé DL: {c['profit_docs']} / {c['total_docs']} dokladů."
    if c['legacy_months']:msg+=f" U {c['legacy_months']} měsíců je zisk převzatý z historického souhrnu; nelze jej rozdělit zákazníkům a produktům."
    if c['missing_months']:msg+=' Zisk je neúplný (*); marže za celé období se proto neuvádí.'
    return msg


def share_caption(rows,key):
    return 'Obsahuje záporné hodnoty: místo koláče je použito částkové srovnání.' if any((number(x.get(key)) or 0)<0 for x in rows) else 'TOP 5 + ostatní; procenta ze součtu dostupných hodnot.'


def build_html(analytics,year,month,mode='month'):
    return render_report(collect_report(analytics,year,month,mode))


def render_report(d):
    k=d['kpis'];title,dates=period_label(d);pages=[]
    sales=[dict(x,profit=x['profit'] if x.get('profit_available') else None) for x in d['sales']]
    customers=[dict(x,profit=x['profit'] if x.get('profit_available') else None) for x in d['customers']]
    products=d['products'];trend=d['trend']
    context=('Kontext od ledna do vybraného měsíce' if d['mode']=='month' else 'Vývoj v rozsahu exportovaného období')
    legend='<div class="legend"><span><i class="bar"></i>Obrat bez DPH</span><span><i class="profit"></i>Hrubý zisk</span><span><i class="margin"></i>Marže % · pravá osa</span></div>'
    previous=(f"{k['yoy']:+.1f} % meziročně".replace('.',',') if k.get('yoy_available') else 'Srovnatelné předchozí období není k dispozici')
    values=[('Obrat podle DL',money(k['revenue']),previous),('Hrubý zisk',profit(k),'Součet dostupných ziskových podkladů'),
            ('Vážená marže',percent(k['margin']),'Zisk / prodejní hodnota bez DPH'),('Dodací listy',count(k['count']),'Počet dokladů za vybrané období'),
            ('Průměrná hodnota DL',money(k['avg_order']),'Obrat / počet dodacích listů'),('Režijní listy',money(k['overhead']),'Samostatně; částka podle zdrojového exportu')]
    kpis='<div class="kpis">'+''.join(f'<div class="kpi"><div class="label">{esc(a)}</div><div class="value">{esc(b)}</div><div class="note">{esc(c)}</div></div>' for a,b,c in values)+'</div>'
    body=kpis+card('Obrat, zisk a marže',legend+charts.trend(trend,h=210),context)
    body+=notice(legacy_note(d),not k['profit_complete'])
    pages.append(('Manažerský souhrn','Přehled výsledků z dodacích listů; nikoli účetní výkaz zisku a ztráty.',body))

    # Page 2: chronological detail. Zero and missing profit remain distinct.
    rows=[]
    for x in trend:
        rows.append((x['period'],money(x['revenue']),profit(x),percent(x['margin']),count(x['count']),
                     {'raw':'Zisk podle DL','legacy':'Historický souhrn','partial':'Částečný zisk','empty':'Bez dat','missing':'Zisk chybí'}[x['source']]))
    body='<div class="grid">'+card('Počet dodacích listů',charts.month_bars(trend,'count',fmt='count',h=120),context)+card('Režijní listy podle středisek',charts.bars([dict(x,label=center_display(x['center'])) for x in d['overheads']],'amount','label',h=120),'Částka podle exportu, samostatně od hrubého zisku.')+'</div>'
    body+='<div class="break">'+table(('Období','Obrat bez DPH','Dostupný zisk','Marže','DL','Zdroj zisku'),rows,(12,22,22,12,8,24),(1,2,3,4),True)+'</div>'
    body+=notice('Pomlčka znamená chybějící údaj, nikoli nulový výkon. Nulové částky se zobrazí jako 0 Kč. Měsíce po posledním dostupném záznamu nejsou vykreslené.')
    pages.append(('Měsíční vývoj',context+'. Ukazatele odpovídají tabulce pod grafy.',body))

    # Page 3: all four sales groups, including unassigned.
    body='<div class="grid">'+card('Podíl na obratu',charts.shares(sales,'revenue','name'),share_caption(sales,'revenue'))+card('Zisk obchodníků',charts.bars(sales,'profit','name'),'Částkové srovnání; zisk může obsahovat historické souhrny.')+'</div>'
    rows=[(x['name'],money(x['revenue']),profit(x),percent(x['margin']),count(x['count']),money(x['avg_order']),percent(x.get('profit_share')) if k['profit_available'] and k['profit'] else '—') for x in sorted(sales,key=lambda x:x.get('profit') or 0,reverse=True)]
    body+='<div class="break">'+table(('Obchodník','Obrat','Zisk','Marže','DL','Ø hodnota DL','Podíl na zisku'),rows,(16,18,18,11,7,17,13),(1,2,3,4,5,6))+'</div>'
    body+=notice('J = Jiří Cír · H = Jan Mayer · M = Milan Soukup. Neznámé a prázdné kódy středisek jsou zahrnuté jako Nezařazené. '+legacy_note(d))
    pages.append(('Výkon obchodníků','Obrat, zisk, marže i objem dokladů ve společném období.',body))

    # Page 4: customer charts draw from the full customer set, not the top table.
    body='<div class="grid">'+card('Zastoupení zákazníků',charts.shares(customers,'revenue','customer',h=128),share_caption(customers,'revenue'))+card('TOP zákazníci podle zisku',charts.bars(customers,'profit','customer',h=128,limit=5),'Pouze dostupný zisk spárovaných dodacích listů.')+'</div>'
    rows=[(x['customer'],money(x['revenue']),profit(x),percent(x['margin'])+(' *' if x['margin'] is not None and not x['profit_complete'] else ''),count(x['count']),f"{x['profit_docs']} / {x['count']}") for x in sorted(customers,key=lambda x:x['revenue'],reverse=True)[:10]]
    body+='<h2 class="break">TOP 10 zákazníků podle obratu</h2>'+table(('Zákazník','Obrat','Dostupný zisk','Marže známých DL','DL','DL se ziskem'),rows,(33,18,18,14,6,11),(1,2,3,4,5),True)
    body+=notice(f"Zákazníků ve zdrojovém výběru: {len(customers)}. Hvězdička (*) označuje částečný zisk nebo marži pouze z DL se známým ziskem. Neznámé zákazníky ({d['no_customer']['count']} DL, {money(d['no_customer']['revenue'])}) nelze přiřadit do zákaznického žebříčku.")
    pages.append(('Zákazníci a jejich zastoupení','Grafy vycházejí ze všech pojmenovaných zákazníků vybraného období.',body))

    # Page 5: no fictitious sales or margins when line prices are unavailable.
    cov=d['items']
    detail=f"Položkové podklady: {cov['item_docs']} / {cov['total_docs']} dodacích listů.\n\n"
    detail+=('Prodejní hodnoty jsou dostupné alespoň pro některé položky. * označuje neúplné pokrytí cen; marže je počítaná pouze na oceněných řádcích.' if cov['sales_available'] else 'Položkový prodej a pořizovací náklad současný export neobsahuje. Zisk je známý, ale procentní marži bez prodejní hodnoty nelze určit.')
    body='<div class="grid">'+card('TOP produkty podle zisku',charts.bars(products,'profit','name',h=128,limit=5),'Zisk položek ze spárovaných skladových dokladů.')+card('Dostupnost položkových dat',charts.coverage(cov['item_docs'],cov['total_docs'],'Dodací listy s položkami',h=80)+f'<div class="tiny muted">{esc(detail).replace(chr(10),"<br>")}</div>')+'</div>'
    rows=[]
    for x in products[:10]:
        suffix=' *' if x.get('sales') is not None and not x.get('sales_complete') else ''
        qty=f'{x["quantity"]:,.2f}'.replace(',',' ').replace('.',',').rstrip('0').rstrip(',')
        rows.append((x['code'],x['name'],qty,money(x['profit']),money(x.get('sales'))+suffix,percent(x.get('margin'))+suffix,count(x['documents'])))
    body+='<h2 class="break">TOP 10 produktů podle zisku</h2>'+table(('Kód','Produkt','Množství','Zisk','Prodej','Marže','DL'),rows,(17,31,10,14,13,9,6),(2,3,4,5,6),True)
    body+=notice(f"Produktových kombinací kód / název: {len(products)}. Množství je uvedeno v jednotkách zdrojového exportu; množství různých produktů nesčítáme. Historický souhrnný zisk se na položky nerozděluje.")
    pages.append(('Produkty a položkový zisk','Nejvýznamnější položky a připravené cenové ukazatele.',body))

    # Pages 6–7: readable full names, never a 24-row tiny-font table.
    docs=d['documents']
    chunks=[docs[i:i+12] for i in range(0,len(docs),12)] or [[]]
    for index,part in enumerate(chunks):
        head=f'Největší dodací listy · {index*12+1}–{index*12+len(part)}' if part else 'Dodací listy'
        rows=[(x['doc_no'],x['doc_date'],center_display(x['center']),x['customer'],x['project'] or '—',money(x['base_amount']),money(x['profit']),percent(x['margin'])) for x in part]
        body=table(('Doklad','Datum','Obchodník','Zákazník','Zakázka','Částka bez DPH','Zisk','Marže'),rows,(12,10,10,22,12,14,12,8),(5,6,7),True)
        body+=notice('Pořadí je podle hodnoty DL bez DPH. Zisk a marže jednotlivých dokladů se uvádí pouze při dostupném spárovaném ziskovém reportu. Částky vycházejí z databáze; historický souhrn se na DL nerozpočítává.')
        body+='<div class="break">'+card('Zisk vybraných velkých dokladů',charts.bars(part,'profit','doc_no',w=1000,h=80,limit=4),'Srovnání pouze mezi doklady uvedenými na této stránce.')+'</div>'
        pages.append((head,'Detail největších dokladů ve vybraném období. Úplné položky DL jsou v aplikaci.',body))

    # Last page: source transparency and data quality instead of guessed KPIs.
    coverage=k['coverage'];items=d['items']
    body='<div class="grid">'+card('Pokrytí zisku podle dokladů',charts.coverage(coverage['profit_docs'],coverage['total_docs'],'Spárované ziskové doklady'))+card('Pokrytí položkového detailu',charts.coverage(items['item_docs'],items['total_docs'],'Dodací listy s položkami'))+'</div>'
    unassigned=[(x['center'],count(x['count']),money(x['revenue'])) for x in d['unassigned']]
    body+='<div class="grid break">'+card('Nezařazená střediska',table(('Kód','DL','Obrat'),unassigned,(40,20,40),(1,2)))+card('Jak číst report','<div class="meta">Obrat = hodnota dodacích listů bez DPH, nikoli vydané faktury.<br>Zisk = skladový hrubý zisk z dostupných podkladů, nikoli čistý zisk firmy.<br>Marže = zisk / odpovídající prodejní hodnota.<br>Pomlčka = údaj chybí nebo podíl nemá platný základ.<br>* = částečná hodnota nebo neúplné pokrytí.</div>')+'</div>'
    ir=[(x['imported_at'].replace('T',' '),x['import_type'],x['file_name'],count(x['row_count']),x['status']) for x in d['imports'][:6]]
    body+='<h2 class="break">Použité importy a historické podklady</h2>'+table(('Načteno','Typ','Zdrojový soubor','Řádky importu','Stav'),ir,(19,21,39,13,8),(3,),True)
    body+=notice(legacy_note(d)+' Report je vytvořen z jednoho konzistentního snímku databáze; při jeho přípravě se zdrojová data nemění.',not coverage['complete'])
    pages.append(('Dostupnost dat a zdroje','Rozlišení kompletních, historických a chybějících podkladů.',body))

    from .management_exports import pdf_pages
    if 'management' in d: pages.extend(pdf_pages(d))

    out=['<!doctype html><html lang="cs"><head><meta charset="utf-8">',f'<title>TURTO | Manažerský report | {esc(title)}</title><style>{CSS}</style></head><body>']
    for i,(heading,sub,body) in enumerate(pages,1):
        out.append(f'<section class="page"><header class="header"><div><div class="brand">TURTO</div><div class="eyebrow">Měsíční přehledy · manažerský report</div></div><div class="period"><b>{esc(title)}</b>{esc(dates)}</div></header><h1>{esc(heading)}</h1><div class="subtitle">{esc(sub)}</div><main>{body}</main><footer class="footer"><span>Interní report · verze {APP_VERSION} · Export {esc(d["generated"])}</span><span>{i} / {len(pages)}</span></footer></section>')
    out.append(PAGINATION+'</body></html>');return ''.join(out)


# Fixed-size designed pages, with a measured overflow fallback for unusual names,
# fonts or exceptionally tall rows. Rows and footers are never silently clipped.
PAGINATION = r"""<script>
(function(){
 function continuation(page){
   let n=document.createElement('section');n.className='page';
   for(let q of ['header','h1','.subtitle']) n.append(page.querySelector(q).cloneNode(true));
   if(!n.querySelector('h1').textContent.includes('pokračování'))n.querySelector('h1').textContent+=' (pokračování)';
   n.append(document.createElement('main'));n.append(page.querySelector('footer').cloneNode(true));
   page.after(n);return n;
 }
 function paginate(){
   let loops=0;
   for(let page of Array.from(document.querySelectorAll('.page'))){
     let current=page;
     while(current && ++loops<150){
       let main=current.querySelector('main'),next=null;
       const limit=()=>current.querySelector('footer').getBoundingClientRect().top-12;
       while(main.getBoundingClientRect().bottom>limit() && main.children.length){
         let last=main.lastElementChild;
         let tab=last.tagName==='TABLE'?last:last.querySelector('table');
         if(tab && tab.tBodies.length && tab.tBodies[0].rows.length>1){
           let rows=Array.from(tab.tBodies[0].rows),cut=rows.findIndex(r=>r.getBoundingClientRect().bottom>limit()-5);
           if(cut>0 && cut<rows.length){
             if(!next)next=continuation(current);
             let cloned=last.cloneNode(true),ct=cloned.tagName==='TABLE'?cloned:cloned.querySelector('table');ct.tBodies[0].innerHTML='';
             rows.slice(cut).forEach(r=>ct.tBodies[0].append(r));next.querySelector('main').prepend(cloned);break;
           }
         }
         if(main.children.length===1){
           // Pathologically large single block: let the print layout flow rather
           // than hide text. Normal tables above are split at real row bounds.
           current.style.height='auto';current.style.minHeight='187mm';
           current.querySelector('footer').style.position='static';break;
         }
         if(!next)next=continuation(current);
         next.querySelector('main').prepend(last);
         if(main.lastElementChild && /^H[23]$/.test(main.lastElementChild.tagName)) next.querySelector('main').prepend(main.lastElementChild);
       }
       current=next;
     }
   }
   let pages=Array.from(document.querySelectorAll('.page'));
   pages.forEach((p,i)=>p.querySelector('footer span:last-child').textContent=(i+1)+' / '+pages.length);
   window.TURTO_REPORT_READY=true;
 }
 paginate();
 document.fonts.ready.then(paginate);
})();</script>"""
