from __future__ import annotations
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
for rel, needles in {
    "price_lists_domain/platform/database.py": (
        "CREATE TABLE IF NOT EXISTS catalog_products", "CREATE TABLE IF NOT EXISTS catalog_product_sources",
        "default_margin_pct", "show_recommended_price", "catalog_product_id INTEGER REFERENCES catalog_products",
    ),
    "price_lists_domain/platform/categories.py": (
        "Product placement is intentionally not guessed from keywords", "Produkty ve výběru…",
        "Základní marže [%]", "Pouze výsledná",
    ),
    "price_lists_domain/platform/product_catalog.py": (
        "def sync_price_list", "def sync_supplier_offer", "def update_product",
        "def calculate_prices", "Interní kód", "Zdroje a ceny…",
    ),
    "price_lists_domain/platform/price_page.py": (
        "Interní kód", "Nákupní cena/MJ", "Doporučená cena", "Výsledná cena",
        "product_catalog.calculate_prices",
    ),
}.items():
    text = (root / rel).read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, (rel, needle)

categories_text = (root / "price_lists_domain/platform/categories.py").read_text(encoding="utf-8")
assert "Klíčová slova" not in categories_text
assert "def classify_text(M, value: object):\n    return None" in categories_text
assert "Automaticky podle položek" not in (root / "price_lists_domain/platform/price_dialogs.py").read_text(encoding="utf-8")

sys.path.insert(0, str(root))
from price_lists_domain.platform import database, product_catalog

class M:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False
    def __init__(self, path): self.path = path
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation("CZECH", lambda a,b: (str(a)>str(b))-(str(a)<str(b)))
        con.execute("PRAGMA foreign_keys=ON")
        return con

with tempfile.TemporaryDirectory() as tmp:
    m = M(Path(tmp) / "test.db")
    with m.db() as con:
        con.executescript("""
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
        """)
    database.ensure_platform_schema(m)
    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 1
    with m.db() as con:
        products = con.execute("SELECT * FROM catalog_products").fetchall()
        assert len(products) == 1
        product_id = int(products[0]["id"])
        linked = con.execute("SELECT catalog_product_id FROM price_list_items WHERE id=1").fetchone()[0]
        linked_offer = con.execute("SELECT catalog_product_id FROM supplier_offer_items WHERE id=1").fetchone()[0]
        assert linked == product_id == linked_offer
        group = con.execute("SELECT id FROM product_categories WHERE name='AKUSTICKÁ IZOLACE SCHODIŠŤ'").fetchone()[0]
        subgroup = con.execute("SELECT id FROM product_subgroups WHERE category_id=? ORDER BY id LIMIT 1", (group,)).fetchone()[0]
        con.execute("UPDATE product_subgroups SET default_margin_pct=25,default_discount_pct=10 WHERE id=?", (subgroup,))
    product_catalog.update_product(m, product_id, manufacturer_name="Výrobce A", internal_code="T-001", internal_name="Interní produkt A", category_id=group, subgroup_id=subgroup)
    defaults = product_catalog.quote_defaults(m, product_id, 100)
    assert round(defaults["recommended_unit_price"], 4) == 125
    assert round(defaults["final_unit_price"], 4) == 112.5
    with m.db() as con:
        row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        assert row[0] == group and row[1] == subgroup
        assert con.execute("SELECT internal_code FROM catalog_products WHERE id=?", (product_id,)).fetchone()[0] == "T-001"
        cols = {row[1] for row in con.execute("PRAGMA table_info(business_document_items)")}
        for col in ("catalog_product_id", "internal_code_snapshot", "purchase_unit_price", "margin_pct", "recommended_unit_price", "show_recommended_price"):
            assert col in cols

print("6.3.34 product catalogue and pricing regression checks passed")
