# TURTO CRM 6.0.15 - autocomplete focus/selection model + help touch-up

def apply(M):
    # Floating AutocompleteEntry: keep typing focus in the entry, but maintain a visible active row in the popup.
    try:
        A=M.AutocompleteEntry
        previous_init=A.__init__
        def navigate(self,delta):
            try:
                self._show()
                if not self.listbox or not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0
                nxt=max(0,min(self.listbox.size()-1,cur+delta))
                self.listbox.selection_clear(0,'end');self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt)
                self.focus_set()
                return 'break'
            except:return 'break'
        def accept(self,e=None):
            try:
                if self.popup and self.popup.winfo_exists() and self.popup.winfo_viewable() and self.listbox and self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else self.listbox.index('active')
                    if idx<0:idx=0
                    self._set(self.listbox.get(idx));return 'break'
                if self.selected_value and (self.var.get() or '').strip()==str(self.selected_value).strip():return None
                self._show()
                if self.listbox and self.listbox.size():self._set(self.listbox.get(0));return 'break'
                return None
            except:return 'break'
        A._navigate=navigate;A._accept_first=accept
        def init(self,*a,**k):
            previous_init(self,*a,**k)
            # Rebind after older compatibility layers so Enter always uses the current focus/selection model.
            self.bind('<Return>',self._accept_first)
            self.bind('<KP_Enter>',self._accept_first)
            self.bind('<Down>',lambda e:self._navigate(1))
            self.bind('<Up>',lambda e:self._navigate(-1))
        A.__init__=init
    except:pass

    # InlineChoice uses the same keyboard model.
    try:
        I=M.InlineChoice
        def inav(self,delta):
            try:
                self.show()
                if not self.listbox.size():return 'break'
                sel=self.listbox.curselection();cur=sel[0] if sel else 0
                nxt=max(0,min(self.listbox.size()-1,cur+delta))
                self.listbox.selection_clear(0,'end');self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt)
                self.entry.focus_set();return 'break'
            except:return 'break'
        def iaccept(self,e=None):
            try:
                if self._shown and self.listbox.size():
                    sel=self.listbox.curselection();idx=sel[0] if sel else self.listbox.index('active');idx=max(0,idx)
                    self._set(self.listbox.get(idx));return 'break'
                if (self.var.get() or '').strip() in self.values:return None
                self.show()
                if self.listbox.size():self._set(self.listbox.get(0));return 'break'
                return None
            except:return 'break'
        I._navigate=inav;I._accept_entry=iaccept
    except:pass

    # Help remains version-aware; append current keyboard/audit behavior without replacing the branched help structure.
    old_help=M.App.build_help
    def help_page(self):
        r=old_help(self)
        try:
            p=self.tabs['help']
            import tkinter as tk
            texts=[]
            def walk(w):
                if isinstance(w,tk.Text):texts.append(w)
                for c in w.winfo_children():walk(c)
            walk(p)
            for txt in texts:
                txt.configure(state='normal')
                txt.insert('end','\n\nAKTUÁLNÍ OVLÁDÁNÍ 6.0.15\nNašeptávače: první výsledek je zvýrazněný už při psaní, kurzor zůstává v textovém poli. ↑/↓ mění zvýrazněný výsledek a Enter jej potvrdí včetně interní vazby/ID. Po potvrzení lze dalším Enterem potvrdit celý dialog.\nADMIN HISTORIE: aktivní změny jsou 14 dní; starší audit je read-only archiv. U jednoduchých Úkolů a Poptávek se rozšiřuje bezpečné Undo také na vytvoření a smazání, pokud databázové vazby návrat dovolí.')
                txt.configure(state='disabled')
        except:pass
        return r
    M.App.build_help=help_page
