#!/usr/bin/env python3
"""Apply the TURTO CRM 6.3.41 received-offer/catalogue separation."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, replacement: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_pos = text.find(end, start_pos + len(start))
    if end_pos < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_pos] + replacement + text[end_pos:]


# Product catalogue ---------------------------------------------------------
path = "ZakazkyApp_base_6.1/price_lists_domain/platform/product_catalog.py"
text = read(path)
text = replace_once(
    text,
    """Products are linked to supplier price-list and offer rows by a deterministic
supplier/product identity.  Taxonomy, internal codes and internal designations
therefore survive later price-list updates without copying commercial metadata
into every imported row.
""",
    """Products are linked only to supplier price-list rows by a deterministic
supplier/product identity. Received supplier offers deliberately stay outside
the persistent catalogue; they can be copied directly to an issued offer without
creating or modifying a catalogue product.
""",
    "product_catalog docstring",
)
sync_block = '''def _sync_rows(M, table: str, parent_column: str, parent_id: int, source_kind: str) -> int:
    """Synchronize price-list rows into the persistent catalogue.

    The generic signature is retained for compatibility with earlier modules,
    but received supplier offers are intentionally rejected here.
    """
    if table != "price_list_items":
        return 0
    header_sql = """SELECT p.supplier_company_id,
          coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier
          FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id WHERE p.id=?"""
    item_sql = """SELECT id,product_code,supplier_item_code,item_key,name,description,
                  category_id,subgroup_id FROM price_list_items WHERE price_list_id=?"""
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
                """UPDATE price_list_items
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
    """Compatibility no-op.

    Přijaté nabídky are independent commercial documents. Importing or opening
    one must never create a product, source, or catalogue linkage.
    """
    return 0


def count_unlinked(M) -> int:
    """Count only Ceník rows still waiting for catalogue synchronization."""
    with M.db() as con:
        return int(con.execute(
            "SELECT COUNT(*) FROM price_list_items WHERE catalog_product_id IS NULL"
        ).fetchone()[0] or 0)


def sync_all_unlinked(M, max_documents: int | None = 250, progress=None) -> dict:
    """Synchronize unlinked Ceníky; received supplier offers are intentionally ignored."""
    with M.db() as con:
        sql = """SELECT price_list_id parent_id
                   FROM price_list_items
                  WHERE catalog_product_id IS NULL
                  GROUP BY price_list_id
                  ORDER BY price_list_id"""
        params = []
        if max_documents is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(max_documents)))
        documents = con.execute(sql, params).fetchall()
    total = len(documents)
    linked = 0
    for done, row in enumerate(documents, 1):
        parent_id = int(row["parent_id"])
        linked += sync_price_list(M, parent_id)
        if progress:
            progress(done, total, f"Ceník {parent_id}")
    return {"documents": total, "items": linked, "remaining": count_unlinked(M)}


'''
text = replace_section(
    text,
    "def _sync_rows(",
    "def set_product_taxonomy",
    sync_block,
    "product_catalog synchronization block",
)
text = replace_once(
    text,
    '''            con.execute(
                "UPDATE supplier_offer_items SET category_id=?,subgroup_id=? WHERE catalog_product_id=?",
                (category_id, subgroup_id, product_id),
            )
''',
    "",
    "product_catalog supplier taxonomy propagation",
)
text = replace_once(
    text,
    '''def propagate_taxonomy_from_items(M, table: str, item_ids) -> int:
    if table not in {"price_list_items", "supplier_offer_items"}:
''',
    '''def propagate_taxonomy_from_items(M, table: str, item_ids) -> int:
    if table != "price_list_items":
