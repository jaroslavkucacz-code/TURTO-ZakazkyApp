"""Manual catalogue products and customer/action-specific discount policy.

This module is the canonical owner of customer-facing catalogue pricing rules.
Imported Ceníky remain the owner of purchase-price history. A manually entered
purchase price is only a fallback for a stable catalogue product without a valid
imported price. Customer and Action discounts are kept outside price lists and
issued documents continue to store immutable line snapshots.
"""
from __future__ import annotations

import copy
import functools
import inspect
from datetime import date


UNSET = object()


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _add_column(con, table: str, declaration: str) -> None:
    name = declaration.split()[0].strip('"[]`')
    if name not in _columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {declaration}")


def _number(value, default=0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _optional_number(value):
    if value in (None, ""):
        return None
    return float(str(value).strip().replace(" ", "").replace(",", "."))


def _clamp_discount(value) -> float:
    return min(100.0, max(0.0, _number(value)))


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


def ensure_customer_pricing_schema(M) -> None:
    """Apply the additive 6.3.40 schema exactly as often as needed."""
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

        if "business_document_items" in {
            str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }:
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


def _next_manual_code(M) -> str:
    with M.db() as con:
        rows = con.execute(
            "SELECT internal_code FROM catalog_products WHERE upper(trim(internal_code)) LIKE 'RUC-%'"
        ).fetchall()
    highest = 0
    for row in rows:
        text = str(row[0] or "").strip().upper()
        try:
            highest = max(highest, int(text.rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"RUC-{highest + 1:05d}"


def save_manual_product(M, values: dict, product_id=None) -> int:
    """Create or update a stable catalogue product without manufacturing a fake Ceník."""
    ensure_customer_pricing_schema(M)
    name = str(values.get("internal_name") or "").strip()
    if not name:
        raise ValueError("Interní označení výrobku je povinné.")
    code = str(values.get("internal_code") or "").strip()
    if not code and not product_id:
        code = _next_manual_code(M)
    manufacturer = str(values.get("manufacturer_name") or "").strip()
    description = str(values.get("description") or "").strip()
    currency = str(values.get("manual_currency") or "CZK").strip().upper() or "CZK"
    unit = str(values.get("manual_unit") or "ks").strip() or "ks"
    note = str(values.get("manual_price_note") or "").strip()
    purchase = _optional_number(values.get("manual_purchase_unit_price"))
    margin = _optional_number(values.get("default_margin_pct"))
    discount = _optional_number(values.get("default_discount_pct"))
    if discount is not None and not 0 <= discount <= 100:
        raise ValueError("Standardní sleva musí být v rozsahu 0 až 100 %.")
    if margin is not None and margin <= -100:
        raise ValueError("Marže musí být větší než −100 %.")
    if purchase is not None and purchase < 0:
        raise ValueError("Nákupní cena nesmí být záporná.")
    category_id = int(values["category_id"]) if values.get("category_id") else None
    subgroup_id = int(values["subgroup_id"]) if values.get("subgroup_id") else None
    active = 1 if values.get("active", True) else 0

    with M.db() as con:
        if subgroup_id:
            subgroup = con.execute(
                "SELECT category_id FROM product_subgroups WHERE id=?", (subgroup_id,)
            ).fetchone()
            if not subgroup:
                raise ValueError("Vybraná podskupina už neexistuje.")
            category_id = int(subgroup["category_id"])
        if code:
            duplicate = con.execute(
                """SELECT id FROM catalog_products
                   WHERE lower(trim(internal_code))=lower(trim(?)) AND id<>? LIMIT 1""",
                (code, int(product_id or 0)),
            ).fetchone()
            if duplicate:
                raise ValueError("Stejný interní kód už používá jiný výrobek.")

        params = (
            manufacturer, code, name, description, category_id, subgroup_id, active,
            purchase, currency, unit, note, margin, discount,
        )
        if product_id:
            product_id = int(product_id)
            exists = con.execute("SELECT id FROM catalog_products WHERE id=?", (product_id,)).fetchone()
            if not exists:
                raise ValueError("Upravovaný výrobek už neexistuje.")
            con.execute(
                """UPDATE catalog_products SET
                     manufacturer_name=?,internal_code=?,internal_name=?,description=?,
                     category_id=?,subgroup_id=?,active=?,manual_purchase_unit_price=?,
                     manual_currency=?,manual_unit=?,manual_price_note=?,
                     default_margin_pct=?,default_discount_pct=?,
                     manual_price_updated_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                params + (product_id,),
            )
        else:
            product_id = int(con.execute(
                """INSERT INTO catalog_products(
                     manufacturer_name,internal_code,internal_name,description,
                     category_id,subgroup_id,active,manual_product,
                     manual_purchase_unit_price,manual_currency,manual_unit,manual_price_note,
                     default_margin_pct,default_discount_pct,manual_price_updated_at
                   ) VALUES(?,?,?,?,?,?,?,1,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                params,
            ).lastrowid)

        identity = f"manual:{product_id}"
        con.execute(
            """INSERT INTO catalog_product_sources(
                 product_id,supplier_company_id,supplier_name,supplier_name_norm,
                 source_key,product_identity,supplier_product_code,source_name,source_kind,last_seen_at
               ) VALUES(?,NULL,?,?,?, ?,?,?, 'manual',CURRENT_TIMESTAMP)
               ON CONFLICT(source_key) DO UPDATE SET
                 product_id=excluded.product_id,
                 supplier_name=excluded.supplier_name,
                 supplier_name_norm=excluded.supplier_name_norm,
                 supplier_product_code=excluded.supplier_product_code,
                 source_name=excluded.source_name,
                 source_kind='manual',last_seen_at=CURRENT_TIMESTAMP""",
            (
                product_id, manufacturer, manufacturer.casefold(), identity, identity,
                code, name,
            ),
        )
    return int(product_id)


def product_pricing(M, product_id: int, as_of=None) -> dict:
    """Return current imported price or the manual fallback and standard policy."""
    ensure_customer_pricing_schema(M)
    day = str(as_of or date.today().isoformat())
    with M.db() as con:
        row = con.execute(
            """SELECT cp.id,cp.active,cp.manual_product,cp.internal_code,cp.internal_name,
                      cp.description,cp.manufacturer_name,cp.category_id,cp.subgroup_id,
                      cp.manual_purchase_unit_price,coalesce(cp.manual_currency,'CZK') manual_currency,
                      coalesce(cp.manual_unit,'ks') manual_unit,coalesce(cp.manual_price_note,'') manual_price_note,
                      cp.default_margin_pct product_margin,cp.default_discount_pct product_discount,
                      coalesce(s.default_margin_pct,c.default_margin_pct,0) hierarchy_margin,
                      coalesce(s.default_discount_pct,c.default_discount_pct,0) hierarchy_discount,
                      coalesce(c.show_recommended_price,1) show_recommended_price,
                      coalesce(c.name,'') category_name,coalesce(s.name,'') subgroup_name,
                      (SELECT i.normalized_unit_price FROM price_list_items i
                         JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1
                          AND coalesce(p.archived,0)=0 AND p.valid_from<=?
                          AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_price,
                      (SELECT coalesce(i.currency,'CZK') FROM price_list_items i
                         JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1
                          AND coalesce(p.archived,0)=0 AND p.valid_from<=?
                          AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_currency,
                      (SELECT coalesce(i.unit,'') FROM price_list_items i
                         JOIN price_lists p ON p.id=i.price_list_id
                        WHERE i.catalog_product_id=cp.id AND coalesce(i.active,1)=1
                          AND coalesce(p.archived,0)=0 AND p.valid_from<=?
                          AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                        ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1) imported_unit
                 FROM catalog_products cp
                 LEFT JOIN product_categories c ON c.id=cp.category_id
                 LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id
                WHERE cp.id=?""",
            (day, day, day, day, day, day, int(product_id)),
        ).fetchone()
    if not row:
        raise ValueError("Katalogový výrobek už neexistuje.")
    data = dict(row)
    imported = data.get("imported_price")
    manual = data.get("manual_purchase_unit_price")
    purchase = _number(imported if imported is not None else manual)
    currency = str(data.get("imported_currency") or data.get("manual_currency") or "CZK")
    unit = str(data.get("imported_unit") or data.get("manual_unit") or "ks")
    margin = _number(data.get("product_margin") if data.get("product_margin") is not None else data.get("hierarchy_margin"))
    standard_discount = _clamp_discount(
        data.get("product_discount") if data.get("product_discount") is not None else data.get("hierarchy_discount")
    )
    if data.get("product_discount") is not None:
        standard_source = "Standard výrobku"
    elif data.get("subgroup_id"):
        standard_source = "Standard podskupiny"
    elif data.get("category_id"):
        standard_source = "Standard skupiny"
    else:
        standard_source = "Standard"
    recommended = purchase * (1.0 + margin / 100.0)
    final = recommended * (1.0 - standard_discount / 100.0)
    data.update(
        purchase_unit_price=purchase,
        currency=currency,
        unit=unit,
        margin_pct=margin,
        standard_discount_pct=standard_discount,
        standard_discount_source=standard_source,
        discount_pct=standard_discount,
        discount_source=standard_source,
        discount_rule_id=None,
        recommended_unit_price=recommended,
        final_unit_price=final,
        purchase_source="Ceník" if imported is not None else ("Ruční cena" if manual is not None else "Bez ceny"),
    )
    return data


def resolve_product_pricing(M, product_id: int, company_id=None, action_id=None, as_of=None) -> dict:
    """Resolve Action → company → standard product/group discount hierarchy."""
    result = product_pricing(M, int(product_id), as_of=as_of)
    company_id = int(company_id) if company_id else None
    action_id = int(action_id) if action_id else None
    rule = None
    if company_id:
        with M.db() as con:
            if action_id:
                rule = con.execute(
                    """SELECT id,discount_pct,note FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id=? AND active=1
                       ORDER BY id DESC LIMIT 1""",
                    (int(product_id), company_id, action_id),
                ).fetchone()
                if rule:
                    source = "Výjimka pro Akci"
            if not rule:
                rule = con.execute(
                    """SELECT id,discount_pct,note FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id IS NULL AND active=1
                       ORDER BY id DESC LIMIT 1""",
                    (int(product_id), company_id),
                ).fetchone()
                if rule:
                    source = "Sleva společnosti"
    if rule:
        result["discount_pct"] = _clamp_discount(rule["discount_pct"])
        result["discount_source"] = source
        result["discount_rule_id"] = int(rule["id"])
        result["discount_note"] = str(rule["note"] or "")
        result["final_unit_price"] = result["recommended_unit_price"] * (
            1.0 - result["discount_pct"] / 100.0
        )
    return result


def list_discount_rules(M, product_id: int):
    ensure_customer_pricing_schema(M)
    with M.db() as con:
        return con.execute(
            """SELECT r.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(c.short_name),''),'') company_name,
                      coalesce(a.name,'') action_name
                 FROM customer_product_discounts r
                 JOIN companies c ON c.id=r.company_id
                 LEFT JOIN actions a ON a.id=r.action_id
                WHERE r.product_id=?
                ORDER BY r.active DESC,company_name COLLATE CZECH,
                         CASE WHEN r.action_id IS NULL THEN 0 ELSE 1 END,
                         action_name COLLATE CZECH,r.id""",
            (int(product_id),),
        ).fetchall()


def save_discount_rule(M, product_id: int, company_id: int, discount_pct, action_id=None, note="") -> int:
    ensure_customer_pricing_schema(M)
    product_id = int(product_id)
    company_id = int(company_id)
    action_id = int(action_id) if action_id else None
    discount = _clamp_discount(discount_pct)
    with M.db() as con:
        if not con.execute("SELECT id FROM catalog_products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("Vybraný výrobek už neexistuje.")
        if not con.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone():
            raise ValueError("Vybraná společnost už neexistuje.")
        if action_id and not con.execute("SELECT id FROM actions WHERE id=?", (action_id,)).fetchone():
            raise ValueError("Vybraná Akce už neexistuje.")
        if action_id:
            existing = con.execute(
                """SELECT id FROM customer_product_discounts
                   WHERE product_id=? AND company_id=? AND action_id=?""",
                (product_id, company_id, action_id),
            ).fetchone()
        else:
            existing = con.execute(
                """SELECT id FROM customer_product_discounts
                   WHERE product_id=? AND company_id=? AND action_id IS NULL""",
                (product_id, company_id),
            ).fetchone()
        if existing:
            rule_id = int(existing["id"])
            con.execute(
                """UPDATE customer_product_discounts SET discount_pct=?,note=?,active=1,
                     updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (discount, str(note or "").strip(), rule_id),
            )
        else:
            rule_id = int(con.execute(
                """INSERT INTO customer_product_discounts(
                     product_id,company_id,action_id,discount_pct,note,active
                   ) VALUES(?,?,?,?,?,1)""",
                (product_id, company_id, action_id, discount, str(note or "").strip()),
            ).lastrowid)
    return rule_id


def delete_discount_rule(M, rule_id: int) -> None:
    ensure_customer_pricing_schema(M)
    with M.db() as con:
        con.execute("DELETE FROM customer_product_discounts WHERE id=?", (int(rule_id),))


def apply_pricing_to_document_payload(M, payload: dict, force: bool = False) -> dict:
    """Apply defaults to catalogue lines while preserving explicit line overrides."""
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), (list, tuple)):
        return payload
    result = copy.deepcopy(payload)
    company_id = result.get("company_id") or result.get("customer_company_id") or result.get("buyer_company_id")
    action_id = result.get("action_id")
    issue_date = result.get("issue_date") or date.today().isoformat()
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        product_id = item.get("catalog_product_id") or item.get("product_id")
        if not product_id:
            continue
        try:
            pricing = resolve_product_pricing(M, int(product_id), company_id, action_id, issue_date)
        except Exception:
            continue
        manual_override = bool(
            item.get("discount_manual") or item.get("manual_discount") or item.get("pricing_locked")
            or str(item.get("discount_source") or "").casefold() in {"ruční", "rucni", "manual"}
        )
        current_discount = item.get("discount_pct", UNSET)
        known_discounts = {round(_number(pricing.get("standard_discount_pct")), 8)}
        if pricing.get("discount_rule_id"):
            known_discounts.add(round(_number(pricing.get("discount_pct")), 8))
        may_replace = (
            force or current_discount is UNSET or current_discount in (None, "")
            or round(_number(current_discount), 8) in known_discounts
            or str(item.get("discount_source") or "").casefold() in {
                "", "standard", "standard výrobku", "standard podskupiny", "standard skupiny",
                "sleva společnosti", "výjimka pro akci",
            }
        )
        if not manual_override and may_replace:
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
        discount = _clamp_discount(item.get("discount_pct", pricing["discount_pct"]))
        recommended = purchase * (1.0 + margin / 100.0)
        final = recommended * (1.0 - discount / 100.0)
        item["recommended_unit_price"] = recommended
        item["unit_price"] = final
        item["total_price"] = _number(item.get("quantity"), 1.0) * final
        item.setdefault("show_recommended_price", pricing.get("show_recommended_price", 1))
    return result


def _find_payload_context(value):
    if isinstance(value, dict):
        if isinstance(value.get("items"), (list, tuple)):
            return value
        for nested in value.values():
            found = _find_payload_context(nested)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_payload_context(nested)
            if found is not None:
                return found
    return None


def _replace_payload(value, old_payload, new_payload):
    if value is old_payload:
        return new_payload
    if isinstance(value, list):
        return [_replace_payload(v, old_payload, new_payload) for v in value]
    if isinstance(value, tuple):
        return tuple(_replace_payload(v, old_payload, new_payload) for v in value)
    if isinstance(value, dict):
        return {k: _replace_payload(v, old_payload, new_payload) for k, v in value.items()}
    return value


def _patch_issued_offer_persistence(M) -> None:
    """Attach pricing to the canonical issued-document persistence entry point."""
    try:
        from ..issued_offers import service
    except Exception:
        return
    if getattr(service, "_turto_customer_pricing_v6340", False):
        return
    preferred = {
        "save_document", "save_offer", "create_document", "update_document",
        "save_business_document", "upsert_document",
    }
    patched = 0
    for name, function in list(vars(service).items()):
        if not inspect.isfunction(function) or name.startswith("_"):
            continue
        try:
            source = inspect.getsource(function).casefold()
        except Exception:
            source = ""
        is_persistence = name in preferred or (
            "business_document_items" in source and "items" in source
            and any(token in source for token in ("insert into", "update business_documents", "executemany"))
        )
        if not is_persistence or getattr(function, "_turto_customer_pricing_wrapper", False):
            continue

        @functools.wraps(function)
        def wrapped(*args, __function=function, **kwargs):
            payload = _find_payload_context(args) or _find_payload_context(kwargs)
            if payload is None:
                return __function(*args, **kwargs)
            priced = apply_pricing_to_document_payload(M, payload)
            new_args = tuple(_replace_payload(value, payload, priced) for value in args)
            new_kwargs = {key: _replace_payload(value, payload, priced) for key, value in kwargs.items()}
            return __function(*new_args, **new_kwargs)

        wrapped._turto_customer_pricing_wrapper = True
        setattr(service, name, wrapped)
        patched += 1
    service.resolve_customer_product_pricing = lambda product_id, company_id=None, action_id=None, as_of=None: (
        resolve_product_pricing(M, product_id, company_id, action_id, as_of)
    )
    service.apply_customer_pricing = lambda payload, force=False: apply_pricing_to_document_payload(M, payload, force)
    service._turto_customer_pricing_v6340 = True
    service._turto_customer_pricing_persistence_hooks = patched


def _manual_picker_rows(M, company_id=None, action_id=None):
    with M.db() as con:
        ids = [int(row[0]) for row in con.execute(
            "SELECT id FROM catalog_products WHERE active=1 AND manual_product=1 ORDER BY id"
        ).fetchall()]
    rows = []
    for product_id in ids:
        try:
            price = resolve_product_pricing(M, product_id, company_id, action_id)
        except Exception:
            continue
        rows.append({
            "id": product_id,
            "product_id": product_id,
            "catalog_product_id": product_id,
            "internal_code": price.get("internal_code") or "",
            "product_code": price.get("internal_code") or "",
            "code": price.get("internal_code") or "",
            "item_key": price.get("internal_code") or price.get("internal_name") or "",
            "internal_name": price.get("internal_name") or "",
            "name": price.get("internal_name") or "",
            "description": price.get("description") or "",
            "manufacturer_name": price.get("manufacturer_name") or "",
            "category_id": price.get("category_id"),
            "subgroup_id": price.get("subgroup_id"),
            "category": price.get("category_name") or "",
            "subgroup": price.get("subgroup_name") or "",
            "purchase_unit_price": price.get("purchase_unit_price") or 0,
            "normalized_unit_price": price.get("purchase_unit_price") or 0,
            "current_price": price.get("purchase_unit_price") or 0,
            "margin_pct": price.get("margin_pct") or 0,
            "discount_pct": price.get("discount_pct") or 0,
            "discount_source": price.get("discount_source") or "",
            "recommended_unit_price": price.get("recommended_unit_price") or 0,
            "unit_price": price.get("final_unit_price") or 0,
            "final_unit_price": price.get("final_unit_price") or 0,
            "currency": price.get("currency") or "CZK",
            "unit": price.get("unit") or "ks",
            "show_recommended_price": price.get("show_recommended_price", 1),
            "manual_product": 1,
        })
    return rows


def _augment_picker_result(M, result, company_id=None, action_id=None):
    manual = _manual_picker_rows(M, company_id, action_id)
    if not manual:
        return result

    def merge(rows):
        if not isinstance(rows, list):
            return rows, 0
        existing = set()
        for row in rows:
            try:
                keys = set(row.keys())
                value = row["catalog_product_id"] if "catalog_product_id" in keys else row["product_id"] if "product_id" in keys else row["id"]
                existing.add(int(value))
            except Exception:
                pass
        additions = [dict(row) for row in manual if int(row["catalog_product_id"]) not in existing]
        return rows + additions, len(additions)

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


def _patch_catalog_pickers(M) -> None:
    """Append manually maintained products to existing catalogue selectors."""
    modules = []
    try:
        from ..issued_offers import service, editor
        modules.extend((service, editor))
    except Exception:
        pass
    for module in modules:
        if getattr(module, "_turto_manual_picker_v6340", False):
            continue
        for name, function in list(vars(module).items()):
            if not inspect.isfunction(function) or name.startswith("_"):
                continue
            folded = name.casefold()
            if not any(token in folded for token in ("catalog", "product", "picker", "search")):
                continue
            try:
                source = inspect.getsource(function).casefold()
            except Exception:
                source = ""
            if "catalog_products" not in source and "price_list_items" not in source:
                continue
            if getattr(function, "_turto_manual_picker_wrapper", False):
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
                if __signature is not None:
                    try:
                        bound = __signature.bind_partial(*args, **kwargs).arguments
                        company_id = company_id or bound.get("company_id") or bound.get("customer_company_id")
                        action_id = action_id or bound.get("action_id")
                    except Exception:
                        pass
                return _augment_picker_result(M, result, company_id, action_id)

            wrapped._turto_manual_picker_wrapper = True
            setattr(module, name, wrapped)
        module._turto_manual_picker_v6340 = True


def _catalog_rows_with_manual(M, workspace, scope, query="", manufacturer="", show_inactive=False,
                              limit=250, offset=0, sort_mode="Skupina → podskupina → produkt"):
    """SQL-page products with imported price first and manual fallback second."""
    where = ["1=1"]
    params = []
    if not show_inactive:
        where.append("cp.active=1")
    scope_where, scope_params = workspace._scope_conditions(scope)
    where.extend(scope_where)
    params.extend(scope_params)
    text = str(query or "").strip().casefold()
    if text:
        where.append(
            """lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||
               coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')||' '||
               coalesce(src.source_code,'')||' '||coalesce(src.source_name,'')) LIKE ?"""
        )
        params.append("%" + text + "%")
    maker = str(manufacturer or "").strip().casefold()
    if maker:
        where.append("lower(coalesce(cp.manufacturer_name,'')||' '||coalesce(src.suppliers,'')) LIKE ?")
        params.append("%" + maker + "%")
    where_sql = " AND ".join(where)
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
    sort_map = {
        "Skupina → podskupina → produkt": (
            "coalesce(category_sort,2147483647),category COLLATE CZECH,"
            "coalesce(subgroup_sort,2147483647),subgroup COLLATE CZECH,"
            "coalesce(nullif(trim(internal_name),''),source_name,'') COLLATE CZECH,id"
        ),
        "Interní označení A–Z": "coalesce(nullif(trim(internal_name),''),source_name,'') COLLATE CZECH,id",
        "Výrobce A–Z": "coalesce(nullif(trim(manufacturer_name),''),suppliers,'') COLLATE CZECH,source_name COLLATE CZECH,id",
        "Dodavatel A–Z": "suppliers COLLATE CZECH,source_name COLLATE CZECH,id",
        "Nákupní cena ↑": "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,current_price ASC,id",
        "Nákupní cena ↓": "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,current_price DESC,id",
        "Výsledná cena ↑": (
            "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,"
            "(current_price*(1+margin_pct/100.0)*(1-discount_pct/100.0)) ASC,id"
        ),
        "Výsledná cena ↓": (
            "CASE WHEN current_price IS NULL THEN 1 ELSE 0 END,"
            "(current_price*(1+margin_pct/100.0)*(1-discount_pct/100.0)) DESC,id"
        ),
    }
    order_sql = sort_map.get(str(sort_mode or ""), sort_map["Skupina → podskupina → produkt"])
    select_sql = """SELECT cp.id,cp.active,cp.category_id,cp.subgroup_id,
                          cp.manufacturer_name,cp.internal_code,cp.internal_name,
                          cp.manual_product,cp.manual_purchase_unit_price,cp.manual_unit,
                          coalesce(c.name,'Nezařazeno') category,coalesce(sg.name,'') subgroup,
                          c.sort_order category_sort,sg.sort_order subgroup_sort,
                          coalesce(cp.default_margin_pct,sg.default_margin_pct,c.default_margin_pct,0) margin_pct,
                          coalesce(cp.default_discount_pct,sg.default_discount_pct,c.default_discount_pct,0) discount_pct,
                          coalesce(c.show_recommended_price,1) show_recommended_price,
                          coalesce(src.suppliers,'') suppliers,coalesce(src.source_code,'') source_code,
                          coalesce(src.source_name,'') source_name,
                          (SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                            WHERE i.catalog_product_id=cp.id) price_lists,
                          (SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                            WHERE i.catalog_product_id=cp.id) offers,
                          coalesce((SELECT i.normalized_unit_price FROM price_list_items i
                            JOIN price_lists p ON p.id=i.price_list_id
                            WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                              AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                            ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1),
                            cp.manual_purchase_unit_price) current_price,
                          coalesce((SELECT i.currency FROM price_list_items i
                            JOIN price_lists p ON p.id=i.price_list_id
                            WHERE i.catalog_product_id=cp.id AND i.active=1 AND p.archived=0
                              AND p.valid_from<=? AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)
                            ORDER BY p.valid_from DESC,p.id DESC,i.id DESC LIMIT 1),
                            cp.manual_currency,'CZK') current_currency
                   """ + sql_from + " WHERE " + where_sql
    with M.db() as con:
        total = int(con.execute("SELECT COUNT(*) " + sql_from + " WHERE " + where_sql, params).fetchone()[0] or 0)
        rows = con.execute(
            "WITH product_rows AS (" + select_sql + ") SELECT * FROM product_rows ORDER BY " + order_sql +
            " LIMIT ? OFFSET ?",
            [today, today, today, today] + params + [max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        summary = con.execute(
            """SELECT COUNT(*) products,
                      COUNT(DISTINCT nullif(trim(cp.manufacturer_name),'')) manufacturers,
                      coalesce(SUM((SELECT COUNT(DISTINCT i.price_list_id) FROM price_list_items i
                                    WHERE i.catalog_product_id=cp.id)),0) list_links,
                      coalesce(SUM((SELECT COUNT(DISTINCT i.offer_id) FROM supplier_offer_items i
                                    WHERE i.catalog_product_id=cp.id)),0) offer_links
               """ + sql_from + " WHERE " + where_sql,
            params,
        ).fetchone()
    return total, rows, summary


def _category_options(M):
    with M.db() as con:
        groups = con.execute(
            "SELECT id,name FROM product_categories WHERE active=1 ORDER BY sort_order,name COLLATE CZECH"
        ).fetchall()
        subgroups = con.execute(
            """SELECT s.id,s.category_id,s.name,c.name category_name
                 FROM product_subgroups s JOIN product_categories c ON c.id=s.category_id
                WHERE s.active=1 AND c.active=1
                ORDER BY c.sort_order,c.name COLLATE CZECH,s.sort_order,s.name COLLATE CZECH"""
        ).fetchall()
    return groups, subgroups


def _company_options(M):
    with M.db() as con:
        rows = con.execute(
            """SELECT id,coalesce(nullif(trim(official_name),''),nullif(trim(short_name),''),'') name
                 FROM companies WHERE coalesce(active,1)=1
                ORDER BY name COLLATE CZECH,id"""
        ).fetchall()
    labels = [f"{row['name']}  [#{row['id']}]" for row in rows]
    return labels, {label: int(row["id"]) for label, row in zip(labels, rows)}


def _action_options(M):
    with M.db() as con:
        cols = _columns(con, "actions")
        where = "WHERE coalesce(archived,0)=0" if "archived" in cols else ""
        rows = con.execute(
            f"SELECT id,coalesce(name,'') name FROM actions {where} ORDER BY name COLLATE CZECH,id DESC"
        ).fetchall()
    labels = ["— výchozí pro společnost —"] + [f"{row['name']}  [#{row['id']}]" for row in rows]
    mapping = {labels[0]: None}
    mapping.update({label: int(row["id"]) for label, row in zip(labels[1:], rows)})
    return labels, mapping


def _product_rows_for_manager(M, query=""):
    where = ["1=1"]
    params = []
    text = str(query or "").strip().casefold()
    if text:
        where.append(
            "lower(coalesce(cp.internal_code,'')||' '||coalesce(cp.internal_name,'')||' '||coalesce(cp.manufacturer_name,'')) LIKE ?"
        )
        params.append("%" + text + "%")
    with M.db() as con:
        return con.execute(
            """SELECT cp.*,coalesce(c.name,'Nezařazeno') category_name,coalesce(s.name,'') subgroup_name
                 FROM catalog_products cp
                 LEFT JOIN product_categories c ON c.id=cp.category_id
                 LEFT JOIN product_subgroups s ON s.id=cp.subgroup_id
                WHERE """ + " AND ".join(where) +
            " ORDER BY cp.manual_product DESC,cp.active DESC,c.sort_order,s.sort_order,cp.internal_name COLLATE CZECH,cp.id",
            params,
        ).fetchall()


def open_manual_product_editor(M, app, parent, product_id=None, on_saved=None):
    ensure_customer_pricing_schema(M)
    current = None
    if product_id:
        with M.db() as con:
            current = con.execute("SELECT * FROM catalog_products WHERE id=?", (int(product_id),)).fetchone()
        if not current:
            return M.messagebox.showwarning("Katalog produktů", "Výrobek už neexistuje.", parent=parent)
    groups, subgroups = _category_options(M)
    group_labels = ["Nezařazeno"] + [str(row["name"]) for row in groups]
    group_map = {"Nezařazeno": None, **{str(row["name"]): int(row["id"]) for row in groups}}
    subgroup_by_group = {}
    for row in subgroups:
        subgroup_by_group.setdefault(int(row["category_id"]), []).append(row)

    dialog = M.tk.Toplevel(parent)
    dialog.title("Upravit katalogový výrobek" if current else "Nový ruční výrobek")
    dialog.transient(parent)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 900, 720)
    frame = M.ttk.Frame(dialog, padding=18)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    values = {
        "internal_code": M.tk.StringVar(value=str(current["internal_code"] or "") if current else _next_manual_code(M)),
        "internal_name": M.tk.StringVar(value=str(current["internal_name"] or "") if current else ""),
        "manufacturer_name": M.tk.StringVar(value=str(current["manufacturer_name"] or "") if current else ""),
        "manual_purchase_unit_price": M.tk.StringVar(value=(str(current["manual_purchase_unit_price"]).replace(".", ",") if current and current["manual_purchase_unit_price"] is not None else "")),
        "manual_currency": M.tk.StringVar(value=str(current["manual_currency"] or "CZK") if current else "CZK"),
        "manual_unit": M.tk.StringVar(value=str(current["manual_unit"] or "ks") if current else "ks"),
        "default_margin_pct": M.tk.StringVar(value=(str(current["default_margin_pct"]).replace(".", ",") if current and current["default_margin_pct"] is not None else "")),
        "default_discount_pct": M.tk.StringVar(value=(str(current["default_discount_pct"]).replace(".", ",") if current and current["default_discount_pct"] is not None else "")),
        "active": M.tk.BooleanVar(value=bool(current["active"]) if current else True),
    }
    category_id = int(current["category_id"]) if current and current["category_id"] else None
    subgroup_id = int(current["subgroup_id"]) if current and current["subgroup_id"] else None
    group_name = next((str(row["name"]) for row in groups if int(row["id"]) == category_id), "Nezařazeno")
    group_var = M.tk.StringVar(value=group_name)
    subgroup_var = M.tk.StringVar(value="Bez podskupiny")
    description = M.tk.Text(frame, height=4, wrap="word")
    price_note = M.tk.Text(frame, height=3, wrap="word")
    if current:
        description.insert("1.0", str(current["description"] or ""))
        price_note.insert("1.0", str(current["manual_price_note"] or ""))

    row = 0
    M.ttk.Label(frame, text="Katalogový výrobek", font=("Calibri", 16, "bold")).grid(row=row, column=0, columnspan=2, sticky="w")
    row += 1
    M.ttk.Label(
        frame,
        text="Ruční nákupní cena se použije jen tehdy, když výrobek nemá platnou cenu z importovaného Ceníku.",
        style="PageSubtitle.TLabel",
    ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(2, 12))
    row += 1

    def entry(label, key, width=24):
        nonlocal row
        M.ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        widget = M.ttk.Entry(frame, textvariable=values[key], width=width)
        widget.grid(row=row, column=1, sticky="ew", pady=5)
        row += 1
        return widget

    entry("Interní kód", "internal_code")
    name_entry = entry("Interní označení *", "internal_name")
    entry("Výrobce", "manufacturer_name")
    M.ttk.Label(frame, text="Produktová skupina").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
    group_combo = M.safe_combobox(frame, textvariable=group_var, values=group_labels, state="readonly")
    group_combo.grid(row=row, column=1, sticky="ew", pady=5)
    row += 1
    M.ttk.Label(frame, text="Podskupina").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
    subgroup_combo = M.safe_combobox(frame, textvariable=subgroup_var, values=["Bez podskupiny"], state="readonly")
    subgroup_combo.grid(row=row, column=1, sticky="ew", pady=5)
    row += 1

    def refresh_subgroups(*_):
        gid = group_map.get(group_var.get())
        rows = subgroup_by_group.get(gid, []) if gid else []
        labels = ["Bez podskupiny"] + [str(item["name"]) for item in rows]
        subgroup_combo.configure(values=labels)
        selected = next((str(item["name"]) for item in rows if subgroup_id and int(item["id"]) == subgroup_id), None)
        if selected and selected in labels:
            subgroup_var.set(selected)
        elif subgroup_var.get() not in labels:
            subgroup_var.set("Bez podskupiny")

    group_combo.bind("<<ComboboxSelected>>", refresh_subgroups, add="+")
    refresh_subgroups()

    price = M.ttk.LabelFrame(frame, text="Cena a standard výrobku", padding=10)
    price.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 6))
    for col in range(6):
        price.columnconfigure(col, weight=1 if col in (1, 3, 5) else 0)
    M.ttk.Label(price, text="Nákupní cena").grid(row=0, column=0, sticky="w")
    M.ttk.Entry(price, textvariable=values["manual_purchase_unit_price"], width=14).grid(row=0, column=1, sticky="ew", padx=(6, 12))
    M.ttk.Label(price, text="Měna").grid(row=0, column=2, sticky="w")
    M.safe_combobox(price, textvariable=values["manual_currency"], values=["CZK", "EUR", "PLN"], width=8).grid(row=0, column=3, sticky="ew", padx=(6, 12))
    M.ttk.Label(price, text="MJ").grid(row=0, column=4, sticky="w")
    M.ttk.Entry(price, textvariable=values["manual_unit"], width=8).grid(row=0, column=5, sticky="ew", padx=(6, 0))
    M.ttk.Label(price, text="Marže produktu [%]").grid(row=1, column=0, sticky="w", pady=(8, 0))
    M.ttk.Entry(price, textvariable=values["default_margin_pct"], width=14).grid(row=1, column=1, sticky="ew", padx=(6, 12), pady=(8, 0))
    M.ttk.Label(price, text="Standardní sleva [%]").grid(row=1, column=2, sticky="w", pady=(8, 0))
    M.ttk.Entry(price, textvariable=values["default_discount_pct"], width=14).grid(row=1, column=3, sticky="ew", padx=(6, 12), pady=(8, 0))
    M.ttk.Label(price, text="Prázdné hodnoty přebírají skupinu / podskupinu.", style="PageSubtitle.TLabel").grid(row=1, column=4, columnspan=2, sticky="w", pady=(8, 0))
    row += 1

    M.ttk.Label(frame, text="Popis výrobku").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=5)
    description.grid(row=row, column=1, sticky="nsew", pady=5)
    row += 1
    M.ttk.Label(frame, text="Poznámka k ruční ceně").grid(row=row, column=0, sticky="nw", padx=(0, 12), pady=5)
    price_note.grid(row=row, column=1, sticky="nsew", pady=5)
    row += 1
    M.ttk.Checkbutton(frame, text="Aktivní výrobek", variable=values["active"]).grid(row=row, column=1, sticky="w", pady=(6, 10))
    row += 1

    def save():
        gid = group_map.get(group_var.get())
        subgroup_rows = subgroup_by_group.get(gid, []) if gid else []
        sid = next((int(item["id"]) for item in subgroup_rows if str(item["name"]) == subgroup_var.get()), None)
        data = {key: variable.get() for key, variable in values.items() if key != "active"}
        data.update(
            category_id=gid,subgroup_id=sid,active=values["active"].get(),
            description=description.get("1.0", "end").strip(),
            manual_price_note=price_note.get("1.0", "end").strip(),
        )
        try:
            saved_id = save_manual_product(M, data, product_id=product_id)
        except Exception as exc:
            return M.messagebox.showerror("Katalog produktů", str(exc), parent=dialog)
        dialog.destroy()
        if callable(on_saved):
            on_saved(saved_id)

    buttons = M.ttk.Frame(frame)
    buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="left", padx=(0, 6))
    M.ttk.Button(buttons, text="Uložit výrobek", style="Accent.TButton", command=save).pack(side="left")
    frame.rowconfigure(row - 3, weight=1)
    name_entry.focus_set()
    return dialog


def open_discount_rules(M, app, parent, product_id: int, on_changed=None):
    ensure_customer_pricing_schema(M)
    product = product_pricing(M, int(product_id))
    dialog = M.tk.Toplevel(parent)
    dialog.title("Slevy společností a Akcí")
    dialog.transient(parent)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 1160, 700)
    outer = M.ttk.Frame(dialog, padding=16)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(3, weight=1)
    M.ttk.Label(outer, text=product.get("internal_name") or product.get("internal_code"), font=("Calibri", 16, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        outer,
        text=("Pořadí: ruční sleva na řádku nabídky → výjimka pro Akci → sleva společnosti → "
              f"{product['standard_discount_source']} ({product['standard_discount_pct']:g} %)."),
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))
    status = M.tk.StringVar(value="")
    M.ttk.Label(outer, textvariable=status, style="PageSubtitle.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 6))
    columns = ("Společnost", "Akce / rozsah", "Sleva", "Poznámka", "Aktivní")
    tree = M.ttk.Treeview(outer, columns=columns, show="headings", selectmode="browse")
    for col, width in zip(columns, (280, 300, 90, 360, 75)):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=3, column=0, sticky="nsew")
    scroll = M.ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
    scroll.grid(row=3, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    rows = {}

    def refresh():
        tree.delete(*tree.get_children())
        rows.clear()
        data = list_discount_rules(M, product_id)
        for row in data:
            iid = f"r{row['id']}"
            rows[iid] = dict(row)
            tree.insert("", "end", iid=iid, values=(
                row["company_name"], row["action_name"] or "Výchozí pro společnost",
                f"{_number(row['discount_pct']):g} %", row["note"] or "",
                "Ano" if row["active"] else "Ne",
            ))
        status.set(f"Pravidel: {len(data)}")

    def edit_rule(existing=None):
        companies, company_map = _company_options(M)
        actions, action_map = _action_options(M)
        form = M.tk.Toplevel(dialog)
        form.title("Upravit pravidlo slevy" if existing else "Nové pravidlo slevy")
        form.transient(dialog)
        form.grab_set()
        body = M.ttk.Frame(form, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        company_label = next((label for label, cid in company_map.items() if existing and cid == existing.get("company_id")), companies[0] if companies else "")
        action_label = next((label for label, aid in action_map.items() if existing and aid == existing.get("action_id")), actions[0])
        company_var = M.tk.StringVar(value=company_label)
        action_var = M.tk.StringVar(value=action_label)
        discount_var = M.tk.StringVar(value=(str(existing.get("discount_pct")).replace(".", ",") if existing else "0"))
        note_var = M.tk.StringVar(value=str(existing.get("note") or "") if existing else "")
        M.ttk.Label(body, text="Společnost *").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=6)
        M.safe_combobox(body, textvariable=company_var, values=companies, state="readonly", width=55).grid(row=0, column=1, sticky="ew", pady=6)
        M.ttk.Label(body, text="Akce").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=6)
        M.safe_combobox(body, textvariable=action_var, values=actions, state="readonly", width=55).grid(row=1, column=1, sticky="ew", pady=6)
        M.ttk.Label(body, text="Sleva [%] *").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=6)
        M.ttk.Entry(body, textvariable=discount_var).grid(row=2, column=1, sticky="ew", pady=6)
        M.ttk.Label(body, text="Poznámka").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=6)
        M.ttk.Entry(body, textvariable=note_var).grid(row=3, column=1, sticky="ew", pady=6)

        def commit():
            company_id = company_map.get(company_var.get())
            if not company_id:
                return M.messagebox.showwarning("Slevy", "Vyberte společnost.", parent=form)
            try:
                discount = _optional_number(discount_var.get())
                if discount is None or not 0 <= discount <= 100:
                    raise ValueError("Sleva musí být v rozsahu 0 až 100 %.")
                save_discount_rule(
                    M, product_id, company_id, discount,
                    action_id=action_map.get(action_var.get()), note=note_var.get(),
                )
            except Exception as exc:
                return M.messagebox.showerror("Slevy", str(exc), parent=form)
            form.destroy()
            refresh()
            if callable(on_changed):
                on_changed()

        buttons = M.ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        M.ttk.Button(buttons, text="Zrušit", command=form.destroy).pack(side="left", padx=(0, 6))
        M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=commit).pack(side="left")

    def selected():
        selection = tree.selection()
        return rows.get(selection[0]) if selection else None

    def remove():
        row = selected()
        if not row:
            return M.messagebox.showinfo("Slevy", "Vyberte pravidlo.", parent=dialog)
        if not M.messagebox.askyesno(
            "Odstranit pravidlo",
            "Odstranit vybrané pravidlo? Již vydané PDF nabídky a jejich cenové snímky se nezmění.",
            parent=dialog,
        ):
            return
        delete_discount_rule(M, row["id"])
        refresh()
        if callable(on_changed):
            on_changed()

    tools = M.ttk.Frame(outer)
    tools.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    M.ttk.Button(tools, text="+ Nové pravidlo", style="Accent.TButton", command=lambda: edit_rule()).pack(side="left")
    M.ttk.Button(tools, text="Upravit", command=lambda: edit_rule(selected()) if selected() else None).pack(side="left", padx=5)
    M.ttk.Button(tools, text="Odstranit", command=remove).pack(side="left")
    M.ttk.Button(tools, text="Zavřít", command=dialog.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit_rule(selected()) if selected() else None)
    refresh()
    return dialog


def open_manual_products_manager(M, app, parent):
    ensure_customer_pricing_schema(M)
    dialog = M.tk.Toplevel(parent)
    dialog.title("Ruční výrobky, ceny a zákaznické slevy")
    dialog.transient(parent)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 1450, 820)
    outer = M.ttk.Frame(dialog, padding=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(3, weight=1)
    M.ttk.Label(outer, text="Ruční výrobky a obchodní podmínky", font=("Calibri", 17, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        outer,
        text="Nový výrobek lze založit bez Ceníku. U libovolného výrobku lze nastavit standard produktu a slevy pro společnost nebo konkrétní Akci.",
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))
    query = M.tk.StringVar(value="")
    search = M.ttk.Frame(outer)
    search.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    M.ttk.Label(search, text="Hledat").pack(side="left")
    M.ttk.Entry(search, textvariable=query, width=45).pack(side="left", padx=6)
    status = M.tk.StringVar(value="")
    M.ttk.Label(search, textvariable=status, style="PageSubtitle.TLabel").pack(side="right")
    columns = ("Typ", "Kód", "Výrobek", "Výrobce", "Zařazení", "Ruční nákupní cena", "MJ", "Marže", "Standardní sleva", "Aktivní")
    tree = M.ttk.Treeview(outer, columns=columns, show="headings", selectmode="browse")
    widths = (75, 105, 280, 180, 280, 145, 55, 80, 115, 70)
    for col, width in zip(columns, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=3, column=0, sticky="nsew")
    scroll = M.ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
    scroll.grid(row=3, column=1, sticky="ns")
    tree.configure(yscrollcommand=scroll.set)
    rows = {}
    after = {"id": None}

    def refresh(*_):
        tree.delete(*tree.get_children())
        rows.clear()
        data = _product_rows_for_manager(M, query.get())
        for row in data:
            iid = f"p{row['id']}"
            rows[iid] = dict(row)
            manual_price = row["manual_purchase_unit_price"]
            price_text = "" if manual_price is None else f"{_number(manual_price):,.2f} {row['manual_currency'] or 'CZK'}".replace(",", " ")
            margin = "dědí" if row["default_margin_pct"] is None else f"{_number(row['default_margin_pct']):g} %"
            discount = "dědí" if row["default_discount_pct"] is None else f"{_number(row['default_discount_pct']):g} %"
            placement = row["category_name"] + (f" › {row['subgroup_name']}" if row["subgroup_name"] else "")
            tree.insert("", "end", iid=iid, values=(
                "Ruční" if row["manual_product"] else "Import", row["internal_code"] or "",
                row["internal_name"] or "", row["manufacturer_name"] or "", placement,
                price_text, row["manual_unit"] or "ks", margin, discount,
                "Ano" if row["active"] else "Ne",
            ))
        status.set(f"Výrobků: {len(data)}")

    def schedule(*_):
        if after["id"]:
            try:
                dialog.after_cancel(after["id"])
            except Exception:
                pass
        after["id"] = dialog.after(180, refresh)

    def selected_id():
        selection = tree.selection()
        if not selection:
            return None
        return int(selection[0][1:])

    def saved(_product_id=None):
        try:
            from . import product_catalog
            product_catalog._invalidate(app)
        except Exception:
            pass
        refresh()

    def edit():
        pid = selected_id()
        if not pid:
            return M.messagebox.showinfo("Katalog produktů", "Vyberte výrobek.", parent=dialog)
        open_manual_product_editor(M, app, dialog, pid, saved)

    def discounts():
        pid = selected_id()
        if not pid:
            return M.messagebox.showinfo("Slevy", "Vyberte výrobek.", parent=dialog)
        open_discount_rules(M, app, dialog, pid, saved)

    actions = M.ttk.Frame(outer)
    actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    M.ttk.Button(actions, text="+ Nový ruční výrobek", style="Accent.TButton", command=lambda: open_manual_product_editor(M, app, dialog, None, saved)).pack(side="left")
    M.ttk.Button(actions, text="Upravit výrobek / ruční cenu", command=edit).pack(side="left", padx=5)
    M.ttk.Button(actions, text="Slevy společností a Akcí…", command=discounts).pack(side="left")
    M.ttk.Button(actions, text="Zavřít", command=dialog.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit())
    query.trace_add("write", schedule)
    refresh()
    return dialog


def _patch_product_workspace(M) -> None:
    try:
        from . import product_workspace
    except Exception:
        return
    if getattr(product_workspace, "_turto_customer_pricing_v6340", False):
        return
    product_workspace._catalog_rows = lambda module, scope, query="", manufacturer="", show_inactive=False,
        limit=250, offset=0, sort_mode="Skupina → podskupina → produkt": _catalog_rows_with_manual(
            module, product_workspace, scope, query, manufacturer, show_inactive, limit, offset, sort_mode
        )
    original = product_workspace.build_product_workspace

    @functools.wraps(original)
    def build(M2, app, parent, category_id=None, subgroup_id=None, embedded=False):
        app_root = _root_app(app)
        if not embedded and not getattr(parent, "_turto_manual_pricing_toolbar_v6340", False):
            toolbar = M2.ttk.Frame(parent, padding=(10, 8, 10, 0))
            toolbar.pack(fill="x")
            M2.ttk.Button(
                toolbar, text="+ Nový ruční výrobek", style="Accent.TButton",
                command=lambda: open_manual_product_editor(M2, app_root, parent),
            ).pack(side="left")
            M2.ttk.Button(
                toolbar, text="Ruční ceny a zákaznické slevy…",
                command=lambda: open_manual_products_manager(M2, app_root, parent),
            ).pack(side="left", padx=5)
            M2.ttk.Label(
                toolbar,
                text="Cena z Ceníku má přednost; ruční cena je záloha. Sleva: Akce → společnost → standard.",
                style="PageSubtitle.TLabel",
            ).pack(side="right")
            parent._turto_manual_pricing_toolbar_v6340 = True
        return original(M2, app, parent, category_id, subgroup_id, embedded)

    product_workspace.build_product_workspace = build
    product_workspace._turto_customer_pricing_v6340 = True


def install(module) -> None:
    if getattr(module, "_turto_customer_pricing_v6340", False):
        return
    old_ensure = module.ensure_schema

    def ensure_schema():
        old_ensure()
        ensure_customer_pricing_schema(module)

    module.ensure_schema = ensure_schema
    module.ensure_customer_pricing_schema = lambda: ensure_customer_pricing_schema(module)
    module.resolve_customer_product_pricing = lambda product_id, company_id=None, action_id=None, as_of=None: (
        resolve_product_pricing(module, product_id, company_id, action_id, as_of)
    )
    module.apply_customer_pricing = lambda payload, force=False: apply_pricing_to_document_payload(module, payload, force)
    module.open_manual_products_manager = lambda app, parent=None: open_manual_products_manager(
        module, _root_app(app), parent or app
    )
    _patch_product_workspace(module)
    _patch_issued_offer_persistence(module)
    _patch_catalog_pickers(module)
    module._turto_customer_pricing_v6340 = True


__all__ = [
    "install", "ensure_customer_pricing_schema", "save_manual_product",
    "product_pricing", "resolve_product_pricing", "save_discount_rule",
    "delete_discount_rule", "list_discount_rules", "apply_pricing_to_document_payload",
    "open_manual_product_editor", "open_manual_products_manager", "open_discount_rules",
]
