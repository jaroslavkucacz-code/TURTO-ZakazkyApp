#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.4 issued pricing and table consistency."""
from __future__ import annotations

import pathlib
import sqlite3
import sys
import tempfile


def main() -> None:
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(repository))

    import v740_offer_defaults
    from price_lists_domain.issued_offers import service

    class StubApp:
        def __init__(self, *args, **kwargs):
            return None

        def build(self):
            return None

        def build_offers(self):
            return None

    class Module:
        App = StubApp
        ProductPriceBrowser = None

        def __init__(self, root):
            self.DB = pathlib.Path(root) / "test.db"

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            con.create_collation(
                "CZECH",
                lambda a, b: (str(a) > str(b)) - (str(a) < str(b)),
            )
            return con

        def ensure_schema(self):
            with self.db() as con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS product_categories(
                      id INTEGER PRIMARY KEY,
                      name TEXT NOT NULL,
                      sort_order INTEGER NOT NULL DEFAULT 100,
                      default_margin_pct REAL NOT NULL DEFAULT 0,
                      default_discount_pct REAL NOT NULL DEFAULT 0,
                      show_recommended_price INTEGER NOT NULL DEFAULT 1
                    );
                    CREATE TABLE IF NOT EXISTS product_subgroups(
                      id INTEGER PRIMARY KEY,
                      category_id INTEGER NOT NULL,
                      name TEXT NOT NULL,
                      sort_order INTEGER NOT NULL DEFAULT 100,
                      default_margin_pct REAL NOT NULL DEFAULT 0,
                      default_discount_pct REAL NOT NULL DEFAULT 0
                    );
                    CREATE TABLE IF NOT EXISTS business_document_items(
                      id INTEGER PRIMARY KEY,
                      document_id INTEGER,
                      position INTEGER,
                      row_type TEXT,
                      product_code TEXT,
                      item_key TEXT,
                      name TEXT,
                      description TEXT,
                      quantity REAL,
                      unit TEXT,
                      purchase_unit_price REAL,
                      purchase_currency TEXT,
                      margin_pct REAL,
                      recommended_unit_price REAL,
                      discount_pct REAL,
                      unit_price REAL,
                      total_price REAL,
                      vat_rate REAL,
                      show_recommended_price INTEGER,
                      category_id INTEGER,
                      subgroup_id INTEGER,
                      catalog_product_id INTEGER,
                      internal_code_snapshot TEXT,
                      internal_name_snapshot TEXT,
                      price_source_label TEXT,
                      source_price_list_item_id INTEGER,
                      source_supplier_offer_item_id INTEGER,
                      line_note TEXT,
                      category_name_snapshot TEXT,
                      subgroup_name_snapshot TEXT
                    );
                    """
                )

    with tempfile.TemporaryDirectory(prefix="turto7400_") as temp:
        module = Module(temp)
        module.ensure_schema()
        v740_offer_defaults.apply(module)
        module.ensure_schema()

        with module.db() as con:
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(business_document_items)"
                ).fetchall()
            }
            assert {
                "base_margin_pct_snapshot",
                "base_discount_pct_snapshot",
                "pricing_rule_source_snapshot",
            } <= columns
            con.executescript(
                """
                INSERT INTO product_categories
                  (id,name,sort_order,default_margin_pct,default_discount_pct)
                VALUES
                  (1,'Druhá skupina',20,25,5),
                  (2,'První skupina',10,30,8);
                INSERT INTO product_subgroups
                  (id,category_id,name,sort_order,
                   default_margin_pct,default_discount_pct)
                VALUES
                  (11,1,'Druhá podskupina',20,27,6),
                  (12,1,'První podskupina',10,28,7),
                  (21,2,'Podskupina A',10,31,9);
                """
            )

        items = [
            {
                "row_type": "product",
                "name": "Produkt pozdější skupiny",
                "category_id": 1,
                "subgroup_id": 11,
                "category_name_snapshot": "Druhá skupina",
                "subgroup_name_snapshot": "Druhá podskupina",
            },
            {
                "row_type": "product",
                "name": "Produkt první skupiny",
                "category_id": 2,
                "subgroup_id": 21,
                "category_name_snapshot": "První skupina",
                "subgroup_name_snapshot": "Podskupina A",
            },
            {
                "row_type": "product",
                "name": "Produkt první podskupiny",
                "category_id": 1,
                "subgroup_id": 12,
                "category_name_snapshot": "Druhá skupina",
                "subgroup_name_snapshot": "První podskupina",
            },
        ]
        plan = module.group_issued_offer_items(items)
        labels = [token["label"] for token in plan if token["kind"] == "group"]
        assert labels == [
            "První skupina › Podskupina A",
            "Druhá skupina › První podskupina",
            "Druhá skupina › Druhá podskupina",
        ], labels
        assert service.group_offer_items is module.group_issued_offer_items

        normalized = service.normalize_item(
            {
                "row_type": "product",
                "purchase_unit_price": 100,
                "margin_pct": 35,
                "discount_pct": 4,
                "base_margin_pct_snapshot": 30,
                "base_discount_pct_snapshot": 8,
                "pricing_rule_source_snapshot": "Podskupina",
            },
            1,
            True,
        )
        assert normalized["base_margin_pct_snapshot"] == 30
        assert normalized["base_discount_pct_snapshot"] == 8
        assert normalized["pricing_rule_source_snapshot"] == "Podskupina"
        assert normalized["margin_pct"] == 35
        assert normalized["discount_pct"] == 4

        unresolved = service.normalize_item(
            {
                "row_type": "product",
                "product_code": "DOD-1",
                "name": "Dodavatelský název",
                "internal_code_snapshot": "",
                "internal_name_snapshot": "",
                "_v740_missing_internal_identity": True,
            }
        )
        assert unresolved["_v740_missing_internal_identity"]
        resolved = service.normalize_item(
            {
                **unresolved,
                "product_code": "TUR-001",
                "name": "Interní produkt TURTO",
                "internal_code_snapshot": "TUR-001",
                "internal_name_snapshot": "Interní produkt TURTO",
            }
        )
        assert not resolved["_v740_missing_internal_identity"]

    layer = (source / "v740_offer_defaults.py").read_text(encoding="utf-8")
    assert "Zákl. marže" in layer and "Zákl. sleva" in layer
    assert "pricing_rule_source_snapshot" in layer
    assert "product_code=internal_code" in layer
    assert "name=internal_name" in layer
    assert 'tree.bind("<Button-3>", popup, add=False)' in layer
    assert "Všichni dodavatelé" in layer
    assert "self.help_button" in layer
    assert "remove_columns_buttons(mivo)" in layer
    assert "_turto_v740_internal_identity_guard" in layer
    assert "vytvořit zákaznické PDF" in layer

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert "v740_offer_defaults" in launcher
    assert launcher.index("v730_polish.apply(app)") < launcher.index(
        "v740_offer_defaults.apply(app)"
    )
    publish = (repository / "scripts" / "publish-update.sh").read_text(
        encoding="utf-8"
    )
    assert "validate-7400-issued-pricing-columns.py" in publish
    assert "v740_offer_defaults.py" in publish
    version = (repository / "release_version.txt").read_text(
        encoding="utf-8"
    ).strip()
    try:
        version_tuple = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise AssertionError(version) from exc
    assert version_tuple >= (7, 4, 0), version
    print(
        f"OK {version}: internal issued-offer identity, pricing defaults, "
        "database ordering and uniform column controls"
    )


if __name__ == "__main__":
    main()
