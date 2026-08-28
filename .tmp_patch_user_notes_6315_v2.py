from pathlib import Path

APP = Path('ZakazkyApp_base_6.1/app.py')
text = APP.read_text(encoding='utf-8')

old_schema = '''        CREATE TABLE IF NOT EXISTS user_settings(\n          user_name TEXT NOT NULL,\n          key TEXT NOT NULL,\n          value TEXT DEFAULT '',\n          PRIMARY KEY(user_name,key)\n        );\n        CREATE TABLE IF NOT EXISTS salespeople(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1);'''
new_schema = '''        CREATE TABLE IF NOT EXISTS user_settings(\n          user_name TEXT NOT NULL,\n          key TEXT NOT NULL,\n          value TEXT DEFAULT '',\n          PRIMARY KEY(user_name,key)\n        );\n        CREATE TABLE IF NOT EXISTS user_notes(\n          id INTEGER PRIMARY KEY AUTOINCREMENT,\n          user_name TEXT NOT NULL,\n          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,\n          text TEXT NOT NULL DEFAULT '',\n          archived INTEGER NOT NULL DEFAULT 0,\n          archived_at TEXT DEFAULT ''\n        );\n        CREATE INDEX IF NOT EXISTS idx_user_notes_user_archive\n          ON user_notes(user_name,archived,created_at DESC);\n        CREATE TABLE IF NOT EXISTS salespeople(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1);'''
assert old_schema in text, 'schema marker missing'
text = text.replace(old_schema, new_schema, 1)

