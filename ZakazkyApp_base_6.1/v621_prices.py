# TURTO CRM 6.0.21 - product price browser, document archive, request linking, safer delete
import os, re, shutil, datetime
from pathlib import Path

def apply(M):
    # --- schema ---
    try:
        with M.db() as c:
            if not M.has_column(c,'supplier_offers','request_id'):
                c.execute('ALTER TABLE supplier_offers ADD COLUMN request_id INTEGER')
            if not M.has_column(c,'offer_source_messages','archive_path'):
                c.execute('ALTER TABLE offer_source_messages ADD COLUMN archive_path TEXT DEFAULT ""')
            if not M.has_column(c,'offer_source_attachments','archive_path'):
                c.execute('ALTER TABLE offer_source_attachments ADD COLUMN archive_path TEXT DEFAULT ""')
            c.execute('CREATE INDEX IF NOT EXISTS idx_offer_items_price_browser ON supplier_offer_items(item_key,offer_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_supplier_offers_request ON supplier_offers(request_id)')
    except Exception:
        pass

    def _safe(s,fallback='soubor'):
        s=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(s or '')).strip(' ._')
        return (s[:120] or fallback)

    def _archive_root():
        root=M.stable_root()/ 'Dokumenty' / 'Nabidky'
        root.mkdir(parents=True,exist_ok=True)
        return root

    def _offer_folder(supplier='',offer_no='',when=None):
        d=(when or datetime.date.today()).strftime('%Y-%m-%d')
        p=_archive_root()/f"{d}_{_safe(supplier,'Neurceny')}_{_safe(offer_no,'nabidka')}"
        p.mkdir(parents=True,exist_ok=True)
        return p

    def _archive_msg_after_parse(path,result):
        try:
            mid=(result or {}).get('message_id')
            offers=(result or {}).get('offers') or []
            supplier=(offers[0].get('supplier') if offers else '') or 'Neurceny'
            number=(offers[0].get('number') if offers else '') or 'email'
            folder=_offer_folder(supplier,number)
            src=Path(path);dst=folder/_safe(src.stem,'email')+'.msg'
        except TypeError:
            dst=folder/(_safe(src.stem,'email')+'.msg')
        try:
            shutil.copy2(path,dst)
        except Exception:
            dst=None
        if not mid:return
        try:
            with M.db() as c:
                rows=c.execute('SELECT id,filename,content_blob FROM offer_source_attachments WHERE message_id=?',(mid,)).fetchall()
                for r in rows:
                    ap=''
                    if r['content_blob']:
                        apath=folder/_safe(r['filename'] or f"priloha_{r['id']}")
                        apath.write_bytes(bytes(r['content_blob']));ap=str(apath)
                    c.execute('UPDATE offer_source_attachments SET archive_path=?,content_blob=NULL WHERE id=?',(ap,r['id']))
                cols=[x[1] for x in c.execute('PRAGMA table_info(offer_source_messages)')]
                if 'source_blob' in cols:
                    c.execute('UPDATE offer_source_messages SET archive_path=?,source_blob=NULL WHERE id=?',(str(dst) if dst else '',mid))
                else:c.execute('UPDATE offer_source_messages SET archive_path=? WHERE id=?',(str(dst) if dst else '',mid))
        except Exception:pass

    # Stop storing whole MSG/attachments in the DB after processing; archive to Documents instead.
    old_msg=getattr(M,'process_offer_msg',None)
    if old_msg:
        def process_msg(app,path):
            r=old_msg(app,path)
            _archive_msg_after_parse(path,r)
            return r
        M.process_offer_msg=process_msg

    old_pdf=getattr(M,'process_offer_pdf',None)
    if old_pdf:
        def process_pdf(app,path,*a,**k):
            r=old_pdf(app,path,*a,**k)
            try:
                folder=_offer_folder(r.get('supplier',''),r.get('number',''))
                src=Path(path)
                if src.exists():
                    dst=folder/(_safe(src.stem,'nabidka')+src.suffix.lower());shutil.copy2(src,dst)
                    if r.get('offer_id'):
                        with M.db() as c:c.execute('UPDATE supplier_offers SET source_pdf=? WHERE id=?',(str(dst),r['offer_id']))
            except Exception:pass
            return r
        M.process_offer_pdf=process_pdf

    # Clean legacy source BLOBs once; product images remain untouched.
    try:
        with M.db() as c:
            cols=[x[1] for x in c.execute('PRAGMA table_info(offer_source_messages)')]
            if 'source_blob' in cols:c.execute('UPDATE offer_source_messages SET source_blob=NULL WHERE source_blob IS NOT NULL')
            c.execute('UPDATE offer_source_attachments SET content_blob=NULL WHERE content_blob IS NOT NULL AND trim(coalesce(archive_path,""))<>""')
    except Exception:pass

    # --- Product / price browser ---
    class ProductPriceBrowser(M.tk.Toplevel):
        def __init__(self,parent):
            super().__init__(parent);self.title('Produkty / ceny');M.enable_dialog_maximize(self,1320,820);self.transient(parent)
            f=M.ttk.Frame(self,padding=14);f.pack(fill='both',expand=True)
            top=M.ttk.Frame(f);top.pack(fill='x',pady=(0,8))
            M.ttk.Label(top,text='Produkty / ceny',style='PageTitle.TLabel').pack(side='left')
            self.q=M.tk.StringVar();e=M.ttk.Entry(top,textvariable=self.q,width=38);e.pack(side='right');M.ttk.Label(top,text='Hledat:').pack(side='right',padx=(0,6));e.bind('<KeyRelease>',lambda _:self.load())
            cols=('Dodavatel','Kód','Produkt','Poslední cena','Sleva','Datum','Předchozí cena','Změna %','Akce','Poptávka')
            self.t=M.ttk.Treeview(f,columns=cols,show='headings')
            for c,w in zip(cols,(150,110,330,110,75,95,115,80,210,210)):
                self.t.heading(c,text=c);self.t.column(c,width=w,anchor='w')
            self.t.pack(fill='both',expand=True)
            M.bind_row_double_click(self.t,lambda e:self.history())
            b=M.ttk.Frame(f);b.pack(fill='x',pady=(8,0));M.ttk.Button(b,text='Historie ceny',style='Accent.TButton',command=self.history).pack(side='right');M.ttk.Button(b,text='Zavřít',command=self.destroy).pack(side='right',padx=6)
            self.rows={};self.load()
        def load(self):
            for x in self.t.get_children():self.t.delete(x)
            self.rows={};q=(self.q.get() or '').strip().casefold()
            with M.db() as c:
                has_req=M.has_column(c,'supplier_offers','request_id')
                req_join='LEFT JOIN requests r ON r.id=o.request_id' if has_req else ''
                req_sel=',r.item request_item' if has_req else ",'' request_item"
                rows=c.execute(f'''SELECT i.id,i.item_key,i.product_code,i.original_name,i.unit_price,i.discount_pct,o.offer_date,
                    coalesce(s.official_name,o.supplier_name,'') supplier,a.name action_name {req_sel}
                    FROM supplier_offer_items i JOIN supplier_offers o ON o.id=i.offer_id
                    LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN actions a ON a.id=o.action_id {req_join}
                    ORDER BY supplier COLLATE CZECH,i.item_key COLLATE CZECH,o.offer_date DESC,o.id DESC,i.id DESC''').fetchall()
            groups={}
            for r in rows:
                key=((r['supplier'] or '').casefold(),r['item_key'] or r['original_name'] or '')
                groups.setdefault(key,[]).append(r)
            n=0
            for key,arr in groups.items():
                r=arr[0];prev=arr[1] if len(arr)>1 else None
                hay=' '.join(str(r[x] or '') for x in ('supplier','product_code','original_name','item_key')).casefold()
                if q and q not in hay:continue
                last=float(r['unit_price'] or 0);pv=float(prev['unit_price'] or 0) if prev else 0;chg=((last/pv-1)*100) if last and pv else None
                iid=f'p{n}';n+=1;self.rows[iid]=dict(r)
                self.t.insert('', 'end', iid=iid, values=(r['supplier'],r['product_code'] or '',r['original_name'] or r['item_key'],f'{last:,.2f}',f"{float(r['discount_pct'] or 0):.2f} %",M.fmt_date(r['offer_date']),f'{pv:,.2f}' if pv else '',f'{chg:+.1f} %' if chg is not None else '',r['action_name'] or '',r['request_item'] or ''))
        def history(self):
            s=self.t.selection()
            if not s:return
            r=self.rows[s[0]]
            try:
                import crm_features as F
                d=F.OfferPriceHistoryDialog(self,r['supplier'],r['item_key'] or r['original_name'],r['original_name'] or r['item_key']);self.wait_window(d)
            except Exception as e:M.messagebox.showerror('Produkty / ceny',str(e),parent=self)
    M.ProductPriceBrowser=ProductPriceBrowser
    M.App.open_product_prices=lambda self:ProductPriceBrowser(self)

    # --- Optional request link for an offer ---
    def assign_offer_to_request(app,offer_id,parent=None):
        from tkinter import messagebox
        with M.db() as c:
            cols=[x[1] for x in c.execute('PRAGMA table_info(requests)')]
            if 'id' not in cols:return
            select=['id']+[x for x in ('item','asked_date','action_id','company_id','archived') if x in cols]
            sql='SELECT '+','.join(select)+' FROM requests'
            where=[]
            if 'archived' in cols:where.append('coalesce(archived,0)=0')
            if where:sql+=' WHERE '+' AND '.join(where)
            sql+=' ORDER BY id DESC LIMIT 500'
            rows=c.execute(sql).fetchall()
        if not rows:return
        d=M.tk.Toplevel(parent or app);d.title('Přiřadit nabídku k Poptávce');M.enable_dialog_maximize(d,980,650);d.transient(parent or app);d.grab_set();chosen={'id':None}
        f=M.ttk.Frame(d,padding=14);f.pack(fill='both',expand=True);M.ttk.Label(f,text='Přiřadit k Poptávce (nepovinné)',style='Section.TLabel').pack(anchor='w')
        t=M.ttk.Treeview(f,columns=('ID','Poptáváno','Datum','Akce'),show='headings');[t.heading(c,text=c) for c in ('ID','Poptáváno','Datum','Akce')];t.pack(fill='both',expand=True,pady=8)
        with M.db() as c:
            for r in rows:
                an=''
                if 'action_id' in r.keys() and r['action_id']:
                    a=c.execute('SELECT name FROM actions WHERE id=?',(r['action_id'],)).fetchone();an=a['name'] if a else ''
                t.insert('', 'end', iid=str(r['id']), values=(r['id'],r['item'] if 'item' in r.keys() else '',M.fmt_date(r['asked_date']) if 'asked_date' in r.keys() else '',an))
        def save():
            s=t.selection()
            if not s:return
            rid=int(s[0])
            with M.db() as c:
                rr=c.execute('SELECT * FROM requests WHERE id=?',(rid,)).fetchone();aid=rr['action_id'] if rr and 'action_id' in rr.keys() else None
                c.execute('UPDATE supplier_offers SET request_id=?,action_id=coalesce(?,action_id) WHERE id=?',(rid,aid,offer_id))
            d.destroy();
            try:app.refresh_offers()
            except Exception:pass
        b=M.ttk.Frame(f);b.pack(fill='x');M.ttk.Button(b,text='Bez přiřazení',command=d.destroy).pack(side='right');M.ttk.Button(b,text='Přiřadit',style='Accent.TButton',command=save).pack(side='right',padx=6)
        t.bind('<Double-1>',lambda e:save());d.wait_window()
    M.assign_offer_to_request=assign_offer_to_request

    # Add price browser + request-link button to Offers UI; hide/remove PDF-open controls.
    old_build=M.App.build_offers
    def build_offers(self):
        old_build(self)
        try:
            p=self.tabs['offers'];bar=M.ttk.Frame(p,style='Panel.TFrame',padding=(10,7));bar.pack(fill='x',before=p.winfo_children()[0] if p.winfo_children() else None,pady=(0,5))
            M.ttk.Button(bar,text='💰 Produkty / ceny',style='Accent.TButton',command=self.open_product_prices).pack(side='left')
            M.ttk.Label(bar,text='Přehled posledních a předchozích cen bez rozklikávání jednotlivých nabídek.',style='PageSubtitle.TLabel').pack(side='left',padx=10)
            # Remove buttons whose visible text explicitly opens PDF.
            def walk(w):
                for c in list(w.winfo_children()):
                    try:
                        if c.winfo_class().endswith('Button') and 'PDF' in str(c.cget('text')).upper():c.destroy();continue
                    except Exception:pass
                    walk(c)
            walk(p)
        except Exception:pass
    M.App.build_offers=build_offers

    # Offer detail: replace action-only linking with request-aware linking and suppress original PDF button.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_detail_build=D._build
        def detail_build(self):
            old_detail_build(self)
            try:
                for w in self.f.winfo_children():
                    for c in list(w.winfo_children()):
                        try:
                            if c.winfo_class().endswith('Button') and 'PDF' in str(c.cget('text')).upper():c.destroy()
                        except Exception:pass
                tools=M.ttk.Frame(self.f,style='Panel.TFrame');tools.pack(fill='x',pady=(6,0))
                M.ttk.Button(tools,text='Přiřadit k Poptávce…',style='Toolbar.TButton',command=lambda:assign_offer_to_request(self.parent_app,self.oid,self)).pack(side='left')
            except Exception:pass
        D._build=detail_build
    except Exception:pass

    # Safer delete of wrongly-created opportunities: never hang on FK/linked records.
    def delete_action(self):
        s=self.action_tree.selection()
        if not s:return
        aid=int(str(s[0]).lstrip('aA'))
        with M.db() as c:
            row=c.execute('SELECT name FROM actions WHERE id=?',(aid,)).fetchone()
            if not row:return
            deps=[]
            for table,label in (('requests','Poptávky'),('tasks','Úkoly'),('supplier_offers','Nabídky')):
                try:
                    cols=[x[1] for x in c.execute(f'PRAGMA table_info({table})')]
                    if 'action_id' in cols:
                        n=c.execute(f'SELECT count(*) n FROM {table} WHERE action_id=?',(aid,)).fetchone()['n']
                        if n:deps.append(f'{label}: {n}')
                except Exception:pass
        if deps:
            return M.messagebox.showwarning('Smazat Příležitost','Příležitost nelze smazat, protože má vazby:\n'+'\n'.join(deps)+'\n\nNejprve vazby odpojte nebo záznam zrušte.',parent=self)
        if not M.messagebox.askyesno('Smazat Příležitost',f"Opravdu smazat „{row['name']}“?",parent=self):return
        try:
            with M.db() as c:
                c.execute('BEGIN IMMEDIATE');c.execute('DELETE FROM actions WHERE id=?',(aid,));c.commit()
            try:self.refresh_actions();self.refresh_dash()
            except Exception:pass
        except Exception as e:M.messagebox.showerror('Smazat Příležitost',f'Smazání se nepodařilo:\n{e}',parent=self)
    M.App.delete_action=delete_action

    # Help note.
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                def walk(w):
                    if isinstance(w,tk.Text):
                        w.configure(state='normal');w.insert('end','\n\nNABÍDKY 6.0.21 – PRODUKTY / CENY\nV Nabídkách je samostatný přehled Produkty / ceny s poslední a předchozí cenou, změnou, dodavatelem, Akcí a Poptávkou. Zdrojové MSG/PDF a přílohy se neuchovávají jako velké BLOB objekty v databázi; při zpracování se kopírují do Dokumenty/TURTO Zakazky/Dokumenty/Nabidky. Nabídku lze nepovinně přiřadit k Poptávce a tím se převezme i vazba na Akci. Otevírání původního PDF z CRM bylo odstraněno.');w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(self.tabs['help'])
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
