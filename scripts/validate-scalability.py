#!/usr/bin/env python3
"""CI smoke validation for the scalable Ceníky platform."""
from __future__ import annotations

import pathlib
import shutil
import sqlite3
import sys
import tempfile


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(root))

    from price_lists_domain.platform import categories, compat, database, finalize

    class Fake:
        pass

    M = Fake()
    M.sqlite3 = sqlite3
    M._czech_collate = lambda a, b: (str(a or "") > str(b or "")) - (str(a or "") < str(b or ""))
    temp = pathlib.Path(tempfile.mkdtemp(prefix="turto6331_ci_"))
    try:
        M.DB = temp / "smoke.db"
        M.BACKUP_DIR = temp / "backup"
        M.BACKUP_DIR.mkdir(parents=True)
        with sqlite3.connect(M.DB) as con:
            con.executescript(
                """
                CREATE TABLE app_meta(key TEXT PRIMARY KEY,value TEXT DEFAULT '');
                CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT DEFAULT '',short_name TEXT DEFAULT '');
                CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT DEFAULT '',active INTEGER DEFAULT 1,end_date TEXT DEFAULT '');
                CREATE TABLE actions(id INTEGER PRIMARY KEY,status TEXT DEFAULT '',created_date TEXT DEFAULT '',deadline TEXT DEFAULT '',updated_at TEXT DEFAULT '',project_id INTEGER);
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,done INTEGER DEFAULT 0,due_date TEXT DEFAULT '',done_at TEXT DEFAULT '');
                CREATE TABLE requests(id INTEGER PRIMARY KEY,archived INTEGER DEFAULT 0,no_response INTEGER DEFAULT 0,received_date TEXT DEFAULT '',asked_date TEXT DEFAULT '');
                CREATE TABLE supplier_offers(id INTEGER PRIMARY KEY,offer_date TEXT DEFAULT '',supplier_company_id INTEGER);
                CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY,offer_id INTEGER,product_code TEXT DEFAULT '',item_key TEXT DEFAULT '',original_name TEXT DEFAULT '',details TEXT DEFAULT '');
                CREATE TABLE price_lists(id INTEGER PRIMARY KEY,source_offer_id INTEGER,supplier_company_id INTEGER,supplier_name TEXT DEFAULT '',title TEXT DEFAULT '',valid_from TEXT DEFAULT '',valid_to TEXT DEFAULT '',product_group TEXT DEFAULT '',branch TEXT DEFAULT '',update_mode TEXT DEFAULT 'partial',supersedes_id INTEGER,archived INTEGER DEFAULT 0,parse_status TEXT DEFAULT '');
                CREATE TABLE price_list_items(id INTEGER PRIMARY KEY,price_list_id INTEGER,active INTEGER DEFAULT 1,product_code TEXT DEFAULT '',supplier_item_code TEXT DEFAULT '',item_key TEXT DEFAULT '',name TEXT DEFAULT '',description TEXT DEFAULT '',condition_text TEXT DEFAULT '',dimensions TEXT DEFAULT '');
                """
            )

        database.install_fast_db(M)
        database.ensure_platform_schema(M)
        finalize._install_fast_classifier(M)
        compat.install(M)

        with M.db() as con:
            tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {
                "product_categories", "price_list_ocr_cache", "archive_batches", "archive_batch_items",
                "business_documents", "business_document_items",
            }
            assert required <= tables, required - tables
            offer_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_offers)")}
            assert {"archived", "archived_at", "archived_by"} <= offer_columns
            assert con.execute("SELECT COUNT(*) FROM product_categories").fetchone()[0] >= 12

        one = categories.classify_text(M, "Kunex PVC pás v provedení BV")
        two = categories.classify_text("Kunex PVC pás v provedení BV")
        assert one == two and one is not None
        with M.db() as con:
            label = con.execute("SELECT name FROM product_categories WHERE id=?", (one,)).fetchone()[0]
        assert label == "PVC pásy (Kunex)", label

        platform = root / "price_lists_domain" / "platform"
        domain_init = (root / "price_lists_domain" / "__init__.py").read_text(encoding="utf-8")
        app_integration = (root / "price_lists_domain" / "app_integration.py").read_text(encoding="utf-8")
        platform_init = (platform / "__init__.py").read_text(encoding="utf-8")
        integration = (platform / "integration.py").read_text(encoding="utf-8")
        workset_wrapper = (platform / "worksets" / "__init__.py").read_text(encoding="utf-8")
        lazy_refresh = (platform / "lazy_refresh.py").read_text(encoding="utf-8")

        # One deterministic platform installation; no global installer mutation
        # and no second App.build/show_page/refresh_all wrapper in Ceníky.
        assert "install_platform(module)" in domain_init
        assert "install_platform(module)" not in app_integration
        assert "old_show" not in app_integration and "old_refresh_all" not in app_integration
        assert "old_build" not in integration and "M.App.build =" not in integration
        assert "finalize.install =" not in workset_wrapper
        order = [
            platform_init.index("install_worksets(module)"),
            platform_init.index("install_finalize(module)"),
            platform_init.index("install_compat(module)"),
            platform_init.index("install_lazy_refresh(module)"),
        ]
        assert order == sorted(order), order
        assert '_turto_navigation_owner = "price_lists_domain.platform.lazy_refresh"' in lazy_refresh
        assert '_cancel(app, "_turto_final_layout_after")' in lazy_refresh

        fast_ocr = (platform / "fast_ocr.py").read_text(encoding="utf-8")
        assert "DPI = 170" in fast_ocr and "price_list_ocr_cache" in fast_ocr and "ocr_batch.ps1" in fast_ocr
        offer_perf = (platform / "offers.py").read_text(encoding="utf-8")
        load_segment = offer_perf.split("def load", 1)[1].split("old_build", 1)[0]
        select_segment = load_segment.split("items = con.execute", 1)[1].split("FROM supplier_offer_items", 1)[0]
        assert "image_blob" not in select_segment
        pohlcon = integration
        assert 'scope_value="Kunex"' in pohlcon and 'scope_type="product_name_prefix"' in pohlcon
        future = (platform / "database.py").read_text(encoding="utf-8")
        assert "business_documents" in future and "business_document_items" in future
        print("TURTO CRM 6.3.31 scalability smoke test: OK")
    finally:
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
