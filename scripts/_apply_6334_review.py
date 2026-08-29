from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ZakazkyApp_base_6.1"


def replace(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:160]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


categories = SRC / "price_lists_domain/platform/categories.py"
replace(
    categories,
    '''def set_item_taxonomy(M, table: str, item_ids, category_id=None, subgroup_id=None) -> int:
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
        if "subgroup_id" not in _columns(con, table):
            raise RuntimeError("Databáze ještě neobsahuje podporu produktových podskupin.")
        con.executemany(
            f"UPDATE {table} SET category_id=?,subgroup_id=? WHERE id=?",
            [(category_id, subgroup_id, item_id) for item_id in ids],
        )
    if table in {"price_list_items", "supplier_offer_items"}:
        try:
            from . import product_catalog
            product_catalog.propagate_taxonomy_from_items(M, table, ids)
        except Exception:
            pass
    return len(ids)
''',
    '''def set_item_taxonomy(M, table: str, item_ids, category_id=None, subgroup_id=None) -> int:
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
''',
)
replace(
    categories,
    '''def set_price_list_category(M, price_list_ids, category_id, apply_to_items: bool = True, subgroup_id=None) -> int:
    ids = [int(value) for value in price_list_ids if value]
    if not ids:
        return 0
    if subgroup_id:
        category_id = subgroup_parent_id(M, subgroup_id)
    with M.db() as con:
        con.executemany("UPDATE price_lists SET category_id=? WHERE id=?", [(category_id, pid) for pid in ids])
        if apply_to_items:
            for pid in ids:
                rows = con.execute("SELECT id FROM price_list_items WHERE price_list_id=?", (pid,)).fetchall()
                item_ids = [int(row["id"]) for row in rows]
                con.executemany(
                    "UPDATE price_list_items SET category_id=?,subgroup_id=? WHERE id=?",
                    [(category_id, subgroup_id, item_id) for item_id in item_ids],
                )
                try:
                    from . import product_catalog
                    product_catalog.propagate_taxonomy_from_items(M, "price_list_items", item_ids)
                except Exception:
                    pass
    return len(ids)
''',
    '''def set_price_list_category(M, price_list_ids, category_id, apply_to_items: bool = True, subgroup_id=None) -> int:
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
''',
)
replace(
    categories,
    '''    def open_products():
        kind, row_id = selected()
        category_id = row_id if kind == "group" else subgroup_parent_id(M, row_id) if kind == "subgroup" else None
        subgroup_id = row_id if kind == "subgroup" else None
        product_catalog.open_product_catalog(M, app, category_id, subgroup_id)
        refresh(("g" if kind == "group" else "s") + str(row_id) if row_id else None)
''',
    '''    def open_products():
        kind, row_id = selected()
        category_id = row_id if kind == "group" else subgroup_parent_id(M, row_id) if kind == "subgroup" else None
        subgroup_id = row_id if kind == "subgroup" else None
        try:
            dialog.grab_release()
        except Exception:
            pass
        product_catalog.open_product_catalog(M, app, category_id, subgroup_id)
        refresh(("g" if kind == "group" else "s") + str(row_id) if row_id else None)
''',
)

