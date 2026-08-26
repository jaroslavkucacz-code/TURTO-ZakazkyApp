# TURTO CRM 6.0.9 stability layer
# Re-asserts agreed UI behavior after all feature modules; keeps recipient ranking and UI sizing stable.
import datetime, sqlite3

def apply(M):
    # ---------- persistent stronger theme palette ----------
    LIGHT={
        'status_active':('#b6d8f0','#0b3554'),'status_offer':('#9fddd5','#064d47'),
        'status_done':('#b0ddb9','#124c22'),'status_won':('#9fd8af','#10461f'),
        'status_wait':('#ffe08a','#5c4200'),'status_soon':('#ffbc78','#713400'),
        'status_late':('#f5a2a2','#7b1111'),'status_cancel':('#d6dbe0','#3e474f')}
    DARK={
        'status_active':('#326484','#f5fbff'),'status_offer':('#197b72','#f0fffd'),
        'status_done':('#3b794b','#f1fff4'),'status_won':('#2f7a47','#effff4'),
        'status_wait':('#856719','#fff4c0'),'status_soon':('#96511c','#fff0df'),
        'status_late':('#943b3b','#fff1f1'),'status_cancel':('#555f68','#f5f7f8')}
    aliases={'late':'status_late','soon':'status_soon','waiting':'status_wait','done':'status_done','won':'status_won','lost':'status_cancel','info':'status_active','req_fresh':'status_active','req_mid':'status_wait','req_old':'status_soon','req_received':'status_done'}

    def _quick_styles(app):
        """Keep dashboard quick actions visibly colored in both themes."""
        try:
            s=M.ttk.Style(app);dark='tmav' in (app.theme.get() if hasattr(app,'theme') else '').lower()
            colors={
                'QuickBlue.TButton':('#2f80c9','#ffffff') if not dark else ('#356f9e','#ffffff'),
                'QuickOrange.TButton':('#d99020','#ffffff') if not dark else ('#9b671b','#ffffff'),
                'QuickGreen.TButton':('#3f9a61','#ffffff') if not dark else ('#3d7c50','#ffffff'),
                'QuickPurple.TButton':('#8b68b8','#ffffff') if not dark else ('#6d528f','#ffffff'),
                'QuickGray.TButton':('#667684','#ffffff') if not dark else ('#56636d','#ffffff')}
            for name,(bg,fg) in colors.items():
                s.configure(name,background=bg,foreground=fg,font=('Calibri',11,'bold'),padding=(12,10),relief='flat',borderwidth=0)
                s.map(name,background=[('active',bg),('pressed',bg)],foreground=[('disabled','#c8c8c8'),('!disabled',fg)])
        except:pass

    def recolor(app):
        try:
            import tkinter.ttk as ttk
            dark='tmav' in (app.theme.get() if hasattr(app,'theme') else '').lower();pal=DARK if dark else LIGHT
            def walk(w):
                try:
                    if isinstance(w,ttk.Treeview):
                        for tag,(bg,fg) in pal.items():w.tag_configure(tag,background=bg,foreground=fg)
                        for a,b in aliases.items():w.tag_configure(a,background=pal[b][0],foreground=pal[b][1])
                    for c in w.winfo_children():walk(c)
                except:pass
            walk(app);_quick_styles(app)
        except:pass
    old_theme=M.App.apply_theme
    def theme(self,*a,**k):
        r=old_theme(self,*a,**k);self.after_idle(lambda:recolor(self));return r
    M.App.apply_theme=theme

    # ---------- dialog dimensions / maximized main window ----------
    # Dialogs should be comfortably large immediately, but never exceed usable screen area.
    # Default target: about 84 % screen width and 88 % screen height, while respecting a larger explicit request.
    def safe_size(win,w=980,h=800):
        try:
            win.update_idletasks();sw=max(800,win.winfo_screenwidth());sh=max(600,win.winfo_screenheight())
            target_w=max(int(w),int(sw*0.84));target_h=max(int(h),int(sh*0.88))
            ww=min(target_w,max(560,sw-40));hh=min(target_h,max(500,sh-75))
            x=max(0,(sw-ww)//2);y=max(0,(sh-hh)//2)
            win.geometry(f'{ww}x{hh}+{x}+{y}');win.minsize(min(760,ww),min(560,hh));win.resizable(True,True)
        except:pass
    M.enable_dialog_maximize=safe_size

    # ---------- MIVO: one triangle only; no age-based full-row warning ----------
    old_mivo=M.App.refresh_mivo_requests
    def mivo(self,*a,**k):
        r=old_mivo(self,*a,**k)
        try:
            today=datetime.date.today()
            for iid in self.mivo_tree.get_children():
                vals=list(self.mivo_tree.item(iid,'values'));state=str(vals[0] if vals else '')
                self.mivo_tree.item(iid,tags=('status_done',) if state.casefold().startswith('obdrž') else ('status_active',))
                if len(vals)>2:
                    raw=str(vals[2]).replace('⚠','').replace('!','').replace('•','').strip();dt=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:dt=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    vals[2]=('⚠  '+raw) if state.casefold().startswith('ček') and dt and (today-dt).days>10 else raw
                    self.mivo_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_mivo_requests=mivo

    # ---------- classic requests warning thresholds ----------
    old_req=M.App.refresh_requests
    def requests(self,*a,**k):
        r=old_req(self,*a,**k)
        try:
            today=datetime.date.today()
            for iid in self.request_tree.get_children():
                vals=list(self.request_tree.item(iid,'values'));state=str(vals[0] if vals else '').casefold()
                if not state.startswith('ček'):continue
                if len(vals)>2:
                    raw=str(vals[2]).replace('⚠','').replace('!','').replace('•','').strip();dt=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:dt=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    if dt:
                        age=(today-dt).days;vals[2]=('⚠  '+raw) if age>=11 else (('•  '+raw) if age>=6 else raw);self.request_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_requests=requests

    # ---------- most-used recipients first ----------
    try:
        with M.db() as c:c.execute('CREATE TABLE IF NOT EXISTS recipient_usage(company_id INTEGER,person_id INTEGER,use_count INTEGER DEFAULT 0,last_used TEXT,PRIMARY KEY(company_id,person_id))')
    except:pass
    old_load=M.RequestDialog.load_contacts
    def load_contacts(self,selected=None):
        frame=getattr(self,'contacts_frame',None) or getattr(self,'contacts',None)
        if frame is None:return old_load(self,selected)
        for widget in frame.winfo_children():widget.destroy()
        self.contact_vars=[];cid=self.company_id()
        if not cid:
            if hasattr(self,'contact_count_label'):self.contact_count_label.config(text='Vyberte společnost.')
            return
        with M.db() as con:
            company=con.execute('SELECT official_name FROM companies WHERE id=?',(cid,)).fetchone()
            rows=con.execute('''SELECT p.id,p.name,p.email,p.role,coalesce(u.use_count,0) use_count,coalesce(u.last_used,'') last_used
                                FROM people p LEFT JOIN recipient_usage u ON u.company_id=p.company_id AND u.person_id=p.id
                                WHERE p.active=1 AND p.company_id=?
                                ORDER BY coalesce(u.use_count,0) DESC,coalesce(u.last_used,'') DESC,p.name COLLATE CZECH,p.email''',(cid,)).fetchall()
        selected_set={x.strip().lower() for x in (selected or []) if x and x.strip()};with_email=0
        for rr in rows:
            email=(rr['email'] or '').strip();with_email+=1 if email else 0;label=(rr['name'] or '').strip() or '(bez jména)'
            if rr['role']:label+=f" · {rr['role']}"
            label+=f' — {email}' if email else ' — bez e-mailu';var=M.tk.BooleanVar(value=email.lower() in selected_set if email else False)
            cb=M.ttk.Checkbutton(frame,text=label,variable=var)
            if not email:cb.state(['disabled'])
            cb.pack(anchor='w',pady=2);self.contact_vars.append((var,email))
        nm=company['official_name'] if company else self.company.get()
        if hasattr(self,'contact_count_label'):self.contact_count_label.config(text=f'{nm} · osoby: {len(rows)} · s e-mailem: {with_email} · nejpoužívanější nahoře')
        if not rows:M.ttk.Label(frame,text='U této společnosti nejsou v Adresáři žádné osoby.').pack(anchor='w',pady=4)
    M.RequestDialog.load_contacts=load_contacts

    old_ok=M.RequestDialog.ok
    def req_ok(self,*a,**k):
        try:cid=self.company_id();selected=[email for var,email in self.contact_vars if email and var.get()]
        except:cid=None;selected=[]
        r=old_ok(self,*a,**k)
        try:
            if getattr(self,'result',None) and cid and selected:
                with M.db() as con:
                    for email in selected:
                        pr=con.execute('SELECT id FROM people WHERE company_id=? AND active=1 AND lower(trim(email))=lower(trim(?)) ORDER BY id LIMIT 1',(cid,email)).fetchone()
                        if pr:con.execute('''INSERT INTO recipient_usage(company_id,person_id,use_count,last_used) VALUES(?,?,1,CURRENT_TIMESTAMP)
                                            ON CONFLICT(company_id,person_id) DO UPDATE SET use_count=use_count+1,last_used=CURRENT_TIMESTAMP''',(cid,pr['id']))
        except:pass
        return r
    M.RequestDialog.ok=req_ok

    # ---------- re-assert sorting reset when changing tabs ----------
    old_show=M.App.show_page
    def show(self,key,*a,**k):
        prev=getattr(self,'_v608_page',None);r=old_show(self,key,*a,**k)
        if prev is not None and prev!=key:
            for n in ('action_tree','request_tree','mivo_tree','offer_tree','task_tree','project_tree','people_tree','company_tree'):
                t=getattr(self,n,None)
                if t is not None:
                    try:t._sort_state={};t._active_sort=None
                    except:pass
        self._v608_page=key;return r
    M.App.show_page=show

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(120,lambda:self.state('zoomed'));self.after(250,lambda:recolor(self))
        except:pass
        return r
    M.App.__init__=init
