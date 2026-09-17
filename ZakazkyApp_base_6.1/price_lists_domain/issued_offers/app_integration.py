"""TURTO CRM application integration for issued offers."""
from __future__ import annotations


def install(M) -> None:
    """Register the issued-offer page, commands and navigation exactly once."""
    App = M.App
    if getattr(App, "_turto_issued_offers_v638", False):
        return

    # Import late so every component receives the fully composed application module.
    from . import editor, page, pdf_renderer, settings, template_settings

    page.install(M)
    editor.install(M)
    pdf_renderer.install(M)
    settings.install(M)
    template_settings.install(M)

    # Register this page with the single responsive navigation owner before that
    # owner is installed by price_lists_domain.platform.install().
    try:
        from ..platform import lazy_refresh
        lazy_refresh.PAGE_REFRESH["issued_offers"] = "refresh_issued_offers"
        lazy_refresh.PAGE_TREES["issued_offers"] = ("issued_offer_tree",)
    except Exception:
        pass

    old_build = App.build

    def build(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        try:
            current = self.tabs.get("issued_offers")
            if current is None or not current.winfo_exists():
                current = M.ttk.Frame(self.pages, style="App.TFrame")
                current.grid(row=0, column=0, sticky="nsew")
                self.tabs["issued_offers"] = current

            from ..platform.grouped_navigation import register_page
            register_page(self, "issued_offers", "▤  Vydané nabídky")

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
    App._turto_issued_offers_v638 = True


__all__ = ["install"]
