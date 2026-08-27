# TURTO CRM 6.0.32 - Nabidka -> Poptavka -> Akce visibility

def apply(M):
    # Keep request as the primary business link; action is derived/cache for fast queries.
    try:
        with M.db() as c:
            if not M.has_column(c, 'supplier_offers', 'request_id'):
                c.execute('ALTER TABLE supplier_offers ADD COLUMN request_id INTEGER')
            if not M.has_column(c, 'supplier_offers', 'action_id'):
                c.execute('ALTER TABLE supplier_offers ADD COLUMN action_id INTEGER')
            c.execute('''UPDATE supplier_offers
                         SET action_id=(SELECT r.action_id FROM requests r WHERE r.id=supplier_offers.request_id)
                         WHERE request_id IS NOT NULL
                           AND EXISTS(SELECT 1 FROM requests r WHERE r.id=supplier_offers.request_id)''')
            c.execute('CREATE INDEX IF NOT EXISTS idx_supplier_offers_request_v632 ON supplier_offers(request_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_supplier_offers_action_v632 ON supplier_offers(action_id)')
    except Exception:
        pass

    def _offer_count_for_request(rid):
        try:
            with M.db() as c:
                return int(c.execute('SELECT count(*) n FROM supplier_offers WHERE request_id=?',(rid,)).fetchone()['n'])
        except Exception:
            return 0

    def _offer_count_for_action(aid):
        try:
            with M.db() as c:
                return int(c.execute('''SELECT count(*) n FROM supplier_offers o
                                        WHERE o.action_id=? OR o.request_id IN
                                          (SELECT id FROM requests WHERE action_id=?)''',(aid,aid)).fetchone()['n'])
        except Exception:
            return 0

    class RelatedOffersDialog(M.tk.Toplevel):
        def __init__(self, parent, app, request_id=None, action_id=None, title='Související nabídky'):
            super().__init__(parent)
            self.app=app;self.request_id=request_id;self.action_id=action_id
            self.title(title);M.enable_dialog_maximize(self,1180,680);self.transient(parent);self.grab_set()
            f=M.ttk.Frame(self,padding=14);f.pack(fill='both',expand=True)
            M.ttk.Label(f,text=title,style='PageTitle.TLabel').pack(anchor='w')
            self.summary=M.ttk.Label(f,text='',style='PageSubtitle.TLabel');self.summary.pack(anchor='w',pady=(2,10))
            cols=('Dodavatel','Číslo nabídky','Datum','Poptávka','Akce','Celkem','Měna')
            self.tree=M.ttk.Treeview(f,columns=cols,show='headings',height=16)
            widths=(190,145,95,260,260,120,70)
            for c,w in zip(cols,widths):
                self.tree.heading(c,text=c);self.tree.column(c,width=w,anchor='w')
            self.tree.pack(fill='both',expand=True)
            self.rows={};self.load()
            M.bind_row_double_click(self.tree,lambda e:self.open_detail())
            b=M.ttk.Frame(f);b.pack(fill='x',pady=(10,0))
            M.ttk.Button(b,text='Otevřít nabídku',style='Accent.TButton',command=self.open_detail).pack(side='right')
            M.ttk.Button(b,text='Zavřít',command=self.destroy).pack(side='right',padx=6)
        def load(self):
            for iid in self.tree.get_children():self.tree.delete(iid)
            self.rows={}
            where=[];args=[]
            if self.request_id is not None:
                where.append('o.request_id=?');args.append(self.request_id)
            if self.action_id is not None:
                where.append('(o.action_id=? OR o.request_id IN (SELECT id FROM requests WHERE action_id=?))');args.extend([self.action_id,self.action_id])
            cond=' AND '.join(where) if where else '1=0'
            try:
                with M.db() as c:
                    rows=c.execute(f'''SELECT o.id,o.offer_number,o.offer_date,o.total_value,o.currency,
                        coalesce(s.official_name,o.supplier_name,'') supplier,
                        coalesce(r.item,'') request_item,coalesce(a.name,'') action_name
                        FROM supplier_offers o
                        LEFT JOIN companies s ON s.id=o.supplier_company_id
                        LEFT JOIN requests r ON r.id=o.request_id
                        LEFT JOIN actions a ON a.id=coalesce(r.action_id,o.action_id)
                        WHERE {cond}
                        ORDER BY o.offer_date DESC,o.id DESC''',tuple(args)).fetchall()
                suppliers=[]
                for r in rows:
                    iid=f'o{r["id"]}';self.rows[iid]=int(r['id'])
                    sup=r['supplier'] or '—';suppliers.append(sup)
                    self.tree.insert('', 'end', iid=iid, values=(sup,r['offer_number'] or '—',M.fmt_date(r['offer_date']),r['request_item'] or '—',r['action_name'] or '—',f"{float(r['total_value'] or 0):,.2f}",r['currency'] or 'CZK'))
                uniq=[]
                for s in suppliers:
                    if s not in uniq:uniq.append(s)
                self.summary.configure(text=f"Nabídky: {len(rows)}" + (f"   •   Dodavatelé: {', '.join(uniq[:6])}" if uniq else ''))
            except Exception as e:
                self.summary.configure(text=f'Přehled se nepodařilo načíst: {e}')
        def open_detail(self):
            s=self.tree.selection()
            if not s:return
            oid=self.rows.get(s[0])
            if not oid:return
            try:
                import crm_features as F
                d=F.OfferDetailDialog(self.app,oid);self.wait_window(d);self.load()
            except Exception as e:
                M.messagebox.showerror('Nabídky',str(e),parent=self)

    M.RelatedOffersDialog=RelatedOffersDialog

    def _selected_id(tree,prefix):
        try:
            s=tree.selection()
            if not s:return None
            return int(str(s[0]).lstrip(prefix.upper()+prefix.lower()))
        except Exception:
            return None

    def _add_offer_column(tree):
        try:
            cols=list(tree.cget('columns'))
            if 'Nabídky' not in cols:
                cols.append('Nabídky');tree.configure(columns=tuple(cols))
                tree.heading('Nabídky',text='Nabídky');tree.column('Nabídky',width=82,minwidth=70,anchor='center',stretch=False)
        except Exception:
            pass

    def _refresh_counts(app):
        try:
            at=getattr(app,'action_tree',None)
            if at is not None:
                _add_offer_column(at)
                with M.db() as c:
                    rows=c.execute('''SELECT a.id,count(DISTINCT o.id) n FROM actions a LEFT JOIN supplier_offers o
                                      ON o.action_id=a.id OR o.request_id IN (SELECT id FROM requests r WHERE r.action_id=a.id)
                                      GROUP BY a.id''').fetchall()
                counts={int(r['id']):int(r['n']) for r in rows}
                for iid in at.get_children():
                    aid=_selected_id_from_iid(iid,'a');at.set(iid,'Nabídky',str(counts.get(aid,0)) if aid else '')
        except Exception:
            pass
        try:
            rt=getattr(app,'request_tree',None)
            if rt is not None:
                _add_offer_column(rt)
                with M.db() as c:
                    rows=c.execute('SELECT request_id,count(*) n FROM supplier_offers WHERE request_id IS NOT NULL GROUP BY request_id').fetchall()
                counts={int(r['request_id']):int(r['n']) for r in rows}
                for iid in rt.get_children():
                    rid=_selected_id_from_iid(iid,'r');rt.set(iid,'Nabídky',str(counts.get(rid,0)) if rid else '')
        except Exception:
            pass

    def _selected_id_from_iid(iid,prefix):
        try:return int(str(iid).lstrip(prefix.upper()+prefix.lower()))
        except Exception:return None

    def _open_action_offers(app):
        tree=getattr(app,'action_tree',None);aid=_selected_id(tree,'a') if tree is not None else None
        if not aid:return
        try:
            with M.db() as c:r=c.execute('SELECT name FROM actions WHERE id=?',(aid,)).fetchone();name=r['name'] if r else ''
        except Exception:name=''
        RelatedOffersDialog(app,app,action_id=aid,title=f'Nabídky – {name or "Příležitost"}')

    def _open_request_offers(app):
        tree=getattr(app,'request_tree',None);rid=_selected_id(tree,'r') if tree is not None else None
        if not rid:return
        try:
            with M.db() as c:r=c.execute('SELECT item FROM requests WHERE id=?',(rid,)).fetchone();name=r['item'] if r else ''
        except Exception:name=''
        RelatedOffersDialog(app,app,request_id=rid,title=f'Nabídky k poptávce – {name or "Poptávka"}')

    def _install_context(app,tree,kind):
        if tree is None or getattr(tree,'_v632_offer_context',False):return
        tree._v632_offer_context=True
        menu=M.tk.Menu(tree,tearoff=0)
        def popup(e):
            try:
                row=tree.identify_row(e.y)
                if row:
                    tree.selection_set(row);tree.focus(row)
                menu.delete(0,'end')
                if kind=='action':
                    aid=_selected_id(tree,'a');n=_offer_count_for_action(aid) if aid else 0
                    menu.add_command(label=f'Související nabídky ({n})',command=lambda:_open_action_offers(app))
                else:
                    rid=_selected_id(tree,'r');n=_offer_count_for_request(rid) if rid else 0
                    menu.add_command(label=f'Související nabídky ({n})',command=lambda:_open_request_offers(app))
                menu.tk_popup(e.x_root,e.y_root)
            finally:
                try:menu.grab_release()
                except Exception:pass
        tree.bind('<Button-3>',popup,add='+')

    # Recompute visible counts after normal refreshes.
    for name in ('refresh_actions','refresh_requests','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:_refresh_counts(self))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        def later():
            _refresh_counts(self)
            _install_context(self,getattr(self,'action_tree',None),'action')
            _install_context(self,getattr(self,'request_tree',None),'request')
        try:self.after(1800,later)
        except Exception:pass
        return r
    M.App.__init__=init

    # Make request linkage visually primary in offer detail: keep the v6.0.21
    # 'Přiřadit k Poptávce…' control and hide the older action-only button.
    try:
        import crm_features as F
        D=F.OfferDetailDialog
        old_build=D._build
        def build(self):
            r=old_build(self)
            try:
                def walk(w):
                    for c in list(w.winfo_children()):
                        try:
                            if c.winfo_class().endswith('Button') and str(c.cget('text')).strip().startswith('Přiřadit k Akci'):
                                c.destroy();continue
                        except Exception:pass
                        walk(c)
                walk(self.f)
                # Show the inherited request/action relation in the offer header.
                with M.db() as con:
                    row=con.execute('''SELECT r.item request_item,a.name action_name FROM supplier_offers o
                                      LEFT JOIN requests r ON r.id=o.request_id
                                      LEFT JOIN actions a ON a.id=coalesce(r.action_id,o.action_id)
                                      WHERE o.id=?''',(self.oid,)).fetchone()
                if row and (row['request_item'] or row['action_name']):
                    lab=M.ttk.Label(self.f,text=f"Vazba: Poptávka: {row['request_item'] or '—'}   •   Akce: {row['action_name'] or '—'}",style='PageSubtitle.TLabel')
                    lab.pack(fill='x',pady=(0,6),before=self.f.winfo_children()[1] if len(self.f.winfo_children())>1 else None)
            except Exception:pass
            return r
        D._build=build
    except Exception:
        pass
