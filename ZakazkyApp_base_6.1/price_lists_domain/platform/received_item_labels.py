"""Offer-local internal identities; supplier data and catalogue stay independent."""
from __future__ import annotations


def ensure_columns(con):
    columns = {row[1] for row in con.execute('PRAGMA table_info(supplier_offer_items)')}
    if not columns:
        return
    added = False
    for name in ('internal_code', 'internal_name'):
        if name not in columns:
            con.execute(f"ALTER TABLE supplier_offer_items ADD COLUMN {name} TEXT DEFAULT ''")
            added = True
    if added and con.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='project_activity_823_supplier_offer_items_update'").fetchone():
        # Existing 8.0.23 triggers must also observe the newly added business fields.
        con.execute('DROP TRIGGER IF EXISTS project_activity_823_supplier_offer_items_update')
        from .project_activity import ensure_schema
        ensure_schema(con)


def from_original(row, suffix=''):
    original = str(row.get('original_name') or row.get('item_key') or '').strip()
    suffix = str(suffix or '').strip().lstrip('-–— ').strip()
    return original, original + (' - ' + suffix if original and suffix else '')


def load_items(M, offer_id, item_ids):
    ids = list(dict.fromkeys(int(value) for value in item_ids))
    if not ids:
        raise ValueError('Vyberte jednu nebo více položek nabídky.')
    with M.db() as con:
        rows = con.execute(
            f'''SELECT id,position,original_name,item_key,product_code,
                       coalesce(internal_code,'') internal_code,coalesce(internal_name,'') internal_name
                FROM supplier_offer_items WHERE offer_id=? AND id IN ({','.join('?' for _ in ids)})
                ORDER BY position,id''', (int(offer_id), *ids)).fetchall()
    if len(rows) != len(ids):
        raise ValueError('Některá položka už v této nabídce neexistuje. Obnovte nabídku.')
    return [dict(row) for row in rows]


def save_items(M, offer_id, drafts, originals):
    """One transaction, with optimistic checks against edits in another window."""
    baseline = {int(row['id']): row for row in originals}
    if len(drafts) != len(baseline) or {int(row['id']) for row in drafts} != set(baseline):
        raise ValueError('Výběr položek se změnil. Otevřete úpravu znovu.')
    with M.db() as con:
        con.execute('BEGIN IMMEDIATE')
        for row in drafts:
            old = baseline[int(row['id'])]
            values = (str(row.get('internal_code') or '').strip(), str(row.get('internal_name') or '').strip())
            result = con.execute('''UPDATE supplier_offer_items SET internal_code=?,internal_name=?
                WHERE offer_id=? AND id=? AND coalesce(internal_code,'')=? AND coalesce(internal_name,'')=?''',
                (*values, int(offer_id), int(row['id']), old['internal_code'], old['internal_name']))
            if result.rowcount != 1:
                raise ValueError('Nabídka byla mezitím změněna nebo znovu zpracována. Otevřete úpravu znovu.')


def matching_labels(previous_rows, *, original_name='', item_key='', product_code='', position=0):
    """Preserve annotations on reparse only for an identified source product.

    Position alone is not identity: a corrected parser may insert/reorder rows.
    Ambiguous duplicate products with different labels must not be cross-assigned.
    """
    for field, value in (('product_code', product_code), ('item_key', item_key), ('original_name', original_name)):
        value = str(value or '').strip().casefold()
        if not value:
            continue
        matches = [dict(row) for row in previous_rows if str(dict(row).get(field) or '').strip().casefold() == value]
        if not matches:
            continue
        if len(matches) > 1:
            same_position = [row for row in matches if int(row.get('position') or 0) == int(position or 0)]
            if len(same_position) == 1:
                matches = same_position
        labels = {(row.get('internal_code') or '', row.get('internal_name') or '') for row in matches}
        return next(iter(labels)) if len(labels) == 1 else ('', '')
    return '', ''


def copy_from_manufacturer(M, offer_id, item_ids, suffix=''):
    originals = load_items(M, offer_id, item_ids)
    drafts = [dict(row) for row in originals]
    for row in drafts:
        row['internal_code'], row['internal_name'] = from_original(row, suffix)
    save_items(M, offer_id, drafts, originals)
    return len(drafts)


