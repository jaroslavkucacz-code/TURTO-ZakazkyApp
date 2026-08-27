# TURTO CRM 6.1+ active extension layer
# 6.1.10: deterministic widths + MSG archive workflow + automatic Excel extraction.


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

    # ------------------------------------------------------------------
    # MSG archive workflow
    # ------------------------------------------------------------------
    import os,re,hashlib,shutil
    from pathlib import Path

    MAIN_ATTACHMENT_EXTS={
        '.pdf','.xls','.xlsx','.xlsm','.xlsb','.csv','.ods',
        '.doc','.docx','.odt','.rtf','.txt',
        '.zip','.rar','.7z','.xml','.ifc','.dwg','.dxf'
    }

    def _safe_name(value,maxlen=90):
        s=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(value or '').strip())
        s=re.sub(r'\s+',' ',s).strip(' ._')
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
        path=Path(path);raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        import extract_msg
        msg=extract_msg.Message(str(path))
        try:
            subject=str(getattr(msg,'subject','') or path.stem)
            sent=getattr(msg,'date',None)
            if hasattr(sent,'strftime'):datepart=sent.strftime('%Y-%m-%d')
            else:
                m=re.search(r'\d{4}-\d{2}-\d{2}',str(sent or ''))
                datepart=m.group(0) if m else 'bez-data'
            root=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'Nabidky'
            folder=root/f'{datepart}_{_safe_name(subject,70)}_{digest[:8]}'
            folder.mkdir(parents=True,exist_ok=True)
            msg_name=_safe_name(path.stem,90)+'.msg'
            archived_msg=folder/msg_name
            if not archived_msg.exists() or archived_msg.stat().st_size!=len(raw):
                archived_msg.write_bytes(raw)
            saved=[]
            for n,att in enumerate(getattr(msg,'attachments',[]) or [],1):
                name=str(getattr(att,'longFilename',None) or getattr(att,'shortFilename',None) or getattr(att,'name',None) or f'priloha_{n}')
                ext=Path(name).suffix.lower()
                # Images/logos from signatures are deliberately not archived.
                if ext not in MAIN_ATTACHMENT_EXTS:continue
                data=_att_bytes(att)
                if not data:continue
                out=folder/_safe_name(Path(name).name,120)
                if out.exists() and out.read_bytes()!=data:
                    out=folder/f'{out.stem}_{hashlib.sha256(data).hexdigest()[:6]}{out.suffix}'
                if not out.exists():out.write_bytes(data)
                saved.append(out)
            return folder,archived_msg,saved,subject
        finally:
            try:msg.close()
            except Exception:pass

    def _clean_value(v):
        if isinstance(v,(bytes,bytearray,memoryview)):return '[binární data]'
        if v is None:return ''
        return str(v)

    def _export_offer_excel(result,folder,archived_msg,attachments):
        try:
            import xlsxwriter
        except Exception:
            return None
        out=folder/'Extrakce_nabidky.xlsx'
        wb=xlsxwriter.Workbook(str(out))
        head=wb.add_format({'bold':True,'bg_color':'#E9EEF5','border':1})
        cell=wb.add_format({'border':1,'valign':'top'})
        wrap=wb.add_format({'border':1,'valign':'top','text_wrap':True})
        try:
            ws=wb.add_worksheet('E-mail')
            ws.set_column(0,0,24);ws.set_column(1,1,80)
            meta=[('MSG',archived_msg.name),('Složka',str(folder)),('Předmět',result.get('subject','')),('ID zprávy',result.get('message_id','')),('Počet příloh',result.get('attachments',''))]
            with M.db() as c:
                mid=result.get('message_id')
                if mid:
                    r=c.execute('SELECT * FROM offer_source_messages WHERE id=?',(mid,)).fetchone()
                    if r:
                        for k in r.keys():
                            if k not in ('body',):meta.append((k,_clean_value(r[k])))
                        if 'body' in r.keys():meta.append(('body',_clean_value(r['body'])))
            for i,(k,v) in enumerate(meta):ws.write(i,0,k,head);ws.write(i,1,v,wrap)

            ws2=wb.add_worksheet('Nabídky')
            offer_ids=[x.get('offer_id') for x in (result.get('offers') or []) if isinstance(x,dict) and x.get('offer_id')]
            with M.db() as c:
                cols=[r[1] for r in c.execute('PRAGMA table_info(supplier_offers)').fetchall()]
                export_cols=[x for x in cols if not any(t in x.lower() for t in ('blob','image'))]
                for j,n in enumerate(export_cols):ws2.write(0,j,n,head)
                rr=1
                for oid in offer_ids:
                    row=c.execute('SELECT * FROM supplier_offers WHERE id=?',(oid,)).fetchone()
                    if not row:continue
                    for j,n in enumerate(export_cols):ws2.write(rr,j,_clean_value(row[n]),cell)
                    rr+=1
                ws2.autofilter(0,0,max(0,rr-1),max(0,len(export_cols)-1));ws2.freeze_panes(1,0)
                for j in range(len(export_cols)):ws2.set_column(j,j,18)

                ws3=wb.add_worksheet('Položky')
                icols=[r[1] for r in c.execute('PRAGMA table_info(supplier_offer_items)').fetchall()]
                iex=[x for x in icols if not any(t in x.lower() for t in ('blob','image'))]
                for j,n in enumerate(iex):ws3.write(0,j,n,head)
                rr=1
                for oid in offer_ids:
                    rows=c.execute('SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id',(oid,)).fetchall()
                    for row in rows:
                        for j,n in enumerate(iex):ws3.write(rr,j,_clean_value(row[n]),wrap if n in ('original_name','name','description') else cell)
                        rr+=1
                ws3.autofilter(0,0,max(0,rr-1),max(0,len(iex)-1));ws3.freeze_panes(1,0)
                for j in range(len(iex)):ws3.set_column(j,j,18)

            ws4=wb.add_worksheet('Soubory')
            ws4.write(0,0,'Soubor',head);ws4.write(0,1,'Typ',head)
            files=[(archived_msg.name,'MSG')]+[(p.name,p.suffix.lower().lstrip('.').upper()) for p in attachments]
            for i,(n,t) in enumerate(files,1):ws4.write(i,0,n,cell);ws4.write(i,1,t,cell)
            ws4.set_column(0,0,70);ws4.set_column(1,1,14)
        finally:
            wb.close()
        return out

    old_process_msg=getattr(M,'process_offer_msg',None)
    if callable(old_process_msg):
        def process_offer_msg_archived(app,path):
            folder=archived_msg=attachments=None
            try:folder,archived_msg,attachments,subject=_archive_msg(path)
            except Exception:
                folder=archived_msg=attachments=None
            result=old_process_msg(app,path)
            if isinstance(result,dict) and folder and archived_msg:
                try:
                    with M.db() as c:
                        if result.get('message_id'):
                            c.execute('UPDATE offer_source_messages SET source_path=? WHERE id=?',(str(archived_msg),result['message_id']))
                    _export_offer_excel(result,folder,archived_msg,attachments or [])
                    result['archive_folder']=str(folder);result['archive_msg']=str(archived_msg)
                except Exception as e:
                    result.setdefault('errors',[]).append('Archiv/Excel: '+str(e))
            return result
        M.process_offer_msg=process_offer_msg_archived

        def import_offer_sources_archived(self):
            from tkinter import filedialog,messagebox
            paths=filedialog.askopenfilenames(parent=self,title='Importovat cenové nabídky',filetypes=[('Nabídky / e-maily','*.pdf *.msg'),('PDF','*.pdf'),('Outlook zprávy','*.msg'),('Všechny soubory','*.*')])
            if not paths:return
            ok=[];errors=[];msg_count=0;att_count=0;archives=[]
            for p in paths:
                try:
                    if str(p).lower().endswith('.msg'):
                        r=M.process_offer_msg(self,p);msg_count+=1;att_count+=int((r or {}).get('attachments') or 0);ok.extend((r or {}).get('offers') or [])
                        if (r or {}).get('archive_folder'):archives.append((r or {}).get('archive_folder'))
                        errors.extend((r or {}).get('errors') or [])
                        for x in (r or {}).get('results') or []:
                            if isinstance(x,dict) and x.get('error'):errors.append(x['error'])
                    elif str(p).lower().endswith('.pdf'):ok.append(M.process_offer_pdf(self,p))
                    else:errors.append(f'{Path(p).name}: nepodporovaný vstupní formát')
                except Exception as e:errors.append(f'{Path(p).name}: {e}')
            try:self.refresh_offers()
            except Exception:pass
            text=f'Import dokončen.\n\nNabídky: {len(ok)}\nMSG: {msg_count}\nPřílohy v MSG: {att_count}'
            if archives:text+='\nArchivováno do Dokumenty\\TURTO Zakazky\\Nabidky'
            if errors:text+='\n\nChyby / nerozpoznané: '+str(len(errors))+'\n'+'\n'.join(errors[:12])
            messagebox.showinfo('Zpracování cenových nabídek',text,parent=self)
        M.App.import_offer_sources=import_offer_sources_archived

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.update_idletasks();normalize_all(self);self.update_idletasks();normalize_all(self)
        except Exception:pass
        return r
    M.App.__init__=init
