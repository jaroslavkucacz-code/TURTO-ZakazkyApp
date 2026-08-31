"""Unified CRM presentation for supplier offers and price lists.

The data owners remain the existing offer, price-list and product-catalog
services.  This module is the single final presentation owner for the two
commercial workspaces: it replaces the accumulated page wrappers with direct
builders and SQL-first refresh functions.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta

from . import categories, product_catalog

EXPIRING_DAYS = 30

_PRICE_TAGS = {
    "price_current": {"background": "#d8eadc", "foreground": "#244c2d"},
    "price_future": {"background": "#dce9f4", "foreground": "#203d55"},
    "price_expiring": {"background": "#f6e7b5", "foreground": "#5b4308"},
    "price_review": {"background": "#f3d4ae", "foreground": "#65350a"},
    "price_expired": {"background": "#edc8c8", "foreground": "#6c2020"},
    "price_archived": {"background": "#dfe3e6", "foreground": "#515960"},
}

_OFFER_TAGS = {
    "offer_archived": {"background": "#dfe3e6", "foreground": "#515960"},
    "offer_unassigned": {"background": "#f7e7b2", "foreground": "#5b4308"},
    "offer_uncategorized": {"background": "#f4d8b8", "foreground": "#65350a"},
    "offer_pricelist": {"background": "#dce9f4", "foreground": "#203d55"},
}


def _exists(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return widget is not None


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return float(default)


def _count_text(value) -> str:
    try:
        return f"{int(value or 0):,}".replace(",", " ")
    except Exception:
        return "0"


def _format_number(value, decimals: int = 2) -> str:
    try:
        number = float(value or 0)
    except Exception:
        number = 0.0
    return f"{number:,.{int(decimals)}f}".replace(",", " ").replace(".", ",")


def _format_amount(value, currency: str = "CZK") -> str:
    return f"{_format_number(value)} {currency or 'CZK'}"


def _days_text(value: int) -> str:
    value = abs(int(value))
    if value == 1:
        return "1 den"
    if 2 <= value <= 4:
        return f"{value} dny"
    return f"{value} dní"


def _needs_review(value) -> bool:
    text = str(value or "").strip().casefold()
    return "ocr" in text or "kontrol" in text or text.startswith("bez")


def _validity_text(M, valid_from, valid_to, today=None) -> str:
    today = today or date.today()
    starts = _parse_iso(valid_from)
    ends = _parse_iso(valid_to)
    if starts and starts > today:
        return f"začíná za {_days_text((starts - today).days)}"
    if ends:
        delta = (ends - today).days
        if delta < 0:
            return f"{_days_text(-delta)} po platnosti"
        if delta == 0:
            return "končí dnes"
        if delta <= EXPIRING_DAYS:
            return f"končí za {_days_text(delta)}"
        return f"do {M.fmt_date(ends.isoformat())}"
    return "bez omezení"


def _price_status(row, today=None) -> str:
    today = today or date.today()
    if int(row["archived"] or 0):
        return "price_archived"
    if _needs_review(row["parse_status"]):
        return "price_review"
    starts = _parse_iso(row["valid_from"])
    ends = _parse_iso(row["valid_to"])
    if not starts:
        return "price_review"
    if starts > today:
        return "price_future"
    if ends and ends < today:
        return "price_expired"
    if ends and 0 <= (ends - today).days <= EXPIRING_DAYS:
        return "price_expiring"
    return "price_current"


def _make_tree(M, app, parent, columns, widths, anchors=None, selectmode="extended"):
    wrap = M.ttk.Frame(parent)
    wrap.pack(fill="both", expand=True)
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    tree = M.ttk.Treeview(wrap, columns=columns, show="headings", selectmode=selectmode)
    anchors = anchors or {}
    sorter = getattr(app, "sort_tree", None)
    for column, width in zip(columns, widths):
        if callable(sorter):
            tree.heading(column, text=column, command=lambda col=column: sorter(tree, col))
        else:
            tree.heading(column, text=column)
        tree.column(
            column, width=width, minwidth=min(90, max(45, width // 2)),
            anchor=anchors.get(column, "w"), stretch=False,
        )
    tree.grid(row=0, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    return tree


def _configure_tags(tree, definitions) -> None:
    for name, options in definitions.items():
        try:
            tree.tag_configure(name, **options)
        except Exception:
            pass


def _bind_click(widget, callback) -> None:
    try:
        widget.configure(cursor="hand2")
    except Exception:
        pass
    try:
        widget.bind("<Button-1>", lambda _event: callback(), add="+")
    except Exception:
        pass
    try:
        for child in widget.winfo_children():
            _bind_click(child, callback)
    except Exception:
        pass


def _metric_cards(M, parent, definitions, on_click):
    panel = M.ttk.Frame(parent, style="App.TFrame")
    panel.pack(fill="x", pady=(0, 7))
    variables = {}
    for index, (label, key, target) in enumerate(definitions):
        card = M.ttk.Frame(panel, style="Card.TFrame", padding=(12, 8))
        card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0))
        panel.columnconfigure(index, weight=1)
        M.ttk.Label(card, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        variable = M.tk.StringVar(value="—")
        variables[key] = variable
        M.ttk.Label(card, textvariable=variable, font=("Calibri", 16, "bold")).pack(anchor="w")
        if target is not None:
            _bind_click(card, lambda value=target: on_click(value))
    return variables


def _set_display_columns(tree, profiles, mode: str) -> None:
    columns = tuple(tree["columns"])
    selected = tuple(profiles.get(mode) or profiles.get("Přehled") or columns)
    selected = tuple(column for column in selected if column in columns)
    try:
        tree.configure(displaycolumns=selected)
    except Exception:
        pass


def _separator(M, parent):
    try:
        M.ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=8)
    except Exception:
        pass


def _run_after_invalidation(app, callback, *, prices=False, offers=False):
    if prices:
        app._commercial_price_summary_cache = None
        app._price_filter_cache = None
        app._price_taxonomy_cache = None
    if offers:
        app._commercial_offer_summary_cache = None
    return callback()


# ---------------------------------------------------------------------------
# CENÍKY


def _price_filter_values(M, app):
    selected_group = getattr(app, "price_category_filter", None)
    group_value = selected_group.get().strip() if selected_group is not None else ""
    cache = getattr(app, "_price_filter_cache", None)
    cache_key = group_value
    if cache and time.monotonic() - cache[0] < 30 and cache[2] == cache_key:
        return cache[1]
    with M.db() as con:
        suppliers = [row[0] for row in con.execute(
            """SELECT DISTINCT coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
               FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE trim(coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),''))<>''
               ORDER BY supplier COLLATE CZECH"""
        ).fetchall()]
        ranges = [row[0] for row in con.execute(
            """SELECT DISTINCT trim(product_group) FROM price_lists
               WHERE trim(coalesce(product_group,''))<>'' ORDER BY trim(product_group) COLLATE CZECH"""
        ).fetchall()]
    group_names = [str(row["name"]) for row in categories.list_categories(M)]
    category_id = categories.category_id_by_name(M, group_value) if group_value and group_value != "Všechny" else None
    subgroup_names = [str(row["name"]) for row in categories.list_subgroups(M, category_id)]
    result = (suppliers, ranges, group_names, subgroup_names)
    app._price_filter_cache = (time.monotonic(), result, cache_key)
    return result


def _price_summary_values(M):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=EXPIRING_DAYS)).isoformat()
    review = (
        "(trim(coalesce(p.valid_from,''))='' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
    )
    with M.db() as con:
        row = con.execute(
            f"""SELECT
              (SELECT COUNT(*) FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                WHERE i.active=1 AND p.archived=0 AND trim(coalesce(p.valid_from,''))<>''
                  AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                  AND NOT {review}) items,
              (SELECT COUNT(*) FROM price_lists p
                WHERE p.archived=0 AND trim(coalesce(p.valid_from,''))<>'' AND p.valid_from<=?
                  AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?) AND NOT {review}) active,
              (SELECT COUNT(*) FROM price_lists p WHERE p.archived=0 AND {review}) review,
              (SELECT COUNT(*) FROM price_lists p
                WHERE p.archived=0 AND trim(coalesce(p.valid_from,''))<>'' AND p.valid_from<=?
                  AND trim(coalesce(p.valid_to,''))<>'' AND p.valid_to>=? AND p.valid_to<=?
                  AND NOT {review}) expiring,
              (SELECT COUNT(*) FROM price_lists p
                WHERE p.archived=0 AND trim(coalesce(p.valid_to,''))<>'' AND p.valid_to<?) expired,
              (SELECT COUNT(*) FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                WHERE i.active=1 AND p.archived=0 AND trim(coalesce(p.valid_from,''))<>''
                  AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                  AND NOT {review} AND coalesce(cp.category_id,i.category_id) IS NULL) unassigned
            """,
            (today, today, today, today, today, today, soon, today, today, today),
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _refresh_price_metrics(M, app, force=False):
    variables = getattr(app, "price_metric_vars", None)
    if not variables:
        return
    now = time.monotonic()
    cache = getattr(app, "_commercial_price_summary_cache", None)
    if force or not cache or now - cache[0] > 5:
        values = _price_summary_values(M)
        app._commercial_price_summary_cache = (now, values)
    else:
        values = cache[1]
    for key, variable in variables.items():
        variable.set(_count_text(values.get(key)))


def _price_quick_view(M, app, target: str):
    if not hasattr(app, "price_notebook"):
        return
    if target == "Platné ceny":
        app.price_notebook.select(0)
        app.price_q.set("")
        app.price_supplier_filter.set("")
        app.price_category_filter.set("Všechny")
        app.price_subgroup_filter.set("")
        app.price_group_filter.set("")
        app.price_price_scope.set("Ověřené")
    elif target == "Nezařazené ceny":
        app.price_notebook.select(0)
        app.price_q.set("")
        app.price_supplier_filter.set("")
        app.price_category_filter.set("Všechny")
        app.price_subgroup_filter.set("")
        app.price_group_filter.set("")
        app.price_price_scope.set("Nezařazené")
    else:
        app.price_notebook.select(1)
        app.price_evidence_q.set("")
        app.price_evidence_supplier.set("")
        app.price_evidence_category.set("Všechny")
        app.price_list_show_archived.set(target == "Archivované")
        app.price_evidence_status.set(target)
    app.price_page = 0
    app.price_evidence_page = 0
    schedule_price_refresh(M, app, 0)


def _toggle_price_advanced(app):
    visible = bool(app.price_advanced_visible.get())
    app.price_advanced_visible.set(not visible)
    if visible:
        app.price_advanced_frame.pack_forget()
        app.price_advanced_button.configure(text="Další filtry ▾")
    else:
        app.price_advanced_frame.pack(fill="x", pady=(0, 6), after=app.price_primary_filters)
        app.price_advanced_button.configure(text="Méně filtrů ▴")


def _price_mode_changed(M, app):
    mode = app.price_column_mode.get() or "Přehled"
    try:
        user = M.get_setting("active_user", "")
        M.set_user_setting(user, "price_column_mode", mode)
    except Exception:
        pass
    _set_display_columns(app.price_current_tree, app.price_column_profiles, mode)


def _price_sort_sql(app) -> str:
    variable = getattr(app, "price_sort_mode", None)
    mode = variable.get() if variable is not None else "Skupina → podskupina → produkt"
    mapping = {
        "Skupina → podskupina → produkt": (
            "category COLLATE CZECH,subgroup COLLATE CZECH,"
            "coalesce(nullif(trim(internal_name),''),name,description,'') COLLATE CZECH,supplier COLLATE CZECH,item_id"
        ),
        "Interní označení A–Z": (
            "coalesce(nullif(trim(internal_name),''),name,description,'') COLLATE CZECH,supplier COLLATE CZECH,item_id"
        ),
        "Výrobce A–Z": "manufacturer COLLATE CZECH,name COLLATE CZECH,item_id",
        "Dodavatel A–Z": "supplier COLLATE CZECH,name COLLATE CZECH,item_id",
        "Nákupní cena ↑": (
            "CASE WHEN normalized_unit_price IS NULL THEN 1 ELSE 0 END,normalized_unit_price ASC,"
            "name COLLATE CZECH,item_id"
        ),
        "Nákupní cena ↓": (
            "CASE WHEN normalized_unit_price IS NULL THEN 1 ELSE 0 END,normalized_unit_price DESC,"
            "name COLLATE CZECH,item_id"
        ),
        "Výsledná cena ↑": (
            "CASE WHEN normalized_unit_price IS NULL THEN 1 ELSE 0 END,"
            "(normalized_unit_price*(1+margin_pct/100.0)*(1-sales_discount_pct/100.0)) ASC,item_id"
        ),
        "Výsledná cena ↓": (
            "CASE WHEN normalized_unit_price IS NULL THEN 1 ELSE 0 END,"
            "(normalized_unit_price*(1+margin_pct/100.0)*(1-sales_discount_pct/100.0)) DESC,item_id"
        ),
        "Platnost končí nejdříve": (
            "CASE WHEN trim(coalesce(valid_to,''))='' THEN 1 ELSE 0 END,valid_to ASC,"
            "category COLLATE CZECH,name COLLATE CZECH,item_id"
        ),
    }
    return mapping.get(mode, mapping["Skupina → podskupina → produkt"])


def _select_price_sort(app, ascending: str, descending: str | None = None) -> None:
    """Use a global SQL sort when a meaningful price-table heading is clicked."""
    current = app.price_sort_mode.get() if hasattr(app, "price_sort_mode") else ""
    target = descending if descending and current == ascending else ascending
    app.price_sort_mode.set(target)


def _price_scope_from_iid(M, iid: str) -> dict:
    text = str(iid or "pt_all")
    if text == "pt_unassigned":
        return {
            "iid": text, "category_id": None, "subgroup_id": None,
            "only_without_subgroup": False, "unassigned": True,
            "assignable": True, "label": categories.UNASSIGNED,
        }
    for prefix, only_without in (("pt_s", False), ("pt_n", True), ("pt_g", False)):
        value = text[len(prefix):] if text.startswith(prefix) else ""
        if not value.isdigit():
            continue
        row_id = int(value)
        if prefix == "pt_s":
            subgroup_id = row_id
            category_id = categories.subgroup_parent_id(M, subgroup_id)
            label = categories.taxonomy_path(M, category_id, subgroup_id)
        else:
            category_id = row_id
            subgroup_id = None
            label = categories.category_name(M, category_id)
            if only_without:
                label = f"{label} › {categories.NO_SUBGROUP}"
        return {
            "iid": text, "category_id": category_id, "subgroup_id": subgroup_id,
            "only_without_subgroup": only_without, "unassigned": False,
            "assignable": True, "label": label,
        }
    return {
        "iid": "pt_all", "category_id": None, "subgroup_id": None,
        "only_without_subgroup": False, "unassigned": False,
        "assignable": False, "label": "Všechny aktuální ceny",
    }


def _price_scope_iid_from_filters(M, app) -> str:
    scope_var = getattr(app, "price_price_scope", None)
    if scope_var is not None and scope_var.get() == "Nezařazené":
        return "pt_unassigned"
    category_var = getattr(app, "price_category_filter", None)
    subgroup_var = getattr(app, "price_subgroup_filter", None)
    group_name = category_var.get().strip() if category_var is not None else ""
    subgroup_name = subgroup_var.get().strip() if subgroup_var is not None else ""
    category_id = categories.category_id_by_name(M, group_name) if group_name and group_name != "Všechny" else None
    if category_id and subgroup_name:
        subgroup_id = categories.subgroup_id_by_name(M, subgroup_name, category_id)
        if subgroup_id:
            return f"pt_s{subgroup_id}"
    no_subgroup = getattr(app, "price_taxonomy_no_subgroup", None)
    if category_id and no_subgroup is not None and bool(no_subgroup.get()):
        return f"pt_n{category_id}"
    if category_id:
        return f"pt_g{category_id}"
    return "pt_all"


def _refresh_price_taxonomy(M, app, force=False) -> None:
    tree = getattr(app, "price_taxonomy_tree", None)
    if tree is None or not _exists(tree):
        return
    try:
        from ..common import _iso_date
        effective = _iso_date(app.price_effective_date.get()) or date.today().isoformat()
    except Exception:
        effective = date.today().isoformat()
    review_condition = (
        "(lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
    )
    scope_var = getattr(app, "price_price_scope", None)
    view_scope = scope_var.get() if scope_var is not None else "Ověřené"
    review_sql = review_condition if view_scope == "Ke kontrole" else (
        "1=1" if view_scope == "Všechny včetně kontroly" else f"NOT {review_condition}"
    )
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    cache_key = (effective, view_scope)
    now = time.monotonic()
    cache = getattr(app, "_price_taxonomy_cache", None)
    if force or not cache or cache[1] != cache_key or now - cache[0] > 12:
        with M.db() as con:
            count_rows = con.execute(
                f"""WITH candidates AS (
                   SELECT coalesce(cp.category_id,i.category_id,p.category_id) category_id,
                          coalesce(cp.subgroup_id,i.subgroup_id) subgroup_id,
                          DENSE_RANK() OVER (
                            PARTITION BY lower({supplier_expr}),lower(coalesce(p.branch,'')),lower(coalesce(p.product_group,'')),
                              lower(coalesce(nullif(i.product_code,''),nullif(i.item_key,''),i.name,'')),
                              lower(coalesce(nullif(i.name,''),i.description,'')),lower(coalesce(i.condition_text,'')),
                              round(coalesce(i.minimum_qty,0),8),round(coalesce(i.price_basis_qty,0),8),
                              round(coalesce(i.package_qty,0),8),lower(coalesce(i.unit,''))
                            ORDER BY p.valid_from DESC,p.id DESC
                          ) list_rank
                     FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                     LEFT JOIN companies c ON c.id=p.supplier_company_id
                     LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                    WHERE i.active=1 AND p.archived=0 AND trim(coalesce(p.valid_from,''))<>''
                      AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                      AND {review_sql}
                 )
                 SELECT category_id,subgroup_id,COUNT(*) price_count
                   FROM candidates WHERE list_rank=1 GROUP BY category_id,subgroup_id""",
                (effective, effective),
            ).fetchall()
        exact_counts = {
            (int(row["category_id"]) if row["category_id"] else None,
             int(row["subgroup_id"]) if row["subgroup_id"] else None): int(row["price_count"] or 0)
            for row in count_rows
        }
        app._price_taxonomy_cache = (now, cache_key, exact_counts)
    else:
        exact_counts = cache[2]
    groups = categories.list_categories(M)
    subgroups = categories.list_subgroups(M)
    group_counts: dict[int, int] = {}
    for (category_id, _subgroup_id), value in exact_counts.items():
        if category_id:
            group_counts[category_id] = group_counts.get(category_id, 0) + value
    total = sum(exact_counts.values())
    unassigned = sum(value for (category_id, _subgroup_id), value in exact_counts.items() if not category_id)
    opened = {iid for iid in tree.get_children("") if tree.item(iid, "open")}
    selected_iid = _price_scope_iid_from_filters(M, app)
    for iid in tree.get_children(""):
        tree.delete(iid)
    tree.insert("", "end", iid="pt_all", text="Všechny aktuální ceny", values=(total,), open=True)
    tree.insert(
        "", "end", iid="pt_unassigned", text="Nezařazené", values=(unassigned,),
        tags=("status_wait",),
    )
    by_group: dict[int, list] = {}
    for subgroup in subgroups:
        by_group.setdefault(int(subgroup["category_id"]), []).append(subgroup)
    selected_scope = _price_scope_from_iid(M, selected_iid)
    selected_category = selected_scope.get("category_id")
    for group in groups:
        group_id = int(group["id"])
        group_iid = f"pt_g{group_id}"
        tree.insert(
            "", "end", iid=group_iid, text=group["name"], values=(group_counts.get(group_id, 0),),
            open=(group_iid in opened or selected_category == group_id),
        )
        tree.insert(
            group_iid, "end", iid=f"pt_n{group_id}", text=categories.NO_SUBGROUP,
            values=(exact_counts.get((group_id, None), 0),),
        )
        for subgroup in by_group.get(group_id, []):
            subgroup_id = int(subgroup["id"])
            tree.insert(
                group_iid, "end", iid=f"pt_s{subgroup_id}", text=subgroup["name"],
                values=(exact_counts.get((group_id, subgroup_id), 0),),
            )
    if not tree.exists(selected_iid):
        selected_iid = "pt_all"
    app._price_taxonomy_syncing = True
    try:
        tree.selection_set(selected_iid)
        tree.see(selected_iid)
    finally:
        app._price_taxonomy_syncing = False


def _apply_price_taxonomy_scope(M, app, target: dict, refresh=True) -> None:
    app._price_taxonomy_syncing = True
    try:
        if target.get("unassigned"):
            app.price_category_filter.set("Všechny")
            app.price_subgroup_filter.set("")
            app.price_taxonomy_no_subgroup.set(False)
            app.price_price_scope.set("Nezařazené")
        elif target.get("category_id"):
            app.price_category_filter.set(categories.category_name(M, target["category_id"]) or "Všechny")
            app.price_subgroup_filter.set(
                categories.subgroup_name(M, target.get("subgroup_id")) if target.get("subgroup_id") else ""
            )
            app.price_taxonomy_no_subgroup.set(bool(target.get("only_without_subgroup")))
            if app.price_price_scope.get() == "Nezařazené":
                app.price_price_scope.set("Ověřené")
        else:
            app.price_category_filter.set("Všechny")
            app.price_subgroup_filter.set("")
            app.price_taxonomy_no_subgroup.set(False)
            if app.price_price_scope.get() == "Nezařazené":
                app.price_price_scope.set("Ověřené")
    finally:
        app._price_taxonomy_syncing = False
    app.price_page = 0
    if refresh:
        schedule_price_refresh(M, app, 0)


def _on_price_taxonomy_select(M, app, *_):
    if getattr(app, "_price_taxonomy_syncing", False):
        return
    tree = getattr(app, "price_taxonomy_tree", None)
    selection = tree.selection() if tree is not None else ()
    if not selection:
        return
    selected_iid = str(selection[0])
    # Tree rebuilding queues <<TreeviewSelect>> after the guard is released.
    # Ignore it when the selected branch already represents the active filters.
    if selected_iid == _price_scope_iid_from_filters(M, app):
        return
    _apply_price_taxonomy_scope(M, app, _price_scope_from_iid(M, selected_iid))


def _selected_current_rows(app) -> list[dict]:
    tree = getattr(app, "price_current_tree", None)
    selection = tree.selection() if tree is not None else ()
    rows = []
    seen = set()
    for iid in selection:
        row = getattr(app, "price_current_row_data", {}).get(iid)
        if row and int(row.get("item_id") or 0) not in seen:
            rows.append(row)
            seen.add(int(row.get("item_id") or 0))
    return rows


def _move_current_to_scope(M, app, target: dict, confirm=True, source="button") -> None:
    rows = _selected_current_rows(app)
    if not rows:
        return M.messagebox.showinfo("Ceníky", "Vyberte jednu nebo více cen.", parent=app)
    if not target.get("assignable"):
        return M.messagebox.showinfo(
            "Ceníky", "Jako cíl vyberte konkrétní skupinu, podskupinu nebo Nezařazené.", parent=app
        )
    if confirm and not M.messagebox.askyesno(
        "Přesunout ceny",
        f"Přesunout vybrané ceny ({len(rows)}) do:\n\n{target['label']}?\n\n"
        "U propojených položek se změna promítne do stabilního katalogového produktu a všech jeho zdrojů.",
        parent=app,
    ):
        return
    product_ids = sorted({int(row["catalog_product_id"]) for row in rows if row.get("catalog_product_id")})
    item_ids = sorted({int(row["item_id"]) for row in rows if not row.get("catalog_product_id")})
    product_before = []
    item_before = []
    with M.db() as con:
        if product_ids:
            marks = ",".join("?" for _ in product_ids)
            product_before = [
                (int(row["id"]), int(row["category_id"]) if row["category_id"] else None,
                 int(row["subgroup_id"]) if row["subgroup_id"] else None)
                for row in con.execute(
                    f"SELECT id,category_id,subgroup_id FROM catalog_products WHERE id IN ({marks})", product_ids
                ).fetchall()
            ]
        if item_ids:
            marks = ",".join("?" for _ in item_ids)
            item_before = [
                (int(row["id"]), int(row["category_id"]) if row["category_id"] else None,
                 int(row["subgroup_id"]) if row["subgroup_id"] else None)
                for row in con.execute(
                    f"SELECT id,category_id,subgroup_id FROM price_list_items WHERE id IN ({marks})", item_ids
                ).fetchall()
            ]
    destination = (target.get("category_id"), target.get("subgroup_id"))
    if product_before and all((row[1], row[2]) == destination for row in product_before) and not item_before:
        app.price_current_status.set(f"Vybrané ceny už jsou v: {target['label']}")
        return
    if product_ids:
        product_catalog.set_product_taxonomy(M, product_ids, *destination)
    if item_ids:
        categories.set_item_taxonomy(M, "price_list_items", item_ids, *destination)
    app.price_last_taxonomy_move = {
        "products": product_before, "items": item_before,
        "target": target, "count": len(rows),
    }
    undo = getattr(app, "price_undo_move_button", None)
    if undo is not None:
        undo.state(["!disabled"])
    try:
        product_catalog._invalidate(app)
    except Exception:
        pass
    app._price_filter_cache = None
    app._commercial_price_summary_cache = None
    app._price_taxonomy_cache = None
    _apply_price_taxonomy_scope(M, app, target, refresh=False)
    _refresh_price_taxonomy(M, app, force=True)
    _refresh_current(M, app)
    verb = "Přetaženo" if source == "drag" else "Přesunuto"
    app.price_current_status.set(f"{verb} cen: {len(rows)} → {target['label']} · poslední přesun lze vrátit")


def _undo_current_move(M, app) -> None:
    move = getattr(app, "price_last_taxonomy_move", None)
    if not move:
        return
    product_groups: dict[tuple[object, object], list[int]] = {}
    for product_id, category_id, subgroup_id in move.get("products", []):
        product_groups.setdefault((category_id, subgroup_id), []).append(product_id)
    for (category_id, subgroup_id), ids in product_groups.items():
        product_catalog.set_product_taxonomy(M, ids, category_id, subgroup_id)
    item_groups: dict[tuple[object, object], list[int]] = {}
    for item_id, category_id, subgroup_id in move.get("items", []):
        item_groups.setdefault((category_id, subgroup_id), []).append(item_id)
    for (category_id, subgroup_id), ids in item_groups.items():
        categories.set_item_taxonomy(M, "price_list_items", ids, category_id, subgroup_id)
    original = None
    if move.get("products"):
        original = move["products"][0][1:]
    elif move.get("items"):
        original = move["items"][0][1:]
    app.price_last_taxonomy_move = None
    undo = getattr(app, "price_undo_move_button", None)
    if undo is not None:
        undo.state(["disabled"])
    try:
        product_catalog._invalidate(app)
    except Exception:
        pass
    app._price_filter_cache = None
    app._commercial_price_summary_cache = None
    app._price_taxonomy_cache = None
    if original:
        category_id, subgroup_id = original
        target_iid = f"pt_s{subgroup_id}" if subgroup_id else f"pt_n{category_id}" if category_id else "pt_unassigned"
        _apply_price_taxonomy_scope(M, app, _price_scope_from_iid(M, target_iid), refresh=False)
    _refresh_price_taxonomy(M, app, force=True)
    _refresh_current(M, app)
    app.price_current_status.set(f"Poslední přesun byl vrácen · obnoveno cen: {move.get('count', 0)}")


def _pick_current_taxonomy(M, app) -> None:
    rows = _selected_current_rows(app)
    if not rows:
        return M.messagebox.showinfo("Ceníky", "Vyberte jednu nebo více cen.", parent=app)
    first = rows[0]
    selected = categories.choose_taxonomy(
        M, app, "Přiřadit nebo přesunout vybrané ceny",
        first.get("resolved_category_id"), first.get("resolved_subgroup_id"),
    )
    if selected == "cancel":
        return
    category_id, subgroup_id = selected
    iid = f"pt_s{subgroup_id}" if subgroup_id else f"pt_n{category_id}" if category_id else "pt_unassigned"
    _move_current_to_scope(M, app, _price_scope_from_iid(M, iid), confirm=False)


def _edit_current_product(M, app) -> None:
    rows = _selected_current_rows(app)
    if len(rows) != 1:
        return M.messagebox.showinfo("Ceníky", "Pro přímou editaci vyberte právě jednu cenu.", parent=app)
    row = rows[0]
    product_id = row.get("catalog_product_id")
    if not product_id:
        return _pick_current_taxonomy(M, app)

    def saved():
        app._price_filter_cache = None
        app._price_taxonomy_cache = None
        app._commercial_price_summary_cache = None
        _refresh_price_taxonomy(M, app, force=True)
        _refresh_current(M, app)

    product_catalog._edit_product(M, app, app, int(product_id), saved)


def _clear_price_drop_target(app):
    tree = getattr(app, "price_taxonomy_tree", None)
    iid = getattr(app, "_price_drop_target", None)
    if tree is not None and iid and tree.exists(iid):
        tags = tuple(tag for tag in tree.item(iid, "tags") if tag != "drop_target")
        tree.item(iid, tags=tags)
    app._price_drop_target = None
    try:
        tree.configure(cursor="")
        app.price_current_tree.configure(cursor="")
    except Exception:
        pass


def _mark_price_drop_target(M, app, iid):
    if iid == getattr(app, "_price_drop_target", None):
        return
    _clear_price_drop_target(app)
    tree = getattr(app, "price_taxonomy_tree", None)
    target = _price_scope_from_iid(M, iid)
    if tree is not None and iid and tree.exists(iid) and target.get("assignable"):
        tags = tuple(tree.item(iid, "tags"))
        if "drop_target" not in tags:
            tree.item(iid, tags=tags + ("drop_target",))
        app._price_drop_target = iid
        try:
            tree.configure(cursor="fleur")
            app.price_current_tree.configure(cursor="fleur")
        except Exception:
            pass


def _on_price_drag_press(M, app, event):
    iid = app.price_current_tree.identify_row(event.y)
    current = tuple(app.price_current_tree.selection())
    preserve_multi = bool(iid and iid in current and len(current) > 1)
    if iid and iid not in current:
        app.price_current_tree.selection_set(iid)
    if iid:
        app.price_current_tree.focus(iid)
    app._price_drag_source = iid if iid else None
    app._price_drag_started = False
    _clear_price_drop_target(app)
    if preserve_multi:
        return "break"


def _on_price_drag_motion(M, app, event):
    tree = getattr(app, "price_taxonomy_tree", None)
    if tree is None or not getattr(app, "_price_drag_source", None) or not _selected_current_rows(app):
        return
    app._price_drag_started = True
    x = event.x_root - tree.winfo_rootx()
    y = event.y_root - tree.winfo_rooty()
    height = tree.winfo_height()
    iid = None
    if 0 <= x < tree.winfo_width() and 0 <= y < height:
        if y < 26:
            tree.yview_scroll(-1, "units")
        elif y > height - 26:
            tree.yview_scroll(1, "units")
        iid = tree.identify_row(y)
    _mark_price_drop_target(M, app, iid)


def _on_price_drag_release(M, app, _event):
    target_iid = getattr(app, "_price_drop_target", None)
    started = bool(getattr(app, "_price_drag_started", False))
    _clear_price_drop_target(app)
    app._price_drag_source = None
    app._price_drag_started = False
    if started and target_iid:
        _move_current_to_scope(M, app, _price_scope_from_iid(M, target_iid), confirm=False, source="drag")


def build_price_lists(M, app) -> None:
    from ..archive import price_list_archive_root
    from . import price_page

    page = app.tabs["pricelists"]
    for child in page.winfo_children():
        child.destroy()
    app.title_label(page, "Ceníky")
    M.ttk.Label(
        page,
        text="Aktuální nákupní ceny, platnost zdrojových dokumentů a obchodní pravidla na jednom místě.",
        style="PageSubtitle.TLabel",
    ).pack(anchor="w", pady=(0, 7))

    command = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    command.pack(fill="x", pady=(0, 7))
    M.ttk.Button(
        command, text="+ Importovat Ceník", style="Accent.TButton",
        command=lambda: _run_after_invalidation(app, app.import_price_list, prices=True),
    ).pack(side="left")

    def open_archive():
        root = price_list_archive_root()
        root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(root))

    M.ttk.Button(command, text="Otevřít archiv", command=open_archive).pack(side="left", padx=(6, 0))
    _separator(M, command)
    M.ttk.Button(command, text="Katalog produktů", command=lambda: product_catalog.open_product_catalog(M, app)).pack(side="left")
    M.ttk.Button(command, text="Skupiny a podskupiny", command=lambda: categories.manage_categories(M, app)).pack(side="left", padx=(6, 0))
    _separator(M, command)
    M.ttk.Button(
        command, text="Hromadná archivace",
        command=lambda: getattr(M, "open_bulk_archive_manager", lambda _app: None)(app),
    ).pack(side="left")
    M.ttk.Label(
        command, text="Fotografie se načítají až na vyžádání v detailu.", style="PageSubtitle.TLabel"
    ).pack(side="right")

    definitions = (
        ("Platných cen", "items", "Platné ceny"),
        ("Aktivní ceníky", "active", "Aktuální"),
        ("Končí do 30 dnů", "expiring", "Končí do 30 dnů"),
        ("Ke kontrole", "review", "Ke kontrole"),
        ("Po platnosti", "expired", "Po platnosti"),
        ("Nezařazených cen", "unassigned", "Nezařazené ceny"),
    )
    app.price_metric_vars = _metric_cards(
        M, page, definitions, lambda target: _price_quick_view(M, app, target)
    )

    notebook = M.ttk.Notebook(page)
    notebook.pack(fill="both", expand=True)
    app.price_notebook = notebook
    current = M.ttk.Frame(notebook, padding=8)
    evidence = M.ttk.Frame(notebook, padding=8)
    notebook.add(current, text="Aktuální ceny")
    notebook.add(evidence, text="Evidence ceníků")

    # Current prices ---------------------------------------------------------
    app.price_q = M.tk.StringVar()
    app.price_supplier_filter = M.tk.StringVar()
    app.price_category_filter = M.tk.StringVar(value="Všechny")
    app.price_subgroup_filter = M.tk.StringVar()
    app.price_group_filter = M.tk.StringVar()
    app.price_effective_date = M.tk.StringVar(value=date.today().isoformat())
    app.price_page_size = M.tk.StringVar(value="250")
    app.price_price_scope = M.tk.StringVar(value="Ověřené")
    app.price_taxonomy_no_subgroup = M.tk.BooleanVar(value=False)
    app.price_page = 0
    app.price_last_taxonomy_move = None
    app._price_taxonomy_syncing = False
    app._price_drag_source = None
    app._price_drag_started = False
    app._price_drop_target = None
    price_sort_options = (
        "Skupina → podskupina → produkt", "Interní označení A–Z", "Výrobce A–Z", "Dodavatel A–Z",
        "Nákupní cena ↑", "Nákupní cena ↓", "Výsledná cena ↑", "Výsledná cena ↓",
        "Platnost končí nejdříve",
    )
    try:
        user = M.get_setting("active_user", "")
        stored_mode = M.get_user_setting(user, "price_column_mode", "Přehled")
        stored_sort = M.get_user_setting(user, "price_sort_mode", price_sort_options[0])
    except Exception:
        user = ""
        stored_mode = "Přehled"
        stored_sort = price_sort_options[0]
    app.price_column_mode = M.tk.StringVar(value=stored_mode if stored_mode in ("Přehled", "Obchodní", "Technické") else "Přehled")
    app.price_sort_mode = M.tk.StringVar(value=stored_sort if stored_sort in price_sort_options else price_sort_options[0])

    search = M.ttk.Frame(current, style="Panel.TFrame", padding=(10, 8))
    search.pack(fill="x", pady=(0, 6))
    search.columnconfigure(0, weight=1)
    search.columnconfigure(1, weight=0)
    M.ttk.Label(search, text="Rychlé hledání", style="FilterLabel.TLabel").grid(row=0, column=0, sticky="w")
    M.ttk.Entry(search, textvariable=app.price_q).grid(row=1, column=0, sticky="ew", padx=(0, 12))
    sorting = M.ttk.Frame(search, style="Panel.TFrame")
    sorting.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 14))
    M.ttk.Label(sorting, text="Řazení", style="FilterLabel.TLabel").pack(anchor="w")
    M.safe_combobox(
        sorting, textvariable=app.price_sort_mode, values=price_sort_options, state="readonly", width=31,
    ).pack(anchor="e")
    modes = M.ttk.Frame(search, style="Panel.TFrame")
    modes.grid(row=0, column=2, rowspan=2, sticky="e")
    M.ttk.Label(modes, text="Sloupce:", style="PageSubtitle.TLabel").pack(side="left", padx=(0, 4))
    for label in ("Přehled", "Obchodní", "Technické"):
        M.ttk.Radiobutton(
            modes, text=label, value=label, variable=app.price_column_mode,
            command=lambda: _price_mode_changed(M, app),
        ).pack(side="left", padx=2)

    app.price_primary_filters = M.ttk.Frame(current, style="Panel.TFrame", padding=(10, 8))
    app.price_primary_filters.pack(fill="x", pady=(0, 6))
    labels = ("Dodavatel", "Produktová skupina", "Podskupina", "Cena platná k datu", "Zobrazení")
    for index, label in enumerate(labels):
        M.ttk.Label(app.price_primary_filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=index, sticky="w")
        app.price_primary_filters.columnconfigure(index, weight=2 if index in (0, 1, 2) else 1)
    app.price_supplier_box = M.AutocompleteEntry(app.price_primary_filters, textvariable=app.price_supplier_filter, values=[])
    app.price_supplier_box.grid(row=1, column=0, sticky="ew", padx=(0, 5))
    app.price_category_box = M.safe_combobox(
        app.price_primary_filters, textvariable=app.price_category_filter,
        values=["Všechny"], state="readonly",
    )
    app.price_category_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    app.price_subgroup_box = M.AutocompleteEntry(
        app.price_primary_filters, textvariable=app.price_subgroup_filter, values=[]
    )
    app.price_subgroup_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    M.DatePicker(app.price_primary_filters, app.price_effective_date).grid(row=1, column=3, sticky="ew", padx=(0, 5))
    M.safe_combobox(
        app.price_primary_filters, textvariable=app.price_price_scope,
        values=["Ověřené", "Nezařazené", "Ke kontrole", "Všechny včetně kontroly"], state="readonly", width=22,
    ).grid(row=1, column=4, sticky="ew", padx=(0, 5))
    app.price_advanced_button = M.ttk.Button(
        app.price_primary_filters, text="Další filtry ▾", command=lambda: _toggle_price_advanced(app)
    )
    app.price_advanced_button.grid(row=1, column=5, sticky="e")
    M.ttk.Button(
        app.price_primary_filters, text="Vymazat filtry",
        command=lambda: _clear_current_filters(M, app),
    ).grid(row=1, column=6, sticky="e", padx=(5, 0))

    app.price_advanced_visible = M.tk.BooleanVar(value=False)
    app.price_advanced_frame = M.ttk.Frame(current, style="Panel.TFrame", padding=(10, 8))
    M.ttk.Label(app.price_advanced_frame, text="Rozsah / cenová řada", style="FilterLabel.TLabel").grid(row=0, column=0, sticky="w")
    M.ttk.Label(app.price_advanced_frame, text="Řádků na stránku", style="FilterLabel.TLabel").grid(row=0, column=1, sticky="w")
    app.price_advanced_frame.columnconfigure(0, weight=1)
    app.price_group_box = M.AutocompleteEntry(app.price_advanced_frame, textvariable=app.price_group_filter, values=[])
    app.price_group_box.grid(row=1, column=0, sticky="ew", padx=(0, 6))
    M.safe_combobox(
        app.price_advanced_frame, textvariable=app.price_page_size,
        values=["100", "250", "500", "1000"], state="readonly", width=12,
    ).grid(row=1, column=1, sticky="w")

    body = M.ttk.Panedwindow(current, orient="horizontal")
    body.pack(fill="both", expand=True)
    taxonomy_side = M.ttk.Frame(body, style="Panel.TFrame", padding=8)
    table_side = M.ttk.Frame(body)
    detail_side = M.ttk.Frame(body, style="Panel.TFrame", padding=10)
    body.add(taxonomy_side, weight=1)
    body.add(table_side, weight=4)
    body.add(detail_side, weight=1)
    taxonomy_side.columnconfigure(0, weight=1)
    taxonomy_side.rowconfigure(2, weight=1)
    M.ttk.Label(taxonomy_side, text="Struktura cen", font=("Calibri", 13, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    M.ttk.Label(
        taxonomy_side,
        text="Kliknutím filtrujete. Vybrané ceny přetáhněte přímo na cílovou větev.",
        style="PageSubtitle.TLabel", wraplength=300,
    ).grid(row=1, column=0, sticky="w", pady=(1, 6))
    app.price_taxonomy_tree = M.ttk.Treeview(
        taxonomy_side, columns=("Cen",), show="tree headings", selectmode="browse", height=24,
    )
    app.price_taxonomy_tree.heading("#0", text="Skupina / podskupina")
    app.price_taxonomy_tree.heading("Cen", text="Cen")
    app.price_taxonomy_tree.column("#0", width=285, minwidth=190, anchor="w", stretch=True)
    app.price_taxonomy_tree.column("Cen", width=55, minwidth=45, anchor="e", stretch=False)
    app.price_taxonomy_tree.grid(row=2, column=0, sticky="nsew")
    taxonomy_scroll = M.ttk.Scrollbar(taxonomy_side, orient="vertical", command=app.price_taxonomy_tree.yview)
    taxonomy_scroll.grid(row=2, column=1, sticky="ns")
    app.price_taxonomy_tree.configure(yscrollcommand=taxonomy_scroll.set)
    try:
        app.price_taxonomy_tree.tag_configure("drop_target", background="#dcecff", foreground="#17324a")
    except Exception:
        pass
    taxonomy_actions = M.ttk.Frame(taxonomy_side, style="Panel.TFrame")
    taxonomy_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))
    M.ttk.Button(
        taxonomy_actions, text="Spravovat skupiny…",
        command=lambda: (categories.manage_categories(M, app), _refresh_price_taxonomy(M, app)),
    ).pack(fill="x")
    app.price_taxonomy_tree.bind(
        "<<TreeviewSelect>>", lambda _event: _on_price_taxonomy_select(M, app), add="+"
    )

    current_columns = (
        "Interní kód", "Interní označení", "Výrobce", "Dodavatel", "Kód dodavatele", "Produkt",
        "Produktová skupina", "Podskupina", "Nákupní cena/MJ", "Cenový základ", "Marže", "Doporučená cena",
        "Sleva", "Výsledná cena", "MJ", "Min. odběr", "Balení", "Hmotnost/MJ", "Rozměry",
        "Podmínka", "Platnost", "Zdrojový ceník",
    )
    current_widths = (120, 240, 160, 175, 125, 310, 235, 260, 125, 155, 70, 130, 70, 125, 55, 100, 125, 105, 150, 250, 145, 230)
    anchors = {name: "e" for name in ("Nákupní cena/MJ", "Marže", "Doporučená cena", "Sleva", "Výsledná cena", "Min. odběr", "Hmotnost/MJ")}
    app.price_current_tree = _make_tree(M, app, table_side, current_columns, current_widths, anchors)
    _configure_tags(app.price_current_tree, _PRICE_TAGS)
    for column, ascending, descending in (
        ("Produktová skupina", "Skupina → podskupina → produkt", None),
        ("Podskupina", "Skupina → podskupina → produkt", None),
        ("Interní označení", "Interní označení A–Z", None),
        ("Produkt", "Interní označení A–Z", None),
        ("Výrobce", "Výrobce A–Z", None),
        ("Dodavatel", "Dodavatel A–Z", None),
        ("Nákupní cena/MJ", "Nákupní cena ↑", "Nákupní cena ↓"),
        ("Výsledná cena", "Výsledná cena ↑", "Výsledná cena ↓"),
        ("Platnost", "Platnost končí nejdříve", None),
    ):
        app.price_current_tree.heading(
            column, text=column,
            command=lambda up=ascending, down=descending: _select_price_sort(app, up, down),
        )
    app.price_column_profiles = {
        "Přehled": (
            "Interní kód", "Interní označení", "Výrobce", "Dodavatel", "Produkt",
            "Nákupní cena/MJ", "Výsledná cena", "MJ", "Platnost",
        ),
        "Obchodní": (
            "Produktová skupina", "Podskupina", "Interní kód", "Interní označení", "Dodavatel",
            "Nákupní cena/MJ", "Cenový základ", "Marže", "Doporučená cena", "Sleva", "Výsledná cena", "Zdrojový ceník",
        ),
        "Technické": (
            "Dodavatel", "Kód dodavatele", "Produkt", "MJ", "Cenový základ", "Min. odběr", "Balení",
            "Hmotnost/MJ", "Rozměry", "Podmínka", "Zdrojový ceník",
        ),
    }
    _set_display_columns(app.price_current_tree, app.price_column_profiles, app.price_column_mode.get())
    app.price_current_rows = {}
    app.price_current_row_data = {}
    M.bind_row_double_click(app.price_current_tree, lambda _event: _edit_current_product(M, app))
    app.price_current_tree.bind("<<TreeviewSelect>>", lambda _event: _update_current_detail(M, app), add="+")
    app.price_current_tree.bind("<Return>", lambda _event: _edit_current_product(M, app), add="+")
    app.price_current_tree.bind("<F2>", lambda _event: _edit_current_product(M, app), add="+")
    app.price_current_tree.bind("<ButtonPress-1>", lambda event: _on_price_drag_press(M, app, event), add="+")
    app.price_current_tree.bind("<B1-Motion>", lambda event: _on_price_drag_motion(M, app, event), add="+")
    app.price_current_tree.bind("<ButtonRelease-1>", lambda event: _on_price_drag_release(M, app, event), add="+")

    M.ttk.Label(detail_side, text="Detail vybrané ceny", font=("Calibri", 13, "bold")).pack(anchor="w")
    app.price_current_detail_title = M.tk.StringVar(value="Vyberte cenu v tabulce")
    app.price_current_detail_subtitle = M.tk.StringVar(value="")
    M.ttk.Label(detail_side, textvariable=app.price_current_detail_title, font=("Calibri", 12, "bold"), wraplength=330).pack(anchor="w", pady=(8, 0))
    M.ttk.Label(detail_side, textvariable=app.price_current_detail_subtitle, style="PageSubtitle.TLabel", wraplength=330).pack(anchor="w", pady=(1, 8))
    app.price_current_detail_vars = {}
    for label in (
        "Zařazení", "Dodavatel", "Nákupní cena", "Cenový základ", "Marže a sleva", "Doporučená cena",
        "Výsledná cena", "Množství / balení", "Hmotnost / rozměry", "Platnost", "Zdroj", "Podmínka",
    ):
        row = M.ttk.Frame(detail_side, style="Panel.TFrame")
        row.pack(fill="x", pady=2)
        M.ttk.Label(row, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        variable = M.tk.StringVar(value="—")
        app.price_current_detail_vars[label] = variable
        M.ttk.Label(row, textvariable=variable, wraplength=330, justify="left").pack(anchor="w")
    detail_actions = M.ttk.Frame(detail_side, style="Panel.TFrame")
    detail_actions.pack(fill="x", pady=(10, 0))
    app.price_edit_product_button = M.ttk.Button(
        detail_actions, text="Upravit produkt", style="Accent.TButton",
        command=lambda: _edit_current_product(M, app),
    )
    app.price_edit_product_button.pack(fill="x")
    app.price_assign_button = M.ttk.Button(
        detail_actions, text="Přiřadit / přesunout…", command=lambda: _pick_current_taxonomy(M, app),
    )
    app.price_assign_button.pack(fill="x", pady=(5, 0))
    app.price_undo_move_button = M.ttk.Button(
        detail_actions, text="↶ Vrátit poslední přesun", command=lambda: _undo_current_move(M, app),
    )
    app.price_undo_move_button.pack(fill="x", pady=(5, 0))
    app.price_undo_move_button.state(["disabled"])
    M.ttk.Button(detail_actions, text="Otevřít zdrojový Ceník", command=lambda: _open_current_detail(M, app)).pack(fill="x", pady=(10, 0))
    M.ttk.Button(
        detail_actions, text="Otevřít katalog produktů",
        command=lambda: _open_catalog_for_current(M, app),
    ).pack(fill="x", pady=(5, 0))

    current_nav = M.ttk.Frame(current)
    current_nav.pack(fill="x", pady=(6, 0))
    app.price_current_status = M.tk.StringVar(value="")
    app.price_selection_status = M.tk.StringVar(value="Vybráno: 0")
    M.ttk.Label(current_nav, textvariable=app.price_current_status, style="PageSubtitle.TLabel").pack(side="left")
    M.ttk.Label(current_nav, textvariable=app.price_selection_status, style="PageSubtitle.TLabel").pack(side="left", padx=(14, 0))
    app.price_prev_button = M.ttk.Button(current_nav, text="← Předchozí", command=lambda: _change_current_page(M, app, -1))
    app.price_prev_button.pack(side="right", padx=3)
    app.price_next_button = M.ttk.Button(current_nav, text="Další →", command=lambda: _change_current_page(M, app, 1))
    app.price_next_button.pack(side="right", padx=3)

    # Evidence ---------------------------------------------------------------
    app.price_evidence_q = M.tk.StringVar()
    app.price_evidence_supplier = M.tk.StringVar()
    app.price_evidence_category = M.tk.StringVar(value="Všechny")
    app.price_evidence_status = M.tk.StringVar(value="Všechny")
    app.price_list_show_archived = M.tk.BooleanVar(value=False)
    app.price_evidence_page = 0
    app.price_evidence_page_size = 300

    quick = M.ttk.Frame(evidence, style="Panel.TFrame", padding=(10, 8))
    quick.pack(fill="x", pady=(0, 6))
    M.ttk.Label(quick, text="Rychlé pohledy:", style="PageSubtitle.TLabel").pack(side="left")
    for label in ("Všechny", "Aktuální", "Končí do 30 dnů", "Ke kontrole", "Po platnosti", "Archivované"):
        M.ttk.Button(
            quick, text=label,
            command=lambda value=label: _set_evidence_status(M, app, value),
        ).pack(side="left", padx=(5, 0))
    M.ttk.Checkbutton(
        quick, text="Zahrnout archivované", variable=app.price_list_show_archived,
        command=lambda: _reset_evidence_page_and_refresh(M, app),
    ).pack(side="right")

    evidence_filters = M.ttk.Frame(evidence, style="Panel.TFrame", padding=(10, 8))
    evidence_filters.pack(fill="x", pady=(0, 6))
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
    app.price_evidence_status_box = M.safe_combobox(
        evidence_filters, textvariable=app.price_evidence_status,
        values=["Všechny", "Aktuální", "Končí do 30 dnů", "Budoucí", "Po platnosti", "Ke kontrole", "Archivované"],
        state="readonly",
    )
    app.price_evidence_status_box.grid(row=1, column=3, sticky="ew", padx=(0, 5))
    M.ttk.Button(evidence_filters, text="Vymazat filtry", command=lambda: _clear_evidence_filters(M, app)).grid(row=1, column=4, sticky="e")

    evidence_body = M.ttk.Panedwindow(evidence, orient="horizontal")
    evidence_body.pack(fill="both", expand=True)
    evidence_table_side = M.ttk.Frame(evidence_body)
    evidence_detail_side = M.ttk.Frame(evidence_body, style="Panel.TFrame", padding=10)
    evidence_body.add(evidence_table_side, weight=4)
    evidence_body.add(evidence_detail_side, weight=1)
    evidence_columns = (
        "Stav", "Platnost", "Dodavatel", "Název", "Produktová skupina", "Položek",
        "Režim", "Platí od", "Platí do", "Rozsah / cenová řada", "Větev", "Import",
    )
    evidence_widths = (125, 145, 180, 280, 220, 70, 175, 90, 90, 180, 170, 150)
    evidence_anchors = {"Položek": "e"}
    app.price_list_evidence_tree = _make_tree(
        M, app, evidence_table_side, evidence_columns, evidence_widths, evidence_anchors
    )
    _configure_tags(app.price_list_evidence_tree, _PRICE_TAGS)
    app.price_evidence_rows = {}
    M.bind_row_double_click(app.price_list_evidence_tree, lambda _event: price_page.open_price_list_detail(M, app))
    app.price_list_evidence_tree.bind("<<TreeviewSelect>>", lambda _event: _update_evidence_detail(M, app), add="+")

    M.ttk.Label(evidence_detail_side, text="Detail Ceníku", font=("Calibri", 13, "bold")).pack(anchor="w")
    app.price_evidence_detail_title = M.tk.StringVar(value="Vyberte Ceník v tabulce")
    app.price_evidence_detail_subtitle = M.tk.StringVar(value="")
    M.ttk.Label(evidence_detail_side, textvariable=app.price_evidence_detail_title, font=("Calibri", 12, "bold"), wraplength=330).pack(anchor="w", pady=(8, 0))
    M.ttk.Label(evidence_detail_side, textvariable=app.price_evidence_detail_subtitle, style="PageSubtitle.TLabel", wraplength=330).pack(anchor="w", pady=(1, 8))
    app.price_evidence_detail_vars = {}
    for label in ("Stav", "Platnost", "Dodavatel", "Zařazení", "Rozsah / větev", "Položek", "Aktualizace", "Zdrojový soubor", "Import"):
        row = M.ttk.Frame(evidence_detail_side, style="Panel.TFrame")
        row.pack(fill="x", pady=2)
        M.ttk.Label(row, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        variable = M.tk.StringVar(value="—")
        app.price_evidence_detail_vars[label] = variable
        M.ttk.Label(row, textvariable=variable, wraplength=330, justify="left").pack(anchor="w")

    evidence_actions = M.ttk.Frame(evidence_detail_side, style="Panel.TFrame")
    evidence_actions.pack(fill="x", pady=(10, 0))
    M.ttk.Button(evidence_actions, text="Otevřít detail", style="Accent.TButton", command=lambda: price_page.open_price_list_detail(M, app)).pack(fill="x")
    M.ttk.Button(evidence_actions, text="Upravit údaje", command=lambda: _run_after_invalidation(app, lambda: price_page.edit_price_list_metadata(M, app), prices=True)).pack(fill="x", pady=(5, 0))
    M.ttk.Button(evidence_actions, text="Přiřadit produktovou skupinu", command=lambda: _run_after_invalidation(app, lambda: price_page._assign_list_category(M, app), prices=True)).pack(fill="x", pady=(5, 0))
    file_actions = M.ttk.Frame(evidence_detail_side, style="Panel.TFrame")
    file_actions.pack(fill="x", pady=(8, 0))
    M.ttk.Button(file_actions, text="Otevřít soubor", command=lambda: price_page._open_evidence_source(M, app, False)).pack(side="left", expand=True, fill="x", padx=(0, 2))
    M.ttk.Button(file_actions, text="Otevřít složku", command=lambda: price_page._open_evidence_source(M, app, True)).pack(side="left", expand=True, fill="x", padx=(2, 0))
    lifecycle = M.ttk.Frame(evidence_detail_side, style="Panel.TFrame")
    lifecycle.pack(fill="x", pady=(8, 0))
    M.ttk.Button(lifecycle, text="Archivovat", command=lambda: _run_after_invalidation(app, lambda: price_page._archive_selected(M, app, False), prices=True)).pack(side="left", expand=True, fill="x", padx=(0, 2))
    M.ttk.Button(lifecycle, text="Obnovit", command=lambda: _run_after_invalidation(app, lambda: price_page._archive_selected(M, app, True), prices=True)).pack(side="left", expand=True, fill="x", padx=(2, 0))
    M.ttk.Button(evidence_detail_side, text="Smazat pouze z DB", command=lambda: _run_after_invalidation(app, lambda: price_page._delete_selected(M, app), prices=True)).pack(fill="x", pady=(5, 0))

    evidence_nav = M.ttk.Frame(evidence)
    evidence_nav.pack(fill="x", pady=(6, 0))
    app.price_evidence_status_text = M.tk.StringVar(value="")
    M.ttk.Label(evidence_nav, textvariable=app.price_evidence_status_text, style="PageSubtitle.TLabel").pack(side="left")
    app.price_evidence_prev = M.ttk.Button(evidence_nav, text="← Předchozí", command=lambda: _change_evidence_page(M, app, -1))
    app.price_evidence_prev.pack(side="right", padx=3)
    app.price_evidence_next = M.ttk.Button(evidence_nav, text="Další →", command=lambda: _change_evidence_page(M, app, 1))
    app.price_evidence_next.pack(side="right", padx=3)

    def schedule_current(*_):
        if getattr(app, "_price_taxonomy_syncing", False):
            return
        app.price_page = 0
        schedule_price_refresh(M, app)

    def schedule_sort(*_):
        try:
            M.set_user_setting(user, "price_sort_mode", app.price_sort_mode.get())
        except Exception:
            pass
        schedule_current()

    def schedule_evidence(*_):
        app.price_evidence_page = 0
        schedule_price_refresh(M, app)

    def category_filter_changed(*_):
        if getattr(app, "_price_taxonomy_syncing", False):
            return
        app._price_taxonomy_syncing = True
        try:
            app.price_subgroup_filter.set("")
            app.price_taxonomy_no_subgroup.set(False)
        finally:
            app._price_taxonomy_syncing = False
        schedule_current()

    def subgroup_filter_changed(*_):
        if getattr(app, "_price_taxonomy_syncing", False):
            return
        if app.price_subgroup_filter.get().strip():
            app._price_taxonomy_syncing = True
            try:
                app.price_taxonomy_no_subgroup.set(False)
            finally:
                app._price_taxonomy_syncing = False
        schedule_current()

    def scope_filter_changed(*_):
        if getattr(app, "_price_taxonomy_syncing", False):
            return
        if app.price_price_scope.get() == "Nezařazené":
            app._price_taxonomy_syncing = True
            try:
                app.price_category_filter.set("Všechny")
                app.price_subgroup_filter.set("")
                app.price_taxonomy_no_subgroup.set(False)
            finally:
                app._price_taxonomy_syncing = False
        schedule_current()

    for variable in (
        app.price_q, app.price_supplier_filter, app.price_group_filter, app.price_effective_date,
        app.price_page_size, app.price_taxonomy_no_subgroup,
    ):
        variable.trace_add("write", schedule_current)
    app.price_category_filter.trace_add("write", category_filter_changed)
    app.price_subgroup_filter.trace_add("write", subgroup_filter_changed)
    app.price_price_scope.trace_add("write", scope_filter_changed)
    app.price_sort_mode.trace_add("write", schedule_sort)
    for variable in (
        app.price_evidence_q, app.price_evidence_supplier,
        app.price_evidence_category, app.price_evidence_status,
    ):
        variable.trace_add("write", schedule_evidence)
    notebook.bind("<<NotebookTabChanged>>", lambda _event: refresh_price_lists(M, app), add="+")
    app._commercial_price_ui_ready = True
    refresh_price_lists(M, app)


def schedule_price_refresh(M, app, delay=180):
    previous = getattr(app, "_commercial_price_refresh_after", None)
    if previous:
        try:
            app.after_cancel(previous)
        except Exception:
            pass
    app._commercial_price_refresh_after = app.after(delay, lambda: refresh_price_lists(M, app))


def refresh_price_lists(M, app):
    app._commercial_price_refresh_after = None
    if not getattr(app, "_commercial_price_ui_ready", False):
        return
    suppliers, ranges, group_names, subgroup_names = _price_filter_values(M, app)
    try:
        app.price_supplier_box.set_values(suppliers)
        app.price_evidence_supplier_box.set_values(suppliers)
        app.price_group_box.set_values(ranges)
        app.price_subgroup_box.set_values(subgroup_names)
        current_subgroup = app.price_subgroup_filter.get().strip()
        if current_subgroup and current_subgroup not in subgroup_names:
            app.price_subgroup_filter.set("")
        values = ["Všechny"] + group_names
        app.price_category_box.configure(values=values)
        app.price_evidence_category_box.configure(values=values)
    except Exception:
        pass
    _refresh_price_metrics(M, app)
    try:
        tab_index = app.price_notebook.index(app.price_notebook.select())
    except Exception:
        tab_index = 0
    if tab_index == 0:
        _refresh_price_taxonomy(M, app)
        _refresh_current(M, app)
    else:
        _refresh_evidence(M, app)


def _fts_query(value: str) -> str:
    import re
    tokens = re.findall(r"[0-9A-Za-zÀ-ž]+", value or "")
    return " AND ".join('"' + token.replace('"', '') + '"*' for token in tokens if token)


def _refresh_current(M, app, allow_fts_retry=True):
    from ..common import _iso_date
    from ..storage import _format_price

    tree = app.price_current_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    app.price_current_rows = {}
    app.price_current_row_data = {}
    effective = _iso_date(app.price_effective_date.get()) or date.today().isoformat()
    where = [
        "i.active=1", "p.archived=0", "trim(coalesce(p.valid_from,''))<>''",
        "p.valid_from<=?", "(trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)",
    ]
    params = [effective, effective]
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    category_expr = "coalesce(nullif(trim(pc.name),''),nullif(trim(ic.name),''),nullif(trim(lc.name),''),'Nezařazeno')"
    subgroup_expr = "coalesce(nullif(trim(psg.name),''),nullif(trim(sg.name),''),'')"
    query = app.price_q.get().strip()
    use_fts = bool(query and getattr(M, "PRICE_FTS_AVAILABLE", False) and _fts_query(query))
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
    no_subgroup_var = getattr(app, "price_taxonomy_no_subgroup", None)
    if no_subgroup_var is not None and bool(no_subgroup_var.get()):
        where.append("coalesce(cp.subgroup_id,i.subgroup_id) IS NULL")
    scope = app.price_price_scope.get() or "Ověřené"
    review_condition = (
        "(lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
    )
    if scope == "Ověřené":
        where.append(f"NOT {review_condition}")
    elif scope == "Nezařazené":
        where.append(f"NOT {review_condition}")
        where.append("coalesce(cp.category_id,i.category_id) IS NULL")
    elif scope == "Ke kontrole":
        where.append(review_condition)
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
    order_sql = _price_sort_sql(app)
    sql = f"""
        WITH candidates AS (
          SELECT i.id item_id,i.price_list_id,i.product_code,i.item_key,i.name,i.description,i.unit,
                 i.source_price,i.currency,i.price_basis_qty,i.normalized_unit_price,
                 i.discount_pct,i.surcharge_pct,i.weight_unit,i.minimum_qty,i.package_qty,i.package_unit,
                 i.pallet_qty,i.dimensions,i.condition_text,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,
                 p.parse_status,p.archived,{supplier_expr} supplier,{category_expr} category,{subgroup_expr} subgroup,
                 cp.id catalog_product_id,coalesce(cp.category_id,i.category_id,p.category_id) resolved_category_id,
                 coalesce(cp.subgroup_id,i.subgroup_id) resolved_subgroup_id,
                 coalesce(cp.internal_code,'') internal_code,coalesce(cp.internal_name,'') internal_name,
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
          WHERE {where_sql}
        ), effective_rows AS (SELECT * FROM candidates WHERE list_rank=1)
        SELECT *,COUNT(*) OVER() total_count FROM effective_rows
        ORDER BY {order_sql}
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
    today_date = date.today()
    for row in rows:
        iid = f"pc{row['item_id']}"
        recommended, final = product_catalog.calculate_prices(
            row["normalized_unit_price"], row["margin_pct"], row["sales_discount_pct"]
        )
        validity = _validity_text(M, row["valid_from"], row["valid_to"], today_date)
        package_parts = []
        if row["package_qty"]:
            package_parts.append(
                f"balení {_number(row['package_qty']):g} {row['package_unit'] or row['unit'] or ''}".strip()
            )
        if row["pallet_qty"]:
            package_parts.append(f"paleta {_number(row['pallet_qty']):g}")
        package = " · ".join(package_parts)
        weight = f"{_number(row['weight_unit']):g} kg/{row['unit'] or 'MJ'}" if row["weight_unit"] else ""
        basis_qty = _number(row["price_basis_qty"], 1) or 1
        basis = f"{_format_price(row['source_price'], row['currency'])} / {basis_qty:g} {row['unit'] or 'MJ'}"
        minimum = f"{_number(row['minimum_qty']):g} {row['unit'] or ''}".strip() if row["minimum_qty"] else ""
        values = (
            row["internal_code"], row["internal_name"], row["manufacturer"], row["supplier"],
            row["product_code"] or row["item_key"] or "", row["name"] or row["description"] or "",
            row["category"], row["subgroup"] or "", _format_price(row["normalized_unit_price"], row["currency"]),
            basis, f"{_number(row['margin_pct']):g} %",
            _format_price(recommended, row["currency"]) if row["show_recommended_price"] else "—",
            f"{_number(row['sales_discount_pct']):g} %", _format_price(final, row["currency"]),
            row["unit"] or "", minimum, package, weight, row["dimensions"] or "",
            row["condition_text"] or "", validity, row["title"] or "",
        )
        status = _price_status(row, today_date)
        tags = (status,) if status != "price_current" else ()
        tree.insert("", "end", iid=iid, values=values, tags=tags)
        data = dict(row)
        data.update({
            "recommended": recommended, "final": final, "validity": validity,
            "package_text": package, "weight_text": weight, "basis_text": basis,
            "minimum_text": minimum,
        })
        app.price_current_row_data[iid] = data
        app.price_current_rows[iid] = {
            "price_list_id": int(row["price_list_id"]), "item_id": int(row["item_id"]),
            "catalog_product_id": int(row["catalog_product_id"]) if row["catalog_product_id"] else None,
        }
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    scope_label = app.price_price_scope.get() or "Ověřené"
    suffix = "" if scope_label == "Ověřené" else f" · pohled: {scope_label}"
    app.price_current_status.set(
        f"Zobrazeno {start}–{end} z {total} platných cen · k {M.fmt_date(effective)}{suffix}"
    )
    app.price_prev_button.state(["!disabled"] if app.price_page > 0 else ["disabled"])
    app.price_next_button.state(["!disabled"] if end < total else ["disabled"])
    _update_current_detail(M, app)


