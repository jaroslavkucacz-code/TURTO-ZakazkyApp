"""CRM-style workspace for browsing and moving catalogue products.

The stable catalogue data owner remains :mod:`product_catalog`. This module is
its single presentation owner: product groups form a navigation tree on the
left and the products belonging to the selected group/subgroup are shown on the
right. Moving a catalogue product uses the existing service so every linked
price-list and supplier-offer row follows the same stable product.
"""
from __future__ import annotations

from datetime import date

from . import categories, product_catalog

_SCOPE_ALL = "all"
_SCOPE_UNASSIGNED = "unassigned"
_SCOPE_GROUP_PREFIX = "g"
_SCOPE_SUBGROUP_PREFIX = "s"
_SCOPE_NO_SUBGROUP_PREFIX = "n"


def _root_app(widget):
    current = widget
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        master = getattr(current, "master", None)
        if master is None:
            break
        current = master
    return current or widget


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return float(default)


def _selected_product_ids(tree) -> list[int]:
    result: list[int] = []
    for iid in tree.selection():
        text = str(iid)
        if text.startswith("cp"):
            try:
                result.append(int(text[2:]))
            except Exception:
                pass
    return result


def _scope_from_iid(M, iid: str) -> dict:
    text = str(iid or _SCOPE_ALL)
    if text == _SCOPE_UNASSIGNED:
        return {
            "iid": text,
            "category_id": None,
            "subgroup_id": None,
            "only_without_subgroup": False,
            "only_unassigned": True,
            "assignable": True,
            "label": categories.UNASSIGNED,
        }
    if text.startswith(_SCOPE_SUBGROUP_PREFIX) and text[1:].isdigit():
        subgroup_id = int(text[1:])
        category_id = categories.subgroup_parent_id(M, subgroup_id)
        return {
            "iid": text,
            "category_id": category_id,
            "subgroup_id": subgroup_id,
            "only_without_subgroup": False,
            "only_unassigned": False,
            "assignable": True,
            "label": categories.taxonomy_path(M, category_id, subgroup_id),
        }
    if text.startswith(_SCOPE_NO_SUBGROUP_PREFIX) and text[1:].isdigit():
        category_id = int(text[1:])
        return {
            "iid": text,
            "category_id": category_id,
            "subgroup_id": None,
            "only_without_subgroup": True,
            "only_unassigned": False,
            "assignable": True,
            "label": f"{categories.category_name(M, category_id)} › {categories.NO_SUBGROUP}",
        }
    if text.startswith(_SCOPE_GROUP_PREFIX) and text[1:].isdigit():
        category_id = int(text[1:])
        return {
            "iid": text,
            "category_id": category_id,
            "subgroup_id": None,
            "only_without_subgroup": False,
            "only_unassigned": False,
            "assignable": True,
            "label": categories.category_name(M, category_id),
        }
    return {
        "iid": _SCOPE_ALL,
        "category_id": None,
        "subgroup_id": None,
        "only_without_subgroup": False,
        "only_unassigned": False,
        "assignable": False,
        "label": "Všechny produkty",
    }


def _scope_conditions(scope: dict, alias: str = "cp") -> tuple[list[str], list[object]]:
    where: list[str] = []
    params: list[object] = []
    if scope.get("only_unassigned"):
        where.append(f"{alias}.category_id IS NULL")
    elif scope.get("subgroup_id"):
        where.append(f"{alias}.subgroup_id=?")
        params.append(int(scope["subgroup_id"]))
    elif scope.get("category_id"):
        where.append(f"{alias}.category_id=?")
        params.append(int(scope["category_id"]))
        if scope.get("only_without_subgroup"):
            where.append(f"{alias}.subgroup_id IS NULL")
    return where, params


