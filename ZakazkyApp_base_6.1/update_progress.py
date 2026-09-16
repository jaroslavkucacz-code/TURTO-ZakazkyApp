"""Responsive update progress; every Tk operation stays on the UI thread."""
from pathlib import Path
import queue
import sys
import tkinter as tk
from tkinter import ttk


class ProgressWindow:
    def __init__(self, parent=None, version=""):
        self.window = tk.Toplevel(parent) if parent is not None else tk.Tk()
        win = self.window
        win._turto_compact_dialog = True
        win.title("TURTO CRM – aktualizace")
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self.request_close)
        self.events = queue.SimpleQueue()
        self.busy = True
        self.closed = False
        self._after = None
        self.on_close = None
        body = ttk.Frame(win, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Aktualizace TURTO CRM" + (f" {version}" if version else ""),
                  font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 16))
        self.stage = ttk.Label(body, text="Připravuji aktualizaci…", font=("Segoe UI", 11))
        self.stage.pack(anchor="w", pady=(0, 10))
        self.bar = ttk.Progressbar(body, length=480, mode="indeterminate")
        self.bar.pack(fill="x")
        self.detail = ttk.Label(body, text="Po dokončení se CRM znovu otevře.",
                                wraplength=480, justify="left")
        self.detail.pack(anchor="w", pady=(12, 18))
        self.close_button = ttk.Button(body, text="Zavřít", command=self.request_close, state="disabled")
        self.close_button.pack(anchor="e")
        self.bar.start(12)
        bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        try:
            win.iconbitmap(bitmap=str(bundle / "turto_logo.ico"))
        except tk.TclError:
            pass
        win.update_idletasks()
        width, height = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"{width}x{height}+{max(0, (win.winfo_screenwidth()-width)//2)}+{max(0, (win.winfo_screenheight()-height)//2)}")
        if parent is not None:
            win.transient(parent)
            win.grab_set()
        win.deiconify()
        win.lift()
        win.update_idletasks()
        self._poll()

    def report(self, stage, fraction=None, detail=None):
        """Safe from workers: queue data, never call Tk."""
        self.events.put(("progress", (stage, fraction, detail)))

    def fail(self, message):
        self.events.put(("error", str(message)))

    def complete(self):
        self.events.put(("complete", None))

    def _poll(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "complete":
                self.destroy()
                return
            if kind == "error":
                self.busy = False
                self.bar.stop()
                self.stage.configure(text="Aktualizace nebyla dokončena")
                self.detail.configure(text=value)
                self.close_button.configure(state="normal")
                self.window.grab_release()
            else:
                stage, fraction, detail = value
                self.stage.configure(text=stage)
                if detail is not None:
                    self.detail.configure(text=detail)
                if fraction is None:
                    if str(self.bar.cget("mode")) != "indeterminate":
                        self.bar.configure(mode="indeterminate")
                        self.bar.start(12)
                else:
                    self.bar.stop()
                    self.bar.configure(mode="determinate", value=max(0, min(100, fraction * 100)))
        self._after = self.window.after(100, self._poll)

    def request_close(self):
        if self.busy:
            self.window.bell()
            return
        self.destroy()

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        if self._after is not None:
            self.window.after_cancel(self._after)
        self.window.destroy()
        if self.on_close is not None:
            self.on_close()