notes_class = r"""
class UserNotesDialog(tk.Toplevel):
    'Simple private notebook for exactly one CRM user.'
    def __init__(self,parent):
        super().__init__(parent)
        self.parent_app=parent
        self.user_name=(parent.active_user.get() or '').strip() or get_setting('active_user','')
        self.editing_id=None
        self.title(f"Poznámky – {self.user_name}")
        self.transient(parent)
        self.grab_set()
        enable_dialog_maximize(self,980,650)
        self.protocol('WM_DELETE_WINDOW',self.close)

        outer=ttk.Frame(self,padding=16)
        outer.pack(fill='both',expand=True)
        outer.columnconfigure(0,weight=1)
        outer.rowconfigure(4,weight=1)

        ttk.Label(outer,text='Osobní poznámky',font=('Calibri',16,'bold')).grid(row=0,column=0,sticky='w')
        ttk.Label(
            outer,
            text=f'{self.user_name} · rychlý osobní zápisník bez vazby na Akce, Poptávky nebo Úkoly',
            style='PageSubtitle.TLabel',
        ).grid(row=1,column=0,sticky='w',pady=(2,10))

        editor_card=ttk.Frame(outer,style='Card.TFrame',padding=12)
        editor_card.grid(row=2,column=0,sticky='ew',pady=(0,10))
        editor_card.columnconfigure(0,weight=1)
        ttk.Label(editor_card,text='Nová poznámka',style='Section.TLabel').grid(row=0,column=0,sticky='w')
        self.editor=tk.Text(editor_card,height=5,wrap='word',font=('Calibri',11))
        self.editor.grid(row=1,column=0,columnspan=3,sticky='ew',pady=(7,8))
        try:
            pal=getattr(parent,'palette',{}) or {}
            field=pal.get('field','#ffffff');fg=pal.get('fg','#1c2429');sel=pal.get('select','#d6b64c');border=pal.get('border','#d4dade')
            self.editor.configure(bg=field,fg=fg,insertbackground=fg,selectbackground=sel,selectforeground='white',highlightbackground=border,highlightcolor=border,relief='flat',borderwidth=1)
        except Exception:pass
        self.editor.bind('<Control-Return>',self._ctrl_save)
        self.editor.bind('<Control-KP_Enter>',self._ctrl_save)
        self.edit_label=ttk.Label(editor_card,text='Ctrl+Enter = uložit',style='PageSubtitle.TLabel')
        self.edit_label.grid(row=2,column=0,sticky='w')
        ttk.Button(editor_card,text='Vyčistit',command=self.clear_editor).grid(row=2,column=1,padx=(8,0))
        self.save_button=ttk.Button(editor_card,text='Uložit poznámku',style='Accent.TButton',command=self.save_note)
        self.save_button.grid(row=2,column=2,padx=(8,0))

        tools=ttk.Frame(outer,style='Panel.TFrame',padding=8)
        tools.grid(row=3,column=0,sticky='ew',pady=(0,6))
        tools.columnconfigure(1,weight=1)
        ttk.Label(tools,text='Hledat:').grid(row=0,column=0,sticky='w',padx=(0,6))
        self.search_var=tk.StringVar()
        search=ttk.Entry(tools,textvariable=self.search_var)
        search.grid(row=0,column=1,sticky='ew')
        self.show_archived=tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tools,
            text='Zobrazit archivované',
            variable=self.show_archived,
            command=self.refresh,
        ).grid(row=0,column=2,sticky='e',padx=(12,0))
        self.search_var.trace_add('write',lambda *_:self.refresh())

        tree_wrap=ttk.Frame(outer,style='Panel.TFrame')
        tree_wrap.grid(row=4,column=0,sticky='nsew')
        tree_wrap.columnconfigure(0,weight=1)
        tree_wrap.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(
            tree_wrap,
            columns=('Vytvořeno','Poznámka'),
            show='headings',
            selectmode='browse',
        )
        self.tree.heading('Vytvořeno',text='Vytvořeno')
        self.tree.heading('Poznámka',text='Poznámka')
        self.tree.column('Vytvořeno',width=145,minwidth=125,stretch=False,anchor='w')
        self.tree.column('Poznámka',width=760,minwidth=300,stretch=True,anchor='w')
        ys=ttk.Scrollbar(tree_wrap,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0,column=0,sticky='nsew')
        ys.grid(row=0,column=1,sticky='ns')
        self._archived_font=tkfont.Font(family='Calibri',size=11,overstrike=1)
        self.tree.tag_configure('archived',font=self._archived_font)
        bind_row_double_click(self.tree,lambda _e:self.edit_selected())
        self.tree.bind('<<TreeviewSelect>>',lambda _e:self.sync_buttons(),add='+')

        actions=ttk.Frame(outer)
        actions.grid(row=5,column=0,sticky='ew',pady=(10,0))
        self.edit_button=ttk.Button(actions,text='✎ Upravit',command=self.edit_selected)
        self.edit_button.pack(side='left')
        self.archive_button=ttk.Button(actions,text='✓ Přeškrtnout / archivovat',command=self.archive_selected)
        self.archive_button.pack(side='left',padx=(6,0))
        self.restore_button=ttk.Button(actions,text='↩ Obnovit',command=self.restore_selected)
        self.restore_button.pack(side='left',padx=(6,0))
        ttk.Button(actions,text='Zavřít',command=self.close).pack(side='right')

        self.refresh()
        self.after_idle(self.editor.focus_set)

    def _ctrl_save(self,_event=None):
        self.save_note()
        return 'break'

    def selected_id(self):
        selected=self.tree.selection()
        if not selected:return None
        iid=selected[0]
        return int(iid[1:]) if str(iid).startswith('n') else None

    def selected_row(self):
        note_id=self.selected_id()
        if not note_id:return None
        with db() as con:
            row=con.execute(
                'SELECT * FROM user_notes WHERE id=? AND user_name=?',
                (note_id,self.user_name),
            ).fetchone()
        return row

    def refresh(self):
        if not hasattr(self,'tree'):return
        for iid in self.tree.get_children(''):
            self.tree.delete(iid)
        query=(self.search_var.get() or '').strip() if hasattr(self,'search_var') else ''
        show_archived=bool(self.show_archived.get()) if hasattr(self,'show_archived') else False
        with db() as con:
            rows=con.execute(
                '''SELECT * FROM user_notes
                   WHERE user_name=?
                     AND (?=1 OR archived=0)
                     AND (?='' OR lower(text) LIKE lower(?))
                   ORDER BY archived ASC,datetime(created_at) DESC,id DESC''',
                (self.user_name,1 if show_archived else 0,query,f'%{query}%'),
            ).fetchall()
        for row in rows:
            preview=' '.join(str(row['text'] or '').split())
            tags=('archived',) if int(row['archived'] or 0) else ()
            self.tree.insert(
                '','end',iid=f"n{row['id']}",
                values=(fmt_history_datetime(row['created_at']),preview),
                tags=tags,
            )
        self.sync_buttons()

    def sync_buttons(self):
        row=self.selected_row()
        if not row:
            for button in (self.edit_button,self.archive_button,self.restore_button):
                button.state(['disabled'])
            return
        self.edit_button.state(['!disabled'])
        if int(row['archived'] or 0):
            self.archive_button.state(['disabled'])
            self.restore_button.state(['!disabled'])
        else:
            self.archive_button.state(['!disabled'])
            self.restore_button.state(['disabled'])

    def clear_editor(self):
        self.editing_id=None
        self.editor.delete('1.0','end')
        self.save_button.configure(text='Uložit poznámku')
        self.edit_label.configure(text='Ctrl+Enter = uložit')
        self.editor.focus_set()

    def save_note(self):
        note=self.editor.get('1.0','end').strip()
        if not note:
            return messagebox.showinfo('Poznámky','Napište text poznámky.',parent=self)
        with db() as con:
            if self.editing_id:
                con.execute(
                    '''UPDATE user_notes SET text=?,updated_at=CURRENT_TIMESTAMP
                       WHERE id=? AND user_name=?''',
                    (note,self.editing_id,self.user_name),
                )
            else:
                con.execute(
                    'INSERT INTO user_notes(user_name,text) VALUES(?,?)',
                    (self.user_name,note),
                )
        self.clear_editor()
        self.refresh()
        self.parent_app.refresh_notes_button()

    def edit_selected(self):
        row=self.selected_row()
        if not row:return
        self.editing_id=int(row['id'])
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',row['text'] or '')
        self.save_button.configure(text='Uložit změny')
        self.edit_label.configure(text=f"Upravujete poznámku z {fmt_history_datetime(row['created_at'])}")
        self.editor.focus_set()

    def archive_selected(self):
        row=self.selected_row()
        if not row:return
        if int(row['archived'] or 0):return
        with db() as con:
            con.execute(
                '''UPDATE user_notes
                   SET archived=1,archived_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND user_name=?''',
                (row['id'],self.user_name),
            )
        if self.editing_id==int(row['id']):self.clear_editor()
        self.refresh()
        self.parent_app.refresh_notes_button()

    def restore_selected(self):
        row=self.selected_row()
        if not row:return
        if not int(row['archived'] or 0):return
        with db() as con:
            con.execute(
                '''UPDATE user_notes
                   SET archived=0,archived_at='',updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND user_name=?''',
                (row['id'],self.user_name),
            )
        self.refresh()
        self.parent_app.refresh_notes_button()

    def close(self):
        try:self.grab_release()
        except Exception:pass
        try:self.parent_app._notes_dialog=None
        except Exception:pass
        self.destroy()

"""
marker = 'class NotificationCenter(tk.Toplevel):\n'
assert marker in text, 'NotificationCenter marker missing'
text = text.replace(marker, notes_class + marker, 1)

