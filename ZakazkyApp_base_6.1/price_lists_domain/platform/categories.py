"""Product category catalogue, automatic assignment and category management UI."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def list_categories(M, include_inactive: bool = False):
    with M.db() as con:
        return con.execute(
            """SELECT id,name,parent_id,keywords,active,sort_order
               FROM product_categories
               WHERE (?=1 OR active=1)
               ORDER BY active DESC,sort_order,name COLLATE CZECH""",
            (1 if include_inactive else 0,),
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


def category_name(M, category_id) -> str:
    if not category_id:
        return ""
    with M.db() as con:
        row = con.execute("SELECT name FROM product_categories WHERE id=?", (category_id,)).fetchone()
    return str(row["name"] or "") if row else ""


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


def classify_item(M, row):
    fields = (
        "product_code", "supplier_item_code", "item_key", "name", "description",
        "condition_text", "dimensions", "source_row_json",
    )
    return classify_text(M, " ".join(str(row[key] or "") for key in fields if key in row.keys()))


def majority_category(M, items) -> int | None:
    counts: Counter[int] = Counter()
    for item in list(items or [])[:500]:
        value = " ".join(
            str(item.get(key) or "")
            for key in ("product_code", "item_key", "name", "description", "condition_text")
        )
        cid = classify_text(M, value)
        if cid:
            counts[int(cid)] += 1
    return counts.most_common(1)[0][0] if counts else None


def autocategorize_price_list(M, price_list_id: int, only_empty: bool = True) -> tuple[int, int]:
    with M.db() as con:
        header = con.execute("SELECT category_id FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
        rows = con.execute(
            """SELECT id,category_id,product_code,supplier_item_code,item_key,name,description,
                      condition_text,dimensions,source_row_json
               FROM price_list_items WHERE price_list_id=? AND active=1""",
            (price_list_id,),
        ).fetchall()
    fallback = int(header["category_id"]) if header and header["category_id"] else None
    updates = []
    unassigned = 0
    for row in rows:
        if only_empty and row["category_id"]:
            continue
        cid = classify_item(M, row) or fallback
        if cid:
            updates.append((cid, int(row["id"])))
        else:
            unassigned += 1
    if updates:
        with M.db() as con:
            con.executemany("UPDATE price_list_items SET category_id=? WHERE id=?", updates)
    return len(updates), unassigned


def set_price_list_category(M, price_list_ids, category_id, apply_to_items: bool = True) -> int:
    ids = [int(value) for value in price_list_ids if value]
    if not ids:
        return 0
    with M.db() as con:
        con.executemany("UPDATE price_lists SET category_id=? WHERE id=?", [(category_id, pid) for pid in ids])
        if apply_to_items:
            con.executemany(
                "UPDATE price_list_items SET category_id=? WHERE price_list_id=?",
                [(category_id, pid) for pid in ids],
            )
    return len(ids)


def choose_category(M, parent, title: str = "Vybrat kategorii", current_id=None, allow_auto: bool = False):
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
    labels.append("Nezařazeno")
    mapping[labels[-1]] = None
    for row in rows:
        labels.append(row["name"])
        mapping[row["name"]] = int(row["id"])
    initial = category_name(M, current_id) if current_id else (labels[0] if allow_auto else "Nezařazeno")
    value = M.tk.StringVar(value=initial if initial in labels else labels[0])
    box = M.safe_combobox(frame, textvariable=value, values=labels, state="readonly", width=48)
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


def manage_categories(M, app) -> None:
    dialog = M.tk.Toplevel(app)
    dialog.title("Kategorie produktů")
    dialog.transient(app)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 980, 650)
    outer = M.ttk.Frame(dialog, padding=16)
    outer.pack(fill="both", expand=True)
    outer.rowconfigure(2, weight=1)
    outer.columnconfigure(0, weight=1)
    M.ttk.Label(outer, text="Kategorie produktů", font=("Calibri", 16, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        outer,
        text="Klíčová slova oddělujte znakem |. Automatické zařazení používá první odpovídající aktivní kategorii.",
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))
    tree = M.ttk.Treeview(
        outer, columns=("Kategorie", "Klíčová slova", "Stav", "Ceníků", "Položek"),
        show="headings", selectmode="browse",
    )
    for col, width in (("Kategorie", 250), ("Klíčová slova", 430), ("Stav", 90), ("Ceníků", 80), ("Položek", 80)):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=2, column=0, sticky="nsew")

    def refresh():
        for iid in tree.get_children(""):
            tree.delete(iid)
        with M.db() as con:
            rows = con.execute(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM price_lists p WHERE p.category_id=c.id) list_count,
                          (SELECT COUNT(*) FROM price_list_items i WHERE i.category_id=c.id) item_count
                   FROM product_categories c
                   ORDER BY c.active DESC,c.sort_order,c.name COLLATE CZECH"""
            ).fetchall()
        for row in rows:
            tree.insert(
                "", "end", iid=f"cat{row['id']}",
                values=(row["name"], row["keywords"], "Aktivní" if row["active"] else "Neaktivní",
                        row["list_count"], row["item_count"]),
                tags=("status_cancel",) if not row["active"] else (),
            )

    def selected_id():
        sel = tree.selection()
        return int(str(sel[0])[3:]) if sel else None

    def editor(category_id=None):
        values = {"name": "", "keywords": "", "sort_order": 100}
        if category_id:
            with M.db() as con:
                row = con.execute("SELECT * FROM product_categories WHERE id=?", (category_id,)).fetchone()
            if row:
                values = dict(row)
        win = M.tk.Toplevel(dialog)
        win.title("Kategorie")
        win.transient(dialog)
        win.grab_set()
        frame = M.ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)
        name = M.tk.StringVar(value=values.get("name", "") or "")
        keywords = M.tk.StringVar(value=values.get("keywords", "") or "")
        order = M.tk.StringVar(value=str(values.get("sort_order", 100)))
        for idx, (label, variable) in enumerate((("Název", name), ("Klíčová slova", keywords), ("Pořadí", order))):
            M.ttk.Label(frame, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 10), pady=5)
            M.ttk.Entry(frame, textvariable=variable, width=65).grid(row=idx, column=1, sticky="ew", pady=5)
        frame.columnconfigure(1, weight=1)

        def save():
            category_name_value = name.get().strip()
            if not category_name_value:
                return M.messagebox.showwarning("Kategorie", "Vyplňte název.", parent=win)
            try:
                sort_value = int(order.get().strip() or 100)
            except Exception:
                sort_value = 100
            try:
                with M.db() as con:
                    if category_id:
                        con.execute(
                            """UPDATE product_categories SET name=?,keywords=?,sort_order=?,updated_at=CURRENT_TIMESTAMP
                               WHERE id=?""",
                            (category_name_value, keywords.get().strip(), sort_value, category_id),
                        )
                    else:
                        con.execute(
                            "INSERT INTO product_categories(name,keywords,sort_order,active) VALUES(?,?,?,1)",
                            (category_name_value, keywords.get().strip(), sort_value),
                        )
            except M.sqlite3.IntegrityError:
                return M.messagebox.showwarning("Kategorie", "Kategorie s tímto názvem už existuje.", parent=win)
            win.destroy()
            refresh()

        buttons = M.ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")
        M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))
        try:M.center_dialog(win, dialog)
        except Exception:pass
        win.wait_window()

    def toggle():
        cid = selected_id()
        if not cid:
            return
        with M.db() as con:
            row = con.execute("SELECT active FROM product_categories WHERE id=?", (cid,)).fetchone()
            if row:
                con.execute("UPDATE product_categories SET active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (0 if row["active"] else 1, cid))
        refresh()

    def remove():
        cid = selected_id()
        if not cid:
            return
        with M.db() as con:
            row = con.execute("SELECT name FROM product_categories WHERE id=?", (cid,)).fetchone()
            used = con.execute(
                """SELECT (SELECT COUNT(*) FROM price_lists WHERE category_id=?) +
                          (SELECT COUNT(*) FROM price_list_items WHERE category_id=?)""",
                (cid, cid),
            ).fetchone()[0]
        if used:
            return M.messagebox.showwarning(
                "Kategorie", "Používanou kategorii nelze smazat. Lze ji označit jako neaktivní.", parent=dialog
            )
        if row and M.messagebox.askyesno("Kategorie", f"Smazat kategorii „{row['name']}“?", parent=dialog):
            with M.db() as con:
                con.execute("DELETE FROM product_categories WHERE id=?", (cid,))
            refresh()

    buttons = M.ttk.Frame(outer)
    buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
    M.ttk.Button(buttons, text="+ Přidat", style="Accent.TButton", command=lambda: editor()).pack(side="left")
    M.ttk.Button(buttons, text="Upravit", command=lambda: editor(selected_id()) if selected_id() else None).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Aktivní / neaktivní", command=toggle).pack(side="left")
    M.ttk.Button(buttons, text="Smazat", command=remove).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Zavřít", command=dialog.destroy).pack(side="right")
    try:M.bind_row_double_click(tree, lambda _event: editor(selected_id()) if selected_id() else None)
    except Exception:pass
    refresh()
