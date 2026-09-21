"""Customer portfolios with shared ownership by multiple salespeople."""
from contextlib import closing
from tkinter import font as tkfont
from . import sales_identity, user_access as access, grouped_navigation as navigation
from . import sales_centers, portfolio_contacts


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
        M.ttk.Button(actions, text='Otevřít detail', command=self.open_detail).pack(side='left', padx=8)
        M.ttk.Button(actions, text='+ Kontakt', command=self.new_contact).pack(side='left', padx=4)
        M.ttk.Button(actions, text='Obchodníci a střediska…', command=self.manage_salespeople).pack(side='left', padx=4)
        M.ttk.Button(actions, text='Obnovit přehled', command=self.refresh).pack(side='right')
        self.summary = M.tk.StringVar(master=page)
        M.ttk.Label(page, textvariable=self.summary, style='Panel.TLabel', wraplength=1100).pack(fill='x', pady=(0, 8))
        M.ttk.Label(page,text='Šipka rozbalí kontakty · Dvojklik otevře detail společnosti nebo osoby · Pravé tlačítko nabídne další možnosti · F2 upraví kontakt v řádku',wraplength=1100).pack(fill='x',pady=(0,6))
        self.tree = app.tree(page, ('Společnost / kontakt','Telefon','E-mail','Funkce','Obchodní zástupci','IČO','Sídlo','Okres'), (300,145,245,170,300,95,300,140))
        self.tree.configure(show='tree headings')
        self.tree.heading('#0',text='');self.tree.column('#0',width=35,minwidth=28,stretch=False)
        app.portfolio_tree = self.tree
        self.options = {}
        self.editor=portfolio_contacts.Editor(self)
        self.row_menu=None
        self.tree.bind('<Return>',lambda e:(self.open_detail(),'break')[1])
        # Row menus run before shared bindings; column-header menus stay intact.
        tag='PortfolioRows842_'+str(self.tree)
        self.tree.bindtags((tag,*self.tree.bindtags()))
        self.tree.bind_class(tag,'<Button-3>',self.context_menu)
        self.tree.bind_class(tag,'<Shift-F10>',self.context_menu)
        self.tree.bind_class(tag,'<Menu>',self.context_menu)
        self.tree.bind('<<ThemeChanged>>',lambda e:self.configure_rows(),add='+')
        self.configure_rows()

    def configure_rows(self):
        from .calm_theme_820 import palette
        p=palette(self.tree)
        if not hasattr(self,'company_font'):
            self.company_font=tkfont.Font(root=self.tree,font=self.M.ttk.Style(self.tree).lookup('Treeview','font') or 'TkDefaultFont')
            self.company_font.configure(weight='bold')
        self.tree.tag_configure('portfolio_company',font=self.company_font,background=p['head'],foreground=p['fg'])
        self.tree.tag_configure('portfolio_person',font='',background=p['field'],foreground=p['fg'])

    def select_row(self,iid=None):
        if iid is None:
            chosen=self.tree.selection();iid=chosen[0] if chosen else None
        if not iid or not self.tree.exists(iid):return None
        self.tree.selection_set(iid);self.tree.focus(iid)
        return iid

    def open_detail(self,iid=None):
        if not self.editor.commit():return
        iid=self.select_row(iid)
        if not iid:return
        if iid.startswith('c'):return self.open_company()
        if not access.allowed(self.M,self.app,'people',write=False):return
        pid=int(iid[1:])
        with closing(self.M.db()) as con:
            exists=con.execute('SELECT 1 FROM people WHERE id=? AND active=1',(pid,)).fetchone()
        if not exists:self.refresh();return
        win=self.M.PersonDialog(self.app,pid)
        self.app.wait_window(win);self.app.refresh_people();self.refresh()

    def context_menu(self,event):
        keyboard=getattr(event,'keysym','') in ('F10','Menu')
        if keyboard:
            iid=self.select_row()
            if not iid:return 'break'
            self.tree.see(iid);box=self.tree.bbox(iid)
            if not box:return 'break'
            x,y=self.tree.winfo_rootx()+70,self.tree.winfo_rooty()+box[1]+box[3]
        else:
            region=self.tree.identify_region(event.x,event.y)
            if region in ('heading','separator'):return
            iid=self.tree.identify_row(event.y)
            if not iid:return 'break'
            x,y=event.x_root,event.y_root
        if not self.editor.commit():return 'break'
        self.select_row(iid);self.tree.focus_set()
        if self.row_menu:self.row_menu.destroy()
        menu=self.M.tk.Menu(self.tree,tearoff=False);self.row_menu=menu
        state=lambda page,write=True:'normal' if access.level(self.M,page,fresh=True)>=(access.EDIT if write else access.READ) else 'disabled'
        if iid.startswith('c'):
            menu.add_command(label='Otevřít detail společnosti',state=state('companies',False),command=lambda:self.open_detail(iid))
            menu.add_separator()
            menu.add_command(label='Přidat kontaktní osobu…',state=state('people'),command=self.new_contact)
            menu.add_command(label='Přiřadit obchodníky…',state=state('portfolio'),command=self.assign)
        else:
            menu.add_command(label='Otevřít detail osoby',state=state('people',False),command=lambda:self.open_detail(iid))
            menu.add_separator()
            for column,label in [('Společnost / kontakt','jméno'),('Telefon','telefon'),('E-mail','e-mail'),('Funkce','funkci')]:
                menu.add_command(label='Upravit '+label+' v řádku',state=state('people'),command=lambda c=column:self.editor.begin(iid,c))
            menu.add_separator()
            menu.add_command(label='Otevřít společnost',state=state('companies',False),command=self.open_company)
        try:menu.tk_popup(x,y)
        finally:menu.grab_release()
        return 'break'

    def on_user_changed(self):
        session = getattr(self.M, '_user_access_session', None)
        identity = session.user_id if session else None
        if identity != self.user_id:
            self.editor.cancel()
            self.user_id = identity
            self.selection.set('Moje portfolio' if sales_identity.default_salesperson(self.M) else 'Všichni obchodníci')
            self.query.set('')
        self.refresh()

    def refresh(self):
        if hasattr(self,'editor') and not self.editor.commit():return
        if access.level(self.M, 'portfolio') < access.READ:
            self.tree.delete(*self.tree.get_children())
            self.summary.set('Portfolio není pro tohoto uživatele dostupné.')
            return
        previous_choice=self.options.get(self.selection.get())
        with closing(self.M.db()) as con:
            self.options = {sales_identity.label(r): r['id'] for r in sales_identity.choices(con)}
        self.combo.configure(values=('Moje portfolio', 'Všichni obchodníci', 'Bez obchodníka', *self.options))
        chosen = self.selection.get()
        if previous_choice and chosen not in self.options:
            chosen=next((label for label,sid in self.options.items() if sid==previous_choice),'Moje portfolio')
            self.selection.set(chosen)
        sid = sales_identity.default_salesperson(self.M) if chosen == 'Moje portfolio' else self.options.get(chosen)
        result = [] if chosen == 'Moje portfolio' and sid is None else rows(self.M, sid, chosen == 'Bez obchodníka', self.query.get())
        contacts=portfolio_contacts.grouped(self.M,[r['id'] for r in result]) if access.level(self.M,'people')>=access.READ else {}
        selected = self.tree.selection()
        opened={iid for iid in self.tree.get_children() if self.tree.item(iid,'open')}
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)
        for row in result:
            iid=f"c{row['id']}"
            self.tree.insert('', 'end', iid=iid,open=iid in opened,tags=('portfolio_company',), values=(row['official_name'],'','','',row['representatives'] or '—',row['ico'],row['address'],row['district']))
            for person in contacts.get(row['id'],[]):
                self.tree.insert(iid,'end',iid=f"p{person['id']}",tags=('portfolio_person',),values=(portfolio_contacts.display_value('Společnost / kontakt',person['name']),person['phone'],person['email'],person['role'],'','','',''))
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
        iid=selection[0]
        if iid.startswith('p'):iid=self.tree.parent(iid)
        return int(iid[1:])

    def manage_salespeople(self):
        from .sales_center_ui import open_dialog
        return open_dialog(self.M,self.app)

    def new_contact(self):
        if not self.editor.commit() or not access.allowed(self.M,self.app,'people'):return
        cid=self.company_id()
        if cid is None:return
        win=self.M.PersonDialog(self.app,pre_company_id=cid)
        self.app.wait_window(win);self.app.refresh_people();self.refresh()
        if self.tree.exists(f'c{cid}'):self.tree.item(f'c{cid}',open=True)

    def open_company(self):
        if not self.editor.commit() or not access.allowed(self.M,self.app,'companies',write=False):return
        cid = self.company_id()
        if cid is None:return
        with closing(self.M.db()) as con:
            exists=con.execute('SELECT 1 FROM companies WHERE id=? AND active=1',(cid,)).fetchone()
        if not exists:self.refresh();return
        win = self.M.CompanyDialog(self.app, cid)
        self.app.wait_window(win)
        self.app.refresh_people()
        self.refresh()

    def assign(self):
        M = self.M
        if not access.allowed(M, self.app, 'portfolio'):return
        cid = self.company_id()
        if cid is None:return
        with closing(M.db()) as con:
            original = assignments(con, cid)
            centers=sales_centers.current(con)
            options = [dict(r) for r in con.execute('SELECT * FROM salespeople WHERE canonical_id IS NULL ORDER BY name COLLATE CZECH')
                       if r['active'] or r['id'] in original]
            for row in options:row['pohoda_center']=centers.get(row['id'],'')
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
            sales_centers.ensure_schema(con)
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
