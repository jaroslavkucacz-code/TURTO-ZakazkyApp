"""Manage representatives and dated Pohoda assignments in one place."""
from contextlib import closing
from datetime import date, timedelta
from . import sales_centers as service, user_access as access


def open_dialog(M, app, parent=None):
    parent=parent or app
    if not access.allowed(M,parent,'settings'):return None
    win=M.tk.Toplevel(parent);win.title('Obchodníci a střediska Pohody');win.transient(parent)
    M.enable_dialog_maximize(win,1040,740)
    body=M.scrollable_dialog_frame(win,18)
    M.ttk.Label(body,text='Obchodníci a střediska Pohody',style='Title.TLabel').pack(anchor='w')
    M.ttk.Label(body,text='Kód patří středisku v importu Pohody. Přiřazení obchodníkovi platí od zvoleného data; starší doklady se nepřepisují.',wraplength=930).pack(anchor='w',pady=(6,12))
    representatives=M.ttk.Treeview(body,name='layout__sales_center_representatives',columns=('name','state','centers'),show='headings',height=6,selectmode='browse')
    for col,label,width in [('name','Obchodní zástupce',380),('state','Stav',120),('centers','Střediska nyní',230)]:
        representatives.heading(col,text=label,anchor='w');representatives.column(col,width=width,anchor='w')
    representatives.pack(fill='x')
    records={}
    def refresh():
        with closing(M.db()) as con:
            reps=[dict(r) for r in con.execute('SELECT * FROM salespeople WHERE canonical_id IS NULL ORDER BY active DESC,name COLLATE CZECH')]
            assignments=service.history(con);centers=service.current(con)
        records.clear();records.update({r['id']:r for r in reps})
        representatives.delete(*representatives.get_children())
        for r in reps:representatives.insert('','end',iid=str(r['id']),values=(r['name'],'Aktivní' if r['active'] else 'Neaktivní',centers.get(r['id'],'—')))
        timeline.delete(*timeline.get_children())
        for r in reversed(assignments):
            timeline.insert('','end',iid=str(r['id']),values=(r['center'],r['name'] or 'Bez přiřazení',
                'Od počátku' if r['valid_from']=='0001-01-01' else M.fmt_date(r['valid_from']),
                M.fmt_date((date.fromisoformat(r['valid_to'])-timedelta(days=1)).isoformat()) if r['valid_to'] else 'Bez konce'))
        if hasattr(app,'portfolio_workspace'):app.portfolio_workspace.refresh()

    def person(edit=False):
        chosen=representatives.selection()
        if edit and not chosen:return M.messagebox.showinfo('Obchodník','Vyberte obchodníka.',parent=win)
        old=records[int(chosen[0])] if edit else None
        d=M.tk.Toplevel(win);d.title('Upravit obchodníka' if edit else 'Nový obchodník');d.transient(win);d.grab_set()
        f=M.ttk.Frame(d,padding=18);f.pack(fill='both',expand=True)
        name=M.tk.StringVar(master=d,value=old['name'] if old else '')
        active=M.tk.BooleanVar(master=d,value=bool(old['active']) if old else True)
        M.ttk.Label(f,text='Jméno obchodního zástupce').pack(anchor='w')
        entry=M.ttk.Entry(f,textvariable=name,width=45);entry.pack(fill='x',pady=8);entry.focus_set()
        with closing(M.db()) as con:
            contacts=[dict(r) for r in con.execute('''SELECT p.id,p.name,p.email,p.phone,c.official_name company
                FROM people p LEFT JOIN companies c ON c.id=p.company_id
                ORDER BY CASE WHEN upper(c.official_name) LIKE 'TURTO%' THEN 0 ELSE 1 END,p.name COLLATE CZECH''')]
        options={f"{p['name']} · {p['company'] or 'bez společnosti'} · {p['email'] or p['id']}":p for p in contacts}
        selected=M.tk.StringVar(master=d,value=next((label for label,p in options.items() if old and p['id']==old['person_id']),'Nová osoba'))
        email=M.tk.StringVar(master=d);phone=M.tk.StringVar(master=d)
        M.ttk.Label(f,text='Propojená osoba v adresáři').pack(anchor='w')
        contact_box=M.safe_combobox(f,textvariable=selected,values=('Nová osoba',*options),state='readonly',width=65)
        contact_box.pack(fill='x',pady=(4,8))
        def load_contact(event=None):
            p=options.get(selected.get())
            if p:
                name.set(p['name']);email.set(p['email'] or '');phone.set(p['phone'] or '')
            else:email.set('');phone.set('')
        contact_box.bind('<<ComboboxSelected>>',load_contact)
        load_contact()
        for label,var in (('E-mail',email),('Telefon',phone)):
            M.ttk.Label(f,text=label).pack(anchor='w')
            M.ttk.Entry(f,textvariable=var).pack(fill='x',pady=(4,8))
        M.ttk.Label(f,text='Jméno, e-mail a telefon jsou společné s adresářem a používají se v nových nabídkách.',wraplength=460).pack(anchor='w',pady=5)
        M.ttk.Checkbutton(f,text='Aktivní obchodník',variable=active).pack(anchor='w')
        M.ttk.Label(f,text='Odchod obchodníka řešte deaktivací. Jeho portfolio a historie zůstanou zachované; středisko můžete níže předat nástupci.',wraplength=460).pack(anchor='w',pady=10)
        def commit():
            p=options.get(selected.get())
            contact=dict(person_id=p['id'] if p else None,email=email.get(),phone=phone.get(),
                         expected=(p['name'],p['email'],p['phone']) if p else None)
            try:service.save_person(M,old['id'] if old else None,name.get(),active.get(),(old['name'],old['active']) if old else None,contact)
            except (ValueError,M.sqlite3.Error) as exc:return M.messagebox.showwarning('Obchodník',str(exc),parent=d)
            d.destroy();refresh()
        M.ttk.Button(f,text='Uložit',style='Accent.TButton',command=commit).pack(anchor='e')
        d.bind('<Return>',lambda e:commit());d.bind('<Escape>',lambda e:d.destroy())
        d.name_variable=name;d.active_variable=active;d.email_variable=email;d.phone_variable=phone;d.contact_variable=selected;d.save=commit
        return d

    buttons=M.ttk.Frame(body);buttons.pack(fill='x',pady=8)
    M.ttk.Button(buttons,text='+ Nový obchodník',command=person).pack(side='left')
    M.ttk.Button(buttons,text='Upravit obchodníka',command=lambda:person(True)).pack(side='left',padx=8)
    M.ttk.Label(body,text='Historie přiřazení středisek',style='Section.TLabel').pack(anchor='w',pady=(12,6))
    timeline=M.ttk.Treeview(body,name='layout__sales_center_history',columns=('center','name','start','end'),show='headings',height=8,selectmode='browse')
    for col,label,width in [('center','Kód Pohody',110),('name','Obchodní zástupce',350),('start','Platí od',160),('end','Platí do (včetně)',170)]:
        timeline.heading(col,text=label,anchor='w');timeline.column(col,width=width,anchor='w')
    timeline.pack(fill='both',expand=True)

    def assignment():
        with closing(M.db()) as con:
            history=service.history(con)
            reps=[dict(r) for r in con.execute('SELECT id,name FROM salespeople WHERE active=1 AND canonical_id IS NULL ORDER BY name COLLATE CZECH')]
        selected=timeline.selection();old=next((r for r in history if str(r['id']) in selected),None)
        d=M.tk.Toplevel(win);d.title('Přiřadit středisko od data');d.transient(win);d.grab_set()
        f=M.ttk.Frame(d,padding=18);f.pack(fill='both',expand=True)
        code=M.tk.StringVar(master=d,value=old['center'] if old else '')
        rep=M.tk.StringVar(master=d,value=old['name'] if old and old['active'] else 'Bez přiřazení')
        effective=M.tk.StringVar(master=d,value=date.today().isoformat())
        for text in ('Kód střediska v Pohodě',):M.ttk.Label(f,text=text).pack(anchor='w')
        M.ttk.Combobox(f,textvariable=code,values=sorted({r['center'] for r in history}),width=45).pack(fill='x',pady=(4,10))
        M.ttk.Label(f,text='Obchodní zástupce').pack(anchor='w')
        M.safe_combobox(f,textvariable=rep,values=('Bez přiřazení',*[r['name'] for r in reps]),state='readonly',width=45).pack(fill='x',pady=(4,10))
        M.ttk.Label(f,text='Platí od (včetně tohoto dne)').pack(anchor='w')
        M.DatePicker(f,effective,width=18).pack(anchor='w',pady=(4,10))
        M.ttk.Label(f,text='Předchozí přiřazení skončí den před účinností změny. Budoucí změnu lze naplánovat předem.',wraplength=460).pack(anchor='w',pady=8)
        def commit():
            name=rep.get();sid=next((r['id'] for r in reps if r['name']==name),None)
            if name!='Bez přiřazení' and sid is None:return
            token=code.get().strip().upper()
            expected=[(r['id'],r['salesperson_id'],r['valid_from'],r['valid_to']) for r in history if r['center']==token]
            try:service.assign(M,token,sid,effective.get(),expected)
            except (ValueError,M.sqlite3.Error) as exc:return M.messagebox.showwarning('Středisko Pohody',str(exc),parent=d)
            d.destroy();refresh()
        M.ttk.Button(f,text='Uložit přiřazení',style='Accent.TButton',command=commit).pack(anchor='e',pady=(8,0))
        d.center_variable=code;d.rep_variable=rep;d.date_variable=effective;d.save=commit
        return d
    footer=M.ttk.Frame(body);footer.pack(fill='x',pady=(12,0))
    M.ttk.Button(footer,text='Přiřadit středisko od data…',style='Accent.TButton',command=assignment).pack(side='left')
    M.ttk.Button(footer,text='Zavřít',command=win.destroy).pack(side='right')
    win.representatives=representatives;win.timeline=timeline;win.edit_person=person;win.assign_center=assignment
    refresh();return win
