"""Conservative retention: exact, revalidated files, never recursive deletion.

Legacy files require an explicit preview/selection. Opt-in unattended maintenance
only removes recognised automatic files created after consent. Unknown names,
sidecars, manual/import/migration backups and recovery references are protected.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

import data_location
import updater_safety as safety

POLICY_NAME = "storage_policy.json"
AUTO_LABELS = {"pred_aktualizaci", "pred_navratem", "daily", "before_storage_cleanup"}
BACKUP_RE = re.compile(r"^zakazky_(.+)_(\d{8}_\d{6})(?:_\d{6}(?:_[0-9a-f]{8})?)?\.db$")
PACKAGE_RE = re.compile(r"^TURTO_(?:CRM|Zakazky)_(?:Update_)?[0-9][A-Za-z0-9._-]*\.zip$", re.I)
RULES = "Posledních 5 + 7 denních + 8 týdenních + 12 měsíčních bodů obnovy (překryvy se počítají jednou)."


def _plain(path: Path) -> None:
    # Check parents as well: a normal file inside a junction is not safe either.
    for part in (path, *path.parents):
        if part.exists() and safety.is_link(part):
            raise ValueError(f"Úklid nepodporuje odkazy ani junctiony: {part}")


def maintenance_lock(root: Path):
    _plain(Path(root))
    return safety.FileLock(Path(root) / "updates" / "storage-maintenance.lock")


def _fingerprint(path: Path) -> tuple:
    _plain(path)
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def create_backup(source: Path, directory: Path, label: str) -> Path:
    """Publish a unique, verified, closed SQLite snapshot; never replace a backup."""
    source, directory = Path(source).absolute(), Path(directory).absolute()
    _plain(source); _plain(directory)
    if not source.is_file():
        raise FileNotFoundError(source)
    directory.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(label or "manual"))
    token = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{uuid.uuid4().hex[:8]}"
    target = directory / f"zakazky_{safe_label}_{token}.db"
    temp = target.with_suffix(".db.partial")
    with safety.FileLock(directory / "backup-create.lock"):
        reserved = False
        try:
            # Reserve without truncation, including in the unlikely event of a collision.
            with temp.open("xb"):
                pass
            reserved = True
            started = time.monotonic()
            def progress(_status, _remaining, _total):
                if time.monotonic() - started > 300:
                    raise TimeoutError("Záloha překročila 5 minut. Starší zálohy zůstaly zachované.")
            with closing(sqlite3.connect(data_location._readonly_sqlite_uri(source), uri=True, timeout=10)) as src:
                with closing(sqlite3.connect(temp, timeout=10)) as dst:
                    src.backup(dst, pages=256, progress=progress, sleep=0.01)
                    # Publish a standalone file, not a renamed WAL-mode database
                    # with validation sidecars still bearing the temporary name.
                    dst.execute("PRAGMA journal_mode=DELETE")
            check = data_location.validate_database(temp)
            if not check["ok"]:
                raise ValueError("Záloha neprošla kontrolou: " + str(check["message"]))
            with temp.open("rb") as stream:
                os.fsync(stream.fileno())
            if target.exists():
                raise FileExistsError(target)
            temp.rename(target)
            return target
        finally:
            # Only our unpublished temporary snapshot; no user backup is touched.
            if reserved:
                for suffix in ("", "-wal", "-shm", "-journal"):
                    temp.with_name(temp.name + suffix).unlink(missing_ok=True)


def _json(path: Path) -> dict:
    _plain(path)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Neplatný řídicí soubor: {path}")
    return value


def policy(root: Path) -> dict:
    return _json(Path(root) / POLICY_NAME)


def save_policy(root: Path, database: Path, enabled: bool) -> None:
    with maintenance_lock(root):
        previous = policy(root)
        same_db = previous.get("database") == str(Path(database).resolve())
        since = previous.get("enabled_since") if same_db and previous.get("enabled") is True else None
        safety.write_json(Path(root) / POLICY_NAME, {
            "enabled": bool(enabled), "database": str(Path(database).resolve()),
            "enabled_since": (since or datetime.now().isoformat()) if enabled else None,
        })


def _references(root: Path, database: Path) -> set[Path]:
    protected = {database.resolve()}
    for rel in ("updates/rollback/latest.json", "updates/last_update.json", "updates/last_failed_update.json"):
        document = _json(root / rel)
        for key in ("package", "database", "database_backup", "program_snapshot"):
            value = document.get(key)
            if value:
                p = Path(str(value))
                protected.add((p if p.is_absolute() else root / p).resolve())
    # If references cannot be read, fail closed, not with an empty protection set.
    with closing(sqlite3.connect(data_location._readonly_sqlite_uri(database), uri=True, timeout=10)) as con:
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='archive_batches'").fetchone():
            for (value,) in con.execute("SELECT backup_path FROM archive_batches WHERE backup_path IS NOT NULL"):
                if value:
                    p = Path(str(value))
                    protected.add((p if p.is_absolute() else root / p).resolve())
    return protected


def _retained(backups: list[dict], now: datetime) -> set[str]:
    ordered = sorted(backups, key=lambda e: (e["timestamp"], e["relative"]), reverse=True)
    keep = {e["relative"] for e in ordered[:5]}
    daily, weekly, monthly = set(), set(), set()
    for e in ordered:
        dt = datetime.fromisoformat(e["timestamp"])
        age = (now.date() - dt.date()).days
        month_age = (now.year - dt.year) * 12 + now.month - dt.month
        week = dt.isocalendar()[:2]
        if 0 <= age < 7 and dt.date() not in daily:
            daily.add(dt.date()); keep.add(e["relative"])
        week_age = ((now.date() - timedelta(days=now.weekday())) -
                    (dt.date() - timedelta(days=dt.weekday()))).days // 7
        if 0 <= week_age < 8 and week not in weekly:
            weekly.add(week); keep.add(e["relative"])
        if 0 <= month_age < 12 and (dt.year, dt.month) not in monthly:
            monthly.add((dt.year, dt.month)); keep.add(e["relative"])
    return keep


def build_plan(root: Path, database: Path, *, now: datetime | None = None) -> list[dict]:
    root, database = Path(root).absolute(), Path(database).absolute()
    _plain(root); _plain(database)
    now = now or datetime.now()
    refs = _references(root, database)
    entries, backups = [], []
    for folder in ("backup", "updates", "updates/downloads", "updates/rollback"):
        directory = root / folder
        _plain(directory)
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            # Do not traverse any subdirectory (in particular extracted runtimes).
            if path.is_dir() and not safety.is_link(path):
                continue
            if safety.is_link(path) or not path.is_file():
                continue
            e = {"relative": path.relative_to(root).as_posix(), "size": path.stat().st_size,
                 "fingerprint": _fingerprint(path), "kind": "ostatní", "eligible": False,
                 "reason": "Nerozpoznaný nebo řídicí soubor – ponechat", "timestamp": ""}
            entries.append(e)
            if path.resolve() in refs or path.samefile(database) or path.stat().st_nlink > 1:
                e["reason"] = "Živá databáze nebo soubor potřebný pro obnovu"
                continue
            match = BACKUP_RE.fullmatch(path.name) if folder == "backup" else None
            if match:
                e["kind"] = "záloha"
                if match[1] not in AUTO_LABELS:
                    e["reason"] = "Ruční / importní / migrační záloha – ponechat"
                    continue
                try:
                    dt = datetime.strptime(match[2], "%Y%m%d_%H%M%S")
                except ValueError:
                    continue
                if any(path.with_name(path.name + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
                    e["reason"] = "Záloha má doprovodné SQLite soubory – ruční kontrola"
                    continue
                e["timestamp"] = dt.isoformat()
                backups.append(e)
            elif folder != "backup" and PACKAGE_RE.fullmatch(path.name):
                e["kind"] = "aktualizace"
                e["timestamp"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            else:
                continue
            dt = datetime.fromisoformat(e["timestamp"])
            if dt > now or (now.timestamp() - path.stat().st_mtime) < 24 * 3600:
                e["reason"] = "Nový soubor (24 hodin) nebo budoucí datum – ponechat"
            else:
                e["eligible"] = True
                e["reason"] = "Starší automatický soubor nad rámec uchování"
    keep = _retained(backups, now)
    for e in entries:
        if e["relative"] in keep:
            e.update(eligible=False, reason="Bod obnovy podle pravidel uchování")
    # Always preserve the two newest packages in each known directory, as well
    # as all explicitly referenced packages above. Downloads in flight stay out.
    for folder in ("updates", "updates/downloads", "updates/rollback"):
        packages = [e for e in entries if e["kind"] == "aktualizace" and str(Path(e["relative"]).parent).replace("\\", "/") == folder]
        for e in sorted(packages, key=lambda e: (e["timestamp"], e["relative"]), reverse=True)[:2]:
            e.update(eligible=False, reason="Dva nejnovější balíčky / návraty verze")
    return entries


def _archive_file(source: Path, target: Path) -> str:
    _plain(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".partial")
    reserved = False
    try:
        with source.open("rb") as src, temp.open("xb") as dst:
            reserved = True
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush(); os.fsync(dst.fileno())
        sha = safety.digest(source)
        if safety.digest(temp) != sha:
            raise ValueError("Kopie v archivu neodpovídá originálu. Originál nebyl smazán.")
        if target.exists():
            raise FileExistsError(target)
        temp.rename(target)
        return sha
    finally:
        if reserved:
            temp.unlink(missing_ok=True)


def _execute(root: Path, database: Path, selected: list[dict], *, archive: Path | None = None,
             verified_backup: Path | None = None, progress=None) -> dict:
    fresh = {e["relative"]: e for e in build_plan(root, database)}
    if not selected or len({e["relative"] for e in selected}) != len(selected):
        raise ValueError("Vyberte konkrétní soubory z aktuálního náhledu.")
    for e in selected:
        current = fresh.get(e["relative"])
        if not current or not current["eligible"] or tuple(e["fingerprint"]) != current["fingerprint"]:
            raise ValueError("Soubory nebo ochrana se od náhledu změnily. Obnovte přehled; nic nebylo smazáno.")
    token = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
    archive_root = None
    if archive is not None:
        archive = Path(archive).absolute()
        _plain(archive)
        if not archive.is_dir() or archive.resolve().is_relative_to(root.resolve()):
            raise ValueError("Archiv vyberte mimo pracovní složku CRM, nejlépe na jiném disku.")
        if shutil.disk_usage(archive).free < sum(e["size"] for e in selected) + 16 * 1024 * 1024:
            raise ValueError("V archivu není dost volného místa. Nic nebylo smazáno.")
        archive_root = archive / ("TURTO_CRM_archiv_" + token)
        archive_root.mkdir(exist_ok=False)
    if progress:
        progress("Ověřuji bezpečnostní zálohu…")
    backup = verified_backup or create_backup(database, root / "backup", "before_storage_cleanup")
    if not data_location.validate_database(backup)["ok"]:
        raise ValueError("Bez ověřené zálohy nelze pokračovat.")
    record = {"database": str(database), "backup": str(backup), "archive": str(archive_root or ""),
              "mode": "archive" if archive_root else "delete", "planned": [e["relative"] for e in selected],
              "completed": [], "bytes": 0, "error": ""}
    log = root / "logs" / ("storage_cleanup_" + token + ".json")
    safety.write_json(log, record)  # No deletions if a durable journal cannot be created.
    try:
        for i, e in enumerate(selected, 1):
            if progress:
                progress(f"{i}/{len(selected)}: {e['relative']}")
            source = root / e["relative"]
            if _fingerprint(source) != tuple(e["fingerprint"]):
                raise ValueError(f"Soubor se změnil, úklid zastaven: {source.name}")
            # Recheck references and sidecars immediately before each operation.
            current = {v["relative"]: v for v in build_plan(root, database)}.get(e["relative"])
            if not current or not current["eligible"]:
                raise ValueError(f"Soubor nově vyžaduje ochranu: {source.name}")
            sha = _archive_file(source, archive_root / e["relative"]) if archive_root else ""
            if _fingerprint(source) != tuple(e["fingerprint"]):
                raise ValueError("Originál se během kopírování změnil; nebyl smazán.")
            # Persist archive location/checksum before unlink, also for crash recovery.
            record["pending"] = {"relative": e["relative"], "sha256": sha}
            safety.write_json(log, record)
            if archive_root:
                safety.write_json(archive_root / "manifest.json", record)
            source.unlink()
            record["completed"].append(record.pop("pending"))
            record["bytes"] += e["size"]
            safety.write_json(log, record)
    except Exception as exc:
        record["error"] = str(exc)
    finally:
        safety.write_json(log, record)
        if archive_root:
            safety.write_json(archive_root / "manifest.json", record)
    record["log"] = str(log)
    return record


def execute(root: Path, database: Path, selected: list[dict], *, archive: Path | None = None, progress=None) -> dict:
    root, database = Path(root).absolute(), Path(database).absolute()
    with maintenance_lock(root):
        return _execute(root, database, selected, archive=archive, progress=progress)


def run_daily(root: Path, database: Path) -> dict | None:
    """Called while CRM is running; opt-in, one backup/day, no legacy deletion."""
    root, database = Path(root).absolute(), Path(database).absolute()
    with maintenance_lock(root):
        settings = policy(root)
        if settings.get("enabled") is not True or settings.get("database") != str(database.resolve()):
            return None
        since = datetime.fromisoformat(settings["enabled_since"])
        state_path = root / "logs" / "storage_daily.json"
        state = _json(state_path)
        today = datetime.now().date().isoformat()
        if state.get("date") == today and state.get("database") == str(database.resolve()):
            return None
        backup = create_backup(database, root / "backup", "daily")
        candidates = [e for e in build_plan(root, database) if e["eligible"] and
                      datetime.fromisoformat(e["timestamp"]) >= since and
                      e["fingerprint"][3] / 1_000_000_000 >= since.timestamp()]
        result = _execute(root, database, candidates, verified_backup=backup) if candidates else None
        safety.write_json(state_path, {"date": today, "database": str(database.resolve()),
                                      "backup": str(backup), "result": result})
        return {"backup": str(backup), "result": result}
