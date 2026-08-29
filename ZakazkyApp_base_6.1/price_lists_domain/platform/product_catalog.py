"""Stable product catalogue and sales-pricing defaults for TURTO CRM.

Products are linked to supplier price-list and offer rows by a deterministic
supplier/product identity.  Taxonomy, internal codes and internal designations
therefore survive later price-list updates without copying commercial metadata
into every imported row.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date

from . import categories


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return float(default)


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def calculate_prices(purchase_price, margin_pct=0, discount_pct=0) -> tuple[float, float]:
    """Return recommended and final unit price.

    TURTO's working convention is deliberately explicit: margin is added to the
    purchase price and the subgroup discount is then applied to that recommended
    price.  The unrounded values are retained for future issued documents.
    """
    purchase = _number(purchase_price)
    margin = _number(margin_pct)
    discount = _number(discount_pct)
    recommended = purchase * (1.0 + margin / 100.0)
    final = recommended * (1.0 - discount / 100.0)
    return recommended, final


def pricing_policy(M, category_id=None, subgroup_id=None) -> dict:
    with M.db() as con:
        if subgroup_id:
            row = con.execute(
                """SELECT s.category_id,s.default_margin_pct,s.default_discount_pct,
                          coalesce(c.show_recommended_price,1) show_recommended_price
                   FROM product_subgroups s
                   JOIN product_categories c ON c.id=s.category_id
                   WHERE s.id=?""",
                (subgroup_id,),
            ).fetchone()
            if row:
                return {
                    "category_id": int(row["category_id"]),
                    "subgroup_id": int(subgroup_id),
                    "margin_pct": _number(row["default_margin_pct"]),
                    "discount_pct": _number(row["default_discount_pct"]),
                    "show_recommended_price": bool(row["show_recommended_price"]),
                }
        if category_id:
            row = con.execute(
                """SELECT id,default_margin_pct,default_discount_pct,
                          coalesce(show_recommended_price,1) show_recommended_price
                   FROM product_categories WHERE id=?""",
                (category_id,),
            ).fetchone()
            if row:
                return {
                    "category_id": int(row["id"]),
                    "subgroup_id": None,
                    "margin_pct": _number(row["default_margin_pct"]),
                    "discount_pct": _number(row["default_discount_pct"]),
                    "show_recommended_price": bool(row["show_recommended_price"]),
                }
    return {
        "category_id": category_id,
        "subgroup_id": subgroup_id,
        "margin_pct": 0.0,
        "discount_pct": 0.0,
        "show_recommended_price": True,
    }


def quote_defaults(M, product_id: int, purchase_price) -> dict:
    with M.db() as con:
        row = con.execute(
            "SELECT category_id,subgroup_id,internal_code,internal_name FROM catalog_products WHERE id=?",
            (product_id,),
        ).fetchone()
    if not row:
        raise ValueError("Produkt už v katalogu neexistuje.")
    policy = pricing_policy(M, row["category_id"], row["subgroup_id"])
    recommended, final = calculate_prices(purchase_price, policy["margin_pct"], policy["discount_pct"])
    return {
        **policy,
        "catalog_product_id": int(product_id),
        "internal_code": row["internal_code"] or "",
        "internal_name": row["internal_name"] or "",
        "purchase_unit_price": _number(purchase_price),
        "recommended_unit_price": recommended,
        "final_unit_price": final,
    }


def _product_identity(product_code, item_key, source_name) -> str:
    code = _norm(product_code)
    if code:
        return "code:" + code
    key = _norm(item_key)
    if key:
        return "key:" + key
    name = _norm(source_name)
    return "name:" + name if name else ""


def _source_key(supplier_company_id, supplier_name_norm: str, product_identity: str) -> str:
    supplier = f"id:{int(supplier_company_id)}" if supplier_company_id else "name:" + supplier_name_norm
    return supplier + "|" + product_identity


def _resolve_product(
    con, *, supplier_company_id=None, supplier_name="", product_code="", item_key="",
    source_name="", category_id=None, subgroup_id=None, source_kind="",
):
    identity = _product_identity(product_code, item_key, source_name)
    if not identity:
        return None
    supplier_norm = _norm(supplier_name)
    row = con.execute(
        """SELECT s.product_id
           FROM catalog_product_sources s
           WHERE s.product_identity=?
             AND ((? IS NOT NULL AND s.supplier_company_id=?) OR s.supplier_name_norm=?)
           ORDER BY CASE WHEN s.supplier_company_id IS NOT NULL THEN 0 ELSE 1 END,s.id
           LIMIT 1""",
        (identity, supplier_company_id, supplier_company_id, supplier_norm),
    ).fetchone()
    product_id = int(row["product_id"]) if row else None
    if not product_id:
        inserted = con.execute(
            """INSERT INTO catalog_products(
                   manufacturer_company_id,manufacturer_name,category_id,subgroup_id,active
               ) VALUES(?,?,?,?,1)""",
            (supplier_company_id, str(supplier_name or "").strip(), category_id, subgroup_id),
        )
        product_id = int(inserted.lastrowid)
    key = _source_key(supplier_company_id, supplier_norm, identity)
    con.execute(
        """INSERT INTO catalog_product_sources(
               product_id,supplier_company_id,supplier_name,supplier_name_norm,source_key,
               product_identity,supplier_product_code,source_name,source_kind,last_seen_at
           ) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(source_key) DO UPDATE SET
             product_id=excluded.product_id,
             supplier_company_id=coalesce(excluded.supplier_company_id,catalog_product_sources.supplier_company_id),
             supplier_name=CASE WHEN trim(excluded.supplier_name)<>'' THEN excluded.supplier_name ELSE catalog_product_sources.supplier_name END,
             supplier_name_norm=CASE WHEN trim(excluded.supplier_name_norm)<>'' THEN excluded.supplier_name_norm ELSE catalog_product_sources.supplier_name_norm END,
             supplier_product_code=CASE WHEN trim(excluded.supplier_product_code)<>'' THEN excluded.supplier_product_code ELSE catalog_product_sources.supplier_product_code END,
             source_name=CASE WHEN trim(excluded.source_name)<>'' THEN excluded.source_name ELSE catalog_product_sources.source_name END,
             source_kind=CASE WHEN trim(excluded.source_kind)<>'' THEN excluded.source_kind ELSE catalog_product_sources.source_kind END,
             last_seen_at=CURRENT_TIMESTAMP""",
        (
            product_id, supplier_company_id, str(supplier_name or "").strip(), supplier_norm, key,
            identity, str(product_code or item_key or "").strip(), str(source_name or "").strip(), source_kind,
        ),
    )
    product = con.execute(
        "SELECT category_id,subgroup_id,manufacturer_name,manufacturer_company_id FROM catalog_products WHERE id=?",
        (product_id,),
    ).fetchone()
    product_category = int(product["category_id"]) if product and product["category_id"] else None
    product_subgroup = int(product["subgroup_id"]) if product and product["subgroup_id"] else None
    updates = []
    values = []
    if not product_category and category_id:
        updates.append("category_id=?")
        values.append(category_id)
        product_category = int(category_id)
    if not product_subgroup and subgroup_id:
        updates.append("subgroup_id=?")
        values.append(subgroup_id)
        product_subgroup = int(subgroup_id)
    if product_subgroup:
        parent = con.execute("SELECT category_id FROM product_subgroups WHERE id=?", (product_subgroup,)).fetchone()
        if parent and int(parent["category_id"]) != int(product_category or 0):
            product_category = int(parent["category_id"])
            updates.append("category_id=?")
            values.append(product_category)
    if product and not str(product["manufacturer_name"] or "").strip() and str(supplier_name or "").strip():
        updates.append("manufacturer_name=?")
        values.append(str(supplier_name).strip())
    if product and not product["manufacturer_company_id"] and supplier_company_id:
        updates.append("manufacturer_company_id=?")
        values.append(supplier_company_id)
    if updates:
        values.extend([product_id])
        con.execute(
            f"UPDATE catalog_products SET {','.join(updates)},updated_at=CURRENT_TIMESTAMP WHERE id=?",
            values,
        )
    return product_id, product_category, product_subgroup


def _sync_rows(M, table: str, parent_column: str, parent_id: int, source_kind: str) -> int:
    if table == "price_list_items":
        header_sql = """SELECT p.supplier_company_id,
              coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
              FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id WHERE p.id=?"""
        item_sql = """SELECT id,product_code,supplier_item_code,item_key,name,description,
                      category_id,subgroup_id FROM price_list_items WHERE price_list_id=?"""
    else:
        header_sql = """SELECT o.supplier_company_id,
              coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),
                       nullif(trim(o.supplier_name),''),'') supplier
              FROM supplier_offers o LEFT JOIN companies c ON c.id=o.supplier_company_id WHERE o.id=?"""
        item_sql = """SELECT id,product_code,'' supplier_item_code,item_key,
                      original_name name,details description,category_id,subgroup_id
                      FROM supplier_offer_items WHERE offer_id=?"""
    with M.db() as con:
        header = con.execute(header_sql, (parent_id,)).fetchone()
        if not header:
            return 0
        rows = con.execute(item_sql, (parent_id,)).fetchall()
        changed = 0
        for row in rows:
            source_name = row["name"] or row["description"] or ""
            resolved = _resolve_product(
                con,
                supplier_company_id=header["supplier_company_id"],
                supplier_name=header["supplier"],
                product_code=row["product_code"] or row["supplier_item_code"],
                item_key=row["item_key"],
                source_name=source_name,
                category_id=row["category_id"],
                subgroup_id=row["subgroup_id"],
                source_kind=source_kind,
            )
            if not resolved:
                continue
            product_id, category_id, subgroup_id = resolved
            con.execute(
                f"""UPDATE {table}
                    SET catalog_product_id=?,category_id=coalesce(?,category_id),
                        subgroup_id=coalesce(?,subgroup_id)
                    WHERE id=?""",
                (product_id, category_id, subgroup_id, row["id"]),
            )
            changed += 1
        return changed


def sync_price_list(M, price_list_id: int) -> int:
    return _sync_rows(M, "price_list_items", "price_list_id", int(price_list_id), "Ceník")


def sync_supplier_offer(M, offer_id: int) -> int:
    return _sync_rows(M, "supplier_offer_items", "offer_id", int(offer_id), "Cenová nabídka")


def count_unlinked(M) -> int:
    with M.db() as con:
        return int(con.execute(
            """SELECT
                 (SELECT COUNT(*) FROM price_list_items WHERE catalog_product_id IS NULL) +
                 (SELECT COUNT(*) FROM supplier_offer_items WHERE catalog_product_id IS NULL)"""
        ).fetchone()[0] or 0)


def sync_all_unlinked(M, max_documents: int | None = 250, progress=None) -> dict:
    with M.db() as con:
        sql = """SELECT source_kind,parent_id FROM (
                   SELECT 0 source_order,'Ceník' source_kind,price_list_id parent_id
                   FROM price_list_items WHERE catalog_product_id IS NULL GROUP BY price_list_id
                   UNION ALL
                   SELECT 1,'Cenová nabídka',offer_id
                   FROM supplier_offer_items WHERE catalog_product_id IS NULL GROUP BY offer_id
                 ) ORDER BY source_order,parent_id"""
        params = []
        if max_documents is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(max_documents)))
        documents = con.execute(sql, params).fetchall()
    total = len(documents)
    linked = 0
    for done, row in enumerate(documents, 1):
        if row["source_kind"] == "Ceník":
            linked += sync_price_list(M, int(row["parent_id"]))
        else:
            linked += sync_supplier_offer(M, int(row["parent_id"]))
        if progress:
            progress(done, total, f"{row['source_kind']} {row['parent_id']}")
    return {"documents": total, "items": linked, "remaining": count_unlinked(M)}


def set_product_taxonomy(M, product_ids, category_id=None, subgroup_id=None) -> int:
    ids = [int(value) for value in product_ids if value]
    if not ids:
        return 0
    if subgroup_id:
        category_id = categories.subgroup_parent_id(M, subgroup_id)
    with M.db() as con:
        con.executemany(
            "UPDATE catalog_products SET category_id=?,subgroup_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            [(category_id, subgroup_id, product_id) for product_id in ids],
        )
        for product_id in ids:
            con.execute(
                "UPDATE price_list_items SET category_id=?,subgroup_id=? WHERE catalog_product_id=?",
                (category_id, subgroup_id, product_id),
            )
            con.execute(
                "UPDATE supplier_offer_items SET category_id=?,subgroup_id=? WHERE catalog_product_id=?",
                (category_id, subgroup_id, product_id),
            )
    return len(ids)


def propagate_taxonomy_from_items(M, table: str, item_ids) -> int:
    if table not in {"price_list_items", "supplier_offer_items"}:
        return 0
    ids = [int(value) for value in item_ids if value]
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with M.db() as con:
        rows = con.execute(
            f"SELECT catalog_product_id,category_id,subgroup_id FROM {table} WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    changed = 0
    for row in rows:
        if row["catalog_product_id"]:
            changed += set_product_taxonomy(
                M, [row["catalog_product_id"]], row["category_id"], row["subgroup_id"]
            )
    return changed


def update_product(
    M, product_id: int, *, manufacturer_name: str, internal_code: str,
    internal_name: str, category_id=None, subgroup_id=None,
) -> None:
    product_id = int(product_id)
    code = str(internal_code or "").strip()
    if subgroup_id:
        category_id = categories.subgroup_parent_id(M, subgroup_id)
    with M.db() as con:
        if code:
            duplicate = con.execute(
                """SELECT id FROM catalog_products
                   WHERE id<>? AND lower(trim(internal_code))=lower(trim(?)) LIMIT 1""",
                (product_id, code),
            ).fetchone()
            if duplicate:
                raise ValueError("Tento interní kód už používá jiný produkt.")
        con.execute(
            """UPDATE catalog_products
               SET manufacturer_name=?,internal_code=?,internal_name=?,category_id=?,subgroup_id=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (
                str(manufacturer_name or "").strip(), code, str(internal_name or "").strip(),
                category_id, subgroup_id, product_id,
            ),
        )
    set_product_taxonomy(M, [product_id], category_id, subgroup_id)


