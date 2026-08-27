# TURTO CRM 6.0.33 compatibility - editable offer assignment only


def apply(M):
    # Historical offer-link editor is kept because later compatibility layers
    # build on its persistent "Změnit přiřazení…" control. Deadline overlays
    # were removed completely in v6.0.39: they caused white cell backgrounds,
    # flicker during scrolling and interference with Treeview headings.
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
        for r in reqs:rt.insert('','end',iid=str(r['id']),values=(r['item'] or '',r['company'] or '',M.fmt_date(r['asked_date']),r['action_name'] or ''))
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
        def save_action():
            s=at.selection()
            if not s:return M.messagebox.showinfo('Vazba nabídky','Vyberte Akci / Příležitost.',parent=d)
            aid=int(s[0])
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=? WHERE id=?',(aid,offer_id))
            d.destroy();refresh_all()
        def unlink():
            with M.db() as c:c.execute('UPDATE supplier_offers SET request_id=NULL,action_id=NULL WHERE id=?',(offer_id,))
            d.destroy();refresh_all()
        rt.bind('<Double-1>',lambda e:save_request());at.bind('<Double-1>',lambda e:save_action())
        b=M.ttk.Frame(f);b.pack(fill='x',pady=(10,0))
        M.ttk.Button(b,text='Odpojit vazbu',command=unlink).pack(side='left')
        M.ttk.Button(b,text='Zrušit',command=d.destroy).pack(side='right')
        M.ttk.Button(b,text='Přiřadit k Akci',style='Toolbar.TButton',command=save_action).pack(side='right',padx=6)
        M.ttk.Button(b,text='Přiřadit k Poptávce',style='Accent.TButton',command=save_request).pack(side='right')
        d.wait_window()
    M.edit_offer_links=edit_offer_links

    try:
        import crm_features as F
        D=F.OfferDetailDialog;old_build=D._build
        def build(self):
            r=old_build(self)
            try:
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
