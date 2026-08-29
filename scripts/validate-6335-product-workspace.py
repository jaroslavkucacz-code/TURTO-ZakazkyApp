from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
workspace_path = root / "price_lists_domain/platform/product_workspace.py"
workspace_text = workspace_path.read_text(encoding="utf-8")
for needle in (
    "Produktové skupiny",
    "Všechny produkty",
    "Nezařazené",
    "Bez podskupiny",
    "Přesunout vybrané do označené skupiny",
    "Změna se automaticky projeví ve všech jejich Ceníkách i cenových Nabídkách",
    "structure_tree",
    "product_tree",
    "def build_product_workspace",
):
    assert needle in workspace_text, needle

platform_text = (root / "price_lists_domain/platform/__init__.py").read_text(encoding="utf-8")
assert "install_product_workspace" in platform_text
# The regression protects the 6.3.35 workspace, while the platform marker is
# intentionally advanced by every later release. Verify the marker mechanism,
# not one obsolete release number.
assert "_turto_platform_v" in platform_text

sys.path.insert(0, str(root))
from price_lists_domain.platform import database, product_catalog, product_workspace


class M:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False

    def __init__(self, path):
        self.path = path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation("CZECH", lambda a, b: (str(a) > str(b)) - (str(a) < str(b)))
        con.execute("PRAGMA foreign_keys=ON")
        return con


with tempfile.TemporaryDirectory() as tmp:
    m = M(Path(tmp) / "test.db")
    with m.db() as con:
        con.executescript(
            """
            CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT,short_name TEXT,active INTEGER DEFAULT 1);
            CREATE TABLE product_categories(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE COLLATE CZECH,parent_id INTEGER,keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE product_subgroups(id INTEGER PRIMARY KEY AUTOINCREMENT,category_id INTEGER NOT NULL,name TEXT NOT NULL,keywords TEXT DEFAULT '',active INTEGER DEFAULT 1,sort_order INTEGER DEFAULT 100,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(category_id,name));
            CREATE TABLE projects(id INTEGER PRIMARY KEY,active INTEGER DEFAULT 1,end_date TEXT);
            CREATE TABLE price_lists(id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,category_id INTEGER,archived INTEGER DEFAULT 0,valid_from TEXT,valid_to TEXT,parse_status TEXT,title TEXT,product_group TEXT,branch TEXT,source_filename TEXT,imported_at TEXT);
            CREATE TABLE price_list_items(id INTEGER PRIMARY KEY,price_list_id INTEGER,category_id INTEGER,subgroup_id INTEGER,active INTEGER DEFAULT 1,product_code TEXT,supplier_item_code TEXT,item_key TEXT,name TEXT,description TEXT,condition_text TEXT,normalized_unit_price REAL,currency TEXT);
            CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,supplier_company_id INTEGER,supplier_name TEXT,archived INTEGER DEFAULT 0,offer_date TEXT,currency TEXT,offer_number TEXT,reference TEXT);
            CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,category_id INTEGER,subgroup_id INTEGER,product_code TEXT,item_key TEXT,original_name TEXT,details TEXT,unit_price REAL);
            CREATE TABLE actions(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,status TEXT,created_date TEXT,deadline TEXT,updated_at TEXT,project_id INTEGER);
            CREATE TABLE tasks(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,done INTEGER DEFAULT 0,due_date TEXT,done_at TEXT);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,received_date TEXT,asked_date TEXT);
            INSERT INTO companies(id,official_name,active) VALUES(1,'Výrobce A',1);
            INSERT INTO price_lists(id,supplier_company_id,supplier_name,valid_from,valid_to,title) VALUES(1,1,'Výrobce A','2026-01-01','','Ceník A');
            INSERT INTO price_list_items(id,price_list_id,product_code,item_key,name,normalized_unit_price,currency) VALUES(1,1,'ABC-1','ABC-1','Produkt A',100,'CZK');
            INSERT INTO supplier_offers(id,supplier_company_id,supplier_name,offer_date,currency) VALUES(1,1,'Výrobce A','2026-02-01','CZK');
            INSERT INTO supplier_offer_items(id,offer_id,product_code,item_key,original_name,unit_price) VALUES(1,1,'ABC-1','ABC-1','Produkt A',95);
            """
        )
    database.ensure_platform_schema(m)
    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 1

    with m.db() as con:
        product_id = int(con.execute("SELECT id FROM catalog_products").fetchone()[0])
        group_a = int(con.execute(
            "SELECT id FROM product_categories WHERE name='AKUSTICKÁ IZOLACE SCHODIŠŤ'"
        ).fetchone()[0])
        subgroup_a = int(con.execute(
            "SELECT id FROM product_subgroups WHERE category_id=? ORDER BY sort_order,id LIMIT 1",
            (group_a,),
        ).fetchone()[0])
        group_b = int(con.execute(
            "SELECT id FROM product_categories WHERE name='Dilatační smykové trny'"
        ).fetchone()[0])

    product_catalog.set_product_taxonomy(m, [product_id], group_a, subgroup_a)
    totals, groups, subgroups = product_workspace._structure_rows(m)
    assert int(totals["product_count"]) == 1
    assert any(int(row["id"]) == group_a and int(row["product_count"]) == 1 for row in groups)
    assert any(int(row["id"]) == subgroup_a and int(row["product_count"]) == 1 for row in subgroups)

    scope = product_workspace._scope_from_iid(m, f"s{subgroup_a}")
    total, rows, summary = product_workspace._catalog_rows(m, scope)
    assert total == 1 and len(rows) == 1 and int(summary["products"]) == 1
    assert int(rows[0]["id"]) == product_id

    # Moving the stable product must immediately propagate to both source domains.
    product_catalog.set_product_taxonomy(m, [product_id], group_b, None)
    with m.db() as con:
        master = con.execute("SELECT category_id,subgroup_id FROM catalog_products WHERE id=?", (product_id,)).fetchone()
        price_row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        offer_row = con.execute("SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=1").fetchone()
        assert tuple(master) == tuple(price_row) == tuple(offer_row) == (group_b, None)

    group_scope = product_workspace._scope_from_iid(m, f"g{group_b}")
    assert product_workspace._catalog_rows(m, group_scope)[0] == 1
    no_subgroup_scope = product_workspace._scope_from_iid(m, f"n{group_b}")
    assert product_workspace._catalog_rows(m, no_subgroup_scope)[0] == 1
    assert product_workspace._catalog_rows(m, product_workspace._scope_from_iid(m, "unassigned"))[0] == 0

print("6.3.35 CRM product workspace regression checks passed")
