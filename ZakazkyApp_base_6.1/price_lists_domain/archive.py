"""Permanent local archive for original price-list files."""
from __future__ import annotations
import json,shutil
from pathlib import Path
from . import context as ctx
from .common import _file_hash,_safe

def _config_path() -> Path:
    root = Path(getattr(ctx.M, "DATA_ROOT", Path.home() / "Documents" / "TURTO Zakazky"))
    return root / "local_settings.json"


def _load_local_config() -> dict:
    try:
        path = _config_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _save_local_config(data: dict) -> None:
    try:
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


def price_list_archive_root() -> Path:
    cfg = _load_local_config()
    custom = str(cfg.get("price_list_archive_dir") or "").strip()
    if custom:
        return Path(custom)
    root = Path(getattr(ctx.M, "DATA_ROOT", Path.home() / "Documents" / "TURTO Zakazky"))
    return root / "Ceniky"


def set_price_list_archive_root(value: object) -> None:
    cfg = _load_local_config()
    cfg["price_list_archive_dir"] = str(Path(str(value)))
    _save_local_config(cfg)


def _archive_source(path: Path, supplier: str, valid_from: str, title: str) -> tuple[Path, str]:
    source_hash = _file_hash(path)
    root = price_list_archive_root()
    supplier_dir = root / _safe(supplier or "Neurceny dodavatel", 70)
    folder_label = f"{valid_from or 'bez-data'} - {_safe(title or path.stem, 100)}"
    folder = supplier_dir / _safe(folder_label, 150)
    if folder.exists():
        existing = folder / path.name
        if existing.exists():
            try:
                if _file_hash(existing) == source_hash:
                    return existing, source_hash
            except Exception:
                pass
        suffix = source_hash[:8]
        folder = supplier_dir / _safe(folder_label + "_" + suffix, 160)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / _safe(path.name, 150)
    shutil.copy2(path, target)
    return target, source_hash
