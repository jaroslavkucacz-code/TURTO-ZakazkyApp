from __future__ import annotations
import importlib.util
import sqlite3
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
worksets = (root / "price_lists_domain/platform/worksets.py").read_text(encoding="utf-8")
assert 'M.fmt_date(row["asked_date"])' in worksets
assert "if not mivo:" in worksets
mivo_block = worksets.split("if mivo:", 1)[1].split("else:", 1)[0]
assert "request_wait_date" not in mivo_block

schema_text = (root / "price_lists_domain/platform/database.py").read_text(encoding="utf-8")
storage_text = (root / "price_lists_domain/storage.py").read_text(encoding="utf-8")
insert_block = storage_text.split("INSERT INTO price_list_items(", 1)[1].split("for attr in", 1)[0]
assert "category_id,subgroup_id,active" in insert_block.replace("\n", "").replace(" ", "")
assert insert_block.count("?") == 29
for needle in (
    "CREATE TABLE IF NOT EXISTS product_subgroups",
    '"subgroup_id INTEGER REFERENCES product_subgroups(id)"',
    "PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK",
    "AKUSTICKÁ IZOLACE SCHODIŠŤ",
    "MEZIVÝPLŇ IZOLAČNÍCH NOSNÍKŮ",
    "TRN PRO ZALOŽENÍ SCHODIŠTĚ",
):
    assert needle in schema_text, needle

for rel, needles in {
    "price_lists_domain/platform/categories.py": (
        "def choose_taxonomy", "def move_subgroup", "supplier_offer_items", "product_subgroups"
    ),
    "price_lists_domain/platform/price_page.py": (
        "price_subgroup_filter", '"Produktová skupina", "Podskupina"', "i.subgroup_id=?"
    ),
    "price_lists_domain/platform/price_dialogs.py": (
        "Přiřadit skupinu / podskupinu", "self.subgroup", "product_subgroups sg"
    ),
    "price_lists_domain/platform/offers.py": (
        "Přiřadit skupinu / podskupinu", "supplier_offer_items", "subgroup_id=row"
    ),
}.items():
    text = (root / rel).read_text(encoding="utf-8")
    for needle in needles:
        assert needle in text, (rel, needle)

# Execute the additive schema against an old-style minimal database and verify
# stable group IDs and subgroup propagation.
spec = importlib.util.spec_from_file_location("turto_database", root / "price_lists_domain/platform/database.py")
database = importlib.util.module_from_spec(spec)
spec.loader.exec_module(database)

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
        CREATE TABLE product_categories(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE CZECH,
          parent_id INTEGER, keywords TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 100, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE projects(id INTEGER PRIMARY KEY,active INTEGER DEFAULT 1,end_date TEXT);
        CREATE TABLE price_lists(id INTEGER PRIMARY KEY,category_id INTEGER,archived INTEGER DEFAULT 0,valid_from TEXT,valid_to TEXT,supplier_company_id INTEGER,parse_status TEXT);
        CREATE TABLE price_list_items(id INTEGER PRIMARY KEY,price_list_id INTEGER,category_id INTEGER,active INTEGER DEFAULT 1,product_code TEXT,item_key TEXT,name TEXT,description TEXT,condition_text TEXT);
        CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,offer_date TEXT,supplier_company_id INTEGER);
        CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,category_id INTEGER,product_code TEXT,item_key TEXT,original_name TEXT,details TEXT);
        CREATE TABLE actions(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,status TEXT,created_date TEXT,deadline TEXT,updated_at TEXT,project_id INTEGER);
        CREATE TABLE tasks(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,done INTEGER DEFAULT 0,due_date TEXT,done_at TEXT);
        CREATE TABLE requests(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,received_date TEXT,asked_date TEXT);
        """)
        old_id = con.execute("INSERT INTO product_categories(name,keywords,active,sort_order) VALUES('Izolační nosníky','',1,10)").lastrowid
    database.ensure_platform_schema(m)
    with m.db() as con:
        group = con.execute("SELECT id FROM product_categories WHERE name='PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK'").fetchone()
        assert group and group[0] == old_id
        sub = con.execute("SELECT id FROM product_subgroups WHERE name='TEPELNĚ IZOLAČNÍ NOSNÍK'").fetchone()
        assert sub
        for table in ("price_list_items", "supplier_offer_items", "business_document_items"):
            cols = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            assert "subgroup_id" in cols, table

print("6.3.33 taxonomy regression checks passed")
