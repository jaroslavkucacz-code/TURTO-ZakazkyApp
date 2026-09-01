"""Canonical manually managed product-group and subgroup catalogue.

Product placement is intentionally not guessed from keywords. Stable IDs keep
renames, pricing defaults and later price-list updates connected to the same
internal product catalogue.
"""
from __future__ import annotations

UNASSIGNED = "Nezařazeno"
NO_SUBGROUP = "Bez podskupiny"


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _number(value, default=0.0) -> float:
    try:
        return float(value or 0)
    except Exception:
        return float(default)


def list_categories(M, include_inactive: bool = False):
    with M.db() as con:
        return con.execute(
            """SELECT id,name,parent_id,active,sort_order,
                      coalesce(default_margin_pct,0) default_margin_pct,
                      coalesce(default_discount_pct,0) default_discount_pct,
                      coalesce(show_recommended_price,1) show_recommended_price
               FROM product_categories
               WHERE (?=1 OR active=1)
               ORDER BY active DESC,sort_order,name COLLATE CZECH""",
            (1 if include_inactive else 0,),
        ).fetchall()


def list_subgroups(M, category_id=None, include_inactive: bool = False):
    with M.db() as con:
        return con.execute(
            """SELECT s.id,s.category_id,s.name,s.active,s.sort_order,
                      coalesce(s.default_margin_pct,0) default_margin_pct,
                      coalesce(s.default_discount_pct,0) default_discount_pct,
                      c.name category_name,c.active category_active,
                      coalesce(c.show_recommended_price,1) show_recommended_price
               FROM product_subgroups s
               JOIN product_categories c ON c.id=s.category_id
               WHERE (? IS NULL OR s.category_id=?)
                 AND (?=1 OR (s.active=1 AND c.active=1))
               ORDER BY c.sort_order,c.name COLLATE CZECH,s.active DESC,s.sort_order,s.name COLLATE CZECH""",
            (category_id, category_id, 1 if include_inactive else 0),
        ).fetchall()


def category_id_by_name(M, name: str):
    if not str(name or "").strip():
        return None
    with M.db() as con:
        row = con.execute(
            "SELECT id FROM product_categories WHERE active=1 AND lower(trim(name))=lower(trim(?))",
            (str(name).strip(),),
        ).fetchone()
    return int(row["id"]) if row else None


def subgroup_id_by_name(M, name: str, category_id=None):
    if not str(name or "").strip():
        return None
    with M.db() as con:
        row = con.execute(
            """SELECT s.id FROM product_subgroups s JOIN product_categories c ON c.id=s.category_id
               WHERE s.active=1 AND c.active=1 AND lower(trim(s.name))=lower(trim(?))
                 AND (? IS NULL OR s.category_id=?)
               ORDER BY s.id LIMIT 1""",
            (str(name).strip(), category_id, category_id),
        ).fetchone()
    return int(row["id"]) if row else None


def category_name(M, category_id) -> str:
    if not category_id:
        return ""
    with M.db() as con:
        row = con.execute("SELECT name FROM product_categories WHERE id=?", (category_id,)).fetchone()
    return str(row["name"] or "") if row else ""


def subgroup_name(M, subgroup_id) -> str:
    if not subgroup_id:
        return ""
    with M.db() as con:
        row = con.execute("SELECT name FROM product_subgroups WHERE id=?", (subgroup_id,)).fetchone()
    return str(row["name"] or "") if row else ""


def subgroup_parent_id(M, subgroup_id):
    if not subgroup_id:
        return None
    with M.db() as con:
        row = con.execute("SELECT category_id FROM product_subgroups WHERE id=?", (subgroup_id,)).fetchone()
    return int(row["category_id"]) if row else None


def taxonomy_path(M, category_id=None, subgroup_id=None) -> str:
    group = category_name(M, category_id)
    subgroup = subgroup_name(M, subgroup_id)
    if group and subgroup:
        return f"{group} › {subgroup}"
    return group or subgroup or UNASSIGNED


# Keyword-based assignment is deliberately disabled. These compatibility
# functions remain because older import dialogs call them, but they never guess.
def classify_text(M, value: object):
    return None


def classify_subgroup_text(M, category_id, value: object):
    return None


def classify_item(M, row):
    return None


def classify_item_taxonomy(M, row):
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    category_id = int(row["category_id"]) if "category_id" in keys and row["category_id"] else None
    subgroup_id = int(row["subgroup_id"]) if "subgroup_id" in keys and row["subgroup_id"] else None
    if subgroup_id:
        category_id = subgroup_parent_id(M, subgroup_id) or category_id
    return category_id, subgroup_id


def majority_category(M, items) -> int | None:
    return None


def set_item_taxonomy(M, table: str, item_ids, category_id=None, subgroup_id=None) -> int:
    allowed = {"price_list_items", "supplier_offer_items", "business_document_items"}
    if table not in allowed:
        raise ValueError("Nepodporovaný typ produktové položky.")
    ids = [int(value) for value in item_ids if value]
    if not ids:
        return 0
    # Existing historical rows may not yet be linked to the stable product master.
    # Link their parent documents before changing taxonomy so this manual decision
    # is inherited by later price-list versions as well.
    if table in {"price_list_items", "supplier_offer_items"}:
        from . import product_catalog
        parent_column = "price_list_id" if table == "price_list_items" else "offer_id"
        marks = ",".join("?" for _ in ids)
        with M.db() as con:
            parent_ids = [int(row[0]) for row in con.execute(
                f"SELECT DISTINCT {parent_column} FROM {table} WHERE id IN ({marks})", ids
            ).fetchall() if row[0]]
        for parent_id in parent_ids:
            if table == "price_list_items":
                product_catalog.sync_price_list(M, parent_id)
            else:
                product_catalog.sync_supplier_offer(M, parent_id)
    if subgroup_id:
        parent = subgroup_parent_id(M, subgroup_id)
        if not parent:
            raise ValueError("Vybraná podskupina už neexistuje.")
        category_id = parent
    with M.db() as con:
        if "subgroup_id" not in _columns(con, table):
            raise RuntimeError("Databáze ještě neobsahuje podporu produktových podskupin.")
        con.executemany(
            f"UPDATE {table} SET category_id=?,subgroup_id=? WHERE id=?",
            [(category_id, subgroup_id, item_id) for item_id in ids],
        )
    if table in {"price_list_items", "supplier_offer_items"}:
        product_catalog.propagate_taxonomy_from_items(M, table, ids)
    return len(ids)