old_top = '''        self.user_button=ttk.Button(top,text="",style="TopAction.TButton",command=self.open_user_menu)\n        self.user_button.grid(row=0,column=2,padx=(8,0))\n        self.refresh_user_button()\n        self.bell_button=ttk.Button(top,text="🔔",style="TopAction.TButton",width=5,command=self.open_notifications)\n        self.bell_button.grid(row=0,column=3,padx=(6,0))\n        ttk.Button(top,text="⚙",style="TopAction.TButton",width=4,\n                   command=lambda:self.show_page("settings")).grid(row=0,column=4,padx=(6,0))'''
new_top = '''        self.user_button=ttk.Button(top,text="",style="TopAction.TButton",command=self.open_user_menu)\n        self.user_button.grid(row=0,column=2,padx=(8,0))\n        self.refresh_user_button()\n        self.notes_button=ttk.Button(top,text="📝",style="TopAction.TButton",width=6,command=self.open_user_notes)\n        self.notes_button.grid(row=0,column=3,padx=(6,0))\n        self.refresh_notes_button()\n        self.bell_button=ttk.Button(top,text="🔔",style="TopAction.TButton",width=5,command=self.open_notifications)\n        self.bell_button.grid(row=0,column=4,padx=(6,0))\n        ttk.Button(top,text="⚙",style="TopAction.TButton",width=4,\n                   command=lambda:self.show_page("settings")).grid(row=0,column=5,padx=(6,0))'''
assert old_top in text, 'topbar marker missing'
text = text.replace(old_top, new_top, 1)

