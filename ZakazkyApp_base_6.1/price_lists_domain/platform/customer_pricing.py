"""Manual catalogue products and customer/Action-specific discount policy.

Imported Ceníky remain the authoritative purchase-price history. A manual price
is a fallback only when no valid imported price exists. Discounts are resolved
in the order line override -> Action -> company -> product/subgroup/group.
Issued-document lines keep their own price snapshot.
"""
from __future__ import annotations

import copy
import functools
import inspect
from datetime import date


UNSET = object()


def _columns(con, table):
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return set()


def _add_column(con, table, declaration):
    name = declaration.split()[0].strip('"[]`')
    if name not in _columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {declaration}")


def _number(value, default=0.0):
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _optional_number(value):
    if value in (None, ""):
        return None
    return float(str(value).strip().replace(" ", "").replace(",", "."))


def _discount(value):
    return max(0.0, min(100.0, _number(value)))


def _root(widget):
    current = widget
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parent = getattr(current, "master", None)
        if parent is None:
            break
        current = parent
    return current or widget


def ensure_schema(M):
    """Add only new columns/tables; existing catalogue and document data stay intact."""
    with M.db() as con:
        for declaration in (
            "manual_product INTEGER NOT NULL DEFAULT 0",
            "description TEXT DEFAULT ''",
            "manual_purchase_unit_price REAL",
            "manual_currency TEXT DEFAULT 'CZK'",
            "manual_unit TEXT DEFAULT 'ks'",
            "manual_price_note TEXT DEFAULT ''",
            "default_margin_pct REAL",
            "default_discount_pct REAL",
            "manual_price_updated_at TEXT DEFAULT ''",
        ):
            _add_column(con, "catalog_products", declaration)
        tables = {str(row[0]) for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "business_document_items" in tables:
            _add_column(con, "business_document_items", "discount_source TEXT DEFAULT ''")
            _add_column(con, "business_document_items", "discount_rule_id INTEGER")
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS customer_product_discounts(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              product_id INTEGER NOT NULL,
              company_id INTEGER NOT NULL,
              action_id INTEGER,
              discount_pct REAL NOT NULL DEFAULT 0,
              note TEXT DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(product_id) REFERENCES catalog_products(id) ON DELETE CASCADE,
              FOREIGN KEY(company_id) REFERENCES companies(id) ON DELETE RESTRICT,
              FOREIGN KEY(action_id) REFERENCES actions(id) ON DELETE RESTRICT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_product_discount_company
              ON customer_product_discounts(product_id,company_id)
              WHERE action_id IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_product_discount_action
              ON customer_product_discounts(product_id,company_id,action_id)
              WHERE action_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_customer_product_discount_lookup
              ON customer_product_discounts(product_id,company_id,action_id,active,id);
            CREATE INDEX IF NOT EXISTS idx_catalog_products_manual
              ON catalog_products(manual_product,active,category_id,subgroup_id,id);
            """
        )


def _next_code(M):
    with M.db() as con:
        values = [str(row[0] or "") for row in con.execute(
            "SELECT internal_code FROM catalog_products WHERE upper(trim(internal_code)) LIKE 'RUC-%'"
        )]
    highest = 0
    for value in values:
        try:
            highest = max(highest, int(value.rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"RUC-{highest + 1:05d}"


def save_product(M, data, product_id=None):
    ensure_schema(M)
    name = str(data.get("internal_name") or "").strip()
    if not name:
        raise ValueError("Interní označení výrobku je povinné.")
    code = str(data.get("internal_code") or "").strip() or (_next_code(M) if not product_id else "")
    manufacturer = str(data.get("manufacturer_name") or "").strip()
    description = str(data.get("description") or "").strip()
    purchase = _optional_number(data.get("manual_purchase_unit_price"))
    margin = _optional_number(data.get("default_margin_pct"))
    discount = _optional_number(data.get("default_discount_pct"))
    if purchase is not None and purchase < 0:
        raise ValueError("Nákupní cena nesmí být záporná.")
    if margin is not None and margin <= -100:
        raise ValueError("Marže musí být větší než −100 %.")
    if discount is not None and not 0 <= discount <= 100:
        raise ValueError("Standardní sleva musí být v rozsahu 0 až 100 %.")
    currency = str(data.get("manual_currency") or "CZK").strip().upper() or "CZK"
    unit = str(data.get("manual_unit") or "ks").strip() or "ks"
    note = str(data.get("manual_price_note") or "").strip()
    category_id = int(data["category_id"]) if data.get("category_id") else None
    subgroup_id = int(data["subgroup_id"]) if data.get("subgroup_id") else None
    active = 1 if data.get("active", True) else 0
    with M.db() as con:
        if subgroup_id:
            row = con.execute("SELECT category_id FROM product_subgroups WHERE id=?", (subgroup_id,)).fetchone()
            if not row:
                raise ValueError("Vybraná podskupina už neexistuje.")
            category_id = int(row["category_id"])
        if code and con.execute(
            """SELECT id FROM catalog_products
               WHERE lower(trim(internal_code))=lower(trim(?)) AND id<>? LIMIT 1""",
            (code, int(product_id or 0)),
        ).fetchone():
            raise ValueError("Stejný interní kód už používá jiný výrobek.")
        values = (
            manufacturer, code, name, description, category_id, subgroup_id, active,
            purchase, currency, unit, note, margin, discount,
        )
        if product_id:
            product_id = int(product_id)
            if not con.execute("SELECT id FROM catalog_products WHERE id=?", (product_id,)).fetchone():
                raise ValueError("Upravovaný výrobek už neexistuje.")
            con.execute(
                """UPDATE catalog_products SET manufacturer_name=?,internal_code=?,internal_name=?,
                     description=?,category_id=?,subgroup_id=?,active=?,manual_purchase_unit_price=?,
                     manual_currency=?,manual_unit=?,manual_price_note=?,default_margin_pct=?,
                     default_discount_pct=?,manual_price_updated_at=CURRENT_TIMESTAMP,
                     updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                values + (product_id,),
            )
        else:
            product_id = int(con.execute(
                """INSERT INTO catalog_products(
                     manufacturer_name,internal_code,internal_name,description,category_id,subgroup_id,
                     active,manual_product,manual_purchase_unit_price,manual_currency,manual_unit,
                     manual_price_note,default_margin_pct,default_discount_pct,manual_price_updated_at
                   ) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                values,
            ).lastrowid)
        source_key = f"manual:{product_id}"
        con.execute(
            """INSERT INTO catalog_product_sources(
                 product_id,supplier_company_id,supplier_name,supplier_name_norm,source_key,
                 product_identity,supplier_product_code,source_name,source_kind,last_seen_at
               ) VALUES(?,NULL,?,?,?,?,?,?,'manual',CURRENT_TIMESTAMP)
               ON CONFLICT(source_key) DO UPDATE SET product_id=excluded.product_id,
                 supplier_name=excluded.supplier_name,supplier_name_norm=excluded.supplier_name_norm,
                 supplier_product_code=excluded.supplier_product_code,source_name=excluded.source_name,
                 source_kind='manual',last_seen_at=CURRENT_TIMESTAMP""",
            (product_id, manufacturer, manufacturer.casefold(), source_key, source_key, code, name),
        )
    return product_id


def product_pricing(M, product_id, as_of=None):
    ensure_schema(M)
    day = str(as_of or date.today().isoformat())
    with M.db() as con:
        row = con.execute(
            """SELECT cp.*,coalesce(c.name,'') category_name,coalesce(s.name,'') subgroup_name,
                      coalesce(s.default_margin_pct,c.default_margin_pct,0) inherited_margin,
                      coalesce(s.default_discount_pct,c.default_discount_pct,0) inherited_discount,
                      coalesce(c.show_recommended_price,1) show_recommended_price,
                      (SELECT i.normalized_unit_price FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1 AND coalesce(p.archived,0)=0
                          AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_price,
                      (SELECT coalesce(i.currency,'CZK') FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1 AND coalesce(p.archived,0)=0
                          AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_currency,
                      (SELECT coalesce(i.unit,'') FROM price_list_items i JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1 AND coalesce(p.archived,0)=0
                          AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_unit
                 FROM catalog_products cp
                 LEFT JOIN product_categories c ON c.id=cp.category_id
                 LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id WHERE cp.id=?""",
            (day, day, day, day, day, day, int(product_id)),
        ).fetchone()
    if not row:
        raise ValueError("Katalogový výrobek už neexistuje.")
    result = dict(row)
    imported = result.get("imported_price")
    manual = result.get("manual_purchase_unit_price")
    purchase = _number(imported if imported is not None else manual)
    margin = _number(result.get("default_margin_pct") if result.get("default_margin_pct") is not None else result.get("inherited_margin"))
    standard_discount = _discount(
        result.get("default_discount_pct") if result.get("default_discount_pct") is not None else result.get("inherited_discount")
    )
    if result.get("default_discount_pct") is not None:
        standard_source = "Standard výrobku"
    elif result.get("subgroup_id"):
        standard_source = "Standard podskupiny"
    elif result.get("category_id"):
        standard_source = "Standard skupiny"
    else:
        standard_source = "Standard"
    recommended = purchase * (1 + margin / 100)
    result.update(
        purchase_unit_price=purchase,
        purchase_source="Ceník" if imported is not None else ("Ruční cena" if manual is not None else "Bez ceny"),
        currency=str(result.get("imported_currency") or result.get("manual_currency") or "CZK"),
        unit=str(result.get("imported_unit") or result.get("manual_unit") or "ks"),
        margin_pct=margin,standard_discount_pct=standard_discount,
        discount_pct=standard_discount,discount_source=standard_source,discount_rule_id=None,
        standard_discount_source=standard_source,recommended_unit_price=recommended,
        final_unit_price=recommended * (1 - standard_discount / 100),
    )
    return result


def resolve(M, product_id, company_id=None, action_id=None, as_of=None):
    result = product_pricing(M, product_id, as_of)
    company_id = int(company_id) if company_id else None
    action_id = int(action_id) if action_id else None
    rule = None
    source = ""
    if company_id:
        with M.db() as con:
            if action_id:
                rule = con.execute(
                    """SELECT id,discount_pct,note FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id=? AND active=1 ORDER BY id DESC LIMIT 1""",
                    (int(product_id), company_id, action_id),
                ).fetchone()
                if rule:
                    source = "Výjimka pro Akci"
            if not rule:
                rule = con.execute(
                    """SELECT id,discount_pct,note FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id IS NULL AND active=1 ORDER BY id DESC LIMIT 1""",
                    (int(product_id), company_id),
                ).fetchone()
                if rule:
                    source = "Sleva společnosti"
    if rule:
        result["discount_pct"] = _discount(rule["discount_pct"])
        result["discount_source"] = source
        result["discount_rule_id"] = int(rule["id"])
        result["discount_note"] = str(rule["note"] or "")
        result["final_unit_price"] = result["recommended_unit_price"] * (1 - result["discount_pct"] / 100)
    return result


def save_rule(M, product_id, company_id, discount_pct, action_id=None, note=""):
    ensure_schema(M)
    product_id, company_id = int(product_id), int(company_id)
    action_id = int(action_id) if action_id else None
    value = _optional_number(discount_pct)
    if value is None or not 0 <= value <= 100:
        raise ValueError("Sleva musí být v rozsahu 0 až 100 %.")
    with M.db() as con:
        if action_id:
            old = con.execute(
                "SELECT id FROM customer_product_discounts WHERE product_id=? AND company_id=? AND action_id=?",
                (product_id, company_id, action_id),
            ).fetchone()
        else:
            old = con.execute(
                "SELECT id FROM customer_product_discounts WHERE product_id=? AND company_id=? AND action_id IS NULL",
                (product_id, company_id),
            ).fetchone()
        if old:
            rule_id = int(old["id"])
            con.execute(
                "UPDATE customer_product_discounts SET discount_pct=?,note=?,active=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (value, str(note or "").strip(), rule_id),
            )
        else:
            rule_id = int(con.execute(
                """INSERT INTO customer_product_discounts(product_id,company_id,action_id,discount_pct,note,active)
                   VALUES(?,?,?,?,?,1)""",
                (product_id, company_id, action_id, value, str(note or "").strip()),
            ).lastrowid)
    return rule_id


def list_rules(M, product_id):
    ensure_schema(M)
    with M.db() as con:
        return con.execute(
            """SELECT r.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),'') company_name,
                      coalesce(a.name,'') action_name
                 FROM customer_product_discounts r JOIN companies c ON c.id=r.company_id
                 LEFT JOIN actions a ON a.id=r.action_id WHERE r.product_id=?
                ORDER BY r.active DESC,company_name COLLATE CZECH,
                         CASE WHEN r.action_id IS NULL THEN 0 ELSE 1 END,action_name COLLATE CZECH,r.id""",
            (int(product_id),),
        ).fetchall()


def delete_rule(M, rule_id):
    with M.db() as con:
        con.execute("DELETE FROM customer_product_discounts WHERE id=?", (int(rule_id),))


def price_payload(M, payload, force=False):
    """Resolve defaults on a copy; explicit line discounts remain untouched."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), (list, tuple)):
        return payload
    result = copy.deepcopy(payload)
    company_id = result.get("company_id") or result.get("customer_company_id") or result.get("buyer_company_id")
    action_id = result.get("action_id")
    as_of = result.get("issue_date") or date.today().isoformat()
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        product_id = item.get("catalog_product_id") or item.get("product_id")
        if not product_id:
            continue
        try:
            pricing = resolve(M, product_id, company_id, action_id, as_of)
        except Exception:
            continue
        source = str(item.get("discount_source") or "").casefold()
        manual = bool(item.get("discount_manual") or item.get("manual_discount") or item.get("pricing_locked") or source in {"ruční", "rucni", "manual"})
        current = item.get("discount_pct", UNSET)
        replaceable = (
            force or current is UNSET or current in (None, "")
            or abs(_number(current) - _number(pricing["standard_discount_pct"])) < 1e-8
            or source in {"", "standard", "standard výrobku", "standard podskupiny", "standard skupiny", "sleva společnosti", "výjimka pro akci"}
        )
        if replaceable and not manual:
            item["discount_pct"] = pricing["discount_pct"]
            item["discount_source"] = pricing["discount_source"]
            item["discount_rule_id"] = pricing.get("discount_rule_id")
        if _number(item.get("purchase_unit_price")) <= 0 and pricing["purchase_unit_price"] > 0:
            item["purchase_unit_price"] = pricing["purchase_unit_price"]
        if item.get("margin_pct") in (None, ""):
            item["margin_pct"] = pricing["margin_pct"]
        item.setdefault("internal_code_snapshot", pricing.get("internal_code") or "")
        item.setdefault("internal_name_snapshot", pricing.get("internal_name") or "")
        item.setdefault("product_code", pricing.get("internal_code") or "")
        item.setdefault("name", pricing.get("internal_name") or "")
        if not item.get("unit"):
            item["unit"] = pricing.get("unit") or "ks"
        purchase = _number(item.get("purchase_unit_price"), pricing["purchase_unit_price"])
        margin = _number(item.get("margin_pct"), pricing["margin_pct"])
        line_discount = _discount(item.get("discount_pct", pricing["discount_pct"]))
        recommended = purchase * (1 + margin / 100)
        final = recommended * (1 - line_discount / 100)
        item["recommended_unit_price"] = recommended
        item["unit_price"] = final
        item["total_price"] = _number(item.get("quantity"), 1) * final
        item.setdefault("show_recommended_price", pricing.get("show_recommended_price", 1))
    return result


def _find_payload(value):
    if isinstance(value, dict):
        if isinstance(value.get("items"), (list, tuple)):
            return value
        for nested in value.values():
            found = _find_payload(nested)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_payload(nested)
            if found is not None:
                return found
    return None


def _replace(value, old, new):
    if value is old:
        return new
    if isinstance(value, list):
        return [_replace(item, old, new) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace(item, old, new) for item in value)
    if isinstance(value, dict):
        return {key: _replace(item, old, new) for key, item in value.items()}
    return value


def _patch_document_service(M):
    try:
        from ..issued_offers import service
    except Exception:
        return
    if getattr(service, "_turto_customer_pricing_v6340", False):
        return
    preferred = {"save_document", "save_offer", "create_document", "update_document", "save_business_document", "upsert_document"}
    for name, function in list(vars(service).items()):
        if not inspect.isfunction(function) or name.startswith("_"):
            continue
        try:
            source = inspect.getsource(function).casefold()
        except Exception:
            source = ""
        persistence = name in preferred or (
            "business_document_items" in source and "items" in source
            and any(token in source for token in ("insert into", "update business_documents", "executemany"))
        )
        if not persistence or getattr(function, "_turto_customer_pricing_wrapper", False):
            continue

        @functools.wraps(function)
        def wrapped(*args, __function=function, **kwargs):
            payload = _find_payload(args) or _find_payload(kwargs)
            if payload is None:
                return __function(*args, **kwargs)
            priced = price_payload(M, payload)
            return __function(
                *tuple(_replace(value, payload, priced) for value in args),
                **{key: _replace(value, payload, priced) for key, value in kwargs.items()},
            )

        wrapped._turto_customer_pricing_wrapper = True
        setattr(service, name, wrapped)
    service.resolve_customer_product_pricing = lambda product_id, company_id=None, action_id=None, as_of=None: resolve(M, product_id, company_id, action_id, as_of)
    service.apply_customer_pricing = lambda payload, force=False: price_payload(M, payload, force)
    service._turto_customer_pricing_v6340 = True


def _manual_picker_rows(M, company_id=None, action_id=None):
    with M.db() as con:
        ids = [int(row[0]) for row in con.execute(
            "SELECT id FROM catalog_products WHERE active=1 AND manual_product=1 ORDER BY id"
        )]
    rows = []
    for product_id in ids:
        data = resolve(M, product_id, company_id, action_id)
        rows.append({
            "id": product_id,"product_id": product_id,"catalog_product_id": product_id,
            "internal_code": data.get("internal_code") or "","product_code": data.get("internal_code") or "",
            "code": data.get("internal_code") or "","item_key": data.get("internal_code") or data.get("internal_name") or "",
            "internal_name": data.get("internal_name") or "","name": data.get("internal_name") or "",
            "description": data.get("description") or "","manufacturer_name": data.get("manufacturer_name") or "",
            "category_id": data.get("category_id"),"subgroup_id": data.get("subgroup_id"),
            "category": data.get("category_name") or "","subgroup": data.get("subgroup_name") or "",
            "purchase_unit_price": data["purchase_unit_price"],"normalized_unit_price": data["purchase_unit_price"],
            "current_price": data["purchase_unit_price"],"margin_pct": data["margin_pct"],
            "discount_pct": data["discount_pct"],"discount_source": data["discount_source"],
            "recommended_unit_price": data["recommended_unit_price"],"unit_price": data["final_unit_price"],
            "final_unit_price": data["final_unit_price"],"currency": data["currency"],"unit": data["unit"],
            "show_recommended_price": data.get("show_recommended_price", 1),"manual_product": 1,
        })
    return rows


def _append_manual(M, result, company_id=None, action_id=None):
    manual = _manual_picker_rows(M, company_id, action_id)
    if not manual:
        return result

    def merge(rows):
        if not isinstance(rows, list):
            return rows, 0
        ids = set()
        for row in rows:
            try:
                keys = set(row.keys())
                value = row["catalog_product_id"] if "catalog_product_id" in keys else row["product_id"] if "product_id" in keys else row["id"]
                ids.add(int(value))
            except Exception:
                pass
        extra = [dict(row) for row in manual if row["catalog_product_id"] not in ids]
        return rows + extra, len(extra)

    if isinstance(result, list):
        return merge(result)[0]
    if isinstance(result, tuple):
        values = list(result)
        for index, value in enumerate(values):
            if isinstance(value, list):
                values[index], added = merge(value)
                if added and index > 0 and isinstance(values[0], int):
                    values[0] += added
                return tuple(values)
    return result


def _patch_pickers(M):
    try:
        from ..issued_offers import service, editor
        modules = (service, editor)
    except Exception:
        modules = ()
    for module in modules:
        if getattr(module, "_turto_manual_picker_v6340", False):
            continue
        for name, function in list(vars(module).items()):
            if not inspect.isfunction(function) or name.startswith("_"):
                continue
            if not any(token in name.casefold() for token in ("catalog", "product", "picker", "search")):
                continue
            try:
                source = inspect.getsource(function).casefold()
            except Exception:
                source = ""
            if "catalog_products" not in source and "price_list_items" not in source:
                continue
            try:
                signature = inspect.signature(function)
            except Exception:
                signature = None

            @functools.wraps(function)
            def wrapped(*args, __function=function, __signature=signature, **kwargs):
                result = __function(*args, **kwargs)
                company_id = kwargs.get("company_id") or kwargs.get("customer_company_id")
                action_id = kwargs.get("action_id")
                if __signature:
                    try:
                        bound = __signature.bind_partial(*args, **kwargs).arguments
                        company_id = company_id or bound.get("company_id") or bound.get("customer_company_id")
                        action_id = action_id or bound.get("action_id")
                    except Exception:
                        pass
                return _append_manual(M, result, company_id, action_id)

            setattr(module, name, wrapped)
        module._turto_manual_picker_v6340 = True


def _patch_catalog_rows(M):
    try:
        from . import product_workspace
    except Exception:
        return
    if getattr(product_workspace, "_turto_customer_pricing_rows_v6340", False):
        return
    original_rows = product_workspace._catalog_rows

    @functools.wraps(original_rows)
    def rows(module, *args, **kwargs):
        total, result, summary = original_rows(module, *args, **kwargs)
        ids = [int(row["id"]) for row in result]
        if not ids:
            return total, result, summary
        marks = ",".join("?" for _ in ids)
        with module.db() as con:
            supplements = {int(row["id"]): dict(row) for row in con.execute(
                f"""SELECT cp.id,cp.manual_product,cp.manual_purchase_unit_price,cp.manual_currency,cp.manual_unit,
                           cp.default_margin_pct product_margin,cp.default_discount_pct product_discount,
                           coalesce(s.default_margin_pct,c.default_margin_pct,0) inherited_margin,
                           coalesce(s.default_discount_pct,c.default_discount_pct,0) inherited_discount
                      FROM catalog_products cp LEFT JOIN product_categories c ON c.id=cp.category_id
                      LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id WHERE cp.id IN ({marks})""",
                ids,
            )}
        patched = []
        for row in result:
            value = dict(row)
            supplement = supplements.get(int(row["id"]), {})
            if value.get("current_price") is None and supplement.get("manual_purchase_unit_price") is not None:
                value["current_price"] = supplement["manual_purchase_unit_price"]
                value["current_currency"] = supplement.get("manual_currency") or "CZK"
            value["margin_pct"] = _number(
                supplement.get("product_margin") if supplement.get("product_margin") is not None else supplement.get("inherited_margin")
            )
            value["discount_pct"] = _discount(
                supplement.get("product_discount") if supplement.get("product_discount") is not None else supplement.get("inherited_discount")
            )
            value["manual_product"] = supplement.get("manual_product", 0)
            value["manual_unit"] = supplement.get("manual_unit") or "ks"
            patched.append(value)
        return total, patched, summary

    product_workspace._catalog_rows = rows
    product_workspace._turto_customer_pricing_rows_v6340 = True


def _options(M):
    with M.db() as con:
        groups = con.execute("SELECT id,name FROM product_categories WHERE active=1 ORDER BY sort_order,name COLLATE CZECH").fetchall()
        subgroups = con.execute(
            """SELECT s.id,s.category_id,s.name FROM product_subgroups s JOIN product_categories c ON c.id=s.category_id
               WHERE s.active=1 AND c.active=1 ORDER BY c.sort_order,s.sort_order,s.name COLLATE CZECH"""
        ).fetchall()
    return groups, subgroups


def product_editor(M, app, parent, product_id=None, on_saved=None):
    ensure_schema(M)
    current = None
    if product_id:
        with M.db() as con:
            current = con.execute("SELECT * FROM catalog_products WHERE id=?", (int(product_id),)).fetchone()
    groups, subgroups = _options(M)
    group_labels = ["Nezařazeno"] + [str(row["name"]) for row in groups]
    group_ids = {"Nezařazeno": None, **{str(row["name"]): int(row["id"]) for row in groups}}
    subgroup_rows = {}
    for row in subgroups:
        subgroup_rows.setdefault(int(row["category_id"]), []).append(row)
    category_id = int(current["category_id"]) if current and current["category_id"] else None
    subgroup_id = int(current["subgroup_id"]) if current and current["subgroup_id"] else None
    group_name = next((str(row["name"]) for row in groups if int(row["id"]) == category_id), "Nezařazeno")

    dialog = M.tk.Toplevel(parent)
    dialog.title("Upravit výrobek" if current else "Nový ruční výrobek")
    dialog.transient(parent); dialog.grab_set(); M.enable_dialog_maximize(dialog, 900, 720)
    frame = M.ttk.Frame(dialog, padding=18); frame.pack(fill="both", expand=True); frame.columnconfigure(1, weight=1)
    variables = {
        "internal_code": M.tk.StringVar(value=str(current["internal_code"] or "") if current else _next_code(M)),
        "internal_name": M.tk.StringVar(value=str(current["internal_name"] or "") if current else ""),
        "manufacturer_name": M.tk.StringVar(value=str(current["manufacturer_name"] or "") if current else ""),
        "manual_purchase_unit_price": M.tk.StringVar(value=str(current["manual_purchase_unit_price"]).replace(".", ",") if current and current["manual_purchase_unit_price"] is not None else ""),
        "manual_currency": M.tk.StringVar(value=str(current["manual_currency"] or "CZK") if current else "CZK"),
        "manual_unit": M.tk.StringVar(value=str(current["manual_unit"] or "ks") if current else "ks"),
        "default_margin_pct": M.tk.StringVar(value=str(current["default_margin_pct"]).replace(".", ",") if current and current["default_margin_pct"] is not None else ""),
        "default_discount_pct": M.tk.StringVar(value=str(current["default_discount_pct"]).replace(".", ",") if current and current["default_discount_pct"] is not None else ""),
        "active": M.tk.BooleanVar(value=bool(current["active"]) if current else True),
    }
    group_var = M.tk.StringVar(value=group_name); subgroup_var = M.tk.StringVar(value="Bez podskupiny")
    description = M.tk.Text(frame, height=4, wrap="word"); note = M.tk.Text(frame, height=3, wrap="word")
    if current:
        description.insert("1.0", str(current["description"] or "")); note.insert("1.0", str(current["manual_price_note"] or ""))
    M.ttk.Label(frame, text="Katalogový výrobek", font=("Calibri", 16, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
    M.ttk.Label(frame, text="Ruční cena se použije pouze bez platné ceny z Ceníku.", style="PageSubtitle.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))
    row_index = 2

    def add_entry(label, key):
        nonlocal row_index
        M.ttk.Label(frame, text=label).grid(row=row_index, column=0, sticky="w", padx=(0, 10), pady=5)
        widget = M.ttk.Entry(frame, textvariable=variables[key]); widget.grid(row=row_index, column=1, sticky="ew", pady=5)
        row_index += 1
        return widget

    add_entry("Interní kód", "internal_code"); name_entry = add_entry("Interní označení *", "internal_name"); add_entry("Výrobce", "manufacturer_name")
    M.ttk.Label(frame, text="Skupina").grid(row=row_index, column=0, sticky="w", pady=5)
    group_combo = M.safe_combobox(frame, textvariable=group_var, values=group_labels, state="readonly"); group_combo.grid(row=row_index, column=1, sticky="ew", pady=5); row_index += 1
    M.ttk.Label(frame, text="Podskupina").grid(row=row_index, column=0, sticky="w", pady=5)
    subgroup_combo = M.safe_combobox(frame, textvariable=subgroup_var, values=["Bez podskupiny"], state="readonly"); subgroup_combo.grid(row=row_index, column=1, sticky="ew", pady=5); row_index += 1

    def refresh_subgroups(*_):
        gid = group_ids.get(group_var.get()); values = subgroup_rows.get(gid, []) if gid else []
        labels = ["Bez podskupiny"] + [str(row["name"]) for row in values]; subgroup_combo.configure(values=labels)
        selected = next((str(row["name"]) for row in values if subgroup_id and int(row["id"]) == subgroup_id), None)
        if selected:
            subgroup_var.set(selected)
        elif subgroup_var.get() not in labels:
            subgroup_var.set(labels[0])

    group_combo.bind("<<ComboboxSelected>>", refresh_subgroups, add="+"); refresh_subgroups()
    price = M.ttk.LabelFrame(frame, text="Cena a standard produktu", padding=10); price.grid(row=row_index, column=0, columnspan=2, sticky="ew", pady=(10, 6)); row_index += 1
    labels = (("Nákupní cena", "manual_purchase_unit_price"), ("Měna", "manual_currency"), ("MJ", "manual_unit"), ("Marže [%]", "default_margin_pct"), ("Standardní sleva [%]", "default_discount_pct"))
    for idx, (label, key) in enumerate(labels):
        M.ttk.Label(price, text=label).grid(row=idx // 3 * 2, column=(idx % 3) * 2, sticky="w", padx=(0, 5), pady=4)
        if key == "manual_currency":
            widget = M.safe_combobox(price, textvariable=variables[key], values=["CZK", "EUR", "PLN"], width=9)
        else:
            widget = M.ttk.Entry(price, textvariable=variables[key], width=14)
        widget.grid(row=idx // 3 * 2 + 1, column=(idx % 3) * 2, sticky="ew", padx=(0, 12), pady=(0, 6))
    M.ttk.Label(frame, text="Popis").grid(row=row_index, column=0, sticky="nw", pady=5); description.grid(row=row_index, column=1, sticky="nsew", pady=5); row_index += 1
    M.ttk.Label(frame, text="Poznámka k ruční ceně").grid(row=row_index, column=0, sticky="nw", pady=5); note.grid(row=row_index, column=1, sticky="nsew", pady=5); row_index += 1
    M.ttk.Checkbutton(frame, text="Aktivní", variable=variables["active"]).grid(row=row_index, column=1, sticky="w", pady=5); row_index += 1

    def commit():
        gid = group_ids.get(group_var.get()); choices = subgroup_rows.get(gid, []) if gid else []
        sid = next((int(row["id"]) for row in choices if str(row["name"]) == subgroup_var.get()), None)
        data = {key: var.get() for key, var in variables.items() if key != "active"}
        data.update(category_id=gid, subgroup_id=sid, active=variables["active"].get(), description=description.get("1.0", "end").strip(), manual_price_note=note.get("1.0", "end").strip())
        try:
            saved = save_product(M, data, product_id)
        except Exception as exc:
            return M.messagebox.showerror("Katalog produktů", str(exc), parent=dialog)
        dialog.destroy()
        if callable(on_saved):
            on_saved(saved)

    buttons = M.ttk.Frame(frame); buttons.grid(row=row_index, column=0, columnspan=2, sticky="e", pady=(12, 0))
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="left", padx=(0, 6)); M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=commit).pack(side="left")
    name_entry.focus_set(); return dialog


def _company_action_options(M):
    with M.db() as con:
        companies = con.execute(
            """SELECT id,coalesce(nullif(trim(official_name),''),nullif(trim(short_name),''),'') name
               FROM companies WHERE coalesce(active,1)=1 ORDER BY name COLLATE CZECH,id"""
        ).fetchall()
        action_cols = _columns(con, "actions"); where = "WHERE coalesce(archived,0)=0" if "archived" in action_cols else ""
        actions = con.execute(f"SELECT id,coalesce(name,'') name FROM actions {where} ORDER BY name COLLATE CZECH,id DESC").fetchall()
    company_labels = [f"{row['name']}  [#{row['id']}]" for row in companies]
    action_labels = ["— výchozí pro společnost —"] + [f"{row['name']}  [#{row['id']}]" for row in actions]
    return company_labels, {label: int(row["id"]) for label, row in zip(company_labels, companies)}, action_labels, {action_labels[0]: None, **{label: int(row["id"]) for label, row in zip(action_labels[1:], actions)}}


def rules_dialog(M, app, parent, product_id, on_changed=None):
    product = product_pricing(M, product_id)
    dialog = M.tk.Toplevel(parent); dialog.title("Slevy společností a Akcí"); dialog.transient(parent); dialog.grab_set(); M.enable_dialog_maximize(dialog, 1120, 680)
    outer = M.ttk.Frame(dialog, padding=16); outer.pack(fill="both", expand=True); outer.columnconfigure(0, weight=1); outer.rowconfigure(2, weight=1)
    M.ttk.Label(outer, text=product.get("internal_name") or product.get("internal_code"), font=("Calibri", 16, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(outer, text=f"Pořadí: ruční řádek → Akce → společnost → {product['standard_discount_source']} ({product['standard_discount_pct']:g} %).", style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 10))
    columns = ("Společnost", "Akce / rozsah", "Sleva", "Poznámka"); tree = M.ttk.Treeview(outer, columns=columns, show="headings", selectmode="browse")
    for column, width in zip(columns, (300, 320, 90, 360)):
        tree.heading(column, text=column); tree.column(column, width=width, anchor="w")
    tree.grid(row=2, column=0, sticky="nsew"); scroll = M.ttk.Scrollbar(outer, orient="vertical", command=tree.yview); scroll.grid(row=2, column=1, sticky="ns"); tree.configure(yscrollcommand=scroll.set)
    mapping = {}

    def refresh():
        children = tree.get_children()
        if children:
            tree.delete(*children)
        mapping.clear()
        for row in list_rules(M, product_id):
            iid = f"r{row['id']}"; mapping[iid] = dict(row)
            tree.insert("", "end", iid=iid, values=(row["company_name"], row["action_name"] or "Výchozí pro společnost", f"{_number(row['discount_pct']):g} %", row["note"] or ""))

    def selected():
        selection = tree.selection(); return mapping.get(selection[0]) if selection else None

    def edit(existing=None):
        company_labels, company_ids, action_labels, action_ids = _company_action_options(M)
        if not company_labels:
            return M.messagebox.showwarning("Slevy", "Nejprve založte společnost.", parent=dialog)
        form = M.tk.Toplevel(dialog); form.title("Pravidlo slevy"); form.transient(dialog); form.grab_set()
        body = M.ttk.Frame(form, padding=16); body.pack(fill="both", expand=True); body.columnconfigure(1, weight=1)
        company_value = next((label for label, value in company_ids.items() if existing and value == existing.get("company_id")), company_labels[0])
        action_value = next((label for label, value in action_ids.items() if existing and value == existing.get("action_id")), action_labels[0])
        company_var = M.tk.StringVar(value=company_value); action_var = M.tk.StringVar(value=action_value)
        discount_var = M.tk.StringVar(value=str(existing.get("discount_pct")).replace(".", ",") if existing else "0"); note_var = M.tk.StringVar(value=str(existing.get("note") or "") if existing else "")
        for index, (label, variable, values) in enumerate((("Společnost *", company_var, company_labels), ("Akce", action_var, action_labels))):
            M.ttk.Label(body, text=label).grid(row=index, column=0, sticky="w", padx=(0, 8), pady=6); M.safe_combobox(body, textvariable=variable, values=values, state="readonly", width=56).grid(row=index, column=1, sticky="ew", pady=6)
        M.ttk.Label(body, text="Sleva [%] *").grid(row=2, column=0, sticky="w", pady=6); M.ttk.Entry(body, textvariable=discount_var).grid(row=2, column=1, sticky="ew", pady=6)
        M.ttk.Label(body, text="Poznámka").grid(row=3, column=0, sticky="w", pady=6); M.ttk.Entry(body, textvariable=note_var).grid(row=3, column=1, sticky="ew", pady=6)

        def commit():
            try:
                save_rule(M, product_id, company_ids[company_var.get()], discount_var.get(), action_ids.get(action_var.get()), note_var.get())
            except Exception as exc:
                return M.messagebox.showerror("Slevy", str(exc), parent=form)
            form.destroy(); refresh()
            if callable(on_changed):
                on_changed()

        buttons = M.ttk.Frame(body); buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0)); M.ttk.Button(buttons, text="Zrušit", command=form.destroy).pack(side="left", padx=(0, 6)); M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=commit).pack(side="left")

    def edit_selected():
        row = selected()
        if row:
            edit(row)
        else:
            M.messagebox.showinfo("Slevy", "Vyberte pravidlo.", parent=dialog)

    def remove():
        row = selected()
        if not row:
            return M.messagebox.showinfo("Slevy", "Vyberte pravidlo.", parent=dialog)
        if M.messagebox.askyesno("Odstranit pravidlo", "Odstranit pravidlo? Starší vydané nabídky se nezmění.", parent=dialog):
            delete_rule(M, row["id"]); refresh()
            if callable(on_changed):
                on_changed()

    tools = M.ttk.Frame(outer); tools.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    M.ttk.Button(tools, text="+ Nové pravidlo", style="Accent.TButton", command=lambda: edit()).pack(side="left"); M.ttk.Button(tools, text="Upravit", command=edit_selected).pack(side="left", padx=5); M.ttk.Button(tools, text="Odstranit", command=remove).pack(side="left"); M.ttk.Button(tools, text="Zavřít", command=dialog.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit_selected()); refresh(); return dialog


def manager(M, app, parent):
    ensure_schema(M)
    dialog = M.tk.Toplevel(parent); dialog.title("Ruční výrobky, ceny a zákaznické slevy"); dialog.transient(parent); dialog.grab_set(); M.enable_dialog_maximize(dialog, 1400, 800)
    outer = M.ttk.Frame(dialog, padding=14); outer.pack(fill="both", expand=True); outer.columnconfigure(0, weight=1); outer.rowconfigure(3, weight=1)
    M.ttk.Label(outer, text="Ruční výrobky a obchodní podmínky", font=("Calibri", 17, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(outer, text="Ruční cena je záloha. Zákaznická sleva může být výchozí pro společnost nebo výjimečná pro konkrétní Akci.", style="PageSubtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 10))
    query = M.tk.StringVar(value=""); M.ttk.Entry(outer, textvariable=query, width=45).grid(row=2, column=0, sticky="w", pady=(0, 8))
    columns = ("Typ", "Kód", "Výrobek", "Výrobce", "Zařazení", "Ruční cena", "MJ", "Marže", "Standardní sleva")
    tree = M.ttk.Treeview(outer, columns=columns, show="headings", selectmode="browse")
    for column, width in zip(columns, (70, 105, 290, 170, 280, 130, 55, 80, 110)):
        tree.heading(column, text=column); tree.column(column, width=width, anchor="w")
    tree.grid(row=3, column=0, sticky="nsew"); scroll = M.ttk.Scrollbar(outer, orient="vertical", command=tree.yview); scroll.grid(row=3, column=1, sticky="ns"); tree.configure(yscrollcommand=scroll.set)
    rows = {}; after = {"id": None}

    def refresh(*_):
        children = tree.get_children()
        if children:
            tree.delete(*children)
        rows.clear(); text = query.get().strip().casefold(); params = []; where = ""
        if text:
            where = "WHERE lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,'')) LIKE ?"; params = [f"%{text}%"]
        with M.db() as con:
            data = con.execute(
                """SELECT cp.*,coalesce(c.name,'Nezařazeno') category_name,coalesce(s.name,'') subgroup_name
                   FROM catalog_products cp LEFT JOIN product_categories c ON c.id=cp.category_id
                   LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id """ + where +
                " ORDER BY cp.manual_product DESC,cp.active DESC,c.sort_order,s.sort_order,cp.internal_name COLLATE CZECH,cp.id",
                params,
            ).fetchall()
        for row in data:
            iid = f"p{row['id']}"; rows[iid] = dict(row); placement = row["category_name"] + (f" › {row['subgroup_name']}" if row["subgroup_name"] else "")
            price = "" if row["manual_purchase_unit_price"] is None else f"{_number(row['manual_purchase_unit_price']):,.2f} {row['manual_currency'] or 'CZK'}".replace(",", " ")
            tree.insert("", "end", iid=iid, values=("Ruční" if row["manual_product"] else "Import", row["internal_code"] or "", row["internal_name"] or "", row["manufacturer_name"] or "", placement, price, row["manual_unit"] or "ks", "dědí" if row["default_margin_pct"] is None else f"{_number(row['default_margin_pct']):g} %", "dědí" if row["default_discount_pct"] is None else f"{_number(row['default_discount_pct']):g} %"))

    def schedule(*_):
        if after["id"]:
            try: dialog.after_cancel(after["id"])
            except Exception: pass
        after["id"] = dialog.after(180, refresh)

    def selected_id():
        selection = tree.selection(); return int(selection[0][1:]) if selection else None

    def saved(_id=None):
        try:
            from . import product_catalog
            product_catalog._invalidate(app)
        except Exception:
            pass
        refresh()

    def edit():
        product_id = selected_id()
        if product_id: product_editor(M, app, dialog, product_id, saved)
        else: M.messagebox.showinfo("Katalog produktů", "Vyberte výrobek.", parent=dialog)

    def discounts():
        product_id = selected_id()
        if product_id: rules_dialog(M, app, dialog, product_id, saved)
        else: M.messagebox.showinfo("Slevy", "Vyberte výrobek.", parent=dialog)

    tools = M.ttk.Frame(outer); tools.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    M.ttk.Button(tools, text="+ Nový ruční výrobek", style="Accent.TButton", command=lambda: product_editor(M, app, dialog, None, saved)).pack(side="left"); M.ttk.Button(tools, text="Upravit výrobek / ruční cenu", command=edit).pack(side="left", padx=5); M.ttk.Button(tools, text="Slevy společností a Akcí…", command=discounts).pack(side="left"); M.ttk.Button(tools, text="Zavřít", command=dialog.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit()); query.trace_add("write", schedule); refresh(); return dialog


def _patch_workspace(M):
    try:
        from . import product_workspace
    except Exception:
        return
    if getattr(product_workspace, "_turto_customer_pricing_toolbar_v6340", False):
        return
    original = product_workspace.build_product_workspace

    @functools.wraps(original)
    def build(M2, app, parent, category_id=None, subgroup_id=None, embedded=False):
        app_root = _root(app)
        if not embedded and not getattr(parent, "_turto_customer_pricing_bar_v6340", False):
            bar = M2.ttk.Frame(parent, padding=(10, 8, 10, 0)); bar.pack(fill="x")
            M2.ttk.Button(bar, text="+ Nový ruční výrobek", style="Accent.TButton", command=lambda: product_editor(M2, app_root, parent)).pack(side="left")
            M2.ttk.Button(bar, text="Ruční ceny a zákaznické slevy…", command=lambda: manager(M2, app_root, parent)).pack(side="left", padx=5)
            M2.ttk.Label(bar, text="Sleva: Akce → společnost → standard; ruční řádek má vždy přednost.", style="PageSubtitle.TLabel").pack(side="right")
            parent._turto_customer_pricing_bar_v6340 = True
        return original(M2, app, parent, category_id, subgroup_id, embedded)

    product_workspace.build_product_workspace = build
    product_workspace._turto_customer_pricing_toolbar_v6340 = True


def install(M):
    if getattr(M, "_turto_customer_pricing_v6340", False):
        return
    old_ensure = M.ensure_schema

    def wrapped_ensure():
        old_ensure(); ensure_schema(M)

    M.ensure_schema = wrapped_ensure
    M.ensure_customer_pricing_schema = lambda: ensure_schema(M)
    M.resolve_customer_product_pricing = lambda product_id, company_id=None, action_id=None, as_of=None: resolve(M, product_id, company_id, action_id, as_of)
    M.apply_customer_pricing = lambda payload, force=False: price_payload(M, payload, force)
    M.open_manual_products_manager = lambda app, parent=None: manager(M, _root(app), parent or app)
    _patch_catalog_rows(M); _patch_workspace(M); _patch_document_service(M); _patch_pickers(M)
    M._turto_customer_pricing_v6340 = True


__all__ = ["install", "ensure_schema", "save_product", "product_pricing", "resolve", "save_rule", "list_rules", "delete_rule", "price_payload", "manager", "product_editor", "rules_dialog"]
