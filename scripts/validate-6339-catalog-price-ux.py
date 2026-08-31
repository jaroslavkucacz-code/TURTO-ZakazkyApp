#!/usr/bin/env python3
"""Regression checks for TURTO CRM 6.3.39 catalogue and price-list UX."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from types import SimpleNamespace


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Module:
    sqlite3 = sqlite3
    PRICE_FTS_AVAILABLE = False

    def __init__(self, path: pathlib.Path):
        self.path = path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.create_collation(
            "CZECH",
            lambda a, b: (str(a or "") > str(b or "")) - (str(a or "") < str(b or "")),
        )
        con.execute("PRAGMA foreign_keys=ON")
        return con


def ordered_ids(con, table: str, where: str = "1=1", params=()) -> list[int]:
    return [
        int(row[0])
        for row in con.execute(
            f"SELECT id FROM {table} WHERE {where} ORDER BY active DESC,sort_order,name COLLATE CZECH,id",
            params,
        ).fetchall()
    ]


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    sys.path.insert(0, str(root))

    from price_lists_domain.platform import categories, commercial_workspace, product_catalog, product_workspace

    categories_text = (root / "price_lists_domain/platform/categories.py").read_text(encoding="utf-8")
    workspace_text = (root / "price_lists_domain/platform/product_workspace.py").read_text(encoding="utf-8")
    prices_text = (root / "price_lists_domain/platform/commercial_workspace.py").read_text(encoding="utf-8")
    catalog_text = (root / "price_lists_domain/platform/product_catalog.py").read_text(encoding="utf-8")
    platform_text = (root / "price_lists_domain/platform/__init__.py").read_text(encoding="utf-8")

    for needle in (
        "def reorder_category", "def reorder_subgroup", "native drag-and-drop",
        "<B1-Motion>", "Přetáhněte skupinu nebo podskupinu", "dialog.wait_window()",
        "Přesunout podskupinu",
    ):
        assert needle in categories_text, needle
    for needle in (
        "sort_mode", "on_product_drag_motion", "move_to_scope", "undo_last_move",
        "přetáhnout přímo na cílovou skupinu", "_turto_product_workspace_v639",
    ):
        assert needle in workspace_text, needle
    for needle in (
        "Struktura cen", "_refresh_price_taxonomy", "_move_current_to_scope",
        "_undo_current_move", "_select_price_sort", "price_sort_mode",
        "přetáhněte přímo na cílovou větev", "_turto_commercial_workspace_v6339",
    ):
        assert needle in prices_text, needle
    assert "_price_taxonomy_cache = None" in catalog_text
    assert "_turto_platform_v6339" in platform_text

    with tempfile.TemporaryDirectory() as temp_dir:
        module = Module(pathlib.Path(temp_dir) / "catalog-price-ux.db")
        today = date.today()
        with module.db() as con:
            con.executescript(
                """
                CREATE TABLE product_categories(
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE CZECH,
                    parent_id INTEGER,
                    keywords TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 100,
                    default_margin_pct REAL DEFAULT 0,
                    default_discount_pct REAL DEFAULT 0,
                    show_recommended_price INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE product_subgroups(
                    id INTEGER PRIMARY KEY,
                    category_id INTEGER NOT NULL REFERENCES product_categories(id),
                    name TEXT NOT NULL COLLATE CZECH,
                    keywords TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 100,
                    default_margin_pct REAL DEFAULT 0,
                    default_discount_pct REAL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category_id,name)
                );
                CREATE TABLE catalog_products(
                    id INTEGER PRIMARY KEY,
                    product_key TEXT DEFAULT '',
                    manufacturer_name TEXT DEFAULT '',
                    internal_code TEXT DEFAULT '',
                    internal_name TEXT DEFAULT '',
                    category_id INTEGER REFERENCES product_categories(id),
                    subgroup_id INTEGER REFERENCES product_subgroups(id),
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE catalog_product_sources(
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL REFERENCES catalog_products(id),
                    source_type TEXT DEFAULT '',
                    supplier_key TEXT DEFAULT '',
                    supplier_name TEXT DEFAULT '',
                    supplier_product_code TEXT DEFAULT '',
                    source_item_key TEXT DEFAULT '',
                    source_name TEXT DEFAULT ''
                );
                CREATE TABLE price_lists(
                    id INTEGER PRIMARY KEY,
                    archived INTEGER DEFAULT 0,
                    valid_from TEXT DEFAULT '',
                    valid_to TEXT DEFAULT ''
                );
                CREATE TABLE price_list_items(
                    id INTEGER PRIMARY KEY,
                    price_list_id INTEGER,
                    category_id INTEGER,
                    subgroup_id INTEGER,
                    catalog_product_id INTEGER,
                    active INTEGER DEFAULT 1,
                    normalized_unit_price REAL,
                    currency TEXT DEFAULT 'CZK'
                );
                CREATE TABLE supplier_offer_items(
                    id INTEGER PRIMARY KEY,
                    offer_id INTEGER,
                    category_id INTEGER,
                    subgroup_id INTEGER,
                    catalog_product_id INTEGER
                );
                CREATE TABLE business_document_items(
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER,
                    category_id INTEGER,
                    subgroup_id INTEGER,
                    catalog_product_id INTEGER
                );

                INSERT INTO product_categories(id,name,sort_order,default_margin_pct,default_discount_pct)
                VALUES(1,'Skupina A',10,10,0),(2,'Skupina B',20,20,5),(3,'Skupina C',30,0,0);
                INSERT INTO product_subgroups(id,category_id,name,sort_order,default_margin_pct,default_discount_pct)
                VALUES(11,1,'A1',10,15,0),(12,1,'A2',20,5,0),(21,2,'B1',10,25,10),
                      (13,1,'Duplicitní',30,0,0),(22,2,'Duplicitní',20,0,0);
                INSERT INTO catalog_products(id,product_key,manufacturer_name,internal_code,internal_name,category_id,subgroup_id)
                VALUES(101,'P101','Výrobce Z','P-101','Produkt dražší',1,11),
                      (102,'P102','Výrobce A','P-102','Produkt levnější',2,21);
                INSERT INTO catalog_product_sources(id,product_id,supplier_name,supplier_product_code,source_name)
                VALUES(1,101,'Dodavatel Z','DZ-1','Zdroj Z'),(2,102,'Dodavatel A','DA-1','Zdroj A');
                INSERT INTO price_list_items(id,price_list_id,category_id,subgroup_id,catalog_product_id,normalized_unit_price,currency)
                VALUES(1001,1,1,11,101,200,'CZK'),(1002,1,2,21,102,100,'CZK');
                INSERT INTO supplier_offer_items(id,offer_id,category_id,subgroup_id,catalog_product_id)
                VALUES(2001,1,1,11,101);
                INSERT INTO business_document_items(id,document_id,category_id,subgroup_id,catalog_product_id)
                VALUES(3001,1,1,11,101);
                """
            )
            con.execute(
                "INSERT INTO price_lists(id,archived,valid_from,valid_to) VALUES(1,0,?,?)",
                ((today - timedelta(days=10)).isoformat(), (today + timedelta(days=30)).isoformat()),
            )

        # Groups retain stable IDs and receive compact, deterministic order values.
        categories.reorder_category(module, 3, 1, after=False)
        with module.db() as con:
            assert ordered_ids(con, "product_categories") == [3, 1, 2]
            assert [row[0] for row in con.execute(
                "SELECT sort_order FROM product_categories ORDER BY sort_order,id"
            )] == [10, 20, 30]
        categories.reorder_category(module, 3, 2, after=True)
        with module.db() as con:
            assert ordered_ids(con, "product_categories") == [1, 2, 3]

        # Reordering within a group is pure presentation order.
        categories.reorder_subgroup(module, 12, 1, 11, after=False)
        with module.db() as con:
            assert ordered_ids(con, "product_subgroups", "category_id=?", (1,))[:3] == [12, 11, 13]

        # Moving a subgroup across groups keeps its ID and propagates the new parent
        # to every catalogue/document row linked by that subgroup.
        categories.reorder_subgroup(module, 11, 2, 21, after=False)
        with module.db() as con:
            assert con.execute("SELECT category_id FROM product_subgroups WHERE id=11").fetchone()[0] == 2
            assert ordered_ids(con, "product_subgroups", "category_id=?", (2,))[:3] == [11, 21, 22]
            assert ordered_ids(con, "product_subgroups", "category_id=?", (1,)) == [12, 13]
            for table, row_id in (
                ("catalog_products", 101), ("price_list_items", 1001),
                ("supplier_offer_items", 2001), ("business_document_items", 3001),
            ):
                row = con.execute(
                    f"SELECT category_id,subgroup_id FROM {table} WHERE id=?", (row_id,)
                ).fetchone()
                assert tuple(row) == (2, 11), (table, tuple(row))

        # A cross-group name collision is rejected transactionally.
        try:
            categories.reorder_subgroup(module, 13, 2)
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("duplicate subgroup move must fail")
        with module.db() as con:
            assert tuple(con.execute(
                "SELECT category_id,name FROM product_subgroups WHERE id=13"
            ).fetchone()) == (1, "Duplicitní")

        all_scope = product_workspace._scope_from_iid(module, "all")
        total, rows, _summary = product_workspace._catalog_rows(
            module, all_scope, sort_mode="Nákupní cena ↑", limit=20
        )
        assert total == 2 and [int(row["id"]) for row in rows] == [102, 101]
        _total, rows, _summary = product_workspace._catalog_rows(
            module, all_scope, sort_mode="Nákupní cena ↓", limit=20
        )
        assert [int(row["id"]) for row in rows] == [101, 102]
        _total, rows, _summary = product_workspace._catalog_rows(
            module, all_scope, sort_mode="Výrobce A–Z", limit=20
        )
        assert [int(row["id"]) for row in rows] == [102, 101]

        assert product_workspace._scope_from_iid(module, "n2")["only_without_subgroup"] is True
        assert product_workspace._scope_from_iid(module, "s11")["category_id"] == 2
        assert commercial_workspace._price_scope_from_iid(module, "pt_s11")["category_id"] == 2

        sort_app = SimpleNamespace(price_sort_mode=Var("Nákupní cena ↑"))
        assert "normalized_unit_price ASC" in commercial_workspace._price_sort_sql(sort_app)
        sort_app.price_sort_mode.set("Výsledná cena ↓")
        assert "DESC" in commercial_workspace._price_sort_sql(sort_app)
        commercial_workspace._select_price_sort(sort_app, "Nákupní cena ↑", "Nákupní cena ↓")
        assert sort_app.price_sort_mode.get() == "Nákupní cena ↑"
        commercial_workspace._select_price_sort(sort_app, "Nákupní cena ↑", "Nákupní cena ↓")
        assert sort_app.price_sort_mode.get() == "Nákupní cena ↓"

        cache_app = SimpleNamespace(
            _commercial_price_summary_cache=(1, {}), _price_filter_cache=(1, (), ""),
            _price_taxonomy_cache=(1, (), {}), _commercial_offer_summary_cache=(1, {}),
        )
        result = commercial_workspace._run_after_invalidation(
            cache_app, lambda: "ok", prices=True, offers=True
        )
        assert result == "ok"
        assert cache_app._commercial_price_summary_cache is None
        assert cache_app._price_filter_cache is None
        assert cache_app._price_taxonomy_cache is None
        assert cache_app._commercial_offer_summary_cache is None

        product_catalog._invalidate(cache_app)
        assert cache_app._price_taxonomy_cache is None

    print("TURTO CRM 6.3.39 catalogue and price-list UX regression test: OK")


if __name__ == "__main__":
    main()