method_marker = '''    def open_user_menu(self):\n'''
notes_methods = r'''    def refresh_notes_button(self):
        if not hasattr(self,'notes_button'):return
        user=self.active_user.get().strip() if hasattr(self,'active_user') else get_setting('active_user','')
        try:
            with db() as con:
                count=con.execute(
                    'SELECT COUNT(*) FROM user_notes WHERE user_name=? AND archived=0',
                    (user,),
                ).fetchone()[0]
        except Exception:
            count=0
        self.notes_button.configure(text=f'📝 {count}' if count else '📝')

    def open_user_notes(self):
        current=getattr(self,'_notes_dialog',None)
        try:
            if current is not None and current.winfo_exists():
                current.deiconify();current.lift();current.focus_force();return
        except Exception:pass
        self._notes_dialog=UserNotesDialog(self)

'''
assert method_marker in text, 'open_user_menu marker missing'
text = text.replace(method_marker, notes_methods + method_marker, 1)

old_changed = '''        self.apply_theme(theme,False)\n        self.refresh_user_button()\n        self.refresh_all()'''
new_changed = '''        self.apply_theme(theme,False)\n        self.refresh_user_button()\n        self.refresh_notes_button()\n        self.refresh_all()'''
assert old_changed in text, 'on_user_changed marker missing'
text = text.replace(old_changed, new_changed, 1)

old_rename = '''                    con.execute("UPDATE users SET name=? WHERE id=?",(name.strip(),uid))\n                    con.execute("UPDATE user_settings SET user_name=? WHERE user_name=?",(name.strip(),old))'''
new_rename = '''                    con.execute("UPDATE users SET name=? WHERE id=?",(name.strip(),uid))\n                    con.execute("UPDATE user_settings SET user_name=? WHERE user_name=?",(name.strip(),old))\n                    con.execute("UPDATE user_notes SET user_name=? WHERE user_name=?",(name.strip(),old))'''
assert old_rename in text, 'user rename marker missing'
text = text.replace(old_rename, new_rename, 1)

APP.write_text(text,encoding='utf-8')
Path('release_version.txt').write_text('6.3.15\n',encoding='utf-8')
Path('release_notes.txt').write_text(
    '• Vedle aktivního uživatele je nová ikona Poznámky. Každý uživatel má vlastní jednoduchý zápisník bez vazeb na Akce, Příležitosti, Poptávky nebo Úkoly.\n'
    '• Nová poznámka automaticky dostane aktuální datum a čas. Ukládá se přímo do databáze; Ctrl+Enter ji rychle uloží a v seznamu lze poznámky vyhledávat.\n'
    '• Přeškrtnutí poznámky je současně její archivace. Z běžného seznamu zmizí; po zapnutí „Zobrazit archivované“ je vidět přeškrtnutá a lze ji obnovit. Samostatný stav „přeškrtnuto“ neexistuje.\n'
    '• Poznámku lze dodatečně upravit. Přejmenování uživatele převede i jeho poznámky na nové jméno; odstranění uživatele poznámky fyzicky nemaže.\n'
    '• Databáze se pouze aditivně rozšiřuje o tabulku user_notes. Stávající zakázková data, Nabídky, parsery, Excel exporty i historie se nemění.\n',
    encoding='utf-8'
)
print('patched 6.3.15')
