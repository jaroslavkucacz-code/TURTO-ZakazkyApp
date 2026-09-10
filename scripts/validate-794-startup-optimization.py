#!/usr/bin/env python3
"""Regression checks for TURTO CRM startup optimization."""
from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
import tempfile


def load_module(root: pathlib.Path):
    path = root / "price_lists_domain" / "platform" / "startup_optimization.py"
    spec = importlib.util.spec_from_file_location("startup_optimization", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_v760_finalize():
    namespace = {}
    exec(
        compile(
            "def finalize():\n    return None\n",
            "v760_table_activity_performance.py",
            "exec",
        ),
        namespace,
    )
    return namespace["finalize"]


def make_v770_step(ids):
    namespace = {}
    exec(
        compile(
            "def make_step(ids):\n"
            "    def step(index=0):\n"
            "        return ids[index] if index < len(ids) else None\n"
            "    return step\n",
            "v770_runtime_policy.py",
            "exec",
        ),
        namespace,
    )
    return namespace["make_step"](ids)


def make_v628_callback(target_name: str):
    namespace = {}
    source = (
        "def outer():\n"
        f"    def {target_name}(app):\n"
        "        return None\n"
        "    app = object()\n"
        f"    return lambda: {target_name}(app)\n"
    )
    exec(compile(source, "v628_modernui_resize.py", "exec"), namespace)
    return namespace["outer"]()


class Module:
    def __init__(self, db_path: pathlib.Path):
        self.path = db_path

    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con


def build_asset_db(path: pathlib.Path) -> Module:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE supplier_offer_items(
            id INTEGER PRIMARY KEY,
            offer_id INTEGER NOT NULL,
            original_name TEXT DEFAULT '',
            item_key TEXT DEFAULT '',
            image_asset_key TEXT DEFAULT ''
        );
        CREATE TABLE offer_image_assets(
            asset_key TEXT PRIMARY KEY,
            image_blob BLOB
        );
        INSERT INTO supplier_offer_items(id,offer_id,original_name,item_key,image_asset_key)
        VALUES
            (1,1,'PLEXUS Typ A','',''),
            (2,2,'PLEXUS Typ B','','nevoga:plexus:B'),
            (3,3,'Jiný výrobek','','');
        INSERT INTO offer_image_assets(asset_key,image_blob)
        VALUES('nevoga:plexus:B',X'010203');
        """
    )
    con.commit()
    con.close()
    return Module(path)


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    startup = load_module(root)

    finalize = make_v760_finalize()
    assert not startup._is_redundant_v760_finalize(0, finalize)
    assert startup._is_redundant_v760_finalize(260, finalize)
    assert startup._is_redundant_v760_finalize(1200, finalize)
    assert not startup._is_redundant_v760_finalize(261, finalize)
    assert not startup._is_redundant_v760_finalize(260, lambda: None)

    palette = make_v628_callback("apply_modern_palette")
    dashboard = make_v628_callback("dashboard_layout")
    detach = make_v628_callback("detach_hidden_pages")
    outlook = make_v628_callback("install_outlook_indicator")
    assert startup._redundant_v628_cosmetic(1550, palette) == "apply_modern_palette"
    assert startup._redundant_v628_cosmetic(1750, dashboard) == "dashboard_layout"
    assert startup._redundant_v628_cosmetic(1450, detach) is None
    assert startup._redundant_v628_cosmetic(1900, outlook) is None
    assert startup._redundant_v628_cosmetic(1550, dashboard) is None
    assert startup._redundant_v628_cosmetic(1750, palette) is None

    with tempfile.TemporaryDirectory(prefix="turto794_start_") as td:
        db_path = pathlib.Path(td) / "assets.db"
        M = build_asset_db(db_path)
        ids = [1, 2, 3]
        before, after = startup.prune_plexus_backfill_ids(M, ids)
        assert (before, after) == (3, 1)
        assert ids == [1]

        # On a legacy schema the optimizer must fall back to the original repair.
        legacy_path = pathlib.Path(td) / "legacy.db"
        con = sqlite3.connect(legacy_path)
        con.execute(
            "CREATE TABLE supplier_offer_items(id INTEGER PRIMARY KEY, offer_id INTEGER, original_name TEXT)"
        )
        con.commit()
        con.close()
        legacy = Module(legacy_path)
        legacy_ids = [7, 8]
        assert startup.prune_plexus_backfill_ids(legacy, legacy_ids) == (2, 2)
        assert legacy_ids == [7, 8]

        class Instance:
            def __init__(self):
                self.calls = []

            def after(self, delay, callback=None, *args):
                self.calls.append((int(delay), callback, args))
                return f"after-{len(self.calls)}"

        # Resolved offer 2 should disappear before v770's 800 ms backfill starts.
        resolved_ids = [2]
        plexus_step = make_v770_step(resolved_ids)
        assert startup._is_v770_plexus_backfill(800, plexus_step)
        instance = Instance()

        def previous_init(current):
            current.after(0, finalize)
            current.after(260, finalize)
            current.after(1200, finalize)
            # Preserve the functional v628 delayed passes, but coalesce the two
            # cosmetic repeats whose real work already has an after_idle pass.
            current.after(1450, detach)
            current.after(1550, palette)
            current.after(1750, dashboard)
            current.after(1900, outlook)
            current.after(800, plexus_step)
            current.after(135, lambda: None)
            return "ok"

        result = startup._call_previous_init_optimized(M, instance, previous_init)
        assert result == "ok"
        assert [delay for delay, _callback, _args in instance.calls] == [0, 1450, 1900, 135]
        assert instance._turto_v760_finalizers_coalesced == (260, 1200)
        assert instance._turto_v628_cosmetic_passes_coalesced == (
            (1550, "apply_modern_palette"),
            (1750, "dashboard_layout"),
        )
        assert instance._turto_plexus_backfill_candidates == 1
        assert instance._turto_plexus_backfill_pending == 0
        assert resolved_ids == []

        # An unresolved offer still keeps the original delayed repair schedule.
        unresolved_ids = [1]
        unresolved_step = make_v770_step(unresolved_ids)
        second = Instance()

        def previous_unresolved(current):
            current.after(800, unresolved_step)
            return "ok"

        startup._call_previous_init_optimized(M, second, previous_unresolved)
        assert [delay for delay, _callback, _args in second.calls] == [800]
        assert unresolved_ids == [1]
        assert second._turto_plexus_backfill_pending == 1

    bootstrap = (root / "runtime_bootstrap.py").read_text(encoding="utf-8")
    ui_token = '"price_lists_domain.platform.ui_cleanup_793"'
    startup_token = '"price_lists_domain.platform.startup_optimization"'
    assert ui_token in bootstrap and startup_token in bootstrap
    assert bootstrap.index(ui_token) < bootstrap.index(startup_token)

    print("TURTO CRM startup optimization: OK")


if __name__ == "__main__":
    main()
