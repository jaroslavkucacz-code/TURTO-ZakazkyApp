"""Export additional management views from the same report snapshot."""
from .management import collect_management


def add_excel(wb,analytics,year,month,mode):
    data=collect_management(analytics,year,month,mode)
    header=wb.add_format({'font_name':'Calibri','bold':True,'bg_color':'#172033','font_color':'white','text_wrap':True})
    normal=wb.add_format({'font_name':'Calibri','valign':'top'})
    money=wb.add_format({'font_name':'Calibri','num_format':'# ##0.00 "Kč"'})
    percent=wb.add_format({'font_name':'Calibri','num_format':'0.0" %"'})
    tables=[
      ('Vývoj firmy','months',[('Období','period'),('Obrat','revenue'),('Obrat loni','previous_revenue'),('Rozdíl Kč','change'),('Změna %','change_percent'),('Dostupný zisk','profit'),('Marže %','margin'),('Počet DL','count'),('Průměr DL','average'),('Podklady','data_note')]),
      ('Změny zákazníků','customers',[('Zákazník','customer'),('Obrat','revenue'),('Obrat loni','previous_revenue'),('Rozdíl Kč','change'),('Změna %','change_percent'),('Počet DL','count'),('Stav','state'),('První evidovaný odběr','first_date')]),
      ('Zakázky','projects',[('Zakázka','project'),('Počet DL','documents'),('Obrat','revenue'),('Dostupný zisk','profit'),('Marže %','margin'),('DL se ziskem / celkem','coverage')]),
      ('Kontrola dat','coverage',[('Období','period'),('DL z POHODY','delivery_documents'),('Chybí export DL','missing_delivery'),('DL se ziskem','profit_documents'),('Pokrytí %','coverage'),('Zdroj zisku','profit_source'),('Položek','items'),('Položek s prodejem','priced'),('Poslední datum','latest_date'),('Co doplnit','status')])]
    for name,key,cols in tables:
        ws=wb.add_worksheet(name);ws.hide_gridlines(2);ws.freeze_panes(1,1);ws.set_row(0,32)
        for c,(title,field) in enumerate(cols):
            ws.write_string(0,c,title,header);ws.set_column(c,c,38 if field in ('customer','project','status','state') else 20)
        for r,record in enumerate(data[key],1):
            for c,(_,field) in enumerate(cols):
                value=record.get(field)
                fmt=percent if field in ('change_percent','margin') or (key=='coverage' and field=='coverage') else money if field in ('revenue','previous_revenue','change','profit','average') else normal
                if value is None:ws.write_blank(r,c,None,fmt)
                elif isinstance(value,str):ws.write_string(r,c,value,fmt)
                else:ws.write_number(r,c,value,fmt)
        if data[key]:ws.autofilter(0,0,len(data[key]),len(cols)-1)
        r=len(data[key])+3
        ws.write_string(r,0,'Dle dostupných dat. Prázdná hodnota = chybí podklad. Částky bez DPH; dostupný zisk není čistý zisk firmy.',normal)


def pdf_pages(data):
    from .reporting import table,notice,money,percent as pct,count
    d=data['management'];pages=[]
    rows=[(r['period'],money(r['revenue']),money(r['previous_revenue']),money(r['change']),pct(r['change_percent']),r['data_note']) for r in d['months']]
    body=table(('Období','Obrat','Obrat loni','Rozdíl','Změna','Podklady'),rows,(12,19,19,18,12,20),(1,2,3,4))
    pages.append(('Vývoj firmy proti předchozímu roku','Stejné měsíce obou roků. Pomlčka znamená chybějící srovnávací podklad.',body))
    rows=[(r['customer'],money(r['revenue']),money(r['previous_revenue']),money(r['change']),r['state']) for r in d['customers'][:20]]
    body=table(('Zákazník','Obrat','Obrat loni','Rozdíl','Stav'),rows,(35,16,16,16,17),(1,2,3),True)
    body+=notice('20 největších změn dle absolutního rozdílu obratu. Bez odběru znamená bez evidovaného DL ve vybraném období. První odběr platí jen v rozsahu dostupné historie. Úplný přehled je v Excelu a aplikaci.')
    pages.append(('Největší změny zákazníků','Srovnání se stejným obdobím předchozího roku dle dostupných dokladů.',body))
    rows=[(r['project'],count(r['documents']),money(r['revenue']),money(r['profit']),pct(r['margin']),r['coverage']) for r in d['projects'][:20]]
    body=table(('Zakázka','DL','Obrat','Dostupný zisk','Marže','DL se ziskem'),rows,(34,7,17,18,10,14),(1,2,3,4,5),True)
    body+=notice('20 zakázek s nejvyšším obratem. Chybějící označení je uvedeno jako Bez zakázky. Marže se nezobrazuje u neúplných podkladů.')
    pages.append(('Výsledky zakázek','Souhrn podle označení zakázky v POHODĚ.',body))
    rows=[(r['period'],count(r['delivery_documents']),count(r['missing_delivery']),count(r['profit_documents']),r['profit_source'],r['status']) for r in d['coverage']]
    body=table(('Období','DL z POHODY','Chybí DL','DL se ziskem','Zdroj zisku','Co doplnit'),rows,(12,12,10,13,20,33),(1,2,3),True)
    body+=notice('Navázání všech evidovaných dokladů nepotvrzuje, že export obsahuje celý měsíc. Výsledek vždy porovnejte s rozsahem exportu z POHODY.')
    pages.append(('Kontrola měsíčních podkladů','Podklady pro další import: DL, zisk, střediska a zákazníci.',body))
    return pages