def _write_sort_order(con, table: str, ids) -> None:
    """Write compact deterministic order values without changing business identity."""
    con.executemany(
        f"UPDATE {table} SET sort_order=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        [((index + 1) * 10, int(row_id)) for index, row_id in enumerate(ids)],
    )


def reorder_category(M, category_id: int, target_category_id=None, after: bool = False) -> None:
    """Move one group before/after another group by stable ID."""
    category_id = int(category_id)
    target_category_id = int(target_category_id) if target_category_id else None
    with M.db() as con:
        rows = con.execute(
            """SELECT id,active FROM product_categories
               ORDER BY active DESC,sort_order,name COLLATE CZECH,id"""
        ).fetchall()
        source = next((row for row in rows if int(row["id"]) == category_id), None)
        if not source:
            raise ValueError("Přesouvaná produktová skupina už neexistuje.")
        source_active = int(source["active"] or 0)
        ordered = [int(row["id"]) for row in rows if int(row["active"] or 0) == source_active]
        ordered.remove(category_id)
        target = next((row for row in rows if target_category_id and int(row["id"]) == target_category_id), None)
        if target and int(target["active"] or 0) == source_active and target_category_id in ordered:
            index = ordered.index(target_category_id) + (1 if after else 0)
            ordered.insert(index, category_id)
        else:
            ordered.append(category_id)
        _write_sort_order(con, "product_categories", ordered)


def reorder_subgroup(
    M, subgroup_id: int, target_category_id: int, target_subgroup_id=None, after: bool = False,
) -> None:
    """Move/reorder a subgroup and propagate its parent group to every linked row."""
    subgroup_id = int(subgroup_id)
    target_category_id = int(target_category_id)
    target_subgroup_id = int(target_subgroup_id) if target_subgroup_id else None
    with M.db() as con:
        source = con.execute(
            "SELECT id,category_id,active,name FROM product_subgroups WHERE id=?", (subgroup_id,)
        ).fetchone()
        target_group = con.execute("SELECT id FROM product_categories WHERE id=?", (target_category_id,)).fetchone()
        if not source:
            raise ValueError("Přesouvaná podskupina už neexistuje.")
        if not target_group:
            raise ValueError("Cílová produktová skupina už neexistuje.")
        if target_subgroup_id == subgroup_id:
            return
        target = None
        if target_subgroup_id:
            target = con.execute(
                "SELECT id,category_id,active FROM product_subgroups WHERE id=?", (target_subgroup_id,)
            ).fetchone()
            if not target:
                raise ValueError("Cílová podskupina už neexistuje.")
            target_category_id = int(target["category_id"])
        old_category_id = int(source["category_id"])
        source_active = int(source["active"] or 0)
        if old_category_id != target_category_id:
            # UNIQUE(category_id,name) deliberately protects accidental duplicates.
            con.execute(
                "UPDATE product_subgroups SET category_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (target_category_id, subgroup_id),
            )
            for table in ("price_list_items", "supplier_offer_items", "business_document_items", "catalog_products"):
                if {"category_id", "subgroup_id"}.issubset(_columns(con, table)):
                    con.execute(f"UPDATE {table} SET category_id=? WHERE subgroup_id=?", (target_category_id, subgroup_id))

        rows = con.execute(
            """SELECT id,active FROM product_subgroups WHERE category_id=?
               ORDER BY active DESC,sort_order,name COLLATE CZECH,id""",
            (target_category_id,),
        ).fetchall()
        ordered = [int(row["id"]) for row in rows if int(row["active"] or 0) == source_active]
        if subgroup_id in ordered:
            ordered.remove(subgroup_id)
        target_row = next((row for row in rows if target_subgroup_id and int(row["id"]) == target_subgroup_id), None)
        if target_row and int(target_row["active"] or 0) == source_active and target_subgroup_id in ordered:
            index = ordered.index(target_subgroup_id) + (1 if after else 0)
            ordered.insert(index, subgroup_id)
        else:
            ordered.append(subgroup_id)
        _write_sort_order(con, "product_subgroups", ordered)

        if old_category_id != target_category_id:
            old_rows = con.execute(
                """SELECT id FROM product_subgroups WHERE category_id=?
                   ORDER BY active DESC,sort_order,name COLLATE CZECH,id""",
                (old_category_id,),
            ).fetchall()
            _write_sort_order(con, "product_subgroups", [int(row["id"]) for row in old_rows])


def move_subgroup(M, subgroup_id: int, category_id: int) -> None:
    """Compatibility entry point: move the subgroup to the end of another group."""
    reorder_subgroup(M, subgroup_id, category_id)


