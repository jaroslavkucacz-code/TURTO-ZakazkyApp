# TURTO CRM 6.0.18 - definitive autocomplete/input owner


def apply(M):
    # 1) Definitive Enter behavior at dialog level.
    # Even if an older widget binding fails to stop propagation, the dialog itself
    # must commit an unconfirmed AutocompleteEntry BEFORE running OK/Save.
    def bind_dialog_keys(win, confirm_callback):
        def _commit_autocomplete(widget):
            try:
                if not isinstance(widget, M.AutocompleteEntry):
                    return False
                current = (widget.var.get() or '').strip()
                # Already committed exact value: this Enter may continue to dialog OK.
                if widget.selected_value and current == str(widget.selected_value).strip():
                    return False
                matches = widget._matches()
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
                widget = event.widget
                if widget.winfo_class() == 'Text':
                    return None
                # First Enter in autocomplete = choose suggestion, never save dialog.
                if _commit_autocomplete(widget):
                    return 'break'
                # If focus is currently in the autocomplete listbox, resolve its owner.
                for autocomplete in list(getattr(M, '_AUTOCOMPLETE_ENTRIES', []) or []):
                    try:
                        if getattr(autocomplete, 'listbox', None) is widget:
                            selection = widget.curselection()
                            index = selection[0] if selection else 0
                            if widget.size():
                                autocomplete._set(widget.get(index))
                            return 'break'
                    except Exception:
                        pass
                if hasattr(win, 'topic_entry') and str(widget).startswith(str(win.topic_entry)):
                    return None
            except Exception:
                pass
            confirm_callback()
            return 'break'

        def _escape(_event):
            try:
                win.destroy()
            except Exception:
                pass
            return 'break'

        win.bind('<Return>', _enter)
        win.bind('<KP_Enter>', _enter)
        win.bind('<Escape>', _escape)

    M.bind_dialog_keys = bind_dialog_keys

    # 2) Canonical autocomplete keyboard model.
    # Keep focus in Entry; build the popup only when necessary. Rebuilding on every
    # arrow press resets the list selection to row 0 and was the reason Down appeared
    # to work only once in Supplier/Customer and similar fields.
    try:
        A = M.AutocompleteEntry
        old_show = A._show

        def show(self):
            result = old_show(self)
            try:
                if self.popup and self.popup.winfo_exists():
                    self.popup.attributes('-topmost', False)
                    self.popup.transient(self.winfo_toplevel())
                if self.listbox and self.listbox.size():
                    selection = self.listbox.curselection()
                    if not selection:
                        self.listbox.selection_set(0)
                        self.listbox.activate(0)
                        self.listbox.see(0)
                    self.focus_set()
            except Exception:
                pass
            return result

        def enter(self, event=None):
            try:
                current = (self.var.get() or '').strip()
                if self.selected_value and current == str(self.selected_value).strip():
                    return None
                matches = self._matches()
                if matches:
                    if self.listbox and self.listbox.curselection():
                        value = self.listbox.get(self.listbox.curselection()[0])
                    else:
                        value = matches[0]
                    self._set(value)
                    return 'break'
                return 'break'
            except Exception:
                return 'break'

        def navigate(self, delta):
            try:
                visible = False
                try:
                    visible = bool(
                        self.popup
                        and self.popup.winfo_exists()
                        and self.popup.winfo_viewable()
                        and self.listbox
                    )
                except Exception:
                    visible = False

                # Important: do not call _show() again for an already visible popup;
                # _show() refills the Listbox and resets selection to the first row.
                if not visible:
                    self._show()

                if not self.listbox or not self.listbox.size():
                    return 'break'

                size = self.listbox.size()
                selection = self.listbox.curselection()
                if not visible:
                    # Opening with Down selects the first result; Up selects the last.
                    next_index = 0 if delta > 0 else size - 1
                else:
                    current_index = selection[0] if selection else (0 if delta > 0 else size - 1)
                    next_index = max(0, min(size - 1, current_index + delta))

                self.listbox.selection_clear(0, 'end')
                self.listbox.selection_set(next_index)
                self.listbox.activate(next_index)
                self.listbox.see(next_index)
                self.focus_set()
                return 'break'
            except Exception:
                return 'break'

        A._show = show
        A._accept_first = enter
        A._navigate = navigate

        previous_init = A.__init__

        def init(self, *args, **kwargs):
            previous_init(self, *args, **kwargs)
            # Rebind after older compatibility layers so all AutocompleteEntry fields
            # share one deterministic keyboard model.
            self.bind('<Return>', self._accept_first)
            self.bind('<KP_Enter>', self._accept_first)
            self.bind('<Down>', lambda _event: self._navigate(1))
            self.bind('<Up>', lambda _event: self._navigate(-1))

        A.__init__ = init
    except Exception:
        pass

    # 3) Poptávka – guarantee that "Poptáváno" uses the materials catalogue.
    # The base dialog already has item_box; this refresh prevents stale/empty values
    # after catalogue edits and older feature layers.
    try:
        RequestDialog = M.RequestDialog
        old_request_init = RequestDialog.__init__

        def request_init(self, *args, **kwargs):
            old_request_init(self, *args, **kwargs)
            try:
                with M.db() as con:
                    values = [
                        row['name']
                        for row in con.execute(
                            "SELECT name FROM materials "
                            "WHERE trim(coalesce(name,''))<>'' "
                            "ORDER BY name COLLATE CZECH"
                        )
                    ]
                if hasattr(self, 'item_box') and isinstance(self.item_box, M.AutocompleteEntry):
                    self.item_box.set_values(values)
                    self.item_box.bind(
                        '<FocusIn>',
                        lambda _event: self._refresh_material_suggestions(),
                        add='+',
                    )
                self.materials = [{'name': value} for value in values]
            except Exception:
                pass

        def refresh_material_suggestions(self):
            try:
                with M.db() as con:
                    values = [
                        row['name']
                        for row in con.execute(
                            "SELECT name FROM materials "
                            "WHERE trim(coalesce(name,''))<>'' "
                            "ORDER BY name COLLATE CZECH"
                        )
                    ]
                if hasattr(self, 'item_box'):
                    self.item_box.set_values(values)
            except Exception:
                pass

        RequestDialog._refresh_material_suggestions = refresh_material_suggestions
        RequestDialog.__init__ = request_init
    except Exception:
        pass

    # 4) Příležitost – Obchodník uses the same AutocompleteEntry as companies.
    # The previous readonly Combobox had different and unreliable arrow behavior.
    try:
        ActionDialog = M.ActionDialog
        old_action_init = ActionDialog.__init__

        def action_init(self, *args, **kwargs):
            old_action_init(self, *args, **kwargs)
            try:
                old_box = getattr(self, 'salesperson_box', None)
                if old_box is None or isinstance(old_box, M.AutocompleteEntry):
                    return
                parent = old_box.master
                old_box.destroy()
                values = [row['name'] for row in self.sales]
                self.salesperson_box = M.AutocompleteEntry(
                    parent,
                    textvariable=self.salesperson,
                    values=values,
                )
                self.salesperson_box.grid(row=0, column=0, sticky='ew')
                current = (self.salesperson.get() or '').strip()
                if current in values:
                    self.salesperson_box.selected_value = current
            except Exception:
                pass

        def manage_salespeople(self):
            app = M.find_app(self)
            if not app:
                return
            app.manage_code_lists('Obchodníci', self)
            with M.db() as con:
                self.sales = con.execute(
                    "SELECT id,name FROM salespeople "
                    "WHERE active=1 ORDER BY name COLLATE CZECH"
                ).fetchall()
            values = [row['name'] for row in self.sales]
            box = getattr(self, 'salesperson_box', None)
            if isinstance(box, M.AutocompleteEntry):
                box.set_values(values)
            elif box is not None:
                try:
                    box.configure(values=values)
                except Exception:
                    pass

        ActionDialog.__init__ = action_init
        ActionDialog.manage_salespeople = manage_salespeople
    except Exception:
        pass

    # 5) Help note.
    try:
        old_help = M.App.build_help

        def help_page(self):
            result = old_help(self)
            try:
                import tkinter as tk
                texts = []

                def walk(widget):
                    if isinstance(widget, tk.Text):
                        texts.append(widget)
                    for child in widget.winfo_children():
                        walk(child)

                walk(self.tabs['help'])
                for text in texts:
                    text.configure(state='normal')
                    text.insert(
                        'end',
                        '\n\nAKTUÁLNÍ OVLÁDÁNÍ VÝBĚRŮ\n'
                        'Našeptávače Dodavatele, Odběratele, Akce, Poptávaného zboží '
                        'a Obchodníka používají stejný model: ↑/↓ opakovaně mění '
                        'zvýrazněnou položku, Enter ji potvrdí a fokus zůstává v poli.',
                    )
                    text.configure(state='disabled')
            except Exception:
                pass
            return result

        M.App.build_help = help_page
    except Exception:
        pass
