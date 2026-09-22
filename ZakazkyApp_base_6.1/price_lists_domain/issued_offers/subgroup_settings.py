"""Multi-selection controls for template-owned subgroup presentation."""
from contextlib import closing
import copy
import sqlite3
import unicodedata
from . import subgroup_layout, template_layout


class SubgroupSettings:
    def __init__(self, editor, parent):
        self.editor, self.M = editor, editor.M
        M = self.M
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(2, weight=1)
        self.search = M.tk.StringVar()
        M.ttk.Label(parent, text='Vyberte podskupiny v seznamu nebo přímo v PDF.', wraplength=460).grid(row=0, column=0, sticky='w')
        M.ttk.Entry(parent, textvariable=self.search).grid(row=1, column=0, sticky='ew', pady=5)
        box = M.ttk.Frame(parent)
        box.grid(row=2, column=0, sticky='nsew')
        box.rowconfigure(0, weight=1); box.columnconfigure(0, weight=1)
        self.tree = M.ttk.Treeview(box, columns=('mode',), selectmode='extended', height=7,
                                   name='layout__issued_offers_subgroup_settings__subgroups')
        self.tree.heading('#0', text='Skupina / podskupina')
        self.tree.heading('mode', text='Vzhled')
        self.tree.column('#0', width=315, minwidth=180)
        self.tree.column('mode', width=85, minwidth=75, stretch=False)
        self.tree.grid(row=0, column=0, sticky='nsew')
        scroll = M.ttk.Scrollbar(box, orient='vertical', command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns'); self.tree.configure(yscrollcommand=scroll.set)
        bar = M.ttk.Frame(parent); bar.grid(row=3, column=0, sticky='ew', pady=5)
        M.ttk.Button(bar, text='Vybrat vše', command=self.select_all).pack(side='left')
        M.ttk.Button(bar, text='Použít společné nastavení', command=self.inherit).pack(side='left', padx=5)
        self.selection_label = M.tk.StringVar()
        M.ttk.Label(parent, textvariable=self.selection_label, wraplength=460).grid(row=4, column=0, sticky='w', pady=(0, 6))
        fields = M.ttk.LabelFrame(parent, text='Údaje v položkách vybraných podskupin', padding=8)
        fields.grid(row=5, column=0, sticky='ew')
        fields.columnconfigure(0, weight=1); fields.columnconfigure(1, weight=1)
        labels = [('col:' + k, template_layout.COLUMNS[k][0]) for k in
                  ('name', 'image', 'position', 'code', 'unit_price', 'quantity', 'total', 'recommended', 'discount')]
        labels += [('show_description', 'Popis pod názvem'), ('show_code', 'Kód u názvu'), ('show_line_note', 'Poznámka položky')]
        self.variables, self.buttons = {}, {}
        for i, (key, title) in enumerate(labels):
            var = M.tk.IntVar(value=0); self.variables[key] = var
            button = M.ttk.Checkbutton(fields, text=title, variable=var, onvalue=1, offvalue=0,
                                      command=lambda k=key: self.apply_change(k, bool(self.variables[k].get())))
            button.grid(row=i // 2, column=i % 2, sticky='w', padx=3, pady=3)
            self.buttons[key] = button
        M.ttk.Label(parent, text='Ctrl / Shift: více podskupin. Výběr skupiny zahrne její podskupiny. '
                    'Smíšená volba zůstane beze změny, dokud ji nepřepnete. Souhrnné ceny se nastavují společně.',
                    wraplength=460).grid(row=6, column=0, sticky='w', pady=8)
        self.records = {}; self.updating = False
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        self.tree.bind('<Control-a>', lambda e: self.select_all())
        self.search.trace_add('write', lambda *_: self.filter())

    def layout(self):
        result = dict(self.editor.layout, columns=copy.deepcopy(self.editor.columns),
                      subgroup_layouts=copy.deepcopy(self.editor.subgroup_rules))
        result['show_images'] = self.editor.layout_vars['show_images'].get()
        return result

    def load(self):
        from .template_settings import sample_offer
        selected_keys = {subgroup_layout.key(r) for r in self.targets()}
        records = {}
        for item in (self.editor.preview_items or sample_offer()[1]):
            if item.get('row_type', 'product') == 'product':
                value = subgroup_layout.scope(item); records[subgroup_layout.key(value)] = value
        try:
            with closing(self.M.db()) as con:
                rows = con.execute('SELECT s.id, s.category_id, s.name, c.name FROM product_subgroups s '
                                   'JOIN product_categories c ON c.id=s.category_id WHERE s.active=1 AND c.active=1').fetchall()
            for sid, cid, name, category in rows:
                value = dict(category_id=cid, subgroup_id=sid, category=category, subgroup=name)
                # Bind name-only preview groups to the existing catalogue identity.
                for old in list(records):
                    if old[0] == 'names' and subgroup_layout.names(records[old]) == subgroup_layout.names(value):
                        del records[old]
                records[subgroup_layout.key(value)] = value
        except sqlite3.Error:
            pass  # Historical/minimal databases still expose groups from the offer.
        for rule in self.editor.subgroup_rules:
            value = subgroup_layout.scope(rule)
            if subgroup_layout.key(value) not in records and not any(subgroup_layout.names(v) == subgroup_layout.names(value) for v in records.values()):
                records[subgroup_layout.key(value)] = value
        self.records = {'s' + str(i): r for i, r in enumerate(sorted(records.values(), key=lambda r: subgroup_layout.names(r)))}
        self.filter(selected_keys)

    def filter(self, selected_keys=None):
        if not hasattr(self.editor, 'subgroup_rules'):
            return
        if selected_keys is None:
            selected_keys = {subgroup_layout.key(r) for r in self.targets()}
        self.updating = True
        self.tree.delete(*self.tree.get_children())
        def folded(text):
            return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not unicodedata.combining(c))
        query = folded(self.search.get())
        parents = {}
        for iid, record in self.records.items():
            if query and query not in folded(record['category'] + ' ' + record['subgroup']):
                continue
            category = record['category']
            if category not in parents:
                parent = 'g' + str(len(parents)); parents[category] = parent
                self.tree.insert('', 'end', iid=parent, text=category, open=True)
            mode = 'Vlastní' if subgroup_layout.find(self.editor.subgroup_rules, record) else 'Společné'
            self.tree.insert(parents[category], 'end', iid=iid, text=record['subgroup'], values=(mode,))
        self.tree.selection_set([i for i, r in self.records.items() if self.tree.exists(i) and subgroup_layout.key(r) in selected_keys])
        self.updating = False
        self.refresh_choices()

    def targets(self):
        selected = []
        for iid in self.tree.selection():
            selected.extend([iid] if iid in self.records else self.tree.get_children(iid))
        return [self.records[i] for i in dict.fromkeys(selected) if i in self.records]

    def select_all(self):
        self.tree.selection_set([i for i in self.records if self.tree.exists(i)])
        self.selected()
        return 'break'

    def select_scope(self, item, add=False):
        target = subgroup_layout.scope(item)
        iid = next((i for i, r in self.records.items() if subgroup_layout.key(r) == subgroup_layout.key(target)), None)
        if iid is None:
            iid = next((i for i, r in self.records.items() if subgroup_layout.names(r) == subgroup_layout.names(target)), None)
        if iid is not None:
            if not self.tree.exists(iid):
                self.search.set('')
            if add:
                if iid in self.tree.selection(): self.tree.selection_remove(iid)
                else: self.tree.selection_add(iid)
            else:
                self.tree.selection_set(iid)
            self.tree.see(iid)
            self.editor.notebook.select(self.editor.tabs['subgroups'])
            self.selected()

    def refresh_choices(self):
        if not hasattr(self.editor, 'layout'):
            return
        targets = self.targets()
        layout = self.layout()
        values = [subgroup_layout.choices(layout, t) for t in targets]
        for key, var in self.variables.items():
            states = {v[key] for v in values}
            var.set(int(next(iter(states))) if len(states) == 1 else -1)
            button = self.buttons[key]
            button.state(['disabled'] if not targets or key == 'col:name' else ['!disabled'])
            button.state(['alternate'] if len(states) > 1 else ['!alternate'])
        label = f'Vybráno podskupin: {len(targets)}' if targets else 'Vyberte podskupinu. Bez vlastní úpravy používá společné sloupce.'
        if len(targets) == 1:
            label = targets[0]['category'] + ' › ' + targets[0]['subgroup']
            if len(label)>110:label=label[:107]+'…'
        self.selection_label.set(label)

    def selected(self, _event=None):
        if self.updating or self.editor.loading:
            return
        self.refresh_choices()
        targets = self.targets()
        if hasattr(self.editor, 'viewer'):
            self.editor.viewer.select_scopes(targets)
        if self.editor.preview_mode.get() == 'Vybrané podskupiny – ukázka':
            self.editor.schedule()

    def apply_change(self, key, value):
        targets = self.targets()
        if not targets:
            return
        try:
            self.editor.subgroup_rules = subgroup_layout.change(self.layout(), targets, {key: value})
            for iid, record in self.records.items():
                if self.tree.exists(iid):
                    self.tree.set(iid, 'mode', 'Vlastní' if subgroup_layout.find(self.editor.subgroup_rules, record) else 'Společné')
            self.refresh_choices(); self.editor.schedule()
        except ValueError as exc:
            self.editor.error(exc)

    def inherit(self):
        self.editor.subgroup_rules = subgroup_layout.change(self.layout(), self.targets(), {}, inherit=True)
        self.filter(); self.editor.schedule()
