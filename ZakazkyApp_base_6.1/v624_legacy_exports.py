# TURTO CRM 6.0.24 - supplier-specific Excel export compatible with TURTO_Nabidky_V4_7_24
import io, math

def apply(M):
    def _has(row,key):
        try:return key in row.keys()
        except Exception:return False
    def _v(row,*keys,default=''):
        for k in keys:
            try:
                if k in row.keys() and row[k] not in (None,''):return row[k]
            except Exception:pass
        return default
    def _num(v):
        try:return float(v or 0)
        except Exception:return 0.0
    def _safe_no(v):
        s=str(v or 'nabidka').strip()
        return ''.join(ch if ch.isalnum() or ch in '-_.' else '_' for ch in s).strip('._') or 'nabidka'
    def _save_path(parent,offer_no):
        from tkinter import filedialog
        return filedialog.asksaveasfilename(parent=parent,title='Extrakce dat nabídky',defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')],initialfile=f'Extrakce dat CN {_safe_no(offer_no)}.xlsx') or ''

    def _load(offer_id):
        with M.db() as c:
            o=c.execute('''SELECT o.*,coalesce(s.official_name,o.supplier_name,'') supplier,
                coalesce(cu.official_name,'') customer,coalesce(a.name,'') action_name
                FROM supplier_offers o
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN companies cu ON cu.id=o.customer_company_id
                LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?''',(offer_id,)).fetchone()
            items=c.execute('SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',(offer_id,)).fetchall()
        return o,items

    def _item_image(M,o,it):
        blob=_v(it,'image_blob',default=None)
        ext=_v(it,'image_ext',default='png') or 'png'
        if blob:return blob,ext
        try:
            with M.db() as c:
                r=c.execute('SELECT image_blob,image_ext FROM offer_product_images WHERE supplier=? AND item_key=?',(_v(o,'supplier'),_v(it,'item_key','original_name'))).fetchone()
            if r and r['image_blob']:return r['image_blob'],r['image_ext'] or 'png'
        except Exception:pass
        return None,'png'

    def _export_leviat(wb,ws,o,items):
        title=wb.add_format({'font_name':'Calibri','bold':True,'font_size':16,'font_color':'#1F4E78'})
        label=wb.add_format({'font_name':'Calibri','bold':True,'bg_color':'#D9EAF7','border':1})
        value=wb.add_format({'font_name':'Calibri','border':1})
        money=wb.add_format({'font_name':'Calibri','num_format':'#,##0.00 "Kč"','border':1})
        pct=wb.add_format({'font_name':'Calibri','num_format':'0.00" %"','border':1})
        head=wb.add_format({'font_name':'Calibri','bold':True,'font_color':'white','bg_color':'#1F4E78','border':1,'align':'center','valign':'vcenter','text_wrap':True})
        text=wb.add_format({'font_name':'Calibri','border':1,'valign':'top','text_wrap':True})
        integer=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0','valign':'top'})
        item_money=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'top'})

        offer_no=_v(o,'offer_number')
        net=_num(_v(o,'net_value','total_value'))
        gross=_num(_v(o,'gross_value')) or sum(_num(_v(i,'original_unit_price','unit_price'))*_num(_v(i,'quantity')) for i in items)
        if not net:net=sum(_num(_v(i,'total_price')) for i in items)
        disc_value=max(0,gross-net)
        disc_pct=_num(_v(o,'discount_pct'))
        if not disc_pct and gross:disc_pct=100*disc_value/gross
        vat=round(net*0.21,2);total=round(net+vat,2)
        reference=_v(o,'action_name','note') or 'Nepřiřazeno'
        ws.write('A1',f'Cenová nabídka {offer_no}',title)
        summary=[('Číslo nabídky',offer_no,value),('Datum',M.fmt_date(_v(o,'offer_date')),value),('Reference / zakázka',reference,value),('Součet položek před slevou',gross,money),('Sleva %',disc_pct,pct),('Sleva Kč',disc_value,money),('Celkem bez DPH',net,money),('DPH',vat,money),('Celková částka s DPH',total,money)]
        for r,(lab,val,fmt) in enumerate(summary,start=2):
            ws.write(r-1,0,lab,label);ws.write(r-1,1,val,fmt)
        start=13
        ws.write(start-1,0,'Pol.',head);ws.write(start-1,1,'Číslo výrobku',head);ws.merge_range(start-1,2,start-1,7,'Název položky',head);ws.write(start-1,8,'Množství [KS]',head);ws.write(start-1,9,'Cena za kus bez DPH',head);ws.write(start-1,10,'Cena položky bez DPH',head)
        for r,it in enumerate(items,start=start):
            pos=_num(_v(it,'position'));prod=_v(it,'product_code');desc=_v(it,'original_name','item_key');qty=_num(_v(it,'quantity'));up=_num(_v(it,'unit_price'));tot=_num(_v(it,'total_price')) or qty*up
            ws.write_number(r,0,pos,integer);ws.write(r,1,prod,text);ws.merge_range(r,2,r,7,desc,text);ws.write_number(r,8,qty,integer);ws.write_number(r,9,up,item_money);ws.write_number(r,10,tot,item_money)
        last=start+len(items)-1
        if items:ws.autofilter(start-1,0,last,10)
        ws.freeze_panes(start,0);ws.set_column('A:A',9);ws.set_column('B:B',17);ws.set_column('C:H',10);ws.set_column('I:I',15);ws.set_column('J:K',22);ws.set_row(start-1,32);ws.set_landscape();ws.fit_to_pages(1,0)

    def _estimate_height(text):
        lines=max(1,len(str(text or '').splitlines()))
        chars=max(1,len(str(text or '')))
        return min(180,max(54,15*lines+12*math.ceil(chars/56)))

    def _export_gerotop(wb,ws,o,items):
        title=wb.add_format({'font_name':'Calibri','bold':True,'font_size':16,'font_color':'#1F4E78'})
        label=wb.add_format({'font_name':'Calibri','bold':True,'bg_color':'#D9EAF7','border':1})
        value=wb.add_format({'font_name':'Calibri','border':1})
        money=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"'})
        head=wb.add_format({'font_name':'Calibri','bold':True,'font_color':'white','bg_color':'#1F4E78','border':1,'align':'center','valign':'vcenter','text_wrap':True})
        text=wb.add_format({'font_name':'Calibri','border':1,'valign':'vcenter','align':'left','text_wrap':True})
        integer=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0','valign':'vcenter','align':'center'})
        item_money=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'vcenter','align':'center'})
        key_money=wb.add_format({'font_name':'Calibri','border':1,'num_format':'#,##0.00 "Kč"','valign':'vcenter','align':'center','bold':True})
        pct=wb.add_format({'font_name':'Calibri','border':1,'num_format':'0.##" %"','valign':'vcenter','align':'center'})

        offer_no=_v(o,'offer_number');reference=_v(o,'action_name','note') or 'Nepřiřazeno'
        # V4.7.24 summary deliberately reports products only. Exclude obvious freight/transport rows.
        product_net=0.0
        for it in items:
            name=(str(_v(it,'original_name'))+' '+str(_v(it,'product_code'))).casefold()
            if any(x in name for x in ('doprava','dopravné','balné','preprava','přeprava')):continue
            product_net+=_num(_v(it,'total_price'))
        if not product_net:product_net=_num(_v(o,'net_value','total_value'))
        ws.write('A1',f'Cenová nabídka {offer_no}',title)
        summary=[('Dodavatel',_v(o,'supplier',default='GEROtop')),('Číslo nabídky',offer_no),('Datum',M.fmt_date(_v(o,'offer_date'))),('Zakázka',reference),('Celkem bez DPH – pouze výrobky',product_net)]
        for r,(lab,val) in enumerate(summary,start=2):
            ws.write(r-1,0,lab,label)
            if isinstance(val,(int,float)):ws.write_number(r-1,1,val,money)
            else:ws.write(r-1,1,val,value)
        start=9
        ws.write(start-1,0,'Kód',head);ws.merge_range(start-1,1,start-1,4,'Název / technický popis',head);ws.merge_range(start-1,5,start-1,6,'Obrázek',head);ws.write(start-1,7,'Počet [KS]',head);ws.write(start-1,8,'Cena/ks po slevě',head);ws.write(start-1,9,'Sleva',head);ws.write(start-1,10,'Původní cena/ks',head);ws.write(start-1,11,'Cena celkem',head)
        for row,it in enumerate(items,start=start):
            code=_v(it,'product_code');desc=_v(it,'original_name','item_key');qty=_num(_v(it,'quantity'));unit=_num(_v(it,'unit_price'));disc=_num(_v(it,'discount_pct'));orig=_num(_v(it,'original_unit_price')) or unit;tot=_num(_v(it,'total_price')) or qty*unit
            ws.write(row,0,code,text);ws.merge_range(row,1,row,4,desc,text);ws.merge_range(row,5,row,6,'',text);ws.write_number(row,7,qty,integer);ws.write_number(row,8,unit,key_money);ws.write_number(row,9,disc,pct);ws.write_number(row,10,orig,item_money);ws.write_number(row,11,tot,item_money)
            rh=_estimate_height(desc);ws.set_row(row,rh)
            blob,ext=_item_image(M,o,it)
            if blob:
                try:
                    bio=io.BytesIO(bytes(blob))
                    try:ws.embed_image(row,5,'produkt.'+str(ext),{'image_data':bio})
                    except Exception:ws.insert_image(row,5,'produkt.'+str(ext),{'image_data':bio,'object_position':1,'x_scale':0.45,'y_scale':0.45})
                except Exception:pass
        ws.set_column('A:A',16);ws.set_column('B:E',11);ws.set_column('F:G',18);ws.set_column('H:H',12);ws.set_column('I:I',20);ws.set_column('J:J',11);ws.set_column('K:L',19);ws.freeze_panes(start,0);ws.set_landscape();ws.fit_to_pages(1,0)

    def export_legacy(app,offer_id,parent=None):
        from tkinter import messagebox
        try:import xlsxwriter
        except Exception as e:return messagebox.showerror('Extrakce dat',f'Chybí XlsxWriter.\n\n{e}',parent=parent or app)
        o,items=_load(offer_id)
        if not o:return
        path=_save_path(parent or app,_v(o,'offer_number'))
        if not path:return
        wb=None
        try:
            wb=xlsxwriter.Workbook(path);ws=wb.add_worksheet('Nabídka')
            supplier=str(_v(o,'supplier')).casefold()
            if 'gerotop' in supplier:_export_gerotop(wb,ws,o,items)
            elif 'leviat' in supplier:_export_leviat(wb,ws,o,items)
            else:
                # Unknown future supplier: keep export usable, but do not pretend it matches a known supplier template.
                _export_leviat(wb,ws,o,items)
            wb.close();messagebox.showinfo('Extrakce dat',f'Extrakce vytvořena:\n{path}',parent=parent or app)
        except Exception as e:
            try:
                if wb:wb.close()
            except Exception:pass
            messagebox.showerror('Extrakce dat',str(e),parent=parent or app)
    M.export_offer_excel=export_legacy

    def selected(self):
        oid=self._selected_offer_id() if hasattr(self,'_selected_offer_id') else None
        if not oid:return M.messagebox.showinfo('Extrakce dat','Vyberte nabídku.',parent=self)
        return export_legacy(self,oid,self)
    M.App.export_selected_offer_excel=selected

    # v6.0.23 detail button captured the old exporter in a closure. Rewire that button after each detail rebuild.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old=D._build
        def build(self):
            r=old(self)
            try:
                def walk(w):
                    for c in w.winfo_children():
                        try:
                            if c.winfo_class().endswith('Button') and str(c.cget('text')).strip()=='Exportovat do Excelu':
                                c.configure(text='Extrakce dat do Excelu',command=lambda:export_legacy(self.parent_app,self.oid,self))
                        except Exception:pass
                        walk(c)
                walk(self.f)
            except Exception:pass
            return r
        D._build=build
    except Exception:pass

    # Rename the main Offers export button wording to match the legacy program terminology.
    old_build=M.App.build_offers
    def build_offers(self):
        r=old_build(self)
        try:
            p=self.tabs['offers']
            def walk(w):
                for c in w.winfo_children():
                    try:
                        if c.winfo_class().endswith('Button') and 'Export vybrané nabídky' in str(c.cget('text')):
                            c.configure(text='Extrakce dat vybrané nabídky')
                    except Exception:pass
                    walk(c)
            walk(p)
        except Exception:pass
        return r
    M.App.build_offers=build_offers

    # Help note.
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                p=self.tabs['help']
                def walk(w):
                    if isinstance(w,tk.Text):
                        w.configure(state='normal');w.insert('end','\n\nEXTRAKCE DAT NABÍDEK 6.0.24\nExport jednotlivé nabídky používá dodavatelské šablony podle původního TURTO_Nabidky_V4_7_24. Název souboru je „Extrakce dat CN <číslo nabídky>.xlsx“. GEROtop export zachovává technický blok, obrázky, množství, cenu po slevě, slevu, původní cenu a celkovou cenu; souhrn „Celkem bez DPH – pouze výrobky“ odděluje dopravu. Leviat export zachovává rekapitulaci nabídky a tabulku Pol. / Číslo výrobku / Název položky / Množství / Cena za kus / Cena položky. Každý další dodavatel může mít vlastní exportní šablonu.')
                        w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