def _structure_rows(M, include_inactive_products: bool = False):
    product_active = "1=1" if include_inactive_products else "p.active=1"
    with M.db() as con:
        totals = con.execute(
            f"""SELECT
                  (SELECT COUNT(*) FROM catalog_products p WHERE {product_active}) product_count,
                  (SELECT COUNT(*) FROM catalog_products p WHERE {product_active} AND p.category_id IS NULL) unassigned_count,
                  (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                    JOIN catalog_products p ON p.id=i.catalog_product_id WHERE {product_active}) list_count,
                  (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                    JOIN catalog_products p ON p.id=i.catalog_product_id WHERE {product_active}) offer_count"""
        ).fetchone()
        groups = con.execute(
            f"""SELECT c.id,c.name,c.active,c.sort_order,
                      (SELECT COUNT(*) FROM catalog_products p
                        WHERE p.category_id=c.id AND {product_active}) product_count,
                      (SELECT COUNT(*) FROM catalog_products p
                        WHERE p.category_id=c.id AND p.subgroup_id IS NULL AND {product_active}) no_subgroup_count,
                      (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                        JOIN catalog_products p ON p.id=i.catalog_product_id
                        WHERE p.category_id=c.id AND {product_active}) list_count,
                      (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                        JOIN catalog_products p ON p.id=i.catalog_product_id
                        WHERE p.category_id=c.id AND {product_active}) offer_count
                 FROM product_categories c
                 ORDER BY c.active DESC,c.sort_order,c.name COLLATE CZECH"""
        ).fetchall()
        subgroups = con.execute(
            f"""SELECT s.id,s.category_id,s.name,s.active,s.sort_order,
                      (SELECT COUNT(*) FROM catalog_products p
                        WHERE p.subgroup_id=s.id AND {product_active}) product_count,
                      (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                        JOIN catalog_products p ON p.id=i.catalog_product_id
                        WHERE p.subgroup_id=s.id AND {product_active}) list_count,
                      (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                        JOIN catalog_products p ON p.id=i.catalog_product_id
                        WHERE p.subgroup_id=s.id AND {product_active}) offer_count
                 FROM product_subgroups s
                 ORDER BY s.active DESC,s.sort_order,s.name COLLATE CZECH"""
        ).fetchall()
    return totals, groups, subgroups