def _refresh_evidence(M, app):
    from ..common import UPDATE_MODES
    from ..storage import _list_status

    tree = app.price_list_evidence_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    app.price_evidence_rows = {}
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    where = []
    params = []
    status = app.price_evidence_status.get()
    if status != "Archivované" and not app.price_list_show_archived.get():
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
        category_id = categories.category_id_by_name(M, category) or -1
        where.append(
            "(p.category_id=? OR EXISTS("
            "SELECT 1 FROM price_list_items ix "
            "LEFT JOIN catalog_products cpx ON cpx.id=ix.catalog_product_id "
            "WHERE ix.price_list_id=p.id AND ix.active=1 "
            "AND coalesce(cpx.category_id,ix.category_id)=?))"
        )
        params.extend((category_id, category_id))
    today_date = date.today()
    today = today_date.isoformat()
    soon = (today_date + timedelta(days=EXPIRING_DAYS)).isoformat()
    review = (
        "(trim(coalesce(p.valid_from,''))='' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
    )
    if status == "Aktuální":
        where += [
            "p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from<=?",
            "(trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)", f"NOT {review}",
        ]
        params += [today, today]
    elif status == "Končí do 30 dnů":
        where += [
            "p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from<=?",
            "trim(coalesce(p.valid_to,''))<>''", "p.valid_to>=?", "p.valid_to<=?",
            f"NOT {review}",
        ]
        params += [today, today, soon]
    elif status == "Budoucí":
        where += ["p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from>?"]
        params.append(today)
    elif status == "Po platnosti":
        where += ["p.archived=0", "trim(coalesce(p.valid_to,''))<>''", "p.valid_to<?"]
        params.append(today)
    elif status == "Ke kontrole":
        where.append(review)
    elif status == "Archivované":
        where.append("p.archived=1")
    where_sql = " AND ".join(where) if where else "1=1"
    offset = max(0, int(app.price_evidence_page or 0)) * app.price_evidence_page_size
    base_joins = """
        LEFT JOIN companies c ON c.id=p.supplier_company_id
        LEFT JOIN product_categories cat ON cat.id=p.category_id
    """
    with M.db() as con:
        total = int(con.execute(
            f"SELECT COUNT(*) FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id WHERE {where_sql}",
            params,
        ).fetchone()[0] or 0)
        rows = con.execute(
            f"""WITH page AS (
                   SELECT p.id,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,p.update_mode,
                          p.supersedes_id,p.archived,p.source_filename,p.archive_path,p.imported_at,
                          p.parse_status,p.note,p.terms_text,{supplier_expr} supplier,
                          cat.name header_category
                   FROM price_lists p {base_joins}
                   WHERE {where_sql}
                   ORDER BY CASE WHEN trim(coalesce(p.valid_from,''))='' THEN 1 ELSE 0 END,
                            p.valid_from DESC,p.id DESC
                   LIMIT ? OFFSET ?
                 ), item_stats AS (
                   SELECT i.price_list_id,COUNT(*) item_count,
                          COUNT(DISTINCT coalesce(cp.category_id,i.category_id)) category_count,
                          MIN(pc.name) single_category
                   FROM price_list_items i
                   JOIN page pg ON pg.id=i.price_list_id
                   LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                   LEFT JOIN product_categories pc ON pc.id=coalesce(cp.category_id,i.category_id)
                   WHERE i.active=1
                   GROUP BY i.price_list_id
                 )
                 SELECT pg.*,
                        CASE WHEN pg.header_category IS NOT NULL THEN pg.header_category
                             WHEN coalesce(s.category_count,0)>1 THEN 'Více kategorií'
                             WHEN coalesce(s.category_count,0)=1 THEN s.single_category
                             ELSE 'Nezařazeno' END category,
                        coalesce(s.item_count,0) item_count
                 FROM page pg LEFT JOIN item_stats s ON s.price_list_id=pg.id
                 ORDER BY CASE WHEN trim(coalesce(pg.valid_from,''))='' THEN 1 ELSE 0 END,
                          pg.valid_from DESC,pg.id DESC""",
            params + [app.price_evidence_page_size, offset],
        ).fetchall()
    if total and offset >= total and app.price_evidence_page:
        app.price_evidence_page = 0
        return _refresh_evidence(M, app)
    for row in rows:
        validity = _validity_text(M, row["valid_from"], row["valid_to"], today_date)
        row_status = _list_status(row)
        values = (
            row_status, validity, row["supplier"], row["title"], row["category"], row["item_count"],
            UPDATE_MODES.get(row["update_mode"], row["update_mode"]), M.fmt_date(row["valid_from"]),
            M.fmt_date(row["valid_to"]), row["product_group"], row["branch"],
            M.fmt_history_datetime(row["imported_at"]),
        )
        iid = f"pl{row['id']}"
        tree.insert("", "end", iid=iid, values=values, tags=(_price_status(row, today_date),))
        data = dict(row)
        data.update({"validity": validity, "display_status": row_status})
        app.price_evidence_rows[iid] = data
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    suffix = f" · filtr: {status}" if status and status != "Všechny" else ""
    app.price_evidence_status_text.set(f"Zobrazeno {start}–{end} z {total} ceníků{suffix}")
    app.price_evidence_prev.state(["!disabled"] if app.price_evidence_page > 0 else ["disabled"])
    app.price_evidence_next.state(["!disabled"] if end < total else ["disabled"])
    _update_evidence_detail(M, app)
    _refresh_price_metrics(M, app)


