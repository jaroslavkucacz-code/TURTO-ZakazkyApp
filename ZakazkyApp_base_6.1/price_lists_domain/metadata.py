"""Ceník metadata and import-preview dialog."""
from __future__ import annotations
from datetime import date
from pathlib import Path
from . import context as ctx
from .common import UPDATE_MODES,_iso_date,_number
from .storage import _format_price

def _metadata_dialog(parent, parsed: dict, path: Path, source_offer_id=None):
    dialog = ctx.M.tk.Toplevel(parent)
    dialog.title("Import Ceníku")
    dialog.transient(parent)
    dialog.grab_set()
    ctx.M.enable_dialog_maximize(dialog, 1150, 760)
    result = {"value": None}
    outer = ctx.M.scrollable_dialog_frame(dialog, 16)
    with ctx.M.db() as con:
        companies = con.execute(
            """SELECT MIN(id) id,official_name FROM companies WHERE active=1
               AND trim(coalesce(official_name,''))<>'' GROUP BY lower(trim(official_name))
               ORDER BY official_name COLLATE CZECH"""
        ).fetchall()
        prior = con.execute(
            """SELECT p.id,p.title,p.valid_from,p.supplier_name,c.official_name supplier
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE p.archived=0 ORDER BY p.valid_from DESC,p.id DESC LIMIT 500"""
        ).fetchall()
    supplier = ctx.M.tk.StringVar(value=str(parsed.get("supplier") or ""))
    title = ctx.M.tk.StringVar(value=str(parsed.get("title") or path.stem))
    valid_from = ctx.M.tk.StringVar(value=str(parsed.get("valid_from") or ""))
    valid_to = ctx.M.tk.StringVar(value=str(parsed.get("valid_to") or ""))
    product_group = ctx.M.tk.StringVar(value=str(parsed.get("product_group") or ""))
    branch = ctx.M.tk.StringVar(value=str(parsed.get("branch") or ""))
    suggested_mode=str(parsed.get("suggested_update_mode") or "partial")
    update_mode = ctx.M.tk.StringVar(value=UPDATE_MODES.get(suggested_mode, UPDATE_MODES["partial"]))
    previous = ctx.M.tk.StringVar(value="")
    currency = ctx.M.tk.StringVar(value=str(parsed.get("currency") or "CZK"))

    ctx.M.ttk.Label(outer, text="Zdrojový soubor").grid(row=0, column=0, sticky="w", pady=5)
    ctx.M.ttk.Label(outer, text=path.name, style="PageSubtitle.TLabel").grid(row=0, column=1, columnspan=2, sticky="w", pady=5)
    fields = [
        ("Dodavatel", supplier), ("Název ceníku", title), ("Produktová skupina", product_group),
        ("Dodavatelská větev / podmínka", branch), ("Měna", currency),
    ]
    widgets = []
    for offset, (label, variable) in enumerate(fields, 1):
        ctx.M.ttk.Label(outer, text=label).grid(row=offset, column=0, sticky="w", padx=(0, 10), pady=5)
        if label == "Dodavatel":
            widget = ctx.M.AutocompleteEntry(outer, textvariable=variable, values=[r["official_name"] for r in companies])
        else:
            widget = ctx.M.ttk.Entry(outer, textvariable=variable)
        widget.grid(row=offset, column=1, columnspan=2, sticky="ew", pady=5)
        widgets.append(widget)
    row = 6
    ctx.M.ttk.Label(outer, text="Platí od").grid(row=row, column=0, sticky="w", pady=5)
    ctx.M.DatePicker(outer, valid_from).grid(row=row, column=1, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Platí do").grid(row=row + 1, column=0, sticky="w", pady=5)
    ctx.M.DatePicker(outer, valid_to).grid(row=row + 1, column=1, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Způsob aktualizace").grid(row=row + 2, column=0, sticky="w", pady=5)
    mode_box = ctx.M.safe_combobox(outer, textvariable=update_mode, values=list(UPDATE_MODES.values()), state="readonly")
    mode_box.grid(row=row + 2, column=1, columnspan=2, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Aktualizuje předchozí ceník").grid(row=row + 3, column=0, sticky="w", pady=5)
    prior_values = [(f"{r['supplier'] or r['supplier_name']} · {r['title']} · {ctx.M.fmt_date(r['valid_from'])}", r["id"]) for r in prior]
    previous_box = ctx.M.AutocompleteEntry(outer, textvariable=previous, values=prior_values)
    previous_box.grid(row=row + 3, column=1, columnspan=2, sticky="ew", pady=5)
    note = ctx.M.tk.Text(outer, height=3, wrap="word")
    ctx.M.ttk.Label(outer, text="Poznámka").grid(row=row + 4, column=0, sticky="nw", pady=5)
    note.grid(row=row + 4, column=1, columnspan=2, sticky="ew", pady=5)

    preview_frame = ctx.M.ttk.LabelFrame(
        outer, text=f"Náhled rozpoznaných položek ({len(parsed.get('items') or [])})", padding=8
    )
    preview_frame.grid(row=row + 5, column=0, columnspan=3, sticky="nsew", pady=(10, 5))
    preview_frame.columnconfigure(0, weight=1)
    preview_frame.rowconfigure(0, weight=1)
    tree = ctx.M.ttk.Treeview(preview_frame, columns=("Ř.", "Kód", "Produkt", "Cena/MJ", "MJ", "Hmotnost", "Podmínka"), show="headings", height=12)
    for col, width in (("Ř.", 55), ("Kód", 125), ("Produkt", 370), ("Cena/MJ", 115), ("MJ", 65), ("Hmotnost", 100), ("Podmínka", 220)):
        tree.heading(col, text=col); tree.column(col, width=width, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    scroll = ctx.M.ttk.Scrollbar(preview_frame, orient="vertical", command=tree.yview)
    scroll.grid(row=0, column=1, sticky="ns"); tree.configure(yscrollcommand=scroll.set)
    for index, item in enumerate((parsed.get("items") or [])[:250], 1):
        tree.insert("", "end", values=(item.get("row_no") or index, item.get("product_code") or "",
                    item.get("name") or item.get("description") or "", _format_price(item.get("normalized_unit_price"), currency.get()),
                    item.get("unit") or "", f"{_number(item.get('weight_unit')):g} kg" if _number(item.get("weight_unit")) else "",
                    item.get("condition_text") or ""))
    status_text = str(parsed.get("parse_status") or "")
    ctx.M.ttk.Label(outer, text=f"Stav rozpoznání: {status_text}", style="PageSubtitle.TLabel").grid(row=row + 6, column=0, columnspan=3, sticky="w", pady=(3, 8))
    buttons = ctx.M.ttk.Frame(outer)
    buttons.grid(row=row + 7, column=0, columnspan=3, sticky="e", pady=8)

    def save():
        if not supplier.get().strip():
            return ctx.M.messagebox.showwarning("Ceníky", "Vyberte dodavatele.", parent=dialog)
        if not title.get().strip():
            return ctx.M.messagebox.showwarning("Ceníky", "Zadejte název ceníku.", parent=dialog)
        if not _iso_date(valid_from.get()):
            return ctx.M.messagebox.showwarning("Ceníky", "Vyplňte datum, od kterého ceník platí.", parent=dialog)
        selected_prior = getattr(previous_box, "selected_payload", None)
        if not selected_prior and previous.get().strip():
            selected_prior = next((payload for label, payload in prior_values if label.casefold() == previous.get().strip().casefold()), None)
        if selected_prior:
            prior_row = next((row for row in prior if int(row["id"]) == int(selected_prior)), None)
            prior_supplier = str((prior_row["supplier"] or prior_row["supplier_name"] or "") if prior_row else "").strip()
            norm = getattr(ctx.M, "norm_name", lambda value: str(value or "").strip().casefold())
            if prior_supplier and norm(prior_supplier) != norm(supplier.get().strip()):
                return ctx.M.messagebox.showwarning(
                    "Ceníky",
                    "Předchozí ceník patří jinému dodavateli. Vyberte ceník stejného dodavatele, nebo ponechte vazbu prázdnou.",
                    parent=dialog,
                )
        result["value"] = {
            "supplier": supplier.get().strip(), "title": title.get().strip(),
            "valid_from": _iso_date(valid_from.get()), "valid_to": _iso_date(valid_to.get()),
            "product_group": product_group.get().strip(), "branch": branch.get().strip(),
            "currency": currency.get().strip() or "CZK",
            "update_mode": next((key for key,label in UPDATE_MODES.items() if label==update_mode.get()), "partial"),
            "supersedes_id": selected_prior, "note": note.get("1.0", "end").strip(),
            "source_offer_id": source_offer_id,
        }
        dialog.destroy()

    ctx.M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right", padx=4)
    ctx.M.ttk.Button(buttons, text="Archivovat a importovat", style="Accent.TButton", command=save).pack(side="right")
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(row + 5, weight=1)
    dialog.wait_window()
    return result["value"]
