"""Persistent data-location policy for TURTO CRM 8.0+.

Program files may live under LocalAppData/Program Files while business data stay
outside the installation.  This module is intentionally UI-free so it can be
used by the main EXE, the updater and validation tools.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any
from urllib.parse import quote

APP_DIR_NAME = "TURTO CRM"
CONFIG_NAME = "installation.json"
DEFAULT_DB_NAME = "zakazky.db"
CORE_TABLES = {
    "settings",
    "users",
    "companies",
    "people",
    "projects",
    "actions",
    "requests",
    "tasks",
}


def default_data_root() -> Path:
    if os.name == "nt":
        profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
        return profile / "Documents" / "TURTO Zakazky"
    return Path.home() / "Documents" / "TURTO Zakazky"


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / APP_DIR_NAME


def config_file() -> Path:
    return config_dir() / CONFIG_NAME


def _read_config() -> dict[str, Any]:
    path = config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_config(data: dict[str, Any]) -> Path:
    target = config_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(target)
    return target


def data_root() -> Path:
    env = str(os.environ.get("TURTO_CRM_DATA_ROOT", "")).strip()
    if env:
        return Path(env).expanduser()
    configured = str(_read_config().get("data_root") or "").strip()
    return Path(configured).expanduser() if configured else default_data_root()


def database_path() -> Path:
    env = str(os.environ.get("TURTO_CRM_DATABASE", "")).strip()
    if env:
        return Path(env).expanduser()
    configured = str(_read_config().get("database_path") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return data_root() / "data" / DEFAULT_DB_NAME


def ensure_data_directories() -> dict[str, Path]:
    root = data_root()
    paths = {
        "root": root,
        "data": root / "data",
        "backup": root / "backup",
        "updates": root / "updates",
        "logs": root / "logs",
        "test": root / "test_session",
    }
    for key in ("root", "data", "backup", "updates", "logs"):
        paths[key].mkdir(parents=True, exist_ok=True)
    database_path().parent.mkdir(parents=True, exist_ok=True)
    return paths


def use_default_location() -> dict[str, str]:
    root = default_data_root()
    db = root / "data" / DEFAULT_DB_NAME
    data = {
        "mode": "standard",
        "data_root": str(root),
        "database_path": str(db),
    }
    _write_config(data)
    ensure_data_directories()
    return data


def attach_database(path: str | Path, *, data_root_path: str | Path | None = None) -> dict[str, str]:
    db = Path(path).expanduser().resolve()
    validation = validate_database(db)
    if not validation["ok"]:
        raise ValueError(str(validation["message"]))
    root = Path(data_root_path).expanduser().resolve() if data_root_path else default_data_root()
    data = {
        "mode": "external-database",
        "data_root": str(root),
        "database_path": str(db),
    }
    _write_config(data)
    ensure_data_directories()
    return data


def copy_database_to_standard(path: str | Path, *, replace: bool = False) -> Path:
    source = Path(path).expanduser().resolve()
    validation = validate_database(source)
    if not validation["ok"]:
        raise ValueError(str(validation["message"]))

    root = default_data_root()
    target = root / "data" / DEFAULT_DB_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not replace:
        raise FileExistsError(target)

    temp = target.with_suffix(".importing.db")
    try:
        temp.unlink(missing_ok=True)
    except Exception:
        pass
    with sqlite3.connect(source) as src, sqlite3.connect(temp) as dst:
        src.backup(dst)
    copied = validate_database(temp)
    if not copied["ok"]:
        temp.unlink(missing_ok=True)
        raise ValueError("Zkopírovaná databáze neprošla kontrolou: " + str(copied["message"]))
    if target.exists():
        target.unlink()
    temp.replace(target)
    use_default_location()
    return target


def validate_database(path: str | Path) -> dict[str, Any]:
    db = Path(path).expanduser()
    result: dict[str, Any] = {
        "ok": False,
        "path": str(db),
        "message": "",
        "tables": [],
        "core_tables": [],
    }
    if not db.is_file():
        result["message"] = "Soubor databáze neexistuje."
        return result
    try:
        uri = "file:" + quote(str(db.resolve()).replace("\\", "/"), safe="/:_") + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as con:
            quick = con.execute("PRAGMA quick_check").fetchone()
            if not quick or str(quick[0]).strip().casefold() != "ok":
                result["message"] = "SQLite quick_check nevrátil stav OK."
                return result
            tables = {
                str(row[0])
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            }
        core = sorted(tables & CORE_TABLES)
        result["tables"] = sorted(tables)
        result["core_tables"] = core
        if len(core) < 4:
            result["message"] = "Soubor je platná SQLite databáze, ale nevypadá jako databáze TURTO CRM."
            return result
        result["ok"] = True
        result["message"] = "Databáze je v pořádku."
        return result
    except Exception as exc:
        result["message"] = f"Databázi se nepodařilo otevřít: {exc}"
        return result


def apply_to_app(module: Any) -> None:
    """Redirect legacy app globals before schema/bootstrap code starts using them."""
    root = data_root()
    db = database_path()
    module.DATA_ROOT = root
    module.DATA_DIR = root / "data"
    module.BACKUP_DIR = root / "backup"
    module.DB = db
    module.LIVE_DB = db
    module.TEST_DIR = root / "test_session"
    module.TEST_DB = module.TEST_DIR / "zakazky_test.db"
    module.TEST_MARKER = module.TEST_DIR / "active.txt"
    ensure_data_directories()


__all__ = [
    "attach_database",
    "apply_to_app",
    "config_file",
    "copy_database_to_standard",
    "data_root",
    "database_path",
    "default_data_root",
    "ensure_data_directories",
    "use_default_location",
    "validate_database",
]
