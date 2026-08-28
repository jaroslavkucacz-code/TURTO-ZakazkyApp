# TURTO CRM 6.2 active extension layer
# Consolidated from the proven 6.1.15 runtime. One active layer owns table layout,
# offer archive/import, exact supplier Excel export and DB-only offer deletion.


def apply(M):
    import os,re,json,hashlib,shutil
    from pathlib import Path

    # ---- unified Treeview geometry -----------------------------------------
    COMPACT={'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení','ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'}
    def display_columns(t):
        try:
            allc=list(t.cget('columns')); raw=list(t.cget('displaycolumns'))
            if not raw or raw==['#all']:return allc
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allc):out.append(allc[i])
                elif c in allc:out.append(c)
            return out or allc
        except Exception:return []
    def fit_tree(t,available=None):
        try:
            cols=display_columns(t)
            if not cols:return
            if not hasattr(t,'_turto_design_widths'):
                t._turto_design_widths={c:max(50,min(int(t.column(c,'width')),500)) for c in cols}
            d=t._turto_design_widths
            for c in cols:
                if c not in d:d[c]=max(50,min(int(t.column(c,'width')),500))
            w=int(available if available is not None else t.winfo_width())
            if w<=10:return
            flex=[c for c in cols if str(c) not in COMPACT] or [cols[-1]]
            preferred=sum(d[c] for c in cols);q,r=divmod(max(0,w-4-preferred),len(flex))
            for c in cols:
                cw=d[c]
                if c in flex:
                    i=flex.index(c);cw+=q+(1 if i<r else 0)
                t.column(c,width=cw,minwidth=max(50,min(d[c],120)),stretch=False)
        except Exception:pass
    def install_tree(t):
        try:
            if not getattr(t,'_turto_layout_bound',False):
                t._turto_layout_bound=True
                t.bind('<Configure>',lambda e:fit_tree(t,e.width),add='+');t.bind('<Map>',lambda e:fit_tree(t),add='+')
            fit_tree(t)
        except Exception:pass
    def walk(w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':install_tree(c)
                except Exception:pass
                walk(c)
        except Exception:pass
    def normalize(app):walk(app)
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k);install_tree(t);return t
        M.App.tree=tree
    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_projects','refresh_offers','refresh_tasks','refresh_companies','refresh_people','refresh_all'):
        old=getattr(M.App,name,None)
        if callable(old):
            def make(fn):
                def wrapped(self,*a,**k):
                    r=fn(self,*a,**k);normalize(self);return r
                return wrapped
            setattr(M.App,name,make(old))

    # ---- local archive setting ---------------------------------------------
    LOCAL_CFG=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'local_settings.json'
    DEFAULT_ARCHIVE=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'Nabidky'
    MAIN_EXTS={'.pdf','.xls','.xlsx','.xlsm','.xlsb','.csv','.ods','.doc','.docx','.odt','.rtf','.txt','.zip','.rar','.7z','.xml','.ifc','.dwg','.dxf'}
    def active_user(app=None):
        try:return (app.active_user.get() or '').strip() or 'Výchozí'
        except Exception:
            try:return (M.get_setting('active_user','') or '').strip() or 'Výchozí'
            except Exception:return 'Výchozí'
    def load_cfg():
        try:return json.loads(LOCAL_CFG.read_text(encoding='utf-8')) if LOCAL_CFG.exists() else {}
        except Exception:return {}
    def save_cfg(d):
        try:LOCAL_CFG.parent.mkdir(parents=True,exist_ok=True);LOCAL_CFG.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception:pass
    def archive_root(app=None):
        p=((load_cfg().get('offer_archive_dir_by_user') or {}).get(active_user(app)) or '').strip();return Path(p) if p else DEFAULT_ARCHIVE
    def set_archive_root(app,path):
        d=load_cfg();d.setdefault('offer_archive_dir_by_user',{})[active_user(app)]=str(Path(path));save_cfg(d)
    old_settings=getattr(M.App,'build_settings',None)
    if callable(old_settings):
        def build_settings(self):
            r=old_settings(self)
            try:
                from tkinter import ttk,filedialog
                p=self.tabs['settings'];card=ttk.Frame(p,style='Panel.TFrame',padding=18);card.pack(fill='x',pady=(10,0))
                ttk.Label(card,text='Ukládání zpracovaných nabídek',style='Panel.TLabel',font=('Calibri',12,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
                var=M.tk.StringVar(value=str(archive_root(self)));self._offer_archive_dir_var=var
                ent=ttk.Entry(card,textvariable=var);ent.grid(row=1,column=0,sticky='ew',padx=(0,8));card.columnconfigure(0,weight=1)
                def choose():
                    x=filedialog.askdirectory(parent=self,initialdir=var.get() or str(DEFAULT_ARCHIVE))
                    if x:var.set(x);set_archive_root(self,x)
                ent.bind('<FocusOut>',lambda e:set_archive_root(self,var.get()) if var.get().strip() else None)
                ttk.Button(card,text='Vybrat…',command=choose).grid(row=1,column=1)
            except Exception:pass
            return r
        M.App.build_settings=build_settings

    # ---- exact proven supplier exporter ------------------------------------
    # v624 is the canonical exporter; do not duplicate workbook formatting here.
    try:
        import v624_legacy_exports
        v624_legacy_exports.apply(M)
    except Exception:pass
    manual_export=getattr(M,'export_offer_excel',None)
    def export_to_path(app,oid,target):
        if not callable(manual_export):raise RuntimeError('CRM Excel export není dostupný.')
        from tkinter import filedialog,messagebox
        target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
        save,info,error=filedialog.asksaveasfilename,messagebox.showinfo,messagebox.showerror;errs=[]
        try:
            filedialog.asksaveasfilename=lambda *a,**k:str(target);messagebox.showinfo=lambda *a,**k:None;messagebox.showerror=lambda t,m,*a,**k:errs.append(str(m))
            manual_export(app,oid,app)
        finally:filedialog.asksaveasfilename,messagebox.showinfo,messagebox.showerror=save,info,error
        if errs:raise RuntimeError(errs[-1])
        return target
    M.export_offer_exactly_like_manual=export_to_path

    # ---- DB-first archive pipeline -----------------------------------------
    def safe(v,n=100):return (re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(v or '')).strip(' ._') or 'Bez_nazvu')[:n]
    def folder_for(app,oid,path=None,subject=''):
        with M.db() as c:o=c.execute("SELECT offer_date,offer_number,coalesce(supplier_name,'') supplier FROM supplier_offers WHERE id=?",(oid,)).fetchone()
        h=''
        try:h=hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]
        except Exception:pass
        name='_'.join(x for x in (((o['offer_date'] or '')[:10] if o else '') or 'bez-data',safe(o['supplier'] if o else '',35),safe((o['offer_number'] if o else '') or subject or Path(path).stem,55),h) if x)
        f=archive_root(app)/name;f.mkdir(parents=True,exist_ok=True);return f
    base_pdf=getattr(M,'process_offer_pdf',None);base_msg=getattr(M,'process_offer_msg',None)
    if callable(base_pdf):
        def process_pdf(app,path,*a,**k):
            result=base_pdf(app,path,*a,**k)
            if getattr(app,'_turto_inside_msg',False):return result
            try:
                oid=result.get('offer_id');f=folder_for(app,oid,path);src=Path(path);shutil.copy2(src,f/safe(src.name,130));out=f/'Extrakce_nabidky.xlsx';export_to_path(app,oid,out);result.update(archive_folder=str(f),excel_files=[str(out)])
            except Exception as e:
                if isinstance(result,dict):result.setdefault('errors',[]).append(str(e))
            return result
        M.process_offer_pdf=process_pdf
    if callable(base_msg):
        def process_msg(app,path,*a,**k):
            app._turto_inside_msg=True
            try:result=base_msg(app,path,*a,**k)
            finally:app._turto_inside_msg=False
            try:
                offers=[x for x in result.get('offers',[]) if x.get('offer_id')]
                if not offers:return result
                import extract_msg
                msg=extract_msg.Message(str(path));f=folder_for(app,offers[0]['offer_id'],path,getattr(msg,'subject',''))
                shutil.copy2(path,f/safe(Path(path).name,130))
                for i,a in enumerate(getattr(msg,'attachments',[]) or [],1):
                    name=str(getattr(a,'longFilename',None) or getattr(a,'shortFilename',None) or f'priloha_{i}')
                    if Path(name).suffix.lower() not in MAIN_EXTS:continue
                    data=getattr(a,'data',b'');data=data() if callable(data) else data
                    if data:(f/safe(Path(name).name,130)).write_bytes(bytes(data))
                try:msg.close()
                except Exception:pass
                outs=[]
                for i,o in enumerate(offers,1):
                    out=f/('Extrakce_nabidky.xlsx' if len(offers)==1 else f'Extrakce_nabidky_{i}.xlsx');export_to_path(app,o['offer_id'],out);outs.append(str(out))
                result.update(archive_folder=str(f),excel_files=outs)
            except Exception as e:result.setdefault('errors',[]).append(str(e))
            return result
        M.process_offer_msg=process_msg

    # ---- DB-only deletion; disk archive is independent ---------------------
    def delete_offer(self):
        oid=self._selected_offer_id() if hasattr(self,'_selected_offer_id') else None
        if not oid:return
        if not M.messagebox.askyesno('Nabídky','Opravdu odstranit tento import nabídky z CRM?\n\nSoubory na disku zůstanou beze změny.',parent=self):return
        try:
            with M.db() as c:
                try:c.execute('UPDATE offer_source_attachments SET offer_id=NULL WHERE offer_id=?',(oid,))
                except Exception:pass
                c.execute('DELETE FROM supplier_offers WHERE id=?',(oid,))
            self.refresh_offers()
        except Exception as e:M.messagebox.showerror('Nabídky',str(e),parent=self)
    M.App.delete_offer=delete_offer

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.update_idletasks();normalize(self)
        except Exception:pass
        return r
    M.App.__init__=init
