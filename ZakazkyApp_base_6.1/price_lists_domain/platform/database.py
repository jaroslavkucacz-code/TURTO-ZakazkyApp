"""Database tuning and additive enterprise-scale schema.

This module deliberately keeps SQLite as the storage engine.  The data set expected
for TURTO is still well inside SQLite's useful range, but connections, indexes and
refresh patterns must be disciplined so the GUI does not repeatedly scan or copy
large binary values.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

_DB_INIT_LOCK = threading.Lock()
_WAL_READY: set[str] = set()


CATEGORY_SEEDS = (
    (10, "PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK", "izolacni nosnik|isokorb|egcobox|hit hp|hit mv|hit smv|hit mvx|thermo nosnik"),
    (20, "AKUSTICKÁ IZOLACE SCHODIŠŤ", "tronsole|cisador|cibatur|schodist|schodovy prvek|akustika schod|treppensicherung|impact sound insulation"),
    (30, "Dilatační smykové trny", "sinton|smykovy trn|dilatacni trn|dilatační trn|dorn"),
    (40, "PVC pásy (Kunex)", "kunex"),
    (50, "Plastové distanční prvky", "plastovy distanc|plastova distance|plastovy distancni|plastový distanční"),
    (60, "Betonové distanční prvky", "betonovy distanc|betonova distance|vlaknobetonovy distanc|vláknobetonový distanční"),
    (70, "Ocelové distanční prvky", "ocelovy distanc|ocelova distance|drateny distanc|drátěný distanční"),
    (80, "Plastové profily", "plastovy profil|plastový profil|pvc profil"),
    (90, "Hydroizolační prvky", "pentaflex|tesnici plech|těsnicí plech|tesnici pas|těsnicí pás"),
    (100, "Smyková výztuž", "smykova vyztuz|smyková výztuž|dvojhlavy trn|dvojhlavý trn"),
    (110, "Kotevní technika", "kotevni lista|kotevní lišta|kotevni sroub|kotevní šroub|chemicka kotva|chemická kotva"),
    (120, "Vibroizolace", "vibroizolace|vibroizolacni|vibroizolační|calenberg"),
    (999, "Ostatní", ""),
)

GROUP_RENAMES = (
    ("Izolační nosníky", "PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK"),
    ("Akustická izolace schodišť", "AKUSTICKÁ IZOLACE SCHODIŠŤ"),
)

SUBGROUP_SEEDS = (
    ("PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK", 10, "TEPELNĚ IZOLAČNÍ NOSNÍK",
     "izolační nosník|izolacni nosnik|isokorb|egcobox|hit hp|hit mv|hit smv|hit mvx"),
    ("PŘERUŠENÍ TEPELNÝCH MOSTŮ - IZONOSNÍK", 20, "MEZIVÝPLŇ IZOLAČNÍCH NOSNÍKŮ",
     "mezivýplň|mezivypln|výplň izolačních nosníků|vypln izolacnich nosniku"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 10, "BOX PRO ULOŽENÍ PODEST DO STĚN",
     "hbb v-box|hbb vh-box|hbb vvh-box|hbb-ov|hbb-ovv|hbb-ovvh|box pro uložení podest"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 20, "PRVEK PRO NAPOJENÍ MONOLITICKÉHO SCHODIŠTĚ NA MONOLITICKOU PODESTU",
     "napojení monolitického schodiště|napojeni monolitickeho schodiste|htf-t"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 30, "TLUMICÍ DESKA PRO NAPOJENÍ SCHODIŠŤOVÉHO RAMENE A ZÁKLADOVÉ DESKY",
     "tlumicí deska|tlumici deska|cisador|cibatur|napojení schodišťového ramene a základové desky"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 40, "KAPSA PRO ULOŽENÍ PREFABRIKOVANÉHO SCHODIŠŤOVÉHO RAMENA NA KONZOLU PODESTY",
     "kapsa pro uložení prefabrikovaného schodišťového ramena|kapsa pro ulozeni prefabrikovaneho schodistoveho ramena"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 50, "SPÁROVÁ DESKA, BOČNÍ ODDĚLENÍ SCHODIŠŤOVÉHO RAMENA A STĚNY",
     "spárová deska|sparova deska|boční oddělení schodišťového ramena|bocni oddeleni schodistoveho ramena|htpl"),
    ("AKUSTICKÁ IZOLACE SCHODIŠŤ", 60, "TRN PRO ZALOŽENÍ SCHODIŠTĚ",
     "trn pro založení schodiště|trn pro zalozeni schodiste|treppensicherung|cet-ts|hsd-p"),
)


def install_fast_db(M) -> None:
    """Replace the connection factory with a tuned, short-lived connection.

    The old factory switched journal mode on every single connection.  That is
    unnecessary work and becomes noticeable once filters open many connections.
    WAL is now negotiated once for each active database path (live/test), while
    every connection receives safe runtime pragmas.
    """
    if getattr(M, "_turto_fast_db_installed", False):
        return

    def tuned_db():
        db_path = Path(M.DB)
        con = M.sqlite3.connect(str(db_path), timeout=10.0)
        con.row_factory = M.sqlite3.Row
        try:
            con.create_collation("CZECH", M._czech_collate)
        except Exception:
            pass
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        try:
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("PRAGMA temp_store=MEMORY")
            con.execute("PRAGMA cache_size=-32768")
            con.execute("PRAGMA mmap_size=268435456")
        except Exception:
            pass

        try:
            key = str(db_path.resolve())
        except Exception:
            key = str(db_path)
        if key not in _WAL_READY:
            with _DB_INIT_LOCK:
                if key not in _WAL_READY:
                    try:
                        con.execute("PRAGMA journal_mode=WAL").fetchone()
                    finally:
                        _WAL_READY.add(key)
        return con

    M.db = tuned_db
    M._turto_fast_db_installed = True


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _add_column(con, table: str, declaration: str) -> None:
    name = declaration.split()[0]
    if name not in _columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {declaration}")


def _ensure_fts(M, con) -> None:
    """Create a prefix-search index for price-list products when FTS5 is present."""
    try:
        con.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS price_list_items_fts USING fts5(
                   product_code,item_key,name,description,condition_text,
                   content='price_list_items',content_rowid='id',
                   tokenize='unicode61 remove_diacritics 2'
               )"""
        )
        con.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS price_list_items_fts_ai AFTER INSERT ON price_list_items BEGIN
              INSERT INTO price_list_items_fts(rowid,product_code,item_key,name,description,condition_text)
              VALUES(new.id,new.product_code,new.item_key,new.name,new.description,new.condition_text);
            END;
            CREATE TRIGGER IF NOT EXISTS price_list_items_fts_ad AFTER DELETE ON price_list_items BEGIN
              INSERT INTO price_list_items_fts(price_list_items_fts,rowid,product_code,item_key,name,description,condition_text)
              VALUES('delete',old.id,old.product_code,old.item_key,old.name,old.description,old.condition_text);
            END;
            CREATE TRIGGER IF NOT EXISTS price_list_items_fts_au AFTER UPDATE ON price_list_items BEGIN
              INSERT INTO price_list_items_fts(price_list_items_fts,rowid,product_code,item_key,name,description,condition_text)
              VALUES('delete',old.id,old.product_code,old.item_key,old.name,old.description,old.condition_text);
              INSERT INTO price_list_items_fts(rowid,product_code,item_key,name,description,condition_text)
              VALUES(new.id,new.product_code,new.item_key,new.name,new.description,new.condition_text);
            END;
            """
        )
        marker = con.execute(
            "SELECT value FROM app_meta WHERE key='price_list_fts_v1'"
        ).fetchone()
        if not marker:
            con.execute("INSERT INTO price_list_items_fts(price_list_items_fts) VALUES('rebuild')")
            con.execute(
                "INSERT OR REPLACE INTO app_meta(key,value) VALUES('price_list_fts_v1',?)",
                (datetime.now().isoformat(timespec="seconds"),),
            )
        M.PRICE_FTS_AVAILABLE = True
    except Exception:
        M.PRICE_FTS_AVAILABLE = False


def ensure_platform_schema(M) -> None:
    """Add only new tables/columns; no existing business row is rewritten."""
    with M.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS product_categories(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE COLLATE CZECH,
              parent_id INTEGER,
              keywords TEXT DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 100,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(parent_id) REFERENCES product_categories(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS product_subgroups(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              category_id INTEGER NOT NULL,
              name TEXT NOT NULL COLLATE CZECH,
              keywords TEXT DEFAULT '',
              active INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 100,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(category_id,name),
              FOREIGN KEY(category_id) REFERENCES product_categories(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS price_list_ocr_cache(
              source_hash TEXT NOT NULL,
              page_no INTEGER NOT NULL,
              profile TEXT NOT NULL,
              text TEXT DEFAULT '',
              layout_json TEXT DEFAULT '',
              language TEXT DEFAULT '',
              width INTEGER DEFAULT 0,
              height INTEGER DEFAULT 0,
              elapsed_ms INTEGER DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(source_hash,page_no,profile)
            );

            CREATE TABLE IF NOT EXISTS archive_batches(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by TEXT DEFAULT '',
              cutoff_date TEXT NOT NULL DEFAULT '',
              note TEXT DEFAULT '',
              backup_path TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS archive_batch_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              batch_id INTEGER NOT NULL,
              table_name TEXT NOT NULL,
              row_id INTEGER NOT NULL,
              old_state TEXT DEFAULT '',
              new_state TEXT DEFAULT '',
              FOREIGN KEY(batch_id) REFERENCES archive_batches(id) ON DELETE CASCADE
            );

            -- Foundation for the forthcoming issued offers and issued orders.
            CREATE TABLE IF NOT EXISTS business_documents(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_type TEXT NOT NULL,
              direction TEXT NOT NULL DEFAULT 'issued',
              document_number TEXT DEFAULT '',
              issue_date TEXT DEFAULT '',
              due_date TEXT DEFAULT '',
              valid_to TEXT DEFAULT '',
              company_id INTEGER,
              project_id INTEGER,
              status TEXT DEFAULT 'Rozpracováno',
              currency TEXT DEFAULT 'CZK',
              total_value REAL DEFAULT 0,
              note TEXT DEFAULT '',
              source_path TEXT DEFAULT '',
              archived INTEGER NOT NULL DEFAULT 0,
              archived_at TEXT DEFAULT '',
              archived_by TEXT DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(company_id) REFERENCES companies(id),
              FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS business_document_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_id INTEGER NOT NULL,
              position INTEGER DEFAULT 0,
              product_code TEXT DEFAULT '',
              item_key TEXT DEFAULT '',
              name TEXT DEFAULT '',
              description TEXT DEFAULT '',
              quantity REAL DEFAULT 0,
              unit TEXT DEFAULT '',
              unit_price REAL DEFAULT 0,
              discount_pct REAL DEFAULT 0,
              total_price REAL DEFAULT 0,
              category_id INTEGER,
              FOREIGN KEY(document_id) REFERENCES business_documents(id) ON DELETE CASCADE,
              FOREIGN KEY(category_id) REFERENCES product_categories(id)
            );
            """
        )

        _add_column(con, "price_lists", "category_id INTEGER")
        _add_column(con, "price_list_items", "category_id INTEGER")
        _add_column(con, "price_list_items", "subgroup_id INTEGER REFERENCES product_subgroups(id)")
        _add_column(con, "supplier_offer_items", "category_id INTEGER")
        _add_column(con, "supplier_offer_items", "subgroup_id INTEGER REFERENCES product_subgroups(id)")
        _add_column(con, "business_document_items", "subgroup_id INTEGER REFERENCES product_subgroups(id)")
        for table in ("supplier_offers", "actions", "tasks"):
            _add_column(con, table, "archived INTEGER NOT NULL DEFAULT 0")
            _add_column(con, table, "archived_at TEXT DEFAULT ''")
            _add_column(con, table, "archived_by TEXT DEFAULT ''")

        # Preserve stable IDs when replacing the initial working labels with the
        # user-approved product-group names. Existing product assignments need no rewrite.
        for old_name, new_name in GROUP_RENAMES:
            old = con.execute(
                "SELECT id FROM product_categories WHERE lower(trim(name))=lower(trim(?))", (old_name,)
            ).fetchone()
            new = con.execute(
                "SELECT id FROM product_categories WHERE lower(trim(name))=lower(trim(?))", (new_name,)
            ).fetchone()
            if old and not new:
                con.execute(
                    "UPDATE product_categories SET name=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (new_name, old["id"]),
                )

        for sort_order, name, keywords in CATEGORY_SEEDS:
            con.execute(
                """INSERT INTO product_categories(name,keywords,active,sort_order)
                   VALUES(?,?,1,?)
                   ON CONFLICT(name) DO UPDATE SET
                     keywords=CASE WHEN trim(coalesce(product_categories.keywords,''))=''
                                   THEN excluded.keywords ELSE product_categories.keywords END,
                     sort_order=MIN(product_categories.sort_order,excluded.sort_order)""",
                (name, keywords, sort_order),
            )

        for group_name, sort_order, subgroup_name, keywords in SUBGROUP_SEEDS:
            group = con.execute(
                "SELECT id FROM product_categories WHERE lower(trim(name))=lower(trim(?))",
                (group_name,),
            ).fetchone()
            if group:
                con.execute(
                    """INSERT INTO product_subgroups(category_id,name,keywords,active,sort_order)
                       VALUES(?,?,?,1,?)
                       ON CONFLICT(category_id,name) DO UPDATE SET
                         keywords=CASE WHEN trim(coalesce(product_subgroups.keywords,''))=''
                                       THEN excluded.keywords ELSE product_subgroups.keywords END,
                         sort_order=MIN(product_subgroups.sort_order,excluded.sort_order)""",
                    (group["id"], subgroup_name, keywords, sort_order),
                )

        con.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_categories_active_order
              ON product_categories(active,sort_order,name);
            CREATE INDEX IF NOT EXISTS idx_product_subgroups_group_order
              ON product_subgroups(category_id,active,sort_order,name);
            CREATE INDEX IF NOT EXISTS idx_price_lists_workset
              ON price_lists(archived,valid_from,valid_to,category_id,id);
            CREATE INDEX IF NOT EXISTS idx_price_list_items_workset
              ON price_list_items(price_list_id,active,category_id,product_code,item_key,id);
            CREATE INDEX IF NOT EXISTS idx_price_list_items_category_name
              ON price_list_items(category_id,name,product_code);
            CREATE INDEX IF NOT EXISTS idx_price_list_items_subgroup
              ON price_list_items(subgroup_id,category_id,name,product_code);
            CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_taxonomy
              ON supplier_offer_items(category_id,subgroup_id,offer_id,id);
            CREATE INDEX IF NOT EXISTS idx_business_document_items_taxonomy
              ON business_document_items(category_id,subgroup_id,document_id,id);
            CREATE INDEX IF NOT EXISTS idx_supplier_offers_archive_date
              ON supplier_offers(archived,offer_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_supplier_offers_archive_supplier
              ON supplier_offers(archived,supplier_company_id,offer_date DESC);
            CREATE INDEX IF NOT EXISTS idx_actions_archive_status
              ON actions(archived,status,created_date,deadline,id);
            CREATE INDEX IF NOT EXISTS idx_tasks_archive_done
              ON tasks(archived,done,due_date,id);
            CREATE INDEX IF NOT EXISTS idx_requests_archive_dates
              ON requests(archived,no_response,received_date,asked_date,id);
            CREATE INDEX IF NOT EXISTS idx_archive_batch_items_batch
              ON archive_batch_items(batch_id,table_name,row_id);
            CREATE INDEX IF NOT EXISTS idx_business_documents_workset
              ON business_documents(archived,document_type,direction,status,issue_date,id);
            CREATE INDEX IF NOT EXISTS idx_business_documents_company
              ON business_documents(company_id,archived,issue_date DESC);
            CREATE INDEX IF NOT EXISTS idx_business_document_items_doc
              ON business_document_items(document_id,position,id);
            CREATE INDEX IF NOT EXISTS idx_business_document_items_category
              ON business_document_items(category_id,product_code,item_key);
            """
        )
        _ensure_fts(M, con)

        try:
            marker = con.execute(
                "SELECT value FROM app_meta WHERE key='sqlite_optimize_last'"
            ).fetchone()
            last = date.fromisoformat(marker[0]) if marker and marker[0] else date.min
            if (date.today() - last).days >= 7:
                con.execute("PRAGMA optimize")
                con.execute(
                    "INSERT OR REPLACE INTO app_meta(key,value) VALUES('sqlite_optimize_last',?)",
                    (date.today().isoformat(),),
                )
        except Exception:
            pass


def patch_schema(M) -> None:
    if getattr(M, "_turto_platform_schema_installed", False):
        return
    old_ensure = M.ensure_schema

    def ensure_schema():
        old_ensure()
        ensure_platform_schema(M)

    M.ensure_schema = ensure_schema
    M.ensure_platform_schema = lambda: ensure_platform_schema(M)
    M._turto_platform_schema_installed = True


def maintain_database(M, app) -> None:
    """Manual low-risk maintenance; VACUUM is intentionally not automatic."""
    backup = None
    try:
        backup = M.backup_now("before_optimize")
    except Exception:
        pass
    try:
        db_path = Path(M.DB)
        before = db_path.stat().st_size if db_path.exists() else 0
        with M.db() as con:
            con.execute("PRAGMA optimize")
            con.execute("ANALYZE")
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            except Exception:
                pass
            con.execute(
                "INSERT OR REPLACE INTO app_meta(key,value) VALUES('sqlite_optimize_last',?)",
                (date.today().isoformat(),),
            )
        after = db_path.stat().st_size if db_path.exists() else 0
        M.messagebox.showinfo(
            "Optimalizace databáze",
            "Databázové indexy a statistiky byly aktualizovány.\n\n"
            f"Velikost databáze: {before/1024/1024:.1f} MB → {after/1024/1024:.1f} MB\n"
            f"Bezpečnostní záloha: {backup or 'nebyla potřeba'}",
            parent=app,
        )
    except Exception as exc:
        M.messagebox.showerror("Optimalizace databáze", str(exc), parent=app)