''',
    "product_catalog item propagation guard",
)
source_start = '''        rows = con.execute(
            """SELECT 'Ceník' source_type,p.valid_from source_date,
'''
source_end = '''        ).fetchall()
    win = M.tk.Toplevel(parent)
'''
source_replacement = '''        rows = con.execute(
            """SELECT 'Ceník' source_type,p.valid_from source_date,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier,
                      i.product_code source_code,i.name source_name,i.normalized_unit_price price,i.currency,
                      p.title document_name
               FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
               LEFT JOIN companies c ON c.id=p.supplier_company_id
               WHERE i.catalog_product_id=?
               ORDER BY source_date DESC,source_type,document_name""",
            (product_id,),
        ).fetchall()
    win = M.tk.Toplevel(parent)
'''
text = replace_section(text, source_start, source_end, source_replacement, "product_catalog source dialog")
install_start = '''    old_save_offer = getattr(M, "save_offer_import", None)
'''
install_end = '''    M.open_product_catalog = lambda app, category_id=None, subgroup_id=None: open_product_catalog(
'''
install_replacement = '''    # Přijaté nabídky are deliberately not wrapped here. Their import must stay
    # independent from the catalogue; only Ceníky and explicit manual products
    # are catalogue sources.
    M.open_product_catalog = lambda app, category_id=None, subgroup_id=None: open_product_catalog(
'''
text = replace_section(text, install_start, install_end, install_replacement, "product_catalog install hook")
write(path, text)


# Product workspace ---------------------------------------------------------
path = "ZakazkyApp_base_6.1/price_lists_domain/platform/product_workspace.py"
text = read(path)
text = replace_once(
    text,
    """The stable catalogue data owner remains :mod:`product_catalog`. This module is
its single presentation owner: product groups form a navigation tree on the
left and the products belonging to the selected group/subgroup are shown on the
right. Moving a catalogue product uses the existing service so every linked
price-list and supplier-offer row follows the same stable product.
""",
    """The stable catalogue data owner remains :mod:`product_catalog`. This module is
its single presentation owner: product groups form a navigation tree on the
left and the products belonging to the selected group/subgroup are shown on the
right. Only Ceníky and explicit manual products feed this catalogue; received
supplier offers remain independent commercial documents.
""",
    "product_workspace docstring",
)
text = replace_once(
    text,
    '''            text=("Vlevo vyberte skupinu nebo podskupinu. Produkty můžete upravit dvojklikem nebo je myší "
                  "přetáhnout přímo na cílovou skupinu; poslední přesun lze jedním tlačítkem vrátit."),
''',
    '''            text=("Katalog se plní pouze z Ceníků nebo ručně založených výrobků. Vlevo vyberte skupinu "
                  "nebo podskupinu; produkty lze upravit dvojklikem nebo přetáhnout na cílovou skupinu."),
''',
    "product_workspace subtitle",
)
text = replace_once(text, '    structure_cols = ("Produktů", "Ceníků", "Nabídek")\n', '    structure_cols = ("Produktů", "Ceníků")\n', "product_workspace structure columns")
text = replace_once(text, '    for col, width in (("Produktů", 72), ("Ceníků", 62), ("Nabídek", 65)):\n', '    for col, width in (("Produktů", 72), ("Ceníků", 62)):\n', "product_workspace structure widths")
text = replace_once(text, '            values=(totals["product_count"], totals["list_count"], totals["offer_count"]),\n', '            values=(totals["product_count"], totals["list_count"]),\n', "product_workspace root values")
text = replace_once(text, '                values=(group_row["product_count"], group_row["list_count"], group_row["offer_count"]),\n', '                values=(group_row["product_count"], group_row["list_count"]),\n', "product_workspace group values")
text = replace_once(text, '                    values=(subgroup_row["product_count"], subgroup_row["list_count"], subgroup_row["offer_count"]),\n', '                    values=(subgroup_row["product_count"], subgroup_row["list_count"]),\n', "product_workspace subgroup values")
text = replace_once(text, '        "Marže", "Sleva", "Výsledná cena", "Ceníků", "Nabídek",\n', '        "Marže", "Sleva", "Výsledná cena", "Ceníků",\n', "product_workspace product columns")
text = replace_once(text, '    widths = (120, 230, 165, 175, 135, 290, 230, 250, 125, 68, 68, 125, 65, 65)\n', '    widths = (120, 230, 165, 175, 135, 290, 230, 250, 125, 68, 68, 125, 65)\n', "product_workspace product widths")
text = replace_once(text, '                    row["price_lists"], row["offers"],\n', '                    row["price_lists"],\n', "product_workspace product values")
text = replace_once(
    text,
    '''            f"Produktů: {summary['products']} · Výrobců: {summary['manufacturers']} · "
            f"Vazeb na Ceníky: {summary['list_links']} · Vazeb na cenové Nabídky: {summary['offer_links']}"
''',
    '''            f"Produktů: {summary['products']} · Výrobců: {summary['manufacturers']} · "
            f"Vazeb na Ceníky: {summary['list_links']}"
''',
    "product_workspace summary",
)
text = replace_once(text, '        extra = f" · {remaining} dosud nespojených položek" if remaining else ""\n', '        extra = f" · {remaining} dosud nespojených položek Ceníků" if remaining else ""\n', "product_workspace unlinked status")
text = replace_once(text, '            "Změna se automaticky projeví ve všech jejich Ceníkách i cenových Nabídkách.",\n', '            "Změna se automaticky projeví ve všech propojených Ceníkách. Přijaté nabídky zůstanou beze změny.",\n', "product_workspace move confirmation")
text = replace_once(text, '        progress_win.title("Synchronizace katalogu")\n', '        progress_win.title("Synchronizace Ceníků do katalogu")\n', "product_workspace sync title")
text = replace_once(
    text,
    '''            f"Synchronizováno dokumentů: {result['documents']}\\n"
            f"Propojeno položek: {result['items']}\\nZbývá: {result['remaining']}",
''',
    '''            f"Synchronizováno Ceníků: {result['documents']}\\n"
            f"Propojeno položek Ceníků: {result['items']}\\nZbývá: {result['remaining']}",
''',
    "product_workspace sync result",
)
text = replace_once(text, '    M.ttk.Button(actions, text="Dosynchronizovat katalog", command=sync_everything).pack(side="left", padx=(14, 4))\n', '    M.ttk.Button(actions, text="Dosynchronizovat Ceníky", command=sync_everything).pack(side="left", padx=(14, 4))\n', "product_workspace sync button")
text = replace_once(text, '            status.set(status.get() + f" · při otevření propojeno {result[\'items\']} položek")\n', '            status.set(status.get() + f" · při otevření propojeno {result[\'items\']} položek Ceníků")\n', "product_workspace initial sync status")
write(path, text)


# Issued offer service ------------------------------------------------------
path = "ZakazkyApp_base_6.1/price_lists_domain/issued_offers/service.py"
text = read(path)
draft_function = '''

def draft_from_supplier_offer(M, offer_id: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build an unsaved issued-offer draft from one received supplier offer.

    The source rows are copied as immutable purchase-price snapshots. Even when
    an older database row still has a legacy ``catalog_product_id`` linkage, the
    new issued line deliberately stores ``catalog_product_id=None``. This action
    therefore never creates, updates, or depends on a catalogue product.
    """
    offer_id = int(offer_id)
    with M.db() as con:
        offer_row = con.execute(
            """SELECT o.*,
                      coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),
                               nullif(trim(o.supplier_name),''),'') supplier
                 FROM supplier_offers o
                 LEFT JOIN companies c ON c.id=o.supplier_company_id
                WHERE o.id=?""",
            (offer_id,),
        ).fetchone()
        if not offer_row:
            raise ValueError("Přijatá nabídka už v databázi neexistuje.")

        item_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(supplier_offer_items)")}
        order_sql = "position,id" if "position" in item_columns else "id"
        item_rows = con.execute(
            f"SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY {order_sql}",
            (offer_id,),
        ).fetchall()

        offer = dict(offer_row)
        action_id = int(offer["action_id"]) if offer.get("action_id") else None
        project_id = int(offer["project_id"]) if offer.get("project_id") else None
        request_id = int(offer["request_id"]) if offer.get("request_id") else None

        if request_id and not action_id:
            request_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(requests)")}
            if "action_id" in request_columns:
                request = con.execute("SELECT action_id FROM requests WHERE id=?", (request_id,)).fetchone()
                if request and request[0]:
                    action_id = int(request[0])

        action_name = ""
        if action_id:
            action_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(actions)")}
            select_parts = ["name" if "name" in action_columns else "'' name"]
            select_parts.append("project_id" if "project_id" in action_columns else "NULL project_id")
            action = con.execute(
                f"SELECT {','.join(select_parts)} FROM actions WHERE id=?",
                (action_id,),
            ).fetchone()
            if action:
                action_name = str(action["name"] or "")
                if not project_id and action["project_id"]:
                    project_id = int(action["project_id"])

        project_name = ""
        if project_id:
            project_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(projects)")}
            if "name" in project_columns:
                project = con.execute("SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
                if project:
                    project_name = str(project[0] or "")

    supplier = str(offer.get("supplier") or "").strip()
    source_reference = str(offer.get("offer_number") or offer.get("reference") or f"ID {offer_id}").strip()
    currency = str(offer.get("currency") or "CZK").strip().upper() or "CZK"
    source_label = f"Přijatá nabídka {source_reference}"

    document = offer_defaults(M)
    document.update(
        company_id=None,
        customer_contact_id=None,
        customer_name_snapshot="",
        customer_contact_snapshot="",
        project_id=project_id,
        action_id=action_id,
        project_name=project_name,
        action_name=action_name,
        currency=currency,
        offer_subject=project_name or action_name or "",
        customer_reference="",
        internal_note=(
            f"Zdroj: {source_label}"
            + (f" · dodavatel {supplier}" if supplier else "")
            + f" · interní ID {offer_id}. Položky byly převzaty bez zápisu do Katalogu produktů."
        ),
    )

    from ..platform import product_catalog

    items: list[dict[str, Any]] = []
    for position, source_row in enumerate(item_rows, 1):
        row = dict(source_row)
        purchase = number(row.get("unit_price"))
        if purchase <= 0:
            purchase = number(row.get("original_unit_price"))
        quantity = number(row.get("quantity"), 1)
        if quantity <= 0:
            quantity = 1.0
        category_id = int(row["category_id"]) if row.get("category_id") else None
        subgroup_id = int(row["subgroup_id"]) if row.get("subgroup_id") else None
        policy = product_catalog.pricing_policy(M, category_id, subgroup_id)
        recommended, sale = product_catalog.calculate_prices(
            purchase, policy["margin_pct"], policy["discount_pct"]
        )
        product_code = str(row.get("product_code") or row.get("item_key") or "").strip()
        item_key = str(row.get("item_key") or product_code).strip()
        name = str(row.get("original_name") or item_key or product_code or "Položka").strip()
        description = str(row.get("details") or "").strip()
        item = normalize_item(
            {
                "position": position,
                "row_type": "product",
                "product_code": product_code,
                "item_key": item_key,
                "name": name,
                "description": description,
                "quantity": quantity,
                "unit": str(row.get("unit") or "ks").strip() or "ks",
                "purchase_unit_price": purchase,
                "purchase_currency": currency,
                "margin_pct": policy["margin_pct"],
                "recommended_unit_price": recommended,
                "discount_pct": policy["discount_pct"],
                "unit_price": sale,
                "total_price": quantity * sale,
                "vat_rate": 21.0,
                "show_recommended_price": 1 if policy.get("show_recommended_price", True) else 0,
                "category_id": category_id,
                "subgroup_id": subgroup_id,
                "catalog_product_id": None,
                "internal_code_snapshot": product_code,
                "internal_name_snapshot": name,
                "price_source_label": source_label + (f" · {supplier}" if supplier else ""),
                "source_price_list_item_id": None,
                "source_supplier_offer_item_id": row.get("id"),
                "line_note": "",
            },
            position,
        )
        items.append(item)
    return document, items
'''
text = replace_once(text, '\ndef _sequence_number(con, M, issue_date: str) -> str:\n', draft_function + '\n\ndef _sequence_number(con, M, issue_date: str) -> str:\n', "issued service draft function")
write(path, text)


# Issued offer editor -------------------------------------------------------
path = "ZakazkyApp_base_6.1/price_lists_domain/issued_offers/editor.py"
text = read(path)
text = replace_once(text, 'class IssuedOfferEditor:\n    def __init__(self, M, app, document_id=None):\n', 'class IssuedOfferEditor:\n    def __init__(self, M, app, document_id=None, initial_document=None, initial_items=None):\n', "issued editor constructor")
text = replace_once(
    text,
    '''        document = service.offer_defaults(M)
        if self.document_id:
            document, self.items = service.load_document(M, self.document_id)
        self.document = document
''',
    '''        document = service.offer_defaults(M)
        if initial_document and not self.document_id:
            document.update(dict(initial_document))
        if self.document_id:
            document, self.items = service.load_document(M, self.document_id)
        elif initial_items:
            self.items = [
                service.normalize_item(dict(item), index)
                for index, item in enumerate(initial_items, 1)
            ]
        self.document = document
''',
    "issued editor initial payload",
)
text = replace_once(
    text,
    '''def open_editor(M, app, document_id=None):
    return IssuedOfferEditor(M, app, document_id)


def install(M) -> None:
    M.IssuedOfferEditor = IssuedOfferEditor
    M.open_issued_offer_editor = lambda app, document_id=None: open_editor(M, app, document_id)
    M.App.open_issued_offer_editor = lambda self, document_id=None: open_editor(M, self, document_id)
''',
    '''def open_editor(M, app, document_id=None, initial_document=None, initial_items=None):
    return IssuedOfferEditor(M, app, document_id, initial_document, initial_items)


def install(M) -> None:
    M.IssuedOfferEditor = IssuedOfferEditor
    M.open_issued_offer_editor = (
        lambda app, document_id=None, initial_document=None, initial_items=None:
        open_editor(M, app, document_id, initial_document, initial_items)
    )
    M.App.open_issued_offer_editor = (
        lambda self, document_id=None, initial_document=None, initial_items=None:
        open_editor(M, self, document_id, initial_document, initial_items)
    )
''',
    "issued editor install API",
)
write(path, text)


# Received offer workspace --------------------------------------------------
path = "ZakazkyApp_base_6.1/price_lists_domain/platform/commercial_workspace.py"
text = read(path)
text = replace_once(
    text,
    '''    app.title_label(page, "Nabídky")
    M.ttk.Label(
        page,
        text="Přijaté cenové nabídky dodavatelů, jejich vazby na Akce a propojení s katalogem produktů.",
''',
    '''    app.title_label(page, "Přijaté nabídky")
    M.ttk.Label(
        page,
        text=("Přijaté cenové nabídky zůstávají samostatné. Vybranou nabídku lze překlopit "
              "do Vydané nabídky nebo ji výslovně označit jako Ceník."),
''',
    "commercial offer title",
)
text = replace_once(text, '        ("Bez zařazení produktů", "uncategorized", "Bez zařazení"),\n', '        ("Bez zařazení položek", "uncategorized", "Bez zařazení"),\n', "commercial offer metric")
text = replace_once(
    text,
    '''              SUM(CASE WHEN coalesce(o.archived,0)=0 AND EXISTS(
                    SELECT 1 FROM supplier_offer_items i
                    LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                    WHERE i.offer_id=o.id AND coalesce(cp.category_id,i.category_id) IS NULL
                  ) THEN 1 ELSE 0 END) uncategorized,
''',
    '''              SUM(CASE WHEN coalesce(o.archived,0)=0 AND EXISTS(
                    SELECT 1 FROM supplier_offer_items i
                    WHERE i.offer_id=o.id AND i.category_id IS NULL
                  ) THEN 1 ELSE 0 END) uncategorized,
''',
    "commercial offer summary",
)
text = replace_once(
    text,
    '''    uncategorized_exists = (
        "EXISTS(SELECT 1 FROM supplier_offer_items ux "
        "LEFT JOIN catalog_products cpx ON cpx.id=ux.catalog_product_id "
        "WHERE ux.offer_id=o.id AND coalesce(cpx.category_id,ux.category_id) IS NULL)"
    )
''',
    '''    uncategorized_exists = (
        "EXISTS(SELECT 1 FROM supplier_offer_items ux "
        "WHERE ux.offer_id=o.id AND ux.category_id IS NULL)"
    )
''',
    "commercial offer filter",
)
transfer_function = '''def _offer_to_issued_offer(M, app):
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
            "Položky se nepodařilo připravit pro Vydanou nabídku:\\n\\n" + str(exc),
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


'''
text = replace_once(text, '\ndef _offer_to_price_list(M, app):\n', '\n' + transfer_function + 'def _offer_to_price_list(M, app):\n', "commercial transfer function")
text = replace_once(
    text,
    '''    M.ttk.Button(actions, text="Otevřít detail", style="Accent.TButton", command=app.open_offer_detail).pack(fill="x")
    if callable(getattr(app, "export_selected_offer_excel", None)):
''',
    '''    M.ttk.Button(actions, text="Otevřít detail", command=app.open_offer_detail).pack(fill="x")
    M.ttk.Button(
        actions, text="Překlopit do Vydané nabídky", style="Accent.TButton",
        command=lambda: _offer_to_issued_offer(M, app),
    ).pack(fill="x", pady=(5, 0))
    if callable(getattr(app, "export_selected_offer_excel", None)):
''',
    "commercial transfer button",
)
text = replace_once(
    text,
    '''    context.add_command(label="Otevřít detail", command=app.open_offer_detail)
    context.add_command(label="Označit jako Ceník…", command=lambda: _offer_to_price_list(M, app))
''',
    '''    context.add_command(label="Otevřít detail", command=app.open_offer_detail)
    context.add_command(label="Překlopit do Vydané nabídky", command=lambda: _offer_to_issued_offer(M, app))
    context.add_command(label="Označit jako Ceník…", command=lambda: _offer_to_price_list(M, app))
''',
    "commercial transfer menu",
)
write(path, text)

print("Applied TURTO CRM 6.3.41 core separation")
