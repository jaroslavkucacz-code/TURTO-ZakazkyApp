# TURTO CRM 6.0.14 - autocomplete Enter fix, 14-day audit archive, dashboard palette, performance indexes
import datetime

def apply(M):
    # 1) Correct widget: the base app uses InlineChoice for the inline suggesters.
    # Enter must commit exactly like clicking a list row and must not bubble to dialog OK.
    try:
        def accept_inline(self,event=None):
            try:
                if not self._shown:self.show()
                vals=self._matches()
                if not vals:return 'break'
                idx=0
                if self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else max(0,self.listbox.index('active'))
                    idx=min(idx,self.listbox.size()-1);value=self.listbox.get(idx)
                else:value=vals[0]
                self._set(value)
                # generate on both composite and entry for existing dialog listeners
                try:self.entry.event_generate('<<InlineChoiceSelected>>')
                except:pass
                return 'break'
            except:return 'break'
        M.InlineChoice._accept_entry=accept_inline
    except:pass

    # Also harden any floating AutocompleteEntry if present in feature modules.
    try:
        A=M.AutocompleteEntry
        old_init=A.__init__
        def ac_init(self,*a,**k):
            old_init(self,*a,**k)
            def enter(e=None):
                try:
                    # Prefer the widget's own native selection method; it carries payload/ID callbacks.
                    for method in ('_choose','_select','_accept','select_current'):
                        fn=getattr(self,method,None)
                        if callable(fn):
                            try:return fn(e) or 'break'
                            except TypeError:return fn() or 'break'
                    matches=self._matches() if hasattr(self,'_matches') else []
                    if matches and hasattr(self,'_set'):self._set(matches[0])
                    return 'break'
                except:return 'break'
            self.bind('<Return>',enter)
            self.bind('<KP_Enter>',enter)
        A.__init__=ac_init
    except:pass

    # 2) Performance reserve for growing company DB/audit.
    try:
        with M.db() as c:
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_history(created_at DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_history(entity_type,entity_id,created_at DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_history(user_name,created_at DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_requests_dates ON requests(archived,asked_date,received_date)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_actions_status_deadline ON actions(status,deadline)')
    except:pass

    # 3) ADMIN history: active 14 days only; older records are archive/read-only.
    # Patch the v6.0.13 ADMIN implementation after it has been installed.
    try:
        import crm_runtime as R
        def open_admin(app,auth=False):
            if not auth and not R._login(app):return
            import tkinter as tk
            from tkinter import ttk,messagebox,filedialog
            d=tk.Toplevel(app);d.title('ADMIN – TURTO CRM');M.enable_dialog_maximize(d,1180,820);d.transient(app)
            nb=ttk.Notebook(d);nb.pack(fill='both',expand=True,padx=12,pady=12)
            dbf=ttk.Frame(nb,padding=16);usr=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16)
            for w,tit in ((dbf,'Databáze'),(usr,'Uživatelé'),(hist,'HISTORIE'),(upd,'Aktualizace')):nb.add(w,text=tit)
            # DB controls retained
            ttk.Label(dbf,text='Centrální databáze',style='Section.TLabel').pack(anchor='w');ttk.Label(dbf,text=f"Režim: {'SÍŤOVÝ' if R.NETWORK_MODE else 'LOKÁLNÍ'}   •   {M.DB}",style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,10))
            p=tk.StringVar(value=R._cfg().get('network_db','') or '');row=ttk.Frame(dbf);row.pack(fill='x');ttk.Entry(row,textvariable=p).pack(side='left',fill='x',expand=True);ttk.Button(row,text='Vybrat…',command=lambda:p.set(filedialog.askopenfilename(parent=d,filetypes=[('SQLite DB','*.db'),('Všechny soubory','*.*')]) or p.get())).pack(side='left',padx=6)
            b=ttk.Frame(dbf);b.pack(fill='x',pady=10)
            def connect():
                ok,msg=R._valid(p.get().strip())
                if not ok:return messagebox.showerror('ADMIN',msg,parent=d)
                R._save_cfg(mode='network',network_db=p.get().strip());d.destroy();R._restart(app)
            ttk.Button(b,text='Připojit existující',style='Accent.TButton',command=connect).pack(side='left');ttk.Button(b,text='Lokální režim',command=lambda:(R._save_cfg(mode='local',network_db=''),d.destroy(),R._restart(app))).pack(side='left',padx=6)
            ttk.Label(usr,text='Správa uživatelů',style='Section.TLabel').pack(anchor='w');ttk.Button(usr,text='Spravovat uživatele…',style='Accent.TButton',command=app.manage_users).pack(anchor='w',pady=8)

            top=ttk.Frame(hist);top.pack(fill='x');ttk.Label(top,text='Auditní HISTORIE',style='Section.TLabel').pack(side='left');archive=tk.BooleanVar(value=False);ttk.Checkbutton(top,text='Zobrazit archiv (> 14 dní)',variable=archive).pack(side='right')
            info=ttk.Label(hist,text='Posledních 14 dní je aktivních. Starší audit je archivovaný a pouze pro čtení.',style='PageSubtitle.TLabel');info.pack(anchor='w',pady=(2,8))
            cols=('Čas','Uživatel','PC','Objekt','Akce','Pole','Původní','Nová','Stav');t=ttk.Treeview(hist,columns=cols,show='headings')
            for x in cols:t.heading(x,text=x)
            t.pack(fill='both',expand=True);rows_by_id={}
            def load():
                rows_by_id.clear()
                for iid in t.get_children():t.delete(iid)
                cutoff=(datetime.datetime.now()-datetime.timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
                with M.db() as c:
                    if archive.get():rows=c.execute('SELECT * FROM audit_history WHERE created_at < ? ORDER BY id DESC LIMIT 1000',(cutoff,)).fetchall()
                    else:rows=c.execute('SELECT * FROM audit_history WHERE created_at >= ? ORDER BY id DESC LIMIT 1000',(cutoff,)).fetchall()
                for x in rows:
                    rows_by_id[str(x['id'])]=x
                    if archive.get():state='ARCHIV'
                    elif x['undone']:state='VRÁCENO'
                    elif (x['undo_sql'] or '').strip():state='LZE VRÁTIT'
                    else:state='NELZE VRÁTIT'
                    t.insert('','end',iid=str(x['id']),values=(x['created_at'],x['user_name'],x['computer_name'],f"{x['entity_type']} {x['entity_id']}",x['action'],x['field_name'],x['old_value'],x['new_value'],state))
                undo_btn.configure(state='disabled' if archive.get() else 'normal')
            def undo():
                sel=t.selection()
                if not sel:return
                r=rows_by_id.get(sel[0])
                if not r or archive.get() or r['undone'] or not (r['undo_sql'] or '').strip():return messagebox.showinfo('Vrátit změnu','Tento záznam nelze vrátit.',parent=d)
                if not messagebox.askyesno('Vrátit změnu',f"{r['field_name']}: {r['new_value']} → {r['old_value']}?",parent=d):return
                try:
                    with M.db() as c:c.execute('BEGIN IMMEDIATE');c.execute(r['undo_sql']);c.execute('UPDATE audit_history SET undone=1 WHERE id=?',(r['id'],));c.commit()
                    R._audit(r['entity_type'],r['entity_id'],'ADMIN – vrácena změna',r['field_name'],r['new_value'],r['old_value']);app.refresh_all();load()
                except Exception as e:messagebox.showerror('Vrátit změnu',str(e),parent=d)
            foot=ttk.Frame(hist);foot.pack(fill='x',pady=(8,0));undo_btn=ttk.Button(foot,text='↶ Vrátit změnu',style='Accent.TButton',command=undo);undo_btn.pack(side='right');ttk.Button(foot,text='Obnovit',command=load).pack(side='right',padx=6);archive.trace_add('write',lambda *_:load());load()
            auto=tk.BooleanVar(value=str(M.get_setting('company_auto_updates','1'))!='0');ttk.Label(upd,text='Firemní aktualizace',style='Section.TLabel').pack(anchor='w');ttk.Checkbutton(upd,text='Automaticky kontrolovat aktualizace při startu i během běhu aplikace',variable=auto).pack(anchor='w',pady=10);ttk.Button(upd,text='Uložit',command=lambda:M.set_setting('company_auto_updates','1' if auto.get() else '0')).pack(anchor='w')
        R.open_admin=open_admin;M.App.open_admin=open_admin
    except:pass

    # 4) Dashboard must use the same status palette/tags as all other lists.
    # Reapply canonical tags after every overview refresh without inventing a separate palette.
    for name in ('refresh_dashboard','refresh_overview','refresh_home'):
        fn=getattr(M.App,name,None)
        if not fn:continue
        def wrap(original):
            def f(self,*a,**k):
                r=original(self,*a,**k)
                try:
                    for attr in ('dashboard_tree','overview_tree','home_tree','deadline_tree','upcoming_tree'):
                        tree=getattr(self,attr,None)
                        if tree is None:continue
                        for iid in tree.get_children():
                            vals=' '.join(str(x) for x in tree.item(iid,'values')).casefold()
                            tag='status_done' if 'hotovo' in vals else ('status_offer' if ('připraven' in vals or 'nabíd' in vals) else ('status_cancel' if ('zrušen' in vals or 'archiv' in vals) else 'status_active'))
                            tree.item(iid,tags=(tag,))
                except:pass
                return r
            return f
        setattr(M.App,name,wrap(fn))
