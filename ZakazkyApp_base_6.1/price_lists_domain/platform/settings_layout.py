"""Responsive settings sections with local scrolling and keyboard visibility."""
import tkinter as tk
from tkinter import ttk


class ScrollSection(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="App.TFrame")
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, height=200, width=300)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas, style="App.TFrame")
        self.window = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.tag = "SettingsScroll:" + str(self)
        self.bind_class(self.tag, "<MouseWheel>", self.wheel)
        self.bind_class(self.tag, "<Button-4>", lambda e: self.scroll(-3))
        self.bind_class(self.tag, "<Button-5>", lambda e: self.scroll(3))
        self.bind_class(self.tag, "<Next>", lambda e: self.scroll(1, "pages"))
        self.bind_class(self.tag, "<Prior>", lambda e: self.scroll(-1, "pages"))
        self.bind_class(self.tag, "<Control-Home>", lambda e: self.end(0))
        self.bind_class(self.tag, "<Control-End>", lambda e: self.end(1))
        self.bind_class(self.tag, "<FocusIn>", self.reveal)
        self.canvas.bind("<Configure>", self.resize)
        self.body.bind("<Configure>", self.content_changed)
        self.bind("<<ThemeChanged>>", self.theme)
        self.bind("<Destroy>", self.cleanup)
        self.theme()

    def theme(self, _event=None):
        self.canvas.configure(background=ttk.Style(self).lookup("App.TFrame", "background") or "#f2f4f5")

    def walk(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self.walk(child)

    def content_changed(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        for widget in self.walk(self):
            if self.tag not in widget.bindtags():
                # Run before legacy combobox bindings, which consume the wheel.
                widget.bindtags((self.tag,) + widget.bindtags())

    def resize(self, event):
        self.canvas.itemconfigure(self.window, width=max(1, event.width))
        for widget in self.walk(self.body):
            if isinstance(widget, ttk.Label):
                widget.configure(wraplength=max(100, event.width - 60))

    def scroll(self, amount, unit="units"):
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(amount, unit)
        return "break"

    def wheel(self, event):
        return self.scroll(-max(1, abs(event.delta) // 40) if event.delta > 0 else max(1, abs(event.delta) // 40))

    def end(self, fraction):
        self.canvas.yview_moveto(fraction)
        return "break"

    def reveal(self, event):
        widget = event.widget
        if widget in (self, self.canvas, self.bar, self.body):
            return
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        view = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if top < view + 8:
            self.canvas.yview_moveto(max(0, top - 8) / max(1, self.body.winfo_height()))
        elif bottom > view + height - 8:
            self.canvas.yview_moveto((bottom - height + 8) / max(1, self.body.winfo_height()))

    def cleanup(self, event):
        if event.widget is self:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>", "<Next>", "<Prior>", "<Control-Home>", "<Control-End>", "<FocusIn>"):
                self.unbind_class(self.tag, sequence)


def build_shell(app):
    page = app.tabs["settings"]
    header = ttk.Frame(page, style="App.TFrame")
    header.pack(fill="x", pady=(0, 10))
    ttk.Label(header, text="Nastavení", style="Title.TLabel").pack(side="left")
    ttk.Button(header, text="← Zpět na Přehled", command=lambda: app.show_page("dash")).pack(side="right")
    book = ttk.Notebook(page)
    book.pack(fill="both", expand=True)
    app._settings_notebook = book
    app._settings_sections = {}
    for key, title in (("general", "Obecné"), ("data", "Data a úložiště"), ("maintenance", "Aktualizace a údržba")):
        section = ScrollSection(book)
        book.add(section, text=title, padding=8)
        app._settings_sections[key] = section


def card(app, section):
    sections = getattr(app, "_settings_sections", {})
    parent = sections[section].body if section in sections else app.tabs["settings"]
    frame = ttk.Frame(parent, style="Panel.TFrame", padding=16)
    frame.pack(fill="x", pady=(0, 10))
    frame.columnconfigure(0, weight=1)
    return frame


def label(parent, text, row=0, heading=False):
    options = {"font": ("Calibri", 12, "bold")} if heading else {}
    widget = ttk.Label(parent, text=text, style="Panel.TLabel", wraplength=420, **options)
    widget.grid(row=row, column=0, sticky="w", pady=(0, 8))
    return widget


def action(parent, text, command, row, accent=False):
    button = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
    button.grid(row=row, column=0, sticky="w", pady=4)
    return button
