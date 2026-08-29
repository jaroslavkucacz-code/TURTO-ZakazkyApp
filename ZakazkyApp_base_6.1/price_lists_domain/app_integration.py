"""Navigation, page and settings integration for the Ceníky domain."""
from __future__ import annotations

from .archive import price_list_archive_root, set_price_list_archive_root
from .importer import import_price_list
from .page import build_price_lists as build_legacy_price_lists
from .page import refresh_price_lists as refresh_legacy_price_lists


def _install_app_page(module):
    """Create the tab once; the active page owner is selected dynamically."""
    App = module.App
    if getattr(App, "_turto_price_list_tab_v6331", False):
        return

    old_build = App.build

    def build(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        try:
            page = self.tabs.get("pricelists")
            if page is None or not page.winfo_exists():
                page = module.ttk.Frame(self.pages, style="App.TFrame")
                page.grid(row=0, column=0, sticky="nsew")
                self.tabs["pricelists"] = page

            nav_parent = self.nav["offers"].master
            button = self.nav.get("pricelists")
            if button is None or not button.winfo_exists():
                button = module.ttk.Button(
                    nav_parent,
                    text="▥  Ceníky",
                    style="TopNav.TButton",
                    command=lambda: self.show_page("pricelists"),
                )
                self.nav["pricelists"] = button

            # Keep the user-approved navigation order.
            order = [
                "dash", "actions", "requests", "mivo", "offers", "pricelists",
                "companies", "projects", "tasks", "people", "help",
            ]
            for key in order:
                widget = self.nav.get(key)
                if widget is not None:
                    try:
                        widget.pack_forget()
                    except Exception:
                        pass
            for key in order:
                widget = self.nav.get(key)
                if widget is not None:
                    try:
                        widget.pack(side="left", padx=2, pady=(0, 2))
                    except Exception:
                        pass

            # platform.integration installs the scalable builder before any App
            # instance exists. The fallback keeps source compatibility.
            builder = getattr(self, "build_price_lists", None)
            if callable(builder):
                builder()
            else:
                build_legacy_price_lists(self)
            page.grid_remove()
        except Exception as exc:
            try:
                module.messagebox.showerror(
                    "Ceníky",
                    f"Záložku Ceníky se nepodařilo vytvořit:\n{exc}",
                    parent=self,
                )
            except Exception:
                pass
        return result

    App.build = build
    App.build_price_lists = build_legacy_price_lists
    App.refresh_price_lists = refresh_legacy_price_lists
    App.import_price_list = import_price_list
    App._turto_price_list_tab_v6331 = True


def _install_settings(module):
    App = module.App
    if getattr(App, "_turto_price_list_settings_v6331", False):
        return

    old_settings = App.build_settings

    def build_settings(self, *args, **kwargs):
        result = old_settings(self, *args, **kwargs)
        try:
            page = self.tabs["settings"]
            card = module.ttk.Frame(page, style="Panel.TFrame", padding=18)
            card.pack(fill="x", pady=(10, 0))
            module.ttk.Label(
                card,
                text="Trvalý archiv Ceníků",
                style="Panel.TLabel",
                font=("Calibri", 12, "bold"),
            ).grid(row=0, column=0, columnspan=3, sticky="w")
            variable = module.tk.StringVar(value=str(price_list_archive_root()))
            entry = module.ttk.Entry(card, textvariable=variable)
            entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
            card.columnconfigure(0, weight=1)

            def choose():
                value = module.filedialog.askdirectory(
                    parent=self,
                    initialdir=variable.get() or str(price_list_archive_root()),
                )
                if value:
                    variable.set(value)
                    set_price_list_archive_root(value)

            module.ttk.Button(card, text="Vybrat…", command=choose).grid(row=1, column=1)
            module.ttk.Label(
                card,
                text="Původní soubory se ukládají podle dodavatelů a nemažou se při DB-only odstranění.",
                style="Panel.TLabel",
            ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))
            entry.bind(
                "<FocusOut>",
                lambda _event: set_price_list_archive_root(variable.get())
                if variable.get().strip()
                else None,
            )
        except Exception:
            pass
        return result

    App.build_settings = build_settings
    App._turto_price_list_settings_v6331 = True
