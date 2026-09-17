"""Independent company roles; additive migration and checked selections."""
from __future__ import annotations

ROLES = {"customer": "is_customer", "supplier": "is_supplier"}


def ensure_columns(con):
    columns = {row[1] for row in con.execute("PRAGMA table_info(companies)")}
    for name, default in (("is_customer", 1), ("is_supplier", 0)):
        if name not in columns:
            con.execute(f"ALTER TABLE companies ADD COLUMN {name} INTEGER NOT NULL DEFAULT {default}")


def choices(con, role):
    column = ROLES[role]
    return con.execute(f"""SELECT id,official_name FROM companies
        WHERE active=1 AND {column}=1 AND trim(coalesce(official_name,''))<>''
        ORDER BY official_name COLLATE CZECH,id""").fetchall()


def resolve(con, name, role, payload=None, original_id=None):
    """An autocomplete payload is useful only while its text and role still match."""
    name = str(name or "").strip().casefold()
    if not name:
        return None
    for candidate in (payload, original_id):
        if candidate:
            row = con.execute("SELECT * FROM companies WHERE id=?", (candidate,)).fetchone()
            if row and str(row["official_name"] or "").strip().casefold() == name:
                if candidate == original_id or (row["active"] and row[ROLES[role]]):
                    return int(row["id"])
    matches = [row["id"] for row in choices(con, role)
               if str(row["official_name"]).strip().casefold() == name]
    return int(matches[0]) if len(matches) == 1 else None


def require(con, company_id, role, original_id=None, optional=False):
    if company_id is None and optional:
        return
    if company_id and company_id == original_id:
        return  # Preserve a historical assignment; never infer a role from it.
    column = ROLES[role]
    row = con.execute(f"SELECT active,{column} FROM companies WHERE id=?", (company_id,)).fetchone()
    if not row or not row["active"] or not row[column]:
        label = "odběratel" if role == "customer" else "dodavatel"
        raise ValueError(f"Vyberte aktivní společnost označenou jako {label} v Adresáři.")


def validate_request(con, values, original=None):
    original = dict(original or {})
    require(con, values.get("company_id"), "supplier", original.get("company_id"))
    require(con, values.get("requested_for_company_id"), "customer",
            original.get("requested_for_company_id"), optional=True)