def _invalidate(app) -> None:
    try:
        app._price_filter_cache = None
    except Exception:
        pass
    try:
        dirty = set(getattr(app, "_turto_dirty_pages", set()))
        dirty.update(("pricelists", "offers"))
        app._turto_dirty_pages = dirty
    except Exception:
        pass


def _selected_product_ids(tree) -> list[int]:
    result = []
    for iid in tree.selection():
        text = str(iid)
        if text.startswith("cp"):
            try:
                result.append(int(text[2:]))
            except Exception:
                pass
    return result


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


def _edit_product(M, app, parent, product_id: int, on_saved=None) -> None:
    with M.db() as con:
        row = con.execute(
            """SELECT p.*,coalesce(group_concat(DISTINCT s.supplier_name),'') suppliers
               FROM catalog_products p
               LEFT JOIN catalog_product_sources s ON s.product_id=p.id
               WHERE p.id=? GROUP BY p.id""",
            (product_id,),
        ).fetchone()
    if not row:
        return
    win = M.tk.Toplevel(parent)
    win.title("Produkt v interním katalogu")
    win.transient(parent)
    win.grab_set()
    frame = M.ttk.Frame(win, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    manufacturer = M.tk.StringVar(value=row["manufacturer_name"] or row["suppliers"] or "")
    internal_code = M.tk.StringVar(value=row["internal_code"] or "")
    internal_name = M.tk.StringVar(value=row["internal_name"] or "")
    group_rows = categories.list_categories(M)
    group_map = {categories.UNASSIGNED: None, **{str(item["name"]): int(item["id"]) for item in group_rows}}
    group_var = M.tk.StringVar(value=categories.category_name(M, row["category_id"]) or categories.UNASSIGNED)
    subgroup_var = M.tk.StringVar(value=categories.subgroup_name(M, row["subgroup_id"]) or categories.NO_SUBGROUP)
    fields = (
        ("Výrobce", manufacturer),
        ("Interní kód", internal_code),
        ("Interní označení", internal_name),
    )
    for index, (label, variable) in enumerate(fields):
        M.ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", padx=(0, 10), pady=5)
        M.ttk.Entry(frame, textvariable=variable, width=80).grid(row=index, column=1, sticky="ew", pady=5)
    M.ttk.Label(frame, text="Produktová skupina").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=5)
    group_box = M.safe_combobox(frame, textvariable=group_var, values=list(group_map), state="readonly", width=78)
    group_box.grid(row=3, column=1, sticky="ew", pady=5)
    M.ttk.Label(frame, text="Podskupina").grid(row=4, column=0, sticky="w", padx=(0, 10), pady=5)
    subgroup_box = M.safe_combobox(frame, textvariable=subgroup_var, values=[categories.NO_SUBGROUP], state="readonly", width=78)
    subgroup_box.grid(row=4, column=1, sticky="ew", pady=5)
    M.ttk.Label(frame, text="Zdrojoví dodavatelé").grid(row=5, column=0, sticky="nw", padx=(0, 10), pady=5)
    M.ttk.Label(frame, text=row["suppliers"] or "—", style="PageSubtitle.TLabel", wraplength=700).grid(
        row=5, column=1, sticky="w", pady=5
    )

    subgroup_map = {categories.NO_SUBGROUP: None}

    def refresh_subgroups(*_):
        nonlocal subgroup_map
        category_id = group_map.get(group_var.get())
        subgroup_map = {
            categories.NO_SUBGROUP: None,
            **{str(item["name"]): int(item["id"]) for item in categories.list_subgroups(M, category_id)},
        }
        subgroup_box.configure(values=list(subgroup_map))
        if subgroup_var.get() not in subgroup_map:
            subgroup_var.set(categories.NO_SUBGROUP)

    group_var.trace_add("write", refresh_subgroups)
    refresh_subgroups()
    current_subgroup = categories.subgroup_name(M, row["subgroup_id"])
    if current_subgroup in subgroup_map:
        subgroup_var.set(current_subgroup)

    def save():
        try:
            update_product(
                M, product_id,
                manufacturer_name=manufacturer.get(), internal_code=internal_code.get(),
                internal_name=internal_name.get(), category_id=group_map.get(group_var.get()),
                subgroup_id=subgroup_map.get(subgroup_var.get()),
            )
        except ValueError as exc:
            return M.messagebox.showwarning("Katalog produktů", str(exc), parent=win)
        _invalidate(app)
        win.destroy()
        if on_saved:
            on_saved()

    buttons = M.ttk.Frame(frame)
    buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
    M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))
    try:
        M.center_dialog(win, parent)
    except Exception:
        pass
    win.wait_window()


