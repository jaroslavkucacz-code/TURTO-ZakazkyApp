# TURTO CRM 6.0.38 - stable tables, correct Action sorting, manual update notes
import datetime


def apply(M):
    # ------------------------------------------------------------------
    # BUSINESS MODEL
    # projects = Akce, actions = Příležitosti.
    # One Akce may own several Příležitosti; their displayed name is the same.
    # Offers are shown on the Akce, not duplicated in Příležitosti.
    # ------------------------------------------------------------------

    REQUEST_COLS=("Stav","Řeší","Poptáno","Obdrženo","Odběratel","Dodavatel","Akce","Poptáváno","Příjemci","Nabídky")
    OPPORTUNITY_COLS=("Stav","Přijato","Deadline","Příležitost","Společnost","Obchodník","Co se řeší","Poznámka")
    PROJECT_COLS=("Název Akce","Adresa","Investor","Generální dodavatel","Zahájení","Dokončení","Příležitostí","Nabídky")

    def _heading_contract(app,tree,cols):
        if tree is None:return
        try:
            tree.configure(show='headings',columns=cols)
            for c in cols:
                tree.heading(c,text=c,command=lambda col=c,t=tree:app.sort_tree(t,col))
        except Exception:pass

    def _project_offer_counts():
        try:
            with M.db() as c:
                rows=c.execute('''SELECT p.id,count(DISTINCT o.id) n
                    FROM projects p
                    LEFT JOIN supplier_offers o ON
                        o.project_id=p.id OR
                        o.request_id IN (SELECT r.id FROM requests r JOIN actions a ON a.id=r.action_id WHERE a.project_id=p.id)
                    GROUP BY p.id''').fetchall()
            return {int(r['id']):int(r['n']) for r in rows}
        except Exception:return {}

    def _request_offer_counts():
        try:
            with M.db() as c:
                rows=c.execute('SELECT request_id,count(*) n FROM supplier_offers WHERE request_id IS NOT NULL GROUP BY request_id').fetchall()
            return {int(r['request_id']):int(r['n']) for r in rows}
        except Exception:return {}

    def _iid_num(iid,prefix):
        try:return int(str(iid).lstrip(prefix.upper()+prefix.lower()))
        except Exception:return None

    def _restore_main_tables(app):
        # Příležitosti: never show offer count directly.
        at=getattr(app,'action_tree',None)
        if at is not None:
            _heading_contract(app,at,OPPORTUNITY_COLS)

        # Poptávky keep their offer count.
        rt=getattr(app,'request_tree',None)
        if rt is not None:
            _heading_contract(app,rt,REQUEST_COLS)
            try:
                rt.column('Nabídky',width=82,minwidth=70,anchor='center',stretch=False)
                counts=_request_offer_counts()
                for iid in rt.get_children():
                    rid=_iid_num(iid,'r')
                    if rid is not None:rt.set(iid,'Nabídky',str(counts.get(rid,0)))
            except Exception:pass

        # Akce are the central place for offers.
        pt=getattr(app,'project_tree',None)
        if pt is not None:
            _heading_contract(app,pt,PROJECT_COLS)
            try:
                pt.column('Nabídky',width=82,minwidth=70,anchor='center',stretch=False)
                counts=_project_offer_counts()
                for iid in pt.get_children():
                    pid=_iid_num(iid,'p')
                    if pid is not None:pt.set(iid,'Nabídky',str(counts.get(pid,0)))
            except Exception:pass

    def _sort_projects_default(app):
        t=getattr(app,'project_tree',None)
        if t is None:return
        try:
            rows=list(t.get_children(''))
            rows.sort(key=lambda iid:M.czech_sort_key(t.set(iid,'Název Akce')))
            for pos,iid in enumerate(rows):t.move(iid,'',pos)
            t._sort_state={};t._active_sort=None
        except Exception:pass

    def _style_urgent_requests(app):
        # Stable/native Treeview styling only. No Label overlays and no scroll hooks.
        t=getattr(app,'request_tree',None)
        if t is None:return
        try:t.tag_configure('deadline_urgent',foreground='#c62828',font=('Calibri',10,'bold'))
        except Exception:pass
        today=datetime.date.today()
        try:
            for iid in t.get_children():
                vals=t.item(iid,'values')
                tags=[x for x in (t.item(iid,'tags') or ()) if x!='deadline_urgent']
                status=str(vals[0] if vals else '').casefold()
                raw=str(vals[2] if len(vals)>2 else '').strip()
                urgent=False
                if 'ček' in status:
                    try:urgent=(today-datetime.datetime.strptime(raw,'%d.%m.%Y').date()).days>3
                    except Exception:
                        try:urgent=(today-datetime.datetime.strptime(raw,'%Y-%m-%d').date()).days>3
                        except Exception:pass
                if urgent:tags.append('deadline_urgent')
                t.item(iid,tags=tuple(tags))
        except Exception:pass

    def _remove_problematic_request_bindings(app):
        t=getattr(app,'request_tree',None)
        if t is None or getattr(t,'_v638_clean_bindings',False):return
        # v633/v637 added floating redraw hooks here. Remove instance hooks;
        # native Treeview class bindings still provide scrolling normally.
        for seq in ('<MouseWheel>','<ButtonRelease-1>'):
            try:t.unbind(seq)
            except Exception:pass
        # Configure refresh was also the source of repeated full reloads while resizing.
        try:t.unbind('<Configure>')
        except Exception:pass
        t._v638_clean_bindings=True

    def _stabilize(app,sort_projects=False):
        _restore_main_tables(app)
        _remove_problematic_request_bindings(app)
        _style_urgent_requests(app)
        if sort_projects:_sort_projects_default(app)

    # Apply after old wrappers finish their after_idle work. This makes the final
    # contract deterministic and stops the v632/v637 add/remove column race.
    for name in ('refresh_requests','refresh_actions','refresh_projects','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn,method_name=name):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                for ms in (50,420):
                    try:self.after(ms,lambda s=self,n=method_name:_stabilize(s,sort_projects=n in ('refresh_projects','refresh_all')))
                    except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,key,*a,**k):
            r=old_show(self,key,*a,**k)
            try:
                self.after_idle(lambda:_stabilize(self,sort_projects=key in ('projects','project')))
                if key in ('projects','project'):self.after(250,lambda:_sort_projects_default(self))
            except Exception:pass
            return r
        M.App.show_page=show_page

    # ------------------------------------------------------------------
    # MANUAL UPDATE CHECK: show release notes before installation.
    # Use the same manifest 'notes' field that automatic checks already read.
    # ------------------------------------------------------------------
    old_check=getattr(M.App,'check_for_updates',None)
    if callable(old_check):
        def check_for_updates(self,silent=False):
            # Second pass after user explicitly chose Update: call the original
            # installer but suppress its old yes/no prompt.
            if getattr(self,'_v638_update_confirmed',False):
                self._v638_update_confirmed=False
                old_yes=M.messagebox.askyesno
                try:
                    M.messagebox.askyesno=lambda *a,**k:True
                    return old_check(self,silent=True)
                finally:
                    M.messagebox.askyesno=old_yes

            source=(self.update_source.get().strip() if hasattr(self,'update_source') else M.get_setting('update_source',''))
            if hasattr(self,'update_source'):M.set_setting('update_source',source)
            if not source:
                if not silent:M.messagebox.showinfo('Aktualizace','Nejprve nastavte zdroj aktualizací v Nastavení.',parent=self)
                return
            try:
                mf=M._read_update_manifest(source)
                remote=str(mf.get('version') or '').strip()
                if M._version_tuple(remote)<=M._version_tuple(M.APP_VERSION):
                    if not silent:M.messagebox.showinfo('Aktualizace',f'Používáte aktuální verzi {M.APP_VERSION}.',parent=self)
                    return
                notes=str(mf.get('notes') or '').strip() or 'Drobné opravy a vylepšení.'
                # Avoid stacking duplicate update windows for the same version.
                existing=getattr(self,'_v638_update_window',None)
                try:
                    if existing is not None and existing.winfo_exists():existing.lift();return
                except Exception:pass
                d=M.tk.Toplevel(self);self._v638_update_window=d
                d.title(f'Aktualizace {remote}');d.transient(self);d.grab_set();M.enable_dialog_maximize(d,680,460)
                f=M.ttk.Frame(d,padding=18);f.pack(fill='both',expand=True)
                M.ttk.Label(f,text=f'Je dostupná nová verze {remote}',style='Section.TLabel').pack(anchor='w')
                M.ttk.Label(f,text='Co aktualizace obsahuje:',style='PageSubtitle.TLabel').pack(anchor='w',pady=(12,5))
                txt=M.tk.Text(f,height=12,wrap='word',font=('Calibri',11));txt.pack(fill='both',expand=True)
                txt.insert('1.0',notes);txt.configure(state='disabled')
                bar=M.ttk.Frame(f);bar.pack(fill='x',pady=(12,0))
                def close():
                    try:d.destroy()
                    except Exception:pass
                    self._v638_update_window=None
                def install():
                    close();self._v638_update_confirmed=True;self.check_for_updates(silent=False)
                M.ttk.Button(bar,text='Později',command=close).pack(side='right')
                M.ttk.Button(bar,text='Aktualizovat',style='Accent.TButton',command=install).pack(side='right',padx=6)
            except Exception as e:
                if not silent:M.messagebox.showerror('Aktualizace',f'Kontrola aktualizací se nezdařila:\n\n{e}',parent=self)
        M.App.check_for_updates=check_for_updates

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        for ms in (900,2200,3800):
            try:self.after(ms,lambda s=self:_stabilize(s,sort_projects=True))
            except Exception:pass
        return r
    M.App.__init__=init
