"""TURTO CRM 7.4 – issued-offer pricing context and uniform table controls.

This additive layer keeps the 7.3 data model intact while making the commercial
workflow explicit:
- issued offers use TURTO internal product codes and names wherever the catalogue
  can resolve them;
- category, subgroup and product pricing defaults are visible next to the actual
  line margin and discount;
- automatic grouping follows the database sort order;
- received-offer and MIVO columns are controlled consistently from the table
  heading context menu;
- the Products / prices browser can be filtered by supplier;
- Help lives in the top-right application controls next to Settings.
"""
from __future__ import annotations

import types
from collections import OrderedDict
from typing import Any, Iterable


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _fmt(value: Any, decimals: int = 2) -> str:
    return f"{_number(value):.{int(decimals)}f}".replace(".", ",")


def _widget_exists(widget) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def apply(M) -> None:
    if getattr(M, "_turto_v740_offer_defaults_installed", False):
        return

    try:
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import service
        from price_lists_domain.platform import commercial_workspace
        import v710_cleanup
    except Exception:
        M._turto_v740_offer_defaults_installed = True
        return

    # ------------------------------------------------------------------
    # Additive item snapshots for the pricing basis shown in issued offers.
    # ------------------------------------------------------------------
    def table_columns(con, table: str) -> set[str]:
        try:
            return {
                str(row[1])
                for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
        except Exception:
            return set()

    def ensure_v740_schema() -> None:
        with M.db() as con:
            tables = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "business_document_items" not in tables:
                return
            columns = table_columns(con, "business_document_items")
            for name, declaration in (
                ("base_margin_pct_snapshot", "REAL"),
                ("base_discount_pct_snapshot", "REAL"),
                ("pricing_rule_source_snapshot", "TEXT DEFAULT ''"),
            ):
                if name not in columns:
                    con.execute(
                        f'ALTER TABLE business_document_items '
                        f'ADD COLUMN "{name}" {declaration}'
                    )

    previous_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(previous_ensure_schema):
        def ensure_schema():
            result = previous_ensure_schema()
            ensure_v740_schema()
            return result

        M.ensure_schema = ensure_schema

    # ------------------------------------------------------------------
    # Taxonomy order and pricing defaults.
    # ------------------------------------------------------------------
    def sort_text(value: Any):
        helper = getattr(M, "czech_sort_key", None)
        if callable(helper):
            try:
                return helper(value)
            except Exception:
                pass
        return _text(value).casefold()

    def taxonomy_state() -> dict[str, Any]:
        categories: dict[int, dict[str, Any]] = {}
        subgroups: dict[int, dict[str, Any]] = {}
        try:
            with M.db() as con:
                for row in con.execute(
                    """SELECT id,name,sort_order,default_margin_pct,
                              default_discount_pct,show_recommended_price
                         FROM product_categories
                        ORDER BY sort_order,id"""
                ).fetchall():
                    categories[int(row["id"])] = {
                        "id": int(row["id"]),
                        "name": _text(row["name"], "Nezařazeno"),
                        "sort_order": int(row["sort_order"] or 0),
                        "margin_pct": _number(row["default_margin_pct"]),
                        "discount_pct": _number(row["default_discount_pct"]),
                        "show_recommended_price": bool(
                            int(row["show_recommended_price"] or 0)
                        ),
                    }
                for row in con.execute(
                    """SELECT id,category_id,name,sort_order,default_margin_pct,
                              default_discount_pct
                         FROM product_subgroups
                        ORDER BY category_id,sort_order,id"""
                ).fetchall():
                    subgroups[int(row["id"])] = {
                        "id": int(row["id"]),
                        "category_id": int(row["category_id"]),
                        "name": _text(row["name"], "Bez podskupiny"),
                        "sort_order": int(row["sort_order"] or 0),
                        "margin_pct": _number(row["default_margin_pct"]),
                        "discount_pct": _number(row["default_discount_pct"]),
                    }
        except Exception:
            pass
        return {"categories": categories, "subgroups": subgroups}

    def group_key(item: dict[str, Any]) -> tuple[Any, ...]:
        try:
            category_id = int(item["category_id"]) if item.get("category_id") else None
        except Exception:
            category_id = None
        try:
            subgroup_id = int(item["subgroup_id"]) if item.get("subgroup_id") else None
        except Exception:
            subgroup_id = None
        category = _text(
            item.get("category_name_snapshot") or item.get("category"),
            "Nezařazeno",
        )
        subgroup = _text(
            item.get("subgroup_name_snapshot") or item.get("subgroup"),
            "Bez podskupiny",
        )
        return (
            category_id if category_id is not None else f"name:{category.casefold()}",
            subgroup_id if subgroup_id is not None else f"name:{subgroup.casefold()}",
        )

    def ordered_group_tokens(
        segment: list[tuple[int, dict[str, Any]]],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not segment:
            return []
        buckets: "OrderedDict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]]" = OrderedDict()
        metadata: dict[tuple[Any, ...], dict[str, Any]] = {}
        categories = state["categories"]
        subgroups = state["subgroups"]
        for index, item in segment:
            key = group_key(item)
            buckets.setdefault(key, []).append((index, item))
            try:
                category_id = int(item["category_id"]) if item.get("category_id") else None
            except Exception:
                category_id = None
            try:
                subgroup_id = int(item["subgroup_id"]) if item.get("subgroup_id") else None
            except Exception:
                subgroup_id = None
            subgroup_info = subgroups.get(subgroup_id) if subgroup_id else None
            if subgroup_info:
                category_id = subgroup_info["category_id"]
            category_info = categories.get(category_id) if category_id else None
            category = _text(
                (category_info or {}).get("name")
                or item.get("category_name_snapshot")
                or item.get("category"),
                "Nezařazeno",
            )
            subgroup = _text(
                (subgroup_info or {}).get("name")
                or item.get("subgroup_name_snapshot")
                or item.get("subgroup"),
                "Bez podskupiny",
            )
            metadata.setdefault(
                key,
                {
                    "category_id": category_id,
                    "subgroup_id": subgroup_id,
                    "category": category,
                    "subgroup": subgroup,
                },
            )

        def key_order(key):
            meta = metadata[key]
            category_info = categories.get(meta["category_id"]) or {}
            subgroup_info = subgroups.get(meta["subgroup_id"]) or {}
            category_missing = meta["category_id"] is None
            subgroup_missing = meta["subgroup_id"] is None
            return (
                1 if category_missing else 0,
                int(category_info.get("sort_order", 10**9)),
                int(meta["category_id"] or 10**9),
                sort_text(meta["category"]),
                1 if subgroup_missing else 0,
                int(subgroup_info.get("sort_order", 10**9)),
                int(meta["subgroup_id"] or 10**9),
                sort_text(meta["subgroup"]),
            )

        result: list[dict[str, Any]] = []
        for key in sorted(buckets, key=key_order):
            meta = metadata[key]
            result.append(
                {
                    "kind": "group",
                    "category_id": meta["category_id"],
                    "subgroup_id": meta["subgroup_id"],
                    "category": meta["category"],
                    "subgroup": meta["subgroup"],
                    "label": f"{meta['category']} › {meta['subgroup']}",
                }
            )
            for original_index, item in buckets[key]:
                result.append(
                    {"kind": "item", "index": original_index, "item": item}
                )
        return result

    def group_offer_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Group consecutive product blocks in database taxonomy order.

        Explicit headings, text, services and delivery rows retain their position.
        Product rows between them are grouped by category/subgroup and those groups
        follow ``sort_order`` from the catalogue database.
        """
        rows = [(index, dict(raw or {})) for index, raw in enumerate(items)]
        state = taxonomy_state()
        result: list[dict[str, Any]] = []
        segment: list[tuple[int, dict[str, Any]]] = []

        def flush() -> None:
            nonlocal segment
            if segment:
                result.extend(ordered_group_tokens(segment, state))
                segment = []

        for index, item in rows:
            row_type = _text(item.get("row_type"), "product").casefold()
            if row_type == "product":
                segment.append((index, item))
            else:
                flush()
                result.append({"kind": "item", "index": index, "item": item})
        flush()
        return result

    v710_cleanup.group_offer_items = group_offer_items
    service.group_offer_items = group_offer_items
    M.group_issued_offer_items = group_offer_items

    def pricing_source(margin_source: str, discount_source: str) -> str:
        margin_source = _text(margin_source, "Výchozí")
        discount_source = _text(discount_source, "Výchozí")
        if margin_source == discount_source:
            return margin_source
        return f"Marže: {margin_source} · sleva: {discount_source}"

    # ------------------------------------------------------------------
    # Service wrappers: internal identity and pricing-basis snapshots.
    # ------------------------------------------------------------------
    original_normalize_item = service.normalize_item

    def normalize_item(raw, position=None, recalculate_sale=False):
        source = dict(raw or {})
        item = original_normalize_item(source, position, recalculate_sale)
        if _text(item.get("row_type"), "product").casefold() in {
            "heading",
            "text",
        }:
            item["base_margin_pct_snapshot"] = 0.0
            item["base_discount_pct_snapshot"] = 0.0
            item["pricing_rule_source_snapshot"] = ""
            return item

        margin = source.get("base_margin_pct_snapshot")
        discount = source.get("base_discount_pct_snapshot")
        item["base_margin_pct_snapshot"] = (
            _number(margin)
            if margin not in (None, "")
            else _number(item.get("margin_pct"))
        )
        item["base_discount_pct_snapshot"] = (
            _number(discount)
            if discount not in (None, "")
            else _number(item.get("discount_pct"))
        )
        item["pricing_rule_source_snapshot"] = _text(
            source.get("pricing_rule_source_snapshot"),
            "Ruční nastavení",
        )
        for key in (
            "_v740_missing_internal_identity",
            "_v740_internal_product_id",
            "_v740_source_code",
            "_v740_source_name",
        ):
            if key in source:
                item[key] = source[key]
        if _text(item.get("row_type"), "product").casefold() == "product":
            internal_code = _text(item.get("internal_code_snapshot"))
            internal_name = _text(item.get("internal_name_snapshot"))
            item["_v740_missing_internal_identity"] = not bool(
                internal_code and internal_name
            )
        return item

    service.normalize_item = normalize_item

    original_catalog_products = service.catalog_products

    def catalog_products(module, query="", limit=500):
        rows = [
            dict(row)
            for row in original_catalog_products(module, query, max(1, int(limit)))
        ]
        ids = [
            int(row.get("catalog_product_id") or row.get("id"))
            for row in rows
            if row.get("catalog_product_id") or row.get("id")
        ]
        details: dict[int, dict[str, Any]] = {}
        if ids:
            try:
                with module.db() as con:
                    cp_columns = table_columns(con, "catalog_products")
                    description_expr = (
                        "coalesce(cp.description,'')" if "description" in cp_columns
                        else "''"
                    )
                    margin_expr = (
                        "cp.default_margin_pct" if "default_margin_pct" in cp_columns
                        else "NULL"
                    )
                    discount_expr = (
                        "cp.default_discount_pct"
                        if "default_discount_pct" in cp_columns
                        else "NULL"
                    )
                    marks = ",".join("?" for _ in ids)
                    query_sql = f"""SELECT cp.id,cp.internal_code,cp.internal_name,
                                            {description_expr} description,
                                            {margin_expr} product_margin,
                                            {discount_expr} product_discount,
                                            cp.category_id,cp.subgroup_id,
                                            c.name category_name,
                                            c.sort_order category_sort,
                                            c.default_margin_pct category_margin,
                                            c.default_discount_pct category_discount,
                                            coalesce(c.show_recommended_price,1)
                                                show_recommended_price,
                                            s.name subgroup_name,
                                            s.sort_order subgroup_sort,
                                            s.default_margin_pct subgroup_margin,
                                            s.default_discount_pct subgroup_discount
                                       FROM catalog_products cp
                                       LEFT JOIN product_categories c
                                         ON c.id=cp.category_id
                                       LEFT JOIN product_subgroups s
                                         ON s.id=cp.subgroup_id
                                      WHERE cp.id IN ({marks})"""
                    for detail in con.execute(query_sql, ids).fetchall():
                        details[int(detail["id"])] = dict(detail)
            except Exception:
                details = {}

        result = []
        for raw in rows:
            product_id = int(raw.get("catalog_product_id") or raw.get("id"))
            detail = details.get(product_id, {})
            internal_code = _text(
                detail.get("internal_code") or raw.get("internal_code")
            )
            internal_name = _text(
                detail.get("internal_name") or raw.get("internal_name")
            )
            category_id = detail.get("category_id", raw.get("category_id"))
            subgroup_id = detail.get("subgroup_id", raw.get("subgroup_id"))
            product_margin = detail.get("product_margin")
            product_discount = detail.get("product_discount")
            if product_margin not in (None, ""):
                margin = _number(product_margin)
                margin_source = "Výrobek"
            elif subgroup_id:
                margin = _number(
                    detail.get("subgroup_margin", raw.get("margin_pct"))
                )
                margin_source = "Podskupina"
            else:
                margin = _number(
                    detail.get("category_margin", raw.get("margin_pct"))
                )
                margin_source = "Skupina"
            if product_discount not in (None, ""):
                discount = _number(product_discount)
                discount_source = "Výrobek"
            elif subgroup_id:
                discount = _number(
                    detail.get("subgroup_discount", raw.get("discount_pct"))
                )
                discount_source = "Podskupina"
            else:
                discount = _number(
                    detail.get("category_discount", raw.get("discount_pct"))
                )
                discount_source = "Skupina"

            purchase = _number(
                raw.get("purchase_unit_price", raw.get("purchase_price"))
            )
            recommended = purchase * (1.0 + margin / 100.0)
            sale = recommended * (1.0 - discount / 100.0)
            item = dict(raw)
            item.update(
                id=product_id,
                catalog_product_id=product_id,
                category_id=category_id,
                subgroup_id=subgroup_id,
                category=_text(
                    detail.get("category_name") or raw.get("category"),
                    "Nezařazeno",
                ),
                subgroup=_text(
                    detail.get("subgroup_name") or raw.get("subgroup"),
                    "Bez podskupiny",
                ),
                category_name_snapshot=_text(
                    detail.get("category_name") or raw.get("category"),
                    "Nezařazeno",
                ),
                subgroup_name_snapshot=_text(
                    detail.get("subgroup_name") or raw.get("subgroup"),
                    "Bez podskupiny",
                ),
                category_sort=int(detail.get("category_sort") or 10**9),
                subgroup_sort=int(detail.get("subgroup_sort") or 10**9),
                internal_code=internal_code,
                internal_name=internal_name,
                product_code=internal_code,
                item_key=internal_code or internal_name,
                name=internal_name,
                description=_text(detail.get("description")),
                internal_code_snapshot=internal_code,
                internal_name_snapshot=internal_name,
                margin_pct=margin,
                discount_pct=discount,
                base_margin_pct_snapshot=margin,
                base_discount_pct_snapshot=discount,
                pricing_rule_source_snapshot=pricing_source(
                    margin_source, discount_source
                ),
                recommended_unit_price=recommended,
                unit_price=sale,
                total_price=_number(item.get("quantity"), 1) * sale,
                show_recommended_price=1
                if bool(detail.get("show_recommended_price", True))
                else 0,
                _v740_internal_product_id=product_id,
                _v740_missing_internal_identity=not bool(
                    internal_code and internal_name
                ),
            )
            result.append(normalize_item(item))

        def sort_number(value, default=10**9):
            return int(value) if value not in (None, "") else int(default)

        result.sort(
            key=lambda item: (
                sort_number(item.get("category_sort")),
                sort_number(item.get("category_id")),
                sort_number(item.get("subgroup_sort")),
                sort_number(item.get("subgroup_id")),
                sort_text(
                    item.get("internal_name_snapshot")
                    or item.get("internal_code_snapshot")
                ),
                int(item.get("catalog_product_id") or 0),
            )
        )
        return result[: max(1, int(limit))]

    service.catalog_products = catalog_products

    def catalogue_product_details(module, product_id: int) -> dict[str, Any] | None:
        try:
            with module.db() as con:
                cp_columns = table_columns(con, "catalog_products")
                description_expr = (
                    "coalesce(cp.description,'')" if "description" in cp_columns
                    else "''"
                )
                margin_expr = (
                    "cp.default_margin_pct" if "default_margin_pct" in cp_columns
                    else "NULL"
                )
                discount_expr = (
                    "cp.default_discount_pct"
                    if "default_discount_pct" in cp_columns
                    else "NULL"
                )
                row = con.execute(
                    f"""SELECT cp.id,cp.internal_code,cp.internal_name,
                               {description_expr} description,
                               {margin_expr} product_margin,
                               {discount_expr} product_discount,
                               cp.category_id,cp.subgroup_id,
                               c.name category_name,c.default_margin_pct category_margin,
                               c.default_discount_pct category_discount,
                               coalesce(c.show_recommended_price,1)
                                   show_recommended_price,
                               s.name subgroup_name,s.default_margin_pct subgroup_margin,
                               s.default_discount_pct subgroup_discount
                          FROM catalog_products cp
                          LEFT JOIN product_categories c ON c.id=cp.category_id
                          LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id
                         WHERE cp.id=?""",
                    (int(product_id),),
                ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def match_catalogue_product_for_source(
        module, source_item_id: int
    ) -> dict[str, Any] | None:
        try:
            with module.db() as con:
                row = con.execute(
                    """SELECT i.id,i.catalog_product_id,i.product_code,i.item_key,
                              i.original_name,o.supplier_company_id,
                              coalesce(c.official_name,o.supplier_name,'') supplier
                         FROM supplier_offer_items i
                         JOIN supplier_offers o ON o.id=i.offer_id
                         LEFT JOIN companies c ON c.id=o.supplier_company_id
                        WHERE i.id=?""",
                    (int(source_item_id),),
                ).fetchone()
                if not row:
                    return None
                product_id = (
                    int(row["catalog_product_id"])
                    if row["catalog_product_id"]
                    else None
                )
                source_code = _text(row["product_code"] or row["item_key"])
                if not product_id and source_code:
                    hit = con.execute(
                        """SELECT s.product_id
                             FROM catalog_product_sources s
                            WHERE lower(trim(coalesce(s.supplier_product_code,'')))
                                  =lower(trim(?))
                              AND (
                                   (? IS NOT NULL AND s.supplier_company_id=?)
                                   OR lower(trim(coalesce(s.supplier_name,'')))
                                      =lower(trim(?))
                              )
                            ORDER BY CASE
                                       WHEN ? IS NOT NULL
                                            AND s.supplier_company_id=? THEN 0
                                       ELSE 1
                                     END,
                                     s.id
                            LIMIT 1""",
                        (
                            source_code,
                            row["supplier_company_id"],
                            row["supplier_company_id"],
                            row["supplier"],
                            row["supplier_company_id"],
                            row["supplier_company_id"],
                        ),
                    ).fetchone()
                    if hit:
                        product_id = int(hit["product_id"])
            return (
                catalogue_product_details(module, product_id)
                if product_id
                else None
            )
        except Exception:
            return None

    original_draft_from_supplier_offer = service.draft_from_supplier_offer

    def draft_from_supplier_offer(module, offer_id):
        document, items = original_draft_from_supplier_offer(module, offer_id)
        prepared = []
        for index, raw in enumerate(items, 1):
            item = dict(raw or {})
            source_id = item.get("source_supplier_offer_item_id")
            product = (
                match_catalogue_product_for_source(module, int(source_id))
                if source_id
                else None
            )
            if product:
                code = _text(product.get("internal_code"))
                name = _text(product.get("internal_name"))
                subgroup_id = product.get("subgroup_id")
                if product.get("product_margin") not in (None, ""):
                    margin = _number(product.get("product_margin"))
                    margin_source = "Výrobek"
                elif subgroup_id:
                    margin = _number(product.get("subgroup_margin"))
                    margin_source = "Podskupina"
                else:
                    margin = _number(product.get("category_margin"))
                    margin_source = "Skupina"
                if product.get("product_discount") not in (None, ""):
                    discount = _number(product.get("product_discount"))
                    discount_source = "Výrobek"
                elif subgroup_id:
                    discount = _number(product.get("subgroup_discount"))
                    discount_source = "Podskupina"
                else:
                    discount = _number(product.get("category_discount"))
                    discount_source = "Skupina"
                purchase = _number(item.get("purchase_unit_price"))
                recommended = purchase * (1.0 + margin / 100.0)
                sale = recommended * (1.0 - discount / 100.0)
                item.update(
                    product_code=code,
                    item_key=code or name,
                    name=name,
                    description=_text(product.get("description")),
                    internal_code_snapshot=code,
                    internal_name_snapshot=name,
                    category_id=product.get("category_id"),
                    subgroup_id=subgroup_id,
                    category_name_snapshot=_text(
                        product.get("category_name"), "Nezařazeno"
                    ),
                    subgroup_name_snapshot=_text(
                        product.get("subgroup_name"), "Bez podskupiny"
                    ),
                    margin_pct=margin,
                    discount_pct=discount,
                    base_margin_pct_snapshot=margin,
                    base_discount_pct_snapshot=discount,
                    pricing_rule_source_snapshot=pricing_source(
                        margin_source, discount_source
                    ),
                    recommended_unit_price=recommended,
                    unit_price=sale,
                    total_price=_number(item.get("quantity"), 1) * sale,
                    show_recommended_price=1
                    if bool(product.get("show_recommended_price", True))
                    else 0,
                    catalog_product_id=None,
                    _taxonomy_authoritative_ids=True,
                    _v740_internal_product_id=int(product["id"]),
                    _v740_missing_internal_identity=not bool(code and name),
                    _v740_source_code=_text(
                        raw.get("product_code") or raw.get("item_key")
                    ),
                    _v740_source_name=_text(raw.get("name")),
                )
            else:
                item.update(
                    base_margin_pct_snapshot=_number(item.get("margin_pct")),
                    base_discount_pct_snapshot=_number(
                        item.get("discount_pct")
                    ),
                    pricing_rule_source_snapshot="Zařazení přijaté nabídky",
                    _v740_missing_internal_identity=True,
                    _v740_source_code=_text(
                        raw.get("product_code") or raw.get("item_key")
                    ),
                    _v740_source_name=_text(raw.get("name")),
                )
            prepared.append(normalize_item(item, index))
        return document, prepared

    service.draft_from_supplier_offer = draft_from_supplier_offer

    original_save_document = service.save_document

    def save_document(module, values, items, document_id=None):
        ensure_v740_schema()
        prepared = [
            normalize_item(dict(item or {}), index)
            for index, item in enumerate(list(items), 1)
        ]
        result = original_save_document(
            module, values, prepared, document_id
        )
        try:
            with module.db() as con:
                rows = con.execute(
                    """SELECT id,position FROM business_document_items
                       WHERE document_id=? ORDER BY position,id""",
                    (int(result),),
                ).fetchall()
                for row, item in zip(rows, prepared):
                    con.execute(
                        """UPDATE business_document_items
                              SET base_margin_pct_snapshot=?,
                                  base_discount_pct_snapshot=?,
                                  pricing_rule_source_snapshot=?
                            WHERE id=?""",
                        (
                            _number(item.get("base_margin_pct_snapshot")),
                            _number(item.get("base_discount_pct_snapshot")),
                            _text(item.get("pricing_rule_source_snapshot")),
                            int(row["id"]),
                        ),
                    )
        except Exception:
            pass
        return result

    service.save_document = save_document

    # ------------------------------------------------------------------
    # Product picker with database hierarchy and visible pricing defaults.
    # ------------------------------------------------------------------
    class ProductPicker:
        def __init__(self, module, parent):
            self.M = module
            self.result: list[dict[str, Any]] = []
            self.rows: dict[str, dict[str, Any]] = {}
            self.scope_kind = "all"
            self.scope_id = None
            self.win = module.tk.Toplevel(parent)
            self.win.title("Vybrat produkty z katalogu")
            self.win.transient(parent)
            self.win.grab_set()
            module.enable_dialog_maximize(self.win, 1480, 820)

            outer = module.ttk.Frame(self.win, padding=14)
            outer.pack(fill="both", expand=True)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(2, weight=1)
            module.ttk.Label(
                outer,
                text="Produkty z interního katalogu",
                font=("Calibri", 16, "bold"),
            ).grid(row=0, column=0, sticky="w")
            module.ttk.Label(
                outer,
                text=(
                    "Do Vydané nabídky se přenáší výhradně interní kód a "
                    "interní označení TURTO. Základní marže a sleva ukazují "
                    "výchozí pravidlo před případnou ruční změnou položky."
                ),
                style="PageSubtitle.TLabel",
                wraplength=1250,
            ).grid(row=1, column=0, sticky="w", pady=(2, 8))

            body = module.ttk.Panedwindow(outer, orient="horizontal")
            body.grid(row=2, column=0, sticky="nsew")
            structure = module.ttk.Frame(body, style="Panel.TFrame", padding=8)
            products = module.ttk.Frame(body)
            body.add(structure, weight=1)
            body.add(products, weight=4)
            structure.columnconfigure(0, weight=1)
            structure.rowconfigure(1, weight=1)
            products.columnconfigure(0, weight=1)
            products.rowconfigure(2, weight=1)

            module.ttk.Label(
                structure,
                text="Skupiny a podskupiny",
                font=("Calibri", 11, "bold"),
            ).grid(row=0, column=0, sticky="w", pady=(0, 5))
            self.structure = module.ttk.Treeview(
                structure,
                columns=("Marže", "Sleva"),
                show="tree headings",
                selectmode="browse",
            )
            self.structure.heading("#0", text="Zařazení")
            self.structure.heading("Marže", text="Zákl. marže")
            self.structure.heading("Sleva", text="Zákl. sleva")
            self.structure.column("#0", width=330, minwidth=180)
            self.structure.column("Marže", width=95, minwidth=75, anchor="e")
            self.structure.column("Sleva", width=95, minwidth=75, anchor="e")
            self.structure.grid(row=1, column=0, sticky="nsew")
            sy = module.ttk.Scrollbar(
                structure, orient="vertical", command=self.structure.yview
            )
            sy.grid(row=1, column=1, sticky="ns")
            self.structure.configure(yscrollcommand=sy.set)

            self.query = module.tk.StringVar()
            search = module.ttk.Frame(
                products, style="Panel.TFrame", padding=8
            )
            search.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            search.columnconfigure(1, weight=1)
            module.ttk.Label(search, text="Hledat:").grid(
                row=0, column=0, sticky="w", padx=(0, 6)
            )
            entry = module.ttk.Entry(search, textvariable=self.query)
            entry.grid(row=0, column=1, sticky="ew")
            module.ttk.Button(
                search, text="Vymazat", command=lambda: self.query.set("")
            ).grid(row=0, column=2, padx=(6, 0))
            self.scope_label = module.tk.StringVar(value="Všechny produkty")
            module.ttk.Label(
                products,
                textvariable=self.scope_label,
                style="PageSubtitle.TLabel",
            ).grid(row=1, column=0, sticky="w", pady=(0, 4))

            columns = (
                "Interní kód",
                "Interní označení",
                "Výrobce",
                "Skupina",
                "Podskupina",
                "Zákl. marže",
                "Zákl. sleva",
                "Zdroj pravidla",
                "Nákupní cena",
                "MJ",
                "Zdroj ceny",
            )
            widths = (
                125,
                300,
                165,
                220,
                240,
                95,
                95,
                185,
                115,
                60,
                220,
            )
            wrap = module.ttk.Frame(products)
            wrap.grid(row=2, column=0, sticky="nsew")
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)
            self.tree = module.ttk.Treeview(
                wrap,
                columns=columns,
                show="headings",
                selectmode="extended",
            )
            for column, width in zip(columns, widths):
                self.tree.heading(column, text=column)
                self.tree.column(
                    column,
                    width=width,
                    minwidth=45,
                    anchor="w",
                    stretch=False,
                )
            self.tree.grid(row=0, column=0, sticky="nsew")
            ys = module.ttk.Scrollbar(
                wrap, orient="vertical", command=self.tree.yview
            )
            xs = module.ttk.Scrollbar(
                wrap, orient="horizontal", command=self.tree.xview
            )
            ys.grid(row=0, column=1, sticky="ns")
            xs.grid(row=1, column=0, sticky="ew")
            self.tree.configure(
                yscrollcommand=ys.set, xscrollcommand=xs.set
            )

            buttons = module.ttk.Frame(outer)
            buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
            module.ttk.Button(
                buttons, text="Zrušit", command=self.win.destroy
            ).pack(side="right")
            module.ttk.Button(
                buttons,
                text="Přidat vybrané",
                style="Accent.TButton",
                command=self.finish,
            ).pack(side="right", padx=(0, 6))

            self.structure.bind(
                "<<TreeviewSelect>>", lambda _event: self.scope_changed()
            )
            self.tree.bind("<Double-1>", lambda _event: self.finish())
            self.query.trace_add("write", lambda *_: self.refresh())
            self.load_structure()
            self.structure.selection_set("all")
            self.refresh()
            try:
                installer = getattr(
                    module, "install_persistent_tree_layout", None
                )
                if callable(installer):
                    self.tree._turto_configurable_columns = True
                    installer(self.tree, force=True)
            except Exception:
                pass
            self.win.wait_window()

        def load_structure(self):
            state = taxonomy_state()
            self.structure.insert(
                "", "end", iid="all", text="Všechny produkty", open=True
            )
            for category in sorted(
                state["categories"].values(),
                key=lambda row: (
                    row["sort_order"],
                    row["id"],
                ),
            ):
                category_iid = f"c{category['id']}"
                self.structure.insert(
                    "",
                    "end",
                    iid=category_iid,
                    text=category["name"],
                    values=(
                        f"{_fmt(category['margin_pct'])} %",
                        f"{_fmt(category['discount_pct'])} %",
                    ),
                    open=True,
                )
                children = [
                    row
                    for row in state["subgroups"].values()
                    if row["category_id"] == category["id"]
                ]
                children.sort(key=lambda row: (row["sort_order"], row["id"]))
                for subgroup in children:
                    self.structure.insert(
                        category_iid,
                        "end",
                        iid=f"s{subgroup['id']}",
                        text=subgroup["name"],
                        values=(
                            f"{_fmt(subgroup['margin_pct'])} %",
                            f"{_fmt(subgroup['discount_pct'])} %",
                        ),
                    )
            self.structure.insert(
                "", "end", iid="unassigned", text="Nezařazeno"
            )

        def scope_changed(self):
            selection = self.structure.selection()
            iid = str(selection[0]) if selection else "all"
            if iid.startswith("c") and iid[1:].isdigit():
                self.scope_kind = "category"
                self.scope_id = int(iid[1:])
                self.scope_label.set(
                    "Produkty ve vybrané produktové skupině"
                )
            elif iid.startswith("s") and iid[1:].isdigit():
                self.scope_kind = "subgroup"
                self.scope_id = int(iid[1:])
                self.scope_label.set(
                    "Produkty ve vybrané podskupině"
                )
            elif iid == "unassigned":
                self.scope_kind = "unassigned"
                self.scope_id = None
                self.scope_label.set("Nezařazené produkty")
            else:
                self.scope_kind = "all"
                self.scope_id = None
                self.scope_label.set("Všechny produkty")
            self.refresh()

        def refresh(self):
            selected = set(self.tree.selection())
            for iid in self.tree.get_children(""):
                self.tree.delete(iid)
            self.rows.clear()
            for row in service.catalog_products(
                self.M, self.query.get(), 2000
            ):
                if (
                    self.scope_kind == "category"
                    and int(row.get("category_id") or 0)
                    != int(self.scope_id or 0)
                ):
                    continue
                if (
                    self.scope_kind == "subgroup"
                    and int(row.get("subgroup_id") or 0)
                    != int(self.scope_id or 0)
                ):
                    continue
                if self.scope_kind == "unassigned" and row.get("category_id"):
                    continue
                product_id = int(row["catalog_product_id"])
                iid = f"cp{product_id}"
                self.rows[iid] = row
                code = _text(row.get("internal_code_snapshot"))
                name = _text(row.get("internal_name_snapshot"))
                self.tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        code or "⚠ chybí",
                        name or "⚠ chybí interní označení",
                        row.get("manufacturer_name") or "",
                        row.get("category_name_snapshot") or "Nezařazeno",
                        row.get("subgroup_name_snapshot")
                        or "Bez podskupiny",
                        f"{_fmt(row.get('base_margin_pct_snapshot'))} %",
                        f"{_fmt(row.get('base_discount_pct_snapshot'))} %",
                        row.get("pricing_rule_source_snapshot") or "",
                        _fmt(row.get("purchase_unit_price")),
                        row.get("unit") or "",
                        row.get("price_source_label") or "",
                    ),
                    tags=("status_wait",)
                    if not code or not name
                    else (),
                )
            for iid in selected:
                if self.tree.exists(iid):
                    self.tree.selection_add(iid)

        def finish(self):
            selected = [
                self.rows[iid]
                for iid in self.tree.selection()
                if iid in self.rows
            ]
            if not selected:
                return self.M.messagebox.showinfo(
                    "Vydané nabídky",
                    "Vyberte jeden nebo více produktů.",
                    parent=self.win,
                )
            incomplete = [
                row
                for row in selected
                if not _text(row.get("internal_code_snapshot"))
                or not _text(row.get("internal_name_snapshot"))
            ]
            if incomplete:
                return self.M.messagebox.showwarning(
                    "Interní kód a označení",
                    "Vybrané produkty zatím nemají vyplněný interní kód "
                    "nebo interní označení TURTO. Doplňte je nejprve v "
                    "Katalogu produktů.",
                    parent=self.win,
                )
            self.result = [
                service.normalize_item(dict(item), index)
                for index, item in enumerate(selected, 1)
            ]
            self.win.destroy()

    issued_editor.ProductPicker = ProductPicker
    M.ProductPicker = ProductPicker

    # ------------------------------------------------------------------
    # Issued-offer item table: defaults at category, subgroup and product level.
    # ------------------------------------------------------------------
    Editor = issued_editor.IssuedOfferEditor
    editor_columns = (
        "Poz.",
        "Typ",
        "Kód",
        "Označení",
        "Skupina",
        "Podskupina",
        "Zákl. marže",
        "Zákl. sleva",
        "Zdroj základu",
        "Množství",
        "MJ",
        "Nákupní cena",
        "Marže",
        "Doporučená cena",
        "Sleva",
        "Prodejní cena",
        "Celkem bez DPH",
    )
    editor_widths = (
        55,
        105,
        125,
        320,
        220,
        235,
        95,
        95,
        185,
        90,
        60,
        115,
        75,
        125,
        75,
        115,
        130,
    )

    def ensure_editor_columns(instance):
        tree = instance.tree
        if tuple(tree.cget("columns")) != editor_columns:
            tree.configure(columns=editor_columns, show="headings")
        for column, default_width in zip(editor_columns, editor_widths):
            tree.heading(column, text=column)
            try:
                current_width = int(tree.column(column, "width"))
            except Exception:
                current_width = default_width
            tree.column(
                column,
                width=current_width if current_width >= 30 else default_width,
                minwidth=35,
                anchor="w",
                stretch=False,
            )
        if not getattr(tree, "_v740_columns_ready", False):
            tree._v740_columns_ready = True
            tree._turto_configurable_columns = True
            try:
                installer = getattr(
                    M, "install_persistent_tree_layout", None
                )
                if callable(installer):
                    installer(tree, force=True)
            except Exception:
                pass

    def editor_refresh_items(instance, *_args, **_kwargs):
        ensure_editor_columns(instance)
        selected_indices = []
        for iid in instance.tree.selection():
            text = str(iid)
            if text.startswith("r") and text[1:].isdigit():
                selected_indices.append(int(text[1:]))

        for iid in instance.tree.get_children(""):
            instance.tree.delete(iid)

        normalized = [
            service.normalize_item(raw, index)
            for index, raw in enumerate(instance.items, 1)
        ]
        state = taxonomy_state()
        categories = state["categories"]
        subgroups = state["subgroups"]
        category_row = 0
        subgroup_row = 0
        display_no = 0
        last_category = object()

        for token in group_offer_items(normalized):
            if token["kind"] == "group":
                category_id = token.get("category_id")
                subgroup_id = token.get("subgroup_id")
                category = token["category"]
                subgroup = token["subgroup"]
                category_info = categories.get(category_id) or {
                    "margin_pct": 0,
                    "discount_pct": 0,
                }
                subgroup_info = subgroups.get(subgroup_id)
                category_marker = (
                    category_id,
                    _text(category).casefold(),
                )
                if category_marker != last_category:
                    category_row += 1
                    instance.tree.insert(
                        "",
                        "end",
                        iid=f"cg{category_row}",
                        values=(
                            "",
                            "Skupina",
                            "",
                            category,
                            category,
                            "",
                            f"{_fmt(category_info.get('margin_pct'))} %",
                            f"{_fmt(category_info.get('discount_pct'))} %",
                            "Skupina",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                            "",
                        ),
                        tags=("status_active",),
                    )
                    last_category = category_marker
                subgroup_row += 1
                if subgroup_info:
                    subgroup_margin = subgroup_info["margin_pct"]
                    subgroup_discount = subgroup_info["discount_pct"]
                    subgroup_source = "Podskupina"
                else:
                    subgroup_margin = category_info.get("margin_pct", 0)
                    subgroup_discount = category_info.get(
                        "discount_pct", 0
                    )
                    subgroup_source = "Skupina"
                instance.tree.insert(
                    "",
                    "end",
                    iid=f"sg{subgroup_row}",
                    values=(
                        "",
                        "Podskupina",
                        "",
                        f"↳ {subgroup}",
                        category,
                        subgroup,
                        f"{_fmt(subgroup_margin)} %",
                        f"{_fmt(subgroup_discount)} %",
                        subgroup_source,
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ),
                    tags=("status_offer",),
                )
                continue

            original_index = int(token["index"])
            item = service.normalize_item(
                token["item"], original_index + 1
            )
            priced = item.get("row_type") not in {"heading", "text"}
            product = item.get("row_type") == "product"
            display_no += 1
            values = (
                display_no,
                service.ROW_TYPES.get(
                    item.get("row_type"), item.get("row_type")
                ),
                item.get("internal_code_snapshot")
                or item.get("product_code")
                or "",
                issued_editor._display_name(item),
                item.get("category_name_snapshot") if product else "",
                item.get("subgroup_name_snapshot") if product else "",
                f"{_fmt(item.get('base_margin_pct_snapshot'))} %"
                if priced
                else "",
                f"{_fmt(item.get('base_discount_pct_snapshot'))} %"
                if priced
                else "",
                item.get("pricing_rule_source_snapshot") if priced else "",
                issued_editor._fmt(item.get("quantity"), 3)
                if priced
                else "",
                (item.get("unit") or "") if priced else "",
                issued_editor._fmt(item.get("purchase_unit_price"))
                if priced
                else "",
                f"{issued_editor._fmt(item.get('margin_pct'))} %"
                if priced
                else "",
                issued_editor._fmt(item.get("recommended_unit_price"))
                if priced
                else "",
                f"{issued_editor._fmt(item.get('discount_pct'))} %"
                if priced
                else "",
                issued_editor._fmt(item.get("unit_price"))
                if priced
                else "",
                issued_editor._fmt(item.get("total_price"))
                if priced
                else "",
            )
            tags = (
                ("status_wait",)
                if item.get("_v740_missing_internal_identity")
                else (("status_offer",) if item.get("row_type") == "heading" else ())
            )
            instance.tree.insert(
                "",
                "end",
                iid=f"r{original_index}",
                values=values,
                tags=tags,
            )

        instance.items = normalized
        for index in selected_indices:
            iid = f"r{index}"
            if instance.tree.exists(iid):
                instance.tree.selection_add(iid)
        instance.refresh_totals()

        preview = getattr(instance, "_v720_preview", None)
        if preview is not None:
            try:
                preview.schedule(100)
            except Exception:
                pass
        panel = getattr(instance, "_v720_internal_panel", None)
        if panel is not None:
            indices = instance.selected_indices()
            try:
                panel.load(indices[0] if len(indices) == 1 else None)
            except Exception:
                pass

    Editor.refresh_items = editor_refresh_items

    previous_editor_init = Editor.__init__

    def editor_init(self, *args, **kwargs):
        result = previous_editor_init(self, *args, **kwargs)
        try:
            hint = _text(self.status_hint.get())
            extra = (
                "Zákl. marže a Zákl. sleva ukazují pravidlo skupiny, "
                "podskupiny nebo výrobku; sloupce Marže a Sleva jsou "
                "skutečné hodnoty konkrétního řádku."
            )
            if extra not in hint:
                self.status_hint.set((hint + " " + extra).strip())
        except Exception:
            pass

        panel = getattr(self, "_v720_internal_panel", None)
        if panel is not None and not getattr(
            panel, "_v740_basis_installed", False
        ):
            panel._v740_basis_installed = True
            try:
                next_row = int(panel.page.grid_size()[1])
                M.ttk.Separator(panel.page).grid(
                    row=next_row,
                    column=0,
                    columnspan=2,
                    sticky="ew",
                    pady=(10, 7),
                )
                panel._v740_basis = M.tk.StringVar(value="")
                M.ttk.Label(
                    panel.page,
                    text="Základní cenové pravidlo",
                    font=("Calibri", 10, "bold"),
                ).grid(
                    row=next_row + 1,
                    column=0,
                    columnspan=2,
                    sticky="w",
                )
                M.ttk.Label(
                    panel.page,
                    textvariable=panel._v740_basis,
                    style="PageSubtitle.TLabel",
                    wraplength=290,
                    justify="left",
                ).grid(
                    row=next_row + 2,
                    column=0,
                    columnspan=2,
                    sticky="w",
                    pady=(2, 0),
                )
                original_panel_load = panel.load

                def load_basis(current, index):
                    value = original_panel_load(index)
                    try:
                        idx = int(index)
                    except Exception:
                        idx = -1
                    if 0 <= idx < len(current.instance.items):
                        item = service.normalize_item(
                            current.instance.items[idx], idx + 1
                        )
                        current._v740_basis.set(
                            f"Marže {_fmt(item.get('base_margin_pct_snapshot'))} % "
                            f"· sleva {_fmt(item.get('base_discount_pct_snapshot'))} %\n"
                            f"{_text(item.get('pricing_rule_source_snapshot'), 'Ruční nastavení')}"
                        )
                    else:
                        current._v740_basis.set("")
                    return value

                panel.load = types.MethodType(load_basis, panel)
                indices = self.selected_indices()
                panel.load(indices[0] if len(indices) == 1 else None)
            except Exception:
                pass
        return result

    Editor.__init__ = editor_init
    Editor._turto_v740_pricing_basis = True

    def missing_internal_identity_indices(instance):
        missing = []
        for index, raw in enumerate(instance.items):
            item = service.normalize_item(raw, index + 1)
            if _text(item.get("row_type"), "product").casefold() != "product":
                continue
            code = _text(item.get("internal_code_snapshot"))
            name = _text(item.get("internal_name_snapshot"))
            if not code or not name:
                missing.append(index)
        return missing

    def require_internal_identity(instance, action_text):
        missing = missing_internal_identity_indices(instance)
        if not missing:
            return True
        first = missing[0]
        try:
            instance.tree.selection_set(f"r{first}")
            instance.tree.see(f"r{first}")
        except Exception:
            pass
        M.messagebox.showwarning(
            "Interní kódy a názvy",
            f"Nelze {action_text}.\n\n"
            f"{len(missing)} produktových položek nemá vyplněný interní "
            "kód nebo interní název TURTO. Doplňte označené řádky a "
            "akci zopakujte.",
            parent=instance.win,
        )
        return False

    previous_generate_pdf = Editor.generate_pdf

    def generate_pdf(self, *args, **kwargs):
        if not require_internal_identity(self, "vytvořit zákaznické PDF"):
            return None
        return previous_generate_pdf(self, *args, **kwargs)

    Editor.generate_pdf = generate_pdf

    previous_outlook_draft = Editor.outlook_draft

    def outlook_draft(self, *args, **kwargs):
        if not require_internal_identity(self, "vytvořit Outlook koncept"):
            return None
        return previous_outlook_draft(self, *args, **kwargs)

    Editor.outlook_draft = outlook_draft
    Editor._turto_v740_internal_identity_guard = True

    # Warn visibly when a received offer could not be resolved to TURTO identity.
    TransferDialog = getattr(M, "TransferTaxonomyDialog", None)
    if TransferDialog is not None and not getattr(
        TransferDialog, "_turto_v740_identity_warning", False
    ):
        previous_transfer_refresh = TransferDialog.refresh
        previous_transfer_finish = TransferDialog.finish

        def transfer_refresh(self, *args, **kwargs):
            result = previous_transfer_refresh(self, *args, **kwargs)
            for index, item in enumerate(self.items):
                if not item.get("_v740_missing_internal_identity"):
                    continue
                iid = f"r{index}"
                try:
                    if self.tree.exists(iid):
                        code = _text(self.tree.set(iid, "Kód"))
                        self.tree.set(
                            iid,
                            "Kód",
                            "⚠ " + (code or "chybí interní kód"),
                        )
                        self.tree.item(iid, tags=("status_wait",))
                except Exception:
                    pass
            return result

        def transfer_finish(self):
            missing = [
                item
                for item in self.items
                if _text(item.get("row_type"), "product").casefold()
                == "product"
                and item.get("_v740_missing_internal_identity")
            ]
            if missing:
                if not M.messagebox.askyesno(
                    "Interní kódy a názvy",
                    f"{len(missing)} položek se nepodařilo automaticky "
                    "spárovat s interním produktem TURTO.\n\n"
                    "V konceptu budou označené žlutě a před odesláním je "
                    "nutné upravit na naše kódy a názvy.\n\n"
                    "Pokračovat do Vydané nabídky?",
                    parent=self.win,
                ):
                    return
            return previous_transfer_finish(self)

        TransferDialog.refresh = transfer_refresh
        TransferDialog.finish = transfer_finish
        TransferDialog._turto_v740_identity_warning = True

    # ------------------------------------------------------------------
    # Products / prices: supplier filter in addition to full-text search.
    # ------------------------------------------------------------------
    BasePriceBrowser = getattr(M, "ProductPriceBrowser", None)
    if BasePriceBrowser is not None:
        class ProductPriceBrowser(BasePriceBrowser):
            def __init__(self, parent):
                self.supplier_filter = None
                super().__init__(parent)
                try:
                    frame = self.t.master
                    top = frame.winfo_children()[0]
                    suppliers = []
                    with M.db() as con:
                        suppliers = [
                            _text(row[0])
                            for row in con.execute(
                                """SELECT DISTINCT
                                          coalesce(nullif(trim(c.official_name),''),
                                                   nullif(trim(o.supplier_name),''),'')
                                           supplier
                                     FROM supplier_offers o
                                     LEFT JOIN companies c
                                       ON c.id=o.supplier_company_id
                                    WHERE trim(coalesce(
                                          nullif(trim(c.official_name),''),
                                          nullif(trim(o.supplier_name),''),''))<>''
                                    ORDER BY supplier COLLATE CZECH"""
                            ).fetchall()
                        ]
                    self.supplier_filter = M.tk.StringVar(
                        value="Všichni dodavatelé"
                    )
                    box = M.safe_combobox(
                        top,
                        textvariable=self.supplier_filter,
                        values=["Všichni dodavatelé"] + suppliers,
                        state="readonly",
                        width=28,
                    )
                    box.pack(side="right", padx=(12, 0))
                    M.ttk.Label(top, text="Dodavatel:").pack(
                        side="right", padx=(8, 0)
                    )
                    box.bind(
                        "<<ComboboxSelected>>",
                        lambda _event: self.load(),
                    )
                    self.load()
                except Exception:
                    pass

            def load(self):
                for item in self.t.get_children():
                    self.t.delete(item)
                self.rows = {}
                query = (
                    (self.q.get() or "").strip().casefold()
                    if hasattr(self, "q")
                    else ""
                )
                supplier_filter = (
                    _text(self.supplier_filter.get())
                    if self.supplier_filter is not None
                    else "Všichni dodavatelé"
                )
                with M.db() as con:
                    has_request = M.has_column(
                        con, "supplier_offers", "request_id"
                    )
                    request_join = (
                        "LEFT JOIN requests r ON r.id=o.request_id"
                        if has_request
                        else ""
                    )
                    request_select = (
                        ",r.item request_item"
                        if has_request
                        else ",'' request_item"
                    )
                    rows = con.execute(
                        f"""SELECT i.id,i.item_key,i.product_code,
                                   i.original_name,i.unit_price,
                                   i.discount_pct,o.offer_date,
                                   coalesce(s.official_name,o.supplier_name,'')
                                       supplier,
                                   a.name action_name {request_select}
                              FROM supplier_offer_items i
                              JOIN supplier_offers o ON o.id=i.offer_id
                              LEFT JOIN companies s
                                ON s.id=o.supplier_company_id
                              LEFT JOIN actions a ON a.id=o.action_id
                              {request_join}
                             ORDER BY supplier COLLATE CZECH,
                                      i.item_key COLLATE CZECH,
                                      o.offer_date DESC,o.id DESC,i.id DESC"""
                    ).fetchall()

                groups = {}
                for row in rows:
                    key = (
                        _text(row["supplier"]).casefold(),
                        _text(
                            row["item_key"] or row["original_name"]
                        ).casefold(),
                    )
                    groups.setdefault(key, []).append(row)

                number = 0
                for _key, history in groups.items():
                    row = history[0]
                    supplier = _text(row["supplier"])
                    if (
                        supplier_filter
                        and supplier_filter != "Všichni dodavatelé"
                        and supplier.casefold()
                        != supplier_filter.casefold()
                    ):
                        continue
                    previous = history[1] if len(history) > 1 else None
                    haystack = " ".join(
                        str(row[key] or "")
                        for key in (
                            "supplier",
                            "product_code",
                            "original_name",
                            "item_key",
                        )
                    ).casefold()
                    if query and query not in haystack:
                        continue
                    last = float(row["unit_price"] or 0)
                    previous_value = (
                        float(previous["unit_price"] or 0)
                        if previous
                        else 0
                    )
                    change = (
                        (last / previous_value - 1) * 100
                        if last and previous_value
                        else None
                    )
                    iid = f"p{number}"
                    number += 1
                    self.rows[iid] = dict(row)
                    self.t.insert(
                        "",
                        "end",
                        iid=iid,
                        values=(
                            supplier,
                            row["product_code"] or "",
                            row["original_name"] or row["item_key"],
                            f"{last:,.2f}",
                            f"{float(row['discount_pct'] or 0):.2f} %",
                            M.fmt_date(row["offer_date"]),
                            f"{previous_value:,.2f}"
                            if previous_value
                            else "",
                            f"{change:+.1f} %"
                            if change is not None
                            else "",
                            row["action_name"] or "",
                            row["request_item"] or "",
                        ),
                    )

        M.ProductPriceBrowser = ProductPriceBrowser
        M.App.open_product_prices = (
            lambda self: ProductPriceBrowser(self)
        )

    # ------------------------------------------------------------------
    # One heading context menu for received offers; row actions stay on rows.
    # ------------------------------------------------------------------
    def reset_tree_columns(tree):
        try:
            defaults = getattr(tree, "_v700_default_widths", {})
            design = getattr(tree, "_turto_design_widths", {})
            for column in tree.cget("columns"):
                if column in defaults:
                    design[column] = int(defaults[column])
                    tree.column(
                        column,
                        width=int(defaults[column]),
                        minwidth=30,
                    )
            tree._turto_design_widths = design
            tree.configure(displaycolumns="#all")
            saver = getattr(M, "save_persistent_tree_layout", None)
            if callable(saver):
                saver(tree)
        except Exception:
            pass

    def remove_columns_buttons(container):
        try:
            for child in list(container.winfo_children()):
                try:
                    if (
                        child.winfo_class().endswith("Button")
                        and _text(child.cget("text")) == "Sloupce…"
                    ):
                        child.destroy()
                        continue
                except Exception:
                    pass
                remove_columns_buttons(child)
        except Exception:
            pass

    def install_offer_context(app):
        tree = getattr(app, "offer_tree", None)
        if tree is None or not _widget_exists(tree):
            return
        try:
            tree._turto_configurable_columns = True
            installer = getattr(M, "install_persistent_tree_layout", None)
            if callable(installer):
                installer(tree, force=True)
        except Exception:
            pass

        header_menu = M.tk.Menu(tree, tearoff=False)
        header_menu.add_command(
            label="Nastavit zobrazené sloupce…",
            command=lambda: getattr(
                M, "open_tree_columns_dialog", lambda _tree: None
            )(tree),
        )
        header_menu.add_command(
            label="Obnovit výchozí sloupce",
            command=lambda: reset_tree_columns(tree),
        )

        row_menu = M.tk.Menu(tree, tearoff=False)
        row_menu.add_command(
            label="Otevřít detail", command=app.open_offer_detail
        )
        row_menu.add_command(
            label="Překlopit do Vydané nabídky",
            command=lambda: commercial_workspace._offer_to_issued_offer(
                M, app
            ),
        )
        row_menu.add_command(
            label="Označit jako Ceník…",
            command=lambda: commercial_workspace._offer_to_price_list(
                M, app
            ),
        )
        row_menu.add_separator()
        row_menu.add_command(
            label="Archivovat vybrané",
            command=lambda: commercial_workspace._archive_offers(
                M, app, False
            ),
        )
        row_menu.add_command(
            label="Obnovit vybrané",
            command=lambda: commercial_workspace._archive_offers(
                M, app, True
            ),
        )
        def delete_selected_offer():
            callback = getattr(app, "delete_offer", None)
            if not callable(callback):
                return None
            runner = getattr(
                commercial_workspace, "_run_after_invalidation", None
            )
            if callable(runner):
                return runner(app, callback, offers=True)
            result = callback()
            try:
                app.refresh_offers()
            except Exception:
                pass
            return result

        row_menu.add_command(
            label="Smazat pouze z DB",
            command=delete_selected_offer,
        )

        def popup(event):
            region = tree.identify_region(event.x, event.y)
            menu = None
            if region in {"heading", "separator"}:
                menu = header_menu
            else:
                row = tree.identify_row(event.y)
                if not row:
                    return "break"
                if row not in tree.selection():
                    tree.selection_set(row)
                    try:
                        commercial_workspace.update_offer_selection(M, app)
                    except Exception:
                        pass
                menu = row_menu
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
            return "break"

        tree.bind("<Button-3>", popup, add=False)
        tree._v740_header_menu = header_menu
        tree._v740_row_menu = row_menu
        tree._v740_context_owner = True

    previous_build_offers = getattr(M.App, "build_offers", None)
    if callable(previous_build_offers):
        def build_offers(self, *args, **kwargs):
            result = previous_build_offers(self, *args, **kwargs)
            page = getattr(self, "tabs", {}).get("offers")
            if page is not None:
                remove_columns_buttons(page)
            install_offer_context(self)
            return result

        M.App.build_offers = build_offers

    # ------------------------------------------------------------------
    # Help is a top-right action next to Settings, not a main navigation tab.
    # ------------------------------------------------------------------
    previous_build = getattr(M.App, "build", None)
    if callable(previous_build):
        def build(self, *args, **kwargs):
            result = previous_build(self, *args, **kwargs)
            old_help = getattr(self, "nav", {}).pop("help", None)
            if old_help is not None:
                try:
                    old_help.destroy()
                except Exception:
                    try:
                        old_help.pack_forget()
                    except Exception:
                        pass
            if not _widget_exists(getattr(self, "help_button", None)):
                try:
                    top = self.user_button.master
                    self.help_button = M.ttk.Button(
                        top,
                        text="?  Nápověda",
                        style="TopAction.TButton",
                        command=lambda: self.show_page("help"),
                    )
                    self.help_button.grid(
                        row=0, column=6, padx=(6, 0)
                    )
                except Exception:
                    pass
            return result

        M.App.build = build

    # ------------------------------------------------------------------
    # Remove redundant toolbar buttons after all delayed legacy installers.
    # ------------------------------------------------------------------
    previous_app_init = M.App.__init__

    def app_init(self, *args, **kwargs):
        result = previous_app_init(self, *args, **kwargs)

        def tidy():
            try:
                mivo = getattr(self, "tabs", {}).get("mivo")
                offers = getattr(self, "tabs", {}).get("offers")
                if mivo is not None:
                    remove_columns_buttons(mivo)
                if offers is not None:
                    remove_columns_buttons(offers)
                button = getattr(
                    self, "_v710_mivo_columns_button", None
                )
                if _widget_exists(button):
                    button.destroy()
                self._v710_mivo_columns_button = None
                install_offer_context(self)
            except Exception:
                pass

        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, tidy)
            except Exception:
                pass
        return result

    M.App.__init__ = app_init
    M._turto_v740_offer_defaults_installed = True


__all__ = ["apply"]
