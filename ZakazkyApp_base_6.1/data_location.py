"""Persistent data-location policy for TURTO CRM 8.0+.

Program files may live under LocalAppData/Program Files while business data stay
outside the installation. This module is intentionally UI-free so it can be
used by the main EXE, the updater and validation tools.
"""
from __future__ import annotations

from datetime import datetime
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

# Keep this collation byte-for-byte compatible in behavior with the legacy CRM
# app.db() connection. Real TURTO databases contain indexes that reference
# COLLATE CZECH; SQLite integrity/quick_check therefore needs the collation to be
# registered even when the standalone updater opens the database read-only.
_CZ_ORDER = {
    "a": 10, "á": 11, "b": 20, "c": 30, "č": 31, "d": 40, "ď": 41,
    "e": 50, "é": 51, "ě": 52, "f": 60, "g": 70, "h": 80, "ch": 90,
    "i": 100, "í": 101, "j": 110, "k": 120, "l": 130, "m": 140,
    "n": 150, "ň": 151, "o": 160, "ó": 161, "p": 170, "q": 180,
    "r": 190, "ř": 191, "s": 200, "š": 201, "t": 210, "ť": 211,
    "u": 220, "ú": 221, "ů": 222, "v": 230, "w": 240, "x": 250,
    "y": 260, "ý": 261, "z": 270, "ž": 271,
}


def _czech_sort_key(value: Any):
    text = str(value or "").strip().casefold()
    out = []
    index = 0
    while index < len(text):
        if index + 1 < len(text) and text[index:index + 2] == "ch":
            out.append((_CZ_ORDER["ch"], ""))
            index += 2
            continue
        char = text[index]
        if char in _CZ_ORDER:
            out.append((_CZ_ORDER[char], ""))
        elif char.isdigit():
            end = index
            while end < len(text) and text[end].isdigit():
                end += 1
            out.append((500, int(text[index:end])))
            index = end
            continue
        elif char.isspace():
            out.append((1, ""))
        else:
            out.append((400, char))
        index += 1
    return tuple(out)


def _czech_collate(left: Any, right: Any) -> int:
    left_key = _czech_sort_key(left)
    right_key = _czech_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _register_sqlite_collations(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.create_collation("CZECH", _czech_collate)
    return connection


def _readonly_sqlite_uri(path: Path) -> str:
    resolved = str(path.expanduser().resolve()).replace("\\", "/")
    return "file:" + quote(resolved, safe="/:_") + "?mode=ro"


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


def _sqlite_backup(source: Path, target: Path) -> Path:
    """Create a consistent backup while keeping the source strictly read-only."""
    target.parent.mkdir(parents=True, exist_ok=True)
    src = _register_sqlite_collations(sqlite3.connect(_readonly_sqlite_uri(source), uri=True))
    dst = _register_sqlite_collations(sqlite3.connect(target))
    try:
        src.backup(dst)
    finally:
        try:
            dst.close()
        finally:
            src.close()
    return target


def backup_database(
    path: str | Path,
    label: str = "pred_prvnim_pripojenim",
    *,
    backup_root: str | Path | None = None,
) -> Path:
    """Back up an existing TURTO database without changing the source file."""
    source = Path(path).expanduser().resolve()
    validation = validate_database(source)
    if not validation["ok"]:
        raise ValueError(str(validation["message"]))
    root = Path(backup_root).expanduser().resolve() if backup_root else default_data_root()
    backup_dir = root / "backup"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(label or "zaloha"))
    target = backup_dir / f"zakazky_{safe_label}_{stamp}.db"
    _sqlite_backup(source, target)
    copied = validate_database(target)
    if not copied["ok"]:
        target.unlink(missing_ok=True)
        raise ValueError("Záloha databáze neprošla kontrolou: " + str(copied["message"]))
    return target


def adopt_existing_default() -> dict[str, str] | None:
    """Adopt a legacy standard DB once, with a pre-8.0 safety backup."""
    if config_file().is_file():
        return None
    if str(os.environ.get("TURTO_CRM_DATA_ROOT", "")).strip() or str(
        os.environ.get("TURTO_CRM_DATABASE", "")
    ).strip():
        return None

    root = default_data_root()
    db = root / "data" / DEFAULT_DB_NAME
    if not db.is_file():
        return None
    validation = validate_database(db)
    if not validation["ok"]:
        return None

    backup = backup_database(
        db,
        label="pred_prvnim_spustenim_8_0",
        backup_root=root,
    )
    data = {
        "mode": "adopted-existing-standard",
        "data_root": str(root),
        "database_path": str(db),
        "first_8_backup": str(backup),
        "adopted_at": datetime.now().isoformat(timespec="seconds"),
    }
    _write_config(data)
    ensure_data_directories()
    return data


def attach_database(
    path: str | Path,
    *,
    data_root_path: str | Path | None = None,
    backup_before_use: bool = True,
) -> dict[str, str]:
    db = Path(path).expanduser().resolve()
    validation = validate_database(db)
    if not validation["ok"]:
        raise ValueError(str(validation["message"]))
    root = Path(data_root_path).expanduser().resolve() if data_root_path else default_data_root()
    backup = backup_database(db, backup_root=root) if backup_before_use else None
    data = {
        "mode": "external-database",
        "data_root": str(root),
        "database_path": str(db),
        "first_attach_backup": str(backup) if backup else "",
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
    _sqlite_backup(source, temp)
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
    con = None
    try:
        con = _register_sqlite_collations(sqlite3.connect(_readonly_sqlite_uri(db), uri=True))
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
    finally:
        if con is not None:
            con.close()


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
    "adopt_existing_default",
    "attach_database",
    "apply_to_app",
    "backup_database",
    "config_file",
    "copy_database_to_standard",
    "data_root",
    "database_path",
    "default_data_root",
    "ensure_data_directories",
    "use_default_location",
    "validate_database",
]
