"""Inline internal pricing workspace for issued offers.

Keeps customer PDF rendering untouched while giving the editor a compact,
always-visible internal price table beside the live PDF preview.  Purchase price,
markup, line discount and profit are internal-only fields and never become part
of the rendered offer.
"""
from __future__ import annotations

from typing import Any


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


class PricingPanel:
    """Internal-only editable table synchronized with the offer preview."""

    def __init__(self, M: Any, editor: Any, host: Any, hidden_children: list[tuple[Any, dict[str, Any]]]):
        self.M = M
        self.editor = editor
        self.host = host
        self.hidden_children = hidden_children
        self.edit_widget = None
        self.edit_iid = None
        self.edit_column = None
        self.frame = M.ttk.Frame(host, style="Panel.TFrame", padding=(6, 4))
        self.frame.grid(row=1, column=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(2, weight=1)

        self.summary = M.tk.StringVar(value="")
        M.ttk.Label(
            self.frame,
            text="Interní cenotvorba",
            font=("Calibri", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")
        M.ttk.Label(
            self.frame,
            textvariable=self.summary,
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="ew", pady=(2, 5))

        columns = ("Produkt", "NC/MJ", "Marže %", "Sleva %", "Zisk")
        widths = (190, 85, 72, 72, 100)
        wrap = M.ttk.Frame(self.frame)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.tree = M.ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
        for column, width in zip(columns, widths):
            self.tree.heading(column, text=column)
            self.tree.column(
                column,
                width=width,
                minwidth=55,
                anchor="w" if column == "Produkt" else "e",
                stretch=column == "Produkt",
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys = M.ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.tag_configure("heading", font=("Calibri", 10, "bold"))
        self.tree.tag_configure("loss", foreground="#b42318")
        self.tree.bind("<Double-1>", self.begin_edit, add="+")
        self.tree.bind("<F2>", self.begin_margin_edit, add="+")
        self.tree.bind("<<TreeviewSelect>>", self.sync_selection, add="+")

        hint = (
            "Dvojklik: NC, marže nebo sleva. Zisk vychází z nákupní a skutečné "
            "prodejní ceny po slevách. Tyto interní údaje se do PDF nikdy nepřenášejí."
        )
        M.ttk.Label(
            self.frame,
            text=hint,
            style="PageSubtitle.TLabel",
            wraplength=500,
            justify="left",
        ).grid(row=3, column=0, sticky="ew", pady=(5, 0))
        self.refresh()

    def destroy_editor(self) -> None:
        if self.edit_widget is not None:
            try:
                self.edit_widget.destroy()
            except Exception:
                pass
        self.edit_widget = None
        self.edit_iid = None
        self.edit_column = None

    def refresh(self) -> None:
        self.destroy_editor()
        selected = self.tree.selection()
        selected_iid = selected[0] if selected else None
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        discount = self.editor.global_discount.get()
        service = self.editor._v791_service
        for index, raw in enumerate(self.editor.items):
            item = service.normalize_item(dict(raw), index + 1)
            row_type = _text(item.get("row_type")).casefold()
            name = _text(
                item.get("name")
                or item.get("internal_name_snapshot")
                or item.get("description")
                or item.get("internal_code_snapshot")
                or item.get("product_code")
            )
            iid = f"p{index}"
            if row_type not in PRICED_ROW_TYPES:
                self.tree.insert("", "end", iid=iid, values=(name, "", "", "", ""), tags=("heading",))
                continue
            profit = _profit(service, item, discount)
            tags = ("loss",) if profit < -0.005 else ()
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    name,
                    _fmt(service, item.get("purchase_unit_price")),
                    _fmt(service, item.get("margin_pct")),
                    _fmt(service, item.get("discount_pct")),
                    _fmt(service, profit),
                ),
                tags=tags,
            )
        if selected_iid and self.tree.exists(selected_iid):
            self.tree.selection_set(selected_iid)
            self.tree.see(selected_iid)
        purchase, sale, profit = _profit_totals(service, list(self.editor.items), discount)
        currency = _text(self.editor.currency.get()) or "CZK"
        self.summary.set(
            f"Nákup {_fmt(service, purchase)} {currency}  ·  "
            f"Prodej {_fmt(service, sale)} {currency}  ·  "
            f"Zisk {_fmt(service, profit)} {currency}"
        )

    def sync_selection(self, _event: Any = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        iid = str(selection[0])
        if not iid.startswith("p"):
            return
        try:
            index = int(iid[1:])
        except Exception:
            return
        preview = getattr(self.editor, "_v720_preview", None)
        if preview is not None:
            try:
                preview.selected_index = index
                preview.draw_selection()
            except Exception:
                pass
        try:
            row_iid = f"r{index}"
            if self.editor.tree.exists(row_iid):
                self.editor.tree.selection_set(row_iid)
                self.editor.tree.focus(row_iid)
        except Exception:
            pass

    def begin_margin_edit(self, _event: Any = None):
        selection = self.tree.selection()
        if not selection:
            return "break"
        self._open_editor(str(selection[0]), "#3")
        return "break"

    def begin_edit(self, event: Any = None):
        if getattr(self.editor, "locked", False):
            return "break"
        iid = self.tree.identify_row(event.y) if event is not None else ""
        column = self.tree.identify_column(event.x) if event is not None else ""
        if not iid or column not in {"#2", "#3", "#4"}:
            return None
        self._open_editor(iid, column)
        return "break"

    def _open_editor(self, iid: str, column: str) -> None:
        if getattr(self.editor, "locked", False):
            return
        if not iid.startswith("p"):
            return
        try:
            index = int(iid[1:])
        except Exception:
            return
        if not 0 <= index < len(self.editor.items):
            return
        service = self.editor._v791_service
        item = service.normalize_item(dict(self.editor.items[index]), index + 1)
        if _text(item.get("row_type")).casefold() not in PRICED_ROW_TYPES:
            return
        bbox = self.tree.bbox(iid, column)
        if not bbox:
            return
        self.destroy_editor()
        value_map = {
            "#2": item.get("purchase_unit_price"),
            "#3": item.get("margin_pct"),
            "#4": item.get("discount_pct"),
        }
        x, y, width, height = bbox
        variable = self.M.tk.StringVar(value=_fmt(service, value_map[column]))
        entry = self.M.ttk.Entry(self.tree, textvariable=variable, justify="right")
        entry.place(x=x, y=y, width=width, height=height)
        self.edit_widget = entry
        self.edit_iid = iid
        self.edit_column = column
        self.edit_variable = variable
        entry.focus_set()
        entry.selection_range(0, "end")
        entry.bind("<Return>", lambda _e: self.commit_edit(), add="+")
        entry.bind("<Escape>", lambda _e: self.cancel_edit(), add="+")
        entry.bind("<FocusOut>", lambda _e: self.commit_edit(), add="+")

    def cancel_edit(self) -> str:
        self.destroy_editor()
        return "break"

    def commit_edit(self) -> str:
        entry = self.edit_widget
        iid = self.edit_iid
        column = self.edit_column
        if entry is None or iid is None or column is None:
            return "break"
        try:
            index = int(iid[1:])
            service = self.editor._v791_service
            value = service.number(self.edit_variable.get())
            current = service.normalize_item(dict(self.editor.items[index]), index + 1)
            if column == "#2":
                current["purchase_unit_price"] = max(0.0, value)
                current = service.normalize_item(current, index + 1, recalculate_sale=True)
            elif column == "#3":
                current["margin_pct"] = value
                current = service.normalize_item(current, index + 1, recalculate_sale=True)
            elif column == "#4":
                current["discount_pct"] = min(100.0, max(-100.0, value))
                current = service.normalize_item(current, index + 1, recalculate_sale=True)
            self.editor.items[index] = current
        except Exception:
            self.destroy_editor()
            return "break"
        self.destroy_editor()
        self.editor.refresh_items()
        try:
            self.tree.selection_set(iid)
            self.tree.see(iid)
        except Exception:
            pass
        return "break"


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
                    # Preserve every existing control.  The default view merely
                    # hides the old right-hand details behind a mode switch.
                    original = []
                    for child in list(right.winfo_children()):
                        info = dict(child.grid_info())
                        if not info:
                            continue
                        original.append((child, info))
                        try:
                            child.grid_configure(row=int(info.get("row", 0)) + 1)
                            child.grid_remove()
                        except Exception:
                            pass
                    right.rowconfigure(1, weight=1)
                    right.rowconfigure(8, weight=1)
                    mode = M.ttk.Frame(right)
                    mode.grid(row=0, column=0, sticky="ew", pady=(0, 4))
                    mode.columnconfigure(0, weight=1)
                    self._v791_mode = M.tk.StringVar(value="prices")
                    pricing = PricingPanel(M, self, right, original)
                    self._v791_pricing_panel = pricing

                    def show_prices():
                        self._v791_mode.set("prices")
                        for child, _info in original:
                            try:
                                child.grid_remove()
                            except Exception:
                                pass
                        pricing.frame.grid()
                        pricing.refresh()

                    def show_terms():
                        self._v791_mode.set("terms")
                        pricing.frame.grid_remove()
                        for child, _info in original:
                            try:
                                child.grid()
                            except Exception:
                                pass

                    M.ttk.Button(mode, text="Cenotvorba", command=show_prices).grid(row=0, column=0, sticky="w")
                    M.ttk.Button(mode, text="Podmínky / poznámky", command=show_terms).grid(row=0, column=1, sticky="e")
                    try:
                        body.paneconfigure(left, weight=3)
                        body.paneconfigure(right, weight=2)
                        self.win.after(
                            80,
                            lambda current=body: current.sashpos(
                                0,
                                max(760, int(self.win.winfo_width() * 0.67)),
                            ),
                        )
                    except Exception:
                        pass
                    show_prices()

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
