#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.5 table and issued-offer UX."""
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

    import v750_context_filters_offer_format
    from price_lists_domain.issued_offers import service

    class StubApp:
        def __init__(self, *args, **kwargs):
            return None

    class Module:
        App = StubApp

        def __init__(self, root: pathlib.Path):
            self.DB = root / "test.db"

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            return con

        def ensure_schema(self):
            with self.db() as con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS actions(
                      id INTEGER PRIMARY KEY,
                      name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS requests(
                      id INTEGER PRIMARY KEY,
                      item TEXT
                    );
                    CREATE TABLE IF NOT EXISTS business_document_items(
                      id INTEGER PRIMARY KEY,
                      document_id INTEGER,
                      position INTEGER,
                      row_type TEXT,
                      product_code TEXT,
                      internal_code_snapshot TEXT,
                      internal_name_snapshot TEXT,
                      name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS supplier_offer_items(
                      id INTEGER PRIMARY KEY,
                      product_code TEXT,
                      item_key TEXT,
                      original_name TEXT,
                      details TEXT
                    );
                    INSERT OR IGNORE INTO supplier_offer_items(
                      id,product_code,item_key,original_name,details
                    ) VALUES(
                      7,'DOD-007','DOD-007','Dodavatelský název',
                      'Technické provedení dodavatele'
                    );
                    """
                )

        @staticmethod
        def get_setting(_key, default=""):
            return default

    with tempfile.TemporaryDirectory(prefix="turto7500_") as temp:
        module = Module(pathlib.Path(temp))
        module.ensure_schema()

        # Isolate the 7.5 supplier-presentation transformation from the large
        # base draft builder while retaining the real service normalization.
        service.draft_from_supplier_offer = lambda _module, _offer_id: (
            {"currency": "CZK"},
            [
                service.normalize_item(
                    {
                        "row_type": "product",
                        "product_code": "TUR-OLD",
                        "item_key": "TUR-OLD",
                        "name": "Interní přepsaný název",
                        "internal_code_snapshot": "TUR-OLD",
                        "internal_name_snapshot": "Interní přepsaný název",
                        "source_supplier_offer_item_id": 7,
                        "quantity": 2,
                        "unit": "ks",
                        "purchase_unit_price": 100,
                        "margin_pct": 20,
                        "discount_pct": 5,
                    },
                    1,
                    True,
                )
            ],
        )

        v750_context_filters_offer_format.apply(module)
        module.ensure_schema()

        with module.db() as con:
            action_columns = {
                row[1] for row in con.execute("PRAGMA table_info(actions)")
            }
            request_columns = {
                row[1] for row in con.execute("PRAGMA table_info(requests)")
            }
            item_columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(business_document_items)"
                )
            }
        assert {"archived", "archived_at", "archived_by"} <= action_columns
        assert {"archived", "archived_at", "archived_by"} <= request_columns
        assert {
            "supplier_presentation_snapshot",
            "supplier_name_snapshot",
            "name_note_snapshot",
        } <= item_columns

        _document, items = service.draft_from_supplier_offer(module, 1)
        assert len(items) == 1
        item = items[0]
        assert item["supplier_presentation_snapshot"] == 1
        assert item["supplier_name_snapshot"] == "Dodavatelský název"
        assert item["product_code"] == ""
        assert item["internal_code_snapshot"] == ""
        assert item["internal_name_snapshot"] == ""
        assert item["name"] == "Dodavatelský název"
        assert not item["_v740_missing_internal_identity"]
        assert item["description"] == "Technické provedení dodavatele"

        supplemented = service.normalize_item(
            {
                **item,
                "name_note_snapshot": "atypické provedení 500 mm",
                "name": "Dodavatelský název – atypické provedení 500 mm",
            }
        )
        assert supplemented["name"] == (
            "Dodavatelský název – atypické provedení 500 mm"
        )
        assert supplemented["name_note_snapshot"] == "atypické provedení 500 mm"
        assert supplemented["product_code"] == ""

        # Editing the standard designation field must become an appended suffix,
        # not a replacement of the supplier snapshot.
        edited = service.normalize_item(
            {
                **item,
                "name": "poznámka doplněná uživatelem",
                "name_note_snapshot": "",
            }
        )
        assert edited["supplier_name_snapshot"] == "Dodavatelský název"
        assert edited["name_note_snapshot"] == "poznámka doplněná uživatelem"
        assert edited["name"] == (
            "Dodavatelský název – poznámka doplněná uživatelem"
        )

        regular = service.normalize_item(
            {
                "row_type": "product",
                "product_code": "TUR-001",
                "internal_code_snapshot": "TUR-001",
                "internal_name_snapshot": "Výrobek TURTO",
                "name": "Výrobek TURTO",
            }
        )
        assert regular["supplier_presentation_snapshot"] == 0
        assert regular["product_code"] == "TUR-001"

    class FakeTk:
        @staticmethod
        def splitlist(value):
            return tuple(str(value).split())

    class FakeTree:
        tk = FakeTk()

        def __init__(self):
            self.values = {
                "columns": ("A", "B", "C"),
                "displaycolumns": ("2", "0"),
            }

        def cget(self, key):
            return self.values[key]

    assert v750_context_filters_offer_format.displayed_columns(FakeTree()) == [
        "C",
        "A",
    ]


    class FakeScheduledTree:
        def __init__(self):
            self.exists = True
            self.callbacks = {}
            self.counter = 0
            self.sync_calls = 0
            self._sync_filter_bar = self.sync

        def winfo_exists(self):
            return self.exists

        def sync(self):
            self.sync_calls += 1

        def after(self, delay, callback):
            self.counter += 1
            token = f"after-{delay}-{self.counter}"
            self.callbacks[token] = callback
            return token

    scheduled = FakeScheduledTree()
    module.schedule_v750_filter_sync(scheduled)
    first_tick = scheduled._v750_filter_sync_tick
    module.schedule_v750_filter_sync(scheduled)
    assert scheduled._v750_filter_sync_tick == first_tick
    assert list(scheduled.callbacks) == [first_tick]
    scheduled.callbacks.pop(first_tick)()
    assert scheduled.sync_calls == 1
    assert scheduled._v750_filter_sync_tick is None

    module.schedule_v750_filter_sync(scheduled)
    tick_token = scheduled._v750_filter_sync_tick
    module.schedule_v750_filter_sync(scheduled, 80)
    delayed_token = scheduled._v750_filter_sync_after
    assert tick_token in scheduled.callbacks
    assert delayed_token in scheduled.callbacks
    scheduled.exists = False
    scheduled.callbacks.pop(tick_token)()
    scheduled.callbacks.pop(delayed_token)()
    assert scheduled.sync_calls == 1

    layer = (source / "v750_context_filters_offer_format.py").read_text(
        encoding="utf-8"
    )
    assert "tree.update_idletasks()" not in layer
    assert "filter_frame.update_idletasks()" not in layer
    assert "filter_frame.bind(" not in layer
    assert "after_idle(" not in layer
    for safety_token in (
        "_v750_filter_sync_tick",
        "_v750_filter_sync_after",
        "_v750_filter_sync_running",
        "geometry_matches",
        "_v750_filter_events_bound",
        "_v750_filter_sync_cleanup",
        "A failed schedule must never fall back",
    ):
        assert safety_token in layer, safety_token

    for token in (
        "displayed_columns(tree)",
        "widget.place_forget()",
        "_filter_cell_columns = [column",
        "Otevřít / upravit",
        "Vytvořit poptávku",
        "Přidat připomínku",
        "Obdrženo dnes",
        "Bez odezvy",
        "Archivovat vybrané",
        "Zobrazit archivované",
        "supplier_presentation_snapshot",
        'product_code=""',
        "Doplnit text k názvu…",
        "Formát výstupu: A4 · 210 × 297 mm",
    ):
        assert token in layer, token
    assert "_turto_v750_supplier_presentation_guard" in layer
    assert "_v750_context_owner" in layer

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert "v750_context_filters_offer_format" in launcher
    assert launcher.index("v740_offer_defaults.apply(app)") < launcher.index(
        "v750_context_filters_offer_format.apply(app)"
    )
    version = (repository / "release_version.txt").read_text(
        encoding="utf-8"
    ).strip()
    try:
        version_tuple = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise AssertionError(version) from exc
    assert version_tuple >= (7, 7, 4), version
    publish = (repository / "scripts" / "publish-update.sh").read_text(
        encoding="utf-8"
    )
    assert "validate-7500-context-filters-offer-format.py" in publish
    assert "v750_context_filters_offer_format.py" in publish
    print(
        "OK 7.7.4: filter cells follow visible columns, row actions use context "
        "menus, supplier names remain intact and A4 is visible"
    )


if __name__ == "__main__":
    main()