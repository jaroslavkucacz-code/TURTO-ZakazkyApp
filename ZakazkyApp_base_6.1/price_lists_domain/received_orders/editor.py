"""Explicit Save/Cancel editors for received orders and their agreed prices."""
from __future__ import annotations

from . import service
from ..issued_offers import service as offers
from ..platform import company_roles


class OrderItemEditor:
    def __init__(self, M, parent, item=None):
        self.M, self.result = M, None
        self.original = dict(item or {"row_type": "product", "quantity": 1, "unit": "ks", "unit_price": 0, "vat_rate": 21})
        self.win = M.tk.Toplevel(parent)
        self.win.title("Položka přijaté objednávky")
        self.win.transient(parent)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 720, 520)
        frame = M.ttk.Frame(self.win, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        self.vars = {}
        fields = (("Název", "name"), ("Kód výrobce", "product_code"), ("Interní označení", "internal_name_snapshot"),
                  ("Množství", "quantity"), ("MJ", "unit"), ("Cena / MJ po slevě", "unit_price"), ("DPH %", "vat_rate"), ("Poznámka", "line_note"))
        for index, (label, key) in enumerate(fields):
            value = M.tk.StringVar(value=str(self.original.get(key) or (0 if key in {"quantity", "unit_price", "vat_rate"} else "")))
            self.vars[key] = value
            M.ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", padx=(0, 12), pady=6)
            M.ttk.Entry(frame, textvariable=value).grid(row=index, column=1, sticky="ew", pady=6)
        footer = M.ttk.Frame(frame)
        footer.grid(row=len(fields), column=0, columnspan=2, sticky="e", pady=12)
        M.ttk.Button(footer, text="Zrušit", command=self.win.destroy).pack(side="right", padx=4)
        M.ttk.Button(footer, text="Uložit", style="Accent.TButton", command=self.save).pack(side="right", padx=4)
        M.bind_dialog_keys(self.win, self.save)

    def save(self):
        try:
            values = dict(self.original)
            values.update({key: var.get() for key, var in self.vars.items()})
            if service.numeric(values["unit_price"]) != service.numeric(self.original.get("unit_price", 0)):
                values.update(discount_pct=0, recommended_unit_price=values["unit_price"])
            self.result = service.normalize_item(values)
        except ValueError as exc:
            return self.M.messagebox.showwarning("Položka objednávky", str(exc), parent=self.win)
        self.win.destroy()


class ReceivedOrderEditor:
    def __init__(self, M, app, document_id=None, source_offer_id=None):
        self.M, self.app, self.document_id = M, app, document_id
        if document_id:
            self.document, self.items = service.load_document(M, document_id)
        elif source_offer_id:
            self.document, self.items = service.draft_from_offer(M, source_offer_id)
        else:
            self.document, self.items = service.defaults(M), []
        self.win = M.tk.Toplevel(app)
        self.win.title("Přijatá objednávka")
        self.win.transient(app)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 1180, 780)
        frame = M.ttk.Frame(self.win, padding=14)
        frame.pack(fill="both", expand=True)
        header = M.ttk.Frame(frame)
        header.pack(fill="x")
        for column in (1, 3):
            header.columnconfigure(column, weight=1)
        self.title = M.tk.StringVar(value=self.document.get("document_number") or "Nová přijatá objednávka")
        M.ttk.Label(header, textvariable=self.title, font=("Calibri", 16, "bold")).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        self.vars = {key: M.tk.StringVar(value=self.document.get(key) or "") for key in
                     ("issue_date", "due_date", "status", "currency", "offer_subject", "customer_reference", "global_discount_pct", "delivery_address")}
        self.vars["global_discount_pct"].set(self.document.get("global_discount_pct") or 0)
        self.company = M.tk.StringVar(value=self.document.get("customer_name_snapshot") or "")
        M.ttk.Label(header, text="Odběratel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.company_box = M.AutocompleteEntry(header, textvariable=self.company, values=[])
        self.company_box.grid(row=1, column=1, columnspan=3, sticky="ew", pady=4)
        self.refresh_companies()
        self.company_box.bind("<FocusIn>", self.refresh_companies, add="+")
        fields = (("Datum přijetí", "issue_date"), ("Termín dodání", "due_date"), ("Stav", "status"),
                  ("Měna", "currency"), ("Číslo objednávky odběratele", "customer_reference"), ("Celková sleva %", "global_discount_pct"),
                  ("Předmět", "offer_subject"), ("Dodací adresa", "delivery_address"))
        for index, (label, key) in enumerate(fields):
            row, column = 2 + index // 2, (index % 2) * 2
            M.ttk.Label(header, text=label).grid(row=row, column=column, sticky="w", padx=(10 if column else 0, 8), pady=4)
            if key == "status":
                widget = M.ttk.Combobox(header, textvariable=self.vars[key], values=service.STATUSES, state="readonly")
            else:
                widget = M.ttk.Entry(header, textvariable=self.vars[key])
            widget.grid(row=row, column=column + 1, sticky="ew", pady=4)
        source = M.ttk.Frame(frame)
        source.pack(fill="x", pady=(6, 4))
        self.source_text = M.tk.StringVar(value="Z nabídky: " + (self.document.get("source_offer_number") or "—"))
        M.ttk.Label(source, textvariable=self.source_text).pack(side="left")
        if self.document.get("source_offer_id"):
            M.ttk.Button(source, text="Otevřít výchozí nabídku", command=self.open_source).pack(side="left", padx=12)
        toolbar = M.ttk.Frame(frame)
        toolbar.pack(fill="x", pady=6)
        for label, command in (("+ Položka", self.add_item), ("Upravit položku", self.edit_item), ("Odebrat položku", self.remove_item)):
            M.ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(0, 6))
        table = M.ttk.Frame(frame)
        table.pack(fill="both", expand=True)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        columns = ("Poz.", "Kód", "Název", "Interní označení", "Množství", "MJ", "Cena / MJ", "DPH %", "Celkem bez DPH")
        self.tree = M.ttk.Treeview(table, columns=columns, show="headings", selectmode="extended", name="layout__received_orders_editor__receivedordereditor__items")
        for key, width in zip(columns, (45, 110, 260, 200, 85, 55, 110, 65, 130)):
            self.tree.heading(key, text=key)
            self.tree.column(key, width=width, minwidth=45, stretch=key == "Název", anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        for orientation, side in (("vertical", "y"), ("horizontal", "x")):
            bar = M.ttk.Scrollbar(table, orient=orientation, command=getattr(self.tree, side + "view"))
            bar.grid(row=0 if side == "y" else 1, column=1 if side == "y" else 0, sticky="ns" if side == "y" else "ew")
            self.tree.configure(**{side + "scrollcommand": bar.set})
        M.bind_row_double_click(self.tree, lambda event: self.edit_item())
        self.total = M.tk.StringVar()
        M.ttk.Label(frame, textvariable=self.total, font=("Calibri", 12, "bold")).pack(anchor="e", pady=8)
        notes = M.ttk.Frame(frame)
        notes.pack(fill="x")
        self.notes = {}
        for column, (label, key) in enumerate((("Poznámka k objednávce", "customer_note"), ("Interní poznámka", "internal_note"))):
            notes.columnconfigure(column, weight=1)
            M.ttk.Label(notes, text=label).grid(row=0, column=column, sticky="w")
            text = M.tk.Text(notes, height=3, wrap="word", font=("Calibri", 11))
            text.grid(row=1, column=column, sticky="ew", padx=(0, 8) if column == 0 else 0)
            text.insert("1.0", self.document.get(key) or "")
            self.notes[key] = text
        footer = M.ttk.Frame(frame)
        footer.pack(fill="x", pady=(12, 0))
        M.ttk.Button(footer, text="Zrušit", command=self.win.destroy).pack(side="right", padx=4)
        M.ttk.Button(footer, text="Uložit objednávku", style="Accent.TButton", command=lambda: self.save(close=True)).pack(side="right", padx=4)
        self.vars["global_discount_pct"].trace_add("write", lambda *_: self.refresh_total())
        self.vars["currency"].trace_add("write", lambda *_: self.refresh_total())
        M.bind_dialog_keys(self.win, lambda: self.save(close=True))
        self.refresh_items()

    def refresh_companies(self, event=None):
        with self.M.db() as con:
            rows = company_roles.choices(con, "customer")
        self.company_box.set_values([(row["official_name"], row["id"]) for row in rows])

    def open_source(self):
        try:
            self.app.open_issued_offer_editor(int(self.document["source_offer_id"]))
        except Exception as exc:
            self.M.messagebox.showwarning("Výchozí nabídka", str(exc), parent=self.win)

    def collect(self):
        values = dict(self.document)
        values.update({key: value.get() for key, value in self.vars.items()})
        values.update({key: value.get("1.0", "end-1c").strip() for key, value in self.notes.items()})
        with self.M.db() as con:
            values["company_id"] = company_roles.resolve(con, self.company.get(), "customer",
                getattr(self.company_box, "selected_payload", None), self.document.get("company_id") if self.document_id else None)
        return values

    def save(self, close=False):
        try:
            self.document_id = service.save_document(self.M, self.collect(), self.items, self.document_id)
            self.document, self.items = service.load_document(self.M, self.document_id)
        except Exception as exc:
            self.M.messagebox.showwarning("Přijatá objednávka", str(exc), parent=self.win)
            return None
        self.title.set(self.document["document_number"])
        self.app.refresh_received_orders()
        if close:
            self.win.destroy()
        return self.document_id

    def selected_indices(self):
        return sorted(int(iid[1:]) for iid in self.tree.selection())

    def add_item(self):
        dialog = OrderItemEditor(self.M, self.win)
        self.win.wait_window(dialog.win)
        if dialog.result:
            self.items.append(dialog.result)
            self.refresh_items()

    def edit_item(self):
        selected = self.selected_indices()
        if len(selected) != 1:
            return self.M.messagebox.showinfo("Položka", "Vyberte právě jednu položku.", parent=self.win)
        dialog = OrderItemEditor(self.M, self.win, self.items[selected[0]])
        self.win.wait_window(dialog.win)
        if dialog.result:
            self.items[selected[0]] = dialog.result
            self.refresh_items()

    def remove_item(self):
        for index in reversed(self.selected_indices()):
            del self.items[index]
        self.refresh_items()

    def refresh_items(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, row in enumerate(self.items):
            self.tree.insert("", "end", iid=f"r{i}", values=(i + 1, row.get("product_code"), row.get("name"), row.get("internal_name_snapshot"),
                row.get("quantity"), row.get("unit"), f"{row.get('unit_price', 0):,.2f}", row.get("vat_rate"), f"{row.get('total_price', 0):,.2f}"))
        self.refresh_total()

    def refresh_total(self):
        try:
            total = service.totals(self.items, self.vars["global_discount_pct"].get())
            self.total.set(f"Bez DPH: {total['subtotal_net']:,.2f}   |   S DPH: {total['total_gross']:,.2f} {self.vars['currency'].get()}".replace(",", " "))
        except ValueError as exc:
            self.total.set(str(exc))
