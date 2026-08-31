"""TURTO CRM application integration for issued offers."""
from __future__ import annotations

from . import schema


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_issued_offers_v637", False):
        return

    old_ensure = M.ensure_schema

    def ensure_schema():
        old_ensure()
        schema.ensure_business_documents_schema(M)

    M.ensure_schema = ensure_schema
    M.ensure_business_documents_schema = lambda: schema.ensure_business_documents_schema(M)

    # Import late so the module receives the fully composed app module.
    from . import editor, page, pdf_renderer, settings, template_settings

    page.install(M)
    editor.install(M)
    pdf_renderer.install(M)
    settings.install(M)
    template_settings.install(M)

    old_build = App.build

    def build(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        try:
            current = self.tabs.get("issued_offers")
            if current is None or not current.winfo_exists():
                current = M.ttk.Frame(self.pages, style="App.TFrame")
                current.grid(row=0, column=0, sticky="nsew")
                self.tabs["issued_offers"] = current

            nav_parent = self.nav["offers"].master
            button = self.nav.get("issued_offers")
            if button is None or not button.winfo_exists():
                button = M.ttk.Button(
                    nav_parent,
                    text="▤  Vydané nabídky",
                    style="TopNav.TButton",
                    command=lambda: self.show_page("issued_offers"),
                )
                self.nav["issued_offers"] = button

            # Clarify direction without changing the existing page key or data owner.
            offers_button = self.nav.get("offers")
            if offers_button is not None:
                offers_button.configure(text="▥  Přijaté nabídky")

            order = [
                "dash", "actions", "requests", "mivo", "offers", "issued_offers", "pricelists",
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

            self.build_issued_offers()
            current.grid_remove()
        except Exception as exc:
            try:
                M.messagebox.showerror(
                    "Vydané nabídky",
                    f"Záložku Vydané nabídky se nepodařilo vytvořit:\n{exc}",
                    parent=self,
                )
            except Exception:
                pass
        return result

    App.build = build
    App._turto_issued_offers_v637 = True


__all__ = ["install"]
