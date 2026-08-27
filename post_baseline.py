# TURTO CRM 6.1+ active extension layer
# 6.1.12: one DB-first offer pipeline, canonical Excel export, per-PC archive setting.


def apply(M):
    # ------------------------------------------------------------------
    # 1) Unified deterministic Treeview geometry + safe right-click handling.
    # ------------------------------------------------------------------
    COMPACT={'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení','ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'}

    def display_columns(tree):
        try:
            allcols=list(tree.cget('columns')); raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']: return allcols
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols): out.append(allcols[i])
                elif c in allcols: out.append(c)
            return out or allcols
        except Exception:return []

    def ensure_design(tree,cols):
        if not hasattr(tree,'_v617_design_widths'):
            d={}
            for c in cols:
                try:w=int(tree.column(c,'width'))
                except Exception:w=100
                d[c]=max(50,min(w,500))
            tree._v617_design_widths=d
        d=tree._v617_design_widths
        for c in cols:
            if c not in d:
                try:d[c]=max(50,min(int(tree.column(c,'width')),500))
                except Exception:d[c]=100
        return d

    def fit_tree(tree,available=None):
        try:
            cols=display_columns(tree)
            if not cols:return
            d=ensure_design(tree,cols)
            flex=[c for c in cols if str(c) not in COMPACT] or [cols[-1]]
            if available is None:available=int(tree.winfo_width())
            if int(available)<=10:return
            available=max(1,int(available)-4); preferred=sum(int(d[c]) for c in cols)
            q,r=divmod(max(0,available-preferred),len(flex))
            for c in cols:
                w=int(d[c])
                if c in flex:
                    i=flex.index(c); w+=q+(1 if i<r else 0)
                tree.column(c,width=w,minwidth=max(50,min(int(d[c]),120)),stretch=False)
            try:tree.xview_moveto(0.0)
            except Exception:pass
        except Exception:pass

    def install_tree(tree):
        try:
            if tree is None or not tree.winfo_exists():return
            cols=display_columns(tree)
            if not cols:return
            ensure_design(tree,cols)
            if not getattr(tree,'_v617_width_bound',False):
                tree._v617_width_bound=True
                tree.bind('<Configure>',lambda e:fit_tree(tree,getattr(e,'width',None)),add='+')
                tree.bind('<Map>',lambda e:fit_tree(tree),add='+')
            if not getattr(tree,'_v619_context_guard',False):
                tree._v619_context_guard=True
                def context_guard(e):
                    try:
                        region=tree.identify_region(e.x,e.y); row=tree.identify_row(e.y)
                        if region not in ('tree','cell') or not row:return 'break'
                    except Exception:return 'break'
                tree.bind('<Button-3>',context_guard,add=False)
            fit_tree(tree)
        except Exception:pass

    def walk(w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':install_tree(c)
                except Exception:pass
                walk(c)
        except Exception:pass
    def normalize_all(app):walk(app)

    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k); install_tree(t); return t
        M.App.tree=tree
    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_projects','refresh_offers','refresh_tasks','refresh_companies','refresh_people','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k); normalize_all(self); return r
            return wrapped
        setattr(M.App,name,make(old))
    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k); normalize_all(self); return r
        M.App.show_page=show_page

    # ------------------------------------------------------------------
    # 2) Per-PC / per-user archive folder setting.
    # It intentionally lives outside the CRM DB, so a path from PC A is not
    # propagated to another machine when database data are moved/synchronised.
    # ------------------------------------------------------------------
    import os,re,json,hashlib,shutil
    from pathlib import Path

    LOCAL_CFG=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'local_settings.json'
    DEFAULT_ARCHIVE=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'Nabidky'
    MAIN_ATTACHMENT_EXTS={'.pdf','.xls','.xlsx','.xlsm','.xlsb','.csv','.ods','.doc','.docx','.odt','.rtf','.txt','.zip','.rar','.7z','.xml','.ifc','.dwg','.dxf'}

    def _active_user(app=None):
        try:
            if app is not None and hasattr(app,'active_user'):return (app.active_user.get() or '').strip() or 'Výchozí'
        except Exception:pass
        try:return (M.get_setting('active_user','') or '').strip() or 'Výchozí'
        except Exception:return 'Výchozí'

    def _load_local_cfg():
        try:
            if LOCAL_CFG.exists():
                d=json.loads(LOCAL_CFG.read_text(encoding='utf-8'))
                if isinstance(d,dict):return d
        except Exception:pass
        return {}

    def _save_local_cfg(d):
        try:
            LOCAL_CFG.parent.mkdir(parents=True,exist_ok=True)
            tmp=LOCAL_CFG.with_suffix('.tmp'); tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(LOCAL_CFG)
        except Exception:pass

    def _archive_root(app=None):
        user=_active_user(app); d=_load_local_cfg(); p=((d.get('offer_archive_dir_by_user') or {}).get(user) or '').strip()
        return Path(p) if p else DEFAULT_ARCHIVE

    def _set_archive_root(app,path):
        user=_active_user(app); d=_load_local_cfg(); mp=d.setdefault('offer_archive_dir_by_user',{}); mp[user]=str(Path(path)); _save_local_cfg(d)

    # Add the setting to the existing Settings page without changing DB schema.
    old_build_settings=getattr(M.App,'build_settings',None)
    if callable(old_build_settings):
        def build_settings(self):
            r=old_build_settings(self)
            try:
                import tkinter as tk
                from tkinter import ttk,filedialog
                p=self.tabs['settings']
                card=ttk.Frame(p,style='Panel.TFrame',padding=18); card.pack(fill='x',pady=(10,0))
                ttk.Label(card,text='Ukládání zpracovaných nabídek',style='Panel.TLabel',font=('Calibri',12,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
                ttk.Label(card,text='Výchozí složka je lokální pro tento počítač a aktuálního uživatele.',style='PageSubtitle.TLabel').grid(row=1,column=0,columnspan=3,sticky='w',pady=(2,10))
                var=tk.StringVar(value=str(_archive_root(self))); self._offer_archive_dir_var=var
                ent=ttk.Entry(card,textvariable=var); ent.grid(row=2,column=0,sticky='ew',padx=(0,8))
                card.columnconfigure(0,weight=1)
                def choose():
                    path=filedialog.askdirectory(parent=self,title='Vybrat složku pro nabídky',initialdir=var.get() or str(DEFAULT_ARCHIVE))
                    if path:var.set(path);_set_archive_root(self,path)
                def save_entry(*_):
                    v=var.get().strip()
                    if v:_set_archive_root(self,v)
                ent.bind('<FocusOut>',save_entry); ent.bind('<Return>',save_entry)
                ttk.Button(card,text='Vybrat…',command=choose).grid(row=2,column=1,sticky='e')
                ttk.Button(card,text='Výchozí',command=lambda:(var.set(str(DEFAULT_ARCHIVE)),_set_archive_root(self,DEFAULT_ARCHIVE))).grid(row=2,column=2,sticky='e',padx=(8,0))
            except Exception:pass
            return r
        M.App.build_settings=build_settings

    # ------------------------------------------------------------------
    # 3) ONE canonical Excel writer. Manual export and automatic extraction
    # both call this exact function, so they cannot drift apart visually.
    # Data are read only from the database after import has completed.
    # ------------------------------------------------------------------
    def _write_offer_excel_from_db(offer_id,path):
        import io,xlsxwriter
        with M.db() as c:
            o=c.execute('''SELECT o.*,coalesce(s.official_name,o.supplier_name,'') supplier,c.official_name customer,a.name action_name
                FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?''',(offer_id,)).fetchone()
            items=c.execute('SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',(offer_id,)).fetchall()
        if not o:return None
        wb=xlsxwriter.Workbook(str(path)); ws=wb.add_worksheet('Nabídka')
        title=wb.add_format({'bold':True,'font_size':16}); lab=wb.add_format({'bold':True}); head=wb.add_format({'bold':True,'bg_color':'#E7ECF0','border':1}); num=wb.add_format({'num_format':'#,##0.00','border':1}); cell=wb.add_format({'border':1}); pct=wb.add_format({'num_format':'0.00%','border':1})
        try:
            ws.write('A1','Cenová nabídka',title)
            meta=[('Dodavatel',o['supplier'] or ''),('Odběratel',o['customer'] or ''),('Akce',o['action_name'] or ''),('Číslo nabídky',o['offer_number'] or ''),('Datum',M.fmt_date(o['offer_date'])),('Měna',o['currency'] or 'CZK'),('Celkem',float(o['total_value'] or 0))]
            for i,(k,v) in enumerate(meta,2):ws.write(i-1,0,k,lab);ws.write(i-1,1,v)
            headers=['Poz.','Kód','Název','item_key','Množství','MJ','Původní cena','Sleva %','Cena/ks','Celkem','Obrázek']; row=10
            for col,h in enumerate(headers):ws.write(row,col,h,head)
            for it in items:
                row+=1
                vals=[it['position'],it['product_code'] or '',it['original_name'] or '',it['item_key'] or '',float(it['quantity'] or 0),it['unit'] or '',float(it['original_unit_price'] or 0),float(it['discount_pct'] or 0)/100.0,float(it['unit_price'] or 0),float(it['total_price'] or 0)]
                for col,v in enumerate(vals):ws.write(row,col,v,pct if col==7 else (num if col in (4,6,8,9) else cell))
                blob=it['image_blob'] if 'image_blob' in it.keys() else None
                if not blob:
                    with M.db() as c:
                        im=c.execute('SELECT image_blob FROM offer_product_images WHERE supplier=? AND item_key=?',(o['supplier'] or '',it['item_key'] or '')).fetchone(); blob=im['image_blob'] if im and im['image_blob'] else None
                if blob:
                    try:
                        bio=io.BytesIO(bytes(blob)); ws.set_row(row,72); ws.insert_image(row,10,'image.png',{'image_data':bio,'x_scale':0.35,'y_scale':0.35,'object_position':1})
                    except Exception:pass
            ws.set_column('A:A',7);ws.set_column('B:B',16);ws.set_column('C:C',42);ws.set_column('D:D',30);ws.set_column('E:E',12);ws.set_column('F:F',8);ws.set_column('G:J',14);ws.set_column('K:K',18);ws.freeze_panes(11,0);ws.autofilter(10,0,row,9)
        finally:wb.close()
        return Path(path)
    M.write_offer_excel_from_db=_write_offer_excel_from_db

    def export_offer_excel(app,offer_id,parent=None):
        from tkinter import filedialog,messagebox
        try:
            with M.db() as c:o=c.execute('SELECT offer_number FROM supplier_offers WHERE id=?',(offer_id,)).fetchone()
            safe=''.join(ch if ch.isalnum() or ch in ' _-' else '_' for ch in str((o['offer_number'] if o else '') or 'nabidka')).strip() or 'nabidka'
            path=filedialog.asksaveasfilename(parent=parent or app,title='Exportovat do Excelu',defaultextension='.xlsx',filetypes=[('Excel','*.xlsx')],initialfile=f'Nabidka_{safe}.xlsx')
            if not path:return
            _write_offer_excel_from_db(offer_id,path)
            messagebox.showinfo('Excel export',f'Export dokončen:\n{path}',parent=parent or app)
        except Exception as e:messagebox.showerror('Excel export',str(e),parent=parent or app)
    M.export_offer_excel=export_offer_excel

    def export_selected_offer(self):
        oid=self._selected_offer_id() if hasattr(self,'_selected_offer_id') else None
        if not oid:return M.messagebox.showinfo('Excel export','Vyberte nabídku.',parent=self)
        return M.export_offer_excel(self,oid,self)
    M.App.export_selected_offer_excel=export_selected_offer

    # ------------------------------------------------------------------
    # 4) DB-first import -> archive source -> Excel from DB.
    # ------------------------------------------------------------------
    def _safe_name(value,maxlen=90):
        s=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(value or '').strip()); s=re.sub(r'\s+',' ',s).strip(' ._')
        return (s or 'Bez_nazvu')[:maxlen]

    def _att_bytes(att):
        data=getattr(att,'data',None)
        if callable(data):data=data()
        if data is None:
            try:data=att.get_data()
            except Exception:data=None
        if isinstance(data,str):return data.encode('utf-8',errors='replace')
        try:return bytes(data or b'')
        except Exception:return b''

    def _offer_folder_from_db(app,offer_id,source_path=None,subject=''):
        with M.db() as c:
            o=c.execute('''SELECT o.offer_date,o.offer_number,coalesce(s.official_name,o.supplier_name,'') supplier
                           FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id WHERE o.id=?''',(offer_id,)).fetchone()
        datepart=(o['offer_date'] if o and o['offer_date'] else '')[:10] or 'bez-data'
        ident=(o['offer_number'] if o and o['offer_number'] else '') or subject or (Path(source_path).stem if source_path else 'nabidka')
        supplier=(o['supplier'] if o else '') or ''
        h=''
        try:h=hashlib.sha256(Path(source_path).read_bytes()).hexdigest()[:8] if source_path else ''
        except Exception:pass
        name='_'.join(x for x in (datepart,_safe_name(supplier,35),_safe_name(ident,55),h) if x)
        folder=_archive_root(app)/name; folder.mkdir(parents=True,exist_ok=True); return folder

    def _archive_pdf_after_db(app,path,result):
        oid=(result or {}).get('offer_id') if isinstance(result,dict) else None
        if not oid:return result
        folder=_offer_folder_from_db(app,oid,path)
        src=Path(path); out=folder/_safe_name(src.name,130)
        try:
            if not out.exists() or out.stat().st_size!=src.stat().st_size:shutil.copy2(src,out)
            excel=folder/'Extrakce_nabidky.xlsx'; _write_offer_excel_from_db(oid,excel)
            result['archive_folder']=str(folder);result['archive_file']=str(out);result['excel_files']=[str(excel)]
        except Exception as e:result.setdefault('errors',[]).append('Archiv/Excel: '+str(e))
        return result

    def _archive_msg_after_db(app,path,result):
        if not isinstance(result,dict):return result
        offers=[x for x in (result.get('offers') or []) if isinstance(x,dict) and x.get('offer_id')]
        if not offers:return result
        first_id=offers[0]['offer_id']; raw=Path(path).read_bytes(); digest=hashlib.sha256(raw).hexdigest()
        import extract_msg
        msg=extract_msg.Message(str(path))
        try:
            subject=str(getattr(msg,'subject','') or Path(path).stem)
            folder=_offer_folder_from_db(app,first_id,path,subject)
            archived=folder/(_safe_name(Path(path).stem,100)+'.msg')
            if not archived.exists() or archived.stat().st_size!=len(raw):archived.write_bytes(raw)
            saved=[]
            for n,att in enumerate(getattr(msg,'attachments',[]) or [],1):
                name=str(getattr(att,'longFilename',None) or getattr(att,'shortFilename',None) or getattr(att,'name',None) or f'priloha_{n}')
                ext=Path(name).suffix.lower()
                if ext not in MAIN_ATTACHMENT_EXTS:continue
                data=_att_bytes(att)
                if not data:continue
                out=folder/_safe_name(Path(name).name,130)
                if out.exists() and out.read_bytes()!=data:out=folder/f'{out.stem}_{hashlib.sha256(data).hexdigest()[:6]}{out.suffix}'
                if not out.exists():out.write_bytes(data)
                saved.append(out)
            excels=[]
            for i,o in enumerate(offers,1):
                out=folder/('Extrakce_nabidky.xlsx' if len(offers)==1 else f'Extrakce_nabidky_{i}.xlsx')
                _write_offer_excel_from_db(o['offer_id'],out);excels.append(str(out))
            if result.get('message_id'):
                try:
                    with M.db() as c:c.execute('UPDATE offer_source_messages SET source_path=? WHERE id=?',(str(archived),result['message_id']))
                except Exception:pass
            result['archive_folder']=str(folder);result['archive_msg']=str(archived);result['archive_attachments']=[str(x) for x in saved];result['excel_files']=excels
        except Exception as e:result.setdefault('errors',[]).append('Archiv/Excel: '+str(e))
        finally:
            try:msg.close()
            except Exception:pass
        return result

    base_process_pdf=getattr(M,'process_offer_pdf',None)
    base_process_msg=getattr(M,'process_offer_msg',None)

    if callable(base_process_pdf):
        def process_offer_pdf_dbfirst(app,path,*a,**k):
            # First database import, then archive source PDF, then Excel from DB.
            result=base_process_pdf(app,path,*a,**k)
            # Attachment PDFs inside MSG are handled by the MSG archive as a whole.
            if getattr(app,'_v612_inside_msg',False):return result
            return _archive_pdf_after_db(app,path,result)
        M.process_offer_pdf=process_offer_pdf_dbfirst

    if callable(base_process_msg):
        def process_offer_msg_dbfirst(app,path):
            # Keep nested attachment PDF processing DB-only during the message import.
            app._v612_inside_msg=True
            try:result=base_process_msg(app,path)
            finally:app._v612_inside_msg=False
            # Only now archive the original MSG + relevant attachments and export DB data.
            return _archive_msg_after_db(app,path,result)
        M.process_offer_msg=process_offer_msg_dbfirst

    # ------------------------------------------------------------------
    # 5) One batch runner used by the file-picker and Explorer drag/drop.
    # ------------------------------------------------------------------
    def _start_offer_batch(self,paths):
        import tkinter as tk
        from tkinter import ttk,messagebox
        paths=[Path(p) for p in paths if str(p).lower().endswith(('.pdf','.msg'))]
        if not paths:return
        total=len(paths); state={'i':0,'cancel':False,'ok':[],'errors':[],'msg':0,'att':0,'archives':[]}
        dlg=tk.Toplevel(self);dlg.title('Zpracování cenových nabídek');dlg.transient(self);dlg.resizable(False,False);dlg.geometry('540x205')
        box=ttk.Frame(dlg,padding=18);box.pack(fill='both',expand=True)
        title=ttk.Label(box,text=f'Zpracování 0 z {total}',style='Section.TLabel');title.pack(anchor='w')
        current=ttk.Label(box,text='Připravuji…',style='PageSubtitle.TLabel');current.pack(anchor='w',pady=(6,10))
        bar=ttk.Progressbar(box,maximum=max(1,total),value=0,length=500);bar.pack(fill='x',pady=(0,14))
        buttons=ttk.Frame(box);buttons.pack(fill='x')
        def cancel():state['cancel']=True;current.configure(text='Po dokončení aktuálního souboru bude zpracování zastaveno…')
        def background():dlg.withdraw()
        ttk.Button(buttons,text='Storno',command=cancel).pack(side='right')
        ttk.Button(buttons,text='Pokračovat na pozadí',command=background).pack(side='right',padx=(0,8))
        dlg.protocol('WM_DELETE_WINDOW',background)

        def finish():
            try:self.refresh_offers()
            except Exception:pass
            try:dlg.destroy()
            except Exception:pass
            text=f"Zpracování {'zastaveno' if state['cancel'] else 'dokončeno'}.\n\nNabídky: {len(state['ok'])}\nMSG: {state['msg']}\nPřílohy v MSG: {state['att']}"
            if state['archives']:text+='\nArchiv: '+str(_archive_root(self))
            if state['errors']:text+='\n\nChyby / nerozpoznané: '+str(len(state['errors']))+'\n'+'\n'.join(state['errors'][:12])
            messagebox.showinfo('Zpracování cenových nabídek',text,parent=self)

        def step():
            if state['cancel'] or state['i']>=total:return finish()
            p=paths[state['i']]; title.configure(text=f"Zpracování {state['i']+1} z {total}"); current.configure(text=p.name); bar['value']=state['i']; self.update_idletasks()
            try:
                if p.suffix.lower()=='.msg':
                    r=M.process_offer_msg(self,p);state['msg']+=1;state['att']+=int((r or {}).get('attachments') or 0);state['ok'].extend((r or {}).get('offers') or [])
                    if (r or {}).get('archive_folder'):state['archives'].append((r or {}).get('archive_folder'))
                    state['errors'].extend((r or {}).get('errors') or [])
                    for x in (r or {}).get('results') or []:
                        if isinstance(x,dict) and x.get('error'):state['errors'].append(x['error'])
                else:
                    r=M.process_offer_pdf(self,p);state['ok'].append(r)
                    if isinstance(r,dict) and r.get('archive_folder'):state['archives'].append(r['archive_folder'])
                    if isinstance(r,dict):state['errors'].extend(r.get('errors') or [])
            except Exception as e:state['errors'].append(f'{p.name}: {e}')
            state['i']+=1;bar['value']=state['i'];self.after(30,step)
        self.after(10,step)
    M.App._start_offer_batch=_start_offer_batch

    def import_offer_sources(self):
        from tkinter import filedialog
        paths=filedialog.askopenfilenames(parent=self,title='Importovat cenové nabídky',filetypes=[('Nabídky / e-maily','*.pdf *.msg'),('PDF','*.pdf'),('Outlook zprávy','*.msg'),('Všechny soubory','*.*')])
        if paths:self._start_offer_batch(paths)
    M.App.import_offer_sources=import_offer_sources

    # Replace Explorer/Outlook OLE target after the legacy one so multi-file drag
    # uses the same batch runner. Outlook virtual drops keep the existing safe importer.
    def _install_drop_target(app):
        if os.name!='nt':return False
        try:
            import pythoncom,win32clipboard,win32con,win32com.server.policy
            from win32comext.shell import shell,shellcon
            hwnd=int(app.winfo_id())
            try:pythoncom.RevokeDragDrop(hwnd)
            except Exception:pass
            fmt_w=win32clipboard.RegisterClipboardFormat('FileGroupDescriptorW');fmt_a=win32clipboard.RegisterClipboardFormat('FileGroupDescriptor')
            def qget(obj,fmt,tymed):
                try:obj.QueryGetData((fmt,None,pythoncom.DVASPECT_CONTENT,-1,tymed));return True
                except Exception:return False
            def paths_of(obj):
                if not qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL):return []
                try:
                    data=obj.GetData((win32con.CF_HDROP,None,pythoncom.DVASPECT_CONTENT,-1,pythoncom.TYMED_HGLOBAL));h=getattr(data,'data_handle',None)
                    if not h:return []
                    n=shell.DragQueryFileW(h,-1);return [shell.DragQueryFileW(h,i) for i in range(n)]
                except Exception:return []
            def virtual(obj):
                return (not qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL)) and (qget(obj,fmt_w,pythoncom.TYMED_HGLOBAL) or qget(obj,fmt_a,pythoncom.TYMED_HGLOBAL))
            class Target(win32com.server.policy.DesignatedWrapPolicy):
                _public_methods_=['DragEnter','DragOver','DragLeave','Drop'];_com_interfaces_=[pythoncom.IID_IDropTarget]
                def __init__(self,owner):self._wrap_(self);self.owner=owner;self.kind=None
                def DragEnter(self,obj,key_state,point,effect):
                    self.kind='files' if qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL) else ('outlook' if virtual(obj) else None)
                    return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE
                def DragOver(self,key_state,point,effect):return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE
                def DragLeave(self):self.kind=None
                def Drop(self,obj,key_state,point,effect):
                    kind=self.kind;self.kind=None
                    if kind=='files':
                        ps=[p for p in paths_of(obj) if Path(p).suffix.lower() in ('.pdf','.msg')]
                        if ps:self.owner.after(80,lambda p=tuple(ps):self.owner._start_offer_batch(p));return shellcon.DROPEFFECT_COPY
                    if kind=='outlook':
                        self.owner.after(650,self.owner.import_selected_outlook_offer);return shellcon.DROPEFFECT_COPY
                    return shellcon.DROPEFFECT_NONE
            pythoncom.OleInitialize();target=Target(app);wrapped=pythoncom.WrapObject(target,pythoncom.IID_IDropTarget,pythoncom.IID_IDropTarget);pythoncom.RegisterDragDrop(hwnd,wrapped)
            app._v612_drop_target=target;app._v612_drop_wrapped=wrapped;return True
        except Exception:return False

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.update_idletasks();normalize_all(self);self.update_idletasks();normalize_all(self)
        except Exception:pass
        try:self.after(4200,lambda:_install_drop_target(self))
        except Exception:pass
        return r
    M.App.__init__=init
