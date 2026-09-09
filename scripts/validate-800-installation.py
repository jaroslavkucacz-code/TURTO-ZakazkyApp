#!/usr/bin/env python3
"""Regression checks for the TURTO CRM 8.0 EXE/installer foundation."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sqlite3
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
    con = sqlite3.connect(path)
    try:
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
        con.commit()
    finally:
        con.close()


def table_names(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {
            str(row[0])
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        con.close()


def assert_renameable(path: Path) -> None:
    """Windows-specific contract: no SQLite helper may leave a live file handle."""
    moved = path.with_name(path.stem + ".handle-check" + path.suffix)
    moved.unlink(missing_ok=True)
    path.replace(moved)
    moved.replace(path)


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
            assert_renameable(source)

            attached = data.attach_database(source)
            assert data.database_path() == source.resolve()
            cfg = json.loads(data.config_file().read_text(encoding="utf-8"))
            assert cfg["mode"] == "external-database"
            backup = Path(attached["first_attach_backup"])
            assert backup.is_file()
            assert data.validate_database(backup)["ok"]
            assert_renameable(source)
            assert_renameable(backup)

            data.use_default_location()
            assert data.database_path() == expected_root / "data" / "zakazky.db"
            copied = data.copy_database_to_standard(source)
            assert copied == expected_root / "data" / "zakazky.db"
            assert data.validate_database(copied)["ok"]
            assert_renameable(source)
            assert_renameable(copied)

            # On-demand database management must be able to replace an existing
            # standard DB only after preserving the previous valid DB first.
            replacement = root / "transfer" / "replacement_zakazky.db"
            create_crm_db(replacement)
            con = sqlite3.connect(replacement)
            try:
                con.execute("CREATE TABLE replacement_marker(id INTEGER PRIMARY KEY)")
                con.commit()
            finally:
                con.close()
            previous_backup = data.backup_database(
                copied,
                label="pred_nahrazenim_databaze",
                backup_root=expected_root,
            )
            replaced = data.copy_database_to_standard(replacement, replace=True)
            assert replaced == copied
            assert data.validate_database(previous_backup)["ok"]
            assert data.validate_database(replaced)["ok"]
            assert "replacement_marker" not in table_names(previous_backup)
            assert "replacement_marker" in table_names(replaced)
            assert_renameable(previous_backup)
            assert_renameable(replaced)
            assert_renameable(replacement)

            fake = type("AppModule", (), {})()
            data.apply_to_app(fake)
            assert fake.DB == replaced
            assert fake.LIVE_DB == replaced
            assert fake.BACKUP_DIR == expected_root / "backup"

        launcher = (repo / "build" / "windows" / "launcher_800.pyw").read_text(encoding="utf-8")
        import_app = launcher.index("\nimport app")
        assert launcher.index("ensure_data_location") < import_app
        assert launcher.index('DATA_SETUP = "--data-setup"') < import_app
        assert launcher.index("configure_data_location(force=True)") < import_app
        assert 'app.APP_VERSION = "8.0.0-preview.1"' in launcher
        assert "data_location.apply_to_app(app)" in launcher
        assert "def _baseline_schema_ready(app)" in launcher
        assert '{"users", "settings", "companies", "actions"}.issubset(names)' in launcher
        baseline_guard = launcher.index("if not _baseline_schema_ready(app):")
        first_schema = launcher.index('_run_phase("baseline-schema", app.ensure_schema)', baseline_guard)
        runtime_apply = launcher.index('_run_phase("runtime-apply", lambda: runtime_bootstrap.apply_all(app))')
        final_schema = launcher.index('_run_phase("schema-final", app.ensure_schema)', runtime_apply)
        assert baseline_guard < first_schema < runtime_apply < final_schema
        assert "exe_distribution.apply(app)" in launcher

        onboarding = (base / "data_onboarding.py").read_text(encoding="utf-8")
        assert "allow_replace_standard" in onboarding
        assert 'label="pred_nahrazenim_databaze"' in onboarding
        assert "copy_database_to_standard(source_path, replace=True)" in onboarding
        assert "Před změnou databáze zavřete" in onboarding

        platform_dir = base / "price_lists_domain" / "platform"
        shadowed = sorted(
            source.stem
            for source in platform_dir.glob("*.py")
            if source.name != "__init__.py" and (platform_dir / source.stem / "__init__.py").exists()
        )
        assert not shadowed, f"PyInstaller-unsafe platform file/package collisions: {shadowed}"

        lazy_refresh = (platform_dir / "lazy_refresh.py").read_text(encoding="utf-8")
        assert "def _install_safe_backup(module)" in lazy_refresh
        assert "source.backup(destination" in lazy_refresh
        assert not (platform_dir / "lazy_refresh" / "__init__.py").exists()
        assert not (platform_dir / "worksets" / "__init__.py").exists()
        assert not (platform_dir / "database" / "__init__.py").exists()
        assert not (platform_dir / "compat.py").exists()
        assert (platform_dir / "compat" / "__init__.py").is_file()

        exe_policy = (platform_dir / "exe_distribution.py").read_text(encoding="utf-8")
        assert 'WINDOWS_MANIFEST = "latest-windows.json"' in exe_policy
        assert 'WINDOWS_MANIFEST_FORMAT = "turto-crm-windows-update-v1"' in exe_policy
        assert 'UPDATER_EXE = "TURTO CRM Updater.exe"' in exe_policy
        assert "def _validate_windows_manifest" in exe_policy
        assert "def _download_windows_package" in exe_policy
        assert "actual_sha != expected_sha" in exe_policy
        assert "M._turto_windows_expected_update_sha256" in exe_policy
        assert "tempfile.mkdtemp" in exe_policy
        assert "shutil.copy2(installed_updater, temp_updater)" in exe_policy
        assert "M._download_update_package = download_package" in exe_policy

        updater = (repo / "build" / "windows" / "updater_800.pyw").read_text(encoding="utf-8")
        assert 'MAIN_EXE = "TURTO CRM.exe"' in updater
        assert "data_location.database_path()" in updater
        assert "data_location.backup_database(" in updater
        assert 'path.name.casefold().startswith("unins")' in updater
        assert "_database_backup(label)" in updater
        assert "_snapshot_program(target, current_version)" in updater
        assert "def _verify_package_hash" in updater
        assert "def _safe_extract" in updater
        assert "def _restore_program_snapshot" in updater
        assert "def _replace_program_with_rollback" in updater
        assert "_validate_release(target, installed=True)" in updater
        assert "původní verze byla automaticky obnovena" in updater

        updater_behavior = repo / "scripts" / "validate-800-updater-transaction.py"
        assert updater_behavior.is_file()

        data_source = (base / "data_location.py").read_text(encoding="utf-8")
        assert "def backup_database(" in data_source
        assert '"first_attach_backup"' in data_source
        assert "con.close()" in data_source

        icon = base / "turto_logo.ico"
        assert icon.is_file(), "Canonical TURTO Windows icon is missing"
        spec = (repo / "build" / "windows" / "TURTO_CRM.spec").read_text(encoding="utf-8")
        assert "exclude_binaries=True" in spec
        assert 'name="TURTO CRM"' in spec
        assert 'collect_submodules("price_lists_domain")' in spec
        assert 'ICON = BASE / "turto_logo.ico"' in spec
        assert "icon=str(ICON)" in spec
        assert not (repo / "build" / "windows" / "TURTO_CRM_Diagnostic.spec").exists()

        updater_spec = (repo / "build" / "windows" / "TURTO_CRM_Updater.spec").read_text(encoding="utf-8")
        assert 'name="TURTO CRM Updater"' in updater_spec
        assert "a.binaries" in updater_spec and "a.datas" in updater_spec
        assert 'ICON = BASE / "turto_logo.ico"' in updater_spec

        installer = (repo / "build" / "windows" / "TURTO_CRM.iss").read_text(encoding="utf-8")
        assert "DefaultDirName={localappdata}\\Programs\\TURTO CRM" in installer
        assert "PrivilegesRequired=lowest" in installer
        assert 'Filename: "{app}\\{#MyAppExeName}"' in installer
        assert 'Parameters: "--data-setup"' in installer
        assert "Připojit nebo změnit databázi" in installer
        assert "SetupIconFile=..\\..\\ZakazkyApp_base_6.1\\turto_logo.ico" in installer
        assert "TURTO Zakazky" not in installer

        workflow = (repo / ".github" / "workflows" / "validate-800-windows-installer.yml").read_text(encoding="utf-8")
        assert "clean-install-smoke:" in workflow
        assert "needs: build-windows-preview" in workflow
        assert "actions/download-artifact@v4" in workflow
        assert "Cold frozen runtime first start" in workflow
        assert "validate-800-updater-transaction.py" in workflow
        assert "TURTO_CRM_Diagnostic.spec" not in workflow

    finally:
        os.environ.clear()
        os.environ.update(old_env)

    print("TURTO CRM 8.0 EXE/installer foundation: OK")


if __name__ == "__main__":
    main()