class InlineLabels:
    """Cell editing and selection-based copying on the received offer itself."""
    fields = {'Interní kód': 'internal_code', 'Interní označení': 'internal_name'}

    def __init__(self, M, dialog, toolbar, on_saved):
        self.M, self.dialog, self.tree, self.on_saved = M, dialog, dialog.tree, on_saved
        self.entry = None
        self.busy = False
        self.suffix = M.tk.StringVar(master=dialog)
        self.selection_text = M.tk.StringVar(master=dialog)
        bulk = M.ttk.Frame(toolbar)
        bulk.pack(fill='x', pady=(4, 0))
        M.ttk.Label(bulk, text='Dodatek:').pack(side='left')
        M.ttk.Combobox(bulk, textvariable=self.suffix, values=('', 'izolační nosník'), width=22).pack(side='left', padx=6)
        self.copy_button = M.ttk.Button(bulk, text='Převzít od výrobce', command=self.copy_selected)
        self.copy_button.pack(side='left', padx=(0, 10))
        M.ttk.Label(bulk, textvariable=self.selection_text).pack(side='left')
        M.ttk.Label(bulk, text='Výběr více řádků: Ctrl / Shift · Vše: Ctrl+A',
                    style='PageSubtitle.TLabel').pack(side='right')
        self.tree.bind('<Double-1>', self.double_click)
        self.tree.bind('<F2>', self.begin_selected, add='+')
        self.tree.bind('<Control-a>', self.select_all, add='+')
        self.tree.bind('<Control-A>', self.select_all, add='+')
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed, add='+')
        self.tree.bind('<Configure>', self.reposition, add='+')
        # Scrollbar commands may change row/cell coordinates without a Configure.
        for option in ('xscrollcommand', 'yscrollcommand'):
            previous = self.tree.cget(option)
            def scrolled(first, last, callback=previous):
                if callback:
                    self.tree.tk.call(*self.tree.tk.splitlist(callback), first, last)
                if self.entry is not None:
                    self.tree.after_idle(self.reposition)
            self.tree.configure(**{option: scrolled})
        self.selection_changed()

    def visible_columns(self):
        displayed = tuple(self.tree.cget('displaycolumns'))
        return tuple(self.tree.cget('columns')) if displayed == ('#all',) else displayed

    def select_all(self, _=None):
        if self.commit():
            self.tree.selection_set(self.tree.get_children())
        return 'break'

    def selection_changed(self, _=None):
        count = len(self.tree.selection())
        self.selection_text.set(f'Vybráno: {count}')
        self.copy_button.state(['!disabled'] if count else ['disabled'])

    def double_click(self, event):
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return 'break'
        iid = self.tree.identify_row(event.y)
        token = self.tree.identify_column(event.x)
        column = str(self.tree.column(token, 'id'))
        if column in self.fields:
            self.begin(iid, column)
        elif self.commit():
            self.tree.selection_set(iid); self.tree.focus(iid)
            self.dialog.open_history()
        return 'break'

    def begin_selected(self, _=None):
        selected = self.tree.selection()
        if selected:
            visible = self.visible_columns()
            column = next((name for name in ('Interní označení', 'Interní kód') if name in visible), None)
            if column:
                self.begin(self.tree.focus() or selected[0], column)
        return 'break'

    def begin(self, iid, column):
        if column not in self.fields or not self.tree.exists(iid) or not self.commit():
            return
        try:
            self.original = load_items(self.M, self.dialog.oid, [int(iid[1:])])[0]
        except Exception as exc:
            self.M.messagebox.showerror('Interní označení', str(exc), parent=self.dialog)
            return
        self.tree.see(iid)
        visible = self.visible_columns()
        if column not in visible:
            return
        self.tree.update_idletasks()
        box = self.tree.bbox(iid, column)
        if not box or box[0] < 0 or box[0] + box[2] > self.tree.winfo_width():
            widths = [int(self.tree.column(name, 'width')) for name in visible]
            self.tree.xview_moveto(sum(widths[:visible.index(column)]) / max(1, sum(widths)))
        self.iid, self.column = iid, column
        self.variable = self.M.tk.StringVar(master=self.dialog, value=self.original[self.fields[column]])
        self.entry = self.M.ttk.Entry(self.tree, textvariable=self.variable)
        self.entry._turto_own_input_navigation = True
        self.reposition()
        if self.entry is None:
            return
        self.entry.focus_set(); self.entry.selection_range(0, 'end')
        self.entry.bind('<Return>', lambda _e: self.finish())
        self.entry.bind('<Escape>', lambda _e: self.cancel())
        self.entry.bind('<Tab>', lambda _e: self.next_cell())
        self.entry.bind('<Shift-Tab>', lambda _e: self.next_cell(True))
        self.entry.bind('<ISO_Left_Tab>', lambda _e: self.next_cell(True))
        self.entry.bind('<FocusOut>', lambda _e: self.focus_left())

    def reposition(self, _=None):
        if self.entry is None or not self.entry.winfo_exists():
            return
        box = self.tree.bbox(self.iid, self.column)
        if not box or box[0]+box[2] <= 0 or box[0] >= self.tree.winfo_width():
            self.commit()
            return
        x,y,width,height = box
        left = max(1, x)
        self.entry.place(x=left, y=y, width=max(1, min(x+width, self.tree.winfo_width()-1)-left), height=height)

    def focus_left(self):
        entry = self.entry
        def finish():
            if entry is not None and self.entry is entry and self.dialog.winfo_exists():
                if self.dialog.focus_get() is not entry:
                    self.commit()
        self.tree.after_idle(finish)

    def discard_editor(self):
        entry, self.entry = self.entry, None
        if entry is not None and entry.winfo_exists():
            entry.destroy()

    def commit(self):
        if self.entry is None:
            return True
        if self.busy:
            return False
        self.busy = True
        try:
            draft = dict(self.original)
            draft[self.fields[self.column]] = self.variable.get().strip()
            if draft != self.original:
                save_items(self.M, self.dialog.oid, [draft], [self.original])
            self.discard_editor()
            self.on_saved()
            return True
        except Exception as exc:
            self.M.messagebox.showerror('Interní označení', str(exc), parent=self.dialog)
            if self.entry is not None:
                self.entry.focus_set()
            return False
        finally:
            self.busy = False

    def finish(self):
        if self.commit():
            self.tree.focus_set()
        return 'break'

    def cancel(self):
        self.discard_editor(); self.tree.focus_set()
        return 'break'

    def next_cell(self, backwards=False):
        current = (self.iid, self.column)
        columns = [name for name in self.visible_columns() if name in self.fields]
        cells = [(iid, column) for iid in self.tree.get_children() for column in columns]
        if current in cells and self.commit():
            position = cells.index(current) + (-1 if backwards else 1)
            if 0 <= position < len(cells):
                iid,column = cells[position]
                self.tree.selection_set(iid); self.tree.focus(iid)
                self.begin(iid,column)
            else:
                self.tree.focus_set()
        return 'break'

    def copy_selected(self):
        if not self.commit():
            return
        ids = [int(str(iid)[1:]) for iid in self.tree.selection() if str(iid).startswith('i')]
        if not ids:
            return
        try:
            count = copy_from_manufacturer(self.M, self.dialog.oid, ids, self.suffix.get())
            self.on_saved()
            self.selection_text.set(f'Uloženo pro {count} položek')
        except Exception as exc:
            self.M.messagebox.showerror('Interní označení', str(exc), parent=self.dialog)


