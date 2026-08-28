# TURTO CRM 6.0.23 - Excel exports, product image preview, subject sync, canonical palette, monitor-aware startup
import io, sys

def apply(M):
    # ------------------------------------------------------------------
    # 1) Poptávka subject: always rebuild from CURRENT supplier/action/item.
    # Fixes stale subject after changing the supplier company.
    # ------------------------------------------------------------------
    try:
        RD=M.RequestDialog
        old_changed=RD._company_text_changed
        def company_changed(self,*a):
            try:old_changed(self,*a)
            except Exception:pass
            try:self.after_idle(self.update_preview)
            except Exception:
                try:self.update_preview()
                except Exception:pass
        RD._company_text_changed=company_changed

        old_init=RD.__init__
        def request_init(self,*a,**k):
            old_init(self,*a,**k)
            if getattr(self,'is_mivo',False):return
            def sync(*_):
                try:self.after_idle(self.update_preview)
                except Exception:pass
            for name in ('company','action','item','asked'):
                try:getattr(self,name).trace_add('write',sync)
                except Exception:pass
            try:self.after_idle(self.update_preview)
            except Exception:pass
        RD.__init__=request_init
    except Exception:pass

    # ------------------------------------------------------------------
    # 2) Canonical status palette. Every Treeview uses exactly the same
    # colors for the same status, including Overview/current opportunities.
    # ------------------------------------------------------------------
    LIGHT={
        'status_active':('#b9d9ee','#103852'),'info':('#b9d9ee','#103852'),'req_fresh':('#b9d9ee','#103852'),
        'status_offer':('#a9ddd5','#164d48'),
        'status_wait':('#f4e0a8','#5c4408'),'waiting':('#f4e0a8','#5c4408'),'req_mid':('#f4e0a8','#5c4408'),
        'status_soon':('#efd0a5','#66360a'),'soon':('#efd0a5','#66360a'),'req_old':('#efd0a5','#66360a'),
        'status_late':('#efc2c2','#6c2020'),'late':('#efc2c2','#6c2020'),
        'status_done':('#b7dfbf','#1f572d'),'done':('#b7dfbf','#1f572d'),'status_won':('#b7dfbf','#1f572d'),'won':('#b7dfbf','#1f572d'),'req_received':('#b7dfbf','#1f572d'),
        'status_cancel':('#d8dde1','#485159'),'lost':('#d8dde1','#485159')
    }
    DARK={
        'status_active':('#162b3a','#e7f2f8'),'info':('#162b3a','#e7f2f8'),'req_fresh':('#162b3a','#e7f2f8'),
        'status_offer':('#163631','#e2f5f1'),
        'status_wait':('#332c18','#f5e8c5'),'waiting':('#332c18','#f5e8c5'),'req_mid':('#332c18','#f5e8c5'),
        'status_soon':('#35261b','#f7e6d6'),'soon':('#35261b','#f7e6d6'),'req_old':('#35261b','#f7e6d6'),
        'status_late':('#381f21','#f8e4e4'),'late':('#381f21','#f8e4e4'),
        'status_done':('#173222','#e4f5e8'),'done':('#173222','#e4f5e8'),'status_won':('#173222','#e4f5e8'),'won':('#173222','#e4f5e8'),'req_received':('#173222','#e4f5e8'),
        'status_cancel':('#272d31','#e6eaec'),'lost':('#272d31','#e6eaec')
    }
    def palette_for(app):
        try:
            theme=app.theme_var.get() if hasattr(app,'theme_var') else M.get_setting('theme','Světlý')
            return DARK if theme=='Tmavý' else LIGHT
        except Exception:return LIGHT
    def apply_palette(widget,palette):
        try:
            if isinstance(widget,M.ttk.Treeview):
                for tag,(bg,fg) in palette.items():
                    try:widget.tag_configure(tag,background=bg,foreground=fg)
                    except Exception:pass
            for c in widget.winfo_children():apply_palette(c,palette)
        except Exception:pass
    def recolor(app):
        apply_palette(app,palette_for(app))
    old_theme=getattr(M.App,'apply_theme',None)
    if callable(old_theme):
        def apply_theme(self,*a,**k):
            r=old_theme(self,*a,**k)
            try:self.after_idle(lambda:recolor(self))
            except Exception:recolor(self)
            return r
        M.App.apply_theme=apply_theme
    for nm in ('refresh_dash','refresh_actions','refresh_all','refresh_requests','refresh_offers'):
        old=getattr(M.App,nm,None)
        if not callable(old):continue
        def wrap(fn):
            def x(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:recolor(self))
                except Exception:pass
                return r
            return x
        setattr(M.App,nm,wrap(old))

    # ------------------------------------------------------------------
    # 3) Main window: place on monitor under the mouse, then maximize there.
    # Uses Windows WORK AREA so taskbar remains respected.
    # ------------------------------------------------------------------
    def maximize_current_monitor(app):
        if not sys.platform.startswith('win'):
            try:app.state('zoomed')
            except Exception:pass
            return
        try:
            import ctypes
            from ctypes import wintypes
            class RECT(ctypes.Structure):_fields_=[('left',ctypes.c_long),('top',ctypes.c_long),('right',ctypes.c_long),('bottom',ctypes.c_long)]
            class MI(ctypes.Structure):_fields_=[('cbSize',ctypes.c_ulong),('rcMonitor',RECT),('rcWork',RECT),('dwFlags',ctypes.c_ulong)]
            pt=wintypes.POINT();ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            mon=ctypes.windll.user32.MonitorFromPoint(pt,2);mi=MI();mi.cbSize=ctypes.sizeof(MI)
            if ctypes.windll.user32.GetMonitorInfoW(mon,ctypes.byref(mi)):
                r=mi.rcWork;w=max(600,r.right-r.left);h=max(450,r.bottom-r.top)
                app.state('normal');app.geometry(f'{w-40}x{h-40}+{r.left+20}+{r.top+20}');app.update_idletasks();app.state('zoomed')
        except Exception:
            try:app.state('zoomed')
            except Exception:pass

    # ------------------------------------------------------------------
    # 4) Excel export helpers.
    # ------------------------------------------------------------------
    def _save_xlsx(parent,default_name):
        from tkinter import filedialog
        p=filedialog.asksaveasfilename(parent=parent,title='Exportovat do Excelu',defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')],initialfile=default_name)
        return p or ''

    def export_offer_excel(app,offer_id,parent=None):
        from tkinter import messagebox
        try:
            import xlsxwriter
        except Exception as e:
            return messagebox.showerror('Excel export','Chybí knihovna XlsxWriter. Po aktualizaci aplikaci jednou restartujte.\n\n'+str(e),parent=parent or app)
        with M.db() as c:
            o=c.execute('''SELECT o.*,coalesce(s.official_name,o.supplier_name,'') supplier,c.official_name customer,a.name action_name
                FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?''',(offer_id,)).fetchone()
            items=c.execute('SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',(offer_id,)).fetchall()
        if not o:return
        safe=''.join(ch if ch.isalnum() or ch in ' _-' else '_' for ch in str(o['offer_number'] or 'nabidka')).strip() or 'nabidka'
        path=_save_xlsx(parent or app,f'Nabidka_{safe}.xlsx')
        if not path:return
        try:
            wb=xlsxwriter.Workbook(path);ws=wb.add_worksheet('Nabídka')
            title=wb.add_format({'bold':True,'font_size':16});lab=wb.add_format({'bold':True});head=wb.add_format({'bold':True,'bg_color':'#E7ECF0','border':1});num=wb.add_format({'num_format':'#,##0.00','border':1});cell=wb.add_format({'border':1});pct=wb.add_format({'num_format':'0.00%','border':1})
            ws.write('A1','Cenová nabídka',title)
            meta=[('Dodavatel',o['supplier'] or ''),('Odběratel',o['customer'] or ''),('Akce',o['action_name'] or ''),('Číslo nabídky',o['offer_number'] or ''),('Datum',M.fmt_date(o['offer_date'])),('Měna',o['currency'] or 'CZK'),('Celkem',float(o['total_value'] or 0))]
            for i,(k,v) in enumerate(meta,2):ws.write(i-1,0,k,lab);ws.write(i-1,1,v)
            headers=['Poz.','Kód','Název','item_key','Množství','MJ','Původní cena','Sleva %','Cena/ks','Celkem','Obrázek']
            row=10
            for col,h in enumerate(headers):ws.write(row,col,h,head)
            for it in items:
                row+=1;vals=[it['position'],it['product_code'] or '',it['original_name'] or '',it['item_key'] or '',float(it['quantity'] or 0),it['unit'] or '',float(it['original_unit_price'] or 0),float(it['discount_pct'] or 0)/100.0,float(it['unit_price'] or 0),float(it['total_price'] or 0)]
                for col,v in enumerate(vals):ws.write(row,col,v,pct if col==7 else (num if col in (4,6,8,9) else cell))
                blob=it['image_blob'] if 'image_blob' in it.keys() else None
                if not blob:
                    with M.db() as c:
                        im=c.execute('SELECT image_blob FROM offer_product_images WHERE supplier=? AND item_key=?',(o['supplier'] or '',it['item_key'] or '')).fetchone()
                        blob=im['image_blob'] if im and im['image_blob'] else None
                if blob:
                    try:
                        bio=io.BytesIO(bytes(blob));ws.set_row(row,72);ws.insert_image(row,10,'image.png',{'image_data':bio,'x_scale':0.35,'y_scale':0.35,'object_position':1})
                    except Exception:pass
            ws.set_column('A:A',7);ws.set_column('B:B',16);ws.set_column('C:C',42);ws.set_column('D:D',30);ws.set_column('E:E',12);ws.set_column('F:F',8);ws.set_column('G:J',14);ws.set_column('K:K',18);ws.freeze_panes(11,0);ws.autofilter(10,0,row,9)
            wb.close();messagebox.showinfo('Excel export',f'Export dokončen:\n{path}',parent=parent or app)
        except Exception as e:
            try:wb.close()
            except Exception:pass
            messagebox.showerror('Excel export',str(e),parent=parent or app)
    M.export_offer_excel=export_offer_excel

    # Selected offer export from main Offers list.
    def export_selected_offer(self):
        oid=self._selected_offer_id() if hasattr(self,'_selected_offer_id') else None
        if not oid:return M.messagebox.showinfo('Excel export','Vyberte nabídku.',parent=self)
        export_offer_excel(self,oid,self)
    M.App.export_selected_offer_excel=export_selected_offer

    # Product/price browser: inline selected-product image + export current view/history.
    try:
        B=M.ProductPriceBrowser
        old_binit=B.__init__
        def binit(self,*a,**k):
            old_binit(self,*a,**k)
            box=M.ttk.Frame(self,padding=(10,8));box.pack(fill='x')
            left=M.ttk.Frame(box);left.pack(side='left',fill='x',expand=True)
            self._price_img_title=M.ttk.Label(left,text='Vyberte produkt',style='Section.TLabel');self._price_img_title.pack(anchor='w')
            self._price_img_meta=M.ttk.Label(left,text='',style='PageSubtitle.TLabel');self._price_img_meta.pack(anchor='w')
            image_box=M.ttk.Frame(box,width=230,height=150)
            image_box.pack(side='right',padx=(12,0))
            image_box.pack_propagate(False)
            self._price_img=M.ttk.Label(image_box,text='',anchor='center')
            self._price_img.pack(fill='both',expand=True)
            M.ttk.Button(left,text='Exportovat zobrazené do Excelu',style='Accent.TButton',command=self.export_excel).pack(anchor='w',pady=(8,0))
            self.t.bind('<<TreeviewSelect>>',lambda e:self.show_image(),add='+')
        def show_image(self):
            try:
                s=self.t.selection()
                if not s:return
                r=self.rows.get(s[0])
                if not r:return
                self._price_img_title.configure(text=r.get('original_name') or r.get('item_key') or 'Produkt')
                self._price_img_meta.configure(text=f"{r.get('supplier') or ''}   •   kód {r.get('product_code') or '—'}")
                with M.db() as c:
                    im=c.execute('SELECT image_blob FROM offer_product_images WHERE supplier=? AND item_key=?',(r.get('supplier') or '',r.get('item_key') or r.get('original_name') or '')).fetchone()
                    if not im or not im['image_blob']:
                        im=c.execute('SELECT image_blob FROM supplier_offer_items WHERE id=?',(r.get('id'),)).fetchone()
                if not im or not im['image_blob']:
                    self._price_img.configure(image='',text='Bez obrázku');self._price_img.image=None;return
                from PIL import Image,ImageTk
                source=Image.open(io.BytesIO(bytes(im['image_blob']))).convert('RGBA')
                source.thumbnail((214,134),Image.Resampling.LANCZOS)
                canvas=Image.new('RGBA',(230,150),(0,0,0,0))
                canvas.alpha_composite(source,((230-source.width)//2,(150-source.height)//2))
                ph=ImageTk.PhotoImage(canvas);self._price_img.configure(image=ph,text='');self._price_img.image=ph
            except Exception:
                try:self._price_img.configure(image='',text='Obrázek nelze zobrazit')
                except Exception:pass
        def export_excel(self):
            from tkinter import messagebox
            try:import xlsxwriter
            except Exception as e:return messagebox.showerror('Excel export',str(e),parent=self)
            path=_save_xlsx(self,'Produkty_ceny.xlsx')
            if not path:return
            try:
                wb=xlsxwriter.Workbook(path);ws=wb.add_worksheet('Produkty a ceny');head=wb.add_format({'bold':True,'bg_color':'#E7ECF0','border':1});cell=wb.add_format({'border':1})
                cols=list(self.t['columns'])
                for j,c in enumerate(cols):ws.write(0,j,c,head)
                rr=1
                for iid in self.t.get_children(''):
                    vals=self.t.item(iid,'values')
                    for j,v in enumerate(vals):ws.write(rr,j,v,cell)
                    rr+=1
                for j in range(len(cols)):ws.set_column(j,j,18 if j!=2 else 38)
                ws.freeze_panes(1,0);ws.autofilter(0,0,max(0,rr-1),max(0,len(cols)-1))
                # second sheet: complete price history for products currently visible
                hist=wb.add_worksheet('Historie cen');hcols=['Dodavatel','Kód','Produkt','item_key','Datum','Číslo nabídky','Množství','MJ','Původní cena','Sleva %','Cena/ks','Celkem','Akce']
                for j,c in enumerate(hcols):hist.write(0,j,c,head)
                visible=[]
                for iid in self.t.get_children(''):
                    r=self.rows.get(iid)
                    if r:visible.append((r.get('supplier') or '',r.get('item_key') or r.get('original_name') or ''))
                hr=1
                with M.db() as c:
                    for supplier,key in visible:
                        rows=c.execute('''SELECT coalesce(s.official_name,o.supplier_name,'') supplier,i.product_code,i.original_name,i.item_key,o.offer_date,o.offer_number,i.quantity,i.unit,i.original_unit_price,i.discount_pct,i.unit_price,i.total_price,a.name action_name FROM supplier_offer_items i JOIN supplier_offers o ON o.id=i.offer_id LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE i.item_key=? AND (coalesce(s.official_name,o.supplier_name,'')=?) ORDER BY o.offer_date DESC,o.id DESC,i.id DESC''',(key,supplier)).fetchall()
                        for r in rows:
                            vals=[r['supplier'],r['product_code'] or '',r['original_name'] or '',r['item_key'] or '',M.fmt_date(r['offer_date']),r['offer_number'] or '',r['quantity'],r['unit'] or '',r['original_unit_price'],r['discount_pct'],r['unit_price'],r['total_price'],r['action_name'] or '']
                            for j,v in enumerate(vals):hist.write(hr,j,v,cell)
                            hr+=1
                hist.set_column(0,0,20);hist.set_column(1,1,16);hist.set_column(2,3,35);hist.set_column(4,12,16);hist.freeze_panes(1,0)
                wb.close();messagebox.showinfo('Excel export',f'Export dokončen:\n{path}',parent=self)
            except Exception as e:
                try:wb.close()
                except Exception:pass
                messagebox.showerror('Excel export',str(e),parent=self)
        B.__init__=binit;B.show_image=show_image;B.export_excel=export_excel
    except Exception:pass

    # Offer detail: direct Excel export button.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_db=D._build
        def dbuild(self):
            old_db(self)
            try:
                bar=M.ttk.Frame(self.f);bar.pack(fill='x',pady=(6,0));M.ttk.Button(bar,text='Exportovat do Excelu',style='Accent.TButton',command=lambda:export_offer_excel(self.parent_app,self.oid,self)).pack(side='left')
            except Exception:pass
        D._build=dbuild
    except Exception:pass

    # Main Offers page: export selected offer button.
    old_offers=M.App.build_offers
    def build_offers(self):
        old_offers(self)
        try:
            p=self.tabs['offers'];bar=M.ttk.Frame(p,style='Panel.TFrame',padding=(10,6));bar.pack(fill='x',before=p.winfo_children()[0] if p.winfo_children() else None,pady=(0,4))
            M.ttk.Button(bar,text='Export vybrané nabídky do Excelu',style='Toolbar.TButton',command=self.export_selected_offer_excel).pack(side='right')
        except Exception:pass
    M.App.build_offers=build_offers

    # App init last: canonical palette + monitor-aware maximization.
    old_app_init=M.App.__init__
    def app_init(self,*a,**k):
        old_app_init(self,*a,**k)
        try:self.after(80,lambda:maximize_current_monitor(self))
        except Exception:pass
        try:self.after_idle(lambda:recolor(self))
        except Exception:pass
    M.App.__init__=app_init

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
                        w.configure(state='normal');w.insert('end','\n\nNABÍDKY / EXCEL 6.0.23\nVybranou nabídku lze exportovat do XLSX včetně položek a dostupných obrázků. Přehled Produkty / ceny má vlastní export aktuálního filtru a druhý list s historií cen. Vybraný produkt zároveň zobrazuje dostupný obrázek v pevném náhledovém poli, takže různé poměry stran nemění výšku panelu. Předmět Poptávky se po změně dodavatele, Akce, položky nebo data vždy znovu sestaví z aktuálních hodnot. Stavové barvy jsou centrálně sjednocené pro Přehled i Příležitosti. Hlavní okno se při startu umístí na monitor pod kurzorem a až potom maximalizuje.')
                        w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
