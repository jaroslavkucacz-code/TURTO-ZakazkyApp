"""Canonical product-group and subgroup catalogue for TURTO CRM.

The catalogue stores stable IDs. Renaming a group or subgroup therefore appears
immediately on all already assigned Ceník and supplier-offer products without
rewriting historical prices. Used entries are deactivated rather than deleted.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

UNASSIGNED = "Nezařazeno"
NO_SUBGROUP = "Bez podskupiny"


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def list_categories(M, include_inactive: bool = False):
    with M.db() as con:
        return con.execute(
            """SELECT id,name,parent_id,keywords,active,sort_order
               FROM product_categories
               WHERE (?=1 OR active=1)
               ORDER BY active DESC,sort_order,name COLLATE CZECH""",
            (1 if include_inactive else 0,),
        ).fetchall()


def list_subgroups(M, category_id=None, include_inactive: bool = False):
    with M.db() as con:
        return con.execute(
            """SELECT s.id,s.category_id,s.name,s.keywords,s.active,s.sort_order,
                      c.name category_name,c.active category_active
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


def classify_text(M, value: object):
    hay = _norm(value)
    if not hay:
        return None
    fallback = None
    for row in list_categories(M):
        if _norm(row["name"]) == "ostatni":
            fallback = int(row["id"])
            continue
        keywords = [part.strip() for part in re.split(r"[|;\n]+", str(row["keywords"] or "")) if part.strip()]
        for keyword in keywords:
            needle = _norm(keyword)
            if needle and needle in hay:
                return int(row["id"])
    return fallback


def classify_subgroup_text(M, category_id, value: object):
    if not category_id:
        return None
    hay = _norm(value)
    if not hay:
        return None
    matches = []
    for row in list_subgroups(M, category_id):
        needles = [
            _norm(part) for part in re.split(r"[|;\n]+", str(row["keywords"] or "")) if _norm(part)
        ]
        score = max((len(needle) for needle in needles if needle in hay), default=0)
        if score:
            matches.append((score, -int(row["sort_order"] or 0), int(row["id"])))
    return max(matches)[2] if matches else None


def _row_text(row) -> str:
    fields = (
        "product_code", "supplier_item_code", "item_key", "name", "original_name",
        "description", "details", "condition_text", "dimensions", "source_row_json",
    )
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    return " ".join(str(row[key] or "") for key in fields if key in keys)


def classify_item(M, row):
    return classify_text(M, _row_text(row))


def classify_item_taxonomy(M, row):
    keys = set(row.keys()) if hasattr(row, "keys") else set(row)
    category_id = int(row["category_id"]) if "category_id" in keys and row["category_id"] else None
    subgroup_id = int(row["subgroup_id"]) if "subgroup_id" in keys and row["subgroup_id"] else None
    if subgroup_id:
        parent = subgroup_parent_id(M, subgroup_id)
        if parent:
            category_id = parent
    text = _row_text(row)
    category_id = category_id or classify_text(M, text)
    subgroup_id = subgroup_id or classify_subgroup_text(M, category_id, text)
    return category_id, subgroup_id


def majority_category(M, items) -> int | None:
    counts: Counter[int] = Counter()
    for item in list(items or [])[:500]:
        cid = classify_text(M, _row_text(item))
        if cid:
            counts[int(cid)] += 1
    return counts.most_common(1)[0][0] if counts else None


def set_item_taxonomy(M, table: str, item_ids, category_id=None, subgroup_id=None) -> int:
    allowed = {"price_list_items", "supplier_offer_items", "business_document_items"}
    if table not in allowed:
        raise ValueError("Nepodporovaný typ produktové položky.")
    ids = [int(value) for value in item_ids if value]
    if not ids:
        return 0
    if subgroup_id:
        parent = subgroup_parent_id(M, subgroup_id)
        if not parent:
            raise ValueError("Vybraná podskupina už neexistuje.")
        category_id = parent
    with M.db() as con:
        cols = _columns(con, table)
        if "subgroup_id" not in cols:
            raise RuntimeError("Databáze ještě neobsahuje podporu produktových podskupin.")
        con.executemany(
            f"UPDATE {table} SET category_id=?,subgroup_id=? WHERE id=?",
            [(category_id, subgroup_id, item_id) for item_id in ids],
        )
    return len(ids)


