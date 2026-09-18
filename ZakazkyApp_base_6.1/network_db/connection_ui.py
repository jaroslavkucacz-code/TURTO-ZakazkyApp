"""A single company endpoint for both office Wi-Fi and the company VPN."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from .profile import Profile
from .migration import schema_name
from . import settings


class ConnectionDialog(tk.Toplevel):
    def __init__(self, pilot):
        super().__init__(pilot)
        self.pilot = pilot
        self.title('Připojení k firemnímu serveru')
        self.geometry('760x440'); self.minsize(680, 430); self.transient(pilot)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text='Stejná adresa v kanceláři i přes firemní VPN.', font=('Calibri', 12, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', padx=14, pady=(14, 8))
        try:
            profile, schema = settings.load(pilot.profile_path.get())
        except Exception:
            profile, schema = None, 'turto_pilot_prvni'
        defaults = {'host': '', 'port': '5432', 'dbname': 'turto_crm_pilot', 'schema': schema,
                    'user': '', 'sslrootcert': ''}
        if profile:
            defaults.update({key: str(getattr(profile, key)) for key in defaults if key != 'schema'})
        labels = {'host': 'Adresa serveru', 'port': 'Port', 'dbname': 'Testovací databáze',
                  'schema': 'Testovací schéma', 'user': 'Osobní serverový účet', 'sslrootcert': 'Certifikát od správce'}
        self.variables = {}
        for row, (key, label) in enumerate(labels.items(), 1):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky='w', padx=14, pady=7)
            var = tk.StringVar(self, defaults[key]); self.variables[key] = var
            ttk.Entry(self, textvariable=var).grid(row=row, column=1, sticky='ew', padx=8, pady=7)
        ttk.Button(self, text='Vybrat…', command=self.certificate).grid(row=6, column=2, padx=12)
        ttk.Label(self, text='Adresu, databázi, schéma, účet a veřejný certifikát dodá správce.\n'
                  'Z domova nejprve zapněte firemní VPN. Heslo zadáte při přihlášení.', wraplength=690).grid(
                      row=7, column=0, columnspan=3, sticky='w', padx=14, pady=12)
        self.save_button = ttk.Button(self, text='Uložit připojení', command=self.save)
        self.save_button.grid(row=8, column=1, sticky='e', padx=8, pady=12)
        ttk.Button(self, text='Zrušit', command=self.destroy).grid(row=8, column=2, padx=12, pady=12)
        self.bind('<Escape>', lambda e=None: self.destroy() if e is not None else None)
        self.grab_set()

    def certificate(self):
        path = filedialog.askopenfilename(parent=self, title='Veřejný certifikát certifikační autority',
                                         filetypes=[('Certifikát', '*.crt *.pem'), ('Všechny soubory', '*')])
        if path:
            self.variables['sslrootcert'].set(path)

    def save(self):
        try:
            v = {key: var.get().strip() for key, var in self.variables.items()}
            schema = schema_name(v.pop('schema'))
            v['port'] = int(v['port'])
            local = v['host'] in ('127.0.0.1', 'localhost', '::1')
            if v['sslrootcert']:
                v['sslrootcert'] = str(Path(v['sslrootcert']).resolve(strict=True))
            elif not local:
                raise ValueError('Vyberte veřejný certifikát od správce serveru.')
            profile = Profile(**v, sslmode='disable' if local and not v['sslrootcert'] else 'verify-full')
            path = settings.default_path()
            settings.save(path, profile, schema)
        except Exception:
            messagebox.showerror('Připojení', 'Zkontrolujte adresu, port, databázi, osobní účet, testovací schéma a soubor certifikátu.', parent=self)
            return
        self.pilot.profile_path.set(str(path)); self.pilot.schema.set(schema); self.pilot.login.set(profile.user)
        self.pilot.status.set('Připojení je uložené. Zadejte heslo a klikněte na Přihlásit.')
        self.destroy()