price_dialogs = SRC / "price_lists_domain/platform/price_dialogs.py"
replace(price_dialogs, 'auto_category = selected_category == "Automaticky podle položek"', 'auto_category = False')
replace(
    price_dialogs,
    'category_id = None if selected_category in {"Automaticky podle položek", "Nezařazeno"} else categories.category_id_by_name(M, selected_category)',
    'category_id = None if selected_category == "Nezařazeno" else categories.category_id_by_name(M, selected_category)',
)
replace(
    price_dialogs,
    '"category": M.tk.StringVar(value=categories.category_name(M, row["category_id"]) or "Automaticky podle položek"),',
    '"category": M.tk.StringVar(value=categories.category_name(M, row["category_id"]) or "Nezařazeno"),',
)
replace(
    price_dialogs,
    'category_id = None if category_label in {"Automaticky podle položek", "Nezařazeno"} else categories.category_id_by_name(M, category_label)',
    'category_id = None if category_label == "Nezařazeno" else categories.category_id_by_name(M, category_label)',
)
replace(
    price_dialogs,
    '''        with M.db() as con:
            con.execute(
                """UPDATE price_lists SET title=?,valid_from=?,valid_to=?,product_group=?,branch=?,
                          update_mode=?,supersedes_id=?,note=?,category_id=? WHERE id=?""",
                (
                    variables["title"].get().strip(), valid_from, _iso_date(variables["valid_to"].get()),
                    variables["product_group"].get().strip(), variables["branch"].get().strip(), mode,
                    previous_id, note.get("1.0", "end").strip(), category_id, price_list_id,
                ),
            )
            if category_label == "Nezařazeno":
                con.execute("UPDATE price_list_items SET category_id=NULL,subgroup_id=NULL WHERE price_list_id=?", (price_list_id,))
            elif category_id:
                con.execute("UPDATE price_list_items SET category_id=?,subgroup_id=NULL WHERE price_list_id=?", (category_id, price_list_id))
            if previous_id and mode in {"replace_group", "replace_all"}:
                previous_day = (datetime.strptime(valid_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
                con.execute(
                    "UPDATE price_lists SET valid_to=? WHERE id=? AND (valid_to='' OR valid_to>?)",
                    (previous_day, previous_id, previous_day),
                )
        if category_label == "Automaticky podle položek":
            categories.autocategorize_price_list(M, price_list_id, only_empty=False)
''',
    '''        product_catalog.sync_price_list(M, price_list_id)
        item_ids = []
        with M.db() as con:
            con.execute(
                """UPDATE price_lists SET title=?,valid_from=?,valid_to=?,product_group=?,branch=?,
                          update_mode=?,supersedes_id=?,note=?,category_id=? WHERE id=?""",
                (
                    variables["title"].get().strip(), valid_from, _iso_date(variables["valid_to"].get()),
                    variables["product_group"].get().strip(), variables["branch"].get().strip(), mode,
                    previous_id, note.get("1.0", "end").strip(), category_id, price_list_id,
                ),
            )
            item_ids = [int(item[0]) for item in con.execute(
                "SELECT id FROM price_list_items WHERE price_list_id=?", (price_list_id,)
            ).fetchall()]
            if category_label == "Nezařazeno":
                con.execute("UPDATE price_list_items SET category_id=NULL,subgroup_id=NULL WHERE price_list_id=?", (price_list_id,))
            elif category_id:
                con.execute("UPDATE price_list_items SET category_id=?,subgroup_id=NULL WHERE price_list_id=?", (category_id, price_list_id))
            if previous_id and mode in {"replace_group", "replace_all"}:
                previous_day = (datetime.strptime(valid_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
                con.execute(
                    "UPDATE price_lists SET valid_to=? WHERE id=? AND (valid_to='' OR valid_to>?)",
                    (previous_day, previous_id, previous_day),
                )
        if item_ids:
            product_catalog.propagate_taxonomy_from_items(M, "price_list_items", item_ids)
''',
)

