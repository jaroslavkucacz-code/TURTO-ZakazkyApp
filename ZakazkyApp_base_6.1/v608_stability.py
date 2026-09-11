# TURTO CRM 6.0.10 stability layer
# Stable UI + recipient ranking + simplified request warnings.
import datetime, sqlite3

def apply(M):
    # The final Treeview status palette is owned by v628_modernui_resize. Keep
    # v608 responsible only for its historical quick-action button styles. This
    # avoids a recursive full-window walk on every theme change and after start.
    def _quick_styles(app):
        try:
            s=M.ttk.Style(app);dark='tmav' in (app.theme.get() if hasattr(app,'theme') else '').lower();colors={'QuickBlue.TButton':('#2f80c9','#fff') if not dark else ('#356f9e','#fff'),'QuickOrange.TButton':('#d99020','#fff') if not dark else ('#9b671b','#fff'),'QuickGreen.TButton':('#3f9a61','#fff') if not dark else ('#3d7c50','#fff'),'QuickPurple.TButton':('#8b68b8','#fff') if not dark else ('#6d528f','#fff'),'QuickGray.TButton':('#667684','#fff') if not dark else ('#56636d','#fff')}
            for name,(bg,fg) in colors.items():s.configure(name,background=bg,foreground=fg,font=('Calibri',11,'bold'),padding=(12,10),relief='flat',borderwidth=0);s.map(name,background=[('active',bg),('pressed',bg)],foreground=[('!disabled',fg)])
        except:pass
    old_theme=M.App.apply_theme
    def theme(self,*a,**k):
        r=old_theme(self,*a,**k)
        try:self.after_idle(lambda:_quick_styles(self))
        except Exception:_quick_styles(self)
        return r
    M.App.apply_theme=theme

    # Large dialogs, always within screen.
    def safe_size(win,w=980,h=800):
        try:
            win.update_idletasks();sw=max(800,win.winfo_screenwidth());sh=max(600,win.winfo_screenheight());target_w=max(int(w),int(sw*.84));target_h=max(int(h),int(sh*.88));ww=min(target_w,max(560,sw-40));hh=min(target_h,max(500,sh-75));win.geometry(f'{ww}x{hh}+{max(0,(sw-ww)//2)}+{max(0,(sh-hh)//2)}');win.minsize(min(760,ww),min(560,hh));win.resizable(True,True)
        except:pass
    M.enable_dialog_maximize=safe_size

    # MIVO: one triangle after >10 days, no age coloring of whole row.
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
                    vals[2]=('⚠  '+raw) if state.casefold().startswith('ček') and dt and (today-dt).days>10 else raw;self.mivo_tree.item(iid,values=vals)
        except:pass
        return r
    M.App.refresh_mivo_requests=mivo

    # Classic requests: ONLY one triangle after more than 3 days. No dots, no age-based row colors.
    old_req=M.App.refresh_requests
    def requests(self,*a,**k):
        r=old_req(self,*a,**k)
        try:
            today=datetime.date.today()
            for iid in self.request_tree.get_children():
                vals=list(self.request_tree.item(iid,'values'));state=str(vals[0] if vals else '').casefold()
                if len(vals)>2:
                    raw=str(vals[2]).replace('⚠','').replace('!','').replace('•','').strip();dt=None
                    for fmt in ('%d.%m.%Y','%Y-%m-%d'):
                        try:dt=datetime.datetime.strptime(raw,fmt).date();break
                        except:pass
                    if dt:vals[2]=('⚠  '+raw) if state.startswith('ček') and (today-dt).days>3 else raw
                    self.request_tree.item(iid,values=vals)
                # Waiting age must not recolor the entire request row.
                if state.startswith('ček'):self.request_tree.item(iid,tags=('status_active',))
        except:pass
        return r
    M.App.refresh_requests=requests

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
            company=con.execute('SELECT official_name FROM companies WHERE id=?',(cid,)).fetchone();rows=con.execute("""SELECT p.id,p.name,p.email,p.role,coalesce(u.use_count,0) use_count,coalesce(u.last_used,'') last_used FROM people p LEFT JOIN recipient_usage u ON u.company_id=p.company_id AND u.person_id=p.id WHERE p.active=1 AND p.company_id=? ORDER BY coalesce(u.use_count,0) DESC,coalesce(u.last_used,'') DESC,p.name COLLATE CZECH,p.email""",(cid,)).fetchall()
        selected_set={x.strip().lower() for x in (selected or []) if x and x.strip()};with_email=0
        for rr in rows:
            email=(rr['email'] or '').strip();with_email+=1 if email else 0;label=(rr['name'] or '').strip() or '(bez jména)';label+=(f" · {rr['role']}" if rr['role'] else '')+(f' — {email}' if email else ' — bez e-mailu');var=M.tk.BooleanVar(value=email.lower() in selected_set if email else False);cb=M.ttk.Checkbutton(frame,text=label,variable=var)
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
                        if pr:con.execute("""INSERT INTO recipient_usage(company_id,person_id,use_count,last_used) VALUES(?,?,1,CURRENT_TIMESTAMP) ON CONFLICT(company_id,person_id) DO UPDATE SET use_count=use_count+1,last_used=CURRENT_TIMESTAMP""",(cid,pr['id']))
        except:pass
        return r
    M.RequestDialog.ok=req_ok
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
        try:self.after(120,lambda:self.state('zoomed'));self.after(250,lambda:_quick_styles(self))
        except:pass
        return r
    M.App.__init__=init