def _catalog_rows(
    M, scope: dict, query: str = "", manufacturer: str = "", show_inactive: bool = False,
    limit: int = 250, offset: int = 0,
):
    where = ["1=1"]
    params: list[object] = []
    if not show_inactive:
        where.append("cp.active=1")
    scope_where, scope_params = _scope_conditions(scope)
    where.extend(scope_where)
    params.extend(scope_params)
    text = str(query or "").strip().casefold()
    if text:
        where.append(
            """lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||
               coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')||' '||
               coalesce(src.source_code,'')||' '||coalesce(src.source_name,'')) LIKE ?"""
        )
        params.append("%" + text + "%")
    maker = str(manufacturer or "").strip().casefold()
    if maker:
        where.append("lower(coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')) LIKE ?")
        params.append("%" + maker + "%")
    where_sql = " AND ".join(where)
    today = date.today().isoformat()
    sql_from = """
        FROM catalog_products cp
        LEFT JOIN product_categories c ON c.id=cp.category_id
        LEFT JOIN product_subgroups sg ON sg.id=cp.subgroup_id
        LEFT JOIN (
          SELECT product_id,group_concat(DISTINCT supplier_name) suppliers,
                 min(nullif(trim(supplier_product_code),'')) source_code,
                 min(nullif(trim(source_name),'')) source_name
          FROM catalog_product_sources GROUP BY product_id
        ) src ON src.product_id=cp.id
    """
    with M.db() as con:
        total = int(con.execute(
            "SELECT COUNT(*) " + sql_from + " WHERE " + where_sql, params
        ).fetchone()[0] or 0)
        rows = con.execute(
            """SELECT cp.id,cp.active,cp.category_id,cp.subgroup_id,
                      cp.manufacturer_name,cp.internal_code,cp.internal_name,
                      coalesce(c.name,'Nezařazeno') category,coalesce(sg.name,'') subgroup,
                      coalesce(sg.default_margin_pct,c.default_margin_pct,0) margin_pct,
                      coalesce(sg.default_discount_pct,c.default_discount_pct,0) discount_pct,
                      coalesce(c.show_recommended_price,1) show_recommended_price,
                      coalesce(src.suppliers,'') suppliers,coalesce(src.source_code,'') source_code,
                      coalesce(src.source_name,'') source_name,
                      (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                        WHERE i.catalog_product_id=cp.id) price_lists,
                      (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                        WHERE i.catalog_product_id=cp.id) offers,
                      (SELECT i.normalized_unit_price FROM price_list_items i
                        JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                          AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) current_price,
                      (SELECT i.currency FROM price_list_items i
                        JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                          AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) current_currency
               """ + sql_from + " WHERE " + where_sql +
            " ORDER BY cp.manufacturer_name COLLATE CZECH,src.source_name COLLATE CZECH,cp.id LIMIT ? OFFSET ?",
            [today, today, today, today] + params + [max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        summary = con.execute(
            """SELECT COUNT(*) products,
                      COUNT(DISTINCT nullif(trim(cp.manufacturer_name),'')) manufacturers,
                      coalesce(SUM((SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                                    WHERE i.catalog_product_id=cp.id)),0) list_links,
                      coalesce(SUM((SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                                    WHERE i.catalog_product_id=cp.id)),0) offer_links
               """ + sql_from + " WHERE " + where_sql,
            params,
        ).fetchone()
    return total, rows, summary


def build_product_workspace(M, app, parent, category_id=None, subgroup_id=None, embedded: bool = False):
    """Build the split CRM workspace and return a small test/control API."""
    app = _root_app(app)
    outer = M.ttk.Frame(parent, padding=10)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(2, weight=1)

    if not embedded:
        M.ttk.Label(outer, text="Katalog produktů", font=("Calibri", 17, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        M.ttk.Label(
            outer,
            text=("Vlevo vyberte skupinu nebo podskupinu. Vpravo se ihned zobrazí její produkty; "
                  "vybrané řádky můžete přesunout přímo do označené části katalogu."),
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        workspace_row = 2
    else:
        workspace_row = 0
        outer.rowconfigure(0, weight=1)

    pane = M.ttk.Panedwindow(outer, orient="horizontal")
    pane.grid(row=workspace_row, column=0, sticky="nsew")

    left = M.ttk.Frame(pane, style="Panel.TFrame", padding=8)
    right = M.ttk.Frame(pane, padding=(10, 0, 0, 0))
    pane.add(left, weight=1)
    pane.add(right, weight=4)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(2, weight=1)
    right.columnconfigure(0, weight=1)
    right.rowconfigure(4, weight=1)

    M.ttk.Label(left, text="Produktové skupiny", font=("Calibri", 13, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    M.ttk.Label(
        left, text="Kliknutím filtrujete produkty. Šipkou rozbalíte podskupiny.",
        style="PageSubtitle.TLabel", wraplength=340,
    ).grid(row=1, column=0, sticky="w", pady=(1, 6))

    structure_cols = ("Produktů", "Ceníků", "Nabídek")
    structure = M.ttk.Treeview(
        left, columns=structure_cols, show="tree headings", selectmode="browse", height=24
    )
    structure.heading("#0", text="Skupina / podskupina")
    structure.column("#0", width=340, minwidth=220, anchor="w", stretch=True)
    for col, width in (("Produktů", 72), ("Ceníků", 62), ("Nabídek", 65)):
        structure.heading(col, text=col)
        structure.column(col, width=width, minwidth=55, anchor="e", stretch=False)
    structure.grid(row=2, column=0, sticky="nsew")
    structure_scroll = M.ttk.Scrollbar(left, orient="vertical", command=structure.yview)
    structure_scroll.grid(row=2, column=1, sticky="ns")
    structure.configure(yscrollcommand=structure_scroll.set)

    left_tools = M.ttk.Frame(left)
    left_tools.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))

    scope_title = M.tk.StringVar(value="Všechny produkty")
    scope_summary = M.tk.StringVar(value="")
    M.ttk.Label(right, textvariable=scope_title, font=("Calibri", 14, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    M.ttk.Label(right, textvariable=scope_summary, style="PageSubtitle.TLabel").grid(
        row=1, column=0, sticky="w", pady=(1, 6)
    )

    filters = M.ttk.Frame(right, style="Panel.TFrame", padding=8)
    filters.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    filters.columnconfigure(0, weight=3)
    filters.columnconfigure(1, weight=2)
    query = M.tk.StringVar()
    manufacturer = M.tk.StringVar()
    show_inactive = M.tk.BooleanVar(value=False)
    for col, label in enumerate(("Hledat produkt, interní kód nebo kód dodavatele", "Výrobce / dodavatel")):
        M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
    M.ttk.Entry(filters, textvariable=query).grid(row=1, column=0, sticky="ew", padx=(0, 6))
    manufacturer_box = M.AutocompleteEntry(filters, textvariable=manufacturer, values=[])
    manufacturer_box.grid(row=1, column=1, sticky="ew", padx=(0, 6))
    M.ttk.Checkbutton(filters, text="Zobrazit neaktivní produkty", variable=show_inactive).grid(
        row=1, column=2, sticky="w"
    )

    actions = M.ttk.Frame(right, style="Panel.TFrame", padding=8)
    actions.grid(row=3, column=0, sticky="ew", pady=(0, 6))

    table_wrap = M.ttk.Frame(right)
    table_wrap.grid(row=4, column=0, sticky="nsew")
    table_wrap.columnconfigure(0, weight=1)
    table_wrap.rowconfigure(0, weight=1)
    cols = (
        "Interní kód", "Interní označení", "Výrobce", "Dodavatel", "Kód dodavatele",
        "Označení dodavatele", "Produktová skupina", "Podskupina", "Nákupní cena",
        "Marže", "Sleva", "Výsledná cena", "Ceníků", "Nabídek",
    )
    widths = (120, 230, 165, 175, 135, 290, 230, 250, 125, 68, 68, 125, 65, 65)
    products = M.ttk.Treeview(table_wrap, columns=cols, show="headings", selectmode="extended")
    for col, width in zip(cols, widths):
        products.heading(col, text=col)
        products.column(col, width=width, minwidth=55, anchor="w")
    products.grid(row=0, column=0, sticky="nsew")
    product_y = M.ttk.Scrollbar(table_wrap, orient="vertical", command=products.yview)
    product_x = M.ttk.Scrollbar(table_wrap, orient="horizontal", command=products.xview)
    product_y.grid(row=0, column=1, sticky="ns")
    product_x.grid(row=1, column=0, sticky="ew")
    products.configure(yscrollcommand=product_y.set, xscrollcommand=product_x.set)

    nav = M.ttk.Frame(right)
    nav.grid(row=5, column=0, sticky="ew", pady=(6, 0))
    status = M.tk.StringVar(value="")
    selection_status = M.tk.StringVar(value="Vybráno: 0")
    M.ttk.Label(nav, textvariable=status, style="PageSubtitle.TLabel").pack(side="left")
    M.ttk.Label(nav, textvariable=selection_status, style="PageSubtitle.TLabel").pack(side="left", padx=(14, 0))
    prev_button = M.ttk.Button(nav, text="← Předchozí")
    next_button = M.ttk.Button(nav, text="Další →")
    next_button.pack(side="right", padx=3)
    prev_button.pack(side="right", padx=3)

    row_map: dict[str, dict] = {}
    state = {
        "scope_iid": _SCOPE_ALL,
        "page": 0,
        "page_size": 250,
        "after": None,
    }

    def selected_scope() -> dict:
        selection = structure.selection()
        iid = str(selection[0]) if selection else str(state["scope_iid"])
        return _scope_from_iid(M, iid)

    def refresh_manufacturers():
        with M.db() as con:
            values = [row[0] for row in con.execute(
                """SELECT DISTINCT trim(value) FROM (
                     SELECT manufacturer_name value FROM catalog_products
                     UNION ALL SELECT supplier_name FROM catalog_product_sources
                   ) WHERE trim(coalesce(value,''))<>'' ORDER BY value COLLATE CZECH"""
            ).fetchall()]
        manufacturer_box.set_values(values)

    def refresh_structure(select_iid=None):
        opened = {iid for iid in structure.get_children("") if structure.item(iid, "open")}
        selected_iid = str(select_iid or state["scope_iid"] or _SCOPE_ALL)
        for iid in structure.get_children(""):
            structure.delete(iid)
        totals, groups, subgroups = _structure_rows(M, bool(show_inactive.get()))
        structure.insert(
            "", "end", iid=_SCOPE_ALL, text="Všechny produkty",
            values=(totals["product_count"], totals["list_count"], totals["offer_count"]),
            open=True,
        )
        structure.insert(
            "", "end", iid=_SCOPE_UNASSIGNED, text="Nezařazené",
            values=(totals["unassigned_count"], "", ""), tags=("status_wait",),
        )
        by_group: dict[int, list] = {}
        for subgroup_row in subgroups:
            by_group.setdefault(int(subgroup_row["category_id"]), []).append(subgroup_row)
        selected_scope_data = _scope_from_iid(M, selected_iid)
        selected_category_id = selected_scope_data.get("category_id")
        for group_row in groups:
            group_id = int(group_row["id"])
            group_iid = f"{_SCOPE_GROUP_PREFIX}{group_id}"
            structure.insert(
                "", "end", iid=group_iid, text=group_row["name"],
                values=(group_row["product_count"], group_row["list_count"], group_row["offer_count"]),
                open=(group_iid in opened or selected_category_id == group_id),
                tags=("status_cancel",) if not group_row["active"] else (),
            )
            structure.insert(
                group_iid, "end", iid=f"{_SCOPE_NO_SUBGROUP_PREFIX}{group_id}",
                text=categories.NO_SUBGROUP, values=(group_row["no_subgroup_count"], "", ""),
            )
            for subgroup_row in by_group.get(group_id, []):
                subgroup_iid = f"{_SCOPE_SUBGROUP_PREFIX}{subgroup_row['id']}"
                structure.insert(
                    group_iid, "end", iid=subgroup_iid, text=subgroup_row["name"],
                    values=(subgroup_row["product_count"], subgroup_row["list_count"], subgroup_row["offer_count"]),
                    tags=("status_cancel",) if not subgroup_row["active"] else (),
                )
        if not structure.exists(selected_iid):
            selected_iid = _SCOPE_ALL
        state["scope_iid"] = selected_iid
        structure.selection_set(selected_iid)
        structure.see(selected_iid)

    def refresh_products():
        state["after"] = None
        for iid in products.get_children(""):
            products.delete(iid)
        row_map.clear()
        scope = selected_scope()
        state["scope_iid"] = scope["iid"]
        scope_title.set(scope["label"] or "Všechny produkty")
        offset = int(state["page"]) * int(state["page_size"])
        total, rows, summary = _catalog_rows(
            M, scope, query.get(), manufacturer.get(), bool(show_inactive.get()),
            int(state["page_size"]), offset,
        )
        from ..storage import _format_price
        for row in rows:
            purchase = _number(row["current_price"])
            _recommended, final = product_catalog.calculate_prices(
                purchase, row["margin_pct"], row["discount_pct"]
            )
            iid = f"cp{row['id']}"
            row_map[iid] = dict(row)
            products.insert(
                "", "end", iid=iid,
                values=(
                    row["internal_code"], row["internal_name"],
                    row["manufacturer_name"] or row["suppliers"], row["suppliers"],
                    row["source_code"], row["source_name"], row["category"], row["subgroup"],
                    _format_price(row["current_price"], row["current_currency"] or "CZK"),
                    f"{_number(row['margin_pct']):g} %", f"{_number(row['discount_pct']):g} %",
                    _format_price(final if row["current_price"] is not None else None, row["current_currency"] or "CZK"),
                    row["price_lists"], row["offers"],
                ),
                tags=("status_cancel",) if not row["active"] else (),
            )
        start = offset + 1 if total else 0
        end = min(total, offset + len(rows))
        remaining = product_catalog.count_unlinked(M)
        extra = f" · {remaining} dosud nespojených položek" if remaining else ""
        status.set(f"Zobrazeno {start}–{end} z {total}{extra}")
        scope_summary.set(
            f"Produktů: {summary['products']} · Výrobců: {summary['manufacturers']} · "
            f"Vazeb na Ceníky: {summary['list_links']} · Vazeb na cenové Nabídky: {summary['offer_links']}"
        )
        prev_button.state(["!disabled"] if state["page"] > 0 else ["disabled"])
        next_button.state(["!disabled"] if end < total else ["disabled"])
        selection_status.set("Vybráno: 0")

    def schedule_products(*_):
        state["page"] = 0
        if state["after"]:
            try:
                parent.after_cancel(state["after"])
            except Exception:
                pass
        state["after"] = parent.after(160, refresh_products)

    def on_scope_change(*_):
        selection = structure.selection()
        if not selection:
            return
        state["scope_iid"] = str(selection[0])
        state["page"] = 0
        refresh_products()

    def update_selection_status(*_):
        selection_status.set(f"Vybráno: {len(_selected_product_ids(products))}")

    def edit_selected():
        ids = _selected_product_ids(products)
        if len(ids) != 1:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte právě jeden produkt.", parent=parent)
        product_catalog._edit_product(M, app, parent, ids[0], lambda: refresh_all(state["scope_iid"]))

    def move_to_scope(target_scope: dict):
        ids = _selected_product_ids(products)
        if not ids:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte jeden nebo více produktů.", parent=parent)
        if not target_scope.get("assignable"):
            return M.messagebox.showinfo(
                "Katalog produktů",
                "Jako cíl vyberte vlevo konkrétní skupinu, podskupinu, „Bez podskupiny“ nebo „Nezařazené“.",
                parent=parent,
            )
        if not M.messagebox.askyesno(
            "Přesunout produkty",
            f"Přesunout vybrané produkty ({len(ids)}) do:\n\n{target_scope['label']}?\n\n"
            "Změna se automaticky projeví ve všech jejich Ceníkách i cenových Nabídkách.",
            parent=parent,
        ):
            return
        product_catalog.set_product_taxonomy(
            M, ids, target_scope.get("category_id"), target_scope.get("subgroup_id")
        )
        product_catalog._invalidate(app)
        refresh_all(target_scope["iid"])

    def move_selected_here():
        move_to_scope(selected_scope())

    def move_selected_elsewhere():
        ids = _selected_product_ids(products)
        if not ids:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte jeden nebo více produktů.", parent=parent)
        first = row_map.get(str(products.selection()[0]), {}) if products.selection() else {}
        selected = categories.choose_taxonomy(
            M, parent, "Přesunout produkty do skupiny a podskupiny",
            first.get("category_id"), first.get("subgroup_id"),
        )
        if selected == "cancel":
            return
        target_category, target_subgroup = selected
        target_iid = (
            f"{_SCOPE_SUBGROUP_PREFIX}{target_subgroup}" if target_subgroup else
            f"{_SCOPE_NO_SUBGROUP_PREFIX}{target_category}" if target_category else _SCOPE_UNASSIGNED
        )
        product_catalog.set_product_taxonomy(M, ids, target_category, target_subgroup)
        product_catalog._invalidate(app)
        refresh_all(target_iid)

    def show_sources():
        ids = _selected_product_ids(products)
        if len(ids) != 1:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte právě jeden produkt.", parent=parent)
        product_catalog._open_sources(M, parent, ids[0])

    def manage_structure():
        categories.manage_categories(M, app)
        refresh_all(state["scope_iid"])

    def clear_filters():
        query.set("")
        manufacturer.set("")
        show_inactive.set(False)
        state["page"] = 0
        refresh_all(_SCOPE_ALL)

    def sync_everything():
        progress_win = M.tk.Toplevel(parent)
        progress_win.title("Synchronizace katalogu")
        progress_win.transient(parent)
        progress_win.grab_set()
        frame = M.ttk.Frame(progress_win, padding=16)
        frame.pack(fill="both", expand=True)
        label = M.tk.StringVar(value="Připravuji synchronizaci…")
        M.ttk.Label(frame, textvariable=label).pack(anchor="w", pady=(0, 8))
        bar = M.ttk.Progressbar(frame, mode="determinate", length=540)
        bar.pack(fill="x")
        cancelled = {"value": False}
        M.ttk.Button(frame, text="Storno", command=lambda: cancelled.__setitem__("value", True)).pack(
            anchor="e", pady=(10, 0)
        )

        def progress(done, total, text):
            bar.configure(maximum=max(1, total), value=done)
            label.set(f"{done}/{total} · {text}")
            progress_win.update()
            if cancelled["value"]:
                raise RuntimeError("__TURTO_CATALOG_CANCELLED__")

        try:
            result = product_catalog.sync_all_unlinked(M, max_documents=None, progress=progress)
        except Exception as exc:
            progress_win.destroy()
            if str(exc) == "__TURTO_CATALOG_CANCELLED__":
                refresh_all(state["scope_iid"])
                return M.messagebox.showinfo(
                    "Katalog produktů",
                    "Synchronizace byla stornována. Již propojené položky zůstaly bezpečně uložené.",
                    parent=parent,
                )
            return M.messagebox.showerror(
                "Katalog produktů", "Synchronizaci se nepodařilo dokončit:\n\n" + str(exc), parent=parent
            )
        progress_win.destroy()
        refresh_all(state["scope_iid"])
        M.messagebox.showinfo(
            "Katalog produktů",
            f"Synchronizováno dokumentů: {result['documents']}\n"
            f"Propojeno položek: {result['items']}\nZbývá: {result['remaining']}",
            parent=parent,
        )

    def refresh_all(select_iid=None):
        refresh_manufacturers()
        refresh_structure(select_iid)
        refresh_products()

    M.ttk.Button(left_tools, text="Spravovat skupiny…", command=manage_structure).pack(side="left")
    M.ttk.Button(left_tools, text="Obnovit", command=lambda: refresh_all(state["scope_iid"])).pack(
        side="left", padx=4
    )

    M.ttk.Button(
        actions, text="Přesunout vybrané do označené skupiny", style="Accent.TButton",
        command=move_selected_here,
    ).pack(side="left")
    M.ttk.Button(actions, text="Přesunout jinam…", command=move_selected_elsewhere).pack(side="left", padx=4)
    M.ttk.Button(actions, text="Upravit produkt…", command=edit_selected).pack(side="left", padx=4)
    M.ttk.Button(actions, text="Zdroje a ceny…", command=show_sources).pack(side="left", padx=4)
    M.ttk.Button(actions, text="Dosynchronizovat katalog", command=sync_everything).pack(side="left", padx=(14, 4))
    M.ttk.Button(actions, text="Zrušit filtry", command=clear_filters).pack(side="right")

    context = M.tk.Menu(products, tearoff=False)
    context.add_command(label="Upravit produkt…", command=edit_selected)
    context.add_command(label="Zdroje a ceny…", command=show_sources)
    context.add_separator()
    context.add_command(label="Přesunout do označené skupiny", command=move_selected_here)
    context.add_command(label="Přesunout jinam…", command=move_selected_elsewhere)

    def popup(event):
        iid = products.identify_row(event.y)
        if iid and iid not in products.selection():
            products.selection_set(iid)
        try:
            context.tk_popup(event.x_root, event.y_root)
        finally:
            context.grab_release()

    structure.bind("<<TreeviewSelect>>", on_scope_change, add="+")
    products.bind("<<TreeviewSelect>>", update_selection_status, add="+")
    products.bind("<Double-1>", lambda _event: edit_selected(), add="+")
    products.bind("<Button-3>", popup, add="+")
    query.trace_add("write", schedule_products)
    manufacturer.trace_add("write", schedule_products)
    show_inactive.trace_add("write", lambda *_: refresh_all(state["scope_iid"]))
    prev_button.configure(
        command=lambda: (state.__setitem__("page", max(0, int(state["page"]) - 1)), refresh_products())
    )
    next_button.configure(
        command=lambda: (state.__setitem__("page", int(state["page"]) + 1), refresh_products())
    )

    initial_iid = (
        f"{_SCOPE_SUBGROUP_PREFIX}{int(subgroup_id)}" if subgroup_id else
        f"{_SCOPE_GROUP_PREFIX}{int(category_id)}" if category_id else _SCOPE_ALL
    )
    refresh_all(initial_iid)

    def initial_sync():
        try:
            result = product_catalog.sync_all_unlinked(M, max_documents=5)
        except Exception:
            return
        if result.get("items"):
            refresh_all(state["scope_iid"])
            status.set(status.get() + f" · při otevření propojeno {result['items']} položek")

    try:
        parent.after(80, initial_sync)
    except Exception:
        pass

    api = {
        "frame": outer,
        "structure_tree": structure,
        "product_tree": products,
        "refresh": refresh_all,
        "selected_scope": selected_scope,
        "move_selected_here": move_selected_here,
        "state": state,
    }
    try:
        parent._turto_product_workspace = api
    except Exception:
        pass
    return api


def open_product_catalog(M, app, category_id=None, subgroup_id=None) -> None:
    app = _root_app(app)
    try:
        grabbed = app.grab_current()
        if grabbed is not None:
            grabbed.grab_release()
    except Exception:
        pass
    win = M.tk.Toplevel(app)
    win.title("Katalog produktů")
    win.transient(app)
    M.enable_dialog_maximize(win, 1600, 880)
    build_product_workspace(M, app, win, category_id, subgroup_id, embedded=False)


def install(M) -> None:
    """Make this split workspace the one presentation owner of the catalogue."""
    if getattr(M, "_turto_product_workspace_v635", False):
        return
    product_catalog.open_product_catalog = open_product_catalog
    M.open_product_catalog = lambda app, category_id=None, subgroup_id=None: open_product_catalog(
        M, app, category_id, subgroup_id
    )
    try:
        M.App.open_product_catalog = lambda self, category_id=None, subgroup_id=None: open_product_catalog(
            M, self, category_id, subgroup_id
        )
    except Exception:
        pass
    M.build_product_workspace = lambda app, parent, category_id=None, subgroup_id=None, embedded=False: build_product_workspace(
        M, app, parent, category_id, subgroup_id, embedded
    )
    M._turto_product_workspace_v635 = True


__all__ = ["build_product_workspace", "open_product_catalog", "install"]
