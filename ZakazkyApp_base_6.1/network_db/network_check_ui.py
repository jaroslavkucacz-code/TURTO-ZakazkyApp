"""Read-only connectivity check that needs no database credentials or admin."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from .diagnostics import check_network, network_summary, save_report


class NetworkCheck:
    def __init__(self, root):
        self.root = root
        self.report = None
        self.messages = queue.Queue()
        root.title('TURTO CRM – kontrola připojení')
        root.geometry('750x500'); root.minsize(650, 450)
        root.option_add('*Font', 'Calibri 11')
        frame = ttk.Frame(root, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Kontrola firemního připojení', font=('Calibri', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Doma nejprve připojte firemní VPN. Kontrola potřebuje jen adresu a port.',
                  wraplength=690).pack(anchor='w', pady=10)
        fields = ttk.Frame(frame); fields.pack(fill='x')
        self.host = tk.StringVar(root, '192.168.8.240'); self.port = tk.StringVar(root, '5432')
        ttk.Label(fields, text='Server').pack(side='left')
        ttk.Entry(fields, textvariable=self.host, width=28).pack(side='left', padx=10)
        ttk.Label(fields, text='Port databáze').pack(side='left')
        ttk.Entry(fields, textvariable=self.port, width=8).pack(side='left', padx=10)
        self.run_button = ttk.Button(fields, text='Zkontrolovat', command=self.run)
        self.run_button.pack(side='right')
        self.text = ScrolledText(frame, wrap='word', height=13, font=('Calibri', 11), state='disabled')
        self.text.pack(fill='both', expand=True, pady=14)
        self.status = tk.StringVar(root, 'Připraveno ke kontrole.')
        ttk.Label(frame, textvariable=self.status, wraplength=690).pack(anchor='w')
        self.copy_button = ttk.Button(frame, text='Kopírovat výsledek', command=self.copy, state='disabled')
        self.copy_button.pack(anchor='w', pady=(10, 0))

    def display(self, text):
        self.text.configure(state='normal'); self.text.delete('1.0', 'end')
        self.text.insert('1.0', text); self.text.configure(state='disabled')

    def run(self):
        host, port = self.host.get(), self.port.get()
        self.report = None
        self.copy_button.state(['disabled']); self.run_button.state(['disabled'])
        self.status.set('Kontroluji dostupnost serveru…')
        def worker():
            try:
                report = check_network(host, int(port))
                try:
                    path = str(save_report(report, 'pripojeni'))
                except OSError:
                    path = None
                self.messages.put((report, path, None))
            except (ValueError, OSError) as exc:
                self.messages.put((None, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self.poll)

    def poll(self):
        try:
            report, path, error = self.messages.get_nowait()
        except queue.Empty:
            self.root.after(50, self.poll); return
        self.run_button.state(['!disabled'])
        if error:
            self.display(error); self.status.set('Zkontrolujte zadané údaje.'); return
        self.report = report
        self.display(network_summary(report))
        self.copy_button.state(['!disabled'])
        self.status.set('Protokol: ' + path if path else 'Protokol nešel uložit. Výsledek můžete zkopírovat.')

    def copy(self):
        if self.report:
            self.root.clipboard_clear()
            self.root.clipboard_append(json.dumps(self.report, ensure_ascii=False, indent=2))
            self.status.set('Výsledek je zkopírovaný. Můžete jej vložit do zprávy.')


def main():
    root = tk.Tk(); NetworkCheck(root); root.mainloop()
    return 0
