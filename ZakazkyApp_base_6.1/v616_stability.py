# TURTO CRM 6.0.16 - keyboard autocomplete, work-area dialogs, recipient ordering, next-step hardening
import sys

def apply(M):
    # --- 1) AutocompleteEntry: stable keyboard model ---
    # Keep typing focus in Entry. Popup always owns a visual selection, but never steals focus.
    try:
        A=M.AutocompleteEntry
        prev_init=A.__init__
        def _select_index(self,idx):
            if not self.listbox or not self.listbox.size():return
            idx=max(0,min(self.listbox.size()-1,int(idx)))
            self.listbox.selection_clear(0,'end');self.listbox.selection_set(idx);self.listbox.activate(idx);self.listbox.see(idx)
        def _show_keyboard(self):
            self._show()
            if self.listbox and self.listbox.size():
                sel=self.listbox.curselection()
                if not sel:_select_index(self,0)
            try:self.focus_set()
            except:pass
        def _nav(self,delta):
            try:
                _show_keyboard(self)
                if not self.listbox or not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0
                _select_index(self,cur+delta)
                self.focus_set()
                return 'break'
            except:return 'break'
        def _enter(self,event=None):
            try:
                # Open popup + active suggestion => commit exactly as mouse selection (_set sets payload/ID + event).
                visible=bool(self.popup and self.popup.winfo_exists() and self.popup.winfo_viewable())
                if visible and self.listbox and self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else 0
                    self._set(self.listbox.get(idx));return 'break'
                # Uncommitted typed text => reveal list and immediately commit first match.
                current=(self.var.get() or '').strip()
                if not (self.selected_value and current==str(self.selected_value).strip()):
                    self._show()
                    if self.listbox and self.listbox.size():
                        _select_index(self,0);self._set(self.listbox.get(0));return 'break'
                # Already committed: allow dialog-level Enter to save.
                return None
            except:return 'break'
        A._navigate=_nav;A._accept_first=_enter
        def init(self,*a,**k):
            prev_init(self,*a,**k)
            self.bind('<Down>',lambda e:self._navigate(1))
            self.bind('<Up>',lambda e:self._navigate(-1))
            self.bind('<Return>',self._accept_first)
            self.bind('<KP_Enter>',self._accept_first)
        A.__init__=init
    except:pass

    # InlineChoice: same behavior, no focus transfer to Listbox.
    try:
        I=M.InlineChoice
        def _inav(self,delta):
            try:
                self.show()
                if not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0;nxt=max(0,min(self.listbox.size()-1,cur+delta))
                self.listbox.selection_clear(0,'end');self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt);self.entry.focus_set();return 'break'
            except:return 'break'
        def _ienter(self,event=None):
            try:
                if self._shown and self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else 0;self._set(self.listbox.get(idx));return 'break'
                current=(self.var.get() or '').strip()
                if current not in self.values:
                    self.show()
                    if self.listbox.size():self._set(self.listbox.get(0));return 'break'
                return None
            except:return 'break'
        I._navigate=_inav;I._accept_entry=_ienter
    except:pass

    # --- 2) Dialog geometry based on Windows WORK AREA (excludes taskbar) on the actual monitor. ---
    # Dialog sizing/maximize is owned by v770/dialog_chrome.

    # --- 3) Request contacts: most-used in THIS company, then last used, then Czech alphabetic name/email. ---
    try:
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
                rows=con.execute("""SELECT p.id,p.name,p.email,p.role,coalesce(u.use_count,0) use_count,coalesce(u.last_used,'') last_used
                    FROM people p LEFT JOIN recipient_usage u ON u.company_id=p.company_id AND u.person_id=p.id
                    WHERE p.active=1 AND p.company_id=?
                    ORDER BY coalesce(u.use_count,0) DESC,coalesce(u.last_used,'') DESC,p.name COLLATE CZECH,p.email COLLATE NOCASE""",(cid,)).fetchall()
            selected_set={x.strip().lower() for x in (selected or []) if x and x.strip()};with_email=0
            for rr in rows:
                email=(rr['email'] or '').strip();with_email+=1 if email else 0;label=(rr['name'] or '').strip() or '(bez jména)'
                if rr['role']:label+=f" · {rr['role']}"
                label+=f' — {email}' if email else ' — bez e-mailu'
                var=M.tk.BooleanVar(value=email.lower() in selected_set if email else False);cb=M.ttk.Checkbutton(frame,text=label,variable=var)
                if not email:cb.state(['disabled'])
                cb.pack(anchor='w',pady=2);self.contact_vars.append((var,email))
            nm=company['official_name'] if company else self.company.get()
            if hasattr(self,'contact_count_label'):self.contact_count_label.config(text=f'{nm} · nejpoužívanější kontakty nahoře, ostatní abecedně')
        M.RequestDialog.load_contacts=load_contacts
    except:pass

    # --- 4) Next step: indexes specifically for recipient ranking and audit archive. ---
    try:
        with M.db() as c:
            c.execute('CREATE INDEX IF NOT EXISTS idx_recipient_usage_rank ON recipient_usage(company_id,use_count DESC,last_used DESC)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_people_company_active_name ON people(company_id,active,name)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_active_archive ON audit_history(created_at DESC,undone)')
    except:pass

    # Legacy help composition removed in 8.0; professional_workflow owns help.
