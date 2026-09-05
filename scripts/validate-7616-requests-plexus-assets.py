#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.6.16 request UI and PLEXUS image assets."""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
import tempfile


def _load_layer(source: pathlib.Path):
    path = source / "v7616_requests_plexus_assets.py"
    spec = importlib.util.spec_from_file_location("_turto_v7616_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeFrame:
    def __init__(self):
        self.columns = {}

    def columnconfigure(self, index, **kwargs):
        self.columns[int(index)] = dict(kwargs)


class FakeTree:
    def __init__(self, columns):
        self.columns = tuple(columns)
        self.column_cfg = {c: {"width": 1, "anchor": "center"} for c in self.columns}
        self.heading_cfg = {c: {"anchor": "center"} for c in self.columns}
        self.rows = {
            "r1": {"Poptáno": "⚠ 01.08.2026", "tags": ("req_old",)},
            "r2": {"Poptáno": "03.09.2026", "tags": ("req_fresh",)},
        }
        self.tags = {}
        self.bindings = []
        self._filter_frame = FakeFrame()
        self.sync_calls = 0
        self._sync_filter_bar = lambda: setattr(self, "sync_calls", self.sync_calls + 1)

    def __getitem__(self, key):
        if key == "columns":
            return self.columns
        raise KeyError(key)

    def column(self, column, option=None, **kwargs):
        if kwargs:
            self.column_cfg[column].update(kwargs)
        if option:
            return self.column_cfg[column].get(option)
        return dict(self.column_cfg[column])

    def heading(self, column, option=None, **kwargs):
        if kwargs:
            self.heading_cfg[column].update(kwargs)
        if option:
            return self.heading_cfg[column].get(option)
        return dict(self.heading_cfg[column])

    def bind(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))

    def after_idle(self, callback):
        callback()

    def tag_configure(self, tag, **kwargs):
        self.tags[tag] = dict(kwargs)

    def exists(self, iid):
        return iid in self.rows

    def set(self, iid, column, value=None):
        if value is None:
            return self.rows[iid].get(column, "")
        self.rows[iid][column] = value

    def item(self, iid, option=None, **kwargs):
        if kwargs and "tags" in kwargs:
            self.rows[iid]["tags"] = tuple(kwargs["tags"])
        if option == "tags":
            return self.rows[iid].get("tags", ())
        return {"tags": self.rows[iid].get("tags", ())}


class App:
    def build_requests(self):
        # Reproduce the legacy mismatch: all nine columns exist, but the final
        # column was never configured because app.py used zip(cols, eight widths).
        self.request_tree = FakeTree(
            (
                "Stav", "Řeší", "Poptáno", "Obdrženo", "Odběratel",
                "Dodavatel", "Akce", "Poptáváno", "Příjemci",
            )
        )
        return self.request_tree

    def after_idle(self, callback):
        callback()


class Module:
    App = App

    def __init__(self, db_path: pathlib.Path):
        self.DB = db_path
        self.messagebox = type(
            "Messagebox",
            (),
            {"showinfo": staticmethod(lambda *a, **k: None),
             "showerror": staticmethod(lambda *a, **k: None)},
        )

    def db(self):
        con = sqlite3.connect(self.DB)
        con.row_factory = sqlite3.Row
        return con

    def ensure_schema(self):
        with self.db() as con:
            con.executescript(
                """
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
                  product_code TEXT DEFAULT '',
                  quantity REAL DEFAULT 0,
                  unit TEXT DEFAULT '',
                  original_unit_price REAL DEFAULT 0,
                  discount_pct REAL DEFAULT 0,
                  unit_price REAL DEFAULT 0,
                  total_price REAL DEFAULT 0,
                  details TEXT DEFAULT '',
                  details_rich_json TEXT DEFAULT '',
                  image_source_offer_date TEXT DEFAULT '',
                  image_blob BLOB,
                  image_ext TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS offer_product_images(
                  supplier TEXT NOT NULL,
                  item_key TEXT NOT NULL,
                  image_blob BLOB NOT NULL,
                  image_ext TEXT DEFAULT '',
                  source_offer_no TEXT DEFAULT '',
                  source_offer_date TEXT DEFAULT '',
                  image_hash TEXT DEFAULT '',
                  updated_at TEXT DEFAULT '',
                  PRIMARY KEY(supplier,item_key)
                );
                """
            )

    @staticmethod
    def save_offer_import(*_args, **_kwargs):
        return (0, False, 0, {})



