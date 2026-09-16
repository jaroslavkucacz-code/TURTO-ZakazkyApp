"""Incremental table search: live draft AND removable, Enter-confirmed terms.

The same literal matching contract is used by in-memory tables and SQL pages.
No database content, table values, sorting or persisted layouts are rewritten.
"""
from __future__ import annotations

import re
import math
import unicodedata
import tkinter as tk
from tkinter import ttk


def normalize(value):
    return " ".join("".join(c for c in unicodedata.normalize(
        "NFKD", str(value if value is not None else "").casefold()
    ) if not unicodedata.combining(c)).split())


def match_ranges(text, search_terms):
    """Map normalized matches back to original glyphs, including combining marks.

    Case folding can expand one character (ß -> ss), while accents and repeated
    whitespace contract. Never use normalized offsets to slice displayed text.
    """
    text = str(text)
    folded, positions = [], []
    for index, char in enumerate(text):
        chars = ''.join(c for c in unicodedata.normalize('NFKD', char.casefold())
                        if not unicodedata.combining(c))
        if not chars and positions:
            positions[-1] = (positions[-1][0], index + 1)
        for c in chars:
            if c.isspace():
                if not folded:
                    continue
                if folded[-1] == ' ':
                    positions[-1] = (positions[-1][0], index + 1)
                    continue
                c = ' '
            folded.append(c)
            positions.append((index, index + 1))
    haystack = ''.join(folded).rstrip()
    matches = []
    for term in search_terms:
        term = normalize(term)
        start = haystack.find(term) if term else -1
        while start >= 0:
            matches.append((positions[start][0], positions[start + len(term) - 1][1]))
            start = haystack.find(term, start + 1)
    merged = []
    for start, end in sorted(matches):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def attach_tree(tree, bar):
    """Presentation-only association; SQL remains responsible for paged filtering."""
    tree._table_search = bar
    bar.trees.append(tree)


def searchable_text(*values):
    parts = [str(v) for v in values if v is not None]
    for value in values:
        if isinstance(value, (int, float)) and math.isfinite(value):
            whole, fraction = f"{value:,.4f}".split(".")
            parts.append(whole.replace(",", " ") + "," + fraction.rstrip("0").ljust(2, "0"))
    text = " | ".join(parts)
    # Search dates in the Czech form displayed in the UI as well as ISO storage.
    dates = re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    text += " " + " ".join(f"{d}.{m}.{y}" for y, m, d in dates)
    return normalize(text)


def register_sql(con):
    con.create_function("turto_search_text", -1, searchable_text, deterministic=True)


def terms(owner, key, fallback=""):
    bar = getattr(owner, "_table_searches", {}).get(key)
    return bar.terms if bar is not None else ([normalize(fallback)] if normalize(fallback) else [])


def add_sql_terms(where, params, search_terms, expressions):
    """Append bound literal conditions BEFORE COUNT/LIMIT/OFFSET (never LIKE)."""
    if not search_terms:
        return
    haystack = "turto_search_text(" + ",".join(expressions) + ")"
    for term in search_terms:
        where.append(f"instr({haystack},?)>0")
        params.append(normalize(term))


def reset_search(owner, key):
    bar = getattr(owner, "_table_searches", {}).get(key)
    if bar is not None:
        bar.reset()


def insert_matching(tree, *args, **kwargs):
    bar = getattr(tree, "_table_search", None)
    if bar is not None and bar.terms:
        haystack = searchable_text(*kwargs.get("values", ()))
        if not all(term in haystack for term in bar.terms):
            return None
    return tree.insert(*args, **kwargs)