catalog = SRC / "price_lists_domain/platform/product_catalog.py"
replace(
    catalog,
    '''def sync_all_unlinked(M, max_documents: int | None = 250, progress=None) -> dict:
    limit_sql = "" if max_documents is None else f" LIMIT {max(1, int(max_documents))}"
    with M.db() as con:
        price_ids = [int(row[0]) for row in con.execute(
            "SELECT DISTINCT price_list_id FROM price_list_items WHERE catalog_product_id IS NULL ORDER BY price_list_id" + limit_sql
        ).fetchall()]
        offer_ids = [int(row[0]) for row in con.execute(
            "SELECT DISTINCT offer_id FROM supplier_offer_items WHERE catalog_product_id IS NULL ORDER BY offer_id" + limit_sql
        ).fetchall()]
    total = len(price_ids) + len(offer_ids)
    done = 0
    linked = 0
    for price_list_id in price_ids:
        linked += sync_price_list(M, price_list_id)
        done += 1
        if progress:
            progress(done, total, f"Ceník {price_list_id}")
    for offer_id in offer_ids:
        linked += sync_supplier_offer(M, offer_id)
        done += 1
        if progress:
            progress(done, total, f"Cenová nabídka {offer_id}")
    return {"documents": done, "items": linked, "remaining": count_unlinked(M)}
''',
    '''def sync_all_unlinked(M, max_documents: int | None = 250, progress=None) -> dict:
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
''',
)
replace(catalog, 'initial_sync = sync_all_unlinked(M, max_documents=250)', 'initial_sync = sync_all_unlinked(M, max_documents=100)')
replace(
    catalog,
    '''        try:
            result = sync_all_unlinked(M, max_documents=None, progress=progress)
        finally:
            progress_win.destroy()
        refresh_filters()
''',
    '''        try:
            result = sync_all_unlinked(M, max_documents=None, progress=progress)
        except Exception as exc:
            progress_win.destroy()
            return M.messagebox.showerror("Katalog produktů", f"Synchronizaci se nepodařilo dokončit:\n{exc}", parent=win)
        progress_win.destroy()
        refresh_filters()
''',
)
replace(categories, 'product_catalog.sync_all_unlinked(M, max_documents=250)', 'product_catalog.sync_all_unlinked(M, max_documents=100)')

release_notes = ROOT / "release_notes.txt"
release_notes.write_text(
    "• Klíčová slova byla odstraněna z uživatelského rozhraní a produktové zařazení se už automaticky nehádá. Skupiny a podskupiny se spravují ručně.\n"
    "• Přidán stabilní Katalog produktů. U produktu je vidět výrobce, zdrojový dodavatel, dodavatelský kód, označení ve zdroji, interní kód, interní označení, skupina, podskupina a počet cenových zdrojů.\n"
    "• Produkty lze hromadně přesouvat mezi skupinami a podskupinami. Stejný produkt v novém ceníku převezme zařazení, interní kód i interní označení podle dodavatele a produktového kódu.\n"
    "• U každé podskupiny lze nastavit základní marži a základní slevu. Skupina obsahuje stejné výchozí hodnoty pro produkty bez podskupiny.\n"
    "• U každé hlavní skupiny lze zvolit, zda se má ve vydaných nabídkách zobrazovat doporučená i výsledná cena, nebo pouze výsledná cena.\n"
    "• Aktuální ceny nově ukazují interní kód a označení, výrobce, nákupní cenu, marži, doporučenou cenu, slevu a výslednou cenu. Doporučená cena se u skupin s režimem „Pouze výsledná“ nezobrazuje.\n"
    "• Výpočet je jednotný: doporučená cena = nákupní cena × (1 + marže/100); výsledná cena = doporučená cena × (1 − sleva/100).\n"
    "• Datový základ budoucích Vydaných nabídek a objednávek obsahuje vazbu na katalog produktu a snímky interního označení, nákupní ceny, marže a doporučené ceny.\n"
    "• Databázová změna je pouze aditivní. Historické nabídky, ceníky, ceny, fyzické archivy, Outlook import a uživatelská data zůstávají zachovány.\n",
    encoding="utf-8",
)

validation = ROOT / "scripts/validate-6334-product-catalog.py"
text = validation.read_text(encoding="utf-8")
text = text.replace(
    'assert "def classify_text(M, value: object):\\n    return None" in categories_text',
    'assert "def classify_text(M, value: object):\\n    return None" in categories_text\nassert "Automaticky podle položek" not in (root / "price_lists_domain/platform/price_dialogs.py").read_text(encoding="utf-8")',
)
validation.write_text(text, encoding="utf-8")

print("TURTO CRM 6.3.34 review hardening complete")