def _update_current_detail(M, app):
    selection = app.price_current_tree.selection() if hasattr(app, "price_current_tree") else ()
    rows = [app.price_current_row_data.get(iid) for iid in selection if app.price_current_row_data.get(iid)]
    status_var = getattr(app, "price_selection_status", None)
    if status_var is not None:
        status_var.set(f"Vybráno: {len(rows)}" + (" · přetáhněte na skupinu vlevo" if rows else ""))
    edit_button = getattr(app, "price_edit_product_button", None)
    assign_button = getattr(app, "price_assign_button", None)
    if edit_button is not None:
        edit_button.state(["!disabled"] if len(rows) == 1 else ["disabled"])
    if assign_button is not None:
        assign_button.state(["!disabled"] if rows else ["disabled"])
    row = rows[0] if rows else None
    if not row:
        app.price_current_detail_title.set("Vyberte cenu v tabulce")
        app.price_current_detail_subtitle.set("")
        for variable in app.price_current_detail_vars.values():
            variable.set("—")
        return
    from ..storage import _format_price
    title = row["internal_name"] or row["name"] or row["description"] or "Produkt"
    code = row["internal_code"] or row["product_code"] or row["item_key"] or ""
    app.price_current_detail_title.set(title)
    app.price_current_detail_subtitle.set(" · ".join(part for part in (code, row["manufacturer"]) if part))
    path = row["category"] + (" › " + row["subgroup"] if row["subgroup"] else "")
    app.price_current_detail_vars["Zařazení"].set(path)
    app.price_current_detail_vars["Dodavatel"].set(row["supplier"] or "—")
    app.price_current_detail_vars["Nákupní cena"].set(_format_price(row["normalized_unit_price"], row["currency"]))
    app.price_current_detail_vars["Cenový základ"].set(row["basis_text"] or "—")
    app.price_current_detail_vars["Marže a sleva"].set(f"{_number(row['margin_pct']):g} % / {_number(row['sales_discount_pct']):g} %")
    app.price_current_detail_vars["Doporučená cena"].set(_format_price(row["recommended"], row["currency"]) if row["show_recommended_price"] else "nezobrazuje se")
    app.price_current_detail_vars["Výsledná cena"].set(_format_price(row["final"], row["currency"]))
    amount = row["unit"] or "—"
    if row["minimum_text"]:
        amount += f" · min. {row['minimum_text']}"
    if row["package_text"]:
        amount += f" · balení {row['package_text']}"
    app.price_current_detail_vars["Množství / balení"].set(amount)
    technical = " · ".join(part for part in (row["weight_text"], row["dimensions"] or "") if part) or "—"
    app.price_current_detail_vars["Hmotnost / rozměry"].set(technical)
    app.price_current_detail_vars["Platnost"].set(row["validity"])
    app.price_current_detail_vars["Zdroj"].set(row["title"] or "—")
    app.price_current_detail_vars["Podmínka"].set(row["condition_text"] or "—")


