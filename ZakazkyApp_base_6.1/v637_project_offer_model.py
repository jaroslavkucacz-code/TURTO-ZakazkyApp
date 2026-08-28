# TURTO CRM 6.0.37 - offers belong to real Actions (projects), not Opportunities
import datetime


def apply(M):
    # ------------------------------------------------------------------
    # DATA MODEL: Offer -> Request -> Opportunity -> Action(project)
    # or Offer -> Action(project) directly, or no link.
    # Historical action_id values are legacy Opportunity links and are NOT a
    # canonical assignment on their own.
    # ------------------------------------------------------------------
    try:
        with M.db() as c:
            if not M.has_column(c,'supplier_offers','project_id'):
                c.execute('ALTER TABLE supplier_offers ADD COLUMN project_id INTEGER')
            # Requests are authoritative when present.
            c.execute('''UPDATE supplier_offers
                         SET project_id=(SELECT a.project_id
                                         FROM requests r JOIN actions a ON a.id=r.action_id
                                         WHERE r.id=supplier_offers.request_id)
                         WHERE request_id IS NOT NULL
                           AND EXISTS(SELECT 1 FROM requests r JOIN actions a ON a.id=r.action_id
                                      WHERE r.id=supplier_offers.request_id AND a.project_id IS NOT NULL)''')
            # Do not migrate a bare historical action_id to project_id anymore.
            # Older imports used to auto-match the supplier reference to an
            # Opportunity name; that was not an explicit user assignment.
            c.execute('CREATE INDEX IF NOT EXISTS idx_supplier_offers_project_v637 ON supplier_offers(project_id)')
    except Exception:
        pass

    def _project_for_request(c,rid):
        if not rid:return None
        r=c.execute('''SELECT a.project_id FROM requests r
                       LEFT JOIN actions a ON a.id=r.action_id WHERE r.id=?''',(rid,)).fetchone()
        return r['project_id'] if r and r['project_id'] else None

    # The base importer historically auto-filled action_id when the parsed
    # supplier reference happened to equal an Opportunity name. Keep explicit
    # action_name calls backwards-compatible, but never create that automatic
    # relationship for ordinary parser/MSG/PDF imports.
    old_save_offer_import=getattr(M,'save_offer_import',None)
    if callable(old_save_offer_import):
        def save_offer_import(*args,**kwargs):
            explicit_action=''
            try:
                raw_action=args[3] if len(args)>3 else kwargs.get('action_name','')
                explicit_action=str(raw_action or '').strip()
            except Exception:
                explicit_action=''
            result=old_save_offer_import(*args,**kwargs)
            try:
                oid=result[0] if result else None
                created=bool(result[1]) if result and len(result)>1 else False
                if oid and created and not explicit_action:
                    with M.db() as c:
                        c.execute('''UPDATE supplier_offers
                                     SET action_id=NULL
                                     WHERE id=? AND request_id IS NULL''',(oid,))
            except Exception:
                pass
            return result
        M.save_offer_import=save_offer_import

    # ------------------------------------------------------------------
    # SEARCHABLE ASSIGNMENT: Request or real Action(project), never Opportunity.
    # ------------------------------------------------------------------
    def edit_offer_links(app,offer_id,parent=None):
        host=parent or app
        with M.db() as c:
            offer=c.execute('SELECT id,request_id,project_id,action_id FROM supplier_offers WHERE id=?',(offer_id,)).fetchone()
            if not offer:return
            reqs=[dict(r) for r in c.execute('''SELECT r.id,r.item,r.asked_date,coalesce(co.official_name,'') company,
                         coalesce(p.name,'') project_name
                         FROM requests r
                         LEFT JOIN companies co ON co.id=r.company_id
                         LEFT JOIN actions a ON a.id=r.action_id
                         LEFT JOIN projects p ON p.id=a.project_id
                         WHERE coalesce(r.archived,0)=0
                         ORDER BY r.id DESC LIMIT 2000''').fetchall()]
            projects=[dict(r) for r in c.execute('''SELECT id,name,address,investor FROM projects
                         WHERE coalesce(active,1)=1 AND trim(coalesce(name,''))<>''
                         ORDER BY name COLLATE CZECH,id''').fetchall()]

        d=M.tk.Toplevel(host);d.title('Vazba nabídky');M.enable_dialog_maximize(d,1100,720);d.transient(host);d.grab_set()
        f=M.ttk.Frame(d,padding=14);f.pack(fill='both',expand=True)
        M.ttk.Label(f,text='Přiřazení nabídky',style='PageTitle.TLabel').pack(anchor='w')
        M.ttk.Label(f,text='Dvojklikem přiřadíte nabídku k Poptávce nebo přímo k Akci. Při vazbě na Poptávku se Akce doplní automaticky.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,10))
        q=M.tk.StringVar();sr=M.ttk.Frame(f);sr.pack(fill='x',pady=(0,8));M.ttk.Label(sr,text='Hledat:').pack(side='left',padx=(0,6));entry=M.ttk.Entry(sr,textvariable=q);entry.pack(side='left',fill='x',expand=True)
        nb=M.ttk.Notebook(f);nb.pack(fill='both',expand=True)
        rf=M.ttk.Frame(nb,padding=8);pf=M.ttk.Frame(nb,padding=8);nb.add(rf,text='Poptávka');nb.add(pf,text='Akce')
        rt=M.ttk.Treeview(rf,columns=('Poptáváno','Společnost','Datum','Akce'),show='headings')
        for col,w in (('Poptáváno',300),('Společnost',230),('Datum',100),('Akce',300)):rt.heading(col,text=col);rt.column(col,width=w,anchor='w')
        rt.pack(fill='both',expand=True)
        pt=M.ttk.Treeview(pf,columns=('Akce','Adresa','Investor'),show='headings')
        for col,w in (('Akce',420),('Adresa',280),('Investor',280)):pt.heading(col,text=col);pt.column(col,width=w,anchor='w')
        pt.pack(fill='both',expand=True)
        for t in (rt,pt):
            try:t.tag_configure('current_link',font=('Calibri',10,'bold'))
            except Exception:pass
        current_rid=int(offer['request_id']) if offer['request_id'] else None
        legacy_action_link=bool(offer['action_id'] and not offer['request_id'])
        current_pid=(int(offer['project_id']) if offer['project_id'] else None) if not legacy_action_link else None
        def match(text,*parts):
            s=(text or '').strip().casefold()
            return (not s) or s in ' '.join(str(x or '') for x in parts).casefold()
        def load(*_):
            text=q.get()
            for t in (rt,pt):
                for iid in t.get_children():t.delete(iid)
            for r in sorted(reqs,key=lambda x:(0 if current_rid and int(x['id'])==current_rid else 1,-int(x['id']))):
                if not match(text,r.get('item'),r.get('company'),r.get('asked_date'),r.get('project_name')):continue
                iid=str(r['id']);tags=('current_link',) if current_rid and int(r['id'])==current_rid else ()
                rt.insert('','end',iid=iid,tags=tags,values=(r.get('item') or '',r.get('company') or '',M.fmt_date(r.get('asked_date')),r.get('project_name') or '—'))
            for p in sorted(projects,key=lambda x:(0 if current_pid and int(x['id'])==current_pid else 1,(x.get('name') or '').casefold(),int(x['id']))):
                if not match(text,p.get('name'),p.get('address'),p.get('investor')):continue
                iid=str(p['id']);tags=('current_link',) if current_pid and int(p['id'])==current_pid else ()
                pt.insert('','end',iid=iid,tags=tags,values=(p.get('name') or '',p.get('address') or '',p.get('investor') or ''))
            if current_rid and rt.exists(str(current_rid)):rt.selection_set(str(current_rid));rt.focus(str(current_rid));rt.see(str(current_rid))
            if current_pid and pt.exists(str(current_pid)):pt.selection_set(str(current_pid));pt.focus(str(current_pid));pt.see(str(current_pid))
        def refresh_all():
            for name in ('refresh_offers','refresh_requests','refresh_actions','refresh_projects','refresh_dash','refresh_all'):
                try:
                    fn=getattr(app,name,None)
                    if callable(fn):fn()
                except Exception:pass
        def finish():
            try:d.destroy()
            except Exception:pass
            refresh_all()
            try:
                if parent and hasattr(parent,'_build'):parent._build()
            except Exception:pass
        def assign_request(e=None):
            s=rt.selection()
            if not s:return 'break'
            rid=int(s[0])
            with M.db() as c:
                pid=_project_for_request(c,rid)
                c.execute('UPDATE supplier_offers SET request_id=?,project_id=?,action_id=NULL WHERE id=?',(rid,pid,offer_id))
            finish();return 'break'
        def assign_project(e=None):
            s=pt.selection()
            if not s:return 'break'
            pid=int(s[0])
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,project_id=?,action_id=NULL WHERE id=?',(pid,offer_id))
            finish();return 'break'
        def unlink():
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,project_id=NULL,action_id=NULL WHERE id=?',(offer_id,))
            finish()
        rt.bind('<Double-1>',assign_request);pt.bind('<Double-1>',assign_project);q.trace_add('write',load)
        foot=M.ttk.Frame(f);foot.pack(fill='x',pady=(10,0));M.ttk.Button(foot,text='Odebrat vazby',style='Toolbar.TButton',command=unlink).pack(side='left');M.ttk.Button(foot,text='Zrušit',command=d.destroy).pack(side='right')
        load();entry.focus_set();d.wait_window()
    M.edit_offer_links=edit_offer_links

    # Correct Offer detail binding/header to show the real Action and never overwrite
    # the source reference/title parsed from the document.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_build=D._build
        def build(self):
            r=old_build(self)
            try:
                with M.db() as c:
                    x=c.execute('''SELECT o.request_id,o.project_id,o.action_id,coalesce(o.reference,'') source_title,
                              CASE
                                WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                                WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                                ELSE ''
                              END project_name,
                              coalesce(rq.item,'') request_item
                              FROM supplier_offers o
                              LEFT JOIN requests rq ON rq.id=o.request_id
                              LEFT JOIN actions ra ON ra.id=rq.action_id
                              LEFT JOIN projects pr ON pr.id=ra.project_id
                              LEFT JOIN projects pd ON pd.id=o.project_id
                              WHERE o.id=?''',(self.oid,)).fetchone()
                def walk(w):
                    for child in w.winfo_children():
                        try:
                            if child.winfo_class().endswith('Button') and str(child.cget('text')).strip()=='Změnit přiřazení…':
                                child.configure(command=lambda:edit_offer_links(self.parent_app,self.oid,self))
                            if child.winfo_class().endswith('Label'):
                                txt=str(child.cget('text'))
                                if txt.startswith('Vazba:'):
                                    rel='Vazba: '
                                    if x and x['request_id']:rel+=f"Poptávka: {x['request_item'] or '#'+str(x['request_id'])}  •  Akce: {x['project_name'] or '—'}"
                                    elif x and x['project_name']:rel+=f"Akce: {x['project_name']}  •  bez Poptávky"
                                    else:rel+='nepřiřazeno'
                                    child.configure(text=rel)
                                elif txt.startswith('Akce:') and '|' in txt:
                                    rest=txt.split('|',1)[1]
                                    child.configure(text=f"Akce: {(x['project_name'] if x else '') or '—'}   |{rest}")
                        except Exception:pass
                        walk(child)
                walk(self.f)
            except Exception:pass
            return r
        D._build=build
    except Exception:pass

    # ------------------------------------------------------------------
    # ACTIONS(projects) MAIN TABLE: show offers here, remove from Opportunities.
    # ------------------------------------------------------------------
    def _remove_offer_col_from_opportunities(app):
        t=getattr(app,'action_tree',None)
        if t is None:return
        try:
            cols=[c for c in list(t.cget('columns')) if c!='Nabídky']
            if tuple(cols)!=tuple(t.cget('columns')):t.configure(columns=tuple(cols))
        except Exception:pass

    def _project_offer_counts():
        try:
            with M.db() as c:
                rows=c.execute('''SELECT p.id,count(DISTINCT o.id) n
                    FROM projects p
                    LEFT JOIN supplier_offers o ON
                        (o.request_id IS NULL AND o.action_id IS NULL AND o.project_id=p.id)
                        OR o.request_id IN (SELECT r.id FROM requests r JOIN actions a ON a.id=r.action_id WHERE a.project_id=p.id)
                    GROUP BY p.id''').fetchall()
            return {int(r['id']):int(r['n']) for r in rows}
        except Exception:return {}

    def _add_project_offer_column(app):
        t=getattr(app,'project_tree',None)
        if t is None:return
        try:
            cols=list(t.cget('columns'))
            if 'Nabídky' not in cols:
                cols.append('Nabídky');t.configure(columns=tuple(cols));t.heading('Nabídky',text='Nabídky');t.column('Nabídky',width=82,minwidth=70,anchor='center',stretch=False)
            counts=_project_offer_counts()
            for iid in t.get_children():
                try:pid=int(str(iid).lstrip('pP'));t.set(iid,'Nabídky',str(counts.get(pid,0)))
                except Exception:pass
        except Exception:pass

    for name in ('refresh_actions','refresh_projects','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:
                    self.after_idle(lambda:(_remove_offer_col_from_opportunities(self),_add_project_offer_column(self)))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    # ------------------------------------------------------------------
    # REAL ACTION DETAIL (ProjectDialog): related offers.
    # ------------------------------------------------------------------
    try:
        P=M.ProjectDialog;old_pinit=P.__init__
        def pinit(self,parent,pid=None,*a,**k):
            old_pinit(self,parent,pid,*a,**k)
            if not pid:return
            try:
                # Find inner scrollable frame by locating the "Název Akce" label.
                target=None
                def scan(w):
                    nonlocal target
                    for c in w.winfo_children():
                        try:
                            if c.winfo_class().endswith('Label') and str(c.cget('text'))=='Název Akce':target=c.master;return
                        except Exception:pass
                        scan(c)
                        if target:return
                scan(self)
                if target is None:return
                maxrow=0;button_frames=[]
                for c in target.winfo_children():
                    try:
                        gi=c.grid_info()
                        if gi:maxrow=max(maxrow,int(gi.get('row',0)))
                        texts=[]
                        for b in c.winfo_children():
                            try:texts.append(str(b.cget('text')))
                            except Exception:pass
                        if 'Uložit' in texts or 'Zrušit' in texts:button_frames.append(c)
                    except Exception:pass
                row=maxrow
                for bf in button_frames:bf.grid_configure(row=row+1)
                box=M.ttk.LabelFrame(target,text='Související nabídky',padding=8);box.grid(row=row,column=0,columnspan=2,sticky='nsew',pady=(8,8))
                cols=('Dodavatel','Číslo nabídky','Datum','Název z nabídky','Poptávka','Celkem','Měna')
                t=M.ttk.Treeview(box,columns=cols,show='headings',height=6)
                for col,w in zip(cols,(190,130,95,280,240,110,65)):t.heading(col,text=col);t.column(col,width=w,anchor='w')
                t.pack(fill='both',expand=True);ids={}
                with M.db() as c:
                    data=c.execute('''SELECT DISTINCT o.id,o.offer_number,o.offer_date,o.total_value,o.currency,
                         coalesce(s.official_name,o.supplier_name,'') supplier,coalesce(o.reference,'') source_title,
                         coalesce(r.item,'') request_item
                         FROM supplier_offers o
                         LEFT JOIN companies s ON s.id=o.supplier_company_id
                         LEFT JOIN requests r ON r.id=o.request_id
                         WHERE (o.request_id IS NULL AND o.action_id IS NULL AND o.project_id=?) OR o.request_id IN
                           (SELECT rr.id FROM requests rr JOIN actions a ON a.id=rr.action_id WHERE a.project_id=?)
                         ORDER BY o.offer_date DESC,o.id DESC''',(pid,pid)).fetchall()
                for x in data:
                    iid=f"o{x['id']}";ids[iid]=int(x['id']);t.insert('','end',iid=iid,values=(x['supplier'] or '—',x['offer_number'] or '—',M.fmt_date(x['offer_date']),x['source_title'] or '—',x['request_item'] or '—',f"{float(x['total_value'] or 0):,.2f}",x['currency'] or 'CZK'))
                def open_offer(e=None):
                    s=t.selection()
                    if not s:return
                    oid=ids.get(s[0])
                    if not oid:return
                    try:
                        import crm_features as F
                        d=F.OfferDetailDialog(self,oid);self.wait_window(d)
                    except Exception as ex:M.messagebox.showerror('Nabídky',str(ex),parent=self)
                M.bind_row_double_click(t,open_offer)
                ff=M.ttk.Frame(box);ff.pack(fill='x',pady=(6,0));M.ttk.Label(ff,text=f'Nabídky: {len(data)}',style='PageSubtitle.TLabel').pack(side='left');M.ttk.Button(ff,text='Otevřít nabídku',style='Toolbar.TButton',command=open_offer).pack(side='right')
                target.rowconfigure(row,weight=1)
            except Exception:pass
        P.__init__=pinit
    except Exception:pass

    # ------------------------------------------------------------------
    # DEADLINES: kill floating labels and use a native row tag instead.
    # Native Treeview cannot draw a per-row border, so urgent waiting rows use
    # red bold text while preserving the existing blue/green status background.
    # ------------------------------------------------------------------
    def _kill_labels(tree):
        try:
            for lab in list(getattr(tree,'_v633_deadline_labels',[]) or []):
                try:lab.destroy()
                except Exception:pass
            tree._v633_deadline_labels=[]
            tree.configure(show='headings')
        except Exception:pass

    def _style_urgent_requests(app):
        t=getattr(app,'request_tree',None)
        if t is None:return
        _kill_labels(t)
        try:t.tag_configure('deadline_urgent',foreground='#c62828',font=('Calibri',10,'bold'))
        except Exception:pass
        today=datetime.date.today()
        try:
            for iid in t.get_children():
                vals=t.item(iid,'values');tags=[x for x in (t.item(iid,'tags') or ()) if x!='deadline_urgent']
                status=str(vals[0] if vals else '').casefold()
                raw=str(vals[2] if len(vals)>2 else '').strip()
                urgent=False
                if 'ček' in status:
                    try:urgent=(today-datetime.datetime.strptime(raw,'%d.%m.%Y').date()).days>3
                    except Exception:pass
                if urgent:tags.append('deadline_urgent')
                t.item(iid,tags=tuple(tags))
        except Exception:pass

    def _install_cleanup_events(app):
        t=getattr(app,'request_tree',None)
        if t is None or getattr(t,'_v637_cleanup',False):return
        t._v637_cleanup=True
        for seq in ('<Configure>','<MouseWheel>','<ButtonRelease-1>'):
            try:t.bind(seq,lambda e,tr=t:tr.after_idle(lambda:(_kill_labels(tr),_style_urgent_requests(app))),add='+')
            except Exception:pass

    for name in ('refresh_requests','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make2(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                for ms in (0,20,120,350):
                    try:self.after(ms,lambda s=self:(_style_urgent_requests(s),_install_cleanup_events(s)))
                    except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make2(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        def later():
            _remove_offer_col_from_opportunities(self);_add_project_offer_column(self);_style_urgent_requests(self);_install_cleanup_events(self)
        try:self.after(3200,later)
        except Exception:pass
        return r
    M.App.__init__=init