def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    layer = _load_layer(source)

    assert len(layer.REQUEST_COLUMNS) == 9
    assert len(layer.REQUEST_WIDTHS) == 9
    assert layer.REQUEST_COLUMNS[-1] == "Příjemci"
    assert layer._plexus_type("PLEXUS® | typ B | Ø10 mm") == "B"
    assert layer._plexus_type("PLEXUS® | typ CC | Ø10 mm") == "CC"

    with tempfile.TemporaryDirectory(prefix="turto7616_") as temp:
        module = Module(pathlib.Path(temp) / "test.db")
        module.ensure_schema()
        image = b"PLEXUS-B-IMAGE"
        other = b"OTHER-SUPPLIER-IMAGE"
        with module.db() as con:
            con.executemany(
                "INSERT INTO supplier_offers(id,supplier_name,offer_number,offer_date) VALUES(?,?,?,?)",
                (
                    (1, "Nevoga", "2026 / 906", "2026-08-31"),
                    (2, "Nevoga s.r.o.", "2026 / 999", "2026-09-01"),
                    (3, "Leviat", "10380000", "2026-09-01"),
                    (4, "Nevoga", "2026 / 1000", "2026-09-02"),
                ),
            )
            con.executemany(
                """INSERT INTO supplier_offer_items(
                       id,offer_id,position,original_name,item_key,image_blob,image_ext
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    (11, 1, 1, "PLEXUS® | typ B | L=125 cm", "nevoga-b-125", image, "png"),
                    (12, 2, 1, "PLEXUS® | typ B | L=80 cm", "nevoga-b-80", image, "png"),
                    (13, 3, 1, "HIT", "leviat-hit", other, "png"),
                    (14, 4, 1, "PLEXUS® | typ C | L=100 cm", "nevoga-c-100", None, ""),
                ),
            )
            con.executemany(
                """INSERT INTO offer_product_images(
                       supplier,item_key,image_blob,image_ext,source_offer_no,source_offer_date
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    ("Nevoga", "nevoga-b-125", image, "png", "2026 / 906", "2026-08-31"),
                    ("Nevoga s.r.o.", "nevoga-b-80", image, "png", "2026 / 999", "2026-09-01"),
                    ("Leviat", "leviat-hit", other, "png", "10380000", "2026-09-01"),
                ),
            )

        layer.apply(module)
        module.ensure_schema()

        with module.db() as con:
            assets = con.execute(
                "SELECT * FROM offer_image_assets ORDER BY asset_key"
            ).fetchall()
            assert len(assets) == 1, [dict(row) for row in assets]
            assert assets[0]["asset_key"] == "nevoga:plexus:B"
            assert assets[0]["type_code"] == "B"
            assert bytes(assets[0]["image_blob"]) == image

            nevoga_rows = con.execute(
                "SELECT * FROM supplier_offer_items WHERE id IN (11,12) ORDER BY id"
            ).fetchall()
            assert all(row["image_blob"] is None for row in nevoga_rows)
            assert all(row["image_asset_key"] == "nevoga:plexus:B" for row in nevoga_rows)
            assert all(row["plexus_type"] == "B" for row in nevoga_rows)

            leviat = con.execute(
                "SELECT image_blob,image_asset_key FROM supplier_offer_items WHERE id=13"
            ).fetchone()
            assert bytes(leviat["image_blob"]) == other
            assert not str(leviat["image_asset_key"] or "")

            assert con.execute(
                "SELECT COUNT(*) FROM offer_product_images WHERE lower(supplier) LIKE '%nevoga%'"
            ).fetchone()[0] == 0
            assert con.execute(
                "SELECT COUNT(*) FROM offer_product_images WHERE supplier='Leviat'"
            ).fetchone()[0] == 1

            resolved = module.resolve_offer_item_image(con, nevoga_rows[0], "Nevoga")
            assert resolved and bytes(resolved["image_blob"]) == image
            assert resolved["type_code"] == "B"

        parsed = {
            "supplier": "Nevoga",
            "offer_no": "2026 / 1000",
            "date": "02.09.2026",
            "items": [
                {
                    "position": 1,
                    "description": "PLEXUS® | typ C | L=100 cm",
                    "plexus_type": "C",
                    "image_bytes": b"PLEXUS-C-IMAGE",
                    "image_ext": "png",
                }
            ],
        }
        assert layer._centralize_parsed_plexus(module, 4, parsed) == 1
        with module.db() as con:
            assert con.execute("SELECT COUNT(*) FROM offer_image_assets").fetchone()[0] == 2
            c_row = con.execute(
                "SELECT * FROM supplier_offer_items WHERE id=14"
            ).fetchone()
            assert c_row["image_asset_key"] == "nevoga:plexus:C"
            assert c_row["plexus_type"] == "C"
            assert c_row["image_blob"] is None
            resolved_c = module.resolve_offer_item_image(con, c_row, "Nevoga")
            assert bytes(resolved_c["image_blob"]) == b"PLEXUS-C-IMAGE"

        app = App()
        tree = app.build_requests()
        for column, width in zip(layer.REQUEST_COLUMNS, layer.REQUEST_WIDTHS):
            assert tree.column_cfg[column]["width"] == width
            assert tree.column_cfg[column]["anchor"] == "w"
            assert tree.heading_cfg[column]["anchor"] == "w"
        assert set(tree._filter_frame.columns) == set(range(9))
        assert tree.sync_calls >= 1

        app._refresh_request_date_highlights(
            tree,
            (("r1", True), ("r2", False)),
        )
        assert tree.rows["r1"]["Poptáno"] == "01.08.2026"
        assert "req_old" in tree.rows["r1"]["tags"]
        assert layer.OVERDUE_TAG in tree.rows["r1"]["tags"]
        assert layer.OVERDUE_TAG not in tree.rows["r2"]["tags"]
        assert tree.tags[layer.OVERDUE_TAG]["font"][-1] == "bold"

    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    version_tuple = tuple(int(part) for part in version.split("."))
    assert version_tuple >= (7, 6, 16), version
    if version_tuple >= (7, 7, 0):
        bootstrap = (source / "runtime_bootstrap.py").read_text(encoding="utf-8")
        assert '"v7615_nevoga_meter_units"' in bootstrap
        assert '"v7616_requests_plexus_assets"' in bootstrap
        assert bootstrap.index('"v7615_nevoga_meter_units"') < bootstrap.index(
            '"v7616_requests_plexus_assets"'
        )
        assert '"v7616_requests_plexus_assets"' < 'z'
    else:
        bridge = (source / "v768_clean_table_markers.py").read_text(encoding="utf-8")
        assert "import v7616_requests_plexus_assets" in bridge
        assert "v7616_requests_plexus_assets.apply(M)" in bridge
        assert bridge.index("v7615_nevoga_meter_units.apply(M)") < bridge.index(
            "v7616_requests_plexus_assets.apply(M)"
        )
    print(
        f"OK {version}: Poptavky headings align with rows, long waits are bold, "
        "and PLEXUS drawings are deduplicated per type in the database"
    )


if __name__ == "__main__":
    main()