def _update_evidence_detail(M, app):
    selection = app.price_list_evidence_tree.selection() if hasattr(app, "price_list_evidence_tree") else ()
    if len(selection) != 1:
        count = len(selection)
        app.price_evidence_detail_title.set(f"Vybráno ceníků: {count}" if count else "Vyberte Ceník v tabulce")
        app.price_evidence_detail_subtitle.set("Hromadně lze archivovat, obnovit nebo přiřadit skupinu." if count > 1 else "")
        for variable in app.price_evidence_detail_vars.values():
            variable.set("—")
        return
    row = app.price_evidence_rows.get(selection[0])
    if not row:
        return
    from ..common import UPDATE_MODES
    app.price_evidence_detail_title.set(row["title"] or "Ceník")
    app.price_evidence_detail_subtitle.set(row["source_filename"] or "")
    app.price_evidence_detail_vars["Stav"].set(row["display_status"])
    app.price_evidence_detail_vars["Platnost"].set(
        f"{M.fmt_date(row['valid_from']) or '—'} – {M.fmt_date(row['valid_to']) or 'bez omezení'} · {row['validity']}"
    )
    app.price_evidence_detail_vars["Dodavatel"].set(row["supplier"] or "—")
    app.price_evidence_detail_vars["Zařazení"].set(row["category"] or "Nezařazeno")
    app.price_evidence_detail_vars["Rozsah / větev"].set(" · ".join(part for part in (row["product_group"], row["branch"]) if part) or "—")
    app.price_evidence_detail_vars["Položek"].set(_count_text(row["item_count"]))
    app.price_evidence_detail_vars["Aktualizace"].set(UPDATE_MODES.get(row["update_mode"], row["update_mode"] or "—"))
    app.price_evidence_detail_vars["Zdrojový soubor"].set(row["source_filename"] or row["archive_path"] or "—")
    app.price_evidence_detail_vars["Import"].set(f"{M.fmt_history_datetime(row['imported_at'])} · {row['parse_status'] or '—'}")


