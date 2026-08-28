# TURTO CRM 6.3 active extension layer
# One active layer owns table geometry, dashboard status tagging, offer archive,
# exact supplier Excel export and DB-only offer deletion.


def apply(M):
    import re,json,hashlib,shutil
    from pathlib import Path

    # ------------------------------------------------------------------
    # Unified Treeview geometry and auxiliary redraws.
    # This is the only active owner of column fitting after startup.
    # ------------------------------------------------------------------
    COMPACT={
        'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení',
        'ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'
    }

    def display_columns(tree):
        try:
            all_cols=list(tree.cget('columns'))
            raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']:
                return all_cols
            out=[]
            for col in raw:
                if str(col).isdigit():
                    idx=int(col)
                    if 0<=idx<len(all_cols):
                        out.append(all_cols[idx])
                elif col in all_cols:
                    out.append(col)
            return out or all_cols
        except Exception:
            return []

    def fit_tree(tree,available=None):
        try:
            cols=display_columns(tree)
            if not cols:
                return
            if not hasattr(tree,'_turto_design_widths'):
                tree._turto_design_widths={
                    col:max(50,min(int(tree.column(col,'width')),500)) for col in cols
                }
            design=tree._turto_design_widths
            for col in cols:
                if col not in design:
                    design[col]=max(50,min(int(tree.column(col,'width')),500))
            width=int(available if available is not None else tree.winfo_width())
            if width<=10:
                return
            flex=[col for col in cols if str(col) not in COMPACT] or [cols[-1]]
            preferred=sum(design[col] for col in cols)
            share,rest=divmod(max(0,width-4-preferred),len(flex))
            for col in cols:
                col_width=design[col]
                if col in flex:
                    idx=flex.index(col)
                    col_width+=share+(1 if idx<rest else 0)
                tree.column(
                    col,
                    width=col_width,
                    minwidth=max(50,min(design[col],120)),
                    stretch=False,
                )
        except Exception:
            pass

    def schedule_auxiliary_redraw(tree):
        try:
            previous=getattr(tree,'_turto_aux_after',None)
            if previous is not None:
                try:tree.after_cancel(previous)
                except Exception:pass

            def finish():
                tree._turto_aux_after=None
                try:
                    fn=getattr(tree,'_sync_filter_bar',None)
                    if callable(fn):fn()
                except Exception:pass
                try:
                    fn=getattr(tree,'_date_cell_redraw',None)
                    if callable(fn):fn()
                except Exception:pass

            tree._turto_aux_after=tree.after(110,finish)
        except Exception:
            pass

    def install_tree(tree):
        try:
            if tree is None or not tree.winfo_exists():
                return
            if not getattr(tree,'_turto_layout_bound',False):
                tree._turto_layout_bound=True

                def on_configure(event,t=tree):
                    fit_tree(t,getattr(event,'width',None))
                    schedule_auxiliary_redraw(t)

                tree.bind('<Configure>',on_configure,add='+')
            if not getattr(tree,'_turto_map_bound',False):
                tree._turto_map_bound=True
                tree.bind('<Map>',lambda e,t=tree:(fit_tree(t),schedule_auxiliary_redraw(t)),add='+')
            fit_tree(tree)
        except Exception:
            pass

    def walk(widget,callback):
        try:
            for child in widget.winfo_children():
                try:callback(child)
                except Exception:pass
                walk(child,callback)
        except Exception:
            pass

    def normalize(app):
        walk(app,lambda widget:install_tree(widget) if widget.winfo_class()=='Treeview' else None)

    def reclaim_tree_layout(app):
        """Remove legacy Configure handlers installed by old runtime layers.
        The consolidated fitter is then installed once as the final owner.
        """
        def reclaim(widget):
            try:
                if widget.winfo_class()!='Treeview':
                    return
                try:widget.unbind('<Configure>')
                except Exception:pass
                widget._turto_layout_bound=False
                install_tree(widget)
                schedule_auxiliary_redraw(widget)
            except Exception:
                pass
        walk(app,reclaim)

    # ------------------------------------------------------------------
    # Exact dashboard status tagging. Colors are configured by the modern
    # palette layer; this code only selects the correct tag from the Stav cell.
    # ------------------------------------------------------------------
    STATUS_TAGS={
        'rozpracováno':'status_active','rozpracovano':'status_active',
        'připraveno':'status_offer','pripraveno':'status_offer',
        'hotovo':'status_done','zrušeno':'status_cancel','zruseno':'status_cancel',
    }

    def recolor_dashboard(app):
        try:page=getattr(app,'tabs',{}).get('dash')
        except Exception:page=None
        if page is None:
            return

        def recolor(widget):
            try:
                if widget.winfo_class()!='Treeview':
                    return
                cols=list(widget.cget('columns') or ())
                status_col=None
                for col in cols:
                    try:heading=str(widget.heading(col,'text') or '').strip().casefold()
                    except Exception:heading=str(col).strip().casefold()
                    if heading=='stav' or 'stav' in heading:
                        status_col=col
                        break
                if status_col is None:
                    return
                for iid in widget.get_children(''):
                    status=str(widget.set(iid,status_col) or '').strip().casefold()
                    tag=STATUS_TAGS.get(status)
                    if tag:
                        widget.item(iid,tags=(tag,))
            except Exception:
                pass

        recolor(page)
        walk(page,recolor)

    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*args,**kwargs):
            widget=old_tree(self,*args,**kwargs)
            install_tree(widget)
            return widget
        M.App.tree=tree

    for name in (
        'refresh_dash','refresh_dashboard','refresh_actions','refresh_requests',
        'refresh_mivo_requests','refresh_mivo','refresh_projects','refresh_offers',
        'refresh_tasks','refresh_companies','refresh_people','refresh_all'
    ):
        old=getattr(M.App,name,None)
        if not callable(old):
            continue
        def make(fn):
            def wrapped(self,*args,**kwargs):
                result=fn(self,*args,**kwargs)
                normalize(self)
                try:self.after_idle(lambda:recolor_dashboard(self))
                except Exception:recolor_dashboard(self)
                return result
            return wrapped
        setattr(M.App,name,make(old))

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*args,**kwargs):
            result=old_show(self,*args,**kwargs)
            normalize(self)
            recolor_dashboard(self)
            return result
        M.App.show_page=show_page

    # ------------------------------------------------------------------
    # Per-PC / per-user archive folder setting.
    # ------------------------------------------------------------------
    LOCAL_CFG=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'local_settings.json'
    DEFAULT_ARCHIVE=Path(getattr(M,'DATA_ROOT',Path.home()/'Documents'/'TURTO Zakazky'))/'Nabidky'
    MAIN_EXTS={
        '.pdf','.xls','.xlsx','.xlsm','.xlsb','.csv','.ods',
        '.doc','.docx','.odt','.rtf','.txt','.zip','.rar','.7z',
        '.xml','.ifc','.dwg','.dxf'
    }

    def active_user(app=None):
        try:return (app.active_user.get() or '').strip() or 'Výchozí'
        except Exception:
            try:return (M.get_setting('active_user','') or '').strip() or 'Výchozí'
            except Exception:return 'Výchozí'

    def load_cfg():
        try:return json.loads(LOCAL_CFG.read_text(encoding='utf-8')) if LOCAL_CFG.exists() else {}
        except Exception:return {}

    def save_cfg(data):
        try:
            LOCAL_CFG.parent.mkdir(parents=True,exist_ok=True)
            temp=LOCAL_CFG.with_suffix('.tmp')
            temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            temp.replace(LOCAL_CFG)
        except Exception:
            pass

    def archive_root(app=None):
        path=((load_cfg().get('offer_archive_dir_by_user') or {}).get(active_user(app)) or '').strip()
        return Path(path) if path else DEFAULT_ARCHIVE

    def set_archive_root(app,path):
        data=load_cfg()
        data.setdefault('offer_archive_dir_by_user',{})[active_user(app)]=str(Path(path))
        save_cfg(data)

    old_settings=getattr(M.App,'build_settings',None)
    if callable(old_settings):
        def build_settings(self):
            result=old_settings(self)
            try:
                from tkinter import ttk,filedialog
                page=self.tabs['settings']
                card=ttk.Frame(page,style='Panel.TFrame',padding=18)
                card.pack(fill='x',pady=(10,0))
                ttk.Label(
                    card,text='Ukládání zpracovaných nabídek',
                    style='Panel.TLabel',font=('Calibri',12,'bold')
                ).grid(row=0,column=0,columnspan=3,sticky='w')
                var=M.tk.StringVar(value=str(archive_root(self)))
                self._offer_archive_dir_var=var
                entry=ttk.Entry(card,textvariable=var)
                entry.grid(row=1,column=0,sticky='ew',padx=(0,8))
                card.columnconfigure(0,weight=1)

                def choose():
                    value=filedialog.askdirectory(parent=self,initialdir=var.get() or str(DEFAULT_ARCHIVE))
                    if value:
                        var.set(value)
                        set_archive_root(self,value)

                entry.bind('<FocusOut>',lambda e:set_archive_root(self,var.get()) if var.get().strip() else None)
                ttk.Button(card,text='Vybrat…',command=choose).grid(row=1,column=1)
            except Exception:
                pass
            return result
        M.App.build_settings=build_settings

    # ------------------------------------------------------------------
    # Exact proven supplier exporter. v624 remains the canonical workbook
    # implementation; automatic extraction invokes that same function.
    # ------------------------------------------------------------------
    try:
        import v624_legacy_exports
        v624_legacy_exports.apply(M)
    except Exception:
        pass

    manual_export=getattr(M,'export_offer_excel',None)

    def export_to_path(app,offer_id,target):
        if not callable(manual_export):
            raise RuntimeError('CRM Excel export není dostupný.')
        from tkinter import filedialog,messagebox
        target=Path(target)
        target.parent.mkdir(parents=True,exist_ok=True)
        old_save=filedialog.asksaveasfilename
        old_info=messagebox.showinfo
        old_error=messagebox.showerror
        errors=[]
        try:
            filedialog.asksaveasfilename=lambda *a,**k:str(target)
            messagebox.showinfo=lambda *a,**k:None
            messagebox.showerror=lambda title,msg,*a,**k:errors.append(str(msg))
            manual_export(app,offer_id,app)
        finally:
            filedialog.asksaveasfilename=old_save
            messagebox.showinfo=old_info
            messagebox.showerror=old_error
        if errors:
            raise RuntimeError(errors[-1])
        if not target.exists():
            raise RuntimeError('CRM export nevytvořil očekávaný soubor: '+str(target))
        return target

    M.export_offer_exactly_like_manual=export_to_path

    # ------------------------------------------------------------------
    # DB-first archive pipeline.
    # ------------------------------------------------------------------
    def safe(value,maxlen=100):
        text=re.sub(r'[<>:"/\\|?*\x00-\x1f]+','_',str(value or '')).strip(' ._')
        return (text or 'Bez_nazvu')[:maxlen]

    def folder_for(app,offer_id,path=None,subject=''):
        with M.db() as con:
            offer=con.execute(
                "SELECT offer_date,offer_number,coalesce(supplier_name,'') supplier "
                "FROM supplier_offers WHERE id=?",(offer_id,)
            ).fetchone()
        digest=''
        try:digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]
        except Exception:pass
        source_name=Path(path).stem if path else 'nabidka'
        parts=(
            ((offer['offer_date'] or '')[:10] if offer else '') or 'bez-data',
            safe(offer['supplier'] if offer else '',35),
            safe((offer['offer_number'] if offer else '') or subject or source_name,55),
            digest,
        )
        folder=archive_root(app)/'_'.join(part for part in parts if part)
        folder.mkdir(parents=True,exist_ok=True)
        return folder

    base_pdf=getattr(M,'process_offer_pdf',None)
    base_msg=getattr(M,'process_offer_msg',None)

    if callable(base_pdf):
        def process_pdf(app,path,*args,**kwargs):
            result=base_pdf(app,path,*args,**kwargs)
            if getattr(app,'_turto_inside_msg',False):
                return result
            try:
                offer_id=result.get('offer_id')
                folder=folder_for(app,offer_id,path)
                source=Path(path)
                shutil.copy2(source,folder/safe(source.name,130))
                output=folder/'Extrakce_nabidky.xlsx'
                export_to_path(app,offer_id,output)
                result.update(archive_folder=str(folder),excel_files=[str(output)])
            except Exception as exc:
                if isinstance(result,dict):result.setdefault('errors',[]).append(str(exc))
            return result
        M.process_offer_pdf=process_pdf

    if callable(base_msg):
        def process_msg(app,path,*args,**kwargs):
            app._turto_inside_msg=True
            try:result=base_msg(app,path,*args,**kwargs)
            finally:app._turto_inside_msg=False
            try:
                offers=[item for item in result.get('offers',[]) if item.get('offer_id')]
                if not offers:
                    return result
                import extract_msg
                message=extract_msg.Message(str(path))
                folder=folder_for(app,offers[0]['offer_id'],path,getattr(message,'subject',''))
                shutil.copy2(path,folder/safe(Path(path).name,130))
                for index,attachment in enumerate(getattr(message,'attachments',[]) or [],1):
                    name=str(
                        getattr(attachment,'longFilename',None)
                        or getattr(attachment,'shortFilename',None)
                        or f'priloha_{index}'
                    )
                    if Path(name).suffix.lower() not in MAIN_EXTS:
                        continue
                    data=getattr(attachment,'data',b'')
                    data=data() if callable(data) else data
                    if data:
                        (folder/safe(Path(name).name,130)).write_bytes(bytes(data))
                try:message.close()
                except Exception:pass
                outputs=[]
                for index,offer in enumerate(offers,1):
                    output=folder/(
                        'Extrakce_nabidky.xlsx'
                        if len(offers)==1 else f'Extrakce_nabidky_{index}.xlsx'
                    )
                    export_to_path(app,offer['offer_id'],output)
                    outputs.append(str(output))
                result.update(archive_folder=str(folder),excel_files=outputs)
            except Exception as exc:
                result.setdefault('errors',[]).append(str(exc))
            return result
        M.process_offer_msg=process_msg

    # ------------------------------------------------------------------
    # DB-only deletion; the physical archive remains independent.
    # ------------------------------------------------------------------
    def delete_offer(self):
        offer_id=self._selected_offer_id() if hasattr(self,'_selected_offer_id') else None
        if not offer_id:
            return
        if not M.messagebox.askyesno(
            'Nabídky',
            'Opravdu odstranit tento import nabídky z CRM?\n\nSoubory na disku zůstanou beze změny.',
            parent=self,
        ):
            return
        try:
            with M.db() as con:
                try:con.execute('UPDATE offer_source_attachments SET offer_id=NULL WHERE offer_id=?',(offer_id,))
                except Exception:pass
                con.execute('DELETE FROM supplier_offers WHERE id=?',(offer_id,))
            self.refresh_offers()
        except Exception as exc:
            M.messagebox.showerror('Nabídky',str(exc),parent=self)

    M.App.delete_offer=delete_offer

    old_init=M.App.__init__
    def init(self,*args,**kwargs):
        result=old_init(self,*args,**kwargs)
        try:
            self.update_idletasks()
            normalize(self)
            recolor_dashboard(self)
        except Exception:
            pass
        # v625 installs its historical resize handler after 500 ms. Reclaim
        # all Treeview Configure bindings afterwards so geometry has one owner.
        try:self.after(1200,lambda:reclaim_tree_layout(self))
        except Exception:pass
        return result
    M.App.__init__=init