def _open_sources(M, parent, product_id: int) -> None:
    with M.db() as con:
        product = con.execute(
            "SELECT internal_code,internal_name,manufacturer_name FROM catalog_products WHERE id=?",
            (product_id,),
        ).fetchone()
        rows = con.execute(
            """SELECT 'Ceník' source_type,p.valid_from source_date,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier,
                      i.product_code source_code,i.name source_name,i.normalized_unit_price price,i.currency,
                      p.title document_name
               FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
               LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE i.catalog_product_id=?
               UNION ALL
               SELECT 'Cenová nabídka',o.offer_date,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(o.supplier_name),''),''),
                      i.product_code,i.original_name,i.unit_price,coalesce(o.currency,'CZK'),
                      coalesce(o.offer_number,o.reference,'')
               FROM supplier_offer_items i JOIN supplier_offers o ON o.id=i.offer_id
               LEFT JOIN companies c ON c.id=o.supplier_company_id
               WHERE i.catalog_product_id=?
               ORDER BY source_date DESC,source_type,document_name""",
            (product_id, product_id),
        ).fetchall()
    win = M.tk.Toplevel(parent)
    win.title("Zdroje produktu")
    win.transient(parent)
    M.enable_dialog_maximize(win, 1200, 700)
    outer = M.ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    heading = (product["internal_code"] or product["internal_name"] or product["manufacturer_name"] or "Produkt") if product else "Produkt"
    M.ttk.Label(outer, text=heading, font=("Calibri", 15, "bold")).pack(anchor="w", pady=(0, 8))
    cols = ("Typ", "Datum", "Dodavatel", "Kód dodavatele", "Označení ve zdroji", "Cena", "Dokument")
    widths = (120, 100, 200, 150, 330, 120, 260)
    wrap = M.ttk.Frame(outer)
    wrap.pack(fill="both", expand=True)
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    tree = M.ttk.Treeview(wrap, columns=cols, show="headings")
    for col, width in zip(cols, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    ys.grid(row=0, column=1, sticky="ns")
    tree.configure(yscrollcommand=ys.set)
    from ..storage import _format_price
    for row in rows:
        tree.insert("", "end", values=(
            row["source_type"], M.fmt_date(row["source_date"]), row["supplier"], row["source_code"],
            row["source_name"], _format_price(row["price"], row["currency"]), row["document_name"],
        ))
    M.ttk.Button(outer, text="Zavřít", style="Accent.TButton", command=win.destroy).pack(anchor="e", pady=(8, 0))


def open_product_catalog(M, app, category_id=None, subgroup_id=None) -> None:
    app = _root_app(app)
    # The catalogue may be opened from a modal Ceník/Nabídka detail. Release its
    # grab first so the new window is always interactive.
    try:
        grabbed = app.grab_current()
        if grabbed is not None:
            grabbed.grab_release()
    except Exception:
        pass
    # Link only a small legacy batch synchronously; full migration has progress
    # and Storno so a large customer database never appears frozen.
    initial_sync = sync_all_unlinked(M, max_documents=25)
    win = M.tk.Toplevel(app)
    win.title("Katalog produktů")
    win.transient(app)
    M.enable_dialog_maximize(win, 1550, 850)
    outer = M.ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    M.ttk.Label(outer, text="Katalog produktů", font=("Calibri", 17, "bold")).pack(anchor="w")
    M.ttk.Label(
        outer,
        text=("Interní údaje a zařazení jsou navázané na stabilní produkt. Novější ceník se stejným "
              "dodavatelem a kódem je převezme automaticky."),
        style="PageSubtitle.TLabel",
    ).pack(anchor="w", pady=(2, 8))

    filters = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
    filters.pack(fill="x", pady=(0, 6))
    query = M.tk.StringVar()
    manufacturer = M.tk.StringVar()
    group = M.tk.StringVar(value=categories.category_name(M, category_id) or "Všechny")
    subgroup = M.tk.StringVar(value=categories.subgroup_name(M, subgroup_id) or "Všechny")
    show_inactive = M.tk.BooleanVar(value=False)
    labels = ("Hledat", "Výrobce / dodavatel", "Produktová skupina", "Podskupina")
    for index, label in enumerate(labels):
        M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=index, sticky="w")
        filters.columnconfigure(index, weight=2 if index == 0 else 1)
    M.ttk.Entry(filters, textvariable=query).grid(row=1, column=0, sticky="ew", padx=(0, 5))
    manufacturer_box = M.AutocompleteEntry(filters, textvariable=manufacturer, values=[])
    manufacturer_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    group_box = M.safe_combobox(
        filters, textvariable=group, values=["Všechny"] + [row["name"] for row in categories.list_categories(M)], state="readonly"
    )
    group_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    subgroup_box = M.safe_combobox(filters, textvariable=subgroup, values=["Všechny"], state="readonly")
    subgroup_box.grid(row=1, column=3, sticky="ew")

    tools = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
    tools.pack(fill="x", pady=(0, 6))
    M.ttk.Checkbutton(tools, text="Zobrazit neaktivní", variable=show_inactive).pack(side="left")

    table_wrap = M.ttk.Frame(outer)
    table_wrap.pack(fill="both", expand=True)
    table_wrap.columnconfigure(0, weight=1)
    table_wrap.rowconfigure(0, weight=1)
    cols = (
        "Výrobce", "Dodavatel", "Kód dodavatele", "Označení ve zdroji", "Interní kód", "Interní označení",
        "Produktová skupina", "Podskupina", "Marže", "Sleva", "Zobrazení ceny", "Ceníků", "Nabídek", "Aktuální nákupní cena",
    )
    widths = (180, 190, 145, 300, 130, 260, 250, 280, 75, 75, 150, 70, 70, 145)
    tree = M.ttk.Treeview(table_wrap, columns=cols, show="headings", selectmode="extended")
    for col, width in zip(cols, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, minwidth=60, anchor="w")
    tree.grid(row=0, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
    xs = M.ttk.Scrollbar(table_wrap, orient="horizontal", command=tree.xview)
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    row_map = {}
    state = {"page": 0, "page_size": 500, "after": None}

    nav = M.ttk.Frame(outer)
    nav.pack(fill="x", pady=(7, 0))
    status = M.tk.StringVar()
    M.ttk.Label(nav, textvariable=status, style="PageSubtitle.TLabel").pack(side="left")
    prev_button = M.ttk.Button(nav, text="← Předchozí")
    prev_button.pack(side="right", padx=3)
    next_button = M.ttk.Button(nav, text="Další →")
    next_button.pack(side="right", padx=3)

    def update_subgroups(*_):
        selected_group = group.get()
        group_id = categories.category_id_by_name(M, selected_group) if selected_group != "Všechny" else None
        values = ["Všechny"] + [row["name"] for row in categories.list_subgroups(M, group_id)]
        subgroup_box.configure(values=values)
        if subgroup.get() not in values:
            subgroup.set("Všechny")

    def refresh_filters():
        with M.db() as con:
            values = [row[0] for row in con.execute(
                """SELECT DISTINCT trim(value) FROM (
                     SELECT manufacturer_name value FROM catalog_products
                     UNION ALL SELECT supplier_name FROM catalog_product_sources
                   ) WHERE trim(coalesce(value,''))<>'' ORDER BY value COLLATE CZECH"""
            ).fetchall()]
        manufacturer_box.set_values(values)

    def refresh():
        state["after"] = None
        for iid in tree.get_children(""):
            tree.delete(iid)
        row_map.clear()
        where = ["1=1"]
        params = []
        if not show_inactive.get():
            where.append("cp.active=1")
        text = query.get().strip().casefold()
        if text:
            where.append(
                """lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||
                   coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')||' '||
                   coalesce(src.source_code,'')||' '||coalesce(src.source_name,'')) LIKE ?"""
            )
            params.append("%" + text + "%")
        maker = manufacturer.get().strip().casefold()
        if maker:
            where.append("lower(coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')) LIKE ?")
            params.append("%" + maker + "%")
        group_id = categories.category_id_by_name(M, group.get()) if group.get() != "Všechny" else None
        if group_id:
            where.append("cp.category_id=?")
            params.append(group_id)
        subgroup_id_value = categories.subgroup_id_by_name(M, subgroup.get(), group_id) if subgroup.get() != "Všechny" else None
        if subgroup_id_value:
            where.append("cp.subgroup_id=?")
            params.append(subgroup_id_value)
        where_sql = " AND ".join(where)
        offset = state["page"] * state["page_size"]
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
            total = int(con.execute("SELECT COUNT(*) " + sql_from + " WHERE " + where_sql, params).fetchone()[0] or 0)
            rows = con.execute(
                """SELECT cp.id,cp.manufacturer_name,cp.internal_code,cp.internal_name,
                          coalesce(c.name,'Nezařazeno') category,coalesce(sg.name,'') subgroup,
                          coalesce(sg.default_margin_pct,c.default_margin_pct,0) margin_pct,
                          coalesce(sg.default_discount_pct,c.default_discount_pct,0) discount_pct,
                          coalesce(c.show_recommended_price,1) show_recommended_price,
                          coalesce(src.suppliers,'') suppliers,coalesce(src.source_code,'') source_code,
                          coalesce(src.source_name,'') source_name,
                          (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i WHERE i.catalog_product_id=cp.id) price_lists,
                          (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i WHERE i.catalog_product_id=cp.id) offers,
                          (SELECT i.normalized_unit_price FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                           WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                             AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                           ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) current_price,
                          (SELECT i.currency FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                           WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                             AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                           ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) current_currency
                   """ + sql_from + " WHERE " + where_sql +
                " ORDER BY category COLLATE CZECH,subgroup COLLATE CZECH,cp.manufacturer_name COLLATE CZECH,src.source_name COLLATE CZECH,cp.id LIMIT ? OFFSET ?",
                [today, today, today, today] + params + [state["page_size"], offset],
            ).fetchall()
        from ..storage import _format_price
        for row in rows:
            iid = f"cp{row['id']}"
            row_map[iid] = dict(row)
            tree.insert("", "end", iid=iid, values=(
                row["manufacturer_name"] or row["suppliers"], row["suppliers"], row["source_code"], row["source_name"],
                row["internal_code"], row["internal_name"], row["category"], row["subgroup"],
                f"{_number(row['margin_pct']):g} %", f"{_number(row['discount_pct']):g} %",
                "Doporučená i výsledná" if row["show_recommended_price"] else "Pouze výsledná",
                row["price_lists"], row["offers"], _format_price(row["current_price"], row["current_currency"] or "CZK"),
            ))
        start = offset + 1 if total else 0
        end = min(total, offset + len(rows))
        remaining = count_unlinked(M)
        extra = f" · {remaining} dosud nespojených položek" if remaining else ""
        status.set(f"Zobrazeno {start}–{end} z {total} produktů{extra}")
        prev_button.state(["!disabled"] if state["page"] > 0 else ["disabled"])
        next_button.state(["!disabled"] if end < total else ["disabled"])

    def schedule(*_):
        state["page"] = 0
        if state["after"]:
            try:
                win.after_cancel(state["after"])
            except Exception:
                pass
        state["after"] = win.after(180, refresh)

    def edit_selected():
        ids = _selected_product_ids(tree)
        if len(ids) != 1:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte právě jeden produkt.", parent=win)
        _edit_product(M, app, win, ids[0], refresh)

    def move_selected():
        ids = _selected_product_ids(tree)
        if not ids:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte jeden nebo více produktů.", parent=win)
        first = row_map.get(str(tree.selection()[0]), {}) if tree.selection() else {}
        selected = categories.choose_taxonomy(
            M, win, "Přesunout produkty do skupiny a podskupiny",
            categories.category_id_by_name(M, first.get("category")),
            categories.subgroup_id_by_name(M, first.get("subgroup")),
        )
        if selected == "cancel":
            return
        set_product_taxonomy(M, ids, *selected)
        _invalidate(app)
        refresh()

    def show_sources():
        ids = _selected_product_ids(tree)
        if len(ids) != 1:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte právě jeden produkt.", parent=win)
        _open_sources(M, win, ids[0])

    def sync_everything():
        progress_win = M.tk.Toplevel(win)
        progress_win.title("Synchronizace katalogu")
        progress_win.transient(win)
        progress_win.grab_set()
        frame = M.ttk.Frame(progress_win, padding=16)
        frame.pack(fill="both", expand=True)
        label = M.tk.StringVar(value="Připravuji synchronizaci…")
        M.ttk.Label(frame, textvariable=label).pack(anchor="w", pady=(0, 8))
        bar = M.ttk.Progressbar(frame, mode="determinate", length=520)
        bar.pack(fill="x")
        cancelled = {"value": False}
        M.ttk.Button(
            frame, text="Storno", command=lambda: cancelled.__setitem__("value", True)
        ).pack(anchor="e", pady=(10, 0))

        def progress(done, total, text):
            bar.configure(maximum=max(1, total), value=done)
            label.set(f"{done}/{total} · {text}")
            progress_win.update()
            if cancelled["value"]:
                raise RuntimeError("__TURTO_CATALOG_CANCELLED__")

        try:
            result = sync_all_unlinked(M, max_documents=None, progress=progress)
        except Exception as exc:
            progress_win.destroy()
            if str(exc) == "__TURTO_CATALOG_CANCELLED__":
                refresh_filters()
                refresh()
                return M.messagebox.showinfo(
                    "Katalog produktů", "Synchronizace byla stornována. Již propojené položky zůstaly bezpečně uložené.", parent=win
                )
            return M.messagebox.showerror(
                "Katalog produktů", "Synchronizaci se nepodařilo dokončit:" + chr(10) + str(exc), parent=win
            )
        progress_win.destroy()
        refresh_filters()
        refresh()
        M.messagebox.showinfo(
            "Katalog produktů",
            f"Synchronizováno dokumentů: {result['documents']}\nPropojeno položek: {result['items']}\nZbývá: {result['remaining']}",
            parent=win,
        )

    M.ttk.Button(tools, text="Upravit produkt…", style="Accent.TButton", command=edit_selected).pack(side="left", padx=(8, 4))
    M.ttk.Button(tools, text="Přesunout vybrané…", command=move_selected).pack(side="left", padx=4)
    M.ttk.Button(tools, text="Zdroje a ceny…", command=show_sources).pack(side="left", padx=4)
    M.ttk.Button(tools, text="Dosynchronizovat katalog", command=sync_everything).pack(side="left", padx=(16, 4))
    M.ttk.Button(tools, text="Zavřít", command=win.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit_selected(), add="+")
    prev_button.configure(command=lambda: (state.__setitem__("page", max(0, state["page"] - 1)), refresh()))
    next_button.configure(command=lambda: (state.__setitem__("page", state["page"] + 1), refresh()))
    for variable in (query, manufacturer, group, subgroup, show_inactive):
        variable.trace_add("write", schedule)
    group.trace_add("write", update_subgroups)
    update_subgroups()
    if subgroup_id:
        value = categories.subgroup_name(M, subgroup_id)
        if value:
            subgroup.set(value)
    refresh_filters()
    refresh()
    if initial_sync["items"]:
        status.set(status.get() + f" · při otevření propojeno {initial_sync['items']} položek")


def install(M) -> None:
    if getattr(M, "_turto_product_catalog_v634", False):
        return
    old_save_offer = getattr(M, "save_offer_import", None)
    if callable(old_save_offer):
        def save_offer_import(*args, **kwargs):
            result = old_save_offer(*args, **kwargs)
            offer_id = None
            if isinstance(result, (tuple, list)) and result:
                offer_id = result[0]
            elif isinstance(result, int):
                offer_id = result
            try:
                if offer_id:
                    sync_supplier_offer(M, int(offer_id))
            except Exception:
                pass
            return result
        M.save_offer_import = save_offer_import
    M.open_product_catalog = lambda app, category_id=None, subgroup_id=None: open_product_catalog(
        M, app, category_id, subgroup_id
    )
    try:
        M.App.open_product_catalog = lambda self, category_id=None, subgroup_id=None: open_product_catalog(
            M, self, category_id, subgroup_id
        )
    except Exception:
        pass
    M._turto_product_catalog_v634 = True


__all__ = [
    "calculate_prices", "pricing_policy", "quote_defaults", "sync_price_list",
    "sync_supplier_offer", "sync_all_unlinked", "count_unlinked",
    "set_product_taxonomy", "propagate_taxonomy_from_items", "update_product",
    "open_product_catalog", "install",
]