def _open_current_detail(M, app):
    from .price_dialogs import open_price_list_detail
    selection = app.price_current_tree.selection() if hasattr(app, "price_current_tree") else ()
    if not selection:
        return M.messagebox.showinfo("Ceníky", "Vyberte cenu.", parent=app)
    info = app.price_current_rows.get(selection[0]) or {}
    open_price_list_detail(M, app, info.get("price_list_id"))


def _open_catalog_for_current(M, app):
    selection = app.price_current_tree.selection() if hasattr(app, "price_current_tree") else ()
    row = app.price_current_row_data.get(selection[0]) if selection else None
    if not row:
        return M.messagebox.showinfo("Ceníky", "Vyberte cenu.", parent=app)
    product_catalog.open_product_catalog(M, app, row.get("resolved_category_id"), row.get("resolved_subgroup_id"))


def _change_current_page(M, app, delta):
    app.price_page = max(0, int(app.price_page or 0) + int(delta))
    _refresh_current(M, app)


def _change_evidence_page(M, app, delta):
    app.price_evidence_page = max(0, int(app.price_evidence_page or 0) + int(delta))
    _refresh_evidence(M, app)


def _clear_current_filters(M, app):
    app.price_q.set("")
    app.price_supplier_filter.set("")
    app.price_category_filter.set("Všechny")
    app.price_subgroup_filter.set("")
    app.price_group_filter.set("")
    no_subgroup = getattr(app, "price_taxonomy_no_subgroup", None)
    if no_subgroup is not None:
        no_subgroup.set(False)
    app.price_effective_date.set(date.today().isoformat())
    app.price_price_scope.set("Ověřené")
    app.price_page = 0
    schedule_price_refresh(M, app, 0)


