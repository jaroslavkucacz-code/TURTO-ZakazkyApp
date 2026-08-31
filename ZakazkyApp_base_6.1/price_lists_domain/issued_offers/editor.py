"""CRM editor for issued offers."""
from __future__ import annotations

from datetime import date
from typing import Any

from . import service


def _fmt(value, decimals=2) -> str:
    return f"{service.number(value):.{decimals}f}".replace(".", ",")


def _parse(value, default=0.0) -> float:
    return service.number(value, default)


def _display_name(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("internal_name_snapshot") or item.get("description") or "")


class ItemDialog:
    def __init__(self, M, parent, item=None, default_vat=21.0):
        self.M = M
        self.parent = parent
        self.result = None
        self.item = service.normalize_item(dict(item or {}), recalculate_sale=False)
        if not self.item.get("vat_rate"):
            self.item["vat_rate"] = default_vat
        self.win = M.tk.Toplevel(parent)
        self.win.title("Položka vydané nabídky")
        self.win.transient(parent)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 920, 650)
        frame = M.scrollable_dialog_frame(self.win, 16)
        frame.columnconfigure(1, weight=1)

        self.row_type = M.tk.StringVar(value=service.ROW_TYPES.get(self.item.get("row_type"), "Produkt"))
        self.code = M.tk.StringVar(value=str(self.item.get("internal_code_snapshot") or self.item.get("product_code") or ""))
        self.name = M.tk.StringVar(value=_display_name(self.item))
        self.quantity = M.tk.StringVar(value=_fmt(self.item.get("quantity"), 3))
        self.unit = M.tk.StringVar(value=str(self.item.get("unit") or "ks"))
        self.purchase = M.tk.StringVar(value=_fmt(self.item.get("purchase_unit_price")))
        self.margin = M.tk.StringVar(value=_fmt(self.item.get("margin_pct")))
        self.recommended = M.tk.StringVar(value=_fmt(self.item.get("recommended_unit_price")))
        self.discount = M.tk.StringVar(value=_fmt(self.item.get("discount_pct")))
        self.sale = M.tk.StringVar(value=_fmt(self.item.get("unit_price")))
        self.vat = M.tk.StringVar(value=_fmt(self.item.get("vat_rate")))
        self.show_recommended = M.tk.BooleanVar(value=bool(self.item.get("show_recommended_price", 1)))

        row = 0
        fields = (
            ("Typ řádku", self.row_type, "combo"),
            ("Interní / zákaznický kód", self.code, "entry"),
            ("Označení", self.name, "entry"),
            ("Množství", self.quantity, "entry"),
            ("Měrná jednotka", self.unit, "entry"),
            ("Nákupní cena / MJ", self.purchase, "entry"),
            ("Marže [%]", self.margin, "entry"),
            ("Doporučená cena / MJ", self.recommended, "entry"),
            ("Sleva [%]", self.discount, "entry"),
            ("Výsledná cena / MJ", self.sale, "entry"),
            ("DPH [%]", self.vat, "entry"),
        )
        reverse_types = {label: key for key, label in service.ROW_TYPES.items()}
        self._reverse_types = reverse_types
        for label, variable, kind in fields:
            self.M.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            if kind == "combo":
                widget = self.M.safe_combobox(frame, textvariable=variable, values=list(reverse_types), state="readonly")
            else:
                widget = self.M.ttk.Entry(frame, textvariable=variable)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            row += 1

        self.M.ttk.Checkbutton(
            frame,
            text="V PDF zobrazit doporučenou cenu a slevu, pokud to dovoluje produktová skupina",
            variable=self.show_recommended,
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(7, 5))
        row += 1
        self.M.ttk.Label(frame, text="Popis pro zákazníka").grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=5)
        self.description = self.M.tk.Text(frame, height=5, wrap="word", font=("Calibri", 11))
        self.description.grid(row=row, column=1, sticky="ew", pady=5)
        self.description.insert("1.0", str(self.item.get("description") or ""))
        row += 1
        self.M.ttk.Label(frame, text="Poznámka k řádku").grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=5)
        self.line_note = self.M.tk.Text(frame, height=3, wrap="word", font=("Calibri", 11))
        self.line_note.grid(row=row, column=1, sticky="ew", pady=5)
        self.line_note.insert("1.0", str(self.item.get("line_note") or ""))
        row += 1

        hint = self.M.tk.StringVar(value="")
        self.M.ttk.Label(frame, textvariable=hint, style="PageSubtitle.TLabel").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(5, 2)
        )
        row += 1

        def recalculate(*_):
            try:
                purchase = _parse(self.purchase.get())
                margin = _parse(self.margin.get())
                discount = _parse(self.discount.get())
                recommended = purchase * (1 + margin / 100)
                sale = recommended * (1 - discount / 100)
                self.recommended.set(_fmt(recommended))
                self.sale.set(_fmt(sale))
                quantity = _parse(self.quantity.get(), 1)
                hint.set(f"Celkem bez DPH: {_fmt(quantity * sale)}")
            except Exception:
                hint.set("")

        for var in (self.purchase, self.margin, self.discount, self.quantity):
            var.trace_add("write", recalculate)
        recalculate()

        buttons = self.M.ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(14, 0))
        self.M.ttk.Button(buttons, text="Zrušit", command=self.win.destroy).pack(side="right")
        self.M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=self.save).pack(side="right", padx=(0, 6))
        try:
            self.M.center_dialog(self.win, parent)
        except Exception:
            pass
        self.win.wait_window()

    def save(self):
        row_type = self._reverse_types.get(self.row_type.get(), "product")
        name = self.name.get().strip()
        description = self.description.get("1.0", "end-1c").strip()
        if row_type != "text" and not name:
            return self.M.messagebox.showwarning("Vydané nabídky", "Vyplňte označení položky.", parent=self.win)
        if row_type == "text" and not description:
            return self.M.messagebox.showwarning("Vydané nabídky", "Vyplňte text poznámky.", parent=self.win)
        item = dict(self.item)
        item.update(
            row_type=row_type,
            product_code=self.code.get().strip(),
            internal_code_snapshot=self.code.get().strip(),
            name=name,
            internal_name_snapshot=name,
            description=description,
            quantity=_parse(self.quantity.get()),
            unit=self.unit.get().strip(),
            purchase_unit_price=_parse(self.purchase.get()),
            margin_pct=_parse(self.margin.get()),
            recommended_unit_price=_parse(self.recommended.get()),
            discount_pct=_parse(self.discount.get()),
            unit_price=_parse(self.sale.get()),
            vat_rate=_parse(self.vat.get(), 21),
            show_recommended_price=1 if self.show_recommended.get() else 0,
            line_note=self.line_note.get("1.0", "end-1c").strip(),
        )
        self.result = service.normalize_item(item)
        self.win.destroy()


