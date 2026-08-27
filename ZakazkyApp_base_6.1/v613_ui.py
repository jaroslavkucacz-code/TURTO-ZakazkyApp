# TURTO CRM 6.0.13 - direct autocomplete Enter + ADMIN history Undo button

def apply(M):
    # ---------- Autocomplete: Enter immediately confirms the highlighted/first suggestion ----------
    try:
        def accept_first(self,event=None):
            try:
                matches=self._matches()
                if not matches:
                    self.hide();return "break"
                # If popup list is open, prefer its current active/selected row.
                chosen=None
                if getattr(self,'listbox',None) is not None:
                    try:
                        sel=self.listbox.curselection()
                        if sel:chosen=self.listbox.get(sel[0])
                        elif self.listbox.size():chosen=self.listbox.get(self.listbox.index('active'))
                    except:chosen=None
                if not chosen:chosen=matches[0]
                self._set(chosen)
                return "break"
            except Exception:
                return "break"
        M.AutocompleteEntry._accept_first=accept_first
    except:pass

    # ---------- ADMIN UI: Undo directly inside HISTORIE ----------
    try:
        import crm_runtime as R
        def open_admin(app,auth=False):
            if not auth and not R._login(app):return
            import tkinter as tk
            from tkinter import ttk,messagebox,filedialog
            d=tk.Toplevel(app);d.title('ADMIN – TURTO CRM');M.enable_dialog_maximize(d,1180,820);d.transient(app)
            nb=ttk.Notebook(d);nb.pack(fill='both',expand=True,padx=12,pady=12)
            dbf=ttk.Frame(nb,padding=16);usr=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16)
            for w,t in ((dbf,'Databáze'),(usr,'Uživatelé'),(hist,'HISTORIE'),(upd,'Aktualizace')):nb.add(w,text=t)

            # DB tab
            ttk.Label(dbf,text='Centrální databáze',style='Section.TLabel').pack(anchor='w')
            ttk.Label(dbf,text=f"Režim: {'SÍŤOVÝ' if R.NETWORK_MODE else 'LOKÁLNÍ'}   •   {M.DB}",style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,10))
            p=tk.StringVar(value=R._cfg().get('network_db','') or '')
            row=ttk.Frame(dbf);row.pack(fill='x');ttk.Entry(row,textvariable=p).pack(side='left',fill='x',expand=True)
            ttk.Button(row,text='Vybrat…',command=lambda:p.set(filedialog.askopenfilename(parent=d,filetypes=[('SQLite DB','*.db'),('Všechny soubory','*.*')]) or p.get())).pack(side='left',padx=6)
            b=ttk.Frame(dbf);b.pack(fill='x',pady=10)
            def create():
                target=p.get().strip()
                if not target:return messagebox.showwarning('ADMIN','Vyberte síťovou cestu.',parent=d)
                try:
                    import datetime
                    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S');R._backup(M.DB,M.Path(M.BACKUP_DIR)/f'pred_sitovou_migraci_{stamp}.db');R._backup(M.DB,target);R._save_cfg(mode='network',network_db=target);R._audit('database',target,'Vytvořena síťová DB');messagebox.showinfo('ADMIN','Síťová DB vytvořena. CRM se restartuje.',parent=d);d.destroy();R._restart(app)
                except Exception as e:messagebox.showerror('ADMIN',str(e),parent=d)
            def connect():
                ok,msg=R._valid(p.get().strip())
                if not ok:return messagebox.showerror('ADMIN',msg,parent=d)
                R._save_cfg(mode='network',network_db=p.get().strip());R._audit('database',p.get().strip(),'Připojena síťová DB');d.destroy();R._restart(app)
            def local():R._save_cfg(mode='local',network_db='');R._audit('database','local','Přepnuto na lokální DB');d.destroy();R._restart(app)
            ttk.Button(b,text='Vytvořit síťovou DB z aktuální',style='Accent.TButton',command=create).pack(side='left');ttk.Button(b,text='Připojit existující',command=connect).pack(side='left',padx=6);ttk.Button(b,text='Lokální režim',command=local).pack(side='left')
            test_btn=ttk.Button(dbf,text='Otestovat síťovou databázi');test_btn.pack(anchor='w',pady=(0,8))
            def testnet():
                target=p.get().strip()
                if not target:return messagebox.showwarning('Test databáze','Nejdřív vyberte konkrétní síťovou databázi.',parent=d)
                try:
                    import sqlite3
                    c=sqlite3.connect(target,timeout=5);c.execute('SELECT count(*) FROM sqlite_master').fetchone();c.execute('BEGIN IMMEDIATE');c.execute('ROLLBACK');c.close();messagebox.showinfo('Test databáze',f'Test proběhl úspěšně.\n\nDatabáze:\n{target}\n\nČtení i získání zapisovacího zámku je funkční.',parent=d)
                except Exception as e:messagebox.showerror('Test databáze',f'Test selhal pro:\n{target}\n\n{e}',parent=d)
            test_btn.configure(command=testnet,state='normal' if p.get().strip() else 'disabled');p.trace_add('write',lambda *_:test_btn.configure(state='normal' if p.get().strip() else 'disabled'))
            ttk.Label(dbf,text='Při nedostupné VPN se síťový klient nespustí lokálně. Tím nevznikají dvě paralelní verze dat.',style='PageSubtitle.TLabel').pack(anchor='w')

            # Users tab
            ttk.Label(usr,text='Správa uživatelů',style='Section.TLabel').pack(anchor='w');ttk.Label(usr,text='Pouze ADMIN může přidávat, upravovat nebo odebírat uživatele.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,8));ttk.Button(usr,text='Spravovat uživatele…',style='Accent.TButton',command=app.manage_users).pack(anchor='w')

            # History tab
            ttk.Label(hist,text='Auditní HISTORIE',style='Section.TLabel').pack(anchor='w')
            ttk.Label(hist,text='Vyberte auditovanou změnu a použijte ↶ Vrátit změnu. Operace se sama zapíše do historie.',style='PageSubtitle.TLabel').pack(anchor='w',pady=(2,8))
            cols=('Čas','Uživatel','PC','Objekt','Akce','Pole','Původní','Nová','Stav')
            t=ttk.Treeview(hist,columns=cols,show='headings')
            for x in cols:t.heading(x,text=x)
            t.pack(fill='both',expand=True)
            def refresh_hist():
                for iid in t.get_children():t.delete(iid)
                with M.db() as c:rows=c.execute('SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000').fetchall()
                for x in rows:
                    state='VRÁCENO' if x['undone'] else ('LZE VRÁTIT' if (x['undo_sql'] or '').strip() else '')
                    t.insert('', 'end',iid=str(x['id']),values=(x['created_at'],x['user_name'],x['computer_name'],f"{x['entity_type']} {x['entity_id']}",x['action'],x['field_name'],x['old_value'],x['new_value'],state))
            def undo_selected():
                sel=t.selection()
                if not sel:return messagebox.showinfo('Vrátit změnu','Nejdřív vyberte konkrétní záznam historie.',parent=d)
                iid=int(sel[0])
                with M.db() as c:r=c.execute('SELECT * FROM audit_history WHERE id=?',(iid,)).fetchone()
                if not r:return
                if r['undone']:return messagebox.showinfo('Vrátit změnu','Tato změna už byla vrácena.',parent=d)
                if not (r['undo_sql'] or '').strip():return messagebox.showinfo('Vrátit změnu','Tuto operaci zatím nelze bezpečně vrátit.',parent=d)
                if not messagebox.askyesno('Vrátit změnu',f"Opravdu vrátit změnu?\n\n{r['field_name']}:\n{r['new_value']}  →  {r['old_value']}",parent=d):return
                try:
                    with M.db() as c:
                        c.execute('BEGIN IMMEDIATE');c.execute(r['undo_sql']);c.execute('UPDATE audit_history SET undone=1 WHERE id=?',(iid,));c.commit()
                    R._audit(r['entity_type'],r['entity_id'],'ADMIN – vrácena změna',r['field_name'],r['new_value'],r['old_value'])
                    try:app.refresh_all()
                    except:pass
                    refresh_hist();messagebox.showinfo('Vrátit změnu','Změna byla vrácena.',parent=d)
                except Exception as e:messagebox.showerror('Vrátit změnu',f'Změnu se nepodařilo vrátit:\n{e}',parent=d)
            hb=ttk.Frame(hist);hb.pack(fill='x',pady=(8,0));ttk.Button(hb,text='↶ Vrátit změnu',style='Accent.TButton',command=undo_selected).pack(side='right');ttk.Button(hb,text='Obnovit historii',command=refresh_hist).pack(side='right',padx=6)
            t.bind('<Double-1>',lambda e:undo_selected())
            refresh_hist()

            # Updates tab
            auto=tk.BooleanVar(value=str(M.get_setting('company_auto_updates','1'))!='0');ttk.Label(upd,text='Firemní aktualizace',style='Section.TLabel').pack(anchor='w');ttk.Checkbutton(upd,text='Automaticky kontrolovat aktualizace při startu i během běhu aplikace',variable=auto).pack(anchor='w',pady=10);ttk.Label(upd,text='Kontrola během běhu probíhá přibližně každých 10 minut.',style='PageSubtitle.TLabel').pack(anchor='w');ttk.Button(upd,text='Uložit',command=lambda:M.set_setting('company_auto_updates','1' if auto.get() else '0')).pack(anchor='w',pady=8)
        R.open_admin=open_admin
        M.App.open_admin=open_admin
    except:pass
