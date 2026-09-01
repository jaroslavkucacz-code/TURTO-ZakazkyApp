"""TURTO CRM 7.1 – consolidated workflow, table and commercial cleanup.

This layer is intentionally additive.  It keeps the 6.1 baseline readable while
owning the cross-cutting behaviour requested for 7.0: keyboard traversal,
persistent Treeview geometry, configurable commercial columns, batch request
archiving and taxonomy grouping in issued offers.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Iterable


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def group_offer_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a stable display plan with one heading per product subgroup.

    Product rows sharing the same category/subgroup are emitted together at the
    position of the group's first occurrence.  Non-product rows keep their
    relative position.  Every item token carries its original list index so UI
    selection/editing continues to address the underlying document row.
    """
    rows = [(index, dict(raw or {})) for index, raw in enumerate(items)]
    buckets: "OrderedDict[tuple[str, str], list[tuple[int, dict[str, Any]]]]" = OrderedDict()
    labels: dict[tuple[str, str], tuple[str, str]] = {}
    for index, item in rows:
        if _text(item.get("row_type"), "product").lower() != "product":
            continue
        category = _text(
            item.get("category_name_snapshot") or item.get("category"),
            "Nezařazeno",
        )
        subgroup = _text(
            item.get("subgroup_name_snapshot") or item.get("subgroup"),
            "Bez podskupiny",
        )
        key = (category.casefold(), subgroup.casefold())
        labels.setdefault(key, (category, subgroup))
        buckets.setdefault(key, []).append((index, item))

    result: list[dict[str, Any]] = []
    emitted: set[tuple[str, str]] = set()
    for index, item in rows:
        if _text(item.get("row_type"), "product").lower() != "product":
            result.append({"kind": "item", "index": index, "item": item})
            continue
        category = _text(
            item.get("category_name_snapshot") or item.get("category"),
            "Nezařazeno",
        )
        subgroup = _text(
            item.get("subgroup_name_snapshot") or item.get("subgroup"),
            "Bez podskupiny",
        )
        key = (category.casefold(), subgroup.casefold())
        if key in emitted:
            continue
        emitted.add(key)
        category, subgroup = labels[key]
        result.append(
            {
                "kind": "group",
                "category": category,
                "subgroup": subgroup,
                "label": f"{category} › {subgroup}",
            }
        )
        for original_index, grouped_item in buckets.get(key, []):
            result.append(
                {"kind": "item", "index": original_index, "item": grouped_item}
            )
    return result