def move_subgroup(M, subgroup_id: int, category_id: int) -> None:
    subgroup_id = int(subgroup_id)
    category_id = int(category_id)
    with M.db() as con:
        con.execute(
            "UPDATE product_subgroups SET category_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (category_id, subgroup_id),
        )
        for table in ("price_list_items", "supplier_offer_items", "business_document_items"):
            if {"category_id", "subgroup_id"}.issubset(_columns(con, table)):
                con.execute(
                    f"UPDATE {table} SET category_id=? WHERE subgroup_id=?",
                    (category_id, subgroup_id),
                )


def autocategorize_price_list(M, price_list_id: int, only_empty: bool = True) -> tuple[int, int]:
    with M.db() as con:
        header = con.execute("SELECT category_id FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
        rows = con.execute(
            """SELECT id,category_id,subgroup_id,product_code,supplier_item_code,item_key,name,description,
                      condition_text,dimensions,source_row_json
               FROM price_list_items WHERE price_list_id=? AND active=1""",
            (price_list_id,),
        ).fetchall()
    fallback = int(header["category_id"]) if header and header["category_id"] else None
    updates = []
    unassigned = 0
    for row in rows:
        old_category = int(row["category_id"]) if row["category_id"] else None
        old_subgroup = int(row["subgroup_id"]) if row["subgroup_id"] else None
        text = _row_text(row)
        guessed_category = classify_text(M, text) or fallback
        guessed_subgroup = classify_subgroup_text(M, guessed_category, text) if guessed_category else None
        if only_empty:
            category_id = old_category or guessed_category
            subgroup_id = old_subgroup or (
                classify_subgroup_text(M, category_id, text) if category_id else None
            )
            if old_subgroup:
                category_id = subgroup_parent_id(M, old_subgroup) or category_id
        else:
            category_id = guessed_category
            subgroup_id = guessed_subgroup
        if category_id:
            if category_id != old_category or subgroup_id != old_subgroup:
                updates.append((category_id, subgroup_id, int(row["id"])))
        else:
            unassigned += 1
    if updates:
        with M.db() as con:
            con.executemany(
                "UPDATE price_list_items SET category_id=?,subgroup_id=? WHERE id=?",
                updates,
            )
    return len(updates), unassigned


def set_price_list_category(M, price_list_ids, category_id, apply_to_items: bool = True, subgroup_id=None) -> int:
    ids = [int(value) for value in price_list_ids if value]
    if not ids:
        return 0
    if subgroup_id:
        category_id = subgroup_parent_id(M, subgroup_id)
    with M.db() as con:
        con.executemany("UPDATE price_lists SET category_id=? WHERE id=?", [(category_id, pid) for pid in ids])
        if apply_to_items:
            con.executemany(
                "UPDATE price_list_items SET category_id=?,subgroup_id=? WHERE price_list_id=?",
                [(category_id, subgroup_id, pid) for pid in ids],
            )
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
    labels = []
    mapping = {}
    if allow_auto:
        labels.append("Automaticky podle položek")
        mapping[labels[-1]] = "auto"
    labels.append(UNASSIGNED)
    mapping[labels[-1]] = None
    for row in rows:
        labels.append(row["name"])
        mapping[row["name"]] = int(row["id"])
    initial = category_name(M, current_id) if current_id else (labels[0] if allow_auto else UNASSIGNED)
    value = M.tk.StringVar(value=initial if initial in labels else labels[0])
    box = M.safe_combobox(frame, textvariable=value, values=labels, state="readonly", width=58)
    box.pack(fill="x", pady=(10, 14))
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
    group_box = M.safe_combobox(
        frame, textvariable=group_var, values=list(group_mapping), state="readonly", width=72
    )
    group_box.grid(row=1, column=1, sticky="ew", pady=5)
    M.ttk.Label(frame, text="Podskupina").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
    subgroup_box = M.safe_combobox(frame, textvariable=subgroup_var, values=[NO_SUBGROUP], state="readonly", width=72)
    subgroup_box.grid(row=2, column=1, sticky="ew", pady=5)
    subgroup_mapping = {NO_SUBGROUP: None}

    def update_subgroups(*_):
        nonlocal subgroup_mapping
        category_id = group_mapping.get(group_var.get())
        rows = list_subgroups(M, category_id) if category_id else []
        subgroup_mapping = {NO_SUBGROUP: None, **{str(row["name"]): int(row["id"]) for row in rows}}
        subgroup_box.configure(values=list(subgroup_mapping))
        if subgroup_var.get() not in subgroup_mapping:
            subgroup_var.set(NO_SUBGROUP)

    group_var.trace_add("write", update_subgroups)
    update_subgroups()
    if current_subgroup_id:
        current = subgroup_name(M, current_subgroup_id)
        if current in subgroup_mapping:
            subgroup_var.set(current)
    result = {"value": "cancel"}

    def finish():
        category_id = group_mapping.get(group_var.get())
        subgroup_id = subgroup_mapping.get(subgroup_var.get())
        if subgroup_id and not category_id:
            return M.messagebox.showwarning(
                "Produktové skupiny", "Podskupinu nelze zvolit bez produktové skupiny.", parent=dialog
            )
        result["value"] = (category_id, subgroup_id)
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
        except Exception:
            pass
        try:
            dirty = set(getattr(app, "_turto_dirty_pages", set()))
            dirty.update(("pricelists", "offers"))
            app._turto_dirty_pages = dirty
        except Exception:
            pass


def manage_categories(M, app) -> None:
    dialog = M.tk.Toplevel(app)
    dialog.title("Produktové skupiny a podskupiny")
    dialog.transient(app)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 1280, 760)
    outer = M.ttk.Frame(dialog, padding=16)
    outer.pack(fill="both", expand=True)
    outer.rowconfigure(2, weight=1)
    outer.columnconfigure(0, weight=1)
    M.ttk.Label(outer, text="Produktové skupiny a podskupiny", font=("Calibri", 16, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    M.ttk.Label(
        outer,
        text=("Přejmenování se ihned projeví u všech již přiřazených položek Ceníků i cenových Nabídek. "
              "Použité záznamy se kvůli historii pouze deaktivují."),
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))
    cols = ("Typ", "Klíčová slova", "Stav", "Ceníků", "Položek ceníků", "Položek nabídek")
    tree = M.ttk.Treeview(outer, columns=cols, show="tree headings", selectmode="browse")
    tree.heading("#0", text="Skupina / podskupina")
    tree.column("#0", width=470, minwidth=260, anchor="w")
    for col, width in (("Typ", 105), ("Klíčová slova", 430), ("Stav", 90), ("Ceníků", 70),
                       ("Položek ceníků", 115), ("Položek nabídek", 115)):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=2, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
    ys.grid(row=2, column=1, sticky="ns")
    tree.configure(yscrollcommand=ys.set)

    def refresh(select_iid=None):
        opened = {iid for iid in tree.get_children("") if tree.item(iid, "open")}
        for iid in tree.get_children(""):
            tree.delete(iid)
        with M.db() as con:
            groups = con.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM price_lists p WHERE p.category_id=c.id) list_count,
                          (SELECT COUNT(*) FROM price_list_items i WHERE i.category_id=c.id) price_count,
                          (SELECT COUNT(*) FROM supplier_offer_items i WHERE i.category_id=c.id) offer_count
                   FROM product_categories c
                   ORDER BY c.active DESC,c.sort_order,c.name COLLATE CZECH"""
            ).fetchall()
            subgroups = con.execute(
                """SELECT s.*,
                          (SELECT COUNT(*) FROM price_list_items i WHERE i.subgroup_id=s.id) price_count,
                          (SELECT COUNT(*) FROM supplier_offer_items i WHERE i.subgroup_id=s.id) offer_count
                   FROM product_subgroups s
                   ORDER BY s.active DESC,s.sort_order,s.name COLLATE CZECH"""
            ).fetchall()
        by_group = {}
        for row in subgroups:
            by_group.setdefault(int(row["category_id"]), []).append(row)
        for row in groups:
            iid = f"g{row['id']}"
            tree.insert(
                "", "end", iid=iid, text=row["name"],
                values=("Skupina", row["keywords"] or "", "Aktivní" if row["active"] else "Neaktivní",
                        row["list_count"], row["price_count"], row["offer_count"]),
                tags=("status_cancel",) if not row["active"] else (),
                open=(iid in opened or bool(by_group.get(int(row["id"])) and not opened)),
            )
            for subgroup in by_group.get(int(row["id"]), []):
                sid = f"s{subgroup['id']}"
                tree.insert(
                    iid, "end", iid=sid, text=subgroup["name"],
                    values=("Podskupina", subgroup["keywords"] or "",
                            "Aktivní" if subgroup["active"] else "Neaktivní", "",
                            subgroup["price_count"], subgroup["offer_count"]),
                    tags=("status_cancel",) if not subgroup["active"] else (),
                )
        if select_iid and tree.exists(select_iid):
            tree.selection_set(select_iid)
            tree.see(select_iid)

    def selected():
        sel = tree.selection()
        if not sel:
            return None, None
        iid = str(sel[0])
        if iid.startswith("g"):
            return "group", int(iid[1:])
        if iid.startswith("s"):
            return "subgroup", int(iid[1:])
        return None, None

    def editor(kind: str, row_id=None, parent_group_id=None):
        groups = list_categories(M, include_inactive=True)
        values = {"name": "", "keywords": "", "sort_order": 100, "category_id": parent_group_id}
        if row_id:
            table = "product_categories" if kind == "group" else "product_subgroups"
            with M.db() as con:
                row = con.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
            if row:
                values.update(dict(row))
        win = M.tk.Toplevel(dialog)
        win.title("Produktová skupina" if kind == "group" else "Produktová podskupina")
        win.transient(dialog)
        win.grab_set()
        frame = M.ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        name = M.tk.StringVar(value=str(values.get("name") or ""))
        keywords = M.tk.StringVar(value=str(values.get("keywords") or ""))
        order = M.tk.StringVar(value=str(values.get("sort_order") or 100))
        group_var = M.tk.StringVar()
        group_map = {str(row["name"]): int(row["id"]) for row in groups}
        if kind == "subgroup":
            group_var.set(category_name(M, values.get("category_id")) or (next(iter(group_map), "")))
            M.ttk.Label(frame, text="Nadřazená produktová skupina").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
            M.safe_combobox(frame, textvariable=group_var, values=list(group_map), state="readonly", width=74).grid(
                row=0, column=1, sticky="ew", pady=5
            )
            base_row = 1
        else:
            base_row = 0
        for offset, (label, variable) in enumerate((("Název", name), ("Klíčová slova", keywords), ("Pořadí", order))):
            M.ttk.Label(frame, text=label).grid(row=base_row + offset, column=0, sticky="w", padx=(0, 10), pady=5)
            M.ttk.Entry(frame, textvariable=variable, width=76).grid(row=base_row + offset, column=1, sticky="ew", pady=5)
        M.ttk.Label(
            frame, text="Klíčová slova oddělujte znakem |. Slouží pouze k návrhu automatického zařazení.",
            style="PageSubtitle.TLabel",
        ).grid(row=base_row + 3, column=0, columnspan=2, sticky="w", pady=(2, 8))

        def save():
            value = name.get().strip()
            if not value:
                return M.messagebox.showwarning("Produktové skupiny", "Vyplňte název.", parent=win)
            try:
                sort_value = int(order.get().strip() or 100)
            except Exception:
                sort_value = 100
            try:
                if kind == "group":
                    with M.db() as con:
                        if row_id:
                            con.execute(
                                """UPDATE product_categories SET name=?,keywords=?,sort_order=?,updated_at=CURRENT_TIMESTAMP
                                   WHERE id=?""",
                                (value, keywords.get().strip(), sort_value, row_id),
                            )
                        else:
                            row_new = con.execute(
                                "INSERT INTO product_categories(name,keywords,sort_order,active) VALUES(?,?,?,1)",
                                (value, keywords.get().strip(), sort_value),
                            )
                            new_id = int(row_new.lastrowid)
                else:
                    category_id = group_map.get(group_var.get())
                    if not category_id:
                        return M.messagebox.showwarning(
                            "Produktové skupiny", "Vyberte nadřazenou produktovou skupinu.", parent=win
                        )
                    if row_id:
                        with M.db() as con:
                            old = con.execute("SELECT category_id FROM product_subgroups WHERE id=?", (row_id,)).fetchone()
                            con.execute(
                                """UPDATE product_subgroups SET name=?,keywords=?,sort_order=?,updated_at=CURRENT_TIMESTAMP
                                   WHERE id=?""",
                                (value, keywords.get().strip(), sort_value, row_id),
                            )
                        if old and int(old["category_id"]) != int(category_id):
                            move_subgroup(M, row_id, category_id)
                    else:
                        with M.db() as con:
                            row_new = con.execute(
                                """INSERT INTO product_subgroups(category_id,name,keywords,sort_order,active)
                                   VALUES(?,?,?,?,1)""",
                                (category_id, value, keywords.get().strip(), sort_value),
                            )
                            new_id = int(row_new.lastrowid)
            except M.sqlite3.IntegrityError:
                return M.messagebox.showwarning(
                    "Produktové skupiny", "Stejný název už v této úrovni existuje.", parent=win
                )
            _invalidate(M, app)
            win.destroy()
            refresh(("g" if kind == "group" else "s") + str(row_id or new_id))

        buttons = M.ttk.Frame(frame)
        buttons.grid(row=base_row + 4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")
        M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))
        try:
            M.center_dialog(win, dialog)
        except Exception:
            pass
        win.wait_window()

    def add_group():
        editor("group")

    def add_subgroup():
        kind, row_id = selected()
        parent_id = row_id if kind == "group" else subgroup_parent_id(M, row_id) if kind == "subgroup" else None
        if not parent_id:
            return M.messagebox.showinfo(
                "Produktové skupiny", "Nejdříve vyberte nadřazenou produktovou skupinu.", parent=dialog
            )
        editor("subgroup", parent_group_id=parent_id)

    def edit_selected():
        kind, row_id = selected()
        if kind and row_id:
            editor(kind, row_id)

    def toggle():
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
        with M.db() as con:
            if kind == "group":
                row = con.execute("SELECT name FROM product_categories WHERE id=?", (row_id,)).fetchone()
                used = con.execute(
                    """SELECT (SELECT COUNT(*) FROM price_lists WHERE category_id=?) +
                              (SELECT COUNT(*) FROM price_list_items WHERE category_id=?) +
                              (SELECT COUNT(*) FROM supplier_offer_items WHERE category_id=?) +
                              (SELECT COUNT(*) FROM business_document_items WHERE category_id=?) +
                              (SELECT COUNT(*) FROM product_subgroups WHERE category_id=?)""",
                    (row_id, row_id, row_id, row_id, row_id),
                ).fetchone()[0]
                table = "product_categories"
            else:
                row = con.execute("SELECT name FROM product_subgroups WHERE id=?", (row_id,)).fetchone()
                used = con.execute(
                    """SELECT (SELECT COUNT(*) FROM price_list_items WHERE subgroup_id=?) +
                              (SELECT COUNT(*) FROM supplier_offer_items WHERE subgroup_id=?) +
                              (SELECT COUNT(*) FROM business_document_items WHERE subgroup_id=?)""",
                    (row_id, row_id, row_id),
                ).fetchone()[0]
                table = "product_subgroups"
        if not row:
            return
        if used:
            if M.messagebox.askyesno(
                "Produktové skupiny",
                f"„{row['name']}“ už je použita. Kvůli historii ji nelze fyzicky smazat.\n\nOznačit ji jako neaktivní?",
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

    buttons = M.ttk.Frame(outer)
    buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    M.ttk.Button(buttons, text="+ Nová skupina", style="Accent.TButton", command=add_group).pack(side="left")
    M.ttk.Button(buttons, text="+ Nová podskupina", command=add_subgroup).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Upravit / přejmenovat", command=edit_selected).pack(side="left")
    M.ttk.Button(buttons, text="Aktivní / neaktivní", command=toggle).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Odebrat", command=remove).pack(side="left")
    M.ttk.Button(buttons, text="Zavřít", command=dialog.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit_selected(), add="+")
    refresh()


__all__ = [
    "UNASSIGNED", "NO_SUBGROUP", "list_categories", "list_subgroups",
    "category_id_by_name", "subgroup_id_by_name", "category_name", "subgroup_name",
    "subgroup_parent_id", "taxonomy_path", "classify_text", "classify_subgroup_text",
    "classify_item", "classify_item_taxonomy", "majority_category",
    "set_item_taxonomy", "move_subgroup", "autocategorize_price_list",
    "set_price_list_category", "choose_category", "choose_taxonomy", "manage_categories",
]
