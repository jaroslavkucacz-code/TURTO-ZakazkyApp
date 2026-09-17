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