def _clear_evidence_filters(M, app):
    app.price_evidence_q.set("")
    app.price_evidence_supplier.set("")
    app.price_evidence_category.set("Všechny")
    app.price_evidence_status.set("Všechny")
    app.price_list_show_archived.set(False)
    app.price_evidence_page = 0
    schedule_price_refresh(M, app, 0)


def _set_evidence_status(M, app, status):
    app.price_notebook.select(1)
    app.price_evidence_status.set(status)
    app.price_evidence_page = 0
    schedule_price_refresh(M, app, 0)


def _reset_evidence_page_and_refresh(M, app):
    app.price_evidence_page = 0
    _refresh_evidence(M, app)


# ---------------------------------------------------------------------------
# NABÍDKY


def _offer_filter_values(M):
    with M.db() as con:
        suppliers = [row[0] for row in con.execute(
            """SELECT DISTINCT coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),nullif(trim(o.supplier_name),''),'') supplier
               FROM supplier_offers o LEFT JOIN companies c ON c.id=o.supplier_company_id
               WHERE trim(coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),nullif(trim(o.supplier_name),''),''))<>''
               ORDER BY supplier COLLATE CZECH"""
        ).fetchall()]
        actions = [row[0] for row in con.execute(
            """SELECT DISTINCT name FROM (
                 SELECT CASE
                   WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                   WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                   ELSE '' END name
                 FROM supplier_offers o
                 LEFT JOIN projects pd ON pd.id=o.project_id
                 LEFT JOIN requests rq ON rq.id=o.request_id
                 LEFT JOIN actions ra ON ra.id=rq.action_id
                 LEFT JOIN projects pr ON pr.id=ra.project_id
               ) WHERE trim(coalesce(name,''))<>'' ORDER BY name COLLATE CZECH"""
        ).fetchall()]
        statuses = [row[0] for row in con.execute(
            """SELECT DISTINCT trim(status) FROM supplier_offers
               WHERE trim(coalesce(status,''))<>'' ORDER BY trim(status) COLLATE CZECH"""
        ).fetchall()]
    return suppliers, actions, statuses


