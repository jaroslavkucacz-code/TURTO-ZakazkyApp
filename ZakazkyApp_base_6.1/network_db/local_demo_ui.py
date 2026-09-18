"""One-click demonstration: no company endpoint, profile or password entry."""
import queue
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from .local_demo import LocalDemo


class DemoApplication:
    def __init__(self, root):
        self.root = root
        self.session = LocalDemo()
        self.windows = set()
        self.messages = queue.Queue()
        self.cancelled = False
        self.error = None
        self.ready = False
        root.title('TURTO CRM – místní ukázka')
        root.geometry('610x210')
        root.option_add('*Font', 'Calibri 11')
        frame = ttk.Frame(root, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Místní ukázka CRM', font=('Calibri', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Používá jen umělé údaje. Každé spuštění začíná s novými daty.',
                  wraplength=560).pack(anchor='w', pady=8)
        self.status = tk.StringVar(root, 'Připravuji místní ukázku…')
        ttk.Label(frame, textvariable=self.status, wraplength=560).pack(anchor='w', pady=8)
        self.progress = ttk.Progressbar(frame, mode='indeterminate'); self.progress.pack(fill='x'); self.progress.start()
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        def prepare():
            try:
                self.session.start(lambda text: self.messages.put(('status', text)))
                self.messages.put(('ready', None))
            except Exception as exc:
                self.messages.put(('error', type(exc).__name__))
        threading.Thread(target=prepare, name='TURTO-Local-Demo', daemon=False).start()
        root.after(50, self.poll)

    def cancel(self):
        self.cancelled = True
        self.status.set('Dokončuji přípravu a ukončuji ukázku…')

    def poll(self):
        try:
            kind, value = self.messages.get_nowait()
        except queue.Empty:
            self.root.after(50, self.poll)
            return
        if kind == 'status':
            if not self.cancelled: self.status.set(value)
            self.root.after(50, self.poll)
        elif kind == 'error':
            self.error = value
            self.show_failure()
        elif self.cancelled:
            self.root.quit()
        else:
            self.ready = True
            self.root.withdraw()
            self.open_window()

    def show_failure(self):
        self.progress.stop()
        self.status.set('Příprava selhala. Podrobnosti jsou uvedené níže.')
        self.root.geometry('780x560'); self.root.minsize(650, 470)
        self.root.protocol('WM_DELETE_WINDOW', self.root.quit)
        details = self.session.failure or {'error_type': self.error, 'phase': self.session.phase}
        self.failure_text = json.dumps(details, ensure_ascii=False, indent=2)
        frame = ttk.Frame(self.root, padding=(20, 0, 20, 15)); frame.pack(fill='both', expand=True)
        text = ScrolledText(frame, height=12, wrap='word', font=('Calibri', 11))
        text.pack(fill='both', expand=True)
        text.insert('1.0', self.failure_text); text.configure(state='disabled')
        saved = ('Protokol: ' + str(self.session.report_path) if self.session.report_path else
                 'Protokol nešel uložit. Použijte Kopírovat podrobnosti.')
        ttk.Label(frame, text=saved, wraplength=720).pack(anchor='w', pady=8)
        buttons = ttk.Frame(frame); buttons.pack(fill='x')
        self.copy_button = ttk.Button(buttons, text='Kopírovat podrobnosti', command=self.copy_failure)
        self.copy_button.pack(side='left')
        ttk.Button(buttons, text='Zavřít', command=self.root.quit).pack(side='right')

    def copy_failure(self):
        self.root.clipboard_clear(); self.root.clipboard_append(self.failure_text)
        self.status.set('Podrobnosti jsou zkopírované. Můžete je vložit do zprávy.')

    def client(self, role):
        return self.session.client(role)

    def open_window(self, role='editor1'):
        from .ui import PilotWindow
        win = PilotWindow(self.root, local_demo=self, demo_role=role)
        self.windows.add(win)
        def closed(event):
            if event.widget is win:
                self.windows.discard(win)
                if not self.windows:
                    self.root.quit()
        win.bind('<Destroy>', closed)
        win.after_idle(win.connect)
        return win

    def stop(self):
        self.session.stop()


def main():
    root = tk.Tk()
    app = DemoApplication(root)
    try:
        root.mainloop()
    finally:
        root.deiconify(); app.status.set('Ukončuji místní databázi…'); root.update_idletasks()
        try:
            app.stop()
        except Exception:
            messagebox.showerror('Místní ukázka', 'Úklid dočasných dat se nedokončil. '
                'Databázové procesy ukončí Windows při zavření programu.', parent=root)
        root.destroy()
    return 1 if app.error else 0