def autocategorize_price_list(M, price_list_id: int, only_empty: bool = True) -> tuple[int, int]:
    """Compatibility entry point: link deterministic products, never guess taxonomy."""
    from . import product_catalog
    linked = product_catalog.sync_price_list(M, int(price_list_id))
    with M.db() as con:
        unassigned = int(con.execute(
            "SELECT COUNT(*) FROM price_list_items WHERE price_list_id=? AND category_id IS NULL",
            (price_list_id,),
        ).fetchone()[0] or 0)
    return linked, unassigned


def set_price_list_category(M, price_list_ids, category_id, apply_to_items: bool = True, subgroup_id=None) -> int:
    ids = [int(value) for value in price_list_ids if value]
    if not ids:
        return 0
    if subgroup_id:
        category_id = subgroup_parent_id(M, subgroup_id)
    from . import product_catalog
    if apply_to_items:
        for price_list_id in ids:
            product_catalog.sync_price_list(M, price_list_id)
    changed_item_ids = []
    with M.db() as con:
        con.executemany("UPDATE price_lists SET category_id=? WHERE id=?", [(category_id, pid) for pid in ids])
        if apply_to_items:
            marks = ",".join("?" for _ in ids)
            changed_item_ids = [int(row[0]) for row in con.execute(
                f"SELECT id FROM price_list_items WHERE price_list_id IN ({marks})", ids
            ).fetchall()]
            con.executemany(
                "UPDATE price_list_items SET category_id=?,subgroup_id=? WHERE id=?",
                [(category_id, subgroup_id, item_id) for item_id in changed_item_ids],
            )
    if changed_item_ids:
        product_catalog.propagate_taxonomy_from_items(M, "price_list_items", changed_item_ids)
    return len(ids)


def choose_category(M, parent, title: str = "Vybrat produktovou skupinu", current_id=None, allow_auto: bool = False):
    rows = list_categories(M)
    dialog = M.tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    frame = M.ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    M.ttk.Label(frame, text=title, font=("Calibri", 13, "bold")).pack(anchor="w")
    labels = [UNASSIGNED] + [row["name"] for row in rows]
    mapping = {UNASSIGNED: None, **{row["name"]: int(row["id"]) for row in rows}}
    initial = category_name(M, current_id) if current_id else UNASSIGNED
    value = M.tk.StringVar(value=initial if initial in labels else UNASSIGNED)
    M.safe_combobox(frame, textvariable=value, values=labels, state="readonly", width=62).pack(fill="x", pady=(10, 14))
    result = {"value": "cancel"}

    def finish():
        result["value"] = mapping.get(value.get())
        dialog.destroy()

    buttons = M.ttk.Frame(frame)
    buttons.pack(fill="x")
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Vybrat", style="Accent.TButton", command=finish).pack(side="right", padx=(0, 6))
    try:
        M.center_dialog(dialog, parent)
    except Exception:
        pass
    dialog.wait_window()
    return result["value"]


def choose_taxonomy(
    M, parent, title: str = "Přiřadit produktovou skupinu a podskupinu",
    current_category_id=None, current_subgroup_id=None,
):
    if current_subgroup_id:
        current_category_id = subgroup_parent_id(M, current_subgroup_id) or current_category_id
    groups = list_categories(M)
    group_mapping = {UNASSIGNED: None, **{str(row["name"]): int(row["id"]) for row in groups}}
    dialog = M.tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.grab_set()
    dialog.resizable(False, False)
    frame = M.ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    M.ttk.Label(frame, text=title, font=("Calibri", 13, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
    )
    group_var = M.tk.StringVar(value=category_name(M, current_category_id) or UNASSIGNED)
    subgroup_var = M.tk.StringVar(value=subgroup_name(M, current_subgroup_id) or NO_SUBGROUP)
    M.ttk.Label(frame, text="Produktová skupina").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
    M.safe_combobox(frame, textvariable=group_var, values=list(group_mapping), state="readonly", width=74).grid(
        row=1, column=1, sticky="ew", pady=5
    )
    M.ttk.Label(frame, text="Podskupina").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
    subgroup_box = M.safe_combobox(frame, textvariable=subgroup_var, values=[NO_SUBGROUP], state="readonly", width=74)
    subgroup_box.grid(row=2, column=1, sticky="ew", pady=5)
    subgroup_mapping = {NO_SUBGROUP: None}

    def update_subgroups(*_):
        nonlocal subgroup_mapping
        category_id = group_mapping.get(group_var.get())
        subgroup_mapping = {
            NO_SUBGROUP: None,
            **{str(row["name"]): int(row["id"]) for row in list_subgroups(M, category_id) if category_id},
        }
        subgroup_box.configure(values=list(subgroup_mapping))
        if subgroup_var.get() not in subgroup_mapping:
            subgroup_var.set(NO_SUBGROUP)

    group_var.trace_add("write", update_subgroups)
    update_subgroups()
    current = subgroup_name(M, current_subgroup_id)
    if current in subgroup_mapping:
        subgroup_var.set(current)
    result = {"value": "cancel"}

    def finish():
        result["value"] = (group_mapping.get(group_var.get()), subgroup_mapping.get(subgroup_var.get()))
        dialog.destroy()

    buttons = M.ttk.Frame(frame)
    buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(14, 0))
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Přiřadit", style="Accent.TButton", command=finish).pack(side="right", padx=(0, 6))
    try:
        M.center_dialog(dialog, parent)
    except Exception:
        pass
    dialog.wait_window()
    return result["value"]


def _invalidate(M, app=None):
    try:
        M.invalidate_product_category_cache()
    except Exception:
        pass
    if app is not None:
        try:
            app._price_filter_cache = None
            app._price_taxonomy_cache = None
            app._commercial_price_summary_cache = None
        except Exception:
            pass
        try:
            dirty = set(getattr(app, "_turto_dirty_pages", set()))
            dirty.update(("pricelists", "offers"))
            app._turto_dirty_pages = dirty
        except Exception:
            pass


