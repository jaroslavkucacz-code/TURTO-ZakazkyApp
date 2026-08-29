"""Indexed, paged and category-aware Ceníky page."""
from __future__ import annotations

import os
import re
import time
from datetime import date

from . import categories, product_catalog
from .price_dialogs import edit_price_list_metadata, open_price_list_detail, _selected_price_list_ids


def _filter_values(M, app):
    cached = getattr(app, "_price_filter_cache", None)
    selected_group = (getattr(app, "price_category_filter", None).get().strip()
                      if hasattr(app, "price_category_filter") else "")
    cache_key = selected_group
    if cached and time.monotonic() - cached[0] < 30 and len(cached) > 2 and cached[2] == cache_key:
        return cached[1]
    with M.db() as con:
        suppliers = [
            row["supplier"] for row in con.execute(
                """SELECT DISTINCT coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
                   FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
                   WHERE trim(coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),''))<>''
                   ORDER BY supplier COLLATE CZECH"""
            ).fetchall()
        ]
        ranges = [
            row[0] for row in con.execute(
                """SELECT DISTINCT trim(product_group) FROM price_lists
                   WHERE trim(coalesce(product_group,''))<>'' ORDER BY trim(product_group) COLLATE CZECH"""
            ).fetchall()
        ]
    group_rows = categories.list_categories(M)
    group_names = [row["name"] for row in group_rows]
    category_id = categories.category_id_by_name(M, selected_group) if selected_group and selected_group != "Všechny" else None
    subgroup_names = [row["name"] for row in categories.list_subgroups(M, category_id)]
    result = (suppliers, ranges, group_names, subgroup_names)
    app._price_filter_cache = (time.monotonic(), result, cache_key)
    return result

def _fts_query(value: str) -> str:
    tokens = re.findall(r"[0-9A-Za-zÀ-ž]+", value or "")
    return " AND ".join('"' + token.replace('"', '') + '"*' for token in tokens if token)


def _format_adjustment(row) -> str:
    surcharge = float(row["surcharge_pct"] or 0)
    discount = float(row["discount_pct"] or 0)
    value = surcharge - discount
    return f"+{value:g} %" if value > 0 else f"{value:g} %" if value < 0 else ""


