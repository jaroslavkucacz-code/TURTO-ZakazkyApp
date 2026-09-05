#!/usr/bin/env python3
"""Contract test for TURTO CRM 7.7 final runtime policy and rollback."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import pathlib
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

from PIL import Image


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (20, 14), (205, 180, 90)).save(stream, format="PNG")
    return stream.getvalue()


def _validate_same_hash_image_recovery(source: pathlib.Path) -> None:
    """A repeated MSG/PDF pass may not erase a previously usable image."""
    layer = _load(
        source / "v767_offer_reprocess_images.py",
        "v767_offer_reprocess_images_772_test",
    )
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        db_path = root / "offers.db"
        pdf_path = root / "same.pdf"
        pdf_path.write_bytes(b"same-pdf-from-msg")
        source_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        image = _png_bytes()

        con = sqlite3.connect(db_path)
        con.executescript(
            """
            CREATE TABLE supplier_offers(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              offer_date TEXT DEFAULT '', supplier_company_id INTEGER,
              customer_company_id INTEGER, action_id INTEGER,
              offer_number TEXT DEFAULT '', source_pdf TEXT DEFAULT '',
              source_hash TEXT NOT NULL UNIQUE, raw_text TEXT DEFAULT '',
              note TEXT DEFAULT '', updated_by TEXT DEFAULT '',
              imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
              supplier_name TEXT DEFAULT '', source_type TEXT DEFAULT 'PDF',
              reference TEXT DEFAULT '', gross_value REAL DEFAULT 0,
              discount_pct REAL DEFAULT 0, net_value REAL DEFAULT 0,
              total_value REAL DEFAULT 0
            );
            CREATE TABLE supplier_offer_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              offer_id INTEGER NOT NULL, position INTEGER DEFAULT 0,
              original_name TEXT DEFAULT '', item_key TEXT DEFAULT '',
              quantity REAL DEFAULT 0, unit TEXT DEFAULT '',
              unit_price REAL DEFAULT 0, discount REAL DEFAULT 0,
              net_price REAL DEFAULT 0, total_price REAL DEFAULT 0,
              image_path TEXT DEFAULT '', image_source_offer_date TEXT DEFAULT '',
              image_blob BLOB, image_ext TEXT DEFAULT '',
              product_code TEXT DEFAULT '', details TEXT DEFAULT '',
              original_unit_price REAL DEFAULT 0, discount_pct REAL DEFAULT 0,
              image_asset_key TEXT DEFAULT '', plexus_type TEXT DEFAULT ''
            );
            CREATE TABLE offer_item_aliases(
              item_key TEXT NOT NULL, alias TEXT NOT NULL,
              PRIMARY KEY(item_key,alias)
            );
            CREATE TABLE offer_product_images(
              supplier TEXT NOT NULL, item_key TEXT NOT NULL,
              image_blob BLOB NOT NULL, image_ext TEXT DEFAULT '',
              source_offer_no TEXT DEFAULT '', source_offer_date TEXT DEFAULT '',
              image_hash TEXT DEFAULT '',
              PRIMARY KEY(supplier,item_key)
            );
            CREATE TABLE offer_image_assets(
              asset_key TEXT PRIMARY KEY, supplier TEXT, family TEXT,
              type_code TEXT, image_blob BLOB, image_ext TEXT,
              image_hash TEXT, source_offer_no TEXT,
              source_offer_date TEXT, updated_at TEXT
            );
            """
        )
        offer_id = con.execute(
            """INSERT INTO supplier_offers(
                 offer_date,offer_number,source_pdf,source_hash,raw_text,
                 supplier_name,source_type,total_value)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                "2026-09-04",
                "P-IMAGE",
                "old.pdf",
                source_hash,
                "old",
                "GEROtop",
                "PDF",
                100,
            ),
        ).lastrowid
        con.execute(
            """INSERT INTO supplier_offer_items(
                 offer_id,position,original_name,item_key,quantity,unit,
                 unit_price,total_price,image_blob,image_ext,product_code)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                offer_id,
                10,
                "Položka s obrázkem",
                "Položka s obrázkem",
                1,
                "KS",
                100,
                100,
                sqlite3.Binary(image),
                "png",
                "IMG-1",
            ),
        )
        con.commit()
        con.close()

        parsed = {
            "supplier": "GEROtop",
            "offer_no": "P-IMAGE",
            "date": "04.09.2026",
            "source_type": "PDF",
            "net": 100,
            "items": [
                {
                    "position": 10,
                    "product": "IMG-1",
                    "description": "Položka s obrázkem",
                    "quantity": 1,
                    "unit": "KS",
                    "unit_price": 100,
                    "item_total": 100,
                    # Deliberately no image_bytes: this is the reported repeat
                    # processing path whose Excel still has a canonical image.
                }
            ],
        }

        def db():
            connection = sqlite3.connect(db_path)
            connection.row_factory = sqlite3.Row
            return connection

        def save_canonical(
            connection,
            supplier,
            item_key,
            image_bytes,
            image_ext,
            offer_no,
            offer_date,
        ):
            digest = hashlib.sha1(bytes(image_bytes)).hexdigest()
            connection.execute(
                """INSERT INTO offer_product_images(
                     supplier,item_key,image_blob,image_ext,source_offer_no,
                     source_offer_date,image_hash,updated_at)
                   VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
                   ON CONFLICT(supplier,item_key) DO UPDATE SET
                     image_blob=excluded.image_blob,
                     image_ext=excluded.image_ext,
                     image_hash=excluded.image_hash,
                     updated_at=CURRENT_TIMESTAMP""",
                (
                    supplier,
                    item_key,
                    sqlite3.Binary(image_bytes),
                    image_ext,
                    offer_no,
                    offer_date,
                    digest,
                ),
            )

        M = SimpleNamespace(
            ensure_schema=lambda: None,
            save_offer_import=lambda *args, **kwargs: (999, True, 0, {}),
            extract_offer_pdf=lambda _path: (parsed, "fresh"),
            db=db,
            _offer_date_iso=lambda _value: "2026-09-04",
            _stable_offer_key=lambda _con, _supplier, name, _date: name,
            _save_canonical_image=save_canonical,
            get_setting=lambda _key, default="": default,
            sqlite3=sqlite3,
        )

        layer.apply(M)
        result = M.save_offer_import(pdf_path)
        with db() as con:
            row = con.execute(
                "SELECT image_blob,image_ext FROM supplier_offer_items WHERE offer_id=?",
                (offer_id,),
            ).fetchone()
        assert row and bytes(row["image_blob"]) == image
        assert row["image_ext"] == "png"
        assert result[3]["images_preserved"] is True
        assert result[3]["images_restored_from_previous"] == 1
        assert result[3]["program_images_available"] == 1


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    repository = source.parent
    policy_path = source / "v770_runtime_policy.py"
    bootstrap_path = source / "runtime_bootstrap.py"
    updater_path = source / "crm_updater.pyw"
    launcher_path = source / "ZakazkyCRM.pyw"
    for path in (policy_path, bootstrap_path, updater_path, launcher_path):
        assert path.is_file(), path
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    policy = policy_path.read_text(encoding="utf-8")
    assert 'M.APP_NAME = "TURTO CRM"' in policy
    assert 'app.title("TURTO CRM")' in policy
    assert "turto_crm.ico" in policy and "turto_crm.png" in policy
    assert "_refresh_action_deadline_highlights = _attention_callback" in policy
    assert "_refresh_request_date_highlights = _request_attention_callback" in policy
    assert "_fit_action_tree" in policy and "_sync_filter_bar" in policy
    assert "_workarea_for_window" in policy and "MonitorFromWindow" in policy
    assert "_workarea_for_point" in policy and "MonitorFromPoint" in policy
    assert "_reposition_popup" in policy
    assert "_ensure_offer_plexus_images" in policy
    assert "offer_source_attachments" in policy and "source_pdf" in policy
    assert "offer_image_assets" in policy and "nevoga:plexus:" in policy
    assert "Obnovení předchozí verze" in policy
    assert "rollback_preserves_database" in policy

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    assert bootstrap.count('"v770_runtime_policy"') >= 1
    assert bootstrap.index('"v7616_requests_plexus_assets"') < bootstrap.index('"v770_runtime_policy"')
    launcher = launcher_path.read_text(encoding="utf-8")
    assert "runtime_bootstrap.apply_all(app)" in launcher
    launcher_tree = ast.parse(launcher, filename=str(launcher_path))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "apply"
        for node in ast.walk(launcher_tree)
    )

    updater = updater_path.read_text(encoding="utf-8")
    for token in ("_database_backup", "_snapshot_program", "latest.json", "--install", "rollback"):
        assert token in updater, token
    assert "src.backup(dst)" in updater
    assert '"_rollback"' in updater

    assert "def _ensure_icon_assets" in policy
    assert 'Image.new("RGBA"' in policy
    assert 'image.save(\n            ico' in policy or 'format="ICO"' in policy
    assert 'gold = (214, 169, 0, 255)' in policy

    reprocess = (source / "v767_offer_reprocess_images.py").read_text(encoding="utf-8")
    assert "images_restored_from_previous" in reprocess
    assert "program_images_available" in reprocess
    assert "offer_image_assets" in reprocess
    _validate_same_hash_image_recovery(source)

    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    version_parts = tuple(int(part) for part in version.split("."))
    assert len(version_parts) == 3, version
    assert version_parts[:2] == (7, 7) and version_parts >= (7, 7, 0), version
    publish = (repository / "scripts" / "publish-update.sh").read_text(encoding="utf-8")
    assert "validate-770-runtime-policy.py" in publish
    assert "rollback_manifest.json" in publish
    assert "ZakazkyApp_v7.6.16.zip" in publish
    print(
        f"OK {version}: identity, images after repeated MSG processing, PLEXUS "
        "assets, deadlines, monitor policy and reversible updater"
    )


if __name__ == "__main__":
    main()
