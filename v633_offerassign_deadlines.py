# TURTO CRM 6.0.33 - editable offer assignment + clean deadline warnings
import datetime


def apply(M):
    # ------------------------------------------------------------------
    # 1) OFFER LINK EDITOR
    # Primary relation is Request -> Action. Direct Action is allowed as a
    # fallback when there is no matching Request. Existing links can be changed
    # or removed at any time from Offer detail.
    # ------------------------------------------------------------------
    def edit_offer_links(app, offer_id, parent=None):
        host=parent or app
        with M.db() as c:
            offer=c.execute('SELECT id,request_id,action_id FROM supplier_offers WHERE id=?',(offer_id,)).fetchone()
            if not offer:return
            reqs=c.execute('''SELECT r.id,r.item,r.asked_date,r.action_id,coalesce(a.name,'') action_name,
                              coalesce(co.official_name,'') company
                              FROM requests r
                              LEFT JOIN actions a ON a.id=r.action_id
                              LEFT JOIN companies co ON co.id=r.company_id
                              WHERE coalesce(r.archived,0)=0
                              ORDER BY r.id DESC LIMIT 1000''').fetchall()
            actions=c.execute("SELECT id,name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY name COLLATE CZECH,id DESC").fetchall()
        d=M.tk.Toplevel(host);d.title('Vazba nabídky');M.enable_dialog_maximize(d,1080,720);d.transient(host);d.grab_set()
        f=M.ttk.Frame(d,padding=14);f.pack(fill='both',expand=True)
        M.ttk.Label(f,text='Přiřazení nabídky',style='PageTitle.TLabel').pack(anchor='w')
        M.ttk.Label(f,text='Preferovaná vazba je na Poptávku; Akce se z ní doplní automaticky. Přímou Akci použijte jen pokud Poptávka neexistuje.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,10))
        nb=M.ttk.Notebook(f);nb.pack(fill='both',expand=True)
        rf=M.ttk.Frame(nb,padding=10);af=M.ttk.Frame(nb,padding=10);nb.add(rf,text='Poptávka');nb.add(af,text='Akce / Příležitost')
        rcols=('Poptáváno','Společnost','Datum','Akce')
        rt=M.ttk.Treeview(rf,columns=rcols,show='headings')
        for col,w in zip(rcols,(300,230,100,300)):rt.heading(col,text=col);rt.column(col,width=w,anchor='w')
        rt.pack(fill='both',expand=True)
        for r in reqs:
            rt.insert('','end',iid=str(r['id']),values=(r['item'] or '',r['company'] or '',M.fmt_date(r['asked_date']),r['action_name'] or ''))
        if offer['request_id'] and rt.exists(str(offer['request_id'])):
            rt.selection_set(str(offer['request_id']));rt.focus(str(offer['request_id']));rt.see(str(offer['request_id']))
        acols=('Akce / Příležitost',)
        at=M.ttk.Treeview(af,columns=acols,show='headings');at.heading(acols[0],text=acols[0]);at.column(acols[0],width=760,anchor='w');at.pack(fill='both',expand=True)
        for a in actions:at.insert('','end',iid=str(a['id']),values=(a['name'],))
        if offer['action_id'] and at.exists(str(offer['action_id'])):
            at.selection_set(str(offer['action_id']));at.focus(str(offer['action_id']));at.see(str(offer['action_id']))
        def refresh_all():
            for name in ('refresh_offers','refresh_requests','refresh_actions','refresh_dash','refresh_all'):
                try:
                    fn=getattr(app,name,None)
                    if callable(fn):fn()
                except Exception:pass
        def save_request():
            s=rt.selection()
            if not s:return M.messagebox.showinfo('Vazba nabídky','Vyberte Poptávku.',parent=d)
            rid=int(s[0])
            with M.db() as c:
                r=c.execute('SELECT action_id FROM requests WHERE id=?',(rid,)).fetchone();aid=r['action_id'] if r else None
                c.execute('UPDATE supplier_offers SET request_id=?,action_id=? WHERE id=?',(rid,aid,offer_id))
            d.destroy();refresh_all()
            try:
                if parent and hasattr(parent,'_build'):parent._build()
            except Exception:pass
        def save_action():
            s=at.selection()
            if not s:return M.messagebox.showinfo('Vazba nabídky','Vyberte Akci / Příležitost.',parent=d)
            aid=int(s[0])
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=? WHERE id=?',(aid,offer_id))
            d.destroy();refresh_all()
            try:
                if parent and hasattr(parent,'_build'):parent._build()
            except Exception:pass
        def unlink():
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=NULL WHERE id=?',(offer_id,))
            d.destroy();refresh_all()
            try:
                if parent and hasattr(parent,'_build'):parent._build()
            except Exception:pass
        rt.bind('<Double-1>',lambda e:save_request());at.bind('<Double-1>',lambda e:save_action())
        b=M.ttk.Frame(f);b.pack(fill='x',pady=(10,0))
        M.ttk.Button(b,text='Odpojit vazbu',command=unlink).pack(side='left')
        M.ttk.Button(b,text='Zrušit',command=d.destroy).pack(side='right')
        M.ttk.Button(b,text='Přiřadit k Akci',style='Toolbar.TButton',command=save_action).pack(side='right',padx=6)
        M.ttk.Button(b,text='Přiřadit k Poptávce',style='Accent.TButton',command=save_request).pack(side='right')
        d.wait_window()
    M.edit_offer_links=edit_offer_links

    # Add one persistent control after all older OfferDetail patches. Do not hide
    # either business option; this editor supports create/change/unlink.
    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_build=D._build
        def build(self):
            r=old_build(self)
            try:
                # Remove older request-link buttons to avoid two different editors.
                def walk(w):
                    for c in list(w.winfo_children()):
                        try:
                            txt=str(c.cget('text')).strip() if c.winfo_class().endswith('Button') else ''
                            if txt.startswith('Přiřadit k Poptávce') or txt.startswith('Přiřadit k Akci'):
                                c.destroy();continue
                        except Exception:pass
                        walk(c)
                walk(self.f)
                with M.db() as c:
                    x=c.execute('''SELECT o.request_id,o.action_id,coalesce(r.item,'') request_item,
                                   coalesce(a.name,'') action_name
                                   FROM supplier_offers o LEFT JOIN requests r ON r.id=o.request_id
                                   LEFT JOIN actions a ON a.id=coalesce(r.action_id,o.action_id)
                                   WHERE o.id=?''',(self.oid,)).fetchone()
                panel=M.ttk.Frame(self.f,style='Panel.TFrame',padding=(10,7));panel.pack(fill='x',pady=(4,6),before=self.f.winfo_children()[1] if len(self.f.winfo_children())>1 else None)
                text='Vazba: '
                if x and x['request_id']:text+=f"Poptávka: {x['request_item'] or '#'+str(x['request_id'])}  •  Akce: {x['action_name'] or '—'}"
                elif x and x['action_id']:text+=f"Akce: {x['action_name'] or '#'+str(x['action_id'])}  •  bez Poptávky"
                else:text+='nepřiřazeno'
                M.ttk.Label(panel,text=text,style='PageSubtitle.TLabel').pack(side='left',fill='x',expand=True)
                M.ttk.Button(panel,text='Změnit přiřazení…',style='Accent.TButton',command=lambda:edit_offer_links(self.parent_app,self.oid,self)).pack(side='right')
            except Exception:pass
            return r
        D._build=build
    except Exception:pass

    # ------------------------------------------------------------------
    # 2) DEADLINE WARNING WITHOUT TRIANGLE
    # Treeview cannot style one cell with tags, so draw a red bold date overlay
    # exactly over the deadline cell. The row itself keeps its normal status color.
    # ------------------------------------------------------------------
    def _clean_warning_text(tree):
        try:
            for iid in tree.get_children():
                vals=list(tree.item(iid,'values'))
                changed=False
                for i,v in enumerate(vals):
                    s=str(v or '')
                    clean=s.replace('⚠','').replace('⚠️','').strip()
                    if clean!=s:vals[i]=clean;changed=True
                if changed:tree.item(iid,values=vals)
        except Exception:pass

    def _deadline_column(tree):
        try:
            cols=list(tree.cget('columns'))
            preferred=('Termín','Deadline','Do data','Datum','Poptáno')
            for p in preferred:
                if p in cols:return p
            for c in cols:
                low=str(c).casefold()
                if 'term' in low or 'dead' in low:return c
        except Exception:pass
        return None

    def _parse_date(s):
        raw=str(s or '').replace('⚠','').replace('⚠️','').strip()
        for fmt in ('%d.%m.%Y','%Y-%m-%d'):
            try:return datetime.datetime.strptime(raw,fmt).date(),raw
            except Exception:pass
        return None,raw

    def _urgent_for_row(tree,iid,col):
        try:
            dt,raw=_parse_date(tree.set(iid,col))
            if not dt:return False,raw
            vals=' '.join(str(x or '') for x in tree.item(iid,'values')).casefold()
            if any(x in vals for x in ('hotovo','zrušeno','archiv','obdrž')):return False,raw
            today=datetime.date.today()
            # Future deadlines: today or within 3 days. For request waiting dates,
            # old unanswered records remain urgent after 3 days as in prior logic.
            if col=='Poptáno':return (today-dt).days>3,raw
            return dt<=today+datetime.timedelta(days=3),raw
        except Exception:return False,''

    def _install_deadline_overlay(app,tree):
        if tree is None:return
        try:
            old=getattr(tree,'_v633_deadline_labels',[])
            for lab in old:
                try:lab.destroy()
                except Exception:pass
            tree._v633_deadline_labels=[]
            _clean_warning_text(tree)
            col=_deadline_column(tree)
            if not col:return
            try:idx=list(tree.cget('columns')).index(col)+1
            except Exception:return
            def redraw(*_):
                for lab in list(getattr(tree,'_v633_deadline_labels',[])):
                    try:lab.destroy()
                    except Exception:pass
                tree._v633_deadline_labels=[]
                try:
                    fg='#ff5a5f' if 'tmav' in str(app.theme.get() or '').casefold() else '#c62828'
                except Exception:fg='#c62828'
                for iid in tree.get_children():
                    urgent,text=_urgent_for_row(tree,iid,col)
                    if not urgent or not text:continue
                    try:b=tree.bbox(iid,f'#{idx}')
                    except Exception:b=''
                    if not b:continue
                    x,y,w,h=b
                    lab=M.tk.Label(tree,text=text,font=('Calibri',10,'bold'),fg=fg,bg=tree.cget('background') if 'background' in tree.keys() else '#ffffff',anchor='w',bd=0,padx=2)
                    lab.place(x=x+1,y=y+1,width=max(1,w-2),height=max(1,h-2));tree._v633_deadline_labels.append(lab)
            tree.bind('<Configure>',redraw,add='+');tree.bind('<MouseWheel>',lambda e:tree.after_idle(redraw),add='+');tree.bind('<ButtonRelease-1>',lambda e:tree.after_idle(redraw),add='+')
            tree.after_idle(redraw)
        except Exception:pass

    def _apply_deadlines(app):
        # Known deadline/request tables; harmlessly skip missing ones.
        for name in ('request_tree','mivo_tree','task_tree','deadline_tree','upcoming_tree'):
            try:_install_deadline_overlay(app,getattr(app,name,None))
            except Exception:pass

    for name in ('refresh_requests','refresh_mivo_requests','refresh_tasks','refresh_dash','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:_apply_deadlines(self))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(2200,lambda:_apply_deadlines(self))
        except Exception:pass
        return r
    M.App.__init__=init
