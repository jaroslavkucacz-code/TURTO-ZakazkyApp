"""Customer portfolios with shared ownership by multiple salespeople."""
from contextlib import closing
from . import sales_identity, user_access as access, grouped_navigation as navigation


def assignments(con, company_id):
    return {r[0] for r in con.execute('SELECT salesperson_id FROM company_salespeople WHERE company_id=?', (company_id,))}


def save(M, company_id, selected, expected):
    access.require(M, 'portfolio')
    selected = set(selected)
    with closing(M.db()) as con, con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT is_customer,active FROM companies WHERE id=?', (company_id,)).fetchone()
        if not row or not row['is_customer'] or not row['active']:
            raise ValueError('Portfolio lze přiřadit aktivnímu odběrateli.')
        current = assignments(con, company_id)
        if current != set(expected):
            raise ValueError('Přiřazení mezitím změnil jiný uživatel. Otevřete výběr znovu.')
        available = {r['id'] for r in sales_identity.choices(con)} | current
        if not selected <= available:
            raise ValueError('Vyberte aktivní obchodní zástupce.')
        session = getattr(M, '_user_access_session', None)
        for sid in current - selected:
            con.execute('DELETE FROM company_salespeople WHERE company_id=? AND salesperson_id=?', (company_id, sid))
        for sid in selected - current:
            con.execute('INSERT INTO company_salespeople(company_id,salesperson_id,assigned_by) VALUES(?,?,?)',
                        (company_id, sid, session.name if session else ''))


def rows(M, salesperson=None, unassigned=False, query=''):
    with closing(M.db()) as con:
        result = con.execute('''SELECT c.id,c.official_name,c.ico,c.address,c.district,
            (SELECT group_concat(name, ', ') FROM
                (SELECT s.name FROM company_salespeople p JOIN salespeople s ON s.id=p.salesperson_id
                 WHERE p.company_id=c.id ORDER BY s.name COLLATE CZECH)) representatives
            FROM companies c WHERE c.active=1 AND c.is_customer=1
            AND (? IS NULL OR EXISTS(SELECT 1 FROM company_salespeople p WHERE p.company_id=c.id AND p.salesperson_id=?))
            AND (?=0 OR NOT EXISTS(SELECT 1 FROM company_salespeople p WHERE p.company_id=c.id))
            ORDER BY c.official_name COLLATE CZECH''', (salesperson, salesperson, int(unassigned))).fetchall()
        needle = sales_identity.key(query)
        return [dict(r) for r in result if not needle or needle in sales_identity.key(' '.join(str(x or '') for x in r))]


