"""Frozen-safe loader for the legacy TURTO price-offer parser engine.

The historical offer router intentionally loads provider Python files and the
legacy Leviat ``.pyw`` parser from real files.  A Windows 8.x update, however,
must remain acceptable to the updater already shipped in 8.0.5, which rejects
loose ``.py``/``.pyw`` files in update payloads.  The frozen application therefore
ships one hash-protected ``offers_engine_bundle.zip`` data file and materializes
its trusted parser sources into a process-private temporary directory on demand.

Source/development execution is deliberately unchanged and delegates to the
historical loader.  Only frozen Windows execution uses the runtime archive.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
from typing import Any
import zipfile

POLICY_OWNER = "price_lists_domain.platform.frozen_offer_engine_806"
ROUTER_MODULE_NAME = "_zakazky_nabidky_router"
BUNDLE_NAME = "offers_engine_bundle.zip"
MAX_BUNDLE_UNCOMPRESSED = 16 * 1024 * 1024
_REQUIRED_FILES = {
    "nabidky_router.py",
    "leviat_nabidky.pyw",
    "gerotop_parser_767.py",
    "providers/pohlcon.py",
}
_FROZEN_ENGINE_TEMP: tempfile.TemporaryDirectory | None = None
_FROZEN_ENGINE_ROOT: Path | None = None


def _frozen_bundle_path() -> Path | None:
    """Resolve the immutable Offer Engine archive bundled by PyInstaller."""
    if not getattr(sys, "frozen", False):
        return None
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(str(bundle_root)) / BUNDLE_NAME
    return Path(sys.executable).resolve().parent / "_internal" / BUNDLE_NAME


def _materialize_bundle(bundle: Path) -> Path:
    """Safely extract the trusted internal parser archive for this process."""
    global _FROZEN_ENGINE_TEMP, _FROZEN_ENGINE_ROOT
    if _FROZEN_ENGINE_ROOT is not None and _FROZEN_ENGINE_ROOT.is_dir():
        return _FROZEN_ENGINE_ROOT

    if not bundle.is_file():
        raise RuntimeError(
            "Chybí interní balík offers_engine v instalaci TURTO CRM: "
            f"{bundle}"
        )

    holder = tempfile.TemporaryDirectory(prefix="turto_offer_engine_")
    engine = Path(holder.name) / "offers_engine"
    engine.mkdir(parents=True, exist_ok=True)
    total = 0
    names: set[str] = set()
    try:
        with zipfile.ZipFile(bundle) as archive:
            for info in archive.infolist():
                raw_name = str(info.filename or "").replace("\\", "/")
                rel = PurePosixPath(raw_name)
                if not raw_name or rel.is_absolute() or ".." in rel.parts:
                    raise RuntimeError("Interní Offer Engine obsahuje nepovolenou cestu.")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise RuntimeError("Interní Offer Engine nesmí obsahovat symbolické odkazy.")
                if info.is_dir() or raw_name.endswith("/"):
                    continue
                if Path(rel.name).suffix.lower() not in {".py", ".pyw"}:
                    raise RuntimeError(
                        f"Interní Offer Engine obsahuje neočekávaný soubor: {raw_name}"
                    )
                total += int(info.file_size or 0)
                if total > MAX_BUNDLE_UNCOMPRESSED:
                    raise RuntimeError("Interní Offer Engine překračuje povolenou velikost.")
                destination = engine.joinpath(*rel.parts)
                try:
                    destination.resolve().relative_to(engine.resolve())
                except Exception as exc:
                    raise RuntimeError(
                        "Interní Offer Engine se pokusil zapisovat mimo dočasnou složku."
                    ) from exc
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                names.add(rel.as_posix().casefold())

        missing = sorted(_REQUIRED_FILES.difference(names))
        if missing:
            raise RuntimeError(
                "Interní Offer Engine je neúplný; chybí: " + ", ".join(missing)
            )
    except Exception:
        holder.cleanup()
        raise

    _FROZEN_ENGINE_TEMP = holder
    _FROZEN_ENGINE_ROOT = engine
    return engine


def _frozen_engine_root() -> Path | None:
    """Return a process-private physical Offer Engine tree for frozen execution."""
    bundle = _frozen_bundle_path()
    if bundle is None:
        return None
    return _materialize_bundle(bundle)


def _load_physical_router(engine: Path):
    router_file = engine / "Nabidky_Router.py"
    if not router_file.is_file():
        raise RuntimeError(
            "Chybí interní modul offers_engine v instalaci TURTO CRM: "
            f"{router_file}"
        )

    engine_text = str(engine)
    if engine_text not in sys.path:
        sys.path.insert(0, engine_text)

    current = sys.modules.get(ROUTER_MODULE_NAME)
    if current is not None:
        return current

    spec = importlib.util.spec_from_file_location(ROUTER_MODULE_NAME, router_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nelze načíst interní Offer Engine: {router_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[ROUTER_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(ROUTER_MODULE_NAME, None)
        raise
    return module


def apply(M: Any) -> None:
    if getattr(M, "_turto_frozen_offer_engine_806", False):
        return

    historical = getattr(M, "_load_offer_router", None)
    if not callable(historical):
        M.FROZEN_OFFER_ENGINE_806 = {
            "owner": POLICY_OWNER,
            "installed": False,
            "reason": "historical-loader-missing",
        }
        return

    def load_offer_router():
        if not getattr(sys, "frozen", False):
            return historical()
        engine = _frozen_engine_root()
        if engine is None:
            return historical()
        return _load_physical_router(engine)

    load_offer_router._turto_806_frozen_offer_engine = True
    load_offer_router._turto_original = historical
    M._load_offer_router = load_offer_router
    M._turto_frozen_offer_engine_806 = True
    M.FROZEN_OFFER_ENGINE_806 = {
        "owner": POLICY_OWNER,
        "installed": True,
        "source_mode": "historical-loader",
        "frozen_mode": "temporary-runtime-archive",
        "bundle_name": BUNDLE_NAME,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "ROUTER_MODULE_NAME",
    "BUNDLE_NAME",
    "_frozen_bundle_path",
    "_materialize_bundle",
    "_frozen_engine_root",
    "_load_physical_router",
]