def build_price_lists(M, app) -> None:
    from ..archive import price_list_archive_root

    page = app.tabs["pricelists"]
    for child in page.winfo_children():
        child.destroy()
    app.title_label(page, "Ceníky")
    top = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    top.pack(fill="x", pady=(0, 6))
    M.ttk.Button(top, text="+ Importovat Ceník", style="Accent.TButton", command=app.import_price_list).pack(side="left")

    def open_archive():
        root = price_list_archive_root()
        root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(root))

    M.ttk.Button(top, text="Otevřít archiv Ceníků", command=open_archive).pack(side="left", padx=5)
    M.ttk.Button(
        top, text="Produktové skupiny…", command=lambda: categories.manage_categories(M, app)
    ).pack(side="left", padx=5)
    M.ttk.Button(
        top, text="Katalog produktů…", command=lambda: product_catalog.open_product_catalog(M, app)
    ).pack(side="left", padx=5)
    M.ttk.Button(
        top, text="Hromadná archivace…", command=lambda: getattr(M, "open_bulk_archive_manager", lambda _app: None)(app)
    ).pack(side="left", padx=5)
    M.ttk.Label(
        top,
        text="Výsledky jsou stránkované a fotografie se nenačítají, dokud je výslovně nezapnete v detailu.",
        style="PageSubtitle.TLabel",
    ).pack(side="left", padx=(12, 0))

    notebook = M.ttk.Notebook(page)
    notebook.pack(fill="both", expand=True)
    app.price_notebook = notebook
    current = M.ttk.Frame(notebook, padding=8)
    evidence = M.ttk.Frame(notebook, padding=8)
    notebook.add(current, text="Aktuální ceny")
    notebook.add(evidence, text="Evidence ceníků")

    # ----------------------------- current effective prices
    filters = M.ttk.Frame(current, style="Panel.TFrame", padding=8)
    filters.pack(fill="x", pady=(0, 6))
    app.price_q = M.tk.StringVar()
    app.price_supplier_filter = M.tk.StringVar()
    app.price_category_filter = M.tk.StringVar(value="Všechny")
    app.price_subgroup_filter = M.tk.StringVar()
    app.price_group_filter = M.tk.StringVar()
    app.price_effective_date = M.tk.StringVar(value=date.today().isoformat())
    app.price_page_size = M.tk.StringVar(value="250")
    app.price_page = 0
    labels = ("Hledat produkt / kód", "Dodavatel", "Produktová skupina", "Podskupina", "Rozsah / cenová řada", "Cena platná k datu", "Řádků")
    for col, label in enumerate(labels):
        M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
        filters.columnconfigure(col, weight=3 if col == 0 else 1)
    M.ttk.Entry(filters, textvariable=app.price_q).grid(row=1, column=0, sticky="ew", padx=(0, 5))
    app.price_supplier_box = M.AutocompleteEntry(filters, textvariable=app.price_supplier_filter, values=[])
    app.price_supplier_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    app.price_category_box = M.safe_combobox(
        filters, textvariable=app.price_category_filter, values=["Všechny"], state="readonly"
    )
    app.price_category_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    app.price_subgroup_box = M.AutocompleteEntry(filters, textvariable=app.price_subgroup_filter, values=[])
    app.price_subgroup_box.grid(row=1, column=3, sticky="ew", padx=(0, 5))
    app.price_group_box = M.AutocompleteEntry(filters, textvariable=app.price_group_filter, values=[])
    app.price_group_box.grid(row=1, column=4, sticky="ew", padx=(0, 5))
    M.DatePicker(filters, app.price_effective_date).grid(row=1, column=5, sticky="ew", padx=(0, 5))
    M.safe_combobox(filters, textvariable=app.price_page_size, values=["100", "250", "500", "1000"], state="readonly", width=7).grid(
        row=1, column=6, sticky="ew"
    )

    current_cols = (
        "Produktová skupina", "Podskupina", "Interní kód", "Interní označení", "Výrobce",
        "Dodavatel", "Kód dodavatele", "Produkt", "Nákupní cena/MJ", "Marže",
        "Doporučená cena", "Sleva", "Výsledná cena", "MJ", "Min. odběr",
        "Podmínka", "Platí od", "Zdrojový ceník",
    )
    current_widths = [250, 280, 125, 250, 175, 180, 130, 330, 125, 75, 130, 75, 125, 65, 95, 230, 95, 240]
    app.price_current_tree = app.tree(current, current_cols, current_widths)
    app.price_current_rows = {}
    M.bind_row_double_click(app.price_current_tree, lambda _event: _open_current_detail(M, app))
    current_nav = M.ttk.Frame(current)
    current_nav.pack(fill="x", pady=(6, 0))
    app.price_current_status = M.tk.StringVar(value="")
    M.ttk.Label(current_nav, textvariable=app.price_current_status, style="PageSubtitle.TLabel").pack(side="left")
    M.ttk.Button(current_nav, text="Zrušit filtry", command=lambda: _clear_current_filters(M, app)).pack(side="left", padx=(12, 0))
    app.price_prev_button = M.ttk.Button(current_nav, text="← Předchozí", command=lambda: _change_current_page(M, app, -1))
    app.price_prev_button.pack(side="right", padx=3)
    app.price_next_button = M.ttk.Button(current_nav, text="Další →", command=lambda: _change_current_page(M, app, 1))
    app.price_next_button.pack(side="right", padx=3)

    # ----------------------------- price-list evidence
    evidence_filters = M.ttk.Frame(evidence, style="Panel.TFrame", padding=8)
    evidence_filters.pack(fill="x", pady=(0, 6))
    app.price_evidence_q = M.tk.StringVar()
    app.price_evidence_supplier = M.tk.StringVar()
    app.price_evidence_category = M.tk.StringVar(value="Všechny")
    app.price_evidence_status = M.tk.StringVar(value="Všechny")
    app.price_list_show_archived = M.tk.BooleanVar(value=False)
    app.price_evidence_page = 0
    app.price_evidence_page_size = 300
    for col, label in enumerate(("Hledat", "Dodavatel", "Produktová skupina", "Stav")):
        M.ttk.Label(evidence_filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
        evidence_filters.columnconfigure(col, weight=2 if col == 0 else 1)
    M.ttk.Entry(evidence_filters, textvariable=app.price_evidence_q).grid(row=1, column=0, sticky="ew", padx=(0, 5))
    app.price_evidence_supplier_box = M.AutocompleteEntry(evidence_filters, textvariable=app.price_evidence_supplier, values=[])
    app.price_evidence_supplier_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    app.price_evidence_category_box = M.safe_combobox(
        evidence_filters, textvariable=app.price_evidence_category, values=["Všechny"], state="readonly"
    )
    app.price_evidence_category_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    M.safe_combobox(
        evidence_filters, textvariable=app.price_evidence_status,
        values=["Všechny", "Aktuální", "Budoucí", "Po platnosti", "Ke kontrole", "Archivované"],
        state="readonly",
    ).grid(row=1, column=3, sticky="ew")

    evidence_tools = M.ttk.Frame(evidence, style="Panel.TFrame", padding=8)
    evidence_tools.pack(fill="x", pady=(0, 6))
    M.ttk.Checkbutton(
        evidence_tools, text="Zobrazit archivované", variable=app.price_list_show_archived,
        command=lambda: _reset_evidence_page_and_refresh(M, app),
    ).pack(side="left")
    M.ttk.Button(evidence_tools, text="Detail", style="Accent.TButton", command=lambda: open_price_list_detail(M, app)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Upravit údaje", command=lambda: edit_price_list_metadata(M, app)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Přiřadit produktovou skupinu", command=lambda: _assign_list_category(M, app)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Otevřít soubor", command=lambda: _open_evidence_source(M, app, False)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Otevřít složku", command=lambda: _open_evidence_source(M, app, True)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Archivovat", command=lambda: _archive_selected(M, app, False)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Obnovit", command=lambda: _archive_selected(M, app, True)).pack(side="right", padx=3)
    M.ttk.Button(evidence_tools, text="Smazat z DB", command=lambda: _delete_selected(M, app)).pack(side="right", padx=3)

    evidence_cols = (
        "Stav", "Platí od", "Platí do", "Dodavatel", "Produktová skupina", "Název", "Rozsah / cenová řada", "Větev",
        "Režim", "Položek", "Soubor", "Import",
    )
    evidence_widths = [130, 95, 95, 190, 210, 280, 150, 180, 180, 75, 250, 145]
    app.price_list_evidence_tree = app.tree(evidence, evidence_cols, evidence_widths)
    app.price_list_evidence_tree.configure(selectmode="extended")
    M.bind_row_double_click(app.price_list_evidence_tree, lambda _event: open_price_list_detail(M, app))
    evidence_nav = M.ttk.Frame(evidence)
    evidence_nav.pack(fill="x", pady=(6, 0))
    app.price_evidence_status_text = M.tk.StringVar(value="")
    M.ttk.Label(evidence_nav, textvariable=app.price_evidence_status_text, style="PageSubtitle.TLabel").pack(side="left")
    M.ttk.Button(evidence_nav, text="Zrušit filtry", command=lambda: _clear_evidence_filters(M, app)).pack(side="left", padx=(12, 0))
    app.price_evidence_prev = M.ttk.Button(evidence_nav, text="← Předchozí", command=lambda: _change_evidence_page(M, app, -1))
    app.price_evidence_prev.pack(side="right", padx=3)
    app.price_evidence_next = M.ttk.Button(evidence_nav, text="Další →", command=lambda: _change_evidence_page(M, app, 1))
    app.price_evidence_next.pack(side="right", padx=3)

    def schedule_current(*_):
        app.price_page = 0
        schedule_refresh(M, app)

    def schedule_evidence(*_):
        app.price_evidence_page = 0
        schedule_refresh(M, app)

    for variable in (
        app.price_q, app.price_supplier_filter, app.price_category_filter,
        app.price_subgroup_filter, app.price_group_filter, app.price_effective_date, app.price_page_size,
    ):
        variable.trace_add("write", schedule_current)
    for variable in (
        app.price_evidence_q, app.price_evidence_supplier,
        app.price_evidence_category, app.price_evidence_status,
    ):
        variable.trace_add("write", schedule_evidence)
    notebook.bind("<<NotebookTabChanged>>", lambda _event: refresh_price_lists(M, app), add="+")
    refresh_price_lists(M, app)


def schedule_refresh(M, app, delay: int = 180) -> None:
    previous = getattr(app, "_price_refresh_after", None)
    if previous:
        try:app.after_cancel(previous)
        except Exception:pass
    app._price_refresh_after = app.after(delay, lambda: refresh_price_lists(M, app))


def refresh_price_lists(M, app) -> None:
    app._price_refresh_after = None
    if not hasattr(app, "price_notebook"):
        return
    suppliers, ranges, category_names, subgroup_names = _filter_values(M, app)
    try:
        app.price_supplier_box.set_values(suppliers)
        app.price_evidence_supplier_box.set_values(suppliers)
        app.price_group_box.set_values(ranges)
        app.price_subgroup_box.set_values(subgroup_names)
        if app.price_subgroup_filter.get().strip() and app.price_subgroup_filter.get().strip() not in subgroup_names:
            app.price_subgroup_filter.set("")
        values = ["Všechny"] + category_names
        app.price_category_box.configure(values=values)
        app.price_evidence_category_box.configure(values=values)
    except Exception:
        pass
    try:
        tab_index = app.price_notebook.index(app.price_notebook.select())
    except Exception:
        tab_index = 0
    if tab_index == 0:
        _refresh_current(M, app)
    else:
        _refresh_evidence(M, app)


def _refresh_current(M, app, allow_fts_retry: bool = True) -> None:
    from ..common import _iso_date
    from ..storage import _format_price

    tree = app.price_current_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    app.price_current_rows = {}
    effective = _iso_date(app.price_effective_date.get()) or date.today().isoformat()
    where = [
        "i.active=1", "p.archived=0", "trim(coalesce(p.valid_from,''))<>''",
        "p.valid_from<=?", "(trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)",
    ]
    params = [effective, effective]
    if not getattr(app, "_turto_catalog_price_sync_v634", False):
        product_catalog.sync_all_unlinked(M, max_documents=120)
        app._turto_catalog_price_sync_v634 = True
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    category_expr = "coalesce(nullif(trim(pc.name),''),nullif(trim(ic.name),''),nullif(trim(lc.name),''),'Nezařazeno')"
    subgroup_expr = "coalesce(nullif(trim(psg.name),''),nullif(trim(sg.name),''),'')"
    query = app.price_q.get().strip()
    use_fts = bool(query and getattr(M, "PRICE_FTS_AVAILABLE", False) and _fts_query(query))
    join_fts = ""
    catalog_search = "lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,''))"
    if use_fts:
        where.append("(i.id IN (SELECT rowid FROM price_list_items_fts WHERE price_list_items_fts MATCH ?) OR " + catalog_search + " LIKE ?)")
        params.extend([_fts_query(query), "%" + query.casefold() + "%"])
    elif query:
        where.append(
            "lower(coalesce(i.product_code,'')||' '||coalesce(i.item_key,'')||' '||coalesce(i.name,'')||' '||"
            "coalesce(i.description,'')||' '||coalesce(i.condition_text,'')||' '||coalesce(i.gtin,'')||' '||"
            "coalesce(i.customs_code,'')||' '||coalesce(i.dimensions,'')||' '||coalesce(cp.internal_code,'')||' '||"
            "coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,'')) LIKE ?"
        )
        params.append("%" + query.casefold() + "%")
    supplier = app.price_supplier_filter.get().strip()
    if supplier:
        where.append(f"lower({supplier_expr}) LIKE ?")
        params.append("%" + supplier.casefold() + "%")
    category = app.price_category_filter.get().strip()
    if category and category != "Všechny":
        where.append("coalesce(cp.category_id,i.category_id,p.category_id)=?")
        params.append(categories.category_id_by_name(M, category) or -1)
    subgroup = app.price_subgroup_filter.get().strip()
    if subgroup:
        selected_category = categories.category_id_by_name(M, category) if category and category != "Všechny" else None
        where.append("coalesce(cp.subgroup_id,i.subgroup_id)=?")
        params.append(categories.subgroup_id_by_name(M, subgroup, selected_category) or -1)
    product_group = app.price_group_filter.get().strip()
    if product_group:
        where.append("lower(coalesce(p.product_group,'')) LIKE ?")
        params.append("%" + product_group.casefold() + "%")
    where_sql = " AND ".join(where)
    try:
        page_size = max(50, min(1000, int(app.price_page_size.get() or 250)))
    except Exception:
        page_size = 250
    offset = max(0, int(app.price_page or 0)) * page_size
    sql = f"""
        WITH candidates AS (
          SELECT i.id item_id,i.price_list_id,i.product_code,i.item_key,i.name,i.description,i.unit,
                 i.source_price,i.currency,i.price_basis_qty,i.normalized_unit_price,
                 i.discount_pct,i.surcharge_pct,i.weight_unit,i.minimum_qty,i.package_qty,
                 i.condition_text,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,
                 {supplier_expr} supplier,{category_expr} category,{subgroup_expr} subgroup,
                 cp.id catalog_product_id,coalesce(cp.internal_code,'') internal_code,
                 coalesce(cp.internal_name,'') internal_name,
                 coalesce(nullif(trim(cp.manufacturer_name),''),{supplier_expr}) manufacturer,
                 coalesce(psg.default_margin_pct,pc.default_margin_pct,0) margin_pct,
                 coalesce(psg.default_discount_pct,pc.default_discount_pct,0) sales_discount_pct,
                 coalesce(pc.show_recommended_price,1) show_recommended_price,
                 DENSE_RANK() OVER (
                   PARTITION BY lower({supplier_expr}),lower(coalesce(p.branch,'')),lower(coalesce(p.product_group,'')),
                     lower(coalesce(nullif(i.product_code,''),nullif(i.item_key,''),i.name,'')),
                     lower(coalesce(nullif(i.name,''),i.description,'')),lower(coalesce(i.condition_text,'')),
                     round(coalesce(i.minimum_qty,0),8),round(coalesce(i.price_basis_qty,0),8),
                     round(coalesce(i.package_qty,0),8),lower(coalesce(i.unit,''))
                   ORDER BY p.valid_from DESC,p.id DESC
                 ) list_rank
          FROM price_list_items i
          JOIN price_lists p ON p.id=i.price_list_id
          LEFT JOIN companies c ON c.id=p.supplier_company_id
          LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
          LEFT JOIN product_categories pc ON pc.id=cp.category_id
          LEFT JOIN product_subgroups psg ON psg.id=cp.subgroup_id
          LEFT JOIN product_categories ic ON ic.id=i.category_id
          LEFT JOIN product_categories lc ON lc.id=p.category_id
          LEFT JOIN product_subgroups sg ON sg.id=i.subgroup_id
          {join_fts}
          WHERE {where_sql}
        ), effective_rows AS (
          SELECT * FROM candidates WHERE list_rank=1
        )
        SELECT *,COUNT(*) OVER() total_count FROM effective_rows
        ORDER BY category COLLATE CZECH,subgroup COLLATE CZECH,supplier COLLATE CZECH,name COLLATE CZECH,item_id
        LIMIT ? OFFSET ?
    """
    try:
        with M.db() as con:
            rows = con.execute(sql, params + [page_size, offset]).fetchall()
    except M.sqlite3.OperationalError:
        if use_fts and allow_fts_retry:
            M.PRICE_FTS_AVAILABLE = False
            return _refresh_current(M, app, False)
        raise
    total = int(rows[0]["total_count"]) if rows else 0
    if total and offset >= total and app.price_page:
        app.price_page = 0
        return _refresh_current(M, app, allow_fts_retry)
    for index, row in enumerate(rows, 1):
        iid = f"pc{row['item_id']}"
        app.price_current_rows[iid] = {
            "price_list_id": int(row["price_list_id"]), "item_id": int(row["item_id"]),
            "catalog_product_id": int(row["catalog_product_id"]) if row["catalog_product_id"] else None,
        }
        recommended, final = product_catalog.calculate_prices(
            row["normalized_unit_price"], row["margin_pct"], row["sales_discount_pct"]
        )
        tree.insert(
            "", "end", iid=iid,
            values=(
                row["category"], row["subgroup"] or "", row["internal_code"], row["internal_name"],
                row["manufacturer"], row["supplier"], row["product_code"] or row["item_key"] or "",
                row["name"] or row["description"] or "", _format_price(row["normalized_unit_price"], row["currency"]),
                f"{float(row['margin_pct'] or 0):g} %",
                _format_price(recommended, row["currency"]) if row["show_recommended_price"] else "—",
                f"{float(row['sales_discount_pct'] or 0):g} %", _format_price(final, row["currency"]),
                row["unit"] or "", f"{float(row['minimum_qty'] or 0):g}" if row["minimum_qty"] else "",
                row["condition_text"] or "", M.fmt_date(row["valid_from"]), row["title"] or "",
            ),
        )
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    app.price_current_status.set(
        f"Zobrazeno {start}–{end} z {total} platných cen · vyhodnoceno k {M.fmt_date(effective)}"
    )
    app.price_prev_button.state(["!disabled"] if app.price_page > 0 else ["disabled"])
    app.price_next_button.state(["!disabled"] if end < total else ["disabled"])


def _refresh_evidence(M, app) -> None:
    from ..common import UPDATE_MODES
    from ..storage import _list_status

    tree = app.price_list_evidence_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    category_expr = "coalesce(nullif(trim(cat.name),''),'Nezařazeno')"
    where = []
    params = []
    if not app.price_list_show_archived.get():
        where.append("p.archived=0")
    query = app.price_evidence_q.get().strip().casefold()
    if query:
        where.append(
            f"lower({supplier_expr}||' '||coalesce(p.title,'')||' '||coalesce(p.product_group,'')||' '||"
            "coalesce(p.branch,'')||' '||coalesce(p.source_filename,'')) LIKE ?"
        )
        params.append("%" + query + "%")
    supplier = app.price_evidence_supplier.get().strip()
    if supplier:
        where.append(f"lower({supplier_expr}) LIKE ?")
        params.append("%" + supplier.casefold() + "%")
    category = app.price_evidence_category.get().strip()
    if category and category != "Všechny":
        where.append("p.category_id=?")
        params.append(categories.category_id_by_name(M, category) or -1)
    status = app.price_evidence_status.get()
    today = date.today().isoformat()
    if status == "Aktuální":
        where += ["p.archived=0", "p.valid_from<=?", "(p.valid_to='' OR p.valid_to>=?)", "lower(coalesce(p.parse_status,'')) NOT LIKE '%ocr%'", "lower(coalesce(p.parse_status,'')) NOT LIKE '%kontrol%'", "lower(coalesce(p.parse_status,'')) NOT LIKE 'bez%'"]
        params += [today, today]
    elif status == "Budoucí":
        where += ["p.archived=0", "p.valid_from>?"]
        params.append(today)
    elif status == "Po platnosti":
        where += ["p.archived=0", "trim(coalesce(p.valid_to,''))<>''", "p.valid_to<?"]
        params.append(today)
    elif status == "Ke kontrole":
        where.append("(lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR lower(coalesce(p.parse_status,'')) LIKE 'bez%')")
    elif status == "Archivované":
        where.append("p.archived=1")
    where_sql = " AND ".join(where) if where else "1=1"
    offset = max(0, int(app.price_evidence_page or 0)) * app.price_evidence_page_size
    with M.db() as con:
        total = con.execute(
            f"""SELECT COUNT(*) FROM price_lists p
                 LEFT JOIN companies c ON c.id=p.supplier_company_id
                 LEFT JOIN product_categories cat ON cat.id=p.category_id
                 WHERE {where_sql}""",
            params,
        ).fetchone()[0]
        rows = con.execute(
            f"""SELECT p.*,{supplier_expr} supplier,{category_expr} category,coalesce(cnt.item_count,0) item_count
                 FROM price_lists p
                 LEFT JOIN companies c ON c.id=p.supplier_company_id
                 LEFT JOIN product_categories cat ON cat.id=p.category_id
                 LEFT JOIN (
                   SELECT price_list_id,COUNT(*) item_count FROM price_list_items
                   WHERE active=1 GROUP BY price_list_id
                 ) cnt ON cnt.price_list_id=p.id
                 WHERE {where_sql}
                 ORDER BY CASE WHEN trim(coalesce(p.valid_from,''))='' THEN 1 ELSE 0 END,
                          p.valid_from DESC,p.id DESC LIMIT ? OFFSET ?""",
            params + [app.price_evidence_page_size, offset],
        ).fetchall()
    if total and offset >= total and app.price_evidence_page:
        app.price_evidence_page = 0
        return _refresh_evidence(M, app)
    for row in rows:
        row_status = _list_status(row)
        tree.insert(
            "", "end", iid=f"pl{row['id']}",
            values=(
                row_status, M.fmt_date(row["valid_from"]), M.fmt_date(row["valid_to"]), row["supplier"],
                row["category"], row["title"], row["product_group"], row["branch"],
                UPDATE_MODES.get(row["update_mode"], row["update_mode"]), row["item_count"],
                row["source_filename"], M.fmt_history_datetime(row["imported_at"]),
            ),
            tags=("status_cancel",) if int(row["archived"] or 0) else (),
        )
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    app.price_evidence_status_text.set(f"Zobrazeno {start}–{end} z {total} ceníků")
    app.price_evidence_prev.state(["!disabled"] if app.price_evidence_page > 0 else ["disabled"])
    app.price_evidence_next.state(["!disabled"] if end < total else ["disabled"])


def _open_current_detail(M, app):
    selection = app.price_current_tree.selection()
    if not selection:
        return
    info = app.price_current_rows.get(selection[0]) or {}
    open_price_list_detail(M, app, info.get("price_list_id"))


def _change_current_page(M, app, delta):
    app.price_page = max(0, int(app.price_page or 0) + delta)
    _refresh_current(M, app)


def _change_evidence_page(M, app, delta):
    app.price_evidence_page = max(0, int(app.price_evidence_page or 0) + delta)
    _refresh_evidence(M, app)


def _clear_current_filters(M, app):
    app.price_q.set("")
    app.price_supplier_filter.set("")
    app.price_category_filter.set("Všechny")
    app.price_subgroup_filter.set("")
    app.price_group_filter.set("")
    app.price_effective_date.set(date.today().isoformat())
    app.price_page = 0
    schedule_refresh(M, app, 0)


def _clear_evidence_filters(M, app):
    app.price_evidence_q.set("")
    app.price_evidence_supplier.set("")
    app.price_evidence_category.set("Všechny")
    app.price_evidence_status.set("Všechny")
    app.price_evidence_page = 0
    schedule_refresh(M, app, 0)


def _reset_evidence_page_and_refresh(M, app):
    app.price_evidence_page = 0
    _refresh_evidence(M, app)


def _archive_selected(M, app, restore: bool):
    ids = _selected_price_list_ids(app)
    if not ids:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden nebo více ceníků.", parent=app)
    with M.db() as con:
        con.executemany("UPDATE price_lists SET archived=? WHERE id=?", [(0 if restore else 1, pid) for pid in ids])
    app._price_filter_cache = None
    refresh_price_lists(M, app)


def _assign_list_category(M, app):
    ids = _selected_price_list_ids(app)
    if not ids:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden nebo více ceníků.", parent=app)
    selected = categories.choose_category(M, app, "Přiřadit kategorii Ceníkům", allow_auto=True)
    if selected == "cancel":
        return
    if selected == "auto":
        for price_list_id in ids:
            with M.db() as con:
                con.execute("UPDATE price_lists SET category_id=NULL WHERE id=?", (price_list_id,))
            categories.autocategorize_price_list(M, price_list_id, only_empty=False)
    else:
        categories.set_price_list_category(M, ids, selected, apply_to_items=True)
    app._price_filter_cache = None
    refresh_price_lists(M, app)


def _delete_selected(M, app):
    ids = _selected_price_list_ids(app)
    if not ids:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden nebo více ceníků.", parent=app)
    if not M.messagebox.askyesno(
        "Smazat Ceníky z databáze",
        f"Odstranit {len(ids)} vybraných Ceníků a jejich vytěžené položky z databáze?\n\n"
        "Původní archivované soubory na disku zůstanou zachované.",
        parent=app,
    ):
        return
    with M.db() as con:
        con.executemany("DELETE FROM price_lists WHERE id=?", [(pid,) for pid in ids])
    app._price_filter_cache = None
    refresh_price_lists(M, app)
    try:app.refresh_offers()
    except Exception:pass


def _open_evidence_source(M, app, folder: bool):
    from ..operations import open_price_list_file, open_price_list_folder
    if len(_selected_price_list_ids(app)) != 1:
        return M.messagebox.showinfo("Ceníky", "Vyberte jeden ceník.", parent=app)
    (open_price_list_folder if folder else open_price_list_file)(app)
