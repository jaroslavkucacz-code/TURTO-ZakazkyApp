"""CRM-style workspace for browsing and moving catalogue products.

The stable catalogue data owner remains :mod:`product_catalog`. This module is
its single presentation owner: product groups form a navigation tree on the
left and the products belonging to the selected group/subgroup are shown on the
right. Only Ceníky and explicit manual products feed this catalogue; received
supplier offers remain independent commercial documents.
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
    limit: int = 250, offset: int = 0, sort_mode: str = "Skupina → podskupina → produkt",
):
    """Return one SQL-filtered page in the user-selected deterministic order."""
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
    sort_map = {
        "Skupina → podskupina → produkt": (
            "coalesce(category_sort,2147483647),category COLLATE CZECH,"
            "coalesce(subgroup_sort,2147483647),subgroup COLLATE CZECH,"
            "coalesce(nullif(trim(internal_name),''),source_name,'') COLLATE CZECH,id"
        ),
        "Interní označení A–Z": "coalesce(nullif(trim(internal_name),''),source_name,'') COLLATE CZECH,id",
        "Výrobce A–Z": "coalesce(nullif(trim(manufacturer_name),''),suppliers,'') COLLATE CZECH,source_name COLLATE CZECH,id",
        "Dodavatel A–Z": "suppliers COLLATE CZECH,source_name COLLATE CZECH,id",
        "Nákupní cena ↑": "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,current_price ASC,id",
        "Nákupní cena ↓": "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,current_price DESC,id",
        "Výsledná cena ↑": (
            "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,"
            "(current_price*(1+margin_pct/100.0)*(1-discount_pct/100.0)) ASC,id"
        ),
        "Výsledná cena ↓": (
            "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,"
            "(current_price*(1+margin_pct/100.0)*(1-discount_pct/100.0)) DESC,id"
        ),
    }
    order_sql = sort_map.get(str(sort_mode or ""), sort_map["Skupina → podskupina → produkt"])
    select_sql = """SELECT cp.id,cp.active,cp.category_id,cp.subgroup_id,
                          cp.manufacturer_name,cp.internal_code,cp.internal_name,
                          coalesce(c.name,'Nezařazeno') category,coalesce(sg.name,'') subgroup,
                          c.sort_order category_sort,sg.sort_order subgroup_sort,
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
                   """ + sql_from + " WHERE " + where_sql
    with M.db() as con:
        total = int(con.execute(
            "SELECT COUNT(*) " + sql_from + " WHERE " + where_sql, params
        ).fetchone()[0] or 0)
        rows = con.execute(
            "WITH product_rows AS (" + select_sql + ") SELECT * FROM product_rows ORDER BY " + order_sql +
            " LIMIT ? OFFSET ?",
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
            text=("Katalog se plní pouze z Ceníků nebo ručně založených výrobků. Vlevo vyberte skupinu "
                  "nebo podskupinu; produkty lze upravit dvojklikem nebo je myší přetáhnout přímo na cílovou skupinu."),
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
        left, text="Kliknutím filtrujete. Přetažením produktu sem změníte jeho zařazení.",
        style="PageSubtitle.TLabel", wraplength=340,
    ).grid(row=1, column=0, sticky="w", pady=(1, 6))

    structure_cols = ("Produktů", "Ceníků")
    structure = M.ttk.Treeview(
        left, columns=structure_cols, show="tree headings", selectmode="browse", height=24
    )
    structure.heading("#0", text="Skupina / podskupina")
    structure.column("#0", width=340, minwidth=220, anchor="w", stretch=True)
    for col, width in (("Produktů", 72), ("Ceníků", 62)):
        structure.heading(col, text=col)
        structure.column(col, width=width, minwidth=55, anchor="e", stretch=False)
    structure.grid(row=2, column=0, sticky="nsew")
    structure_scroll = M.ttk.Scrollbar(left, orient="vertical", command=structure.yview)
    structure_scroll.grid(row=2, column=1, sticky="ns")
    structure.configure(yscrollcommand=structure_scroll.set)
    try:
        structure.tag_configure("drop_target", background="#dcecff", foreground="#17324a")
    except Exception:
        pass

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
    filters.columnconfigure(2, weight=2)
    query = M.tk.StringVar()
    manufacturer = M.tk.StringVar()
    show_inactive = M.tk.BooleanVar(value=False)
    sort_options = (
        "Skupina → podskupina → produkt", "Interní označení A–Z", "Výrobce A–Z", "Dodavatel A–Z",
        "Nákupní cena ↑", "Nákupní cena ↓", "Výsledná cena ↑", "Výsledná cena ↓",
    )
    try:
        active_user = M.get_setting("active_user", "")
        stored_sort = M.get_user_setting(active_user, "catalog_product_sort_mode", sort_options[0])
    except Exception:
        active_user = ""
        stored_sort = sort_options[0]
    sort_mode = M.tk.StringVar(value=stored_sort if stored_sort in sort_options else sort_options[0])
    for col, label in enumerate((
        "Hledat produkt, interní kód nebo kód dodavatele", "Výrobce / dodavatel", "Řazení",
    )):
        M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
    M.ttk.Entry(filters, textvariable=query).grid(row=1, column=0, sticky="ew", padx=(0, 6))
    manufacturer_box = M.AutocompleteEntry(filters, textvariable=manufacturer, values=[])
    manufacturer_box.grid(row=1, column=1, sticky="ew", padx=(0, 6))
    M.safe_combobox(filters, textvariable=sort_mode, values=sort_options, state="readonly").grid(
        row=1, column=2, sticky="ew", padx=(0, 8)
    )
    M.ttk.Checkbutton(filters, text="Zobrazit neaktivní", variable=show_inactive).grid(
        row=1, column=3, sticky="w"
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
        "Marže", "Sleva", "Výsledná cena", "Ceníků",
    )
    widths = (120, 230, 165, 175, 135, 290, 230, 250, 125, 68, 68, 125, 65)
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
        "last_move": None,
        "drag_source": None,
        "drop_target": None,
        "drag_started": False,
        "inactive_scopes": set(),
    }

    def scope_for_iid(iid) -> dict:
        scope = _scope_from_iid(M, str(iid or _SCOPE_ALL))
        if scope["iid"] in state.get("inactive_scopes", set()):
            scope = dict(scope)
            scope["assignable"] = False
            scope["label"] = f"{scope['label']} (neaktivní)"
        return scope

    def selected_scope() -> dict:
        selection = structure.selection()
        iid = str(selection[0]) if selection else str(state["scope_iid"])
        return scope_for_iid(iid)

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
        state["inactive_scopes"] = set()
        structure.insert(
            "", "end", iid=_SCOPE_ALL, text="Všechny produkty",
            values=(totals["product_count"], totals["list_count"]),
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
            group_active = bool(group_row["active"])
            structure.insert(
                "", "end", iid=group_iid, text=group_row["name"],
                values=(group_row["product_count"], group_row["list_count"]),
                open=(group_iid in opened or selected_category_id == group_id),
                tags=("status_cancel",) if not group_active else (),
            )
            no_subgroup_iid = f"{_SCOPE_NO_SUBGROUP_PREFIX}{group_id}"
            structure.insert(
                group_iid, "end", iid=no_subgroup_iid,
                text=categories.NO_SUBGROUP, values=(group_row["no_subgroup_count"], "", ""),
                tags=("status_cancel",) if not group_active else (),
            )
            if not group_active:
                state["inactive_scopes"].update((group_iid, no_subgroup_iid))
            for subgroup_row in by_group.get(group_id, []):
                subgroup_iid = f"{_SCOPE_SUBGROUP_PREFIX}{subgroup_row['id']}"
                subgroup_active = group_active and bool(subgroup_row["active"])
                structure.insert(
                    group_iid, "end", iid=subgroup_iid, text=subgroup_row["name"],
                    values=(subgroup_row["product_count"], subgroup_row["list_count"]),
                    tags=("status_cancel",) if not subgroup_active else (),
                )
                if not subgroup_active:
                    state["inactive_scopes"].add(subgroup_iid)
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
            int(state["page_size"]), offset, sort_mode.get(),
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
                    row["price_lists"],
                ),
                tags=("status_cancel",) if not row["active"] else (),
            )
        start = offset + 1 if total else 0
        end = min(total, offset + len(rows))
        remaining = product_catalog.count_unlinked(M)
        extra = f" · {remaining} dosud nespojených položek Ceníků" if remaining else ""
        status.set(f"Zobrazeno {start}–{end} z {total}{extra}")
        scope_summary.set(
            f"Produktů: {summary['products']} · Výrobců: {summary['manufacturers']} · "
            f"Vazeb na Ceníky: {summary['list_links']}"
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
        count = len(_selected_product_ids(products))
        selection_status.set(
            f"Vybráno: {count}" + (" · přetáhněte na skupinu vlevo" if count else "")
        )

    def edit_selected():
        ids = _selected_product_ids(products)
        if len(ids) != 1:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte právě jeden produkt.", parent=parent)
        product_catalog._edit_product(M, app, parent, ids[0], lambda: refresh_all(state["scope_iid"]))

    def snapshot_taxonomy(ids):
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        with M.db() as con:
            rows = con.execute(
                f"SELECT id,category_id,subgroup_id FROM catalog_products WHERE id IN ({marks})", ids
            ).fetchall()
        return [
            (int(row["id"]), int(row["category_id"]) if row["category_id"] else None,
             int(row["subgroup_id"]) if row["subgroup_id"] else None)
            for row in rows
        ]

    def select_moved(ids):
        found = []
        for product_id in ids:
            iid = f"cp{int(product_id)}"
            if products.exists(iid):
                found.append(iid)
        if found:
            products.selection_set(found)
            products.see(found[0])
            update_selection_status()

    def move_to_scope(target_scope: dict, confirm: bool = True, source: str = "button"):
        ids = _selected_product_ids(products)
        if not ids:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte jeden nebo více produktů.", parent=parent)
        if not target_scope.get("assignable"):
            return M.messagebox.showinfo(
                "Katalog produktů",
                "Jako cíl vyberte vlevo konkrétní skupinu, podskupinu, „Bez podskupiny“ nebo „Nezařazené“.",
                parent=parent,
            )
        before = snapshot_taxonomy(ids)
        target = (target_scope.get("category_id"), target_scope.get("subgroup_id"))
        if before and all((category_id, subgroup_id) == target for _pid, category_id, subgroup_id in before):
            status.set(f"Vybrané produkty už jsou v: {target_scope['label']}")
            return
        if confirm and not M.messagebox.askyesno(
            "Přesunout produkty",
            f"Přesunout vybrané produkty ({len(ids)}) do:\n\n{target_scope['label']}?\n\n"
            "Změna se automaticky projeví ve všech propojených Ceníkách. Přijaté nabídky zůstanou beze změny.",
            parent=parent,
        ):
            return
        product_catalog.set_product_taxonomy(
            M, ids, target_scope.get("category_id"), target_scope.get("subgroup_id")
        )
        state["last_move"] = {
            "rows": before,
            "label": target_scope["label"],
            "ids": list(ids),
        }
        undo_button.state(["!disabled"])
        product_catalog._invalidate(app)
        refresh_all(target_scope["iid"])
        select_moved(ids)
        verb = "Přetaženo" if source == "drag" else "Přesunuto"
        status.set(f"{verb} produktů: {len(ids)} → {target_scope['label']} · poslední přesun lze vrátit")

    def undo_last_move():
        move = state.get("last_move")
        if not move:
            return
        grouped: dict[tuple[object, object], list[int]] = {}
        for product_id, category_id, subgroup_id in move["rows"]:
            grouped.setdefault((category_id, subgroup_id), []).append(product_id)
        for (category_id, subgroup_id), ids in grouped.items():
            product_catalog.set_product_taxonomy(M, ids, category_id, subgroup_id)
        restored_ids = [row[0] for row in move["rows"]]
        first = move["rows"][0] if move["rows"] else (None, None, None)
        first_scope = (
            f"{_SCOPE_SUBGROUP_PREFIX}{first[2]}" if first[2] else
            f"{_SCOPE_NO_SUBGROUP_PREFIX}{first[1]}" if first[1] else _SCOPE_UNASSIGNED
        )
        state["last_move"] = None
        undo_button.state(["disabled"])
        product_catalog._invalidate(app)
        refresh_all(first_scope)
        select_moved(restored_ids)
        status.set(f"Poslední přesun byl vrácen · obnoveno produktů: {len(restored_ids)}")

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
        move_to_scope(_scope_from_iid(M, target_iid), confirm=False)

    def clear_drop_target():
        iid = state.get("drop_target")
        if iid and structure.exists(iid):
            tags = tuple(tag for tag in structure.item(iid, "tags") if tag != "drop_target")
            structure.item(iid, tags=tags)
        state["drop_target"] = None
        try:
            structure.configure(cursor="")
            products.configure(cursor="")
        except Exception:
            pass

    def mark_drop_target(iid):
        if iid == state.get("drop_target"):
            return
        clear_drop_target()
        scope = scope_for_iid(iid)
        if iid and structure.exists(iid) and scope.get("assignable"):
            tags = tuple(structure.item(iid, "tags"))
            structure.item(iid, tags=tags + (() if "drop_target" in tags else ("drop_target",)))
            state["drop_target"] = iid
            try:
                structure.configure(cursor="fleur")
                products.configure(cursor="fleur")
            except Exception:
                pass

    def on_product_drag_press(event):
        iid = products.identify_row(event.y)
        current = tuple(products.selection())
        preserve_multi = bool(iid and iid in current and len(current) > 1)
        if iid and iid not in current:
            products.selection_set(iid)
        if iid:
            products.focus(iid)
        state["drag_source"] = iid if iid else None
        state["drag_started"] = False
        clear_drop_target()
        if preserve_multi:
            return "break"

    def on_product_drag_motion(event):
        if not state.get("drag_source") or not _selected_product_ids(products):
            return
        state["drag_started"] = True
        x = event.x_root - structure.winfo_rootx()
        y = event.y_root - structure.winfo_rooty()
        candidate = None
        height = structure.winfo_height()
        if 0 <= x < structure.winfo_width() and 0 <= y < height:
            if y < 26:
                structure.yview_scroll(-1, "units")
            elif y > height - 26:
                structure.yview_scroll(1, "units")
            candidate = structure.identify_row(y)
        mark_drop_target(candidate)

    def on_product_drag_release(_event):
        target_iid = state.get("drop_target")
        started = bool(state.get("drag_started"))
        clear_drop_target()
        state.update(drag_source=None, drag_started=False)
        if started and target_iid:
            move_to_scope(scope_for_iid(target_iid), confirm=False, source="drag")

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
        progress_win.title("Synchronizace Ceníků do katalogu")
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
            f"Synchronizováno Ceníků: {result['documents']}\n"
            f"Propojeno položek Ceníků: {result['items']}\nZbývá: {result['remaining']}",
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
    undo_button = M.ttk.Button(actions, text="↶ Vrátit poslední přesun", command=undo_last_move)
    undo_button.pack(side="left", padx=(10, 4))
    undo_button.state(["disabled"])
    M.ttk.Button(actions, text="Upravit produkt…", command=edit_selected).pack(side="left", padx=4)
    M.ttk.Button(actions, text="Zdroje a ceny…", command=show_sources).pack(side="left", padx=4)
    M.ttk.Button(actions, text="Dosynchronizovat Ceníky", command=sync_everything).pack(side="left", padx=(14, 4))
    M.ttk.Button(actions, text="Zrušit filtry", command=clear_filters).pack(side="right")

    context = M.tk.Menu(products, tearoff=False)
    context.add_command(label="Upravit produkt…", command=edit_selected)
    context.add_command(label="Zdroje a ceny…", command=show_sources)
    context.add_separator()
    context.add_command(label="Přesunout do označené skupiny", command=move_selected_here)
    context.add_command(label="Přesunout jinam…", command=move_selected_elsewhere)
    context.add_command(label="Vrátit poslední přesun", command=undo_last_move)

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
    products.bind("<Return>", lambda _event: edit_selected(), add="+")
    products.bind("<F2>", lambda _event: edit_selected(), add="+")
    products.bind("<Button-3>", popup, add="+")
    products.bind("<ButtonPress-1>", on_product_drag_press, add="+")
    products.bind("<B1-Motion>", on_product_drag_motion, add="+")
    products.bind("<ButtonRelease-1>", on_product_drag_release, add="+")
    query.trace_add("write", schedule_products)
    manufacturer.trace_add("write", schedule_products)

    def on_sort_changed(*_):
        try:
            M.set_user_setting(active_user, "catalog_product_sort_mode", sort_mode.get())
        except Exception:
            pass
        schedule_products()

    sort_mode.trace_add("write", on_sort_changed)
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
            status.set(status.get() + f" · při otevření propojeno {result['items']} položek Ceníků")

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
        "undo_last_move": undo_last_move,
        "sort_mode": sort_mode,
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
    if getattr(M, "_turto_product_workspace_v639", False):
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
    M._turto_product_workspace_v639 = True


__all__ = ["build_product_workspace", "open_product_catalog", "install"]