class ProductPicker:
    def __init__(self, M, parent):
        self.M = M
        self.result = []
        self.win = M.tk.Toplevel(parent)
        self.win.title("Vybrat produkty z katalogu")
        self.win.transient(parent)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 1350, 760)
        outer = M.ttk.Frame(self.win, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)
        M.ttk.Label(outer, text="Produkty z interního katalogu", font=("Calibri", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.query = M.tk.StringVar()
        search = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
        search.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        search.columnconfigure(0, weight=1)
        M.ttk.Entry(search, textvariable=self.query).grid(row=0, column=0, sticky="ew")
        M.ttk.Button(search, text="Hledat", command=self.refresh).grid(row=0, column=1, padx=(6, 0))
        cols = ("Interní kód", "Interní označení", "Výrobce", "Skupina", "Podskupina", "Nákupní cena", "MJ", "Zdroj")
        widths = (125, 300, 175, 230, 260, 120, 65, 220)
        wrap = M.ttk.Frame(outer)
        wrap.grid(row=2, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.tree = M.ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for column, width in zip(cols, widths):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=width, anchor="w", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys = M.ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.rows = {}
        buttons = M.ttk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        M.ttk.Button(buttons, text="Zrušit", command=self.win.destroy).pack(side="right")
        M.ttk.Button(buttons, text="Přidat vybrané", style="Accent.TButton", command=self.finish).pack(side="right", padx=(0, 6))
        self.query.bind("<Return>", lambda _event: self.refresh())
        self.tree.bind("<Double-1>", lambda _event: self.finish())
        self.refresh()
        self.win.wait_window()

    def refresh(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.rows.clear()
        rows = service.catalog_products(self.M, self.query.get(), 1000)
        for row in rows:
            iid = f"cp{row['catalog_product_id']}"
            self.rows[iid] = row
            self.tree.insert(
                "", "end", iid=iid,
                values=(
                    row.get("internal_code") or row.get("supplier_product_code") or "",
                    row.get("internal_name") or row.get("source_name") or "",
                    row.get("manufacturer_name") or "",
                    row.get("category") or "Nezařazeno",
                    row.get("subgroup") or "",
                    _fmt(row.get("purchase_price")),
                    row.get("unit") or "",
                    row.get("price_source_label") or "",
                ),
            )

    def finish(self):
        selected = [self.rows[iid] for iid in self.tree.selection() if iid in self.rows]
        if not selected:
            return self.M.messagebox.showinfo("Vydané nabídky", "Vyberte jeden nebo více produktů.", parent=self.win)
        self.result = [dict(item) for item in selected]
        self.win.destroy()


class IssuedOfferEditor:
    def __init__(self, M, app, document_id=None):
        self.M = M
        self.app = app
        self.document_id = int(document_id) if document_id else None
        self.items = []
        self._loading = False
        self.win = M.tk.Toplevel(app)
        self.win.title("Vydaná nabídka")
        self.win.transient(app)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 1580, 880)
        self.outer = M.ttk.Frame(self.win, padding=12)
        self.outer.pack(fill="both", expand=True)
        self.outer.columnconfigure(0, weight=1)
        self.outer.rowconfigure(2, weight=1)

        document = service.offer_defaults(M)
        if self.document_id:
            document, self.items = service.load_document(M, self.document_id)
        self.document = document
        self.locked = bool(document.get("locked"))

        heading = M.ttk.Frame(self.outer, style="Panel.TFrame", padding=(12, 9))
        heading.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        heading.columnconfigure(0, weight=1)
        title = document.get("document_number") or "Nová vydaná nabídka"
        M.ttk.Label(heading, text=title, font=("Calibri", 17, "bold")).grid(row=0, column=0, sticky="w")
        self.status_hint = M.tk.StringVar(value="")
        M.ttk.Label(heading, textvariable=self.status_hint, style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w")
        if self.locked:
            M.ttk.Label(
                heading,
                text="Dokument je po odeslání uzamčen. Pro změny vytvořte kopii nebo novou revizi.",
                style="PageSubtitle.TLabel",
            ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))

        header = M.ttk.Frame(self.outer, style="Card.TFrame", padding=10)
        header.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        for col in (1, 3, 5):
            header.columnconfigure(col, weight=1)

        self.issue_date = M.tk.StringVar(value=str(document.get("issue_date") or date.today().isoformat()))
        self.valid_to = M.tk.StringVar(value=str(document.get("valid_to") or ""))
        self.status = M.tk.StringVar(value=str(document.get("status") or "Rozpracováno"))
        self.currency = M.tk.StringVar(value=str(document.get("currency") or "CZK"))
        self.subject = M.tk.StringVar(value=str(document.get("offer_subject") or ""))
        self.reference = M.tk.StringVar(value=str(document.get("customer_reference") or ""))
        self.salesperson = M.tk.StringVar(value=str(document.get("salesperson_snapshot") or service.active_user(M)))
        self.global_discount = M.tk.StringVar(value=_fmt(document.get("global_discount_pct")))

        companies = service.list_companies(M)
        self.company_map = {name: cid for cid, name in companies}
        company_name = str(document.get("customer_name_snapshot") or document.get("company_name") or "")
        self.company = M.tk.StringVar(value=company_name)
        self.contact = M.tk.StringVar(value=str(document.get("customer_contact_snapshot") or ""))
        self.contact_map = {}
        projects = service.list_projects(M)
        self.project_map = {name: pid for pid, name in projects}
        self.project = M.tk.StringVar(value=str(document.get("project_name") or ""))
        actions = service.list_actions(M)
        self.action_map = {name: (aid, pid) for aid, name, pid in actions}
        self.action = M.tk.StringVar(value=str(document.get("action_name") or ""))
        templates = service.list_templates(M)
        self.template_map = {str(row["name"]): int(row["id"]) for row in templates}
        current_template = next((name for name, tid in self.template_map.items() if tid == document.get("template_id")), next(iter(self.template_map), "Standardní nabídka TURTO"))
        self.template = M.tk.StringVar(value=current_template)

        fields = (
            ("Datum vystavení", self.issue_date, "date"),
            ("Platnost do", self.valid_to, "date"),
            ("Stav", self.status, "status"),
            ("Měna", self.currency, "currency"),
            ("Odběratel", self.company, "company"),
            ("Kontaktní osoba", self.contact, "contact"),
            ("Příležitost", self.action, "action"),
            ("Akce", self.project, "project"),
            ("Předmět nabídky", self.subject, "entry"),
            ("Reference zákazníka", self.reference, "entry"),
            ("Obchodník", self.salesperson, "entry"),
            ("PDF šablona", self.template, "template"),
        )
        self.widgets = []
        for index, (label, variable, kind) in enumerate(fields):
            row = index // 3
            col = (index % 3) * 2
            M.ttk.Label(header, text=label, style="FilterLabel.TLabel").grid(row=row * 2, column=col, sticky="w", padx=(0, 5))
            if kind == "date":
                widget = M.DatePicker(header, variable)
            elif kind == "status":
                widget = M.safe_combobox(header, textvariable=variable, values=list(service.STATUSES), state="readonly")
            elif kind == "currency":
                widget = M.safe_combobox(header, textvariable=variable, values=["CZK", "EUR", "PLN"], state="readonly")
            elif kind == "company":
                widget = M.AutocompleteEntry(header, textvariable=variable, values=list(self.company_map))
                self.company_box = widget
            elif kind == "contact":
                widget = M.AutocompleteEntry(header, textvariable=variable, values=[])
                self.contact_box = widget
            elif kind == "action":
                widget = M.AutocompleteEntry(header, textvariable=variable, values=list(self.action_map))
            elif kind == "project":
                widget = M.AutocompleteEntry(header, textvariable=variable, values=list(self.project_map))
            elif kind == "template":
                widget = M.safe_combobox(header, textvariable=variable, values=list(self.template_map), state="readonly")
            else:
                widget = M.ttk.Entry(header, textvariable=variable)
            widget.grid(row=row * 2 + 1, column=col, sticky="ew", padx=(0, 12), pady=(0, 6))
            self.widgets.append(widget)

        body = M.ttk.Panedwindow(self.outer, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")
        left = M.ttk.Frame(body)
        right = M.ttk.Frame(body, style="Panel.TFrame", padding=10)
        body.add(left, weight=4)
        body.add(right, weight=1)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(7, weight=1)

        tools = M.ttk.Frame(left, style="Panel.TFrame", padding=7)
        tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        M.ttk.Button(tools, text="+ Z katalogu", style="Accent.TButton", command=self.add_from_catalog).pack(side="left")
        M.ttk.Button(tools, text="+ Ruční položka", command=self.add_manual).pack(side="left", padx=4)
        M.ttk.Button(tools, text="+ Nadpis", command=lambda: self.add_special("heading")).pack(side="left", padx=4)
        M.ttk.Button(tools, text="+ Text", command=lambda: self.add_special("text")).pack(side="left", padx=4)
        M.ttk.Button(tools, text="Upravit", command=self.edit_item).pack(side="left", padx=(14, 4))
        M.ttk.Button(tools, text="Odebrat", command=self.remove_items).pack(side="left", padx=4)
        M.ttk.Button(tools, text="Nahoru", command=lambda: self.move_item(-1)).pack(side="left", padx=(14, 4))
        M.ttk.Button(tools, text="Dolů", command=lambda: self.move_item(1)).pack(side="left", padx=4)

        columns = (
            "Poz.", "Typ", "Kód", "Označení", "Množství", "MJ", "Nákupní cena", "Marže",
            "Doporučená cena", "Sleva", "Prodejní cena", "Celkem bez DPH",
        )
        widths = (55, 100, 120, 360, 90, 60, 115, 75, 125, 75, 115, 130)
        wrap = M.ttk.Frame(left)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(0, weight=1)
        self.tree = M.ttk.Treeview(wrap, columns=columns, show="headings", selectmode="extended")
        for column, width in zip(columns, widths):
            self.tree.heading(column, text=column)
            self.tree.column(column, width=width, anchor="w", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys = M.ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.bind("<Double-1>", lambda _event: self.edit_item())

        M.ttk.Label(right, text="Souhrn nabídky", font=("Calibri", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.totals_text = M.tk.StringVar(value="")
        M.ttk.Label(right, textvariable=self.totals_text, justify="left", font=("Calibri", 11)).grid(row=1, column=0, sticky="ew", pady=(7, 12))
        M.ttk.Label(right, text="Celková sleva [%]").grid(row=2, column=0, sticky="w")
        M.ttk.Entry(right, textvariable=self.global_discount).grid(row=3, column=0, sticky="ew", pady=(3, 10))
        M.ttk.Label(right, text="Platební podmínky").grid(row=4, column=0, sticky="w")
        self.payment_terms = M.tk.Text(right, height=4, wrap="word", font=("Calibri", 10))
        self.payment_terms.grid(row=5, column=0, sticky="ew", pady=(3, 8))
        self.payment_terms.insert("1.0", str(document.get("payment_terms") or ""))
        M.ttk.Label(right, text="Dodací podmínky a termín").grid(row=6, column=0, sticky="w")
        terms = M.ttk.Notebook(right)
        terms.grid(row=7, column=0, sticky="nsew", pady=(3, 8))
        delivery_page = M.ttk.Frame(terms, padding=5)
        time_page = M.ttk.Frame(terms, padding=5)
        note_page = M.ttk.Frame(terms, padding=5)
        internal_page = M.ttk.Frame(terms, padding=5)
        for page, label in ((delivery_page, "Dodání"), (time_page, "Termín"), (note_page, "Pro zákazníka"), (internal_page, "Interní")):
            terms.add(page, text=label)
        self.delivery_terms = M.tk.Text(delivery_page, height=5, wrap="word", font=("Calibri", 10))
        self.delivery_terms.pack(fill="both", expand=True)
        self.delivery_terms.insert("1.0", str(document.get("delivery_terms") or ""))
        self.delivery_time = M.tk.Text(time_page, height=5, wrap="word", font=("Calibri", 10))
        self.delivery_time.pack(fill="both", expand=True)
        self.delivery_time.insert("1.0", str(document.get("delivery_time") or ""))
        self.customer_note = M.tk.Text(note_page, height=5, wrap="word", font=("Calibri", 10))
        self.customer_note.pack(fill="both", expand=True)
        self.customer_note.insert("1.0", str(document.get("customer_note") or ""))
        self.internal_note = M.tk.Text(internal_page, height=5, wrap="word", font=("Calibri", 10))
        self.internal_note.pack(fill="both", expand=True)
        self.internal_note.insert("1.0", str(document.get("internal_note") or ""))

        footer = M.ttk.Frame(self.outer, style="Panel.TFrame", padding=8)
        footer.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        M.ttk.Button(footer, text="Zavřít", command=self.close).pack(side="right")
        M.ttk.Button(footer, text="Uložit", style="Accent.TButton", command=self.save).pack(side="right", padx=5)
        self.pdf_button = M.ttk.Button(footer, text="Vytvořit a otevřít PDF", command=lambda: self.generate_pdf(True))
        self.pdf_button.pack(side="right", padx=5)
        self.draft_button = M.ttk.Button(footer, text="Outlook koncept", command=self.outlook_draft)
        self.draft_button.pack(side="right", padx=5)
        M.ttk.Button(footer, text="Nastavení šablony…", command=lambda: getattr(self.app, "manage_issued_offer_templates")()).pack(side="left")

        self.company.trace_add("write", self.company_changed)
        self.global_discount.trace_add("write", lambda *_: self.refresh_totals())
        self.status.trace_add("write", lambda *_: self.refresh_status())
        self.refresh_contacts()
        self.refresh_items()
        self.refresh_status()
        self.set_readonly(self.locked)

    def set_readonly(self, value):
        if not value:
            return
        for widget in self.widgets:
            try:
                widget.state(["disabled"])
            except Exception:
                try:
                    widget.configure(state="disabled")
                except Exception:
                    pass
        for widget in (self.payment_terms, self.delivery_terms, self.delivery_time, self.customer_note, self.internal_note):
            try:
                widget.configure(state="disabled")
            except Exception:
                pass

    def company_changed(self, *_):
        self.refresh_contacts()

    def refresh_contacts(self):
        company_id = self.company_map.get(self.company.get().strip())
        rows = service.list_people(self.M, company_id)
        self.contact_map = {name: pid for pid, name in rows}
        try:
            self.contact_box.set_values(list(self.contact_map))
        except Exception:
            pass
        if self.contact.get().strip() not in self.contact_map and not self._loading:
            self.contact.set("")

    def refresh_status(self):
        text = self.status.get()
        if text == "Odesláno":
            self.status_hint.set("Nabídka byla odeslána; další změny doporučujeme řešit duplikací nebo novou revizí.")
        elif text == "Připraveno":
            self.status_hint.set("Dokument je připraven k vytvoření PDF a odeslání.")
        else:
            self.status_hint.set("Rozpracovaný dokument lze průběžně ukládat.")

    def refresh_items(self):
        selected_indices = []
        for iid in self.tree.selection():
            try:
                selected_indices.append(int(str(iid)[1:]))
            except Exception:
                pass
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        normalized = []
        for index, raw in enumerate(self.items, 1):
            item = service.normalize_item(raw, index)
            normalized.append(item)
            priced = item.get("row_type") not in {"heading", "text"}
            values = (
                index,
                service.ROW_TYPES.get(item.get("row_type"), item.get("row_type")),
                item.get("internal_code_snapshot") or item.get("product_code") or "",
                _display_name(item),
                _fmt(item.get("quantity"), 3) if priced else "",
                (item.get("unit") or "") if priced else "",
                _fmt(item.get("purchase_unit_price")) if priced else "",
                f"{_fmt(item.get('margin_pct'))} %" if priced else "",
                _fmt(item.get("recommended_unit_price")) if priced else "",
                f"{_fmt(item.get('discount_pct'))} %" if priced else "",
                _fmt(item.get("unit_price")) if priced else "",
                _fmt(item.get("total_price")) if priced else "",
            )
            iid = f"r{index - 1}"
            tags = ("status_active",) if item.get("row_type") == "heading" else ()
            self.tree.insert("", "end", iid=iid, values=values, tags=tags)
        self.items = normalized
        for index in selected_indices:
            iid = f"r{index}"
            if self.tree.exists(iid):
                self.tree.selection_add(iid)
        self.refresh_totals()

    def selected_indices(self):
        result = []
        for iid in self.tree.selection():
            text = str(iid)
            if text.startswith("r"):
                try:
                    result.append(int(text[1:]))
                except Exception:
                    pass
        return sorted(set(index for index in result if 0 <= index < len(self.items)))

    def refresh_totals(self):
        totals = service.calculate_totals(self.items, self.global_discount.get())
        currency = self.currency.get() or "CZK"
        lines = [
            f"Položky bez DPH: {_fmt(totals.items_subtotal)} {currency}",
        ]
        if totals.global_discount:
            lines.append(f"Celková sleva: -{_fmt(totals.global_discount)} {currency}")
        lines += [
            f"Celkem bez DPH: {_fmt(totals.subtotal_net)} {currency}",
            f"DPH: {_fmt(totals.vat_total)} {currency}",
            f"Celkem s DPH: {_fmt(totals.total_gross)} {currency}",
        ]
        self.totals_text.set("\n".join(lines))

    def add_from_catalog(self):
        if self.locked:
            return
        picker = ProductPicker(self.M, self.win)
        for product in picker.result:
            self.items.append(product)
        if picker.result:
            self.refresh_items()

    def add_manual(self):
        if self.locked:
            return
        dialog = ItemDialog(self.M, self.win, {"row_type": "product", "quantity": 1, "unit": "ks", "vat_rate": 21})
        if dialog.result:
            self.items.append(dialog.result)
            self.refresh_items()

    def add_special(self, row_type):
        if self.locked:
            return
        dialog = ItemDialog(self.M, self.win, {"row_type": row_type, "quantity": 0, "unit": "", "vat_rate": 0})
        if dialog.result:
            self.items.append(dialog.result)
            self.refresh_items()

    def edit_item(self):
        if self.locked:
            return
        indices = self.selected_indices()
        if len(indices) != 1:
            return self.M.messagebox.showinfo("Vydané nabídky", "Vyberte právě jednu položku.", parent=self.win)
        index = indices[0]
        dialog = ItemDialog(self.M, self.win, self.items[index], service.number(self.items[index].get("vat_rate"), 21))
        if dialog.result:
            self.items[index] = dialog.result
            self.refresh_items()
            self.tree.selection_set(f"r{index}")

    def remove_items(self):
        if self.locked:
            return
        indices = self.selected_indices()
        if not indices:
            return
        if not self.M.messagebox.askyesno("Vydané nabídky", f"Odebrat {len(indices)} vybraných řádků?", parent=self.win):
            return
        self.items = [item for index, item in enumerate(self.items) if index not in set(indices)]
        self.refresh_items()

    def move_item(self, delta):
        if self.locked:
            return
        indices = self.selected_indices()
        if len(indices) != 1:
            return
        index = indices[0]
        target = index + int(delta)
        if not (0 <= target < len(self.items)):
            return
        self.items[index], self.items[target] = self.items[target], self.items[index]
        self.refresh_items()
        self.tree.selection_set(f"r{target}")
        self.tree.see(f"r{target}")

    def collect(self):
        company_id = self.company_map.get(self.company.get().strip())
        contact_id = self.contact_map.get(self.contact.get().strip())
        project_id = self.project_map.get(self.project.get().strip())
        action_info = self.action_map.get(self.action.get().strip())
        action_id = action_info[0] if action_info else None
        if action_info and not project_id and action_info[1]:
            project_id = action_info[1]
        values = dict(self.document)
        values.update(
            issue_date=self.issue_date.get(), valid_to=self.valid_to.get(), status=self.status.get(),
            currency=self.currency.get(), offer_subject=self.subject.get().strip(),
            customer_reference=self.reference.get().strip(), salesperson_snapshot=self.salesperson.get().strip(),
            global_discount_pct=_parse(self.global_discount.get()), company_id=company_id,
            customer_contact_id=contact_id, project_id=project_id, action_id=action_id,
            template_id=self.template_map.get(self.template.get().strip()),
            payment_terms=self.payment_terms.get("1.0", "end-1c").strip(),
            delivery_terms=self.delivery_terms.get("1.0", "end-1c").strip(),
            delivery_time=self.delivery_time.get("1.0", "end-1c").strip(),
            customer_note=self.customer_note.get("1.0", "end-1c").strip(),
            internal_note=self.internal_note.get("1.0", "end-1c").strip(),
        )
        values.update(service.company_snapshot(self.M, company_id))
        values.update(service.contact_snapshot(self.M, contact_id))
        if not company_id:
            values["customer_name_snapshot"] = self.company.get().strip()
            values["customer_contact_snapshot"] = self.contact.get().strip()
        return values

    def save(self, quiet=False):
        if self.locked:
            return self.document_id
        values = self.collect()
        if not values.get("customer_name_snapshot"):
            self.M.messagebox.showwarning("Vydané nabídky", "Vyberte nebo vyplňte odběratele.", parent=self.win)
            return None
        if not self.items:
            self.M.messagebox.showwarning("Vydané nabídky", "Nabídka zatím neobsahuje žádné položky.", parent=self.win)
            return None
        try:
            self.document_id = service.save_document(self.M, values, self.items, self.document_id)
            self.document, self.items = service.load_document(self.M, self.document_id)
            try:
                self.app.refresh_issued_offers()
            except Exception:
                pass
            if not quiet:
                self.M.messagebox.showinfo("Vydané nabídky", f"Nabídka {self.document['document_number']} byla uložena.", parent=self.win)
            return self.document_id
        except Exception as exc:
            self.M.messagebox.showerror("Vydané nabídky", str(exc), parent=self.win)
            return None

    def generate_pdf(self, open_after=True):
        document_id = self.save(quiet=True)
        if not document_id:
            return
        try:
            path = self.M.render_issued_offer_pdf(document_id, open_after=open_after)
            self.document, self.items = service.load_document(self.M, document_id)
            try:
                self.app.refresh_issued_offers()
            except Exception:
                pass
            if not open_after:
                self.M.messagebox.showinfo("Vydané nabídky", f"PDF bylo vytvořeno:\n{path}", parent=self.win)
        except Exception as exc:
            self.M.messagebox.showerror("Vydané nabídky", f"PDF se nepodařilo vytvořit:\n\n{exc}", parent=self.win)

    def outlook_draft(self):
        document_id = self.save(quiet=True)
        if not document_id:
            return
        self.M.create_issued_offer_outlook_draft(self.app, document_id)

    def close(self):
        if self.locked:
            self.win.destroy()
            return
        if self.M.messagebox.askyesno("Vydané nabídky", "Uložit změny před zavřením?", parent=self.win):
            if self.save(quiet=True):
                self.win.destroy()
        elif self.M.messagebox.askyesno("Vydané nabídky", "Zavřít bez uložení?", parent=self.win):
            self.win.destroy()


def open_editor(M, app, document_id=None):
    return IssuedOfferEditor(M, app, document_id)


def install(M) -> None:
    M.IssuedOfferEditor = IssuedOfferEditor
    M.open_issued_offer_editor = lambda app, document_id=None: open_editor(M, app, document_id)
    M.App.open_issued_offer_editor = lambda self, document_id=None: open_editor(M, self, document_id)


__all__ = ["IssuedOfferEditor", "ItemDialog", "ProductPicker", "open_editor", "install"]