def manage_categories(M, app) -> None:
    """Manage the catalogue hierarchy with a live inspector and native drag-and-drop."""
    from . import product_catalog

    product_catalog.sync_all_unlinked(M, max_documents=25)
    dialog = M.tk.Toplevel(app)
    dialog.title("Produktové skupiny a podskupiny")
    dialog.transient(app)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 1520, 850)

    outer = M.ttk.Frame(dialog, padding=16)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(3, weight=1)
    M.ttk.Label(outer, text="Produktové skupiny a podskupiny", font=("Calibri", 17, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    M.ttk.Label(
        outer,
        text=("Přetáhněte skupinu nebo podskupinu na nové místo. Přesun podskupiny do jiné skupiny "
              "automaticky zachová její stabilní ID a promítne novou hlavní skupinu do katalogu, Ceníků i Nabídek."),
        style="PageSubtitle.TLabel", wraplength=1350,
    ).grid(row=1, column=0, sticky="w", pady=(2, 8))

    toolbar = M.ttk.Frame(outer, style="Panel.TFrame", padding=(10, 8))
    toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 7))
    toolbar.columnconfigure(1, weight=1)
    search = M.tk.StringVar()
    show_inactive = M.tk.BooleanVar(value=False)
    M.ttk.Label(toolbar, text="Hledat", style="FilterLabel.TLabel").grid(row=0, column=0, sticky="w")
    search_entry = M.ttk.Entry(toolbar, textvariable=search)
    search_entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 10))
    M.ttk.Checkbutton(toolbar, text="Zobrazit neaktivní", variable=show_inactive).grid(
        row=1, column=2, sticky="e", padx=(6, 0)
    )

    pane = M.ttk.Panedwindow(outer, orient="horizontal")
    pane.grid(row=3, column=0, sticky="nsew")
    left = M.ttk.Frame(pane, style="Panel.TFrame", padding=8)
    right = M.ttk.Frame(pane, style="Panel.TFrame", padding=12)
    pane.add(left, weight=3)
    pane.add(right, weight=2)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(1, weight=1)
    right.columnconfigure(1, weight=1)

    hierarchy_status = M.tk.StringVar(value="")
    M.ttk.Label(left, textvariable=hierarchy_status, style="PageSubtitle.TLabel", wraplength=720).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
    )
    cols = ("Typ", "Stav", "Produktů", "Ceníků", "Nabídek", "Marže", "Sleva", "Zobrazení ceny")
    tree = M.ttk.Treeview(left, columns=cols, show="tree headings", selectmode="browse")
    tree.heading("#0", text="Skupina / podskupina")
    tree.column("#0", width=430, minwidth=260, anchor="w", stretch=True)
    for col, width, anchor in (
        ("Typ", 95, "w"), ("Stav", 85, "w"), ("Produktů", 75, "e"),
        ("Ceníků", 65, "e"), ("Nabídek", 70, "e"), ("Marže", 75, "e"),
        ("Sleva", 75, "e"), ("Zobrazení ceny", 155, "w"),
    ):
        tree.heading(col, text=col)
        tree.column(col, width=width, minwidth=55, anchor=anchor, stretch=False)
    tree.grid(row=1, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(left, orient="vertical", command=tree.yview)
    ys.grid(row=1, column=1, sticky="ns")
    tree.configure(yscrollcommand=ys.set)
    try:
        tree.tag_configure("drop_target", background="#dcecff", foreground="#17324a")
    except Exception:
        pass

    left_buttons = M.ttk.Frame(left)
    left_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(7, 0))

    detail_title = M.tk.StringVar(value="Vyberte skupinu nebo podskupinu")
    detail_path = M.tk.StringVar(value="")
    M.ttk.Label(right, textvariable=detail_title, font=("Calibri", 14, "bold"), wraplength=480).grid(
        row=0, column=0, columnspan=2, sticky="w"
    )
    M.ttk.Label(right, textvariable=detail_path, style="PageSubtitle.TLabel", wraplength=480).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(1, 12)
    )

    name_var = M.tk.StringVar()
    parent_var = M.tk.StringVar()
    margin_var = M.tk.StringVar(value="0")
    discount_var = M.tk.StringVar(value="0")
    show_recommended = M.tk.BooleanVar(value=True)
    active_var = M.tk.BooleanVar(value=True)
    detail_info = M.tk.StringVar(value="")
    fields = (
        ("Název", name_var),
        ("Nadřazená skupina", parent_var),
        ("Základní marže [%]", margin_var),
        ("Základní sleva [%]", discount_var),
    )
    widgets = {}
    for index, (label, variable) in enumerate(fields, 2):
        M.ttk.Label(right, text=label, style="FilterLabel.TLabel").grid(
            row=index, column=0, sticky="w", padx=(0, 10), pady=5
        )
        if label == "Nadřazená skupina":
            widget = M.safe_combobox(right, textvariable=variable, values=[], state="readonly", width=52)
        else:
            widget = M.ttk.Entry(right, textvariable=variable, width=54)
        widget.grid(row=index, column=1, sticky="ew", pady=5)
        widgets[label] = widget
    M.ttk.Checkbutton(
        right, text="V Ceníku zobrazovat doporučenou i výslednou cenu", variable=show_recommended,
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))
    show_widget = right.grid_slaves(row=6, column=0)[0]
    M.ttk.Checkbutton(right, text="Aktivní", variable=active_var).grid(
        row=7, column=0, columnspan=2, sticky="w", pady=4
    )
    M.ttk.Label(right, textvariable=detail_info, style="PageSubtitle.TLabel", wraplength=490).grid(
        row=8, column=0, columnspan=2, sticky="w", pady=(10, 8)
    )
    detail_buttons = M.ttk.Frame(right)
    detail_buttons.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    row_map: dict[str, dict] = {}
    state = {
        "kind": None,
        "id": None,
        "new": False,
        "drag_source": None,
        "drop_target": None,
        "drag_started": False,
        "suspend_selection": False,
    }

    def group_values():
        rows = list_categories(M, include_inactive=True)
        return [str(row["name"]) for row in rows], {str(row["name"]): int(row["id"]) for row in rows}

    def parse_percent(variable, label):
        value = variable.get().strip().replace(" ", "").replace(",", ".")
        try:
            number = float(value or 0)
        except Exception:
            raise ValueError(f"Pole „{label}“ musí obsahovat číslo.")
        if not -1000 <= number <= 1000:
            raise ValueError(f"Pole „{label}“ je mimo povolený rozsah.")
        return number

    def selected():
        selection = tree.selection()
        iid = str(selection[0]) if selection else ""
        if iid.startswith("g") and iid[1:].isdigit():
            return "group", int(iid[1:])
        if iid.startswith("s") and iid[1:].isdigit():
            return "subgroup", int(iid[1:])
        return None, None

    def usage_count(con, kind, row_id):
        checks = []
        if kind == "group":
            checks.extend((("price_lists", "category_id"), ("product_subgroups", "category_id")))
        for table in ("price_list_items", "supplier_offer_items", "business_document_items", "catalog_products"):
            checks.append((table, "category_id" if kind == "group" else "subgroup_id"))
        total = 0
        for table, column in checks:
            if column in _columns(con, table):
                total += int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (row_id,)).fetchone()[0] or 0)
        return total

    def clear_drop_target():
        iid = state.get("drop_target")
        if iid and tree.exists(iid):
            tags = tuple(tag for tag in tree.item(iid, "tags") if tag != "drop_target")
            tree.item(iid, tags=tags)
        state["drop_target"] = None
        try:
            tree.configure(cursor="")
        except Exception:
            pass

    def mark_drop_target(iid):
        if iid == state.get("drop_target"):
            return
        clear_drop_target()
        if iid and tree.exists(iid):
            tags = tuple(tree.item(iid, "tags"))
            if "drop_target" not in tags:
                tree.item(iid, tags=tags + ("drop_target",))
            state["drop_target"] = iid
            try:
                tree.configure(cursor="fleur")
            except Exception:
                pass

    def refresh(select_iid=None):
        opened = {iid for iid in tree.get_children("") if tree.item(iid, "open")}
        current = str(select_iid or (tree.selection()[0] if tree.selection() else ""))
        query = search.get().strip().casefold()
        for iid in tree.get_children(""):
            tree.delete(iid)
        row_map.clear()
        with M.db() as con:
            groups = con.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM catalog_products p WHERE p.category_id=c.id) product_count,
                          (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i WHERE i.category_id=c.id) list_count,
                          (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i WHERE i.category_id=c.id) offer_count
                   FROM product_categories c
                   ORDER BY c.active DESC,c.sort_order,c.name COLLATE CZECH,c.id"""
            ).fetchall()
            subgroups = con.execute(
                """SELECT s.*,coalesce(c.show_recommended_price,1) show_recommended_price,c.name category_name,
                          (SELECT COUNT(*) FROM catalog_products p WHERE p.subgroup_id=s.id) product_count,
                          (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i WHERE i.subgroup_id=s.id) list_count,
                          (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i WHERE i.subgroup_id=s.id) offer_count
                   FROM product_subgroups s JOIN product_categories c ON c.id=s.category_id
                   ORDER BY c.active DESC,c.sort_order,c.name COLLATE CZECH,
                            s.active DESC,s.sort_order,s.name COLLATE CZECH,s.id"""
            ).fetchall()
        by_group: dict[int, list] = {}
        for row in subgroups:
            by_group.setdefault(int(row["category_id"]), []).append(row)
        visible_groups = 0
        visible_subgroups = 0
        for row in groups:
            group_id = int(row["id"])
            children = by_group.get(group_id, [])
            if not show_inactive.get():
                children = [item for item in children if int(item["active"] or 0)]
            group_match = not query or query in str(row["name"] or "").casefold()
            child_matches = [item for item in children if not query or query in str(item["name"] or "").casefold()]
            if (not show_inactive.get() and not int(row["active"] or 0)) or (query and not group_match and not child_matches):
                continue
            iid = f"g{group_id}"
            display = "Doporučená i výsledná" if row["show_recommended_price"] else "Pouze výsledná"
            tags = ("status_cancel",) if not row["active"] else ()
            tree.insert(
                "", "end", iid=iid, text=row["name"],
                values=("Skupina", "Aktivní" if row["active"] else "Neaktivní", row["product_count"],
                        row["list_count"], row["offer_count"], f"{_number(row['default_margin_pct']):g} %",
                        f"{_number(row['default_discount_pct']):g} %", display),
                tags=tags, open=(iid in opened or bool(query) or current.startswith("s") and any(f"s{x['id']}" == current for x in children)),
            )
            row_map[iid] = {"kind": "group", **dict(row)}
            visible_groups += 1
            for subgroup in child_matches if query else children:
                sid = f"s{subgroup['id']}"
                tree.insert(
                    iid, "end", iid=sid, text=subgroup["name"],
                    values=("Podskupina", "Aktivní" if subgroup["active"] else "Neaktivní", subgroup["product_count"],
                            subgroup["list_count"], subgroup["offer_count"],
                            f"{_number(subgroup['default_margin_pct']):g} %",
                            f"{_number(subgroup['default_discount_pct']):g} %", display),
                    tags=("status_cancel",) if not subgroup["active"] else (),
                )
                row_map[sid] = {"kind": "subgroup", **dict(subgroup)}
                visible_subgroups += 1
        hierarchy_status.set(
            f"Zobrazeno skupin: {visible_groups} · podskupin: {visible_subgroups} · "
            "pořadí změníte přetažením nebo klávesami Ctrl+↑ / Ctrl+↓"
        )
        if current and tree.exists(current):
            state["suspend_selection"] = True
            tree.selection_set(current)
            tree.see(current)
            state["suspend_selection"] = False
        elif tree.get_children(""):
            first = tree.get_children("")[0]
            state["suspend_selection"] = True
            tree.selection_set(first)
            state["suspend_selection"] = False
        load_selection()

    def set_widget_state(widget, enabled):
        try:
            widget.configure(state="normal" if enabled else "disabled")
        except Exception:
            try:
                widget.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                pass

    def load_selection(*_):
        if state.get("suspend_selection"):
            return
        kind, row_id = selected()
        row = row_map.get(("g" if kind == "group" else "s") + str(row_id)) if kind and row_id else None
        state.update(kind=kind, id=row_id, new=False)
        if not row:
            detail_title.set("Vyberte skupinu nebo podskupinu")
            detail_path.set("")
            name_var.set("")
            detail_info.set("")
            return
        values, mapping = group_values()
        widgets["Nadřazená skupina"].configure(values=values)
        name_var.set(str(row["name"] or ""))
        margin_var.set(f"{_number(row['default_margin_pct']):g}")
        discount_var.set(f"{_number(row['default_discount_pct']):g}")
        active_var.set(bool(row["active"]))
        if kind == "group":
            detail_title.set("Produktová skupina")
            detail_path.set(str(row["name"] or ""))
            parent_var.set("")
            show_recommended.set(bool(row["show_recommended_price"]))
            set_widget_state(widgets["Nadřazená skupina"], False)
            set_widget_state(show_widget, True)
        else:
            detail_title.set("Podskupina")
            detail_path.set(f"{row['category_name']} › {row['name']}")
            parent_var.set(str(row["category_name"] or ""))
            show_recommended.set(bool(row["show_recommended_price"]))
            set_widget_state(widgets["Nadřazená skupina"], True)
            set_widget_state(show_widget, False)
        detail_info.set(
            f"Produktů: {row['product_count']} · Ceníků: {row['list_count']} · Nabídek: {row['offer_count']}\n"
            "Přejmenování ani změna pořadí nepřepisuje historické ceny; pracuje se stabilním ID."
        )

    def begin_new(kind):
        values, mapping = group_values()
        widgets["Nadřazená skupina"].configure(values=values)
        state.update(kind=kind, id=None, new=True)
        name_var.set("")
        margin_var.set("0")
        discount_var.set("0")
        active_var.set(True)
        show_recommended.set(True)
        if kind == "group":
            detail_title.set("Nová produktová skupina")
            detail_path.set("Bude vložena na konec aktivních skupin")
            parent_var.set("")
            set_widget_state(widgets["Nadřazená skupina"], False)
            set_widget_state(show_widget, True)
        else:
            selected_kind, selected_id = selected()
            parent_id = selected_id if selected_kind == "group" else subgroup_parent_id(M, selected_id) if selected_kind == "subgroup" else None
            selected_name = category_name(M, parent_id)
            parent_var.set(selected_name or (values[0] if values else ""))
            detail_title.set("Nová podskupina")
            detail_path.set("Vyberte nadřazenou skupinu")
            set_widget_state(widgets["Nadřazená skupina"], True)
            set_widget_state(show_widget, False)
        detail_info.set("Po uložení můžete záznam okamžitě přetáhnout na požadované místo.")
        widgets["Název"].focus_set()

    def save():
        kind = state.get("kind")
        row_id = state.get("id")
        if kind not in {"group", "subgroup"}:
            return M.messagebox.showinfo("Produktové skupiny", "Vyberte nebo vytvořte skupinu či podskupinu.", parent=dialog)
        name = name_var.get().strip()
        if not name:
            return M.messagebox.showwarning("Produktové skupiny", "Vyplňte název.", parent=dialog)
        try:
            margin = parse_percent(margin_var, "Základní marže")
            discount = parse_percent(discount_var, "Základní sleva")
        except ValueError as exc:
            return M.messagebox.showwarning("Produktové skupiny", str(exc), parent=dialog)
        group_names, group_map = group_values()
        target_iid = None
        try:
            if kind == "group":
                with M.db() as con:
                    if row_id:
                        con.execute(
                            """UPDATE product_categories SET name=?,default_margin_pct=?,default_discount_pct=?,
                               show_recommended_price=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                            (name, margin, discount, 1 if show_recommended.get() else 0, 1 if active_var.get() else 0, row_id),
                        )
                        target_id = int(row_id)
                    else:
                        sort_order = int(con.execute("SELECT coalesce(MAX(sort_order),0)+10 FROM product_categories").fetchone()[0] or 10)
                        target_id = int(con.execute(
                            """INSERT INTO product_categories(
                                 name,keywords,sort_order,active,default_margin_pct,default_discount_pct,show_recommended_price
                               ) VALUES(?,'',?,?,?,?,?)""",
                            (name, sort_order, 1 if active_var.get() else 0, margin, discount, 1 if show_recommended.get() else 0),
                        ).lastrowid)
                target_iid = f"g{target_id}"
            else:
                category_id = group_map.get(parent_var.get())
                if not category_id:
                    return M.messagebox.showwarning("Produktové skupiny", "Vyberte nadřazenou skupinu.", parent=dialog)
                if row_id:
                    old_parent = subgroup_parent_id(M, row_id)
                    with M.db() as con:
                        duplicate = con.execute(
                            """SELECT id FROM product_subgroups
                               WHERE category_id=? AND id<>? AND lower(trim(name))=lower(trim(?)) LIMIT 1""",
                            (category_id, row_id, name),
                        ).fetchone()
                        if duplicate:
                            raise M.sqlite3.IntegrityError("duplicate subgroup")
                        con.execute(
                            """UPDATE product_subgroups SET name=?,default_margin_pct=?,default_discount_pct=?,active=?,
                               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                            (name, margin, discount, 1 if active_var.get() else 0, row_id),
                        )
                    if old_parent != category_id:
                        reorder_subgroup(M, row_id, category_id)
                    target_id = int(row_id)
                else:
                    with M.db() as con:
                        sort_order = int(con.execute(
                            "SELECT coalesce(MAX(sort_order),0)+10 FROM product_subgroups WHERE category_id=?",
                            (category_id,),
                        ).fetchone()[0] or 10)
                        target_id = int(con.execute(
                            """INSERT INTO product_subgroups(
                                 category_id,name,keywords,sort_order,active,default_margin_pct,default_discount_pct
                               ) VALUES(?,?,'',?,?,?,?)""",
                            (category_id, name, sort_order, 1 if active_var.get() else 0, margin, discount),
                        ).lastrowid)
                target_iid = f"s{target_id}"
        except M.sqlite3.IntegrityError:
            return M.messagebox.showwarning(
                "Produktové skupiny", "Stejný název už v této úrovni existuje.", parent=dialog
            )
        except ValueError as exc:
            return M.messagebox.showwarning("Produktové skupiny", str(exc), parent=dialog)
        _invalidate(M, app)
        refresh(target_iid)

    def open_products():
        kind = state.get("kind")
        row_id = state.get("id")
        if not row_id:
            return M.messagebox.showinfo("Produktové skupiny", "Nejdříve záznam uložte.", parent=dialog)
        category_id = row_id if kind == "group" else subgroup_parent_id(M, row_id)
        subgroup_id = row_id if kind == "subgroup" else None
        try:
            dialog.grab_release()
        except Exception:
            pass
        product_catalog.open_product_catalog(M, app, category_id, subgroup_id)
        try:
            dialog.grab_set()
        except Exception:
            pass
        refresh(("g" if kind == "group" else "s") + str(row_id))

    def toggle_active():
        kind, row_id = selected()
        if not kind:
            return
        table = "product_categories" if kind == "group" else "product_subgroups"
        with M.db() as con:
            row = con.execute(f"SELECT active FROM {table} WHERE id=?", (row_id,)).fetchone()
            if row:
                con.execute(
                    f"UPDATE {table} SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (0 if row["active"] else 1, row_id),
                )
        _invalidate(M, app)
        refresh(("g" if kind == "group" else "s") + str(row_id))

    def remove():
        kind, row_id = selected()
        if not kind:
            return
        table = "product_categories" if kind == "group" else "product_subgroups"
        with M.db() as con:
            row = con.execute(f"SELECT name FROM {table} WHERE id=?", (row_id,)).fetchone()
            used = usage_count(con, kind, row_id)
        if not row:
            return
        if used:
            if M.messagebox.askyesno(
                "Produktové skupiny",
                f"„{row['name']}“ je použita v {used} vazbách. Kvůli historii ji nelze smazat.\n\nOznačit ji jako neaktivní?",
                parent=dialog,
            ):
                with M.db() as con:
                    con.execute(f"UPDATE {table} SET active=0,updated_at=CURRENT_TIMESTAMP WHERE id=?", (row_id,))
                _invalidate(M, app)
                refresh()
            return
        if M.messagebox.askyesno("Produktové skupiny", f"Trvale odstranit „{row['name']}“?", parent=dialog):
            with M.db() as con:
                con.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
            _invalidate(M, app)
            refresh()

    def move_step(delta):
        kind, row_id = selected()
        selection = tree.selection()
        if not kind or not selection:
            return
        iid = str(selection[0])
        parent_iid = tree.parent(iid)
        siblings = [item for item in tree.get_children(parent_iid) if str(item).startswith("g" if kind == "group" else "s")]
        try:
            index = siblings.index(iid)
        except ValueError:
            return
        target_index = index + int(delta)
        if not 0 <= target_index < len(siblings):
            return
        target_iid = siblings[target_index]
        try:
            if kind == "group":
                reorder_category(M, row_id, int(target_iid[1:]), after=delta > 0)
            else:
                reorder_subgroup(M, row_id, int(parent_iid[1:]), int(target_iid[1:]), after=delta > 0)
        except (ValueError, M.sqlite3.IntegrityError) as exc:
            return M.messagebox.showwarning("Produktové skupiny", str(exc), parent=dialog)
        _invalidate(M, app)
        refresh(iid)

    def on_drag_press(event):
        iid = tree.identify_row(event.y)
        state["drag_source"] = iid if iid in row_map else None
        state["drag_started"] = False
        clear_drop_target()

    def valid_drop_target(source_iid, candidate_iid):
        if not source_iid or not candidate_iid or source_iid == candidate_iid:
            return None
        if source_iid.startswith("g"):
            if candidate_iid.startswith("s"):
                candidate_iid = tree.parent(candidate_iid)
            return candidate_iid if candidate_iid.startswith("g") and candidate_iid != source_iid else None
        if source_iid.startswith("s"):
            return candidate_iid if candidate_iid.startswith(("g", "s")) else None
        return None

    def on_drag_motion(event):
        source_iid = state.get("drag_source")
        if not source_iid:
            return
        state["drag_started"] = True
        height = tree.winfo_height()
        if 0 <= event.y < height:
            if event.y < 26:
                tree.yview_scroll(-1, "units")
            elif event.y > height - 26:
                tree.yview_scroll(1, "units")
        candidate = valid_drop_target(source_iid, tree.identify_row(event.y))
        mark_drop_target(candidate)

    def on_drag_release(event):
        source_iid = state.get("drag_source")
        target_iid = state.get("drop_target")
        drag_started = bool(state.get("drag_started"))
        clear_drop_target()
        state.update(drag_source=None, drag_started=False)
        if not drag_started or not source_iid or not target_iid:
            return
        try:
            bbox = tree.bbox(target_iid)
            after = bool(bbox and event.y > bbox[1] + bbox[3] / 2)
            if source_iid.startswith("g"):
                reorder_category(M, int(source_iid[1:]), int(target_iid[1:]), after=after)
            else:
                source_id = int(source_iid[1:])
                old_parent = subgroup_parent_id(M, source_id)
                if target_iid.startswith("g"):
                    target_category = int(target_iid[1:])
                    target_subgroup = None
                    after = True
                else:
                    target_subgroup = int(target_iid[1:])
                    target_category = subgroup_parent_id(M, target_subgroup)
                if old_parent != target_category:
                    label = taxonomy_path(M, target_category, target_subgroup)
                    if not M.messagebox.askyesno(
                        "Přesunout podskupinu",
                        f"Přesunout podskupinu včetně všech navázaných produktů do:\n\n{label}?",
                        parent=dialog,
                    ):
                        return
                reorder_subgroup(M, source_id, target_category, target_subgroup, after=after)
        except M.sqlite3.IntegrityError:
            return M.messagebox.showwarning(
                "Produktové skupiny", "V cílové skupině už existuje podskupina se stejným názvem.", parent=dialog
            )
        except ValueError as exc:
            return M.messagebox.showwarning("Produktové skupiny", str(exc), parent=dialog)
        _invalidate(M, app)
        refresh(source_iid)

    M.ttk.Button(left_buttons, text="+ Nová skupina", style="Accent.TButton", command=lambda: begin_new("group")).pack(side="left")
    M.ttk.Button(left_buttons, text="+ Nová podskupina", command=lambda: begin_new("subgroup")).pack(side="left", padx=4)
    M.ttk.Button(left_buttons, text="↑", width=3, command=lambda: move_step(-1)).pack(side="left", padx=(12, 2))
    M.ttk.Button(left_buttons, text="↓", width=3, command=lambda: move_step(1)).pack(side="left", padx=2)
    M.ttk.Button(left_buttons, text="Produkty ve výběru…", command=open_products).pack(side="right")

    save_button = M.ttk.Button(detail_buttons, text="Uložit změny", style="Accent.TButton", command=save)
    save_button.pack(fill="x")
    M.ttk.Button(detail_buttons, text="Aktivní / neaktivní", command=toggle_active).pack(fill="x", pady=(5, 0))
    M.ttk.Button(detail_buttons, text="Odebrat", command=remove).pack(fill="x", pady=(5, 0))
    M.ttk.Button(detail_buttons, text="Zavřít", command=dialog.destroy).pack(fill="x", pady=(14, 0))

    context = M.tk.Menu(tree, tearoff=False)
    context.add_command(label="Upravit", command=lambda: widgets["Název"].focus_set())
    context.add_command(label="Nová podskupina", command=lambda: begin_new("subgroup"))
    context.add_separator()
    context.add_command(label="Posunout výš", command=lambda: move_step(-1))
    context.add_command(label="Posunout níž", command=lambda: move_step(1))
    context.add_command(label="Produkty ve výběru…", command=open_products)
    context.add_separator()
    context.add_command(label="Aktivní / neaktivní", command=toggle_active)
    context.add_command(label="Odebrat", command=remove)

    def popup(event):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            load_selection()
        try:
            context.tk_popup(event.x_root, event.y_root)
        finally:
            context.grab_release()

    tree.bind("<<TreeviewSelect>>", load_selection, add="+")
    tree.bind("<Double-1>", lambda _event: widgets["Název"].focus_set(), add="+")
    tree.bind("<Button-1>", on_drag_press, add="+")
    tree.bind("<B1-Motion>", on_drag_motion, add="+")
    tree.bind("<ButtonRelease-1>", on_drag_release, add="+")
    tree.bind("<Button-3>", popup, add="+")
    tree.bind("<Control-Up>", lambda _event: move_step(-1), add="+")
    tree.bind("<Control-Down>", lambda _event: move_step(1), add="+")
    tree.bind("<F2>", lambda _event: widgets["Název"].focus_set(), add="+")
    tree.bind("<Delete>", lambda _event: remove(), add="+")
    dialog.bind("<Control-s>", lambda _event: save(), add="+")
    search.trace_add("write", lambda *_: refresh())
    show_inactive.trace_add("write", lambda *_: refresh())
    refresh()
    dialog.wait_window()


__all__ = [
    "UNASSIGNED", "NO_SUBGROUP", "list_categories", "list_subgroups",
    "category_id_by_name", "subgroup_id_by_name", "category_name", "subgroup_name",
    "subgroup_parent_id", "taxonomy_path", "classify_text", "classify_subgroup_text",
    "classify_item", "classify_item_taxonomy", "majority_category",
    "set_item_taxonomy", "move_subgroup", "reorder_category", "reorder_subgroup", "autocategorize_price_list",
    "set_price_list_category", "choose_category", "choose_taxonomy", "manage_categories",
]
