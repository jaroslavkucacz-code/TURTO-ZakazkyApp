# TURTO CRM 6.1+ active extension layer
# 6.1.11: deterministic widths + MSG archive + canonical Excel + batch progress.


def apply(M):
    COMPACT={'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení','ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'}

    def display_columns(tree):
        try:
            allcols=list(tree.cget('columns'));raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']:return allcols
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols):out.append(allcols[i])
                elif c in allcols:out.append(c)
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
        return tree._v617_design_widths

    def fit_tree(tree,available=None):
        try:
            cols=display_columns(tree)
            if not cols:return
            d=ensure_design(tree,cols)
            for c in cols:
                if c not in d:
                    try:d[c]=max(50,min(int(tree.column(c,'width')),500))
                    except Exception:d[c]=100
            flex=[c for c in cols if str(c) not in COMPACT] or [cols[-1]]
            if available is None:available=int(tree.winfo_width())
            if int(available)<=10:return
            available=max(1,int(available)-4);preferred=sum(int(d[c]) for c in cols)
            q,r=divmod(max(0,available-preferred),len(flex))
            for c in cols:
                w=int(d[c])
                if c in flex:
                    i=flex.index(c);w+=q+(1 if i<r else 0)
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
                        region=tree.identify_region(e.x,e.y);row=tree.identify_row(e.y)
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
            t=old_tree(self,*a,**k);install_tree(t);return t
        M.App.tree=tree
    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_projects','refresh_offers','refresh_tasks','refresh_companies','refresh_people','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k);normalize_all(self);return r
            return wrapped
        setattr(M.App,name,make(old))
    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k);normalize_all(self);return r
        M.App.show_page=show_page

    # --------------------------- MSG archive ---------------------------
    import re,hashlib
    from pathlib import Path
    MAIN_ATTACHMENT_EXTS={'.pdf','.xls','.xlsx','.xlsm','.xlsb','.csv','.ods','.doc','.docx','.odt','.rtf','.txt','.zip','.rar','.7z','.xml','.ifc','.dwg','.dxf'}
    def _safe_name(value,maxlen=90):
        s=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(value or '').strip());s=re.sub(r'\s+',' ',s).strip(' ._')
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
    def _archive_msg(path):
        path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest();import extract_msg
        msg=extract_msg.Message(str(path))
        try:
            subject=str(getattr(msg,'subject','') or path.stem);sent=getattr(msg,'date',None)
            if hasattr(sent,'strftime'):datepart=sent.strftime('%Y-%m-%d')
            else:
                m=re.search(r'\d{4}-\d{2}-\d{2}',str(sent or ''));datepart=m.group(0) if m else 'bez-data'
            root=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'Nabidky'
            folder=root/f'{datepart}_{_safe_name(subject,70)}_{digest[:8]}';folder.mkdir(parents=True,exist_ok=True)
            archived=folder/(_safe_name(path.stem,90)+'.msg')
            if not archived.exists() or archived.stat().st_size!=len(raw):archived.write_bytes(raw)
            saved=[]
            for n,att in enumerate(getattr(msg,'attachments',[]) or [],1):
                name=str(getattr(att,'longFilename',None) or getattr(att,'shortFilename',None) or getattr(att,'name',None) or f'priloha_{n}')
                ext=Path(name).suffix.lower()
                if ext not in MAIN_ATTACHMENT_EXTS:continue
                data=_att_bytes(att)
                if not data:continue
                out=folder/_safe_name(Path(name).name,120)
                if out.exists() and out.read_bytes()!=data:out=folder/f'{out.stem}_{hashlib.sha256(data).hexdigest()[:6]}{out.suffix}'
                if not out.exists():out.write_bytes(data)
                saved.append(out)
            return folder,archived,saved,subject
        finally:
            try:msg.close()
            except Exception:pass

    # Exact same layout/formatting as the program's normal "Exportovat nabídku do Excelu".
    def _export_offer_same_as_program(offer_id,path):
        import io,xlsxwriter
        with M.db() as c:
            o=c.execute('''SELECT o.*,coalesce(s.official_name,o.supplier_name,'') supplier,c.official_name customer,a.name action_name
                FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?''',(offer_id,)).fetchone()
            items=c.execute('SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',(offer_id,)).fetchall()
        if not o:return None
        wb=xlsxwriter.Workbook(str(path));ws=wb.add_worksheet('Nabídka')
        title=wb.add_format({'bold':True,'font_size':16});lab=wb.add_format({'bold':True});head=wb.add_format({'bold':True,'bg_color':'#E7ECF0','border':1});num=wb.add_format({'num_format':'#,##0.00','border':1});cell=wb.add_format({'border':1});pct=wb.add_format({'num_format':'0.00%','border':1})
        try:
            ws.write('A1','Cenová nabídka',title)
            meta=[('Dodavatel',o['supplier'] or ''),('Odběratel',o['customer'] or ''),('Akce',o['action_name'] or ''),('Číslo nabídky',o['offer_number'] or ''),('Datum',M.fmt_date(o['offer_date'])),('Měna',o['currency'] or 'CZK'),('Celkem',float(o['total_value'] or 0))]
            for i,(k,v) in enumerate(meta,2):ws.write(i-1,0,k,lab);ws.write(i-1,1,v)
            headers=['Poz.','Kód','Název','item_key','Množství','MJ','Původní cena','Sleva %','Cena/ks','Celkem','Obrázek'];row=10
            for col,h in enumerate(headers):ws.write(row,col,h,head)
            for it in items:
                row+=1;vals=[it['position'],it['product_code'] or '',it['original_name'] or '',it['item_key'] or '',float(it['quantity'] or 0),it['unit'] or '',float(it['original_unit_price'] or 0),float(it['discount_pct'] or 0)/100.0,float(it['unit_price'] or 0),float(it['total_price'] or 0)]
                for col,v in enumerate(vals):ws.write(row,col,v,pct if col==7 else (num if col in (4,6,8,9) else cell))
                blob=it['image_blob'] if 'image_blob' in it.keys() else None
                if not blob:
                    with M.db() as c:
                        im=c.execute('SELECT image_blob FROM offer_product_images WHERE supplier=? AND item_key=?',(o['supplier'] or '',it['item_key'] or '')).fetchone();blob=im['image_blob'] if im and im['image_blob'] else None
                if blob:
                    try:
                        bio=io.BytesIO(bytes(blob));ws.set_row(row,72);ws.insert_image(row,10,'image.png',{'image_data':bio,'x_scale':0.35,'y_scale':0.35,'object_position':1})
                    except Exception:pass
            ws.set_column('A:A',7);ws.set_column('B:B',16);ws.set_column('C:C',42);ws.set_column('D:D',30);ws.set_column('E:E',12);ws.set_column('F:F',8);ws.set_column('G:J',14);ws.set_column('K:K',18);ws.freeze_panes(11,0);ws.autofilter(10,0,row,9)
        finally:wb.close()
        return path

    def _export_msg_offers(result,folder):
        offers=[x for x in (result.get('offers') or []) if isinstance(x,dict) and x.get('offer_id')]
        if not offers:return []
        outs=[]
        # One recognized offer => canonical file name. Multiple => same canonical export per offer.
        for i,o in enumerate(offers,1):
            out=folder/('Extrakce_nabidky.xlsx' if len(offers)==1 else f'Extrakce_nabidky_{i}.xlsx')
            _export_offer_same_as_program(o['offer_id'],out);outs.append(out)
        return outs

    old_process_msg=getattr(M,'process_offer_msg',None)
    if callable(old_process_msg):
        def process_offer_msg_archived(app,path):
            folder=archived=atts=None
            try:folder,archived,atts,_=_archive_msg(path)
            except Exception:folder=archived=atts=None
            result=old_process_msg(app,path)
            if isinstance(result,dict) and folder and archived:
                try:
                    with M.db() as c:
                        if result.get('message_id'):c.execute('UPDATE offer_source_messages SET source_path=? WHERE id=?',(str(archived),result['message_id']))
                    result['excel_files']=[str(x) for x in _export_msg_offers(result,folder)]
                    result['archive_folder']=str(folder);result['archive_msg']=str(archived)
                except Exception as e:result.setdefault('errors',[]).append('Archiv/Excel: '+str(e))
            return result
        M.process_offer_msg=process_offer_msg_archived

        # Cooperative batch runner: UI stays responsive between files, Cancel stops
        # before the next file, Background merely hides the progress window.
        def _run_offer_batch(self,paths):
            import tkinter as tk
            from tkinter import ttk,messagebox
            paths=list(paths);total=len(paths);state={'i':0,'cancel':False,'background':False,'ok':[],'errors':[],'msg':0,'att':0,'archives':[]}
            dlg=tk.Toplevel(self);dlg.title('Zpracování cenových nabídek');dlg.transient(self);dlg.resizable(False,False);dlg.geometry('520x190')
            box=ttk.Frame(dlg,padding=18);box.pack(fill='both',expand=True)
            title=ttk.Label(box,text=f'Zpracování 0 z {total}',style='Section.TLabel');title.pack(anchor='w')
            current=ttk.Label(box,text='Připravuji…',style='PageSubtitle.TLabel');current.pack(anchor='w',pady=(6,10))
            bar=ttk.Progressbar(box,maximum=max(1,total),value=0,length=480);bar.pack(fill='x',pady=(0,14))
            buttons=ttk.Frame(box);buttons.pack(fill='x')
            def cancel():state['cancel']=True;current.configure(text='Po dokončení aktuálního souboru bude zpracování zastaveno…')
            def background():state['background']=True;dlg.withdraw()
            ttk.Button(buttons,text='Storno',command=cancel).pack(side='right')
            ttk.Button(buttons,text='Pokračovat na pozadí',command=background).pack(side='right',padx=(0,8))
            dlg.protocol('WM_DELETE_WINDOW',background)

            def finish():
                try:self.refresh_offers()
                except Exception:pass
                try:dlg.destroy()
                except Exception:pass
                text=f"Zpracování {'zastaveno' if state['cancel'] else 'dokončeno'}.\n\nNabídky: {len(state['ok'])}\nMSG: {state['msg']}\nPřílohy v MSG: {state['att']}"
                if state['archives']:text+='\nArchivováno do Dokumenty\\TURTO Zakazky\\Nabidky'
                if state['errors']:text+='\n\nChyby / nerozpoznané: '+str(len(state['errors']))+'\n'+'\n'.join(state['errors'][:12])
                messagebox.showinfo('Zpracování cenových nabídek',text,parent=self)

            def step():
                if state['cancel'] or state['i']>=total:return finish()
                p=Path(paths[state['i']]);title.configure(text=f"Zpracování {state['i']+1} z {total}");current.configure(text=p.name);bar['value']=state['i'];self.update_idletasks()
                try:
                    if p.suffix.lower()=='.msg':
                        r=M.process_offer_msg(self,p);state['msg']+=1;state['att']+=int((r or {}).get('attachments') or 0);state['ok'].extend((r or {}).get('offers') or [])
                        if (r or {}).get('archive_folder'):state['archives'].append((r or {}).get('archive_folder'))
                        state['errors'].extend((r or {}).get('errors') or [])
                        for x in (r or {}).get('results') or []:
                            if isinstance(x,dict) and x.get('error'):state['errors'].append(x['error'])
                    elif p.suffix.lower()=='.pdf':state['ok'].append(M.process_offer_pdf(self,p))
                    else:state['errors'].append(f'{p.name}: nepodporovaný vstupní formát')
                except Exception as e:state['errors'].append(f'{p.name}: {e}')
                state['i']+=1;bar['value']=state['i'];self.after(20,step)
            self.after(20,step)

        def import_offer_sources_archived(self):
            from tkinter import filedialog
            paths=filedialog.askopenfilenames(parent=self,title='Importovat cenové nabídky',filetypes=[('Nabídky / e-maily','*.pdf *.msg'),('PDF','*.pdf'),('Outlook zprávy','*.msg'),('Všechny soubory','*.*')])
            if not paths:return
            if len(paths)>1:return _run_offer_batch(self,paths)
            # Single-file import remains immediate; no unnecessary progress dialog.
            return _run_offer_batch(self,paths)
        M.App.import_offer_sources=import_offer_sources_archived

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.update_idletasks();normalize_all(self);self.update_idletasks();normalize_all(self)
        except Exception:pass
        return r
    M.App.__init__=init
