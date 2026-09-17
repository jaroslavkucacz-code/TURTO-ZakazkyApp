"""Two navigation levels over the existing CRM pages and lazy refresh owner."""
from __future__ import annotations

GROUPS = {
    "directory": ("companies", "people"),
    "technical": ("actions", "requests", "mivo", "offers", "tasks"),
}
PAGE_GROUP = {page: group for group, pages in GROUPS.items() for page in pages}
# Keep the relative order of the remaining main pages.
TOP_ORDER = ("dash", "technical", "pricelists", "issued_offers", "projects", "directory", "help")
LABELS = {
    "dash": "⌂  Přehled", "technical": "Technika", "directory": "Adresář",
    "actions": "Ke zpracování", "requests": "Poptávky", "mivo": "MIVO",
    "offers": "Přijaté nabídky", "tasks": "Úkoly",
    "companies": "Společnosti", "people": "Osoby", "projects": "▣  Akce",
    "help": "?  Nápověda",
}


def resolve_page(app, key):
    """A group resumes its last page; direct links keep their stable leaf key."""
    if key not in GROUPS:
        return key
    available = [page for page in GROUPS[key] if page in getattr(app, "tabs", {})]
    previous = getattr(app, "_nav_last_pages", {}).get(key)
    return previous if previous in available else next(iter(available), key)


def register_page(app, key, label):
    """Extensions add their button to the correct row without moving pages."""
    from tkinter import ttk
    button = app.nav.get(key)
    if button is None or not button.winfo_exists():
        parent = app.nav_groups.get(PAGE_GROUP.get(key), app.main_nav)
        button = ttk.Button(parent, text=label, command=lambda: app.show_page(key),
                            style="SubNav.TButton" if key in PAGE_GROUP else "TopNav.TButton")
        button.bind("<Return>", lambda event: (button.invoke(), "break")[1])
        app.nav[key] = button
    else:
        button.configure(text=label)
    arrange(app)
    return button


def arrange(app):
    """One order owner, also used by delayed legacy startup callbacks."""
    if not hasattr(app, "nav_groups"):
        return
    for parent, keys in [(app.main_nav, TOP_ORDER), *(
        (app.nav_groups[group], pages) for group, pages in GROUPS.items()
    )]:
        buttons = [app.nav[key] for key in keys if key in app.nav]
        if list(parent.pack_slaves()) == buttons:
            continue
        for button in buttons:
            button.pack_forget()
        for button in buttons:
            button.pack(side="left", padx=2, pady=(0, 2))
    activate(app, getattr(app, "_current_page", "dash"))


def activate(app, key):
    """Show only the relevant second row and highlight both navigation levels."""
    group = PAGE_GROUP.get(key)
    rows = getattr(app, "nav_groups", {})
    if group in rows:
        app._nav_last_pages[group] = key
    for name, row in rows.items():
        if name == group:
            if not row.winfo_manager():
                row.pack(fill="x", after=app.main_nav)
        else:
            row.pack_forget()
    for name, button in getattr(app, "nav", {}).items():
        if not button.winfo_exists():
            continue
        prefix = "SubNav" if rows and name in PAGE_GROUP else "TopNav"
        active = name == key or (bool(rows) and name == group)
        button.configure(style=prefix + ("Active.TButton" if active else ".TButton"))


def build(app, parent):
    from tkinter import ttk
    app.main_nav = ttk.Frame(parent, style="NavBar.TFrame", padding=(10, 0))
    app.main_nav.pack(fill="x")
    app.nav_groups = {
        key: ttk.Frame(parent, style="SubNav.TFrame", padding=(10, 0)) for key in GROUPS
    }
    app._nav_last_pages = {}
    app.nav = {}
    for key, label in LABELS.items():
        register_page(app, key, label)
