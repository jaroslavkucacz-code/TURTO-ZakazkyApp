# TURTO CRM 6.0.18 - definitive autocomplete Enter guard + request material suggestions

def apply(M):
    # 1) Definitive Enter behavior at dialog level.
    # Even if an older widget binding fails to stop propagation, the dialog itself
    # must commit an unconfirmed AutocompleteEntry BEFORE running OK/Save.
    def bind_dialog_keys(win,confirm_callback):
        def _commit_autocomplete(widget):
            try:
                if not isinstance(widget,M.AutocompleteEntry):
                    return False
                current=(widget.var.get() or '').strip()
                # Already committed exact value: this Enter may continue to dialog OK.
                if widget.selected_value and current==str(widget.selected_value).strip():
                    return False
                matches=widget._matches()
                if matches:
                    # Use the same _set path as mouse selection: this also sets payload/ID
                    # and generates <<AutocompleteSelected>>.
                    widget._set(matches[0])
                    return True
                return False
            except Exception:
                return False
        def _enter(event):
            try:
                w=event.widget
                if w.winfo_class()=='Text':return None
                # First Enter in autocomplete = choose suggestion, never save dialog.
                if _commit_autocomplete(w):return 'break'
                # If focus is currently in the autocomplete listbox, resolve its owner.
                for ac in list(getattr(M,'_AUTOCOMPLETE_ENTRIES',[]) or []):
                    try:
                        if getattr(ac,'listbox',None) is w:
                            sel=w.curselection();idx=sel[0] if sel else 0
                            if w.size():ac._set(w.get(idx))
                            return 'break'
                    except Exception:pass
                if hasattr(win,'topic_entry') and str(w).startswith(str(win.topic_entry)):
                    return None
            except Exception:pass
            confirm_callback();return 'break'
        def _escape(event):
            try:win.destroy()
            except Exception:pass
            return 'break'
        win.bind('<Return>',_enter)
        win.bind('<KP_Enter>',_enter)
        win.bind('<Escape>',_escape)
    M.bind_dialog_keys=bind_dialog_keys

    # 2) Autocomplete itself: one result or first result can always be accepted
    # immediately with Enter; arrows are optional. Popup never becomes global topmost.
    try:
        A=M.AutocompleteEntry
        old_show=A._show
        def show(self):
            r=old_show(self)
            try:
                if self.popup and self.popup.winfo_exists():
                    self.popup.attributes('-topmost',False)
                    self.popup.transient(self.winfo_toplevel())
                if self.listbox and self.listbox.size():
                    # Keep first/current result visually selected while focus remains in Entry.
                    sel=self.listbox.curselection()
                    if not sel:
                        self.listbox.selection_set(0);self.listbox.activate(0);self.listbox.see(0)
                    self.focus_set()
            except Exception:pass
            return r
        def enter(self,event=None):
            try:
                current=(self.var.get() or '').strip()
                if self.selected_value and current==str(self.selected_value).strip():
                    return None
                matches=self._matches()
                if matches:
                    self._set(matches[0] if not (self.listbox and self.listbox.curselection()) else self.listbox.get(self.listbox.curselection()[0]))
                    return 'break'
                return 'break'
            except Exception:return 'break'
        def navigate(self,delta):
            try:
                self._show()
                if not self.listbox or not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0
                nxt=max(0,min(self.listbox.size()-1,cur+delta))
                self.listbox.selection_clear(0,'end');self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt)
                self.focus_set();return 'break'
            except Exception:return 'break'
        A._show=show;A._accept_first=enter;A._navigate=navigate
        prev_init=A.__init__
        def init(self,*a,**k):
            prev_init(self,*a,**k)
            self.bind('<Return>',self._accept_first)
            self.bind('<KP_Enter>',self._accept_first)
            self.bind('<Down>',lambda e:self._navigate(1))
            self.bind('<Up>',lambda e:self._navigate(-1))
        A.__init__=init
    except Exception:pass

    # 3) Poptávka – guarantee that "Poptáváno" uses the materials catalogue.
    # The base dialog already has item_box; this refresh prevents stale/empty values
    # after catalogue edits and older patch layers.
    try:
        RD=M.RequestDialog
        old_init=RD.__init__
        def request_init(self,*a,**k):
            old_init(self,*a,**k)
            try:
                with M.db() as con:
                    vals=[r['name'] for r in con.execute("SELECT name FROM materials WHERE trim(coalesce(name,''))<>'' ORDER BY name COLLATE CZECH")]
                if hasattr(self,'item_box') and isinstance(self.item_box,M.AutocompleteEntry):
                    self.item_box.set_values(vals)
                    # Keep the catalogue live after + Přidat / Spravovat changes.
                    self.item_box.bind('<FocusIn>',lambda e:self._refresh_material_suggestions(),add='+')
                self.materials=[{'name':v} for v in vals]
            except Exception:pass
        def refresh_material_suggestions(self):
            try:
                with M.db() as con:
                    vals=[r['name'] for r in con.execute("SELECT name FROM materials WHERE trim(coalesce(name,''))<>'' ORDER BY name COLLATE CZECH")]
                if hasattr(self,'item_box'):self.item_box.set_values(vals)
            except Exception:pass
        RD._refresh_material_suggestions=refresh_material_suggestions
        RD.__init__=request_init
    except Exception:pass

    # 4) Help note.
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                texts=[]
                def walk(w):
                    if isinstance(w,tk.Text):texts.append(w)
                    for c in w.winfo_children():walk(c)
                walk(self.tabs['help'])
                for txt in texts:
                    txt.configure(state='normal')
                    txt.insert('end','\n\nOVLÁDÁNÍ 6.0.18\nNašeptávače: šipka dolů není nutná. Pokud existuje jedna nebo více odpovídajících položek, první Enter vybere aktuálně zvýrazněnou/ první nabídku včetně interního ID; teprve další Enter může potvrdit dialog. Pole Poptáváno v Poptávce používá stejný našeptávač nad číselníkem Poptávané zboží a seznam se obnovuje po návratu do pole.')
                    txt.configure(state='disabled')
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
