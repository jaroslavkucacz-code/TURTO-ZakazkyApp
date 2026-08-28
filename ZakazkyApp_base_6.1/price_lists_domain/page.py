"""Dedicated Ceníky page and effective-price resolver."""
from __future__ import annotations
import os
from datetime import date
from . import context as ctx
from .archive import price_list_archive_root
from .common import UPDATE_MODES,_iso_date,_number
from .detail import open_price_list_detail
from .edit import edit_price_list_metadata
from .importer import import_price_list
from .operations import archive_price_list,delete_price_list_db,open_price_list_file,open_price_list_folder
from .storage import _format_price,_list_status

def build_price_lists(app):
    page = app.tabs["pricelists"]
    app.title_label(page, "Ceníky")
    top = ctx.M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8)); top.pack(fill="x", pady=(0, 6))
    ctx.M.ttk.Button(top, text="+ Importovat Ceník", style="Accent.TButton", command=lambda: import_price_list(app)).pack(side="left")
    def open_archive_root():
        root=price_list_archive_root();root.mkdir(parents=True,exist_ok=True)
        if os.name=="nt":os.startfile(str(root))
    ctx.M.ttk.Button(top, text="Otevřít archiv Ceníků", style="Toolbar.TButton",
                 command=open_archive_root).pack(side="left", padx=(6, 0))
    ctx.M.ttk.Label(top, text="Původní soubory se trvale uchovávají podle dodavatelů; DB-only mazání je neodstraní.",
                style="PageSubtitle.TLabel").pack(side="left", padx=(12, 0))
    notebook = ctx.M.ttk.Notebook(page); notebook.pack(fill="both", expand=True)
    current_tab = ctx.M.ttk.Frame(notebook, padding=8); evidence_tab = ctx.M.ttk.Frame(notebook, padding=8)
    notebook.add(current_tab, text="Aktuální ceny"); notebook.add(evidence_tab, text="Evidence ceníků")

    filters = ctx.M.ttk.Frame(current_tab, style="Panel.TFrame", padding=8); filters.pack(fill="x", pady=(0, 6))
    app.price_q = ctx.M.tk.StringVar(); app.price_supplier_filter = ctx.M.tk.StringVar(); app.price_group_filter = ctx.M.tk.StringVar()
    app.price_effective_date = ctx.M.tk.StringVar(value=date.today().isoformat())
    for col, label in enumerate(("Hledat produkt / kód", "Dodavatel", "Produktová skupina", "Cena platná k datu")):
        ctx.M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
        filters.columnconfigure(col, weight=2 if col == 0 else 1)
    ctx.M.ttk.Entry(filters, textvariable=app.price_q).grid(row=1, column=0, sticky="ew", padx=(0, 6))
    app.price_supplier_box = ctx.M.AutocompleteEntry(filters, textvariable=app.price_supplier_filter, values=[])
    app.price_supplier_box.grid(row=1, column=1, sticky="ew", padx=(0, 6))
    app.price_group_box = ctx.M.AutocompleteEntry(filters, textvariable=app.price_group_filter, values=[])
    app.price_group_box.grid(row=1, column=2, sticky="ew", padx=(0, 6))
    ctx.M.DatePicker(filters, app.price_effective_date).grid(row=1, column=3, sticky="ew")
    cols = ("Dodavatel", "Větev", "Kód", "Produkt", "Cena/MJ", "Zdrojová cena", "Cena za", "MJ",
            "Přirážka/Sleva", "Hmotnost/MJ", "Min. odběr", "Podmínka", "Platí od", "Zdrojový ceník")
    widths = [175, 170, 120, 330, 115, 115, 75, 65, 115, 105, 95, 220, 95, 230]
    app.price_current_tree = app.tree(current_tab, cols, widths)
    ctx.M.bind_row_double_click(app.price_current_tree, lambda _event: open_price_list_detail(
        app, (getattr(app, "price_current_rows", {}).get(app.price_current_tree.selection()[0], {}) or {}).get("price_list_id")
        if app.price_current_tree.selection() else None))

    evidence_tools = ctx.M.ttk.Frame(evidence_tab, style="Panel.TFrame", padding=8); evidence_tools.pack(fill="x", pady=(0, 6))
    app.price_list_show_archived = ctx.M.tk.BooleanVar(value=False)
    ctx.M.ttk.Checkbutton(evidence_tools, text="Zobrazit archivované", variable=app.price_list_show_archived,
                      command=app.refresh_price_lists).pack(side="left")
    ctx.M.ttk.Button(evidence_tools, text="Detail", style="Accent.TButton", command=lambda: open_price_list_detail(app)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Upravit údaje", command=lambda: edit_price_list_metadata(app)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Otevřít soubor", command=lambda: open_price_list_file(app)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Otevřít složku", command=lambda: open_price_list_folder(app)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Archivovat", command=lambda: archive_price_list(app, False)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Obnovit", command=lambda: archive_price_list(app, True)).pack(side="right", padx=3)
    ctx.M.ttk.Button(evidence_tools, text="Smazat z DB", command=lambda: delete_price_list_db(app)).pack(side="right", padx=3)
    evidence_cols = ("Stav", "Platí od", "Platí do", "Dodavatel", "Název", "Skupina", "Větev", "Režim", "Položek", "Soubor", "Import")
    evidence_widths = [120, 95, 95, 190, 270, 150, 180, 150, 75, 250, 145]
    app.price_list_evidence_tree = app.tree(evidence_tab, evidence_cols, evidence_widths)
    ctx.M.bind_row_double_click(app.price_list_evidence_tree, lambda _event: open_price_list_detail(app))
    for variable in (app.price_q, app.price_supplier_filter, app.price_group_filter, app.price_effective_date):
        variable.trace_add("write", lambda *_: app.refresh_price_lists())
    app.refresh_price_lists()


def refresh_price_lists(app):
    current_tree = getattr(app, "price_current_tree", None)
    evidence_tree = getattr(app, "price_list_evidence_tree", None)
    if current_tree is None or evidence_tree is None:
        return
    q = (app.price_q.get() or "").strip().casefold()
    supplier_filter = (app.price_supplier_filter.get() or "").strip().casefold()
    group_filter = (app.price_group_filter.get() or "").strip().casefold()
    effective = _iso_date(app.price_effective_date.get()) or date.today().isoformat()
    for iid in current_tree.get_children(""):
        current_tree.delete(iid)
    app.price_current_rows = {}
    for iid in evidence_tree.get_children(""):
        evidence_tree.delete(iid)
    with ctx.M.db() as con:
        lists = con.execute(
            """SELECT p.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier,
                      (SELECT COUNT(*) FROM price_list_items i WHERE i.price_list_id=p.id AND i.active=1) item_count
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
               ORDER BY p.valid_from DESC,p.id DESC"""
        ).fetchall()
        items = con.execute(
            """SELECT i.*,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,p.update_mode,p.id price_list_id,
                      p.currency list_currency,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
               FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
               LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE i.active=1 AND p.archived=0
                 AND trim(coalesce(p.valid_from,''))<>'' AND p.valid_from<=?
                 AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
               ORDER BY p.valid_from DESC,p.id DESC,i.id DESC""",
            (effective, effective),
        ).fetchall()
    supplier_values = sorted({str(row["supplier"] or "").strip() for row in lists if str(row["supplier"] or "").strip()}, key=ctx.M.czech_sort_key)
    group_values = sorted({str(row["product_group"] or "").strip() for row in lists if str(row["product_group"] or "").strip()}, key=ctx.M.czech_sort_key)
    try:app.price_supplier_box.set_values(supplier_values); app.price_group_box.set_values(group_values)
    except Exception:pass
    chosen = {}
    duplicate_variants = []
    for row in items:
        identity = (
            (row["supplier"] or "").casefold(),
            (row["branch"] or "").casefold(),
            (row["product_group"] or "").casefold(),
            (row["product_code"] or row["item_key"] or row["name"] or "").casefold(),
            (row["name"] or row["description"] or "").casefold(),
            (row["condition_text"] or "").casefold(),
            round(_number(row["minimum_qty"]), 8),
            round(_number(row["price_basis_qty"]), 8),
            round(_number(row["package_qty"]), 8),
            (row["unit"] or "").casefold(),
        )
        existing = chosen.get(identity)
        if existing is None:
            chosen[identity] = row
        elif int(existing["price_list_id"]) == int(row["price_list_id"]):
            # The latest source itself contains two indistinguishable rows. Keep
            # both visible instead of silently discarding one price.
            duplicate_variants.append(row)
    visible_index = 0
    for row in list(chosen.values()) + duplicate_variants:
        hay = " ".join(str(row[key] or "") for key in ("supplier", "branch", "product_group", "product_code", "item_key", "name", "description", "condition_text", "title", "gtin", "customs_code", "dimensions")).casefold()
        if q and q not in hay:continue
        if supplier_filter and supplier_filter not in str(row["supplier"] or "").casefold():continue
        if group_filter and group_filter not in str(row["product_group"] or "").casefold():continue
        adjustment = _number(row["surcharge_pct"]) - _number(row["discount_pct"])
        adjustment_text = f"+{adjustment:g} %" if adjustment > 0 else f"{adjustment:g} %" if adjustment < 0 else ""
        visible_index += 1
        if visible_index > 1000:
            break
        current_iid = f"pc{visible_index}"
        app.price_current_rows[current_iid] = {"price_list_id": int(row["price_list_id"]), "item_id": int(row["id"])}
        current_tree.insert("", "end", iid=current_iid, values=(
            row["supplier"] or "", row["branch"] or "", row["product_code"] or row["item_key"] or "",
            row["name"] or row["description"] or "", _format_price(row["normalized_unit_price"], row["currency"] or row["list_currency"]),
            _format_price(row["source_price"], row["currency"] or row["list_currency"]), f"{_number(row['price_basis_qty']):g}",
            row["unit"] or "", adjustment_text,
            f"{_number(row['weight_unit']):g} kg" if _number(row["weight_unit"]) else "",
            f"{_number(row['minimum_qty']):g}" if _number(row["minimum_qty"]) else "",
            row["condition_text"] or "", ctx.M.fmt_date(row["valid_from"]), row["title"] or "",
        ))
    show_archived = bool(app.price_list_show_archived.get())
    for row in lists:
        if int(row["archived"] or 0) and not show_archived:continue
        evidence_tree.insert("", "end", iid=f"pl{row['id']}", values=(
            _list_status(row), ctx.M.fmt_date(row["valid_from"]), ctx.M.fmt_date(row["valid_to"]), row["supplier"] or "",
            row["title"] or "", row["product_group"] or "", row["branch"] or "", UPDATE_MODES.get(row["update_mode"], row["update_mode"]),
            row["item_count"], row["source_filename"] or "", ctx.M.fmt_history_datetime(row["imported_at"]),
        ), tags=("status_cancel",) if int(row["archived"] or 0) else ())
    try:
        layout = getattr(ctx.M, "schedule_final_tree_layout", None)
        if callable(layout):layout(app)
    except Exception:pass
