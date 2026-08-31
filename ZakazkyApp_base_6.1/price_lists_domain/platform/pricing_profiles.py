"""Manual catalogue products and customer-specific pricing rules.

This module owns manually entered catalogue data and the deterministic discount
precedence used by issued offers. Imported price lists remain the first source
of purchase prices; a manually entered purchase price is a safe fallback only.

Discount precedence for a catalogue product is:

1. specific Akce (project) for the selected customer,
2. specific Příležitost for the selected customer,
3. customer default,
4. product-group/subgroup default.

An explicit edit of an offer line is stored as a line override and is never
silently replaced by a later customer/context change.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import categories, product_catalog

SCOPE_COMPANY = "company"
SCOPE_ACTION = "action"
SCOPE_PROJECT = "project"
SCOPE_LABELS = {
    SCOPE_COMPANY: "Společnost",
    SCOPE_ACTION: "Příležitost",
    SCOPE_PROJECT: "Akce",
}


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _company_name_expr(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"coalesce(nullif(trim({prefix}official_name),''),nullif(trim({prefix}short_name),''),'')"


def list_companies(M) -> list[tuple[int, str]]:
    with M.db() as con:
        rows = con.execute(
            f"""SELECT id,{_company_name_expr()} name FROM companies
                WHERE coalesce(active,1)=1
                ORDER BY name COLLATE CZECH,id"""
        ).fetchall()
    return [(int(row["id"]), str(row["name"] or "")) for row in rows]


def list_actions(M, company_id=None) -> list[tuple[int, str, int | None]]:
    with M.db() as con:
        cols = _columns(con, "actions")
        archived = "AND coalesce(a.archived,0)=0" if "archived" in cols else ""
        project_expr = "a.project_id" if "project_id" in cols else "NULL"
        rows = con.execute(
            f"""SELECT a.id,a.name,{project_expr} project_id
                FROM actions a
                WHERE coalesce(a.status,'') NOT IN ('Hotovo','Zrušeno')
                  AND (? IS NULL OR a.company_id=? OR a.company_id IS NULL)
                  {archived}
                ORDER BY a.name COLLATE CZECH,a.id""",
            (company_id, company_id),
        ).fetchall()
    return [
        (int(row["id"]), str(row["name"] or ""), int(row["project_id"]) if row["project_id"] else None)
        for row in rows
    ]


def list_projects(M) -> list[tuple[int, str]]:
    with M.db() as con:
        cols = _columns(con, "projects")
        active = "WHERE coalesce(active,1)=1" if "active" in cols else ""
        rows = con.execute(f"SELECT id,name FROM projects {active} ORDER BY name COLLATE CZECH,id").fetchall()
    return [(int(row["id"]), str(row["name"] or "")) for row in rows]


def product_row(M, product_id: int) -> dict[str, Any] | None:
    with M.db() as con:
        row = con.execute(
            """SELECT p.*,
                      coalesce(group_concat(DISTINCT s.supplier_name),'') suppliers,
                      max(CASE WHEN lower(coalesce(s.source_kind,''))='manual' THEN s.supplier_company_id END) manual_supplier_company_id,
                      max(CASE WHEN lower(coalesce(s.source_kind,''))='manual' THEN s.supplier_product_code END) manual_supplier_code,
                      max(CASE WHEN lower(coalesce(s.source_kind,''))='manual' THEN s.source_name END) manual_source_name
               FROM catalog_products p
               LEFT JOIN catalog_product_sources s ON s.product_id=p.id
               WHERE p.id=? GROUP BY p.id""",
            (int(product_id),),
        ).fetchone()
    return dict(row) if row else None


def _validate_internal_code(con, code: str, product_id=None) -> None:
    if not code:
        return
    row = con.execute(
        """SELECT id FROM catalog_products
           WHERE lower(trim(internal_code))=lower(trim(?)) AND (? IS NULL OR id<>?) LIMIT 1""",
        (code, product_id, product_id),
    ).fetchone()
    if row:
        raise ValueError("Tento interní kód už používá jiný produkt.")


def _manual_source_values(M, supplier_company_id, supplier_name: str) -> tuple[int | None, str]:
    sid = int(supplier_company_id) if supplier_company_id else None
    name = str(supplier_name or "").strip()
    if sid:
        with M.db() as con:
            row = con.execute(
                f"SELECT {_company_name_expr()} name FROM companies WHERE id=?", (sid,)
            ).fetchone()
        if row and str(row["name"] or "").strip():
            name = str(row["name"]).strip()
    return sid, name


def _upsert_manual_source(
    M, con, product_id: int, supplier_company_id=None, supplier_name="",
    supplier_product_code="", source_name="",
) -> None:
    code = str(supplier_product_code or "").strip()
    source_name = str(source_name or "").strip()
    sid, supplier_name = _manual_source_values(M, supplier_company_id, supplier_name)
    existing = con.execute(
        """SELECT id,source_key FROM catalog_product_sources
           WHERE product_id=? AND lower(coalesce(source_kind,''))='manual'
           ORDER BY id LIMIT 1""",
        (int(product_id),),
    ).fetchone()
    if not code:
        if existing:
            con.execute("DELETE FROM catalog_product_sources WHERE id=?", (int(existing["id"]),))
        return
    identity = product_catalog._product_identity(code, code, source_name)
    if not identity:
        raise ValueError("Dodavatelský kód nelze použít jako identitu produktu.")
    supplier_norm = product_catalog._norm(supplier_name)
    key = product_catalog._source_key(sid, supplier_norm, identity)
    collision = con.execute(
        "SELECT product_id FROM catalog_product_sources WHERE source_key=?", (key,)
    ).fetchone()
    if collision and int(collision["product_id"]) != int(product_id):
        raise ValueError(
            "Stejný dodavatel a dodavatelský kód už jsou propojené s jiným produktem. "
            "Použijte existující produkt nebo jiný kód."
        )
    if existing:
        con.execute(
            """UPDATE catalog_product_sources SET
                   supplier_company_id=?,supplier_name=?,supplier_name_norm=?,source_key=?,
                   product_identity=?,supplier_product_code=?,source_name=?,source_kind='manual',
                   last_seen_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                sid, supplier_name, supplier_norm, key, identity, code,
                source_name, int(existing["id"]),
            ),
        )
    else:
        con.execute(
            """INSERT INTO catalog_product_sources(
                   product_id,supplier_company_id,supplier_name,supplier_name_norm,source_key,
                   product_identity,supplier_product_code,source_name,source_kind,last_seen_at
               ) VALUES(?,?,?,?,?,?,?,?, 'manual',CURRENT_TIMESTAMP)""",
            (int(product_id), sid, supplier_name, supplier_norm, key, identity, code, source_name),
        )


