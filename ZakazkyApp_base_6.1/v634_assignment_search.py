# TURTO CRM 6.0.34 - searchable offer assignment + current link first + exact row bg
import datetime


def apply(M):
    # ------------------------------------------------------------------
    # SEARCHABLE OFFER ASSIGNMENT
    # Business relation is only to Request or Action. Opportunity is not a
    # direct offer target. Double-click assigns immediately.
    # ------------------------------------------------------------------
    def edit_offer_links(app, offer_id, parent=None):
        host=parent or app
        with M.db() as c:
            offer=c.execute('SELECT id,request_id,action_id FROM supplier_offers WHERE id=?',(offer_id,)).fetchone()
            if not offer:return
            reqs=[dict(r) for r in c.execute('''SELECT r.id,r.item,r.asked_date,r.action_id,
                          coalesce(a.name,'') action_name,coalesce(co.official_name,'') company
                          FROM requests r
                          LEFT JOIN actions a ON a.id=r.action_id
                          LEFT JOIN companies co ON co.id=r.company_id
                          WHERE coalesce(r.archived,0)=0
                          ORDER BY r.id DESC LIMIT 1500''').fetchall()]
            actions=[dict(r) for r in c.execute("SELECT id,name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY name COLLATE CZECH,id DESC").fetchall()]

        d=M.tk.Toplevel(host);d.title('Vazba nabídky');M.enable_dialog_maximize(d,1080,720);d.transient(host);d.grab_set()
        f=M.ttk.Frame(d,padding=14);f.pack(fill='both',expand=True)
        M.ttk.Label(f,text='Přiřazení nabídky',style='PageTitle.TLabel').pack(anchor='w')
        M.ttk.Label(f,text='Dvojklikem přiřadíte nabídku k Poptávce nebo přímo k Akci. Přiřazená položka je zvýrazněná a zobrazuje se vždy nahoře.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,10))

        search=M.tk.StringVar()
        sr=M.ttk.Frame(f);sr.pack(fill='x',pady=(0,8))
        M.ttk.Label(sr,text='Hledat:').pack(side='left',padx=(0,6))
        se=M.ttk.Entry(sr,textvariable=search);se.pack(side='left',fill='x',expand=True)

        nb=M.ttk.Notebook(f);nb.pack(fill='both',expand=True)
        rf=M.ttk.Frame(nb,padding=8);af=M.ttk.Frame(nb,padding=8);nb.add(rf,text='Poptávka');nb.add(af,text='Akce')

        rcols=('Poptáváno','Společnost','Datum','Akce')
        rt=M.ttk.Treeview(rf,columns=rcols,show='headings')
        for col,w in zip(rcols,(300,230,100,300)):rt.heading(col,text=col);rt.column(col,width=w,anchor='w')
        rt.pack(fill='both',expand=True)
        acols=('Akce',)
        at=M.ttk.Treeview(af,columns=acols,show='headings');at.heading('Akce',text='Akce');at.column('Akce',width=850,anchor='w');at.pack(fill='both',expand=True)

        # Current link tag must remain visible in both themes.
        try:
            rt.tag_configure('current_link',font=('Calibri',10,'bold'))
            at.tag_configure('current_link',font=('Calibri',10,'bold'))
        except Exception:pass

        current_rid=int(offer['request_id']) if offer['request_id'] else None
        current_aid=int(offer['action_id']) if offer['action_id'] else None

        def match(q,*parts):
            q=(q or '').strip().casefold()
            if not q:return True
            return q in ' '.join(str(x or '') for x in parts).casefold()

        def load_lists(*_):
            q=search.get()
            for t in (rt,at):
                for iid in t.get_children():t.delete(iid)
            # Current request first, then others.
            rr=sorted(reqs,key=lambda r:(0 if current_rid and int(r['id'])==current_rid else 1,-int(r['id'])))
            for r in rr:
                if not match(q,r.get('item'),r.get('company'),r.get('asked_date'),r.get('action_name')):continue
                iid=str(r['id']);tags=('current_link',) if current_rid and int(r['id'])==current_rid else ()
                rt.insert('','end',iid=iid,tags=tags,values=(r.get('item') or '',r.get('company') or '',M.fmt_date(r.get('asked_date')),r.get('action_name') or ''))
            # Current direct/derived action first, then alphabetical.
            aa=sorted(actions,key=lambda a:(0 if current_aid and int(a['id'])==current_aid else 1,(a.get('name') or '').casefold(),int(a['id'])))
            for a in aa:
                if not match(q,a.get('name')):continue
                iid=str(a['id']);tags=('current_link',) if current_aid and int(a['id'])==current_aid else ()
                at.insert('','end',iid=iid,tags=tags,values=(a.get('name') or '',))
            # Keep current link visibly selected if it survived filtering.
            if current_rid and rt.exists(str(current_rid)):
                rt.selection_set(str(current_rid));rt.focus(str(current_rid));rt.see(str(current_rid))
            if current_aid and at.exists(str(current_aid)):
                at.selection_set(str(current_aid));at.focus(str(current_aid));at.see(str(current_aid))
        search.trace_add('write',load_lists)

        def refresh_all():
            for name in ('refresh_offers','refresh_requests','refresh_actions','refresh_dash','refresh_all'):
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

        def assign_request(event=None):
            s=rt.selection()
            if not s:return 'break'
            rid=int(s[0])
            with M.db() as c:
                r=c.execute('SELECT action_id FROM requests WHERE id=?',(rid,)).fetchone();aid=r['action_id'] if r else None
                c.execute('UPDATE supplier_offers SET request_id=?,action_id=? WHERE id=?',(rid,aid,offer_id))
            finish();return 'break'

        def assign_action(event=None):
            s=at.selection()
            if not s:return 'break'
            aid=int(s[0])
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=? WHERE id=?',(aid,offer_id))
            finish();return 'break'

        def unlink():
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=NULL WHERE id=?',(offer_id,))
            finish()

        rt.bind('<Double-1>',assign_request);at.bind('<Double-1>',assign_action)
        b=M.ttk.Frame(f);b.pack(fill='x',pady=(10,0))
        M.ttk.Button(b,text='Odebrat vazby',style='Toolbar.TButton',command=unlink).pack(side='left')
        M.ttk.Button(b,text='Zrušit',command=d.destroy).pack(side='right')
        load_lists();se.focus_set();d.wait_window()
    M.edit_offer_links=edit_offer_links

    # Replace button command in OfferDetail created by v6.0.33 while preserving
    # the rest of its UI.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_build=D._build
        def build(self):
            r=old_build(self)
            try:
                def walk(w):
                    for c in w.winfo_children():
                        try:
                            if c.winfo_class().endswith('Button') and str(c.cget('text')).strip()=='Změnit přiřazení…':
                                c.configure(command=lambda:edit_offer_links(self.parent_app,self.oid,self))
                        except Exception:pass
                        walk(c)
                walk(self.f)
            except Exception:pass
            return r
        D._build=build
    except Exception:pass

    # ------------------------------------------------------------------
    # DEADLINE OVERLAY BACKGROUND FIX
    # Preserve the exact row status background under the red bold date.
    # ------------------------------------------------------------------
    def _row_bg(tree,iid):
        try:
            tags=tree.item(iid,'tags') or ()
            for tag in tags:
                cfg=tree.tag_configure(tag)
                bg=cfg.get('background')
                if isinstance(bg,(tuple,list)) and bg:bg=bg[-1]
                if bg:return bg
        except Exception:pass
        try:
            style=M.ttk.Style(tree);sty=tree.cget('style') or 'Treeview';bg=style.lookup(sty,'background')
            if bg:return bg
        except Exception:pass
        try:return tree.cget('background')
        except Exception:return '#ffffff'

    # Patch labels produced by v6.0.33 after each refresh/resize.
    def _repair_deadline_labels(app):
        for name in ('request_tree','mivo_tree','task_tree','deadline_tree','upcoming_tree'):
            tree=getattr(app,name,None)
            if tree is None:continue
            try:
                labels=list(getattr(tree,'_v633_deadline_labels',[]) or [])
                for lab in labels:
                    try:
                        y=lab.winfo_y()+max(1,lab.winfo_height()//2)
                        iid=tree.identify_row(y)
                        if iid:lab.configure(bg=_row_bg(tree,iid))
                    except Exception:pass
            except Exception:pass

    for name in ('refresh_requests','refresh_mivo_requests','refresh_tasks','refresh_dash','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:_repair_deadline_labels(self))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(2600,lambda:_repair_deadline_labels(self))
        except Exception:pass
        return r
    M.App.__init__=init
