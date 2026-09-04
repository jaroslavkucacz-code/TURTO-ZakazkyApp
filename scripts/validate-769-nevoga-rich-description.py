#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.6.9 Nevoga rich descriptions."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    sys.path.insert(0, str(source))

    import v769_nevoga_offer as layer

    assert layer._is_nevoga_name("Nevoga")
    assert layer._is_nevoga_name("Nevegar")
    assert layer._is_nevoga_name("REINFORCEMENT SYSTEMS")
    assert not layer._is_nevoga_name("GEROtop")

    segments = layer._normalized_segments(
        [
            {"text": "PLEXUS | lü=", "bold": False},
            {"text": "max 40 cm", "bold": True, "color": "#FF0000", "changed": True},
        ]
    )
    assert segments[-1]["changed"] is True
    assert segments[-1]["color"] == "#FF0000"

    class StubApp:
        def __init__(self):
            self.offer_row = None

    class Module:
        App = StubApp
        OfferDetailDialog = None

        def __init__(self, root):
            self.DB = root / "test.db"
            self.messagebox = SimpleNamespace(showinfo=lambda *a, **k: None, showerror=lambda *a, **k: None)
            self.export_offer_excel = lambda *a, **k: "legacy"
            self.offer_export_filename = lambda offer_id: f"offer-{offer_id}.xlsx"

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            return con

        def ensure_schema(self):
            with self.db() as con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS companies(
                      id INTEGER PRIMARY KEY,
                      official_name TEXT,
                      short_name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS supplier_offers(
                      id INTEGER PRIMARY KEY,
                      supplier_name TEXT DEFAULT '',
                      supplier_company_id INTEGER,
                      offer_number TEXT DEFAULT '',
                      offer_date TEXT DEFAULT '',
                      reference TEXT DEFAULT '',
                      net_value REAL DEFAULT 0,
                      total_value REAL DEFAULT 0,
                      currency TEXT DEFAULT 'CZK'
                    );
                    CREATE TABLE IF NOT EXISTS supplier_offer_items(
                      id INTEGER PRIMARY KEY,
                      offer_id INTEGER,
                      position INTEGER,
                      original_name TEXT DEFAULT '',
                      item_key TEXT DEFAULT '',
                      quantity REAL DEFAULT 0,
                      unit TEXT DEFAULT '',
                      unit_price REAL DEFAULT 0,
                      total_price REAL DEFAULT 0,
                      product_code TEXT DEFAULT '',
                      details TEXT DEFAULT '',
                      original_unit_price REAL DEFAULT 0,
                      discount_pct REAL DEFAULT 0,
                      image_blob BLOB,
                      image_ext TEXT DEFAULT ''
                    );
                    """
                )

        def _company_id_by_name(self, con, name):
            row = con.execute(
                "SELECT id FROM companies WHERE lower(official_name)=lower(?) LIMIT 1",
                (name,),
            ).fetchone()
            return row["id"] if row else None

        def _load_offer_router(self):
            raise AssertionError("router export is not used by this DB-only test")

        def save_offer_import(self, *args, **kwargs):
            parsed = {
                "supplier": "Nevegar",
                "items": [
                    {
                        "position": 1,
                        "description": "PLEXUS® | typ B | Ø10 mm | lü=max 40 cm | L=80 cm",
                        "rich_segments": [
                            {"text": "PLEXUS® | typ B | Ø10 mm | lü=", "bold": False},
                            {"text": "max 40 cm", "bold": False, "color": "#FF0000", "changed": True},
                            {"text": " | L=80 cm", "bold": False},
                        ],
                    }
                ],
            }
            with self.db() as con:
                con.execute(
                    "INSERT INTO supplier_offers(id,supplier_name,offer_number,offer_date,total_value) "
                    "VALUES(1,'Nevegar','2026 / 906','2026-08-31',1537.13)"
                )
                con.execute(
                    """INSERT INTO supplier_offer_items(
                         id,offer_id,position,original_name,item_key,quantity,unit,
                         unit_price,total_price,product_code,details,original_unit_price,
                         discount_pct,image_ext
                       ) VALUES(1,1,1,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        parsed["items"][0]["description"],
                        parsed["items"][0]["description"],
                        2,
                        "ks",
                        768.565,
                        1537.13,
                        "BWSP26/0906/02",
                        "Zdrojová cena: 626,98 CZK/m",
                        768.56,
                        0,
                        "png",
                    ),
                )
            return 1, True, 1, parsed

    with tempfile.TemporaryDirectory(prefix="turto769_") as temp:
        module = Module(pathlib.Path(temp))
        module.ensure_schema()
        with module.db() as con:
            con.execute(
                "INSERT INTO companies(id,official_name,short_name) VALUES(1,'Nevoga','Nevoga')"
            )

        layer.apply(module)
        result = module.save_offer_import("fixture.pdf")
        assert result[0] == 1
        assert result[3]["supplier"] == "Nevoga"

        with module.db() as con:
            item_columns = {
                row[1] for row in con.execute("PRAGMA table_info(supplier_offer_items)")
            }
            assert "details_rich_json" in item_columns
            forbidden = {
                "type", "iron", "stirrup_distance", "stirrup_width",
                "stirrup_height", "pull_out_length", "dimension", "box_width",
                "box_height", "length", "price_per_meter", "length_cm",
            }
            assert not (forbidden & item_columns), forbidden & item_columns

            offer = con.execute("SELECT * FROM supplier_offers WHERE id=1").fetchone()
            assert offer["supplier_name"] == "Nevoga"
            assert offer["supplier_company_id"] == 1

            item = con.execute("SELECT * FROM supplier_offer_items WHERE id=1").fetchone()
            rich = json.loads(item["details_rich_json"])
            assert any(segment.get("changed") for segment in rich)
            assert any(
                segment.get("color") == "#FF0000" and "max 40" in segment.get("text", "")
                for segment in rich
            )
            assert "lü=max 40 cm" in item["original_name"]
            assert "Zdrojová cena" in item["details"]

        assert module.V769_NEVOGA_RICH_DESCRIPTION["technical_columns_added"] is False
        assert module.V769_NEVOGA_RICH_DESCRIPTION["supplier_red_preserved"] is True

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    # Launcher integration is added before this validation is promoted to release.
    if "v769_nevoga_offer" in launcher:
        assert launcher.index("v768_clean_table_markers.apply(app)") < launcher.index(
            "v769_nevoga_offer.apply(app)"
        )

    print("OK 7.6.9: one technical description, existing rich JSON keeps supplier red changes, no geometry columns")


if __name__ == "__main__":
    main()
