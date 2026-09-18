"""First server-backed CRM window. All network calls run outside the Tk thread."""
from dataclasses import replace
import queue
import threading
from uuid import uuid4
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .client import DirectoryClient, DirectoryError, AccessDenied, Conflict, UncertainWrite
from .profile import Profile
from . import settings


class PilotWindow(tk.Toplevel):
    def __init__(self, master, local_demo=None, demo_role='editor1'):
        super().__init__(master)
        self.local_demo, self.demo_role = local_demo, demo_role
        self.demo_buttons = []
        self.title('TURTO CRM – síťový pilot společností')
        if local_demo:
            self.title('TURTO CRM – místní ukázka')
        self.geometry('1060x720'); self.minsize(780, 560)
        self.option_add('*' + self.winfo_name() + '*Font', 'Calibri 11')
        self.client = None
        self.identity = None
        self.busy = False
        self.offset = 0
        self.total = 0
        self.queue = queue.Queue()
        self.editor = None
        self._poll_id = None
        body = ttk.Frame(self, padding=14); body.pack(fill='both', expand=True)
        ttk.Label(body, text='Společnosti – místní ukázka' if local_demo else 'Společnosti na serveru – testovací provoz',
                  font=('Calibri', 14, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Jen umělá data na tomto PC. Po zavření všech oken se ukázka smaže.' if local_demo else
                  'Pracujete s kopií dat na serveru. Oprávnění určuje váš osobní serverový účet.').pack(anchor='w', pady=(3, 12))
        connect = ttk.LabelFrame(body, text='Připojení', padding=10); connect.pack(fill='x')
        connect.columnconfigure(1, weight=1)
        self.profile_path = tk.StringVar(self)
        self.schema = tk.StringVar(self, 'turto_pilot_prvni')
        self.login = tk.StringVar(self)
        self.password = tk.StringVar(self)
        self.connection_widgets = []
        for row, (label, variable) in enumerate((('Profil spojení', self.profile_path), ('Testovací schéma', self.schema),
                                                ('Serverový účet', self.login), ('Heslo', self.password))):
            ttk.Label(connect, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10), pady=3)
            entry = ttk.Entry(connect, textvariable=variable, show='•' if row == 3 else '')
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            self.connection_widgets.append(entry)
        choose = ttk.Button(connect, text='Vybrat…', command=self.choose_profile)
        choose.grid(row=0, column=2, padx=(8, 0)); self.connection_widgets.append(choose)
        configure = ttk.Button(connect, text='Nastavit…', command=self.configure_connection)
        configure.grid(row=1, column=2, padx=(8, 0)); self.connection_widgets.append(configure)
        self.connect_button = ttk.Button(connect, text='Přihlásit', command=self.connect)
        self.connect_button.grid(row=2, column=2, padx=(8, 0))
        self.disconnect_button = ttk.Button(connect, text='Odhlásit', command=self.disconnect)
        self.disconnect_button.grid(row=3, column=2, padx=(8, 0))
        self.password_entry = self.connection_widgets[3]
        self.password_entry.bind('<Return>', lambda e=None: self.connect() if e is not None else None)
        if local_demo:
            connect.pack_forget()
            roles = ttk.LabelFrame(body, text='Zkušební uživatel', padding=10); roles.pack(fill='x')
            for role, label in (('editor1', 'Editor 1'), ('editor2', 'Editor 2'), ('reader', 'Pouze čtení')):
                button = ttk.Button(roles, text=label, command=lambda role=role: self.switch_demo_role(role))
                button.pack(side='left', padx=(0, 8)); self.demo_buttons.append((button, role))
            self.demo_window_button = ttk.Button(roles, text='Otevřít druhé okno',
                command=lambda: local_demo.open_window('editor2'))
            self.demo_window_button.pack(side='right')
        self.status = tk.StringVar(self, 'Nastavte připojení a přihlaste se. Z domova nejprve zapněte firemní VPN.')
        ttk.Label(body, textvariable=self.status, wraplength=980).pack(fill='x', pady=10)
        controls = ttk.Frame(body); controls.pack(fill='x', pady=(0, 8))
        self.query = tk.StringVar(self)
        self.search = ttk.Entry(controls, textvariable=self.query)
        self.search.pack(side='left', fill='x', expand=True)
        self.search.bind('<Return>', lambda e=None: self.refresh(reset=True) if e is not None else None)
        self.refresh_button = ttk.Button(controls, text='Vyhledat / obnovit', command=lambda: self.refresh(reset=True))
        self.refresh_button.pack(side='left', padx=6)
        self.new_button = ttk.Button(controls, text='Nová společnost', command=self.new)
        self.new_button.pack(side='left')
        columns = ('name', 'ico', 'address', 'active')
        table = ttk.Frame(body); table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='browse')
        for key, label, width in (('name', 'Společnost', 300), ('ico', 'IČ', 100), ('address', 'Adresa', 350), ('active', 'Aktivní', 75)):
            self.tree.heading(key, text=label); self.tree.column(key, width=width, minwidth=65)
        bar = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left', fill='both', expand=True); bar.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', lambda e=None: self._controls() if e is not None else None)
        self.tree.bind('<Double-1>', lambda e=None: self.open_selected() if e is not None and self.tree.identify_region(e.x,e.y)=='cell' else None)
        footer = ttk.Frame(body); footer.pack(fill='x', pady=(10, 0))
        self.open_button = ttk.Button(footer, text='Otevřít společnost', command=self.open_selected)
        self.open_button.pack(side='left')
        self.history_button = ttk.Button(footer, text='Historie změn', command=self.show_history)
        self.history_button.pack(side='left', padx=8)
        self.next_button = ttk.Button(footer, text='Další →', command=lambda: self.page(1))
        self.next_button.pack(side='right')
        self.previous_button = ttk.Button(footer, text='← Předchozí', command=lambda: self.page(-1))
        self.previous_button.pack(side='right', padx=8)
        self.protocol('WM_DELETE_WINDOW', self.close)
        if not local_demo:
            try:
                profile, schema = settings.load(settings.default_path())
                self.profile_path.set(str(settings.default_path())); self.schema.set(schema); self.login.set(profile.user)
            except Exception:
                pass  # No automatic connection and no fallback to a local database.
        self._controls()

    def configure_connection(self):
        if self.busy or self.client:
            return
        from .connection_ui import ConnectionDialog
        ConnectionDialog(self)

    def choose_profile(self):
        path = filedialog.askopenfilename(parent=self, title='Profil připojení k testovací databázi', filetypes=[('Profil JSON', '*.json')])
        if path:
            try:
                profile, schema = settings.load(path)
            except Exception:
                messagebox.showerror('Připojení', 'Profil není platný. Zkontrolujte jeho údaje.', parent=self)
                return
            self.profile_path.set(path); self.login.set(profile.user); self.schema.set(schema)

    def _controls(self):
        level = self.identity['companies'] if self.identity else 0
        selected = bool(self.tree.selection())
        for widget in self.connection_widgets:
            widget.configure(state='disabled' if self.busy or self.client else 'normal')
        states = {self.connect_button: not self.client, self.disconnect_button: bool(self.client),
                  self.search: level >= 1, self.refresh_button: level >= 1, self.new_button: level >= 2,
                  self.open_button: level >= 1 and selected, self.history_button: level >= 1 and selected,
                  self.previous_button: level >= 1 and self.offset > 0,
                  self.next_button: level >= 1 and self.offset + 100 < self.total}
        for widget, enabled in states.items():
            widget.configure(state='normal' if enabled and not self.busy else 'disabled')
        for button, role in self.demo_buttons:
            button.configure(state='disabled' if self.busy or (self.client and self.demo_role == role) else 'normal')
        if self.local_demo:
            self.demo_window_button.configure(state='disabled' if self.busy else 'normal')

    def switch_demo_role(self, role):
        if self.local_demo and self.disconnect():
            self.demo_role = role
            self.connect()

    def run(self, action, success, failure=None):
        if self.busy:
            return
        self.busy = True; self._controls(); self.status.set('Komunikuji se serverem…')
        def worker():
            try:
                self.queue.put((success, action(), None, failure))
            except Exception as exc:
                # No tracebacks/DSNs/passwords in UI or background diagnostics.
                error = exc if isinstance(exc, DirectoryError) else DirectoryError('Operace selhala. Ověřte profil, síť a instalaci podpory PostgreSQL.')
                self.queue.put((success, None, error, failure))
        threading.Thread(target=worker, name='TURTO-Network', daemon=False).start()
        self._poll_id = self.after(50, self.poll)

    def poll(self):
        self._poll_id = None
        try:
            success, result, error, failure = self.queue.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(50, self.poll)
            return
        self.busy = False; self._controls()
        if error:
            self.status.set(str(error))
            if failure:
                failure(error)
            else:
                if isinstance(error, AccessDenied):
                    self.disconnect()
                messagebox.showerror('Síťový pilot', str(error), parent=self)
        else:
            success(result)

    def connect(self):
        if self.busy or self.client:
            return
        try:
            if self.local_demo:
                candidate = self.local_demo.client(self.demo_role)
            else:
                profile, _ = settings.load(self.profile_path.get())
                profile = replace(profile, user=self.login.get().strip())
                if not self.password.get():
                    messagebox.showerror('Připojení', 'Vyplňte heslo osobního serverového účtu.', parent=self)
                    return
                candidate = DirectoryClient(profile, self.schema.get().strip(), password=self.password.get())
        except Exception:
            messagebox.showerror('Připojení', 'Zkontrolujte profil, testovací schéma a serverový účet.', parent=self)
            return
        def connected(identity):
            self.client = candidate; self.identity = identity; self.password.set('')
            self._controls()
            if identity['companies'] >= 1:
                self.refresh(reset=True)
            else:
                self.status.set(identity['name'] + ' – nemáte přístup ke společnostem.')
        def failed(error):
            candidate.close(); self.password.set('')
            messagebox.showerror('Připojení', str(error), parent=self)
        self.run(candidate.identity, connected, failed)

    def disconnect(self):
        if self.busy:
            return False
        if self.editor and self.editor.winfo_exists():
            self.editor.close()
            if self.editor.winfo_exists():
                return False
        if self.client:
            self.client.close()
        self.client = self.identity = None
        self.password.set(''); self.tree.delete(*self.tree.get_children())
        self.offset = self.total = 0
        self.status.set('Odhlášeno.'); self._controls()
        return True

    def refresh(self, reset=False):
        if not self.client or self.busy:
            return
        if reset:
            self.offset = 0
        query, offset = self.query.get().strip(), self.offset
        self.run(lambda: self.client.companies(query, 100, offset), self.display)

    def display(self, result):
        self.tree.delete(*self.tree.get_children())
        for row in result['items']:
            self.tree.insert('', 'end', iid=str(row['id']), values=(row['official_name'] or row['short_name'], row['ico'] or '',
                             row['address'] or '', 'Ano' if row['active'] else 'Ne'))
        self.identity, self.total = result['identity'], result['total']
        rights = 'úpravy povoleny' if self.identity['companies'] >= 2 else 'pouze čtení'
        self.status.set(f"{self.identity['name']} – {rights}. Zobrazeno {len(result['items'])} z {self.total} společností.")
        if self.local_demo:
            label = {'editor1': 'Editor 1', 'editor2': 'Editor 2', 'reader': 'Čtenář'}[self.demo_role]
            self.status.set(f"Místní ukázka · {label} · {rights}. Zobrazeno {len(result['items'])} z {self.total} společností.")
        self._controls()

    def page(self, direction):
        if self.busy:
            return
        self.offset = max(0, self.offset + direction * 100)
        self.refresh()

    def open_selected(self):
        if self.busy or not self.client or not self.tree.selection():
            return
        cid = int(self.tree.selection()[0])
        self.run(lambda: self.client.company(cid), lambda result: self.edit(result['company'], result['identity']))

    def new(self):
        if self.identity and self.identity['companies'] >= 2 and not self.busy:
            self.edit({'id': None, 'network_revision': 0, 'active': 1, 'is_customer': 1, 'is_supplier': 0}, self.identity)

    def edit(self, row, identity):
        if self.editor and self.editor.winfo_exists():
            self.editor.lift(); return
        self.editor = CompanyEditor(self, row, identity['companies'] >= 2)

    def show_history(self):
        if self.busy or not self.client or not self.tree.selection():
            return
        cid = int(self.tree.selection()[0])
        def show(rows):
            win = tk.Toplevel(self); win.title('Historie změn na serveru'); win.geometry('850x480')
            text = tk.Text(win, wrap='word', font=('Calibri', 11)); text.pack(fill='both', expand=True, padx=12, pady=12)
            if not rows:
                text.insert('end', 'Od zapnutí síťového pilotu zatím nebyla provedena žádná změna.')
            for event in rows:
                text.insert('end', f"{event['changed_at']}  ·  {event['user_name']}  ·  {event['db_login']}\n")
                previous, current = event['previous'] or {}, event['current']
                for key, label in CompanyEditor.LABELS.items():
                    if previous.get(key) != current.get(key):
                        def value(row):
                            if key in ('active', 'is_customer', 'is_supplier') and row.get(key) is not None:
                                return 'Ano' if row[key] else 'Ne'
                            return row.get(key) or '—'
                        text.insert('end', f"{label}: {value(previous)} → {value(current)}\n")
                text.insert('end', '\n')
            text.configure(state='disabled')
            self.status.set('Historie načtena ze serveru.')
        self.run(lambda: self.client.history(cid), show)

    def close(self):
        if self.busy:
            messagebox.showinfo('Síťový pilot', 'Počkejte na dokončení serverové operace.', parent=self)
            return
        if not self.disconnect():
            return
        if self._poll_id:
            self.after_cancel(self._poll_id)
        self.destroy()


