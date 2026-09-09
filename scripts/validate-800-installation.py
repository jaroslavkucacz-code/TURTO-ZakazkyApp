#!/usr/bin/env python3
"""Regression checks for the TURTO CRM 8.0 EXE/installer foundation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def load_data_location(base: Path):
    path = base / "data_location.py"
    spec = importlib.util.spec_from_file_location("data_location_800_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def create_crm_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE companies(id INTEGER PRIMARY KEY,official_name TEXT);
            CREATE TABLE people(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
            CREATE TABLE actions(id INTEGER PRIMARY KEY,name TEXT);
            """
        )


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    old_env = dict(os.environ)
    try:
        with tempfile.TemporaryDirectory(prefix="turto800_install_") as td:
            root = Path(td)
            os.environ["USERPROFILE"] = str(root / "profile")
            os.environ["LOCALAPPDATA"] = str(root / "local")
            os.environ.pop("TURTO_CRM_DATA_ROOT", None)
            os.environ.pop("TURTO_CRM_DATABASE", None)
            data = load_data_location(base)

            expected_root = Path(os.environ["USERPROFILE"]) / "Documents" / "TURTO Zakazky"
            assert data.default_data_root() == expected_root
            assert data.database_path() == expected_root / "data" / "zakazky.db"

            source = root / "transfer" / "old_zakazky.db"
            create_crm_db(source)
            check = data.validate_database(source)
            assert check["ok"], check
            assert len(check["core_tables"]) >= 4

            data.attach_database(source)
            assert data.database_path() == source.resolve()
            cfg = json.loads(data.config_file().read_text(encoding="utf-8"))
            assert cfg["mode"] == "external-database"

            data.use_default_location()
            assert data.database_path() == expected_root / "data" / "zakazky.db"
            copied = data.copy_database_to_standard(source)
            assert copied == expected_root / "data" / "zakazky.db"
            assert data.validate_database(copied)["ok"]

            fake = type("AppModule", (), {})()
            data.apply_to_app(fake)
            assert fake.DB == copied
            assert fake.LIVE_DB == copied
            assert fake.BACKUP_DIR == expected_root / "backup"

        launcher = (repo / "build" / "windows" / "launcher_800.pyw").read_text(encoding="utf-8")
        assert launcher.index("ensure_data_location") < launcher.index("import app")
        assert 'app.APP_VERSION = "8.0.0-preview.1"' in launcher
        assert "data_location.apply_to_app(app)" in launcher
        assert "exe_distribution.apply(app)" in launcher

        exe_policy = (base / "price_lists_domain" / "platform" / "exe_distribution.py").read_text(encoding="utf-8")
        assert 'WINDOWS_MANIFEST = "latest-windows.json"' in exe_policy
        assert 'UPDATER_EXE = "TURTO CRM Updater.exe"' in exe_policy
        assert "tempfile.mkdtemp" in exe_policy
        assert "shutil.copy2(installed_updater, temp_updater)" in exe_policy

        updater = (repo / "build" / "windows" / "updater_800.pyw").read_text(encoding="utf-8")
        assert 'MAIN_EXE = "TURTO CRM.exe"' in updater
        assert "data_location.database_path()" in updater
        assert 'path.name.casefold().startswith("unins")' in updater
        assert "_database_backup(label)" in updater
        assert "_snapshot_program(target, current_version)" in updater

        spec = (repo / "build" / "windows" / "TURTO_CRM.spec").read_text(encoding="utf-8")
        assert "exclude_binaries=True" in spec
        assert 'name="TURTO CRM"' in spec
        assert 'collect_submodules("price_lists_domain")' in spec
        updater_spec = (repo / "build" / "windows" / "TURTO_CRM_Updater.spec").read_text(encoding="utf-8")
        assert 'name="TURTO CRM Updater"' in updater_spec
        assert "a.binaries" in updater_spec and "a.datas" in updater_spec

        installer = (repo / "build" / "windows" / "TURTO_CRM.iss").read_text(encoding="utf-8")
        assert "DefaultDirName={localappdata}\\Programs\\TURTO CRM" in installer
        assert "PrivilegesRequired=lowest" in installer
        assert 'Filename: "{app}\\{#MyAppExeName}"' in installer
        assert "TURTO Zakazky" not in installer.replace(
            "{ Business data intentionally live outside {app}. The first-run wizard owns\n      creation or attachment of the SQLite database. Uninstall never removes it. }",
            "",
        )

    finally:
        os.environ.clear()
        os.environ.update(old_env)

    print("TURTO CRM 8.0 EXE/installer foundation: OK")


if __name__ == "__main__":
    main()
