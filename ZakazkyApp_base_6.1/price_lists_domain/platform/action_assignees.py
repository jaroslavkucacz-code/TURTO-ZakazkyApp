"""Multiple CRM users assigned to a processing item, saved explicitly."""
import json
import sqlite3


def decode(raw):
    entries = json.loads(raw or '[]')
    if not isinstance(entries, list):
        raise ValueError('Neplatný uložený seznam řešitelů.')
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or type(entry.get('user_id')) is not int or not isinstance(entry.get('name'), str):
            raise ValueError('Neplatný uložený seznam řešitelů.')
        result[entry['user_id']] = entry['name']
    return result


def display(raw):
    try:
        return ', '.join(decode(raw).values())
    except (ValueError, TypeError):
        return 'Nelze načíst řešitele'


def choices(con, original):
    result = {}
    for row in con.execute('SELECT id,name,active FROM users ORDER BY name COLLATE CZECH'):
        active = bool(row['active']) and row['name'].strip().casefold() not in {'admin', 'test'}
        if active or row['id'] in original:
            result[row['id']] = (row['name'], active)
    for uid, name in original.items():
        result.setdefault(uid, (name, False))
    return result


def encode_selection(con, expected, selected):
    selected = set(selected)
    if any(type(uid) is not int for uid in selected):
        raise ValueError('Neplatný řešitel.')
    original = decode(expected)
    available = choices(con, original)
    if any(uid not in available or (not available[uid][1] and uid not in original) for uid in selected):
        raise ValueError('Některý řešitel už není aktivní. Otevřete výběr znovu.')
    if selected == set(original):
        return expected
    ordered = sorted(selected, key=lambda uid: (available[uid][0].casefold(), uid))
    return json.dumps([{'user_id': uid, 'name': available[uid][0]} for uid in ordered], ensure_ascii=False)


def form_field(M, dialog, parent, original, new=False):
    """Checkboxes only edit the draft; the enclosing form owns the transaction."""
    from .request_mail import logged_in_user
    dialog._original_assignees = original
    selected = decode(original)
    with M.db() as con:
        options = choices(con, selected)
    if new:
        user = logged_in_user(M, dialog)
        selected = {uid: name for uid, (name, active) in options.items() if active and name == user}
    frame = M.ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    canvas = M.tk.Canvas(frame, height=88, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky='ew')
    bar = M.ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
    bar.grid(row=0, column=1, sticky='ns')
    canvas.configure(yscrollcommand=bar.set)
    body = M.ttk.Frame(canvas)
    item = canvas.create_window((0, 0), window=body, anchor='nw')
    body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
    dialog.assignee_variables = {}
    for index, (uid, (name, active)) in enumerate(options.items()):
        variable = M.tk.BooleanVar(master=dialog, value=uid in selected)
        dialog.assignee_variables[uid] = variable
        M.ttk.Checkbutton(body, text=name + ('' if active else ' (neaktivní)'), variable=variable).grid(
            row=index // 3, column=index % 3, sticky='w', padx=(0, 12), pady=2)
    for column in range(3):
        body.columnconfigure(column, weight=1)
    if not options:
        M.ttk.Label(body, text='Nejsou k dispozici aktivní uživatelé.').grid(sticky='w')
    return frame


def save(M, action_id, expected, selected):
    """Compare and update under one write lock; retain names of former users."""
    selected = set(selected)
    if any(type(uid) is not int for uid in selected):
        raise ValueError('Neplatný řešitel.')
    with M.db() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT assignees_json FROM actions WHERE id=?', (action_id,)).fetchone()
        if not row:
            raise ValueError('Záznam už neexistuje.')
        if row['assignees_json'] != expected:
            raise ValueError('Řešitele mezitím změnil jiný uživatel. Zavřete výběr a otevřete jej znovu.')
        encoded = encode_selection(con, expected, selected)
        if encoded == expected:
            return False
        user = M.get_setting('active_user', '')
        con.execute('UPDATE actions SET assignees_json=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                    (encoded, user, action_id))
        con.execute('''INSERT INTO action_history(action_id,user_name,event_type,summary,details)
                       VALUES(?,?,'action_assignees','Změnil řešitele',?)''',
                    (action_id, user, f"Řeší: {display(expected) or '—'} → {display(encoded) or '—'}"))
    return True


def open_picker(M, app):
    tree = app.action_tree
    selection = tree.selection()
    if not selection:
        M.messagebox.showinfo('Řeší', 'Vyberte řádek v tabulce Ke zpracování.', parent=app)
        return
    action_id = int(selection[0][1:])
    try:
        with M.db() as con:
            row = con.execute('SELECT name,assignees_json FROM actions WHERE id=?', (action_id,)).fetchone()
            if not row:
                raise ValueError('Záznam už neexistuje.')
            expected = row['assignees_json']
            original = decode(expected)
            options = choices(con, original)
    except (ValueError, sqlite3.Error) as exc:
        M.messagebox.showerror('Řeší', str(exc), parent=app)
        return

    win = M.tk.Toplevel(app)
    win.title('Řeší – ' + row['name'])
    M.enable_dialog_maximize(win, 560, 480)
    win.transient(app)
    win.grab_set()
    win.result = False
    body = M.scrollable_dialog_frame(win, 14)
    M.ttk.Label(body, text='Vyberte jednu nebo více osob. Změny potvrďte tlačítkem Uložit.').pack(anchor='w', pady=(0, 10))
    variables = {}
    for uid, (name, active) in options.items():
        variable = M.tk.BooleanVar(value=uid in original)
        variables[uid] = variable
        M.ttk.Checkbutton(body, text=name + ('' if active else ' (neaktivní)'), variable=variable).pack(anchor='w', pady=3)
    if not options:
        M.ttk.Label(body, text='Nejsou k dispozici žádní aktivní uživatelé CRM.').pack(anchor='w')

    def commit():
        try:
            changed = save(M, action_id, expected, [uid for uid, var in variables.items() if var.get()])
        except (ValueError, sqlite3.Error) as exc:
            M.messagebox.showerror('Řeší', str(exc), parent=win)
            return
        win.result = True
        win.destroy()
        if changed:
            if hasattr(app, '_turto_mark_dirty'):
                app._turto_mark_dirty({'actions', 'projects', 'dash'})
            app.refresh_actions()
            if tree.exists(selection[0]):
                tree.selection_set(selection[0])
                tree.see(selection[0])

    buttons = M.ttk.Frame(body)
    buttons.pack(fill='x', pady=(14, 0))
    M.ttk.Button(buttons, text='Zrušit', command=win.destroy).pack(side='right', padx=4)
    M.ttk.Button(buttons, text='Uložit', style='Accent.TButton', command=commit).pack(side='right')
    from .form_behavior_817 import wire_close
    wire_close(win, win.destroy)
    # Checkboxes and Enter never persist changes implicitly.
    win.assignee_variables = variables
    return win


def row_double_click(M, app, event):
    tree = app.action_tree
    column = tree.identify_column(event.x)
    if column and tree.column(column, 'id') == 'Řeší':
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            open_picker(M, app)
        return 'break'
    return app.edit_action(tree)
