# TURTO CRM 6.0.36 - action offer overview + stable request table


def apply(M):
    # 1) Remove the floating deadline labels introduced in 6.0.33.
    # They cannot scroll atomically with ttk.Treeview and caused white blocks,
    # flicker and overlap with the native headings. Keep native row colours.
    def remove_deadline_overlays(app):
        for name in ('request_tree','mivo_tree','task_tree','deadline_tree','upcoming_tree'):
            tree=getattr(app,name,None)
            if tree is None:continue
            try:
                for lab in list(getattr(tree,'_v633_deadline_labels',[]) or []):
                    try:lab.destroy()
                    except Exception:pass
                tree._v633_deadline_labels=[]
            except Exception:pass
            try:
                # Restore native headings if any older patch changed show mode.
                tree.configure(show='headings')
            except Exception:pass

    # Run after the old v633/v634 callbacks have had a chance to execute, then
    # keep the overlays disabled after refreshes. We deliberately prefer stable
    # native scrolling over per-cell red text (Treeview has no native cell tags).
    for name in ('refresh_requests','refresh_mivo_requests','refresh_tasks','refresh_dash','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:remove_deadline_overlays(self))
                except Exception:remove_deadline_overlays(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    # 2) Offer title parsed from the supplier document is independent of CRM Action.
    # Never overwrite any parsed source/title field when changing request/action links.
    # Link editors already update request_id/action_id only; keep that contract explicit.

    # 3) Add a related-offers overview directly to the existing Action detail.
    try:
        A=M.ActionDialog
        old_init=A.__init__
        def init(self,parent,aid=None,*a,**k):
            old_init(self,parent,aid,*a,**k)
            if not aid:return
            try:
                f=None
                # scrollable_dialog_frame is the only large child; find its inner frame.
                def frames(w):
                    out=[]
                    for c in w.winfo_children():
                        if c.winfo_class() in ('TFrame','Frame'):out.append(c)
                        out.extend(frames(c))
                    return out
                candidates=frames(self)
                # Locate the frame that owns the Save/Cancel buttons/history.
                for cand in candidates:
                    texts=[]
                    for c in cand.winfo_children():
                        try:
                            if c.winfo_class().endswith('Label'):texts.append(str(c.cget('text')))
                        except Exception:pass
                    if 'Akce' in texts and 'Společnost' in texts:
                        f=cand;break
                if f is None:return
                # Determine insertion row just before the bottom button bar.
                maxrow=0
                for c in f.winfo_children():
                    try:
                        gi=c.grid_info()
                        if gi:maxrow=max(maxrow,int(gi.get('row',0)))
                    except Exception:pass
                row=maxrow
                box=M.ttk.LabelFrame(f,text='Související nabídky',padding=8)
                box.grid(row=row,column=0,columnspan=2,sticky='nsew',pady=(8,8))
                cols=('Dodavatel','Číslo nabídky','Datum','Název z nabídky','Poptávka','Celkem','Měna')
                t=M.ttk.Treeview(box,columns=cols,show='headings',height=6)
                for c,w in zip(cols,(190,130,95,260,240,110,65)):
                    t.heading(c,text=c);t.column(c,width=w,anchor='w')
                t.pack(fill='both',expand=True)
                rows={}
                with M.db() as con:
                    # Detect the best source-title column without assuming one schema revision.
                    offer_cols={r[1] for r in con.execute('PRAGMA table_info(supplier_offers)').fetchall()}
                    title_col=next((x for x in ('project_name','offer_title','subject','source_title','action_name') if x in offer_cols),None)
                    title_expr=f"coalesce(o.{title_col},'')" if title_col else "''"
                    data=con.execute(f'''SELECT DISTINCT o.id,o.offer_number,o.offer_date,o.total_value,o.currency,
                        coalesce(s.official_name,o.supplier_name,'') supplier,
                        {title_expr} source_title,coalesce(r.item,'') request_item
                        FROM supplier_offers o
                        LEFT JOIN companies s ON s.id=o.supplier_company_id
                        LEFT JOIN requests r ON r.id=o.request_id
                        WHERE o.action_id=? OR o.request_id IN (SELECT id FROM requests WHERE action_id=?)
                        ORDER BY o.offer_date DESC,o.id DESC''',(aid,aid)).fetchall()
                for r in data:
                    iid=f"o{r['id']}";rows[iid]=int(r['id'])
                    t.insert('','end',iid=iid,values=(r['supplier'] or '—',r['offer_number'] or '—',M.fmt_date(r['offer_date']),r['source_title'] or '—',r['request_item'] or '—',f"{float(r['total_value'] or 0):,.2f}",r['currency'] or 'CZK'))
                if not data:
                    t.insert('','end',values=('—','—','—','K této Akci zatím není přiřazena žádná nabídka.','—','—','—'))
                def open_offer(e=None):
                    s=t.selection()
                    if not s:return
                    oid=rows.get(s[0])
                    if not oid:return
                    try:
                        import crm_features as F
                        d=F.OfferDetailDialog(self,oid);self.wait_window(d)
                    except Exception as ex:M.messagebox.showerror('Nabídky',str(ex),parent=self)
                M.bind_row_double_click(t,open_offer)
                foot=M.ttk.Frame(box);foot.pack(fill='x',pady=(6,0))
                M.ttk.Label(foot,text=f'Nabídky: {len(data)}',style='PageSubtitle.TLabel').pack(side='left')
                M.ttk.Button(foot,text='Otevřít nabídku',style='Toolbar.TButton',command=open_offer).pack(side='right')
                # Move the original bottom button frame below our new box.
                for c in f.winfo_children():
                    try:
                        gi=c.grid_info()
                        if c is not box and gi and int(gi.get('row',-1))==row:
                            # Button frame is recognizable by Uložit/Zrušit children.
                            labels=[]
                            for b in c.winfo_children():
                                try:labels.append(str(b.cget('text')))
                                except Exception:pass
                            if 'Uložit' in labels or 'Zrušit' in labels:c.grid_configure(row=row+1)
                    except Exception:pass
                f.rowconfigure(row,weight=1)
            except Exception:
                pass
        A.__init__=init
    except Exception:pass

    old_app_init=M.App.__init__
    def app_init(self,*a,**k):
        r=old_app_init(self,*a,**k)
        try:self.after(3000,lambda:remove_deadline_overlays(self))
        except Exception:pass
        return r
    M.App.__init__=app_init