def _offer_summary_values(M):
    since = (date.today() - timedelta(days=30)).isoformat()
    with M.db() as con:
        row = con.execute(
            """SELECT
              SUM(CASE WHEN coalesce(o.archived,0)=0 THEN 1 ELSE 0 END) active,
              SUM(CASE WHEN coalesce(o.archived,0)=0 AND o.offer_date>=? THEN 1 ELSE 0 END) recent,
              SUM(CASE WHEN coalesce(o.archived,0)=0 AND o.request_id IS NULL
                            AND NOT (o.project_id IS NOT NULL AND o.action_id IS NULL) THEN 1 ELSE 0 END) unassigned,
              SUM(CASE WHEN coalesce(o.archived,0)=0 AND EXISTS(
                    SELECT 1 FROM supplier_offer_items i
                    WHERE i.offer_id=o.id AND i.category_id IS NULL
                  ) THEN 1 ELSE 0 END) uncategorized,
              SUM(CASE WHEN coalesce(o.archived,0)=0 AND EXISTS(
                    SELECT 1 FROM price_lists p WHERE p.source_offer_id=o.id
                  ) THEN 1 ELSE 0 END) pricelists,
              SUM(CASE WHEN coalesce(o.archived,0)=1 THEN 1 ELSE 0 END) archived
            FROM supplier_offers o""",
            (since,),
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _refresh_offer_metrics(M, app, force=False):
    variables = getattr(app, "offer_metric_vars", None)
    if not variables:
        return
    now = time.monotonic()
    cache = getattr(app, "_commercial_offer_summary_cache", None)
    if force or not cache or now - cache[0] > 5:
        values = _offer_summary_values(M)
        app._commercial_offer_summary_cache = (now, values)
    else:
        values = cache[1]
    for key, variable in variables.items():
        variable.set(_count_text(values.get(key)))


def _offer_quick_view(M, app, view, reset_filters=False):
    if reset_filters:
        app.offer_q.set("")
        app.offer_supplier_filter.set("")
        app.offer_action_filter.set("")
        app.offer_status_filter.set("Všechny")
        app.offer_type_filter.set("Vše")
    app.offer_view.set(view)
    app.offer_page = 0
    schedule_offer_refresh(M, app, 0)


def _offer_mode_changed(M, app):
    mode = app.offer_column_mode.get() or "Přehled"
    try:
        user = M.get_setting("active_user", "")
        M.set_user_setting(user, "offer_column_mode", mode)
    except Exception:
        pass
    _set_display_columns(app.offer_tree, app.offer_column_profiles, mode)


def build_offers(M, app):
    page = app.tabs["offers"]
    for child in page.winfo_children():
        child.destroy()
    app._offer_drop_area_ready = True
    app.title_label(page, "Přijaté nabídky")
    M.ttk.Label(
        page,
        text=("Přijaté cenové nabídky zůstávají samostatné. Vybranou nabídku lze překlopit "
              "do Vydané nabídky nebo ji výslovně označit jako Ceník."),
        style="PageSubtitle.TLabel",
    ).pack(anchor="w", pady=(0, 7))

    command = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    command.pack(fill="x", pady=(0, 7))
    if callable(getattr(app, "import_offer_sources", None)):
        M.ttk.Button(
            command, text="📥 Zpracovat nabídku", style="Accent.TButton",
            command=lambda: _run_after_invalidation(app, app.import_offer_sources, offers=True),
        ).pack(side="left")
    if callable(getattr(app, "import_selected_outlook_offer", None)):
        M.ttk.Button(
            command, text="✉ Načíst z Outlooku",
            command=lambda: _run_after_invalidation(app, app.import_selected_outlook_offer, offers=True),
        ).pack(side="left", padx=(6, 0))
    if callable(getattr(app, "open_product_prices", None)):
        M.ttk.Button(command, text="💰 Produkty / ceny", command=app.open_product_prices).pack(side="left", padx=(6, 0))
    _separator(M, command)
    M.ttk.Button(command, text="Katalog produktů", command=lambda: product_catalog.open_product_catalog(M, app)).pack(side="left")
    M.ttk.Button(
        command, text="Hromadná archivace",
        command=lambda: getattr(M, "open_bulk_archive_manager", lambda _app: None)(app),
    ).pack(side="left", padx=(6, 0))
    M.ttk.Label(command, text="PDF a MSG lze přetáhnout do okna programu.", style="PageSubtitle.TLabel").pack(side="right")

    definitions = (
        ("Aktivních nabídek", "active", "Aktivní"),
        ("Posledních 30 dní", "recent", "Posledních 30 dní"),
        ("Nepřiřazených", "unassigned", "Nepřiřazené"),
        ("Bez zařazení položek", "uncategorized", "Bez zařazení"),
        ("Evidovaných jako Ceník", "pricelists", "Ceníky"),
        ("Archivovaných", "archived", "Archivované"),
    )
    app.offer_metric_vars = _metric_cards(
        M, page, definitions, lambda target: _offer_quick_view(M, app, target, reset_filters=True)
    )

    app.offer_q = M.tk.StringVar()
    app.offer_supplier_filter = M.tk.StringVar()
    app.offer_action_filter = M.tk.StringVar()
    app.offer_status_filter = M.tk.StringVar(value="Všechny")
    app.offer_type_filter = M.tk.StringVar(value="Vše")
    app.offer_view = M.tk.StringVar(value="Aktivní")
    app.offer_show_archived = M.tk.BooleanVar(value=False)
    app.offer_page = 0
    app.offer_page_size = M.tk.StringVar(value="250")
    try:
        user = M.get_setting("active_user", "")
        stored_mode = M.get_user_setting(user, "offer_column_mode", "Přehled")
    except Exception:
        stored_mode = "Přehled"
    app.offer_column_mode = M.tk.StringVar(value=stored_mode if stored_mode in ("Přehled", "Rozšířené") else "Přehled")

    filter_panel = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    filter_panel.pack(fill="x", pady=(0, 6))
    for col, label in enumerate(("Hledat nabídku nebo produkt", "Dodavatel", "Akce", "Stav", "Typ")):
        M.ttk.Label(filter_panel, text=label, style="FilterLabel.TLabel").grid(row=0, column=col, sticky="w")
        filter_panel.columnconfigure(col, weight=3 if col == 0 else 1)
    M.ttk.Entry(filter_panel, textvariable=app.offer_q).grid(row=1, column=0, sticky="ew", padx=(0, 5))
    app.offer_supplier_box = M.AutocompleteEntry(filter_panel, textvariable=app.offer_supplier_filter, values=[])
    app.offer_supplier_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    app.offer_action_box = M.AutocompleteEntry(filter_panel, textvariable=app.offer_action_filter, values=[])
    app.offer_action_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    app.offer_status_box = M.safe_combobox(filter_panel, textvariable=app.offer_status_filter, values=["Všechny"], state="readonly")
    app.offer_status_box.grid(row=1, column=3, sticky="ew", padx=(0, 5))
    M.safe_combobox(
        filter_panel, textvariable=app.offer_type_filter,
        values=["Vše", "Nabídky", "Ceníky"], state="readonly", width=12,
    ).grid(row=1, column=4, sticky="ew", padx=(0, 5))
    M.ttk.Button(filter_panel, text="Vymazat filtry", command=lambda: clear_offer_filters(M, app)).grid(row=1, column=5, sticky="e")

    views = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 7))
    views.pack(fill="x", pady=(0, 6))
    M.ttk.Label(views, text="Pracovní pohled:", style="PageSubtitle.TLabel").pack(side="left")
    for label in ("Aktivní", "Posledních 30 dní", "Nepřiřazené", "Bez zařazení", "Ceníky", "Archivované", "Vše"):
        M.ttk.Button(views, text=label, command=lambda value=label: _offer_quick_view(M, app, value)).pack(side="left", padx=(5, 0))
    mode_frame = M.ttk.Frame(views, style="Panel.TFrame")
    mode_frame.pack(side="right")
    M.ttk.Label(mode_frame, text="Sloupce:", style="PageSubtitle.TLabel").pack(side="left")
    for label in ("Přehled", "Rozšířené"):
        M.ttk.Radiobutton(
            mode_frame, text=label, value=label, variable=app.offer_column_mode,
            command=lambda: _offer_mode_changed(M, app),
        ).pack(side="left", padx=2)
    M.ttk.Label(mode_frame, text="Řádků:", style="PageSubtitle.TLabel").pack(side="left", padx=(10, 3))
    M.safe_combobox(
        mode_frame, textvariable=app.offer_page_size,
        values=["100", "250", "500", "1000"], state="readonly", width=7,
    ).pack(side="left")

    body = M.ttk.Panedwindow(page, orient="horizontal")
    body.pack(fill="both", expand=True)
    table_side = M.ttk.Frame(body)
    detail_side = M.ttk.Frame(body, style="Panel.TFrame", padding=10)
    body.add(table_side, weight=4)
    body.add(detail_side, weight=1)
    columns = (
        "Datum", "Dodavatel", "Číslo nabídky", "Vazba", "Akce", "Reference", "Položek",
        "Zařazení produktů", "Hodnota", "Měna", "Typ", "Stav",
    )
    widths = (95, 185, 135, 110, 245, 220, 70, 210, 115, 60, 85, 100)
    anchors = {"Položek": "e", "Hodnota": "e"}
    app.offer_tree = _make_tree(M, app, table_side, columns, widths, anchors)
    _configure_tags(app.offer_tree, _OFFER_TAGS)
    app.offer_column_profiles = {
        "Přehled": ("Datum", "Dodavatel", "Číslo nabídky", "Akce", "Položek", "Hodnota", "Měna", "Typ", "Stav"),
        "Rozšířené": columns,
    }
    _set_display_columns(app.offer_tree, app.offer_column_profiles, app.offer_column_mode.get())
    app.offer_rows = {}
    M.bind_row_double_click(app.offer_tree, lambda _event: app.open_offer_detail())
    app.offer_tree.bind("<<TreeviewSelect>>", lambda _event: update_offer_selection(M, app), add="+")

    M.ttk.Label(detail_side, text="Detail nabídky", font=("Calibri", 13, "bold")).pack(anchor="w")
    app.offer_detail_title = M.tk.StringVar(value="Vyberte nabídku v tabulce")
    app.offer_detail_subtitle = M.tk.StringVar(value="")
    M.ttk.Label(detail_side, textvariable=app.offer_detail_title, font=("Calibri", 12, "bold"), wraplength=330).pack(anchor="w", pady=(8, 0))
    M.ttk.Label(detail_side, textvariable=app.offer_detail_subtitle, style="PageSubtitle.TLabel", wraplength=330).pack(anchor="w", pady=(1, 8))
    app.offer_detail_vars = {}
    for label in ("Datum a stav", "Vazba", "Akce", "Reference", "Položek", "Produktové skupiny", "Hodnota", "Typ dokumentu"):
        row = M.ttk.Frame(detail_side, style="Panel.TFrame")
        row.pack(fill="x", pady=2)
        M.ttk.Label(row, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        variable = M.tk.StringVar(value="—")
        app.offer_detail_vars[label] = variable
        M.ttk.Label(row, textvariable=variable, wraplength=330, justify="left").pack(anchor="w")
    app.offer_selection_label = M.ttk.Label(detail_side, text="Nevybrána žádná nabídka", style="PageSubtitle.TLabel")
    app.offer_selection_label.pack(anchor="w", pady=(8, 4))
    actions = M.ttk.Frame(detail_side, style="Panel.TFrame")
    actions.pack(fill="x")
    M.ttk.Button(actions, text="Otevřít detail", command=app.open_offer_detail).pack(fill="x")
    M.ttk.Button(
        actions, text="Překlopit do Vydané nabídky", style="Accent.TButton",
        command=lambda: _offer_to_issued_offer(M, app),
    ).pack(fill="x", pady=(5, 0))
    if callable(getattr(app, "export_selected_offer_excel", None)):
        M.ttk.Button(actions, text="Extrakce dat", command=app.export_selected_offer_excel).pack(fill="x", pady=(5, 0))
    M.ttk.Button(actions, text="Označit jako Ceník", command=lambda: _offer_to_price_list(M, app)).pack(fill="x", pady=(5, 0))
    lifecycle = M.ttk.Frame(detail_side, style="Panel.TFrame")
    lifecycle.pack(fill="x", pady=(8, 0))
    M.ttk.Button(lifecycle, text="Archivovat", command=lambda: _archive_offers(M, app, False)).pack(side="left", expand=True, fill="x", padx=(0, 2))
    M.ttk.Button(lifecycle, text="Obnovit", command=lambda: _archive_offers(M, app, True)).pack(side="left", expand=True, fill="x", padx=(2, 0))
    M.ttk.Button(
        detail_side, text="Smazat pouze z DB",
        command=lambda: _run_after_invalidation(app, app.delete_offer, offers=True),
    ).pack(fill="x", pady=(5, 0))

    context = M.tk.Menu(app.offer_tree, tearoff=False)
    context.add_command(label="Otevřít detail", command=app.open_offer_detail)
    context.add_command(label="Překlopit do Vydané nabídky", command=lambda: _offer_to_issued_offer(M, app))
    context.add_command(label="Označit jako Ceník…", command=lambda: _offer_to_price_list(M, app))
    context.add_separator()
    context.add_command(label="Archivovat vybrané", command=lambda: _archive_offers(M, app, False))
    context.add_command(label="Obnovit vybrané", command=lambda: _archive_offers(M, app, True))
    context.add_command(
        label="Smazat pouze z DB",
        command=lambda: _run_after_invalidation(app, app.delete_offer, offers=True),
    )

    def popup(event):
        row = app.offer_tree.identify_row(event.y)
        if row and row not in app.offer_tree.selection():
            app.offer_tree.selection_set(row)
            update_offer_selection(M, app)
        try:
            context.tk_popup(event.x_root, event.y_root)
        finally:
            context.grab_release()

    app.offer_tree.bind("<Button-3>", popup, add="+")

    nav = M.ttk.Frame(page)
    nav.pack(fill="x", pady=(6, 0))
    app.offer_status_text = M.tk.StringVar(value="")
    M.ttk.Label(nav, textvariable=app.offer_status_text, style="PageSubtitle.TLabel").pack(side="left")
    app.offer_prev_button = M.ttk.Button(nav, text="← Předchozí", command=lambda: _change_offer_page(M, app, -1))
    app.offer_prev_button.pack(side="right", padx=3)
    app.offer_next_button = M.ttk.Button(nav, text="Další →", command=lambda: _change_offer_page(M, app, 1))
    app.offer_next_button.pack(side="right", padx=3)

    for variable in (
        app.offer_q, app.offer_supplier_filter, app.offer_action_filter,
        app.offer_status_filter, app.offer_type_filter, app.offer_view, app.offer_page_size,
    ):
        variable.trace_add("write", lambda *_: schedule_offer_refresh(M, app))
    app._commercial_offer_ui_ready = True
    refresh_offers(M, app)


def schedule_offer_refresh(M, app, delay=180):
    previous = getattr(app, "_commercial_offer_refresh_after", None)
    if previous:
        try:
            app.after_cancel(previous)
        except Exception:
            pass
    app._commercial_offer_refresh_after = app.after(delay, lambda: refresh_offers(M, app))


def refresh_offers(M, app):
    app._commercial_offer_refresh_after = None
    if not getattr(app, "_commercial_offer_ui_ready", False):
        return
    suppliers, actions, statuses = _offer_filter_values(M)
    try:
        app.offer_supplier_box.set_values(suppliers)
        app.offer_action_box.set_values(actions)
        app.offer_status_box.configure(values=["Všechny"] + statuses)
    except Exception:
        pass
    tree = app.offer_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    app.offer_rows = {}

    supplier_expr = "coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),'')"
    action_expr = (
        "CASE WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'') "
        "WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'') ELSE '' END"
    )
    link_expr = (
        "CASE WHEN o.request_id IS NOT NULL THEN 'Poptávka' "
        "WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN 'Akce' ELSE 'Nepřiřazeno' END"
    )
    uncategorized_exists = (
        "EXISTS(SELECT 1 FROM supplier_offer_items ux "
        "WHERE ux.offer_id=o.id AND ux.category_id IS NULL)"
    )
    price_list_exists = "EXISTS(SELECT 1 FROM price_lists px WHERE px.source_offer_id=o.id)"
    where = []
    params = []
    view = app.offer_view.get() or "Aktivní"
    since = (date.today() - timedelta(days=30)).isoformat()
    if view == "Aktivní":
        where.append("coalesce(o.archived,0)=0")
    elif view == "Posledních 30 dní":
        where += ["coalesce(o.archived,0)=0", "o.offer_date>=?"]
        params.append(since)
    elif view == "Nepřiřazené":
        where += ["coalesce(o.archived,0)=0", "o.request_id IS NULL", "NOT (o.project_id IS NOT NULL AND o.action_id IS NULL)"]
    elif view == "Bez zařazení":
        where += ["coalesce(o.archived,0)=0", uncategorized_exists]
    elif view == "Ceníky":
        where += ["coalesce(o.archived,0)=0", price_list_exists]
    elif view == "Archivované":
        where.append("coalesce(o.archived,0)=1")
    supplier = app.offer_supplier_filter.get().strip()
    if supplier:
        where.append(f"lower({supplier_expr}) LIKE ?")
        params.append("%" + supplier.casefold() + "%")
    action = app.offer_action_filter.get().strip()
    if action:
        where.append(f"lower({action_expr}) LIKE ?")
        params.append("%" + action.casefold() + "%")
    status = app.offer_status_filter.get().strip()
    if status and status != "Všechny":
        where.append("lower(trim(coalesce(o.status,'')))=lower(trim(?))")
        params.append(status)
    type_filter = app.offer_type_filter.get()
    if type_filter == "Nabídky":
        where.append(f"NOT {price_list_exists}")
    elif type_filter == "Ceníky":
        where.append(price_list_exists)
    query = app.offer_q.get().strip().casefold()
    if query:
        where.append(
            f"(lower({supplier_expr}||' '||{action_expr}||' '||coalesce(o.offer_number,'')||' '||"
            "coalesce(o.reference,'')||' '||coalesce(o.note,'')||' '||coalesce(o.status,'')) LIKE ? OR "
            "EXISTS(SELECT 1 FROM supplier_offer_items sx WHERE sx.offer_id=o.id AND "
            "lower(coalesce(sx.original_name,'')||' '||coalesce(sx.item_key,'')||' '||coalesce(sx.product_code,'')) LIKE ?))"
        )
        params.extend(("%" + query + "%", "%" + query + "%"))
    where_sql = " AND ".join(where) if where else "1=1"
    try:
        page_size_value = app.offer_page_size.get() if hasattr(app.offer_page_size, "get") else app.offer_page_size
        page_size = max(50, min(1000, int(page_size_value or 250)))
    except Exception:
        page_size = 250
    offset = max(0, int(app.offer_page or 0)) * page_size
    base_joins = """
      LEFT JOIN companies s ON s.id=o.supplier_company_id
      LEFT JOIN projects pd ON pd.id=o.project_id
      LEFT JOIN requests rq ON rq.id=o.request_id
      LEFT JOIN actions ra ON ra.id=rq.action_id
      LEFT JOIN projects pr ON pr.id=ra.project_id
    """
    with M.db() as con:
        total = int(con.execute(
            f"SELECT COUNT(*) FROM supplier_offers o {base_joins} WHERE {where_sql}", params
        ).fetchone()[0] or 0)
        rows = con.execute(
            f"""WITH page AS (
                   SELECT o.id,o.offer_date,o.offer_number,o.reference,o.total_value,o.currency,
                          o.status,o.archived,{supplier_expr} supplier,{action_expr} action_name,
                          {link_expr} link_state,
                          (SELECT MIN(px.id) FROM price_lists px WHERE px.source_offer_id=o.id) price_list_id
                   FROM supplier_offers o {base_joins}
                   WHERE {where_sql}
                   ORDER BY CASE WHEN trim(coalesce(o.offer_date,''))='' THEN 1 ELSE 0 END,
                            o.offer_date DESC,o.id DESC
                   LIMIT ? OFFSET ?
                 ), stats AS (
                   SELECT i.offer_id,COUNT(*) item_count,
                          SUM(CASE WHEN coalesce(cp.category_id,i.category_id) IS NULL THEN 1 ELSE 0 END) unassigned_items,
                          group_concat(DISTINCT pc.name) category_names
                   FROM supplier_offer_items i
                   JOIN page pg ON pg.id=i.offer_id
                   LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                   LEFT JOIN product_categories pc ON pc.id=coalesce(cp.category_id,i.category_id)
                   GROUP BY i.offer_id
                 )
                 SELECT pg.*,coalesce(st.item_count,0) item_count,
                        coalesce(st.unassigned_items,0) unassigned_items,
                        coalesce(st.category_names,'') category_names
                 FROM page pg LEFT JOIN stats st ON st.offer_id=pg.id
                 ORDER BY CASE WHEN trim(coalesce(pg.offer_date,''))='' THEN 1 ELSE 0 END,
                          pg.offer_date DESC,pg.id DESC""",
            params + [page_size, offset],
        ).fetchall()
    if total and offset >= total and app.offer_page:
        app.offer_page = 0
        return refresh_offers(M, app)
    for row in rows:
        iid = f"o{row['id']}"
        type_name = "Ceník" if row["price_list_id"] else "Nabídka"
        taxonomy = row["category_names"] or ("Nezařazeno" if row["unassigned_items"] else "—")
        values = (
            M.fmt_date(row["offer_date"]), row["supplier"], row["offer_number"] or "", row["link_state"],
            row["action_name"], row["reference"] or "", row["item_count"], taxonomy,
            _format_number(row["total_value"]), row["currency"] or "CZK", type_name, row["status"] or "",
        )
        if int(row["archived"] or 0):
            tag = "offer_archived"
        elif row["link_state"] == "Nepřiřazeno":
            tag = "offer_unassigned"
        elif row["unassigned_items"]:
            tag = "offer_uncategorized"
        elif row["price_list_id"]:
            tag = "offer_pricelist"
        else:
            tag = ""
        tree.insert("", "end", iid=iid, values=values, tags=(tag,) if tag else ())
        data = dict(row)
        data.update({"type_name": type_name, "taxonomy": taxonomy})
        app.offer_rows[iid] = data
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    app.offer_status_text.set(f"Zobrazeno {start}–{end} z {total} nabídek · pohled: {view}")
    app.offer_prev_button.state(["!disabled"] if app.offer_page > 0 else ["disabled"])
    app.offer_next_button.state(["!disabled"] if end < total else ["disabled"])
    app.offer_show_archived.set(view in ("Archivované", "Vše"))
    update_offer_selection(M, app)
    _refresh_offer_metrics(M, app)


def update_offer_selection(M, app, *_):
    tree = getattr(app, "offer_tree", None)
    if tree is None:
        return
    selection = tree.selection()
    count = len(selection)
    label = getattr(app, "offer_selection_label", None)
    if label is not None:
        try:
            label.configure(text=f"Vybráno: {count}" if count else "Nevybrána žádná nabídka")
        except Exception:
            pass
    if count != 1:
        app.offer_detail_title.set(f"Vybráno nabídek: {count}" if count else "Vyberte nabídku v tabulce")
        app.offer_detail_subtitle.set("Hromadně lze archivovat nebo smazat z databáze." if count > 1 else "")
        for variable in app.offer_detail_vars.values():
            variable.set("—")
        return
    row = app.offer_rows.get(selection[0])
    if not row:
        return
    app.offer_detail_title.set(row["offer_number"] or row["reference"] or "Cenová nabídka")
    app.offer_detail_subtitle.set(row["supplier"] or "Neurčený dodavatel")
    app.offer_detail_vars["Datum a stav"].set(f"{M.fmt_date(row['offer_date']) or '—'} · {row['status'] or 'bez stavu'}")
    app.offer_detail_vars["Vazba"].set(row["link_state"])
    app.offer_detail_vars["Akce"].set(row["action_name"] or "—")
    app.offer_detail_vars["Reference"].set(row["reference"] or "—")
    app.offer_detail_vars["Položek"].set(_count_text(row["item_count"]))
    app.offer_detail_vars["Produktové skupiny"].set(row["taxonomy"])
    app.offer_detail_vars["Hodnota"].set(_format_amount(row["total_value"], row["currency"] or "CZK"))
    app.offer_detail_vars["Typ dokumentu"].set(row["type_name"] + (" · archivováno" if row["archived"] else ""))


def clear_offer_filters(M, app):
    app.offer_q.set("")
    app.offer_supplier_filter.set("")
    app.offer_action_filter.set("")
    app.offer_status_filter.set("Všechny")
    app.offer_type_filter.set("Vše")
    app.offer_view.set("Aktivní")
    app.offer_page = 0
    schedule_offer_refresh(M, app, 0)


def _selected_offer_ids(app):
    result = []
    tree = getattr(app, "offer_tree", None)
    for iid in tree.selection() if tree is not None else ():
        text = str(iid)
        if text.startswith("o") and text[1:].isdigit():
            result.append(int(text[1:]))
    return result


def _archive_offers(M, app, restore):
    from . import archive
    ids = _selected_offer_ids(app)
    if not ids:
        return M.messagebox.showinfo("Nabídky", "Vyberte jednu nebo více nabídek.", parent=app)
    action = "obnovit" if restore else "archivovat"
    if not M.messagebox.askyesno(
        "Nabídky", f"Opravdu {action} {len(ids)} vybraných nabídek?\n\nFyzické soubory a historie zůstanou zachované.", parent=app
    ):
        return
    archive._archive_rows(M, "offers", ids, M.get_setting("active_user", ""), restore=restore)
    app._commercial_offer_summary_cache = None
    refresh_offers(M, app)


def _offer_to_issued_offer(M, app):
    """Open an unsaved issued offer populated from one received offer."""
    ids = _selected_offer_ids(app)
    if len(ids) != 1:
        return M.messagebox.showinfo(
            "Přijaté nabídky",
            "Vyberte právě jednu přijatou nabídku.",
            parent=app,
        )
    try:
        from ..issued_offers import service as issued_service
        document, items = issued_service.draft_from_supplier_offer(M, ids[0])
    except Exception as exc:
        return M.messagebox.showerror(
            "Přijaté nabídky",
            "Položky se nepodařilo připravit pro Vydanou nabídku:\n\n" + str(exc),
            parent=app,
        )
    if not items:
        return M.messagebox.showinfo(
            "Přijaté nabídky",
            "Vybraná nabídka neobsahuje žádné položky.",
            parent=app,
        )
    opener = getattr(app, "open_issued_offer_editor", None)
    if not callable(opener):
        return M.messagebox.showerror(
            "Přijaté nabídky",
            "Editor Vydaných nabídek není v této instalaci dostupný.",
            parent=app,
        )
    return opener(initial_document=document, initial_items=items)


def _offer_to_price_list(M, app):
    from .. import offer_integration
    offer_integration.classify_selected_offer_as_price_list(app)
    app._commercial_offer_summary_cache = None
    app._commercial_price_summary_cache = None
    app._price_filter_cache = None
    try:
        refresh_offers(M, app)
    except Exception:
        pass


def _change_offer_page(M, app, delta):
    app.offer_page = max(0, int(app.offer_page or 0) + int(delta))
    refresh_offers(M, app)


# ---------------------------------------------------------------------------
# INSTALLATION


def install(M) -> None:
    if getattr(M, "_turto_commercial_workspace_v6339", False):
        return
    from . import price_page

    # Direct ownership, not wrapper chaining.  Earlier compatibility layers may
    # register commands, but these two workspaces have one final presentation
    # owner and one SQL-first refresh path.
    price_page.build_price_lists = build_price_lists
    price_page.refresh_price_lists = refresh_price_lists
    price_page.schedule_refresh = schedule_price_refresh
    price_page._refresh_current = _refresh_current
    price_page._refresh_evidence = _refresh_evidence

    def app_build_price_lists(self, *_args, **_kwargs):
        return build_price_lists(M, self)

    def app_refresh_price_lists(self, *_args, **_kwargs):
        return refresh_price_lists(M, self)

    def app_build_offers(self, *_args, **_kwargs):
        return build_offers(M, self)

    def app_refresh_offers(self, *_args, **_kwargs):
        return refresh_offers(M, self)

    def app_clear_offer_filters(self, *_args, **_kwargs):
        return clear_offer_filters(M, self)

    def app_update_offer_selection(self, *_args, **_kwargs):
        return update_offer_selection(M, self)

    M.App.build_price_lists = app_build_price_lists
    M.App.refresh_price_lists = app_refresh_price_lists
    M.App.build_offers = app_build_offers
    M.App.refresh_offers = app_refresh_offers
    M.App.clear_offer_filters = app_clear_offer_filters
    M.App._update_offer_selection = app_update_offer_selection
    M._turto_commercial_presentation_owner = "price_lists_domain.platform.commercial_workspace"
    M._turto_commercial_workspace_v6339 = True


__all__ = [
    "install", "build_price_lists", "refresh_price_lists", "build_offers", "refresh_offers",
    "_price_summary_values", "_offer_summary_values", "_price_status", "_validity_text",
]