def apply(M):
    import hashlib
    import json
    import re
    import threading
    from datetime import date

    if getattr(M, "_turto_v710_installed", False):
        return

    # ------------------------------------------------------------------
    # Shared helpers.
    # ------------------------------------------------------------------
    def root_app(widget=None):
        current = widget
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, getattr(M, "App", ())):
                return current
            current = getattr(current, "master", None)
        return getattr(M, "_active_app", None)

    def active_user(widget=None) -> str:
        app = root_app(widget)
        try:
            value = _text(app.active_user.get())
            if value:
                return value
        except Exception:
            pass
        try:
            return _text(M.get_setting("active_user", ""), "Výchozí")
        except Exception:
            return "Výchozí"

    def walk(widget):
        yield widget
        try:
            for child in widget.winfo_children():
                yield from walk(child)
        except Exception:
            return

    def focus_widget(widget):
        candidate = getattr(widget, "entry", None) or widget
        try:
            candidate.focus_set()
            candidate.icursor("end")
        except Exception:
            try:
                candidate.focus_set()
            except Exception:
                pass
        return "break"

    # ------------------------------------------------------------------
    # Additive issued-offer taxonomy snapshots.
    # ------------------------------------------------------------------
    def ensure_v700_schema():
        try:
            with M.db() as con:
                tables = {
                    str(row[0])
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "business_document_items" not in tables:
                    return
                columns = {
                    str(row[1])
                    for row in con.execute(
                        "PRAGMA table_info(business_document_items)"
                    ).fetchall()
                }
                if "category_name_snapshot" not in columns:
                    con.execute(
                        "ALTER TABLE business_document_items "
                        "ADD COLUMN category_name_snapshot TEXT DEFAULT ''"
                    )
                if "subgroup_name_snapshot" not in columns:
                    con.execute(
                        "ALTER TABLE business_document_items "
                        "ADD COLUMN subgroup_name_snapshot TEXT DEFAULT ''"
                    )
        except Exception:
            pass

    old_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(old_ensure_schema):
        def ensure_schema():
            result = old_ensure_schema()
            ensure_v700_schema()
            return result
        M.ensure_schema = ensure_schema

    try:
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import pdf_renderer, service
    except Exception:
        issued_editor = pdf_renderer = service = None

    def taxonomy_maps(items):
        category_ids = set()
        subgroup_ids = set()
        for raw in items:
            try:
                if raw.get("category_id"):
                    category_ids.add(int(raw["category_id"]))
                if raw.get("subgroup_id"):
                    subgroup_ids.add(int(raw["subgroup_id"]))
            except Exception:
                pass
        categories: dict[int, str] = {}
        subgroups: dict[int, tuple[str, int | None]] = {}
        try:
            with M.db() as con:
                if category_ids:
                    marks = ",".join("?" for _ in category_ids)
                    for row in con.execute(
                        f"SELECT id,name FROM product_categories WHERE id IN ({marks})",
                        sorted(category_ids),
                    ).fetchall():
                        categories[int(row["id"])] = _text(row["name"])
                if subgroup_ids:
                    marks = ",".join("?" for _ in subgroup_ids)
                    for row in con.execute(
                        f"SELECT id,category_id,name FROM product_subgroups "
                        f"WHERE id IN ({marks})",
                        sorted(subgroup_ids),
                    ).fetchall():
                        subgroups[int(row["id"])] = (
                            _text(row["name"]),
                            int(row["category_id"]) if row["category_id"] else None,
                        )
        except Exception:
            pass
        return categories, subgroups

    def enrich_taxonomy(items, prefer_snapshot=True):
        """Resolve category/subgroup consistently without rewriting old snapshots.

        Existing saved documents keep their immutable text snapshots. New rows
        carrying ``_taxonomy_authoritative_ids`` or ``_taxonomy_dirty`` use the
        current stable IDs, with the subgroup parent always owning the category.
        """
        values = [dict(raw or {}) for raw in items]
        categories, subgroups = taxonomy_maps(values)
        for item in values:
            if _text(item.get("row_type"), "product").lower() != "product":
                item.setdefault("category_name_snapshot", "")
                item.setdefault("subgroup_name_snapshot", "")
                continue
            category_id = None
            subgroup_id = None
            try:
                category_id = int(item["category_id"]) if item.get("category_id") else None
            except Exception:
                pass
            try:
                subgroup_id = int(item["subgroup_id"]) if item.get("subgroup_id") else None
            except Exception:
                pass
            subgroup_info = subgroups.get(subgroup_id) if subgroup_id else None
            if subgroup_info and subgroup_info[1]:
                category_id = subgroup_info[1]
            item["category_id"] = category_id
            item["subgroup_id"] = subgroup_id

            authoritative = bool(
                item.get("_taxonomy_authoritative_ids") or item.get("_taxonomy_dirty")
            )
            keep_snapshot = bool(prefer_snapshot and not authoritative)
            category_snapshot = _text(item.get("category_name_snapshot"))
            subgroup_snapshot = _text(item.get("subgroup_name_snapshot"))
            category_current = _text(categories.get(category_id)) if category_id else ""
            subgroup_current = _text(subgroup_info[0]) if subgroup_info else ""

            if keep_snapshot:
                category_name = _text(
                    category_snapshot or item.get("category") or category_current,
                    "Nezařazeno",
                )
                subgroup_name = _text(
                    subgroup_snapshot or item.get("subgroup") or subgroup_current,
                    "Bez podskupiny",
                )
            else:
                category_name = _text(
                    category_current or item.get("category") or category_snapshot,
                    "Nezařazeno",
                )
                subgroup_name = _text(
                    subgroup_current or item.get("subgroup") or subgroup_snapshot,
                    "Bez podskupiny",
                )
            item["category_name_snapshot"] = category_name
            item["subgroup_name_snapshot"] = subgroup_name
        return values

    if service is not None and not getattr(service, "_turto_v710_taxonomy", False):
        original_normalize_item = service.normalize_item
        original_catalog_products = service.catalog_products
        original_save_document = service.save_document
        original_load_document = service.load_document
        original_draft_from_supplier_offer = service.draft_from_supplier_offer

        def normalize_item(raw, position=None, recalculate_sale=False):
            source = dict(raw or {})
            item = original_normalize_item(source, position, recalculate_sale)
            if _text(item.get("row_type"), "product").lower() == "product":
                authoritative = bool(
                    source.get("_taxonomy_authoritative_ids") or source.get("_taxonomy_dirty")
                )
                has_ids = bool(item.get("category_id") or item.get("subgroup_id"))
                has_snapshot = bool(
                    _text(item.get("category_name_snapshot"))
                    or _text(item.get("subgroup_name_snapshot"))
                )
                if authoritative or (has_ids and not has_snapshot):
                    item.update({
                        key: source.get(key)
                        for key in ("_taxonomy_authoritative_ids", "_taxonomy_dirty")
                        if source.get(key)
                    })
                    item = enrich_taxonomy([item], prefer_snapshot=not authoritative)[0]
                else:
                    item["category_name_snapshot"] = _text(
                        item.get("category_name_snapshot") or item.get("category"),
                        "Nezařazeno",
                    )
                    item["subgroup_name_snapshot"] = _text(
                        item.get("subgroup_name_snapshot") or item.get("subgroup"),
                        "Bez podskupiny",
                    )
            return item

        def catalog_products(module, query="", limit=500):
            rows = original_catalog_products(module, query, limit)
            for row in rows:
                row["category_name_snapshot"] = _text(
                    row.get("category_name_snapshot") or row.get("category"),
                    "Nezařazeno",
                )
                row["subgroup_name_snapshot"] = _text(
                    row.get("subgroup_name_snapshot") or row.get("subgroup"),
                    "Bez podskupiny",
                )
            return rows

        def save_document(module, values, items, document_id=None):
            ensure_v700_schema()
            enriched = enrich_taxonomy(items)
            result = original_save_document(module, values, enriched, document_id)
            try:
                with module.db() as con:
                    rows = con.execute(
                        "SELECT id,position FROM business_document_items "
                        "WHERE document_id=? ORDER BY position,id",
                        (int(result),),
                    ).fetchall()
                    for row, item in zip(rows, enriched):
                        con.execute(
                            "UPDATE business_document_items SET "
                            "category_name_snapshot=?,subgroup_name_snapshot=? WHERE id=?",
                            (
                                item.get("category_name_snapshot", ""),
                                item.get("subgroup_name_snapshot", ""),
                                int(row["id"]),
                            ),
                        )
            except Exception:
                pass
            return result

        def load_document(module, document_id):
            ensure_v700_schema()
            document, items = original_load_document(module, document_id)
            return document, enrich_taxonomy(items)

        def draft_from_supplier_offer(module, offer_id):
            document, items = original_draft_from_supplier_offer(module, offer_id)
            prepared = []
            for raw in items:
                item = dict(raw or {})
                item["_taxonomy_authoritative_ids"] = True
                prepared.append(item)
            return document, enrich_taxonomy(prepared, prefer_snapshot=False)

        service.normalize_item = normalize_item
        service.catalog_products = catalog_products
        service.save_document = save_document
        service.load_document = load_document
        service.draft_from_supplier_offer = draft_from_supplier_offer
        service.group_offer_items = group_offer_items
        service._turto_v710_taxonomy = True

    def assign_taxonomy_to_items(parent, items, indices, ask_pricing=True):
        if service is None:
            return False
        try:
            from price_lists_domain.platform import categories as taxonomy_categories
            from price_lists_domain.platform import product_catalog as catalogue_service
        except Exception as exc:
            M.messagebox.showerror("Zařazení produktů", str(exc), parent=parent)
            return False
        product_indices = [
            int(index) for index in indices
            if 0 <= int(index) < len(items)
            and _text(items[int(index)].get("row_type"), "product").lower() == "product"
        ]
        if not product_indices:
            M.messagebox.showinfo(
                "Zařazení produktů", "Vyberte jednu nebo více produktových položek.", parent=parent
            )
            return False
        first = items[product_indices[0]]
        current_category = first.get("category_id")
        current_subgroup = first.get("subgroup_id")
        if current_subgroup:
            current_category = taxonomy_categories.subgroup_parent_id(M, current_subgroup) or current_category
        selected = taxonomy_categories.choose_taxonomy(
            M, parent, "Přiřadit produktovou skupinu a podskupinu",
            current_category, current_subgroup,
        )
        if selected == "cancel":
            return False
        category_id, subgroup_id = selected
        if subgroup_id:
            category_id = taxonomy_categories.subgroup_parent_id(M, subgroup_id) or category_id
        recalculate = False
        if ask_pricing:
            decision = M.messagebox.askyesnocancel(
                "Cenová pravidla",
                "Převzít zároveň výchozí marži a slevu vybrané skupiny nebo podskupiny?\n\n"
                "Ano = přepočítat ceny podle zařazení.\n"
                "Ne = změnit pouze skupinu a podskupinu.",
                parent=parent,
            )
            if decision is None:
                return False
            recalculate = bool(decision)
        category_label = taxonomy_categories.category_name(M, category_id) or "Nezařazeno"
        subgroup_label = taxonomy_categories.subgroup_name(M, subgroup_id) or "Bez podskupiny"
        for index in product_indices:
            item = dict(items[index] or {})
            item.update(
                category_id=category_id,
                subgroup_id=subgroup_id,
                category_name_snapshot=category_label,
                subgroup_name_snapshot=subgroup_label,
                _taxonomy_dirty=True,
                _taxonomy_authoritative_ids=True,
            )
            if recalculate:
                policy = catalogue_service.pricing_policy(M, category_id, subgroup_id)
                recommended, sale = catalogue_service.calculate_prices(
                    item.get("purchase_unit_price", 0),
                    policy.get("margin_pct", 0),
                    policy.get("discount_pct", 0),
                )
                item.update(
                    margin_pct=policy.get("margin_pct", 0),
                    discount_pct=policy.get("discount_pct", 0),
                    show_recommended_price=1 if policy.get("show_recommended_price", True) else 0,
                    recommended_unit_price=recommended,
                    unit_price=sale,
                    total_price=service.number(item.get("quantity"), 1) * sale,
                )
            items[index] = service.normalize_item(item, index + 1)
        return True

    class TransferTaxonomyDialog:
        """Edit only the outgoing draft; never writes back to the received offer."""
        def __init__(self, parent, items):
            self.items = [dict(item or {}) for item in items]
            self.result = None
            self.win = M.tk.Toplevel(parent)
            self.win.title("Překlopit do Vydané nabídky")
            self.win.transient(parent)
            self.win.grab_set()
            M.enable_dialog_maximize(self.win, 1320, 720)
            frame = M.ttk.Frame(self.win, padding=14)
            frame.pack(fill="both", expand=True)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(2, weight=1)
            M.ttk.Label(
                frame, text="Položky překlopené do Vydané nabídky",
                font=("Calibri", 16, "bold"),
            ).grid(row=0, column=0, sticky="w")
            M.ttk.Label(
                frame,
                text=(
                    "Zařazení se použije pouze v novém konceptu Vydané nabídky. "
                    "Zdrojová Přijatá nabídka ani Katalog produktů se tím nezmění."
                ),
                style="PageSubtitle.TLabel",
            ).grid(row=1, column=0, sticky="w", pady=(2, 8))
            columns = (
                "Kód", "Položka", "Množství", "MJ", "Nákupní cena",
                "Skupina", "Podskupina",
            )
            widths = (120, 360, 90, 65, 120, 250, 290)
            wrap = M.ttk.Frame(frame)
            wrap.grid(row=2, column=0, sticky="nsew")
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)
            self.tree = M.ttk.Treeview(
                wrap, columns=columns, show="headings", selectmode="extended"
            )
            for column, width in zip(columns, widths):
                self.tree.heading(column, text=column)
                self.tree.column(column, width=width, minwidth=45, anchor="w", stretch=False)
            self.tree.grid(row=0, column=0, sticky="nsew")
            ys = M.ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
            xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=self.tree.xview)
            ys.grid(row=0, column=1, sticky="ns")
            xs.grid(row=1, column=0, sticky="ew")
            self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            self.tree.bind("<Double-1>", lambda _event: self.assign())
            tools = M.ttk.Frame(frame)
            tools.grid(row=3, column=0, sticky="ew", pady=(9, 0))
            M.ttk.Button(tools, text="Vybrat vše", command=self.select_all).pack(side="left")
            M.ttk.Button(
                tools, text="Přiřadit skupinu / podskupinu…", command=self.assign
            ).pack(side="left", padx=5)
            M.ttk.Button(tools, text="Zrušit", command=self.win.destroy).pack(side="right")
            M.ttk.Button(
                tools, text="Pokračovat do Vydané nabídky", style="Accent.TButton",
                command=self.finish,
            ).pack(side="right", padx=5)
            self.refresh()
            self.select_all()
            try:
                installer = getattr(M, "install_persistent_tree_layout", None)
                if callable(installer):
                    installer(self.tree, force=True)
            except Exception:
                pass
            self.win.wait_window()

        def refresh(self):
            selected = set(self.tree.selection())
            for iid in self.tree.get_children(""):
                self.tree.delete(iid)
            for index, raw in enumerate(self.items):
                item = service.normalize_item(raw, index + 1)
                self.items[index] = item
                if _text(item.get("row_type"), "product").lower() != "product":
                    continue
                iid = f"r{index}"
                self.tree.insert(
                    "", "end", iid=iid,
                    values=(
                        item.get("internal_code_snapshot") or item.get("product_code") or "",
                        item.get("name") or item.get("internal_name_snapshot") or item.get("description") or "",
                        str(item.get("quantity") or ""), item.get("unit") or "",
                        f"{service.number(item.get('purchase_unit_price')):.2f}",
                        item.get("category_name_snapshot") or "Nezařazeno",
                        item.get("subgroup_name_snapshot") or "Bez podskupiny",
                    ),
                )
            for iid in selected:
                if self.tree.exists(iid):
                    self.tree.selection_add(iid)

        def select_all(self):
            rows = self.tree.get_children("")
            if rows:
                self.tree.selection_set(rows)

        def assign(self):
            indices = [
                int(str(iid)[1:]) for iid in self.tree.selection()
                if str(iid).startswith("r") and str(iid)[1:].isdigit()
            ]
            if assign_taxonomy_to_items(self.win, self.items, indices, ask_pricing=True):
                self.refresh()

        def finish(self):
            self.result = [dict(item or {}) for item in self.items]
            self.win.destroy()

    # Issued-offer editor: show taxonomy on every product and one group row only.
    if issued_editor is not None and not getattr(issued_editor, "_turto_v710_grouped_items", False):
        Editor = issued_editor.IssuedOfferEditor
        editor_columns = (
            "Poz.", "Typ", "Kód", "Označení", "Skupina", "Podskupina",
            "Množství", "MJ", "Nákupní cena", "Marže", "Doporučená cena",
            "Sleva", "Prodejní cena", "Celkem bez DPH",
        )
        editor_widths = (
            55, 110, 120, 330, 220, 240, 90, 60, 115, 75, 125, 75, 115, 130,
        )

        def ensure_editor_columns(instance):
            tree = instance.tree
            if tuple(tree.cget("columns")) != editor_columns:
                tree.configure(columns=editor_columns, show="headings")
            for column, width in zip(editor_columns, editor_widths):
                tree.heading(column, text=column)
                try:
                    current = int(tree.column(column, "width"))
                except Exception:
                    current = width
                tree.column(
                    column,
                    width=current if current > 30 else width,
                    minwidth=35,
                    anchor="w",
                    stretch=False,
                )

        def refresh_items(instance):
            ensure_editor_columns(instance)
            selected_indices = []
            for iid in instance.tree.selection():
                try:
                    if str(iid).startswith("r"):
                        selected_indices.append(int(str(iid)[1:]))
                except Exception:
                    pass
            for iid in instance.tree.get_children(""):
                instance.tree.delete(iid)
            normalized = [
                service.normalize_item(raw, index)
                for index, raw in enumerate(instance.items, 1)
            ]
            group_no = 0
            display_no = 0
            for token in group_offer_items(normalized):
                if token["kind"] == "group":
                    group_no += 1
                    instance.tree.insert(
                        "", "end", iid=f"g{group_no}",
                        values=(
                            "", "Skupina / podskupina", "", token["label"],
                            token["category"], token["subgroup"],
                            "", "", "", "", "", "", "", "",
                        ),
                        tags=("status_active",),
                    )
                    continue
                original_index = int(token["index"])
                display_no += 1
                item = service.normalize_item(token["item"], original_index + 1)
                priced = item.get("row_type") not in {"heading", "text"}
                product = item.get("row_type") == "product"
                values = (
                    display_no,
                    service.ROW_TYPES.get(item.get("row_type"), item.get("row_type")),
                    item.get("internal_code_snapshot") or item.get("product_code") or "",
                    issued_editor._display_name(item),
                    item.get("category_name_snapshot") if product else "",
                    item.get("subgroup_name_snapshot") if product else "",
                    issued_editor._fmt(item.get("quantity"), 3) if priced else "",
                    (item.get("unit") or "") if priced else "",
                    issued_editor._fmt(item.get("purchase_unit_price")) if priced else "",
                    f"{issued_editor._fmt(item.get('margin_pct'))} %" if priced else "",
                    issued_editor._fmt(item.get("recommended_unit_price")) if priced else "",
                    f"{issued_editor._fmt(item.get('discount_pct'))} %" if priced else "",
                    issued_editor._fmt(item.get("unit_price")) if priced else "",
                    issued_editor._fmt(item.get("total_price")) if priced else "",
                )
                tags = ("status_offer",) if item.get("row_type") == "heading" else ()
                instance.tree.insert(
                    "", "end", iid=f"r{original_index}", values=values, tags=tags
                )
            instance.items = normalized
            for index in selected_indices:
                iid = f"r{index}"
                if instance.tree.exists(iid):
                    instance.tree.selection_add(iid)
            instance.refresh_totals()

        Editor.refresh_items = refresh_items

        def assign_selected_taxonomy(instance):
            if getattr(instance, "locked", False):
                return
            indices = instance.selected_indices()
            if assign_taxonomy_to_items(instance.win, instance.items, indices, ask_pricing=True):
                instance.refresh_items()
                for index in indices:
                    iid = f"r{index}"
                    if instance.tree.exists(iid):
                        instance.tree.selection_add(iid)

        previous_editor_init = Editor.__init__

        def editor_init(instance, *args, **kwargs):
            previous_editor_init(instance, *args, **kwargs)
            try:
                toolbar = None
                for widget in walk(instance.win):
                    try:
                        if widget.winfo_class().endswith("Button") and _text(widget.cget("text")) == "+ Z katalogu":
                            toolbar = widget.master
                            break
                    except Exception:
                        pass
                if toolbar is not None:
                    button = M.ttk.Button(
                        toolbar,
                        text="Zařadit skupinu / podskupinu…",
                        command=lambda: instance.assign_selected_taxonomy(),
                    )
                    button.pack(side="left", padx=(14, 4))
                    instance._v710_taxonomy_button = button
                    if getattr(instance, "locked", False):
                        button.state(["disabled"])
                instance.tree.bind(
                    "<Control-g>", lambda _event: instance.assign_selected_taxonomy(), add="+"
                )
                transferred = [
                    index for index, item in enumerate(instance.items)
                    if item.get("source_supplier_offer_item_id")
                ]
                if transferred:
                    def select_transferred():
                        for index in transferred:
                            iid = f"r{index}"
                            if instance.tree.exists(iid):
                                instance.tree.selection_add(iid)
                        hint = _text(instance.status_hint.get())
                        extra = "Převzaté položky lze před uložením společně zařadit do skupiny a podskupiny."
                        if extra not in hint:
                            instance.status_hint.set((hint + " " + extra).strip())
                    instance.win.after_idle(select_transferred)
            except Exception:
                pass

        Editor.assign_selected_taxonomy = assign_selected_taxonomy
        Editor.__init__ = editor_init
        issued_editor._turto_v710_grouped_items = True

    # Transfer from a received offer always passes through a non-destructive
    # taxonomy staging dialog before the issued-offer editor is opened.
    if service is not None:
        try:
            from price_lists_domain.platform import commercial_workspace as commercial_workspace

            def offer_to_issued_offer(module, app):
                ids = commercial_workspace._selected_offer_ids(app)
                if len(ids) != 1:
                    return M.messagebox.showinfo(
                        "Přijaté nabídky", "Vyberte právě jednu přijatou nabídku.", parent=app
                    )
                try:
                    document, items = service.draft_from_supplier_offer(module, ids[0])
                except Exception as exc:
                    return M.messagebox.showerror(
                        "Přijaté nabídky",
                        f"Položky se nepodařilo připravit pro Vydanou nabídku:\n{exc}",
                        parent=app,
                    )
                dialog = TransferTaxonomyDialog(app, items)
                if dialog.result is None:
                    return None
                opener = getattr(module, "open_issued_offer_editor", None)
                if not callable(opener):
                    return M.messagebox.showerror(
                        "Přijaté nabídky",
                        "Editor Vydaných nabídek není v této instalaci dostupný.",
                        parent=app,
                    )
                return opener(
                    app, initial_document=document, initial_items=dialog.result
                )

            commercial_workspace._offer_to_issued_offer = offer_to_issued_offer
            M.TransferTaxonomyDialog = TransferTaxonomyDialog
        except Exception:
            pass

    # PDF renderer receives synthetic taxonomy headings only for rendering.
    if pdf_renderer is not None and service is not None and not getattr(pdf_renderer, "_turto_v710_grouped_pdf", False):
        original_render_offer_pdf = pdf_renderer.render_offer_pdf
        pdf_lock = threading.RLock()

        def grouped_pdf_items(items):
            result = []
            for token in group_offer_items(enrich_taxonomy(items)):
                if token["kind"] == "group":
                    result.append(
                        {
                            "row_type": "heading",
                            "name": token["label"],
                            "description": "",
                            "_automatic_taxonomy_heading": True,
                        }
                    )
                else:
                    result.append(dict(token["item"]))
            return result

        def render_offer_pdf(module, document_id, output_path=None, open_after=False):
            with pdf_lock:
                current_load = service.load_document

                def grouped_load(load_module, load_document_id):
                    document, items = current_load(load_module, load_document_id)
                    return document, grouped_pdf_items(items)

                service.load_document = grouped_load
                try:
                    return original_render_offer_pdf(
                        module, document_id, output_path, open_after
                    )
                finally:
                    service.load_document = current_load

        pdf_renderer.render_offer_pdf = render_offer_pdf
        M.render_issued_offer_pdf = (
            lambda document_id, output_path=None, open_after=False:
            render_offer_pdf(M, document_id, output_path, open_after)
        )
        pdf_renderer._turto_v710_grouped_pdf = True

    # ------------------------------------------------------------------
    # Request history, logical Tab order and batch archiving.
    # ------------------------------------------------------------------
    def request_refresh_similar(instance):
        if not hasattr(instance, "history_tree"):
            return
        for iid in instance.history_tree.get_children(""):
            instance.history_tree.delete(iid)
        action_id = instance.action_id()
        if not action_id:
            return
        params: list[Any] = [int(action_id)]
        sql = """SELECT r.id,r.asked_date,r.received_date,r.item,a.name action_name,
                        cu.official_name company_u,cf.official_name company_for
                   FROM requests r
                   LEFT JOIN actions a ON a.id=r.action_id
                   LEFT JOIN companies cu ON cu.id=r.company_id
                   LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                  WHERE r.action_id=?"""
        if instance.rid:
            sql += " AND r.id<>?"
            params.append(int(instance.rid))
        sql += " ORDER BY r.asked_date DESC,r.id DESC LIMIT 50"
        with M.db() as con:
            rows = con.execute(sql, params).fetchall()
        for row in rows:
            instance.history_tree.insert(
                "", "end", iid=f"h{row['id']}",
                values=(
                    M.fmt_date(row["asked_date"]),
                    row["company_for"] or "—",
                    row["company_u"] or "—",
                    row["action_name"] or "—",
                    row["item"] or "—",
                    "Obdrženo" if row["received_date"] else "Čekám",
                ),
            )

    RequestDialog = getattr(M, "RequestDialog", None)
    if RequestDialog is not None and not getattr(RequestDialog, "_turto_v700", False):
        original_request_init = RequestDialog.__init__
        RequestDialog.refresh_similar = request_refresh_similar

        def request_init(self, *args, **kwargs):
            original_request_init(self, *args, **kwargs)
            try:
                supplier = getattr(self, "company_box", None)
                customer = getattr(self, "requested_for_box", None)
                action = getattr(self, "action_box", None)
                supplier_focus = getattr(supplier, "entry", None) or supplier
                customer_focus = getattr(customer, "entry", None) or customer
                action_focus = getattr(action, "entry", None) or action
                if supplier_focus is not None and customer_focus is not None:
                    supplier_focus.bind(
                        "<Tab>", lambda _event: focus_widget(customer), add=False
                    )
                    customer_focus.bind(
                        "<Shift-Tab>", lambda _event: focus_widget(supplier), add=False
                    )
                if customer_focus is not None and action_focus is not None:
                    customer_focus.bind(
                        "<Tab>", lambda _event: focus_widget(action), add=False
                    )
                    action_focus.bind(
                        "<Shift-Tab>", lambda _event: focus_widget(customer), add=False
                    )
            except Exception:
                pass

        RequestDialog.__init__ = request_init
        RequestDialog._turto_v700 = True

    def selected_request_ids(app):
        result = []
        tree = getattr(app, "request_tree", None)
        if tree is None:
            return result
        for iid in tree.selection():
            value = str(iid)
            if value.lower().startswith("r"):
                try:
                    result.append(int(value[1:]))
                except Exception:
                    pass
        return list(dict.fromkeys(result))

    def archive_requests(app):
        ids = selected_request_ids(app)
        if not ids:
            return M.messagebox.showinfo(
                "Poptávka", "Vyberte jednu nebo více poptávek.", parent=app
            )
        marks = ",".join("?" for _ in ids)
        with M.db() as con:
            rows = con.execute(
                f"""SELECT r.*,a.name action_name,c.official_name company,
                            cf.official_name requested_for
                       FROM requests r
                       LEFT JOIN actions a ON a.id=r.action_id
                       LEFT JOIN companies c ON c.id=r.company_id
                       LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                      WHERE r.id IN ({marks})
                        AND coalesce(r.archived,0)=0
                      ORDER BY r.asked_date DESC,r.id DESC""",
                ids,
            ).fetchall()
        if not rows:
            return M.messagebox.showinfo(
                "Poptávka", "Všechny označené poptávky už jsou archivované.", parent=app
            )
        if len(rows) == 1:
            row = rows[0]
            prompt = (
                "Archivovat tuto poptávku?\n\n"
                f"Akce: {row['action_name'] or '—'}\n"
                f"Pro: {row['requested_for'] or '—'}\n"
                f"U: {row['company'] or '—'}\n"
                f"Poptáváno: {row['item'] or '—'}\n\n"
                "Záznam zůstane v databázi a historii."
            )
        else:
            preview = "\n".join(
                f"• {row['action_name'] or 'Bez Akce'} · "
                f"{row['company'] or '—'} · {row['item'] or '—'}"
                for row in rows[:8]
            )
            if len(rows) > 8:
                preview += f"\n• … a dalších {len(rows) - 8}"
            prompt = (
                f"Archivovat označené poptávky ({len(rows)})?\n\n{preview}\n\n"
                "Všechny záznamy zůstanou v databázi a historii."
            )
        if not M.messagebox.askyesno(
            "Archivovat poptávky", prompt, parent=app
        ):
            return
        user = active_user(app)
        for row in rows:
            try:
                M.log_history(
                    row["action_id"], "request_archive", "Archivoval poptávku",
                    f"Pro: {row['requested_for'] or '—'}; "
                    f"U: {row['company'] or '—'}; "
                    f"Poptáváno: {row['item'] or '—'}; "
                    f"Příjemci: {row['recipients_snapshot'] or '—'}",
                    row["company_id"], row["id"], user_name=user,
                )
            except Exception:
                pass
        active_ids = [int(row["id"]) for row in rows]
        marks = ",".join("?" for _ in active_ids)
        with M.db() as con:
            con.execute(
                f"UPDATE requests SET archived=1,archived_at=CURRENT_TIMESTAMP,"
                f"archived_by=? WHERE id IN ({marks})",
                [user] + active_ids,
            )
        try:
            app.req_show_archived.set(False)
        except Exception:
            pass
        refresh = getattr(app, "refresh_after_request_change", None)
        if callable(refresh):
            refresh()
        else:
            for name in ("refresh_requests", "refresh_dash"):
                try:
                    getattr(app, name)()
                except Exception:
                    pass

    if hasattr(M, "App"):
        M.App.archive_request = archive_requests

    # ------------------------------------------------------------------
    # Opportunity Akce selector uses the same inline layout as Company.
    # ------------------------------------------------------------------
    ActionDialog = getattr(M, "ActionDialog", None)
    if ActionDialog is not None and not getattr(ActionDialog, "_turto_v700_layout", False):
        original_action_init = ActionDialog.__init__

        def action_init(self, *args, **kwargs):
            original_action_init(self, *args, **kwargs)
            try:
                old_box = self.action_name_box
                parent = old_box.master
                info = old_box.grid_info()
                for child in list(parent.winfo_children()):
                    try:
                        if child.winfo_class().endswith("Button") and (
                            "nová akce" in _text(child.cget("text")).casefold()
                        ):
                            child.destroy()
                    except Exception:
                        pass
                old_box.destroy()
                wrapper = M.ttk.Frame(parent)
                wrapper.grid(
                    row=int(info.get("row", 0)),
                    column=int(info.get("column", 1)),
                    sticky="ew",
                    pady=info.get("pady", 5),
                )
                wrapper.columnconfigure(0, weight=1)
                values = [row["name"] for row in getattr(self, "projects", [])]
                self.action_name_box = M.AutocompleteEntry(
                    wrapper, textvariable=self.name, values=values
                )
                self.action_name_box.grid(row=0, column=0, sticky="ew")
                button = M.ttk.Button(
                    wrapper,
                    text="+ Nová akce",
                    takefocus=False,
                    command=lambda: self.new_project_from_opportunity(),
                )
                button.grid(row=0, column=1, padx=(6, 0))
                self._v700_action_wrapper = wrapper
            except Exception:
                pass

        ActionDialog.__init__ = action_init
        ActionDialog._turto_v700_layout = True

    # ------------------------------------------------------------------
    # Persistent Treeview geometry and configurable commercial columns.
    # ------------------------------------------------------------------
    layout_cache: dict[tuple[str, str], dict[str, Any] | None] = {}

    def tree_columns(tree):
        try:
            return [str(column) for column in tree.cget("columns")]
        except Exception:
            return []

    def ensure_heading_labels(tree):
        labels = dict(getattr(tree, "_turto_heading_labels", {}) or {})
        for column in tree_columns(tree):
            try:
                actual = _text(tree.heading(column, "text"))
            except Exception:
                actual = ""
            clean = actual.rstrip(" ▲▼").strip()
            if clean:
                labels[column] = clean
            else:
                fallback = _text(labels.get(column), column)
                labels[column] = fallback
                try:
                    tree.heading(column, text=fallback)
                except Exception:
                    pass
        tree._turto_heading_labels = labels
        return labels

    def displayed_columns(tree):
        columns = tree_columns(tree)
        try:
            raw = list(tree.cget("displaycolumns"))
        except Exception:
            raw = []
        if not raw or raw == ["#all"]:
            return columns
        result = []
        for value in raw:
            text = str(value)
            if text.isdigit():
                index = int(text)
                if 0 <= index < len(columns):
                    result.append(columns[index])
            elif text in columns:
                result.append(text)
        return result or columns

    def tree_layout_key(tree):
        title = ""
        try:
            title = _text(tree.winfo_toplevel().title(), "TURTO")
        except Exception:
            title = "TURTO"
        title = re.sub(r"\d+(?:\.\d+)+", "", title).strip() or "TURTO"
        columns = tree_columns(tree)
        raw = title + "|" + "|".join(columns)
        digest = hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:20]
        return f"tree_layout_v700_{digest}"

    def load_layout(tree):
        user = active_user(tree)
        key = tree_layout_key(tree)
        cache_key = (user, key)
        if cache_key in layout_cache:
            return layout_cache[cache_key]
        value = ""
        try:
            with M.db() as con:
                row = con.execute(
                    "SELECT value FROM user_settings WHERE user_name=? AND key=?",
                    (user, key),
                ).fetchone()
                value = _text(row[0]) if row else ""
        except Exception:
            pass
        try:
            state = json.loads(value) if value else None
            if not isinstance(state, dict):
                state = None
        except Exception:
            state = None
        layout_cache[cache_key] = state
        return state

    def save_layout(tree):
        user = active_user(tree)
        key = tree_layout_key(tree)
        columns = tree_columns(tree)
        visible = displayed_columns(tree)
        design = getattr(tree, "_turto_design_widths", {})
        widths = {}
        for column in columns:
            try:
                widths[column] = max(
                    30, int(design.get(column, tree.column(column, "width")))
                )
            except Exception:
                pass
        state = {"visible": visible, "widths": widths}
        layout_cache[(user, key)] = state
        try:
            with M.db() as con:
                con.execute(
                    "DELETE FROM user_settings WHERE user_name=? AND key=?",
                    (user, key),
                )
                con.execute(
                    "INSERT INTO user_settings(user_name,key,value) VALUES(?,?,?)",
                    (user, key, json.dumps(state, ensure_ascii=False)),
                )
        except Exception:
            pass

    def delete_layout(tree):
        user = active_user(tree)
        key = tree_layout_key(tree)
        layout_cache.pop((user, key), None)
        try:
            with M.db() as con:
                con.execute(
                    "DELETE FROM user_settings WHERE user_name=? AND key=?", (user, key)
                )
        except Exception:
            pass

    def fit_tree(tree, available=None):
        try:
            visible = displayed_columns(tree)
            if not visible:
                return
            width = int(available if available is not None else tree.winfo_width())
            if width <= 20:
                return
            design = getattr(tree, "_turto_design_widths", {})
            for column in tree_columns(tree):
                if column not in design:
                    design[column] = max(30, int(tree.column(column, "width")))
            tree._turto_design_widths = design
            target = max(1, width - 4)
            preferred = sum(max(30, int(design.get(column, 80))) for column in visible)
            filler = max(0, target - preferred)
            last = visible[-1]
            for column in visible:
                base = max(30, int(design.get(column, 80)))
                actual = base + (filler if column == last else 0)
                tree.column(
                    column,
                    width=actual,
                    minwidth=30,
                    stretch=bool(column == last and preferred <= target),
                )
            try:
                sync = getattr(tree, "_sync_filter_bar", None)
                if callable(sync):
                    tree.after_idle(sync)
            except Exception:
                pass
        except Exception:
            pass

    def schedule_tree_fit(tree, delay=90):
        try:
            previous = getattr(tree, "_v700_fit_after", None)
            if previous is not None:
                try:
                    tree.after_cancel(previous)
                except Exception:
                    pass
            tree._v700_fit_after = tree.after(
                delay,
                lambda: (
                    setattr(tree, "_v700_fit_after", None),
                    fit_tree(tree),
                ),
            )
        except Exception:
            fit_tree(tree)

    price_tokens = (
        "cena", "ceník", "nabídk", "marže", "sleva", "dph", "měna",
        "celkem", "price", "purchase", "margin", "discount", "vat",
    )

    def is_commercial_tree(tree):
        if bool(getattr(tree, "_turto_configurable_columns", False)):
            return True
        columns = tree_columns(tree)
        if len(columns) < 4:
            return False
        headings = []
        for column in columns:
            try:
                headings.append(_text(tree.heading(column, "text"), column).casefold())
            except Exception:
                headings.append(column.casefold())
        score = sum(
            1 for heading in headings
            if any(token in heading for token in price_tokens)
        )
        try:
            title = _text(tree.winfo_toplevel().title()).casefold()
        except Exception:
            title = ""
        contextual = any(
            token in title for token in ("cen", "nabídk", "produkt", "katalog")
        )
        return score >= 2 or (score >= 1 and contextual)

    def open_columns_dialog(tree):
        columns = tree_columns(tree)
        if not columns:
            return
        visible = displayed_columns(tree)
        ordered = visible + [column for column in columns if column not in visible]
        rows = [
            {"column": column, "visible": column in visible}
            for column in ordered
        ]
        host = tree.winfo_toplevel()
        dialog = M.tk.Toplevel(host)
        dialog.title("Nastavení sloupců")
        dialog.transient(host)
        dialog.grab_set()
        M.enable_dialog_maximize(dialog, 720, 590)
        frame = M.ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        M.ttk.Label(
            frame, text="Zobrazení a pořadí sloupců", font=("Calibri", 16, "bold")
        ).grid(row=0, column=0, sticky="w")
        M.ttk.Label(
            frame,
            text=(
                "Dvojklikem sloupec zobrazíte nebo skryjete. Šířku lze dál "
                "měnit přímo tažením v záhlaví tabulky."
            ),
            style="PageSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))
        listing = M.ttk.Treeview(
            frame,
            columns=("Zobrazeno", "Sloupec", "Šířka"),
            show="headings",
            selectmode="browse",
        )
        for column, width in (("Zobrazeno", 95), ("Sloupec", 390), ("Šířka", 90)):
            listing.heading(column, text=column)
            listing.column(column, width=width, anchor="w")
        listing.grid(row=2, column=0, sticky="nsew")
        scroll = M.ttk.Scrollbar(frame, orient="vertical", command=listing.yview)
        scroll.grid(row=2, column=1, sticky="ns")
        listing.configure(yscrollcommand=scroll.set)

        heading_labels = ensure_heading_labels(tree)

        def heading_text(column):
            try:
                value = _text(heading_labels.get(column), column)
                return value.rstrip(" ▲▼")
            except Exception:
                return column

        def render(select_index=None):
            for iid in listing.get_children(""):
                listing.delete(iid)
            design = getattr(tree, "_turto_design_widths", {})
            for index, row in enumerate(rows):
                column = row["column"]
                width = int(design.get(column, tree.column(column, "width")))
                listing.insert(
                    "", "end", iid=f"c{index}",
                    values=("✓" if row["visible"] else "—", heading_text(column), width),
                )
            if select_index is not None and 0 <= select_index < len(rows):
                iid = f"c{select_index}"
                listing.selection_set(iid)
                listing.focus(iid)
                listing.see(iid)

        def selected_index():
            selection = listing.selection()
            if not selection:
                return None
            try:
                return int(str(selection[0])[1:])
            except Exception:
                return None

        def toggle(*_):
            index = selected_index()
            if index is None:
                return
            rows[index]["visible"] = not rows[index]["visible"]
            render(index)

        def move(delta):
            index = selected_index()
            if index is None:
                return
            target = index + int(delta)
            if not 0 <= target < len(rows):
                return
            rows[index], rows[target] = rows[target], rows[index]
            render(target)

        def reset():
            defaults = getattr(tree, "_v700_default_widths", {})
            design = getattr(tree, "_turto_design_widths", {})
            for column in columns:
                if column in defaults:
                    design[column] = int(defaults[column])
            tree._turto_design_widths = design
            rows[:] = [{"column": column, "visible": True} for column in columns]
            render(0)

        def apply_changes(close=False):
            selected = [row["column"] for row in rows if row["visible"]]
            if not selected:
                return M.messagebox.showwarning(
                    "Nastavení sloupců",
                    "Alespoň jeden sloupec musí zůstat zobrazený.",
                    parent=dialog,
                )
            tree.configure(displaycolumns=tuple(selected))
            save_layout(tree)
            schedule_tree_fit(tree, 20)
            if close:
                dialog.destroy()

        listing.bind("<Double-1>", toggle)
        tools = M.ttk.Frame(frame)
        tools.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(9, 0))
        M.ttk.Button(tools, text="Zobrazit / skrýt", command=toggle).pack(side="left")
        M.ttk.Button(tools, text="↑ Nahoru", command=lambda: move(-1)).pack(side="left", padx=4)
        M.ttk.Button(tools, text="↓ Dolů", command=lambda: move(1)).pack(side="left")
        M.ttk.Button(tools, text="Výchozí", command=reset).pack(side="left", padx=(12, 0))
        M.ttk.Button(tools, text="Zavřít", command=dialog.destroy).pack(side="right")
        M.ttk.Button(
            tools, text="Použít", style="Accent.TButton",
            command=lambda: apply_changes(True),
        ).pack(side="right", padx=5)
        render(0)

    def reset_tree_layout(tree):
        delete_layout(tree)
        defaults = getattr(tree, "_v700_default_widths", {})
        design = getattr(tree, "_turto_design_widths", {})
        for column in tree_columns(tree):
            if column in defaults:
                design[column] = int(defaults[column])
        tree._turto_design_widths = design
        tree.configure(displaycolumns="#all")
        schedule_tree_fit(tree, 20)

    def install_tree(tree, force=False):
        try:
            if tree is None or not tree.winfo_exists():
                return
            columns = tree_columns(tree)
            if not columns:
                return
            ensure_heading_labels(tree)
            user = active_user(tree)
            first = not getattr(tree, "_v700_layout_installed", False)
            user_changed = getattr(tree, "_v700_layout_user", None) != user
            if first:
                tree._v700_layout_installed = True
                tree._v700_default_widths = {
                    column: max(30, int(tree.column(column, "width")))
                    for column in columns
                }
                tree._turto_design_widths = dict(tree._v700_default_widths)
            elif any(column not in getattr(tree, "_v700_default_widths", {}) for column in columns):
                for column in columns:
                    tree._v700_default_widths.setdefault(
                        column, max(30, int(tree.column(column, "width")))
                    )
                    tree._turto_design_widths.setdefault(
                        column, tree._v700_default_widths[column]
                    )
            if first or user_changed or force:
                state = load_layout(tree)
                if state:
                    saved_visible = [
                        column for column in state.get("visible", []) if column in columns
                    ]
                    if saved_visible:
                        tree.configure(displaycolumns=tuple(saved_visible))
                    widths = state.get("widths", {})
                    if isinstance(widths, dict):
                        for column, value in widths.items():
                            if column in columns:
                                try:
                                    tree._turto_design_widths[column] = max(30, int(value))
                                except Exception:
                                    pass
                tree._v700_layout_user = user
            if first:
                tree._v700_resize_column = None

                def press(event, current=tree):
                    try:
                        if current.identify_region(event.x, event.y) != "separator":
                            current._v700_resize_column = None
                            return
                        token = str(current.identify_column(event.x))
                        index = int(token.lstrip("#")) - 1
                        visible = displayed_columns(current)
                        current._v700_resize_column = (
                            visible[index] if 0 <= index < len(visible) else None
                        )
                    except Exception:
                        current._v700_resize_column = None

                def release(_event, current=tree):
                    column = getattr(current, "_v700_resize_column", None)
                    current._v700_resize_column = None
                    if not column:
                        return

                    def finish_resize():
                        try:
                            current._turto_design_widths[column] = max(
                                30, int(current.column(column, "width"))
                            )
                            save_layout(current)
                            fit_tree(current)
                        except Exception:
                            pass

                    current.after_idle(finish_resize)

                tree.bind("<ButtonPress-1>", press, add="+")
                tree.bind("<ButtonRelease-1>", release, add="+")
                tree.bind(
                    "<Configure>",
                    lambda event, current=tree: schedule_tree_fit(current, 120),
                    add="+",
                )
                tree.bind(
                    "<Map>",
                    lambda _event, current=tree: schedule_tree_fit(current, 40),
                    add="+",
                )
            if is_commercial_tree(tree) and not getattr(tree, "_v700_columns_menu", False):
                tree._v700_columns_menu = True

                def column_menu(event, current=tree):
                    try:
                        if current.identify_region(event.x, event.y) not in {"heading", "separator"}:
                            return None
                        menu = M.tk.Menu(current, tearoff=False)
                        menu.add_command(
                            label="Nastavit zobrazené sloupce…",
                            command=lambda: open_columns_dialog(current),
                        )
                        menu.add_command(
                            label="Obnovit výchozí sloupce",
                            command=lambda: reset_tree_layout(current),
                        )
                        menu.tk_popup(event.x_root, event.y_root)
                        return "break"
                    finally:
                        try:
                            menu.grab_release()
                        except Exception:
                            pass

                tree.bind("<Button-3>", column_menu, add="+")
                tree.bind(
                    "<Control-Shift-C>",
                    lambda _event, current=tree: open_columns_dialog(current),
                    add="+",
                )
            schedule_tree_fit(tree, 30)
        except Exception:
            pass

    auxiliary_prefixes = ("+", "⚙", "▣", "⌄", "⌃")

    def normalize_window(widget, force=False):
        for child in walk(widget):
            try:
                cls = child.winfo_class()
            except Exception:
                continue
            if cls == "Treeview":
                install_tree(child, force=force)
            elif cls.endswith("Button"):
                try:
                    label = _text(child.cget("text"))
                    if label.startswith(auxiliary_prefixes):
                        child.configure(takefocus=False)
                except Exception:
                    pass
        app = root_app(widget)
        try:
            request_tree = getattr(app, "request_tree", None)
            if request_tree is not None:
                request_tree.configure(selectmode="extended")
        except Exception:
            pass

    # Every future dialog receives consistent Tab and table behaviour after its
    # own constructor has finished building widgets.
    Toplevel = M.tk.Toplevel
    if not getattr(Toplevel, "_turto_v700_init", False):
        original_toplevel_init = Toplevel.__init__

        def toplevel_init(self, *args, **kwargs):
            original_toplevel_init(self, *args, **kwargs)
            try:
                self.bind(
                    "<Map>",
                    lambda _event, current=self: current.after_idle(
                        lambda: normalize_window(current)
                    ),
                    add="+",
                )
                for delay in (0, 100, 350, 900):
                    self.after(delay, lambda current=self: normalize_window(current))
            except Exception:
                pass

        Toplevel.__init__ = toplevel_init
        Toplevel._turto_v700_init = True

    M.install_persistent_tree_layout = install_tree
    M.save_persistent_tree_layout = save_layout
    M.open_tree_columns_dialog = open_columns_dialog
    M.group_issued_offer_items = group_offer_items

    old_schedule = getattr(M, "schedule_final_tree_layout", None)
    if callable(old_schedule):
        def schedule_final_tree_layout(app):
            result = old_schedule(app)
            for delay in (80, 260, 520):
                try:
                    app.after(delay, lambda current=app: normalize_window(current))
                except Exception:
                    pass
            return result
        M.schedule_final_tree_layout = schedule_final_tree_layout

    # Re-scan after all high-level refreshes because several legacy layers still
    # add or restore columns asynchronously.
    for method_name in (
        "refresh_dash", "refresh_actions", "refresh_requests", "refresh_mivo_requests",
        "refresh_projects", "refresh_offers", "refresh_issued_offers",
        "refresh_price_lists", "refresh_tasks", "refresh_companies", "refresh_people",
        "refresh_all", "show_page",
    ):
        original = getattr(M.App, method_name, None)
        if not callable(original):
            continue

        def make_wrapper(function):
            def wrapped(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                for delay in (60, 240, 560):
                    try:
                        self.after(delay, lambda current=self: normalize_window(current))
                    except Exception:
                        pass
                return result
            return wrapped

        setattr(M.App, method_name, make_wrapper(original))

    old_user_changed = getattr(M.App, "on_user_changed", None)
    if callable(old_user_changed):
        def on_user_changed(self, *args, **kwargs):
            result = old_user_changed(self, *args, **kwargs)
            layout_cache.clear()
            try:
                self.after(100, lambda: normalize_window(self, force=True))
            except Exception:
                pass
            return result
        M.App.on_user_changed = on_user_changed

    def register_configurable_tables(app):
        attributes = (
            "dash_tree", "dash_tasks_tree", "action_tree", "request_tree", "mivo_tree",
            "project_tree", "offer_tree", "issued_offer_tree", "price_current_tree",
            "price_evidence_tree", "price_list_tree", "task_tree", "company_tree",
            "people_tree", "person_tree",
        )
        for attribute in attributes:
            tree = getattr(app, attribute, None)
            if tree is None:
                continue
            try:
                tree._turto_configurable_columns = True
                ensure_heading_labels(tree)
                install_tree(tree, force=True)
            except Exception:
                pass
        tree = getattr(app, "mivo_tree", None)
        page = getattr(app, "tabs", {}).get("mivo") if hasattr(app, "tabs") else None
        if tree is None or page is None or getattr(app, "_v710_mivo_columns_button", None):
            return
        try:
            toolbar = None
            for child in page.winfo_children():
                texts = []
                for button in child.winfo_children():
                    try:
                        if button.winfo_class().endswith("Button"):
                            texts.append(_text(button.cget("text")))
                    except Exception:
                        pass
                if any("Archivovat" in text for text in texts):
                    toolbar = child
                    break
            if toolbar is not None:
                button = M.ttk.Button(
                    toolbar, text="Sloupce…", takefocus=False,
                    command=lambda: open_columns_dialog(tree),
                )
                button.pack(side="right", padx=4)
                app._v710_mivo_columns_button = button
        except Exception:
            pass

    old_app_init = M.App.__init__

    def app_init(self, *args, **kwargs):
        result = old_app_init(self, *args, **kwargs)
        M._active_app = self
        register_configurable_tables(self)
        for delay in (0, 180, 650, 1500):
            try:
                self.after(
                    delay,
                    lambda current=self: (
                        register_configurable_tables(current), normalize_window(current)
                    ),
                )
            except Exception:
                pass
        return result

    M.App.__init__ = app_init
    M._turto_v710_installed = True


__all__ = ["apply", "group_offer_items"]
