"""Inline internal pricing workspace for issued offers.

Keeps customer PDF rendering untouched while giving the editor a compact,
always-visible internal price table beside the live PDF preview.  Purchase price,
markup, line discount and profit are internal-only fields and never become part
of the rendered offer.
"""
from __future__ import annotations

from typing import Any
from . import group_pricing


PRICED_ROW_TYPES = {"product", "service", "delivery"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fmt(service: Any, value: Any, decimals: int = 2) -> str:
    try:
        number = float(service.number(value))
    except Exception:
        number = 0.0
    text = f"{number:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return text


def _profit(service: Any, item: dict[str, Any], global_discount_pct: Any = 0) -> float:
    quantity = service.number(item.get("quantity"))
    purchase = service.number(item.get("purchase_unit_price"))
    sale = service.number(item.get("unit_price"))
    discount = min(100.0, max(-100.0, service.number(global_discount_pct)))
    final_sale = sale * (1.0 - discount / 100.0)
    return quantity * (final_sale - purchase)


def _profit_totals(service: Any, items: list[dict[str, Any]], global_discount_pct: Any = 0) -> tuple[float, float, float]:
    purchase_total = 0.0
    sale_total = 0.0
    for raw in items:
        item = service.normalize_item(dict(raw))
        if _text(item.get("row_type")).casefold() not in PRICED_ROW_TYPES:
            continue
        quantity = service.number(item.get("quantity"))
        purchase_total += quantity * service.number(item.get("purchase_unit_price"))
        sale_total += quantity * service.number(item.get("unit_price"))
    discount = min(100.0, max(-100.0, service.number(global_discount_pct)))
    sale_total *= 1.0 - discount / 100.0
    return purchase_total, sale_total, sale_total - purchase_total


from .canvas_pricing import PricingPanel


def apply(M: Any) -> None:
    if getattr(M, "_turto_v791_inline_pricing_workspace", False):
        return
    try:
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import service
    except Exception:
        return

    Editor = issued_editor.IssuedOfferEditor
    if getattr(Editor, "_turto_v791_inline_pricing_workspace", False):
        M._turto_v791_inline_pricing_workspace = True
        return

    previous_init = Editor.__init__
    previous_refresh_items = Editor.refresh_items
    previous_refresh_totals = Editor.refresh_totals

    def refresh_workspace(self: Any) -> None:
        panel = getattr(self, "_v791_pricing_panel", None)
        if panel is not None:
            try:
                panel.refresh()
            except Exception:
                pass

    def refresh_items(self: Any, *args: Any, **kwargs: Any):
        result = previous_refresh_items(self, *args, **kwargs)
        refresh_workspace(self)
        return result

    def refresh_totals(self: Any, *args: Any, **kwargs: Any):
        result = previous_refresh_totals(self, *args, **kwargs)
        try:
            purchase, sale, profit = _profit_totals(
                service, list(self.items), self.global_discount.get()
            )
            currency = _text(self.currency.get()) or "CZK"
            lines = [
                f"Prodej: {_fmt(service, sale)} {currency}",
                f"Nákup: {_fmt(service, purchase)} {currency}",
                f"Zisk: {_fmt(service, profit)} {currency}",
            ]
            self.totals_text.set("\n".join(lines))
        except Exception:
            pass
        refresh_workspace(self)
        return result

    def init(self: Any, *args: Any, **kwargs: Any):
        previous_init(self, *args, **kwargs)
        self._v791_service = service
        try:
            # After v780 the canonical rows are: 0 heading, 1 workflow,
            # 2 offer metadata, 3 work area, 4 footer.
            metadata = None
            body = None
            footer = None
            for child in self.outer.winfo_children():
                try:
                    row = int(child.grid_info().get("row", -1))
                except Exception:
                    continue
                if row == 2:
                    metadata = child
                elif row == 3 and isinstance(child, M.ttk.Panedwindow):
                    body = child
                elif row == 4:
                    footer = child
            if metadata is not None:
                self._v791_metadata_panel = metadata
                metadata.grid_remove()
                self._v791_metadata_visible = False

                def toggle_metadata():
                    if getattr(self, "_v791_metadata_visible", False):
                        metadata.grid_remove()
                        self._v791_metadata_visible = False
                        self._v791_metadata_button.configure(text="Údaje nabídky…")
                    else:
                        metadata.grid()
                        self._v791_metadata_visible = True
                        self._v791_metadata_button.configure(text="Skrýt údaje")

                if footer is not None:
                    self._v791_metadata_button = M.ttk.Button(
                        footer,
                        text="Údaje nabídky…",
                        command=toggle_metadata,
                    )
                    self._v791_metadata_button.pack(side="left", padx=(5, 0))

            if body is not None:
                panes = [self.win.nametowidget(name) for name in body.panes()]
                if len(panes) >= 2:
                    left, right = panes[0], panes[1]
                    pricing = PricingPanel(M, self)
                    self._v791_pricing_panel = pricing
                    self._v791_mode = M.tk.StringVar(value='prices')
                    body.forget(right)
                    def toggle_prices():
                        pricing.visible = not pricing.visible
                        pricing.cancel_edit()
                        prices_button.configure(text='Skrýt cenotvorbu' if pricing.visible else 'Cenotvorba')
                        self._v720_preview.schedule(10)
                    def toggle_terms():
                        if str(right) in body.panes():
                            body.forget(right); terms_button.configure(text='Podmínky / poznámky')
                        else:
                            body.add(right, weight=1); body.sashpos(0,max(500,body.winfo_width()-380))
                            terms_button.configure(text='Skrýt podmínky')
                    if footer is not None:
                        prices_button=M.ttk.Button(footer,text='Skrýt cenotvorbu',command=toggle_prices)
                        prices_button.pack(side='left',padx=3)
                        terms_button=M.ttk.Button(footer,text='Podmínky / poznámky',command=toggle_terms)
                        terms_button.pack(side='left',padx=3)
                        M.ttk.Button(footer,text='Vzhled nabídky…',command=self.edit_pdf_template).pack(side='left',padx=3)
                    summary=M.ttk.Label(self._v720_preview.frame,textvariable=pricing.summary,style='PageSubtitle.TLabel')
                    summary.grid(row=2,column=0,sticky='w',pady=3)
                    pricing.refresh()


            # Total profit must react immediately to document-wide discount.
            try:
                self.global_discount.trace_add(
                    "write", lambda *_args, current=self: refresh_workspace(current)
                )
            except Exception:
                pass
        except Exception:
            pass

    Editor.__init__ = init
    Editor.refresh_items = refresh_items
    Editor.refresh_totals = refresh_totals
    Editor._turto_v791_inline_pricing_workspace = True
    M._turto_v791_inline_pricing_workspace = True


__all__ = ["apply", "_profit", "_profit_totals"]