class Workspace:
    def __init__(self, M, app, page):
        self.M, self.app, self.page = M, app, page
        self.user_id = object()
        app.title_label(page, 'Portfolio')
        bar = M.ttk.Frame(page, style='Panel.TFrame', padding=12)
        bar.pack(fill='x', pady=(0, 8))
        M.ttk.Label(bar, text='Obchodní zástupce').grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.selection = M.tk.StringVar(master=page, value='Všichni obchodníci')
        self.combo = M.safe_combobox(bar, textvariable=self.selection, values=('Všichni obchodníci',), state='readonly', width=28)
        self.combo.grid(row=0, column=1, sticky='w')
        self.combo.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        M.ttk.Label(bar, text='Hledat společnost').grid(row=0, column=2, sticky='w', padx=(24, 10))
        self.query = M.tk.StringVar(master=page)
        M.ttk.Entry(bar, textvariable=self.query).grid(row=0, column=3, sticky='ew')
        bar.columnconfigure(3, weight=1)
        self.query.trace_add('write', lambda *a: self.refresh())
        actions = M.ttk.Frame(page, style='Panel.TFrame', padding=10)
        actions.pack(fill='x', pady=(0, 8))
        M.ttk.Button(actions, text='Přiřadit obchodníky…', style='Accent.TButton', command=self.assign).pack(side='left')
        M.ttk.Button(actions, text='Otevřít společnost', command=self.open_company).pack(side='left', padx=8)
        M.ttk.Button(actions, text='Obnovit přehled', command=self.refresh).pack(side='right')
        self.summary = M.tk.StringVar(master=page)
        M.ttk.Label(page, textvariable=self.summary, style='Panel.TLabel', wraplength=1100).pack(fill='x', pady=(0, 8))
        self.tree = app.tree(page, ('Společnost', 'IČO', 'Obchodní zástupci', 'Sídlo', 'Okres'), (310, 95, 320, 330, 160))
        app.portfolio_tree = self.tree
        M.bind_row_double_click(self.tree, lambda e: self.open_company())
        self.options = {}

    def on_user_changed(self):
        session = getattr(self.M, '_user_access_session', None)
        identity = session.user_id if session else None
        if identity != self.user_id:
            self.user_id = identity
            self.selection.set('Moje portfolio' if sales_identity.default_salesperson(self.M) else 'Všichni obchodníci')
            self.query.set('')
        self.refresh()

    def refresh(self):
        if access.level(self.M, 'portfolio') < access.READ:
            self.tree.delete(*self.tree.get_children())
            self.summary.set('Portfolio není pro tohoto uživatele dostupné.')
            return
        with closing(self.M.db()) as con:
            self.options = {sales_identity.label(r): r['id'] for r in sales_identity.choices(con)}
        self.combo.configure(values=('Moje portfolio', 'Všichni obchodníci', 'Bez obchodníka', *self.options))
        chosen = self.selection.get()
        sid = sales_identity.default_salesperson(self.M) if chosen == 'Moje portfolio' else self.options.get(chosen)
        result = [] if chosen == 'Moje portfolio' and sid is None else rows(self.M, sid, chosen == 'Bez obchodníka', self.query.get())
        selected = self.tree.selection()
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in result:
            self.tree.insert('', 'end', iid=f"c{row['id']}", values=(row['official_name'], row['ico'], row['representatives'] or '—', row['address'], row['district']))
        for iid in selected:
            if self.tree.exists(iid):self.tree.selection_add(iid)
        self.summary.set('U vašeho uživatele chybí obchodní zástupce. Přiřazení nastaví ADMIN ve správě uživatelů.'
                         if chosen == 'Moje portfolio' and sid is None else
                         f'{len(result)} společností · Jednu společnost může mít v portfoliu více obchodníků.')

    def company_id(self):
        selection = self.tree.selection()
        if not selection:
            self.M.messagebox.showinfo('Portfolio', 'Vyberte společnost v tabulce.', parent=self.app)
            return None
        return int(selection[0][1:])

    def open_company(self):
        cid = self.company_id()
        if cid is None:return
        win = self.M.CompanyDialog(self.app, cid)
        self.app.wait_window(win)
        self.refresh()

    def assign(self):
        M = self.M
        if not access.allowed(M, self.app, 'portfolio'):return
        cid = self.company_id()
        if cid is None:return
        with closing(M.db()) as con:
            original = assignments(con, cid)
            options = [dict(r) for r in con.execute('SELECT * FROM salespeople WHERE canonical_id IS NULL ORDER BY name COLLATE CZECH')
                       if r['active'] or r['id'] in original]
            name = con.execute('SELECT official_name FROM companies WHERE id=?', (cid,)).fetchone()[0]
        win = M.tk.Toplevel(self.app)
        win.title('Obchodní zástupci – ' + name)
        win.transient(self.app);win.grab_set()
        M.enable_dialog_maximize(win, 630, 430)
        body = M.scrollable_dialog_frame(win, 18)
        M.ttk.Label(body, text=name, font=('Calibri', 14, 'bold'), wraplength=560).pack(anchor='w', pady=(0, 10))
        M.ttk.Label(body, text='Vyberte všechny obchodníky, kteří se o společnost starají.', wraplength=560).pack(anchor='w', pady=(0, 10))
        variables = {}
        for row in options:
            var = M.tk.BooleanVar(master=win, value=row['id'] in original)
            variables[row['id']] = var
            M.ttk.Checkbutton(body, text=sales_identity.label(row) + ('' if row['active'] else ' (neaktivní)'), variable=var).pack(anchor='w', pady=5)
        def commit():
            try:
                save(M, cid, {sid for sid, var in variables.items() if var.get()}, original)
            except (ValueError, M.sqlite3.Error) as exc:
                return M.messagebox.showwarning('Portfolio', str(exc), parent=win)
            win.destroy();self.refresh()
        footer = M.ttk.Frame(body);footer.pack(fill='x', pady=(20, 0))
        M.ttk.Button(footer, text='Zrušit', command=win.destroy).pack(side='right', padx=(8, 0))
        M.ttk.Button(footer, text='Uložit', style='Accent.TButton', command=commit).pack(side='right')
        win.portfolio_variables = variables
        from .form_behavior_817 import register
        register(M, win, commit)
        return win


def apply(M):
    previous_schema = M.ensure_schema
    def schema():
        result = previous_schema()
        with closing(M.db()) as con, con:
            sales_identity.migrate(con)
        return result
    M.ensure_schema = schema
    previous_build = M.App.build
    def build(app, *args, **kwargs):
        result = previous_build(app, *args, **kwargs)
        page = M.ttk.Frame(app.pages, style='App.TFrame')
        app.tabs['portfolio'] = page
        app.portfolio_workspace = Workspace(M, app, page)
        page.grid(row=0, column=0, sticky='nsew');page.lower()
        navigation.register_page(app, 'portfolio', 'Portfolio')
        return result
    M.App.build = build
    M.App.refresh_portfolio = lambda app: app.portfolio_workspace.refresh()