def save_manual_product(M, values: dict[str, Any], product_id=None) -> int:
    data = dict(values or {})
    name = str(data.get("internal_name") or "").strip()
    if not name:
        raise ValueError("Vyplňte interní označení výrobku.")
    code = str(data.get("internal_code") or "").strip()
    manufacturer = str(data.get("manufacturer_name") or "").strip()
    category_id = int(data["category_id"]) if data.get("category_id") else None
    subgroup_id = int(data["subgroup_id"]) if data.get("subgroup_id") else None
    if subgroup_id:
        category_id = categories.subgroup_parent_id(M, subgroup_id)
        if not category_id:
            raise ValueError("Vybraná podskupina už neexistuje.")
    purchase = max(0.0, _number(data.get("manual_purchase_price")))
    currency = str(data.get("manual_purchase_currency") or "CZK").strip().upper() or "CZK"
    unit = str(data.get("manual_unit") or "ks").strip() or "ks"
    vat = max(0.0, _number(data.get("default_vat_rate"), 21.0))
    note = str(data.get("manual_price_note") or "").strip()
    active = 1 if data.get("active", True) else 0
    supplier_company_id = int(data["supplier_company_id"]) if data.get("supplier_company_id") else None
    supplier_name = str(data.get("supplier_name") or "").strip()
    supplier_code = str(data.get("supplier_product_code") or "").strip()
    source_name = str(data.get("source_name") or name).strip()

    with M.db() as con:
        _validate_internal_code(con, code, int(product_id) if product_id else None)
        if product_id:
            if not con.execute("SELECT id FROM catalog_products WHERE id=?", (int(product_id),)).fetchone():
                raise ValueError("Produkt už v katalogu neexistuje.")
            con.execute(
                """UPDATE catalog_products SET
                       manufacturer_company_id=coalesce(?,manufacturer_company_id),
                       manufacturer_name=?,internal_code=?,internal_name=?,category_id=?,subgroup_id=?,
                       manual_product=CASE WHEN manual_product=1 THEN 1 ELSE manual_product END,
                       manual_purchase_price=?,manual_purchase_currency=?,manual_unit=?,default_vat_rate=?,
                       manual_price_note=?,manual_price_updated_at=CURRENT_TIMESTAMP,active=?,updated_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (
                    supplier_company_id, manufacturer, code, name, category_id, subgroup_id,
                    purchase, currency, unit, vat, note, active, int(product_id),
                ),
            )
            result = int(product_id)
        else:
            result = int(con.execute(
                """INSERT INTO catalog_products(
                       manufacturer_company_id,manufacturer_name,internal_code,internal_name,
                       category_id,subgroup_id,manual_product,manual_purchase_price,
                       manual_purchase_currency,manual_unit,default_vat_rate,manual_price_note,
                       manual_price_updated_at,active,updated_at
                   ) VALUES(?,?,?,?,?,?,1,?,?,?,?,?,CURRENT_TIMESTAMP,?,CURRENT_TIMESTAMP)""",
                (
                    supplier_company_id, manufacturer, code, name, category_id, subgroup_id,
                    purchase, currency, unit, vat, note, active,
                ),
            ).lastrowid)
        _upsert_manual_source(
            M, con, result, supplier_company_id, supplier_name,
            supplier_code, source_name,
        )
        # Stable catalogue identity is propagated to every linked commercial row.
        for table in ("price_list_items", "supplier_offer_items", "business_document_items"):
            cols = _columns(con, table)
            if {"catalog_product_id", "category_id", "subgroup_id"}.issubset(cols):
                con.execute(
                    f"UPDATE {table} SET category_id=?,subgroup_id=? WHERE catalog_product_id=?",
                    (category_id, subgroup_id, result),
                )
    return result


def list_discount_rules(M, product_id: int) -> list[dict[str, Any]]:
    with M.db() as con:
        rows = con.execute(
            f"""SELECT r.*,{_company_name_expr('c')} company_name,
                       coalesce(a.name,'') action_name,coalesce(p.name,'') project_name
                FROM catalog_product_discount_rules r
                JOIN companies c ON c.id=r.company_id
                LEFT JOIN actions a ON a.id=r.action_id
                LEFT JOIN projects p ON p.id=r.project_id
                WHERE r.catalog_product_id=?
                ORDER BY r.active DESC,
                         CASE WHEN r.project_id IS NOT NULL THEN 0
                              WHEN r.action_id IS NOT NULL THEN 1 ELSE 2 END,
                         company_name COLLATE CZECH,project_name COLLATE CZECH,
                         action_name COLLATE CZECH,r.id""",
            (int(product_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def save_discount_rule(
    M, product_id: int, company_id: int, discount_pct: Any, *,
    action_id=None, project_id=None, note: str = "", active: bool = True, rule_id=None,
) -> int:
    product_id = int(product_id)
    company_id = int(company_id)
    action_id = int(action_id) if action_id else None
    project_id = int(project_id) if project_id else None
    if action_id and project_id:
        raise ValueError("Pravidlo může být buď pro Příležitost, nebo pro Akci, ne pro obojí současně.")
    discount = _number(discount_pct)
    if not 0 <= discount <= 100:
        raise ValueError("Sleva musí být v rozsahu 0 až 100 %.")
    with M.db() as con:
        if not con.execute("SELECT id FROM catalog_products WHERE id=?", (product_id,)).fetchone():
            raise ValueError("Produkt už v katalogu neexistuje.")
        if not con.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone():
            raise ValueError("Vybraná společnost už neexistuje.")
        if action_id:
            action = con.execute("SELECT company_id FROM actions WHERE id=?", (action_id,)).fetchone()
            if not action:
                raise ValueError("Vybraná Příležitost už neexistuje.")
            if action["company_id"] and int(action["company_id"]) != company_id:
                raise ValueError("Vybraná Příležitost patří jiné společnosti.")
        if project_id and not con.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("Vybraná Akce už neexistuje.")

        if rule_id:
            existing = con.execute(
                "SELECT id FROM catalog_product_discount_rules WHERE id=? AND catalog_product_id=?",
                (int(rule_id), product_id),
            ).fetchone()
            if not existing:
                raise ValueError("Pravidlo slevy už neexistuje.")
            try:
                con.execute(
                    """UPDATE catalog_product_discount_rules SET
                           company_id=?,action_id=?,project_id=?,discount_pct=?,note=?,active=?,
                           updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (company_id, action_id, project_id, discount, str(note or "").strip(), 1 if active else 0, int(rule_id)),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ValueError("Pro tento produkt a zvolený rozsah už pravidlo existuje.") from exc
                raise
            return int(rule_id)

        query = """SELECT id FROM catalog_product_discount_rules
                   WHERE catalog_product_id=? AND company_id=?
                     AND action_id IS ? AND project_id IS ? LIMIT 1"""
        existing = con.execute(query, (product_id, company_id, action_id, project_id)).fetchone()
        if existing:
            con.execute(
                """UPDATE catalog_product_discount_rules SET discount_pct=?,note=?,active=?,
                       updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (discount, str(note or "").strip(), 1 if active else 0, int(existing["id"])),
            )
            return int(existing["id"])
        return int(con.execute(
            """INSERT INTO catalog_product_discount_rules(
                   catalog_product_id,company_id,action_id,project_id,discount_pct,note,active
               ) VALUES(?,?,?,?,?,?,?)""",
            (product_id, company_id, action_id, project_id, discount, str(note or "").strip(), 1 if active else 0),
        ).lastrowid)


def delete_discount_rule(M, rule_id: int, product_id=None) -> None:
    with M.db() as con:
        if product_id:
            con.execute(
                "DELETE FROM catalog_product_discount_rules WHERE id=? AND catalog_product_id=?",
                (int(rule_id), int(product_id)),
            )
        else:
            con.execute("DELETE FROM catalog_product_discount_rules WHERE id=?", (int(rule_id),))


def resolve_discount(
    M, product_id: int, *, company_id=None, action_id=None, project_id=None,
    standard_discount_pct: Any = 0,
) -> dict[str, Any]:
    product_id = int(product_id)
    company_id = int(company_id) if company_id else None
    action_id = int(action_id) if action_id else None
    project_id = int(project_id) if project_id else None
    standard = _number(standard_discount_pct)
    with M.db() as con:
        table_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_product_discount_rules'"
        ).fetchone()
        if not table_exists:
            row = None
        elif action_id and not company_id:
            action_row = con.execute("SELECT company_id FROM actions WHERE id=?", (action_id,)).fetchone()
            if action_row and action_row["company_id"]:
                company_id = int(action_row["company_id"])
            row = None
        else:
            row = None
        if table_exists and company_id:
            row = con.execute(
                f"""SELECT r.*,{_company_name_expr('c')} company_name,
                           coalesce(a.name,'') action_name,coalesce(p.name,'') project_name,
                           CASE WHEN r.project_id IS NOT NULL THEN 1
                                WHEN r.action_id IS NOT NULL THEN 2 ELSE 3 END priority
                    FROM catalog_product_discount_rules r
                    JOIN companies c ON c.id=r.company_id
                    LEFT JOIN actions a ON a.id=r.action_id
                    LEFT JOIN projects p ON p.id=r.project_id
                    WHERE r.catalog_product_id=? AND r.company_id=? AND r.active=1
                      AND ((? IS NOT NULL AND r.project_id=?)
                        OR (? IS NOT NULL AND r.action_id=?)
                        OR (r.action_id IS NULL AND r.project_id IS NULL))
                    ORDER BY priority,r.updated_at DESC,r.id DESC LIMIT 1""",
                (product_id, company_id, project_id, project_id, action_id, action_id),
            ).fetchone()
        else:
            row = None
    if row:
        scope = SCOPE_PROJECT if row["project_id"] else SCOPE_ACTION if row["action_id"] else SCOPE_COMPANY
        target = str(row["project_name"] or row["action_name"] or row["company_name"] or "").strip()
        source = f"{SCOPE_LABELS[scope]}: {target}" if target else SCOPE_LABELS[scope]
        return {
            "discount_pct": _number(row["discount_pct"]),
            "standard_discount_pct": standard,
            "source": source,
            "scope": scope,
            "rule_id": int(row["id"]),
            "company_id": company_id,
            "action_id": int(row["action_id"]) if row["action_id"] else None,
            "project_id": int(row["project_id"]) if row["project_id"] else None,
        }
    return {
        "discount_pct": standard,
        "standard_discount_pct": standard,
        "source": "Standard skupiny / podskupiny",
        "scope": "standard",
        "rule_id": None,
        "company_id": company_id,
        "action_id": action_id,
        "project_id": project_id,
    }


def apply_context_to_item(
    M, item: dict[str, Any], *, company_id=None, action_id=None, project_id=None,
    force: bool = False,
) -> tuple[dict[str, Any], bool]:
    result = dict(item or {})
    product_id = result.get("catalog_product_id")
    if not product_id:
        return result, False
    if result.get("discount_manual_override") and not force:
        return result, False
    policy = product_catalog.pricing_policy(M, result.get("category_id"), result.get("subgroup_id"))
    standard = result.get("standard_discount_pct")
    if standard in (None, ""):
        standard = policy["discount_pct"]
    resolved = resolve_discount(
        M, int(product_id), company_id=company_id, action_id=action_id,
        project_id=project_id, standard_discount_pct=standard,
    )
    purchase = _number(result.get("purchase_unit_price"))
    margin = _number(result.get("margin_pct"), policy["margin_pct"])
    recommended, final = product_catalog.calculate_prices(purchase, margin, resolved["discount_pct"])
    result.update(
        margin_pct=margin,
        recommended_unit_price=recommended,
        standard_discount_pct=resolved["standard_discount_pct"],
        discount_pct=resolved["discount_pct"],
        unit_price=final,
        total_price=_number(result.get("quantity"), 1.0) * final,
        discount_source_snapshot=resolved["source"],
        discount_rule_id=resolved["rule_id"],
        discount_manual_override=0,
        pricing_company_id_snapshot=company_id,
        pricing_action_id_snapshot=action_id,
        pricing_project_id_snapshot=project_id,
    )
    return result, True


def _invalidate(app) -> None:
    if app is None:
        return
    for name in ("_price_filter_cache", "_price_taxonomy_cache", "_commercial_price_summary_cache"):
        try:
            setattr(app, name, None)
        except Exception:
            pass
    try:
        dirty = set(getattr(app, "_turto_dirty_pages", set()))
        dirty.update(("pricelists", "offers", "issued_offers"))
        app._turto_dirty_pages = dirty
    except Exception:
        pass


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


def open_product_dialog(M, app, parent, product_id=None, defaults=None):
    """Create or edit a persistent catalogue product, including a manual price fallback."""
    app = _root_app(app)
    row = product_row(M, int(product_id)) if product_id else None
    values = dict(defaults or {})
    if row:
        values.update(row)
    win = M.tk.Toplevel(parent)
    win.title("Nový výrobek v katalogu" if not product_id else "Výrobek v katalogu")
    win.transient(parent)
    win.grab_set()
    M.enable_dialog_maximize(win, 980, 760)
    frame = M.scrollable_dialog_frame(win, 16)
    frame.columnconfigure(1, weight=1)

    internal_code = M.tk.StringVar(value=str(values.get("internal_code") or ""))
    internal_name = M.tk.StringVar(value=str(values.get("internal_name") or ""))
    manufacturer = M.tk.StringVar(value=str(values.get("manufacturer_name") or ""))
    purchase = M.tk.StringVar(value=str(values.get("manual_purchase_price") or "").replace(".", ","))
    currency = M.tk.StringVar(value=str(values.get("manual_purchase_currency") or "CZK"))
    unit = M.tk.StringVar(value=str(values.get("manual_unit") or "ks"))
    vat = M.tk.StringVar(value=str(values.get("default_vat_rate") if values.get("default_vat_rate") is not None else 21).replace(".", ","))
    active = M.tk.BooleanVar(value=bool(values.get("active", 1)))

    company_rows = list_companies(M)
    company_map = {"— bez vazby na dodavatele —": None, **{name: cid for cid, name in company_rows}}
    selected_supplier_id = values.get("manual_supplier_company_id")
    supplier_name_value = next((name for name, cid in company_map.items() if cid == selected_supplier_id), "— bez vazby na dodavatele —")
    supplier = M.tk.StringVar(value=supplier_name_value)
    supplier_code = M.tk.StringVar(value=str(values.get("manual_supplier_code") or ""))
    source_name = M.tk.StringVar(value=str(values.get("manual_source_name") or values.get("internal_name") or ""))

    groups = categories.list_categories(M)
    group_map = {categories.UNASSIGNED: None, **{str(item["name"]): int(item["id"]) for item in groups}}
    group = M.tk.StringVar(value=categories.category_name(M, values.get("category_id")) or categories.UNASSIGNED)
    subgroup = M.tk.StringVar(value=categories.subgroup_name(M, values.get("subgroup_id")) or categories.NO_SUBGROUP)
    subgroup_map = {categories.NO_SUBGROUP: None}

    intro = (
        "Výrobek bude uložen trvale v interním katalogu a lze jej ihned použít ve Vydaných nabídkách. "
        "Ručně zadaná nákupní cena se použije jen tehdy, když není dostupná platná cena z Ceníku nebo Přijaté nabídky."
    )
    M.ttk.Label(frame, text=intro, style="PageSubtitle.TLabel", wraplength=850, justify="left").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
    )
    fields = [
        ("Interní kód", internal_code, "entry"),
        ("Interní označení *", internal_name, "entry"),
        ("Výrobce", manufacturer, "entry"),
        ("Ručně zadaná nákupní cena / MJ", purchase, "entry"),
        ("Měna", currency, "currency"),
        ("Měrná jednotka", unit, "entry"),
        ("DPH [%]", vat, "entry"),
        ("Produktová skupina", group, "group"),
        ("Podskupina", subgroup, "subgroup"),
        ("Dodavatel pro budoucí propojení", supplier, "supplier"),
        ("Dodavatelský kód", supplier_code, "entry"),
        ("Dodavatelské označení", source_name, "entry"),
    ]
    widgets = {}
    for offset, (label, variable, kind) in enumerate(fields, 1):
        M.ttk.Label(frame, text=label).grid(row=offset, column=0, sticky="w", padx=(0, 10), pady=5)
        if kind == "currency":
            widget = M.safe_combobox(frame, textvariable=variable, values=["CZK", "EUR", "PLN"], state="readonly")
        elif kind == "group":
            widget = M.safe_combobox(frame, textvariable=variable, values=list(group_map), state="readonly")
        elif kind == "subgroup":
            widget = M.safe_combobox(frame, textvariable=variable, values=[categories.NO_SUBGROUP], state="readonly")
        elif kind == "supplier":
            widget = M.safe_combobox(frame, textvariable=variable, values=list(company_map), state="readonly")
        else:
            widget = M.ttk.Entry(frame, textvariable=variable)
        widget.grid(row=offset, column=1, sticky="ew", pady=5)
        widgets[kind] = widget

    note_row = len(fields) + 1
    M.ttk.Label(frame, text="Poznámka k ruční ceně").grid(row=note_row, column=0, sticky="nw", padx=(0, 10), pady=5)
    note = M.tk.Text(frame, height=4, wrap="word", font=("Calibri", 11))
    note.grid(row=note_row, column=1, sticky="ew", pady=5)
    note.insert("1.0", str(values.get("manual_price_note") or ""))
    M.ttk.Checkbutton(frame, text="Aktivní výrobek", variable=active).grid(
        row=note_row + 1, column=0, columnspan=2, sticky="w", pady=(7, 2)
    )
    result = {"id": None}

    def refresh_subgroups(*_):
        nonlocal subgroup_map
        category_id = group_map.get(group.get())
        subgroup_map = {
            categories.NO_SUBGROUP: None,
            **{str(item["name"]): int(item["id"]) for item in categories.list_subgroups(M, category_id)},
        }
        widgets["subgroup"].configure(values=list(subgroup_map))
        if subgroup.get() not in subgroup_map:
            subgroup.set(categories.NO_SUBGROUP)

    group.trace_add("write", refresh_subgroups)
    refresh_subgroups()
    current_subgroup = categories.subgroup_name(M, values.get("subgroup_id"))
    if current_subgroup in subgroup_map:
        subgroup.set(current_subgroup)

    def save(open_rules=False):
        try:
            pid = save_manual_product(M, {
                "internal_code": internal_code.get(),
                "internal_name": internal_name.get(),
                "manufacturer_name": manufacturer.get(),
                "manual_purchase_price": purchase.get(),
                "manual_purchase_currency": currency.get(),
                "manual_unit": unit.get(),
                "default_vat_rate": vat.get(),
                "manual_price_note": note.get("1.0", "end-1c"),
                "active": active.get(),
                "category_id": group_map.get(group.get()),
                "subgroup_id": subgroup_map.get(subgroup.get()),
                "supplier_company_id": company_map.get(supplier.get()),
                "supplier_name": supplier.get() if company_map.get(supplier.get()) is None else "",
                "supplier_product_code": supplier_code.get(),
                "source_name": source_name.get(),
            }, product_id=product_id)
        except Exception as exc:
            return M.messagebox.showwarning("Katalog produktů", str(exc), parent=win)
        result["id"] = pid
        _invalidate(app)
        win.destroy()
        if open_rules:
            open_discount_rules_dialog(M, app, parent, pid)

    buttons = M.ttk.Frame(frame)
    buttons.grid(row=note_row + 2, column=0, columnspan=2, sticky="e", pady=(14, 0))
    M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=lambda: save(False)).pack(side="right", padx=(0, 6))
    M.ttk.Button(buttons, text="Uložit a nastavit slevy…", command=lambda: save(True)).pack(side="right", padx=(0, 6))
    try:
        M.center_dialog(win, parent)
    except Exception:
        pass
    win.wait_window()
    return result["id"]


class _RuleEditor:
    def __init__(self, M, parent, product_id: int, row=None, preselect=None):
        self.M = M
        self.product_id = int(product_id)
        self.row = dict(row or {})
        self.result = None
        preselect = dict(preselect or {})
        self.win = M.tk.Toplevel(parent)
        self.win.title("Pravidlo slevy")
        self.win.transient(parent)
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 760, 520)
        frame = M.ttk.Frame(self.win, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        companies = list_companies(M)
        self.company_map = {name: cid for cid, name in companies}
        company_id = self.row.get("company_id") or preselect.get("company_id")
        company_name = next((name for name, cid in self.company_map.items() if cid == company_id), next(iter(self.company_map), ""))
        self.company = M.tk.StringVar(value=company_name)
        if self.row.get("project_id") or preselect.get("project_id"):
            scope = SCOPE_PROJECT
        elif self.row.get("action_id") or preselect.get("action_id"):
            scope = SCOPE_ACTION
        else:
            scope = SCOPE_COMPANY
        self.scope = M.tk.StringVar(value=SCOPE_LABELS[scope])
        self.target = M.tk.StringVar(value="")
        self.discount = M.tk.StringVar(value=str(self.row.get("discount_pct") if self.row else preselect.get("discount_pct", "")).replace(".", ","))
        self.active = M.tk.BooleanVar(value=bool(self.row.get("active", 1)))
        self.target_map = {}

        M.ttk.Label(frame, text="Společnost").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=5)
        company_box = M.safe_combobox(frame, textvariable=self.company, values=list(self.company_map), state="readonly")
        company_box.grid(row=0, column=1, sticky="ew", pady=5)
        M.ttk.Label(frame, text="Rozsah pravidla").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=5)
        scope_box = M.safe_combobox(frame, textvariable=self.scope, values=list(SCOPE_LABELS.values()), state="readonly")
        scope_box.grid(row=1, column=1, sticky="ew", pady=5)
        M.ttk.Label(frame, text="Příležitost / Akce").grid(row=2, column=0, sticky="w", padx=(0, 10), pady=5)
        target_box = M.safe_combobox(frame, textvariable=self.target, values=["—"], state="readonly")
        target_box.grid(row=2, column=1, sticky="ew", pady=5)
        M.ttk.Label(frame, text="Sleva [%]").grid(row=3, column=0, sticky="w", padx=(0, 10), pady=5)
        M.ttk.Entry(frame, textvariable=self.discount).grid(row=3, column=1, sticky="ew", pady=5)
        M.ttk.Label(frame, text="Poznámka").grid(row=4, column=0, sticky="nw", padx=(0, 10), pady=5)
        self.note = M.tk.Text(frame, height=5, wrap="word", font=("Calibri", 11))
        self.note.grid(row=4, column=1, sticky="ew", pady=5)
        self.note.insert("1.0", str(self.row.get("note") or ""))
        M.ttk.Checkbutton(frame, text="Pravidlo je aktivní", variable=self.active).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=5
        )
        hint = (
            "Při sestavení nabídky má pravidlo pro Akci přednost před Příležitostí a ta před standardem společnosti. "
            "Ruční úprava konkrétního řádku nabídky zůstává nedotčena."
        )
        M.ttk.Label(frame, text=hint, style="PageSubtitle.TLabel", wraplength=650, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(7, 2)
        )

        reverse_scope = {label: key for key, label in SCOPE_LABELS.items()}

        def refresh_target(*_):
            scope_key = reverse_scope.get(self.scope.get(), SCOPE_COMPANY)
            company_id_value = self.company_map.get(self.company.get())
            if scope_key == SCOPE_ACTION:
                rows = list_actions(M, company_id_value)
                self.target_map = {name: aid for aid, name, _pid in rows}
                existing_id = self.row.get("action_id") or preselect.get("action_id")
            elif scope_key == SCOPE_PROJECT:
                rows = list_projects(M)
                self.target_map = {name: pid for pid, name in rows}
                existing_id = self.row.get("project_id") or preselect.get("project_id")
            else:
                self.target_map = {"— pravidlo pro celou společnost —": None}
                existing_id = None
            target_box.configure(values=list(self.target_map))
            existing_name = next((name for name, rid in self.target_map.items() if rid == existing_id), None)
            if existing_name:
                self.target.set(existing_name)
            elif self.target.get() not in self.target_map:
                self.target.set(next(iter(self.target_map), ""))
            target_box.state(["disabled"] if scope_key == SCOPE_COMPANY else ["!disabled", "readonly"])

        self.company.trace_add("write", refresh_target)
        self.scope.trace_add("write", refresh_target)
        refresh_target()

        def save():
            company_id_value = self.company_map.get(self.company.get())
            if not company_id_value:
                return M.messagebox.showwarning("Slevy", "Vyberte společnost.", parent=self.win)
            scope_key = reverse_scope.get(self.scope.get(), SCOPE_COMPANY)
            target_id = self.target_map.get(self.target.get())
            if scope_key != SCOPE_COMPANY and not target_id:
                return M.messagebox.showwarning("Slevy", "Vyberte Příležitost nebo Akci.", parent=self.win)
            try:
                rule_id = save_discount_rule(
                    M, self.product_id, company_id_value, self.discount.get(),
                    action_id=target_id if scope_key == SCOPE_ACTION else None,
                    project_id=target_id if scope_key == SCOPE_PROJECT else None,
                    note=self.note.get("1.0", "end-1c"), active=self.active.get(),
                    rule_id=self.row.get("id"),
                )
            except Exception as exc:
                return M.messagebox.showwarning("Slevy", str(exc), parent=self.win)
            self.result = rule_id
            self.win.destroy()

        buttons = M.ttk.Frame(frame)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))
        M.ttk.Button(buttons, text="Zrušit", command=self.win.destroy).pack(side="right")
        M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 6))
        self.win.wait_window()


def open_discount_rules_dialog(
    M, app, parent, product_id: int, *, company_id=None, action_id=None, project_id=None,
):
    app = _root_app(app)
    product = product_row(M, int(product_id))
    if not product:
        return None
    win = M.tk.Toplevel(parent)
    win.title("Slevy podle odběratele a Akce")
    win.transient(parent)
    win.grab_set()
    M.enable_dialog_maximize(win, 1150, 680)
    outer = M.ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(2, weight=1)
    M.ttk.Label(
        outer,
        text=str(product.get("internal_name") or product.get("internal_code") or "Výrobek"),
        font=("Calibri", 16, "bold"),
    ).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        outer,
        text=("Standardní sleva pochází ze skupiny nebo podskupiny. Zde nastavíte odchylku pro konkrétního "
              "odběratele, Příležitost nebo Akci. Nabídky si použitou slevu uloží jako historický snímek."),
        style="PageSubtitle.TLabel", wraplength=1000, justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(3, 8))
    columns = ("Rozsah", "Společnost", "Příležitost / Akce", "Sleva", "Poznámka", "Stav")
    widths = (125, 250, 300, 90, 300, 80)
    wrap = M.ttk.Frame(outer)
    wrap.grid(row=2, column=0, sticky="nsew")
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    tree = M.ttk.Treeview(wrap, columns=columns, show="headings", selectmode="browse")
    for col, width in zip(columns, widths):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w", stretch=False)
    tree.grid(row=0, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    rows = {}

    def refresh(select_id=None):
        for iid in tree.get_children(""):
            tree.delete(iid)
        rows.clear()
        for row in list_discount_rules(M, int(product_id)):
            iid = f"r{row['id']}"
            rows[iid] = row
            scope = SCOPE_PROJECT if row.get("project_id") else SCOPE_ACTION if row.get("action_id") else SCOPE_COMPANY
            target = row.get("project_name") or row.get("action_name") or "—"
            tree.insert(
                "", "end", iid=iid,
                values=(
                    SCOPE_LABELS[scope], row.get("company_name") or "", target,
                    f"{_number(row.get('discount_pct')):g} %", row.get("note") or "",
                    "Aktivní" if row.get("active") else "Neaktivní",
                ),
                tags=() if row.get("active") else ("status_cancel",),
            )
        if select_id and tree.exists(f"r{select_id}"):
            tree.selection_set(f"r{select_id}")
            tree.see(f"r{select_id}")

    def selected():
        iid = next(iter(tree.selection()), None)
        return rows.get(iid) if iid else None

    preselect = {"company_id": company_id, "action_id": action_id, "project_id": project_id}

    def add_rule():
        dialog = _RuleEditor(M, win, int(product_id), preselect=preselect)
        if dialog.result:
            refresh(dialog.result)
            _invalidate(app)

    def edit_rule():
        row = selected()
        if not row:
            return M.messagebox.showinfo("Slevy", "Vyberte pravidlo.", parent=win)
        dialog = _RuleEditor(M, win, int(product_id), row=row)
        if dialog.result:
            refresh(dialog.result)
            _invalidate(app)

    def delete_rule():
        row = selected()
        if not row:
            return
        if not M.messagebox.askyesno(
            "Slevy", "Odstranit vybrané pravidlo? Již uložené nabídky zůstanou beze změny.", parent=win
        ):
            return
        delete_discount_rule(M, int(row["id"]), int(product_id))
        refresh()
        _invalidate(app)

    tools = M.ttk.Frame(outer, style="Panel.TFrame", padding=7)
    tools.grid(row=3, column=0, sticky="ew", pady=(8, 0))
    M.ttk.Button(tools, text="+ Nové pravidlo", style="Accent.TButton", command=add_rule).pack(side="left")
    M.ttk.Button(tools, text="Upravit", command=edit_rule).pack(side="left", padx=4)
    M.ttk.Button(tools, text="Odstranit", command=delete_rule).pack(side="left", padx=4)
    M.ttk.Button(tools, text="Zavřít", command=win.destroy).pack(side="right")
    tree.bind("<Double-1>", lambda _event: edit_rule())
    refresh()
    win.wait_window()
    return True


def install(M) -> None:
    if getattr(M, "_turto_pricing_profiles_v6340", False):
        return
    M.save_manual_catalog_product = lambda values, product_id=None: save_manual_product(M, values, product_id)
    M.resolve_catalog_product_discount = lambda product_id, **kwargs: resolve_discount(M, product_id, **kwargs)
    M.apply_catalog_pricing_context = lambda item, **kwargs: apply_context_to_item(M, item, **kwargs)
    M.open_manual_catalog_product = lambda app, parent, product_id=None, defaults=None: open_product_dialog(
        M, app, parent, product_id, defaults
    )
    M.open_catalog_product_discounts = lambda app, parent, product_id, **kwargs: open_discount_rules_dialog(
        M, app, parent, product_id, **kwargs
    )
    M._turto_pricing_profiles_v6340 = True


__all__ = [
    "SCOPE_COMPANY", "SCOPE_ACTION", "SCOPE_PROJECT", "SCOPE_LABELS",
    "list_companies", "list_actions", "list_projects", "product_row",
    "save_manual_product", "list_discount_rules", "save_discount_rule",
    "delete_discount_rule", "resolve_discount", "apply_context_to_item",
    "open_product_dialog", "open_discount_rules_dialog", "install",
]
