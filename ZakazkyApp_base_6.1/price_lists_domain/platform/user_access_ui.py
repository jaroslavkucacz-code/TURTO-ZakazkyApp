"""Explicit administrator editor for a user's job title and tab permissions."""
from . import user_access as access


def open_profile(M, app, parent, uid):
    try:
        access.require_admin(M)
        original = access.profile(M, uid)
        modes = access.decode(original['tab_permissions'])
    except ValueError as exc:
        return M.messagebox.showwarning('Uživatel', str(exc), parent=parent)
    win = M.tk.Toplevel(parent)
    win.title('Funkce a oprávnění – ' + original['name'])
    M.enable_dialog_maximize(win, 840, 620)
    win.transient(parent)
    win.grab_set()
    win.result = False
    outer = M.ttk.Frame(win, padding=14)
    outer.pack(fill='both', expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(2, weight=1)
    header = M.ttk.Frame(outer)
    header.grid(row=0, column=0, sticky='ew')
    header.columnconfigure(1, weight=1)
    M.ttk.Label(header, text='Funkce').grid(row=0, column=0, sticky='w', padx=(0, 12))
    title = M.tk.StringVar(master=win, value=original['job_title'])
    M.ttk.Combobox(header, textvariable=title, values=access.JOB_TITLES).grid(row=0, column=1, sticky='ew')
    M.ttk.Label(outer, text='Funkci můžete zvolit nebo napsat vlastní. Přístup nastavte pro každou záložku zvlášť.',
                wraplength=750).grid(row=1, column=0, sticky='w', pady=(8, 12))
    body = M.ttk.Frame(outer)
    body.grid(row=2, column=0, sticky='nsew')
    body.columnconfigure(0, weight=1)
    body.rowconfigure(0, weight=1)
    canvas = M.tk.Canvas(body, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky='nsew')
    scrollbar = M.ttk.Scrollbar(body, orient='vertical', command=canvas.yview)
    scrollbar.grid(row=0, column=1, sticky='ns')
    canvas.configure(yscrollcommand=scrollbar.set)
    fields = M.ttk.Frame(canvas)
    item = canvas.create_window((0, 0), window=fields, anchor='nw')
    fields.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
    fields.columnconfigure(0, weight=1)
    variables = {}
    admin = original['name'].strip().casefold() == 'admin'
    for index, (key, label) in enumerate(access.TITLES.items()):
        variable = M.tk.StringVar(master=win, value=access.MODES[access.EDIT if admin else modes.get(key, access.EDIT)])
        variables[key] = variable
        M.ttk.Label(fields, text=label).grid(row=index, column=0, sticky='w', pady=4, padx=(0, 16))
        M.ttk.Combobox(fields, textvariable=variable, values=access.MODES,
                       state='disabled' if admin else 'readonly', width=24).grid(row=index, column=1, sticky='e', pady=4)
    footer = M.ttk.Frame(outer)
    footer.grid(row=3, column=0, sticky='ew', pady=(12, 0))
    if not admin:
        bulk = M.ttk.Frame(footer)
        bulk.pack(fill='x', pady=(0, 8))
        group = M.tk.StringVar(master=win, value='Technika')
        bulk_mode = M.tk.StringVar(master=win, value=access.MODES[access.EDIT])
        M.ttk.Label(bulk, text='Celá sekce:').pack(side='left', padx=(0, 8))
        M.ttk.Combobox(bulk, textvariable=group, values=('Technika', 'Adresář', 'Přehledy', 'Všechny záložky'),
                       state='readonly', width=18).pack(side='left')
        M.ttk.Combobox(bulk, textvariable=bulk_mode, values=access.MODES, state='readonly', width=19).pack(side='left', padx=8)
        def apply_group():
            key = {'Technika': 'technical', 'Adresář': 'directory', 'Přehledy': 'reports'}.get(group.get())
            for page in access.navigation.GROUPS[key] if key else variables:
                variables[page].set(bulk_mode.get())
        M.ttk.Button(bulk, text='Nastavit', command=apply_group).pack(side='left')
    M.ttk.Label(footer, text='ADMIN má plný přístup ke správě CRM.' if admin else 'Výchozí přístup: všichni mohou číst i upravovat.').pack(anchor='w', pady=(0, 8))

    def save():
        try:
            updated = dict(modes)
            updated.update({key: access.MODES.index(var.get()) for key, var in variables.items()})
            access.save_profile(M, uid, title.get(), updated, (original['job_title'], original['tab_permissions']))
        except ValueError as exc:
            return M.messagebox.showwarning('Uživatel', str(exc), parent=win)
        win.result = True
        win.destroy()
        app.refresh_user_access()
    M.ttk.Button(footer, text='Zrušit', command=win.destroy).pack(side='right', padx=(8, 0))
    M.ttk.Button(footer, text='Uložit', command=save, style='Accent.TButton').pack(side='right')
    from .form_behavior_817 import register
    register(M, win, save)
    win.permission_variables, win.job_title_variable = variables, title
    return win
