"""Additive SQLite schema for Ceníky."""
from __future__ import annotations
from . import context as ctx
from .common import _norm

def ensure_price_list_schema() -> None:
    with ctx.M.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS price_lists(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_offer_id INTEGER,
              supplier_company_id INTEGER,
              supplier_name TEXT DEFAULT '',
              title TEXT NOT NULL DEFAULT '',
              valid_from TEXT DEFAULT '',
              valid_to TEXT DEFAULT '',
              product_group TEXT DEFAULT '',
              branch TEXT DEFAULT '',
              update_mode TEXT NOT NULL DEFAULT 'partial',
              supersedes_id INTEGER,
              archived INTEGER NOT NULL DEFAULT 0,
              source_hash TEXT NOT NULL DEFAULT '',
              source_filename TEXT DEFAULT '',
              archive_path TEXT DEFAULT '',
              source_type TEXT DEFAULT '',
              currency TEXT DEFAULT 'CZK',
              imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              imported_by TEXT DEFAULT '',
              note TEXT DEFAULT '',
              terms_text TEXT DEFAULT '',
              ocr_text TEXT DEFAULT '',
              ocr_layout_json TEXT DEFAULT '',
              ocr_engine TEXT DEFAULT '',
              parse_status TEXT DEFAULT 'Připraveno',
              FOREIGN KEY(source_offer_id) REFERENCES supplier_offers(id) ON DELETE SET NULL,
              FOREIGN KEY(supplier_company_id) REFERENCES companies(id),
              FOREIGN KEY(supersedes_id) REFERENCES price_lists(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS price_list_files(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              price_list_id INTEGER NOT NULL,
              original_name TEXT NOT NULL DEFAULT '',
              archive_path TEXT NOT NULL DEFAULT '',
              sha256 TEXT NOT NULL DEFAULT '',
              extension TEXT DEFAULT '',
              file_size INTEGER NOT NULL DEFAULT 0,
              is_primary INTEGER NOT NULL DEFAULT 1,
              imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(price_list_id) REFERENCES price_lists(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS price_list_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              price_list_id INTEGER NOT NULL,
              row_no INTEGER DEFAULT 0,
              product_code TEXT DEFAULT '',
              supplier_item_code TEXT DEFAULT '',
              item_key TEXT DEFAULT '',
              name TEXT DEFAULT '',
              description TEXT DEFAULT '',
              unit TEXT DEFAULT '',
              source_price REAL DEFAULT 0,
              currency TEXT DEFAULT 'CZK',
              price_basis_qty REAL DEFAULT 1,
              normalized_unit_price REAL DEFAULT 0,
              discount_pct REAL DEFAULT 0,
              surcharge_pct REAL DEFAULT 0,
              net_price REAL DEFAULT 0,
              minimum_qty REAL DEFAULT 0,
              package_qty REAL DEFAULT 0,
              package_unit TEXT DEFAULT '',
              pallet_qty REAL DEFAULT 0,
              weight_unit REAL DEFAULT 0,
              weight_package REAL DEFAULT 0,
              weight_pallet REAL DEFAULT 0,
              gtin TEXT DEFAULT '',
              customs_code TEXT DEFAULT '',
              dimensions TEXT DEFAULT '',
              condition_text TEXT DEFAULT '',
              source_row_json TEXT DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY(price_list_id) REFERENCES price_lists(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS price_list_item_attributes(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              item_id INTEGER NOT NULL,
              attribute_key TEXT NOT NULL DEFAULT '',
              attribute_value TEXT DEFAULT '',
              attribute_unit TEXT DEFAULT '',
              source TEXT DEFAULT '',
              FOREIGN KEY(item_id) REFERENCES price_list_items(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS price_list_rules(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              price_list_id INTEGER NOT NULL,
              scope_type TEXT DEFAULT 'all',
              scope_value TEXT DEFAULT '',
              rule_type TEXT NOT NULL DEFAULT 'surcharge_pct',
              percent_value REAL DEFAULT 0,
              fixed_value REAL DEFAULT 0,
              currency TEXT DEFAULT 'CZK',
              condition_text TEXT DEFAULT '',
              priority INTEGER DEFAULT 0,
              active INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY(price_list_id) REFERENCES price_lists(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_price_lists_supplier_date
              ON price_lists(supplier_company_id,valid_from,valid_to,archived);
            CREATE INDEX IF NOT EXISTS idx_price_lists_offer ON price_lists(source_offer_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_price_lists_source_hash
              ON price_lists(source_hash) WHERE trim(source_hash)<>'';
            CREATE INDEX IF NOT EXISTS idx_price_list_items_lookup
              ON price_list_items(product_code,item_key,name,price_list_id,active);
            CREATE INDEX IF NOT EXISTS idx_price_list_items_list ON price_list_items(price_list_id,row_no);
            CREATE INDEX IF NOT EXISTS idx_price_list_rules_list ON price_list_rules(price_list_id,active,priority);
            """
        )


def _resolve_company(con, supplier_name: str):
    name = (supplier_name or "").strip()
    if not name:
        return None
    rows = con.execute(
        """SELECT id,official_name,short_name FROM companies
           WHERE active=1 AND (
             lower(trim(official_name))=lower(trim(?)) OR
             lower(trim(short_name))=lower(trim(?))
           ) ORDER BY id""",
        (name, name),
    ).fetchall()
    ids = list(dict.fromkeys(row["id"] for row in rows))
    if len(ids) == 1:
        return ids[0]
    target = _norm(name)
    for row in con.execute("SELECT id,official_name,short_name FROM companies WHERE active=1"):
        if _norm(row["official_name"] or row["short_name"]) == target:
            return row["id"]
    return None
