"""Searchable, stable-ID taxonomy selection shared by all assignment dialogs."""
from . import categories, universal_search


def choose(M, parent, title, current_category_id=None, current_subgroup_id=None):
    previous_grab = parent.grab_current()
    groups = categories.list_categories(M)
    children = {}
    for row in categories.list_subgroups(M):
        children.setdefault(row['category_id'], []).append(row)
    dialog = M.tk.Toplevel(parent)
    dialog.title(title); dialog.transient(parent); dialog.grab_set()
    M.enable_dialog_maximize(dialog, 900, 670)
    frame = M.ttk.Frame(dialog, padding=16); frame.pack(fill='both', expand=True)
    M.ttk.Label(frame, text=title, font=('Calibri', 13, 'bold')).pack(anchor='w', pady=(0, 8))
    result = {'value': 'cancel'}
    mapping = {'none': (None, None)}
    def refresh():
        selected = tree.selection()
        opened = {iid for iid in tree.get_children() if tree.item(iid, 'open')}
        tree.delete(*tree.get_children())
        terms = search.terms
        matches = lambda text: all(t in universal_search.normalize(text) for t in terms)
        if matches(categories.UNASSIGNED):
            tree.insert('', 'end', iid='none', text=categories.UNASSIGNED)
        for group in groups:
            cid = group['id']; iid = f'c{cid}'
            found = [r for r in children.get(cid, []) if matches(group['name']+' '+r['name'])]
            if not matches(group['name']) and not found: continue
            mapping[iid] = (cid, None)
            tree.insert('', 'end', iid=iid, text=group['name'], open=bool(terms) or iid in opened)
            for row in found:
                child = f"s{row['id']}"; mapping[child] = (cid, row['id'])
                tree.insert(iid, 'end', iid=child, text=row['name'])
        for iid in selected:
            if tree.exists(iid): tree.selection_set(iid); tree.see(iid)
    search = universal_search.SearchBar(frame, refresh)
    search.pack(fill='x', pady=(0, 8))
    wrap = M.ttk.Frame(frame); wrap.pack(fill='both', expand=True)
    wrap.rowconfigure(0, weight=1); wrap.columnconfigure(0, weight=1)
    tree = M.ttk.Treeview(wrap, show='tree', selectmode='browse')
    tree.grid(row=0, column=0, sticky='nsew')
    scroll = M.ttk.Scrollbar(wrap, orient='vertical', command=tree.yview)
    scroll.grid(row=0, column=1, sticky='ns'); tree.configure(yscrollcommand=scroll.set)
    def finish(event=None):
        selected = tree.selection()
        if selected:
            result['value'] = mapping[selected[0]]; dialog.destroy()
        return 'break'
    tree.bind('<Return>', finish)
    def double_click(event):
        if 'indicator' in tree.identify_element(event.x, event.y): return
        iid = tree.identify_row(event.y)
        if iid: tree.selection_set(iid); return finish()
    tree.bind('<Double-1>', double_click)
    footer = M.ttk.Frame(frame); footer.pack(fill='x', pady=(10, 0))
    M.ttk.Label(footer, text='Vyberte podskupinu nebo celou skupinu bez podskupiny.').pack(side='left')
    M.ttk.Button(footer, text='Zrušit', command=dialog.destroy).pack(side='right')
    M.ttk.Button(footer, text='Přiřadit', style='Accent.TButton', command=finish).pack(side='right', padx=6)
    refresh()
    current = f's{current_subgroup_id}' if current_subgroup_id else f'c{current_category_id}' if current_category_id else 'none'
    if tree.exists(current): tree.selection_set(current); tree.see(current)
    dialog.taxonomy_tree, dialog.taxonomy_search = tree, search
    dialog.taxonomy_finish = finish
    dialog.wait_window()
    if previous_grab is not None and previous_grab.winfo_exists(): previous_grab.grab_set()
    return result['value']