class CompanyEditor(tk.Toplevel):
    LABELS = {'official_name': 'Název společnosti', 'ico': 'IČ', 'dic': 'DIČ', 'address': 'Adresa', 'web': 'Web',
              'note': 'Poznámka', 'active': 'Aktivní', 'is_customer': 'Odběratel', 'is_supplier': 'Dodavatel'}

    def __init__(self, pilot, row, writable):
        super().__init__(pilot)
        self.pilot, self.row, self.writable = pilot, row, writable
        self.pending = None
        self.title('Společnost na serveru' if row['id'] else 'Nová společnost na serveru')
        self.geometry('640x540'); self.minsize(500, 450); self.transient(pilot)
        self.columnconfigure(1, weight=1); self.rowconfigure(5, weight=1)
        self.variables, self.fields = {}, []
        for index, (key, label) in enumerate(list(self.LABELS.items())[:5]):
            ttk.Label(self, text=label).grid(row=index, column=0, sticky='w', padx=12, pady=7)
            value = row.get(key) or (row.get('short_name', '') if key == 'official_name' else '')
            variable = tk.StringVar(self, value)
            entry = ttk.Entry(self, textvariable=variable); entry.grid(row=index, column=1, sticky='ew', padx=12, pady=7)
            entry.bind('<Return>', self.save_key)
            self.variables[key] = variable; self.fields.append(entry)
        ttk.Label(self, text='Poznámka').grid(row=5, column=0, sticky='nw', padx=12, pady=7)
        self.note = tk.Text(self, height=6, wrap='word', font=('Calibri', 11))
        self.note.grid(row=5, column=1, sticky='nsew', padx=12, pady=7)
        self.note.insert('1.0', row.get('note') or ''); self.fields.append(self.note)
        flags = ttk.Frame(self); flags.grid(row=6, column=0, columnspan=2, sticky='w', padx=12, pady=8)
        for key in ('active', 'is_customer', 'is_supplier'):
            variable = tk.BooleanVar(self, bool(row.get(key)))
            self.variables[key] = variable
            control = ttk.Checkbutton(flags, text=self.LABELS[key], variable=variable)
            control.pack(side='left', padx=(0, 18)); self.fields.append(control)
        self.status = tk.StringVar(self, '' if writable else 'Máte oprávnění pouze ke čtení.')
        ttk.Label(self, textvariable=self.status, wraplength=570).grid(row=7, column=0, columnspan=2, sticky='ew', padx=12, pady=7)
        buttons = ttk.Frame(self); buttons.grid(row=8, column=0, columnspan=2, sticky='ew', padx=12, pady=12)
        self.save_button = ttk.Button(buttons, text='Uložit', command=self.save); self.save_button.pack(side='left')
        self.verify_button = ttk.Button(buttons, text='Ověřit uložení', command=self.check); self.verify_button.pack(side='left', padx=8)
        self.reload_button = ttk.Button(buttons, text='Načíst aktuální údaje', command=self.reload); self.reload_button.pack(side='left')
        self.cancel_button = ttk.Button(buttons, text='Zavřít', command=self.close); self.cancel_button.pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda e=None: self.close() if e is not None else None)
        self.bind('<Control-Return>', self.save_key)
        self.controls()

    def save_key(self, event=None):
        # Hosted Tk may call a binding without an event during teardown.
        # Such a callback must neither raise nor initiate a database write.
        if event is not None:
            self.save()
        return 'break'

    def controls(self, busy=False):
        enabled = self.writable and not busy and self.pending is None
        for widget in self.fields:
            widget.configure(state='normal' if enabled else 'disabled')
        self.save_button.configure(state='normal' if self.writable and not busy and (self.pending is None or self.pending.get('retry')) else 'disabled')
        self.verify_button.configure(state='normal' if self.pending and not busy else 'disabled')
        self.reload_button.configure(state='normal' if self.row['id'] and not busy and not self.pending else 'disabled')
        self.cancel_button.configure(state='disabled' if busy else 'normal')

    def save(self):
        if not self.writable or self.pilot.busy or (self.pending and not self.pending.get('retry')):
            return
        if self.pending is None:
            values = {key: int(v.get()) if key in ('active', 'is_customer', 'is_supplier') else v.get().strip()
                      for key, v in self.variables.items()}
            values['note'] = self.note.get('1.0', 'end-1c')
            if not values['official_name']:
                self.status.set('Vyplňte název společnosti.'); return
            self.pending = {'request_id': str(uuid4()), 'id': self.row['id'], 'revision': self.row['network_revision'], 'values': values}
        request = dict(self.pending); self.pending['retry'] = False
        self.controls(True)
        self.pilot.run(lambda: self.pilot.client.save(request['id'], request['revision'], request['values'], request['request_id']),
                       self.saved, self.failed)

    def saved(self, row):
        self.pending = None
        self.destroy()
        self.pilot.refresh(reset=True)

    def failed(self, error):
        if isinstance(error, UncertainWrite):
            self.status.set('Výsledek není jistý. Klikněte na Ověřit uložení; údaje se neposílají znovu automaticky.')
        else:
            self.pending = None
            self.status.set(str(error))
            if isinstance(error, AccessDenied):
                self.writable = False
        self.controls()

    def check(self):
        if not self.pending or self.pilot.busy:
            return
        rid = self.pending['request_id']; self.controls(True)
        def checked(row):
            if row is not None:
                self.saved(row)
            else:
                self.pending['retry'] = True
                self.status.set('Server zatím uložení neeviduje. Tlačítkem Uložit lze zopakovat stejný požadavek bez vytvoření duplicity.')
                self.controls()
        def failed(error):
            self.status.set(str(error)); self.controls()
        self.pilot.run(lambda: self.pilot.client.operation(rid), checked, failed)

    def reload(self):
        if self.pilot.busy or self.pending:
            return
        if not messagebox.askyesno('Načíst aktuální údaje', 'Nahradit rozepsané údaje aktuálními hodnotami ze serveru?', parent=self):
            return
        cid = self.row['id']; self.destroy()
        self.pilot.run(lambda: self.pilot.client.company(cid), lambda value: self.pilot.edit(value['company'], value['identity']))

    def close(self):
        if self.pilot.busy:
            return
        if self.pending and not messagebox.askyesno('Neověřené uložení', 'Výsledek uložení není ověřený. Zavřít okno a ověřit společnost později v historii?', parent=self):
            return
        self.destroy()


def open_pilot(master):
    previous = getattr(master, '_network_pilot_window', None)
    if previous is not None and previous.winfo_exists():
        previous.lift(); return previous
    win = PilotWindow(master)
    master._network_pilot_window = win
    return win


def main():
    root = tk.Tk(); root.withdraw()
    win = open_pilot(root)
    win.bind('<Destroy>', lambda e=None: root.destroy() if e is not None and e.widget is win else None)
    root.mainloop()


if __name__ == '__main__':
    main()