class SearchBar(ttk.Frame):
    def __init__(self, parent, callback, clear_extra=None):
        super().__init__(parent, style="Panel.TFrame", padding=(8, 6))
        self.callback, self.clear_extra = callback, clear_extra
        self.confirmed = []
        self.trees = []
        self._terms = []
        self.draft = tk.StringVar(self)
        self._after = self._layout_after = None
        self._changing = False
        self.columnconfigure(1, weight=1)
        self.title = ttk.Label(self, text="Hledat v tabulce", style="FilterLabel.TLabel")
        self.title.grid(row=0, column=0, padx=(0, 8))
        self.entry = ttk.Entry(self, textvariable=self.draft, takefocus=True)
        self.entry._turto_search_input = True
        self.entry.grid(row=0, column=1, sticky="ew")
        self.clear_button = ttk.Button(self, text="Zrušit filtrování", command=self.clear, takefocus=False)
        self.clear_button.grid(row=0, column=2, padx=(8, 0))
        self.hint = ttk.Label(self, style="PanelMuted.TLabel")
        self.hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(3, 0))
        self.chips = ttk.Frame(self, style="Panel.TFrame")
        self.chips.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.buttons = []
        self.entry.bind("<Return>", self.confirm)
        self.entry.bind("<KP_Enter>", self.confirm)
        self._trace = self.draft.trace_add("write", self.changed)
        self.bind("<Configure>", self.queue_layout, add="+")
        self.bind("<Destroy>", self.close, add="+")
        self.update_state()

    @property
    def terms(self):
        return self._terms

    def changed(self, *_):
        if self._changing:
            return
        self._terms = [normalize(s) for s in (*self.confirmed, self.draft.get()) if normalize(s)]
        self.update_state()
        if self._after is not None:
            self.after_cancel(self._after)
        self._after = self.after(180, self.run)

    def run(self):
        self._after = None
        self.callback()

    def confirm(self, _event=None):
        value = self.draft.get().strip()
        if not value:
            return "break"
        self._changing = True
        if normalize(value) not in [normalize(s) for s in self.confirmed]:
            self.confirmed.append(value)
        self.draft.set("")
        self._changing = False
        self.render_chips()
        self.changed()
        return "break"  # Never submit/close a containing editor dialog.

    def remove(self, index):
        self.confirmed.pop(index)
        self.render_chips()
        self.changed()
        self.entry.focus_set()

    def reset(self):
        """Clear only this search; useful for existing 'clear all' actions."""
        self._changing = True
        self.confirmed.clear()
        self.draft.set("")
        self._changing = False
        self.render_chips()
        self.changed()

    def clear(self):
        self.reset()
        if self.clear_extra is not None:
            self.clear_extra()
        self.entry.focus_set()

    def update_state(self):
        self.clear_button.state(["!disabled"] if self.terms or self.clear_extra else ["disabled"])
        active = bool(self.terms)
        self.configure(style="ActiveSearch.TFrame" if active else "Panel.TFrame")
        self.chips.configure(style="ActiveSearch.TFrame" if active else "Panel.TFrame")
        self.title.configure(style="ActiveSearch.TLabel" if active else "FilterLabel.TLabel")
        self.hint.configure(
            style="ActiveSearch.TLabel" if active else "PanelMuted.TLabel",
            text=(f"Filtrování aktivní · Podmínky: {len(self.terms)} · Enter přidá další · × podmínku odebere"
                  if active else "Pište pro filtrování · Enter přidá podmínku · × podmínku odebere"))
        for tree in self.trees:
            decorator = getattr(tree, '_turto_cells_820', None)
            if decorator and tree.winfo_exists():
                decorator.schedule()

    def render_chips(self):
        for button in self.buttons:
            button.destroy()
        self.buttons = [ttk.Button(self.chips, text=value + "  ×", takefocus=False, style="SearchChip.TButton",
                                  command=lambda i=i: self.remove(i))
                        for i, value in enumerate(self.confirmed)]
        self.queue_layout()

    def queue_layout(self, _event=None):
        if self._layout_after is None:
            self._layout_after = self.after_idle(self.layout)

    def layout(self):
        self._layout_after = None
        width = max(100, self.winfo_width() - 20)
        x = y = height = 0
        for button in self.buttons:
            w = min(width, button.winfo_reqwidth())
            h = button.winfo_reqheight()
            if x and x + w > width:
                x, y = 0, y + height + 3
            button.place(x=x, y=y, width=w, height=h)
            x += w + 5
            height = h
        self.chips.configure(height=y + height + 4 if self.buttons else 0)
        if self.buttons:
            self.chips.grid()
        else:
            self.chips.grid_remove()

    def close(self, event):
        if event.widget is self:
            for token in (self._after, self._layout_after):
                if token is not None:
                    self.after_cancel(token)
            self.draft.trace_remove("write", self._trace)


def replace_filters(frame, owner, key, callback, keep_columns=(), clear_extra=None):
    """Replace legacy text filters, preserving explicit view/price-date controls."""
    kept = []
    for widget in frame.winfo_children():
        info = widget.grid_info()
        if info and int(info.get("column", -1)) in keep_columns:
            kept.append((widget, info))
        widget.grid_forget()
        widget.pack_forget()
        widget.place_forget()
    # Old column weights must not restrict the new field to the first column.
    for i in range(frame.grid_size()[0] + 20):
        frame.columnconfigure(i, weight=0, minsize=0)
    frame.columnconfigure(0, weight=1)
    bar = SearchBar(frame, callback, clear_extra)
    bar.grid(row=0, column=0, columnspan=max(1, len(keep_columns)), sticky="ew")
    for widget, info in kept:
        widget.grid(row=int(info["row"]) + 1, column=list(keep_columns).index(int(info["column"])),
                    sticky=info.get("sticky", "w"), padx=4)
    if not hasattr(owner, "_table_searches"):
        owner._table_searches = {}
    owner._table_searches[key] = bar
    return bar


def install_main_search(owner, tree, frame, key, refresh):
    # Keep old variables for shortcuts/compatibility, but their controls are no
    # longer mapped or in the keyboard focus path.
    bar = replace_filters(frame, owner, key, lambda: getattr(owner, refresh)())
    attach_tree(tree, bar)
    return bar