def open_editor(M, parent, offer_id, item_ids, on_saved):
    from . import form_behavior_817
    originals = load_items(M, offer_id, item_ids)
    drafts = {str(row['id']): dict(row) for row in originals}
    win = M.tk.Toplevel(parent)
    win.title('Interní označení položek')
    M.enable_dialog_maximize(win, 1000, 650)
    win.transient(parent); win.grab_set()
    outer = M.ttk.Frame(win, padding=16); outer.pack(fill='both', expand=True)
    outer.columnconfigure(0, weight=1); outer.rowconfigure(3, weight=1)
    M.ttk.Label(outer, text='Interní kód a označení vybraných položek', style='Section.TLabel').grid(row=0,column=0,sticky='w')
    M.ttk.Label(outer, text='Kód = původní název. Označení = původní název + volitelný dodatek.',
                style='PageSubtitle.TLabel').grid(row=1,column=0,sticky='w',pady=(4,10))
    bulk = M.ttk.Frame(outer); bulk.grid(row=2,column=0,sticky='ew',pady=(0,10))
    suffix = M.tk.StringVar(master=win)
    M.ttk.Label(bulk,text='Dodatek:').pack(side='left')
    M.ttk.Entry(bulk,textvariable=suffix,width=24).pack(side='left',padx=6)
    table = M.ttk.Frame(outer); table.grid(row=3,column=0,sticky='nsew')
    table.columnconfigure(0,weight=1); table.rowconfigure(0,weight=1)
    tree = M.ttk.Treeview(table,columns=('Původní název','Interní kód','Interní označení'),show='headings',selectmode='browse',
                          name='layout__received_item_labels__editor_tree')
    tree._turto_fill_last_column = False
    for column,width in zip(tree.cget('columns'),(300,260,380)):
        tree.heading(column,text=column); tree.column(column,width=width,minwidth=30,stretch=False)
    tree.grid(row=0,column=0,sticky='nsew')
    sx=M.ttk.Scrollbar(table,orient='horizontal',command=tree.xview); sx.grid(row=1,column=0,sticky='ew')
    sy=M.ttk.Scrollbar(table,orient='vertical',command=tree.yview); sy.grid(row=0,column=1,sticky='ns')
    tree.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
    fields=M.ttk.Frame(outer); fields.grid(row=4,column=0,sticky='ew',pady=12); fields.columnconfigure(1,weight=1)
    code=M.tk.StringVar(master=win); name=M.tk.StringVar(master=win)
    M.ttk.Label(fields,text='Interní kód').grid(row=0,column=0,sticky='w',padx=(0,10))
    M.ttk.Entry(fields,textvariable=code).grid(row=0,column=1,sticky='ew',pady=3)
    M.ttk.Label(fields,text='Interní označení').grid(row=1,column=0,sticky='w',padx=(0,10))
    M.ttk.Entry(fields,textvariable=name).grid(row=1,column=1,sticky='ew',pady=3)
    state={'selected':None,'loading':False}

    def paint(iid):
        row=drafts[iid]; values=(row['original_name'],row['internal_code'],row['internal_name'])
        if tree.exists(iid):tree.item(iid,values=values)
        else:tree.insert('','end',iid=iid,values=values)

    def select(_=None):
        selected=tree.selection()
        if not selected:return
        state['selected']=selected[0]; state['loading']=True
        row=drafts[selected[0]]; code.set(row['internal_code']); name.set(row['internal_name'])
        state['loading']=False

    def edited(*_):
        if state['loading'] or state['selected'] is None:return
        row=drafts[state['selected']]; row['internal_code']=code.get(); row['internal_name']=name.get()
        paint(state['selected'])

    def fill(beam=False):
        if beam:suffix.set('izolační nosník')
        for iid,row in drafts.items():
            row['internal_code'],row['internal_name']=from_original(row,suffix.get()); paint(iid)
        select()

    M.ttk.Button(bulk,text='Převzít původní názvy',command=fill).pack(side='left',padx=4)
    M.ttk.Button(bulk,text='Izolační nosníky',command=lambda:fill(True)).pack(side='left',padx=4)
    for iid in drafts:paint(iid)
    tree.bind('<<TreeviewSelect>>',select)
    code.trace_add('write',edited); name.trace_add('write',edited)
    first=next(iter(drafts)); tree.selection_set(first); tree.focus(first); select()

    def save():
        try:save_items(M,offer_id,list(drafts.values()),originals)
        except Exception as exc:
            M.messagebox.showerror('Interní označení',str(exc),parent=win); return False
        win.destroy()
        on_saved()
        return True

    buttons=M.ttk.Frame(outer); buttons.grid(row=5,column=0,sticky='w')
    M.ttk.Button(buttons,text='Uložit',style='Accent.TButton',command=save).pack(side='left')
    M.ttk.Button(buttons,text='Zrušit',command=win.destroy).pack(side='left',padx=8)
    form_behavior_817.register(M,win,save,snapshot=lambda:(suffix.get(),tuple(
        (iid,row['internal_code'],row['internal_name']) for iid,row in drafts.items())))
    # Public controls also support deterministic Windows UI regression checks.
    win.item_tree=tree; win.internal_code=code; win.internal_name=name; win.suffix=suffix
    return win
