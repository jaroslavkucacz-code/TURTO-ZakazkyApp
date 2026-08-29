"""Scalable Ceník metadata and detail dialogs."""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path

from . import categories


def _selected_price_list_ids(app):
    tree = getattr(app, "price_list_evidence_tree", None)
    selection = tree.selection() if tree is not None else ()
    result = []
    for iid in selection:
        text = str(iid)
        if text.startswith("pl"):
            try:result.append(int(text[2:]))
            except Exception:pass
    return result


def metadata_dialog(M, parent, parsed: dict, path: Path, source_offer_id=None):
    from ..common import UPDATE_MODES, _iso_date, _number
    from ..storage import _format_price

    dialog = M.tk.Toplevel(parent)
    dialog.title("Import Ceníku")
    dialog.transient(parent)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 1180, 780)
    result = {"value": None}
    outer = M.scrollable_dialog_frame(dialog, 16)
    with M.db() as con:
        companies = con.execute(
            """SELECT MIN(id) id,official_name FROM companies WHERE active=1
               AND trim(coalesce(official_name,''))<>'' GROUP BY lower(trim(official_name))
               ORDER BY official_name COLLATE CZECH"""
        ).fetchall()
        prior = con.execute(
            """SELECT p.id,p.title,p.valid_from,p.supplier_name,c.official_name supplier
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE p.archived=0 ORDER BY p.valid_from DESC,p.id DESC LIMIT 1000"""
        ).fetchall()
    category_rows = categories.list_categories(M)

    supplier = M.tk.StringVar(value=str(parsed.get("supplier") or ""))
    title = M.tk.StringVar(value=str(parsed.get("title") or path.stem))
    valid_from = M.tk.StringVar(value=str(parsed.get("valid_from") or ""))
    valid_to = M.tk.StringVar(value=str(parsed.get("valid_to") or ""))
    product_group = M.tk.StringVar(value=str(parsed.get("product_group") or ""))
    branch = M.tk.StringVar(value=str(parsed.get("branch") or ""))
    currency = M.tk.StringVar(value=str(parsed.get("currency") or "CZK"))
    suggested_mode = str(parsed.get("suggested_update_mode") or "partial")
    update_mode = M.tk.StringVar(value=UPDATE_MODES.get(suggested_mode, UPDATE_MODES["partial"]))
    previous = M.tk.StringVar(value="")
    category_value = M.tk.StringVar(value="Automaticky podle položek")

    M.ttk.Label(outer, text="Zdrojový soubor").grid(row=0, column=0, sticky="w", pady=5)
    M.ttk.Label(outer, text=path.name, style="PageSubtitle.TLabel").grid(row=0, column=1, columnspan=2, sticky="w", pady=5)
    fields = (
        ("Dodavatel", supplier), ("Název ceníku", title),
        ("Produktová skupina", product_group), ("Dodavatelská větev / podmínka", branch),
        ("Měna", currency),
    )
    for offset, (label, variable) in enumerate(fields, 1):
        M.ttk.Label(outer, text=label).grid(row=offset, column=0, sticky="w", padx=(0, 10), pady=5)
        if label == "Dodavatel":
            widget = M.AutocompleteEntry(outer, textvariable=variable, values=[row["official_name"] for row in companies])
        else:
            widget = M.ttk.Entry(outer, textvariable=variable)
        widget.grid(row=offset, column=1, columnspan=2, sticky="ew", pady=5)

    category_labels = ["Automaticky podle položek", "Nezařazeno"] + [row["name"] for row in category_rows]
    M.ttk.Label(outer, text="Výchozí kategorie").grid(row=6, column=0, sticky="w", pady=5)
    M.safe_combobox(outer, textvariable=category_value, values=category_labels, state="readonly").grid(
        row=6, column=1, columnspan=2, sticky="ew", pady=5
    )
    M.ttk.Label(
        outer,
        text="Automatika může v jednom ceníku rozdělit jednotlivé položky do různých kategorií.",
        style="PageSubtitle.TLabel",
    ).grid(row=7, column=1, columnspan=2, sticky="w", pady=(0, 4))

    M.ttk.Label(outer, text="Platí od").grid(row=8, column=0, sticky="w", pady=5)
    M.DatePicker(outer, valid_from).grid(row=8, column=1, sticky="ew", pady=5)
    M.ttk.Label(outer, text="Platí do").grid(row=9, column=0, sticky="w", pady=5)
    M.DatePicker(outer, valid_to).grid(row=9, column=1, sticky="ew", pady=5)
    M.ttk.Label(outer, text="Způsob aktualizace").grid(row=10, column=0, sticky="w", pady=5)
    M.safe_combobox(outer, textvariable=update_mode, values=list(UPDATE_MODES.values()), state="readonly").grid(
        row=10, column=1, columnspan=2, sticky="ew", pady=5
    )
    M.ttk.Label(outer, text="Aktualizuje předchozí ceník").grid(row=11, column=0, sticky="w", pady=5)
    prior_values = [
        (f"{row['supplier'] or row['supplier_name']} · {row['title']} · {M.fmt_date(row['valid_from'])}", row["id"])
        for row in prior
    ]
    previous_box = M.AutocompleteEntry(outer, textvariable=previous, values=prior_values)
    previous_box.grid(row=11, column=1, columnspan=2, sticky="ew", pady=5)
    note = M.tk.Text(outer, height=3, wrap="word")
    M.ttk.Label(outer, text="Poznámka").grid(row=12, column=0, sticky="nw", pady=5)
    note.grid(row=12, column=1, columnspan=2, sticky="ew", pady=5)

    preview = M.ttk.LabelFrame(
        outer, text=f"Náhled rozpoznaných položek ({len(parsed.get('items') or [])})", padding=8
    )
    preview.grid(row=13, column=0, columnspan=3, sticky="nsew", pady=(10, 5))
    preview.columnconfigure(0, weight=1)
    preview.rowconfigure(0, weight=1)
    cols = ("Ř.", "Kategorie", "Kód", "Produkt", "Cena/MJ", "MJ", "Hmotnost", "Podmínka")
    widths = (55, 210, 125, 350, 115, 65, 100, 220)
    tree = M.ttk.Treeview(preview, columns=cols, show="headings", height=12)
    for col, width in zip(cols, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    scroll = M.ttk.Scrollbar(preview, orient="vertical", command=tree.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    category_name_by_id = {int(row["id"]): row["name"] for row in category_rows}
    for index, item in enumerate((parsed.get("items") or [])[:300], 1):
        guessed = categories.classify_text(
            M,
            " ".join(str(item.get(key) or "") for key in ("product_code", "item_key", "name", "description", "condition_text")),
        )
        tree.insert(
            "", "end",
            values=(
                item.get("row_no") or index, category_name_by_id.get(guessed, "Nezařazeno"),
                item.get("product_code") or "", item.get("name") or item.get("description") or "",
                _format_price(item.get("normalized_unit_price"), currency.get()), item.get("unit") or "",
                f"{_number(item.get('weight_unit')):g} kg" if _number(item.get("weight_unit")) else "",
                item.get("condition_text") or "",
            ),
        )
    M.ttk.Label(
        outer, text=f"Stav rozpoznání: {str(parsed.get('parse_status') or '')}", style="PageSubtitle.TLabel"
    ).grid(row=14, column=0, columnspan=3, sticky="w", pady=(3, 8))
    buttons = M.ttk.Frame(outer)
    buttons.grid(row=15, column=0, columnspan=3, sticky="e", pady=8)

    def save():
        if not supplier.get().strip():
            return M.messagebox.showwarning("Ceníky", "Vyberte dodavatele.", parent=dialog)
        if not title.get().strip():
            return M.messagebox.showwarning("Ceníky", "Zadejte název ceníku.", parent=dialog)
        if not _iso_date(valid_from.get()):
            return M.messagebox.showwarning("Ceníky", "Vyplňte datum, od kterého ceník platí.", parent=dialog)
        selected_prior = getattr(previous_box, "selected_payload", None)
        if not selected_prior and previous.get().strip():
            selected_prior = next(
                (payload for label, payload in prior_values if label.casefold() == previous.get().strip().casefold()), None
            )
        if selected_prior:
            prior_row = next((row for row in prior if int(row["id"]) == int(selected_prior)), None)
            prior_supplier = str((prior_row["supplier"] or prior_row["supplier_name"] or "") if prior_row else "").strip()
            norm = getattr(M, "norm_name", lambda value: str(value or "").strip().casefold())
            if prior_supplier and norm(prior_supplier) != norm(supplier.get().strip()):
                return M.messagebox.showwarning(
                    "Ceníky", "Předchozí ceník patří jinému dodavateli.", parent=dialog
                )
        selected_category = category_value.get()
        auto_category = selected_category == "Automaticky podle položek"
        category_id = None if selected_category in {"Automaticky podle položek", "Nezařazeno"} else categories.category_id_by_name(M, selected_category)
        result["value"] = {
            "supplier": supplier.get().strip(), "title": title.get().strip(),
            "valid_from": _iso_date(valid_from.get()), "valid_to": _iso_date(valid_to.get()),
            "product_group": product_group.get().strip(), "branch": branch.get().strip(),
            "currency": currency.get().strip() or "CZK",
            "update_mode": next((key for key, label in UPDATE_MODES.items() if label == update_mode.get()), "partial"),
            "supersedes_id": selected_prior, "note": note.get("1.0", "end").strip(),
            "source_offer_id": source_offer_id, "category_id": category_id,
            "auto_category": auto_category,
        }
        dialog.destroy()

    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right", padx=4)
    M.ttk.Button(buttons, text="Archivovat a importovat", style="Accent.TButton", command=save).pack(side="right")
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(13, weight=1)
    dialog.wait_window()
    return result["value"]


def edit_price_list_metadata(M, app) -> None:
    from ..common import UPDATE_MODES, _iso_date

    ids = _selected_price_list_ids(app)
    if len(ids) != 1:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden ceník.", parent=app)
    price_list_id = ids[0]
    with M.db() as con:
        row = con.execute(
            """SELECT p.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id WHERE p.id=?""",
            (price_list_id,),
        ).fetchone()
        prior = con.execute(
            """SELECT p.id,p.title,p.valid_from,p.supplier_name,c.official_name supplier
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE p.id<>? AND p.archived=0 ORDER BY p.valid_from DESC,p.id DESC LIMIT 1000""",
            (price_list_id,),
        ).fetchall()
    if not row:
        return
    dialog = M.tk.Toplevel(app)
    dialog.title("Upravit údaje Ceníku")
    dialog.transient(app)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 900, 650)
    outer = M.scrollable_dialog_frame(dialog, 14)
    variables = {
        "title": M.tk.StringVar(value=row["title"] or ""),
        "valid_from": M.tk.StringVar(value=row["valid_from"] or ""),
        "valid_to": M.tk.StringVar(value=row["valid_to"] or ""),
        "product_group": M.tk.StringVar(value=row["product_group"] or ""),
        "branch": M.tk.StringVar(value=row["branch"] or ""),
        "update_mode": M.tk.StringVar(value=UPDATE_MODES.get(row["update_mode"] or "partial", UPDATE_MODES["partial"])),
        "previous": M.tk.StringVar(value=""),
        "category": M.tk.StringVar(value=categories.category_name(M, row["category_id"]) or "Automaticky podle položek"),
    }
    labels = (("Název", "title"), ("Produktová skupina", "product_group"), ("Větev / podmínka", "branch"))
    for idx, (label, key) in enumerate(labels):
        M.ttk.Label(outer, text=label).grid(row=idx, column=0, sticky="w", pady=5)
        M.ttk.Entry(outer, textvariable=variables[key]).grid(row=idx, column=1, sticky="ew", pady=5)
    category_labels = ["Automaticky podle položek", "Nezařazeno"] + [cat["name"] for cat in categories.list_categories(M)]
    M.ttk.Label(outer, text="Výchozí kategorie").grid(row=3, column=0, sticky="w", pady=5)
    M.safe_combobox(outer, textvariable=variables["category"], values=category_labels, state="readonly").grid(
        row=3, column=1, sticky="ew", pady=5
    )
    M.ttk.Label(outer, text="Platí od").grid(row=4, column=0, sticky="w", pady=5)
    M.DatePicker(outer, variables["valid_from"]).grid(row=4, column=1, sticky="ew", pady=5)
    M.ttk.Label(outer, text="Platí do").grid(row=5, column=0, sticky="w", pady=5)
    M.DatePicker(outer, variables["valid_to"]).grid(row=5, column=1, sticky="ew", pady=5)
    M.ttk.Label(outer, text="Způsob aktualizace").grid(row=6, column=0, sticky="w", pady=5)
    M.safe_combobox(outer, textvariable=variables["update_mode"], values=list(UPDATE_MODES.values()), state="readonly").grid(
        row=6, column=1, sticky="ew", pady=5
    )
    prior_values = [
        (f"{item['supplier'] or item['supplier_name']} · {item['title']} · {M.fmt_date(item['valid_from'])}", item["id"])
        for item in prior
    ]
    current_label = next((label for label, pid in prior_values if pid == row["supersedes_id"]), "")
    variables["previous"].set(current_label)
    M.ttk.Label(outer, text="Aktualizuje předchozí ceník").grid(row=7, column=0, sticky="w", pady=5)
    previous_box = M.AutocompleteEntry(outer, textvariable=variables["previous"], values=prior_values)
    previous_box.grid(row=7, column=1, sticky="ew", pady=5)
    note = M.tk.Text(outer, height=4, wrap="word")
    note.insert("1.0", row["note"] or "")
    M.ttk.Label(outer, text="Poznámka").grid(row=8, column=0, sticky="nw", pady=5)
    note.grid(row=8, column=1, sticky="ew", pady=5)

    def save():
        previous_id = getattr(previous_box, "selected_payload", None)
        if not previous_id and variables["previous"].get().strip():
            previous_id = next(
                (pid for label, pid in prior_values if label.casefold() == variables["previous"].get().strip().casefold()), None
            )
        valid_from = _iso_date(variables["valid_from"].get())
        if not valid_from:
            return M.messagebox.showwarning("Ceníky", "Vyplňte datum Platí od.", parent=dialog)
        mode = next((key for key, label in UPDATE_MODES.items() if label == variables["update_mode"].get()), "partial")
        category_label = variables["category"].get()
        category_id = None if category_label in {"Automaticky podle položek", "Nezařazeno"} else categories.category_id_by_name(M, category_label)
        with M.db() as con:
            con.execute(
                """UPDATE price_lists SET title=?,valid_from=?,valid_to=?,product_group=?,branch=?,
                          update_mode=?,supersedes_id=?,note=?,category_id=? WHERE id=?""",
                (
                    variables["title"].get().strip(), valid_from, _iso_date(variables["valid_to"].get()),
                    variables["product_group"].get().strip(), variables["branch"].get().strip(), mode,
                    previous_id, note.get("1.0", "end").strip(), category_id, price_list_id,
                ),
            )
            if category_label == "Nezařazeno":
                con.execute("UPDATE price_list_items SET category_id=NULL WHERE price_list_id=?", (price_list_id,))
            elif category_id:
                con.execute("UPDATE price_list_items SET category_id=? WHERE price_list_id=?", (category_id, price_list_id))
            if previous_id and mode in {"replace_group", "replace_all"}:
                previous_day = (datetime.strptime(valid_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
                con.execute(
                    "UPDATE price_lists SET valid_to=? WHERE id=? AND (valid_to='' OR valid_to>?)",
                    (previous_day, previous_id, previous_day),
                )
        if category_label == "Automaticky podle položek":
            categories.autocategorize_price_list(M, price_list_id, only_empty=False)
        dialog.destroy()
        app.refresh_price_lists()
        try:app.refresh_offers()
        except Exception:pass

    buttons = M.ttk.Frame(outer)
    buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=8)
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right", padx=4)
    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right")
    outer.columnconfigure(1, weight=1)


class PriceListDetailDialog:
    def __init__(self, M, app, price_list_id: int):
        self.M = M
        self.app = app
        self.price_list_id = int(price_list_id)
        self.page = 0
        self.page_size = 500
        self.rows = {}
        with M.db() as con:
            self.header = con.execute(
                """SELECT p.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier,
                          old.title previous_title
                   FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
                   LEFT JOIN price_lists old ON old.id=p.supersedes_id WHERE p.id=?""",
                (self.price_list_id,),
            ).fetchone()
        if not self.header:
            return
        self.win = M.tk.Toplevel(app)
        self.win.title("Detail Ceníku")
        self.win.transient(app)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 1400, 840)
        outer = M.ttk.Frame(self.win, padding=14)
        outer.pack(fill="both", expand=True)
        M.ttk.Label(
            outer, text=f"{self.header['supplier'] or 'Neurčený dodavatel'} · {self.header['title']}",
            font=("Calibri", 16, "bold"),
        ).pack(anchor="w")
        M.ttk.Label(
            outer,
            text=(
                f"Platnost: {M.fmt_date(self.header['valid_from']) or '—'} až "
                f"{M.fmt_date(self.header['valid_to']) or 'bez konce'} · "
                f"Skupina: {self.header['product_group'] or '—'} · Větev: {self.header['branch'] or '—'}"
            ),
            style="PageSubtitle.TLabel",
        ).pack(anchor="w", pady=(2, 8))
        filters = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
        filters.pack(fill="x", pady=(0, 6))
        self.query = M.tk.StringVar()
        self.category = M.tk.StringVar(value="Všechny")
        M.ttk.Label(filters, text="Hledat", style="FilterLabel.TLabel").grid(row=0, column=0, sticky="w")
        M.ttk.Label(filters, text="Kategorie", style="FilterLabel.TLabel").grid(row=0, column=1, sticky="w")
        M.ttk.Entry(filters, textvariable=self.query).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        self.category_box = M.safe_combobox(
            filters, textvariable=self.category,
            values=["Všechny"] + [row["name"] for row in categories.list_categories(M)], state="readonly",
        )
        self.category_box.grid(row=1, column=1, sticky="ew")
        filters.columnconfigure(0, weight=2)
        filters.columnconfigure(1, weight=1)
        self.query.trace_add("write", lambda *_: self.schedule_refresh())
        self.category.trace_add("write", lambda *_: self.schedule_refresh())

        tools = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
        tools.pack(fill="x", pady=(0, 6))
        M.ttk.Button(tools, text="Přiřadit kategorii vybraným", command=self.assign_category).pack(side="left")
        M.ttk.Button(tools, text="Automaticky zařadit nezařazené", command=self.auto_categories).pack(side="left", padx=5)
        user = M.get_setting("active_user", "")
        self.photos = M.tk.BooleanVar(value=M.get_user_setting(user, "load_product_photos", "0") == "1")
        M.ttk.Checkbutton(tools, text="Načítat fotografie", variable=self.photos, command=self.sync_photo).pack(side="left", padx=(15, 5))
        self.photo_button = M.ttk.Button(tools, text="Zobrazit foto vybrané položky", command=self.show_photo)
        self.photo_button.pack(side="left")
        self.sync_photo()

        table_wrap = M.ttk.Frame(outer)
        table_wrap.pack(fill="both", expand=True)
        table_wrap.columnconfigure(0, weight=1)
        table_wrap.rowconfigure(0, weight=1)
        cols = (
            "Ř.", "Kategorie", "Kód", "Produkt", "Zdrojová cena", "Cena/MJ", "Cena za", "MJ",
            "Přirážka", "Sleva", "Min. odběr", "Balení", "Paleta", "Hmotnost/MJ", "Podmínka",
        )
        widths = (55, 210, 120, 330, 110, 110, 70, 60, 80, 70, 90, 100, 80, 105, 240)
        self.tree = M.ttk.Treeview(table_wrap, columns=cols, show="headings", selectmode="extended")
        for col, width in zip(cols, widths):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width, anchor="w")
        ys = M.ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        xs = M.ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self.show_attributes, add="+")

        lower = M.ttk.Panedwindow(outer, orient="horizontal")
        lower.pack(fill="x", pady=(7, 0))
        self.attributes = M.tk.Text(lower, height=7, wrap="word")
        self.terms = M.tk.Text(lower, height=7, wrap="word")
        lower.add(self.attributes, weight=1)
        lower.add(self.terms, weight=1)
        self.terms.insert("1.0", str(self.header["terms_text"] or "") or "Bez dalších podmínek.")
        self.terms.configure(state="disabled")

        nav = M.ttk.Frame(outer)
        nav.pack(fill="x", pady=(8, 0))
        self.status = M.tk.StringVar()
        M.ttk.Label(nav, textvariable=self.status, style="PageSubtitle.TLabel").pack(side="left")
        self.prev = M.ttk.Button(nav, text="← Předchozí", command=self.previous_page)
        self.prev.pack(side="right", padx=3)
        self.next = M.ttk.Button(nav, text="Další →", command=self.next_page)
        self.next.pack(side="right", padx=3)
        M.ttk.Button(nav, text="Otevřít původní soubor", command=lambda: self.open_source(False)).pack(side="left", padx=(12, 3))
        M.ttk.Button(nav, text="Otevřít složku", command=lambda: self.open_source(True)).pack(side="left", padx=3)
        M.ttk.Button(nav, text="Zavřít", style="Accent.TButton", command=self.win.destroy).pack(side="right", padx=(12, 3))
        self.refresh()

    def sync_photo(self):
        user = self.M.get_setting("active_user", "")
        enabled = bool(self.photos.get())
        self.M.set_user_setting(user, "load_product_photos", "1" if enabled else "0")
        self.photo_button.state(["!disabled"] if enabled else ["disabled"])

    def schedule_refresh(self):
        previous = getattr(self, "_refresh_after", None)
        if previous:
            try:self.win.after_cancel(previous)
            except Exception:pass
        self.page = 0
        self._refresh_after = self.win.after(180, self.refresh)

    def refresh(self):
        self._refresh_after = None
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.rows = {}
        where = ["i.price_list_id=?", "i.active=1"]
        params = [self.price_list_id]
        query = self.query.get().strip().casefold()
        if query:
            where.append(
                "lower(coalesce(i.product_code,'')||' '||coalesce(i.item_key,'')||' '||coalesce(i.name,'')||' '||coalesce(i.description,'')||' '||coalesce(i.condition_text,'')) LIKE ?"
            )
            params.append("%" + query + "%")
        if self.category.get() != "Všechny":
            cid = categories.category_id_by_name(self.M, self.category.get())
            where.append("coalesce(i.category_id,p.category_id)=?")
            params.append(cid or -1)
        sql_where = " AND ".join(where)
        with self.M.db() as con:
            total = con.execute(
                f"SELECT COUNT(*) FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id WHERE {sql_where}",
                params,
            ).fetchone()[0]
            rows = con.execute(
                f"""SELECT i.id,i.row_no,i.product_code,i.item_key,i.name,i.description,i.unit,
                           i.source_price,i.currency,i.price_basis_qty,i.normalized_unit_price,
                           i.discount_pct,i.surcharge_pct,i.minimum_qty,i.package_qty,i.package_unit,
                           i.pallet_qty,i.weight_unit,i.condition_text,i.category_id,
                           coalesce(ic.name,lc.name,'Nezařazeno') category
                    FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                    LEFT JOIN product_categories ic ON ic.id=i.category_id
                    LEFT JOIN product_categories lc ON lc.id=p.category_id
                    WHERE {sql_where}
                    ORDER BY i.row_no,i.id LIMIT ? OFFSET ?""",
                params + [self.page_size, self.page * self.page_size],
            ).fetchall()
        from ..storage import _format_price
        for row in rows:
            iid = f"pli{row['id']}"
            self.rows[iid] = dict(row)
            self.tree.insert(
                "", "end", iid=iid,
                values=(
                    row["row_no"], row["category"], row["product_code"] or row["item_key"] or "",
                    row["name"] or row["description"] or "", _format_price(row["source_price"], row["currency"]),
                    _format_price(row["normalized_unit_price"], row["currency"]), f"{float(row['price_basis_qty'] or 1):g}",
                    row["unit"] or "", f"+{float(row['surcharge_pct'] or 0):g} %" if row["surcharge_pct"] else "",
                    f"-{float(row['discount_pct'] or 0):g} %" if row["discount_pct"] else "",
                    f"{float(row['minimum_qty'] or 0):g}" if row["minimum_qty"] else "",
                    f"{float(row['package_qty'] or 0):g} {row['package_unit'] or ''}".strip() if row["package_qty"] else "",
                    f"{float(row['pallet_qty'] or 0):g}" if row["pallet_qty"] else "",
                    f"{float(row['weight_unit'] or 0):g} kg" if row["weight_unit"] else "",
                    row["condition_text"] or "",
                ),
            )
        start = self.page * self.page_size + 1 if total else 0
        end = min(total, (self.page + 1) * self.page_size)
        self.status.set(f"Zobrazeno {start}–{end} z {total} položek")
        self.prev.state(["!disabled"] if self.page > 0 else ["disabled"])
        self.next.state(["!disabled"] if end < total else ["disabled"])

    def previous_page(self):
        if self.page > 0:
            self.page -= 1
            self.refresh()

    def next_page(self):
        self.page += 1
        self.refresh()

    def selected_item_ids(self):
        return [int(str(iid)[3:]) for iid in self.tree.selection() if str(iid).startswith("pli")]

    def assign_category(self):
        ids = self.selected_item_ids()
        if not ids:
            return self.M.messagebox.showinfo("Ceníky", "Vyberte jednu nebo více položek.", parent=self.win)
        selected = categories.choose_category(self.M, self.win, "Přiřadit kategorii položkám")
        if selected == "cancel":
            return
        with self.M.db() as con:
            con.executemany("UPDATE price_list_items SET category_id=? WHERE id=?", [(selected, item_id) for item_id in ids])
        self.refresh()
        self.app.refresh_price_lists()

    def auto_categories(self):
        changed, unassigned = categories.autocategorize_price_list(self.M, self.price_list_id, only_empty=True)
        self.refresh()
        self.app.refresh_price_lists()
        self.M.messagebox.showinfo(
            "Kategorie", f"Automaticky zařazeno: {changed}\nNadále nezařazeno: {unassigned}", parent=self.win
        )

    def show_attributes(self, _event=None):
        self.attributes.configure(state="normal")
        self.attributes.delete("1.0", "end")
        selected = self.selected_item_ids()
        if not selected:
            self.attributes.configure(state="disabled")
            return
        item_id = selected[0]
        with self.M.db() as con:
            row = con.execute(
                """SELECT gtin,customs_code,dimensions,description,source_row_json
                   FROM price_list_items WHERE id=?""",
                (item_id,),
            ).fetchone()
            attrs = con.execute(
                "SELECT attribute_key,attribute_value,attribute_unit FROM price_list_item_attributes WHERE item_id=? ORDER BY id",
                (item_id,),
            ).fetchall()
        lines = []
        if row:
            for label, value in (("GTIN", row["gtin"]), ("Celní kód", row["customs_code"]),
                                 ("Rozměry", row["dimensions"]), ("Popis", row["description"]),
                                 ("Původní řádek", row["source_row_json"])):
                if str(value or "").strip():
                    lines.append(f"{label}: {value}")
        for attr in attrs:
            lines.append(f"{attr['attribute_key']}: {attr['attribute_value']} {attr['attribute_unit'] or ''}".strip())
        self.attributes.insert("1.0", "\n".join(lines) or "Bez dalších údajů.")
        self.attributes.configure(state="disabled")

    def show_photo(self):
        ids = self.selected_item_ids()
        if len(ids) != 1:
            return self.M.messagebox.showinfo("Fotografie", "Vyberte jednu položku.", parent=self.win)
        item = next((row for row in self.rows.values() if int(row["id"]) == ids[0]), None)
        if not item:
            return
        blob = None
        source = ""
        with self.M.db() as con:
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "offer_product_images" in tables and item.get("item_key"):
                image = con.execute(
                    """SELECT image_blob,source_offer_no,source_offer_date FROM offer_product_images
                       WHERE supplier=? AND item_key=? AND image_blob IS NOT NULL LIMIT 1""",
                    (self.header["supplier"] or self.header["supplier_name"] or "", item.get("item_key") or ""),
                ).fetchone()
                if image and image["image_blob"]:
                    blob = bytes(image["image_blob"])
                    source = f"nabídka {image['source_offer_no'] or '—'} z {self.M.fmt_date(image['source_offer_date'])}"
            if blob is None and self.header["source_offer_id"]:
                image = con.execute(
                    """SELECT image_blob FROM supplier_offer_items
                       WHERE offer_id=? AND image_blob IS NOT NULL AND (
                         (trim(coalesce(item_key,''))<>'' AND item_key=?) OR
                         (trim(coalesce(product_code,''))<>'' AND product_code=?) OR
                         original_name=?
                       ) ORDER BY id LIMIT 1""",
                    (
                        self.header["source_offer_id"], item.get("item_key") or "",
                        item.get("product_code") or "", item.get("name") or "",
                    ),
                ).fetchone()
                if image and image["image_blob"]:
                    blob = bytes(image["image_blob"])
                    source = "zdrojová nabídka"
        if blob is None:
            return self.M.messagebox.showinfo("Fotografie", "K této položce není uložen obrázek.", parent=self.win)
        try:
            from PIL import Image, ImageTk
            image = Image.open(io.BytesIO(blob))
            image.thumbnail((950, 650))
            win = self.M.tk.Toplevel(self.win)
            win.title(f"Fotografie – {item.get('name') or item.get('product_code') or ''}")
            win.transient(self.win)
            photo = ImageTk.PhotoImage(image)
            label = self.M.ttk.Label(win, image=photo)
            label.image = photo
            label.pack(padx=14, pady=14)
            self.M.ttk.Label(win, text=f"Zdroj: {source or 'uložený obrázek'}", style="PageSubtitle.TLabel").pack(pady=(0, 8))
            self.M.ttk.Button(win, text="Zavřít", command=win.destroy).pack(pady=(0, 14))
        except Exception as exc:
            self.M.messagebox.showerror("Fotografie", str(exc), parent=self.win)

    def open_source(self, folder: bool):
        from ..operations import _open_archived_path
        _open_archived_path(self.app, self.price_list_id, folder)


def open_price_list_detail(M, app, price_list_id=None):
    if price_list_id is None:
        ids = _selected_price_list_ids(app)
        price_list_id = ids[0] if len(ids) == 1 else None
    if not price_list_id:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden ceník.", parent=app)
    PriceListDetailDialog(M, app, int(price_list_id))
