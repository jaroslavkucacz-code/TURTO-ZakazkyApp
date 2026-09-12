"""Frozen-safe loader for the legacy TURTO price-offer parser engine.

The historical CRM loader intentionally loads ``offers_engine/Nabidky_Router.py``
from real files because the router itself discovers provider ``*.py`` files and
loads the legacy Leviat ``.pyw`` parser from disk.  PyInstaller hidden imports are
therefore not sufficient on their own: a frozen build also needs a physical copy
of the parser source tree under ``sys._MEIPASS``.

Source/development execution is deliberately unchanged and delegates to the
historical loader.  Only a frozen Windows payload uses the bundled physical tree.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.frozen_offer_engine_806"
ROUTER_MODULE_NAME = "_zakazky_nabidky_router"


def _frozen_engine_root() -> Path | None:
    """Return the physical PyInstaller offer-engine directory, if available."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(str(bundle)) / "offers_engine"
    if getattr(sys, "frozen", False):
        # Fail-safe for onedir launchers where the runtime exposes only the EXE
        # directory.  Current PyInstaller sets _MEIPASS, but this keeps the
        # payload discoverable without falling back to user-writable locations.
        return Path(sys.executable).resolve().parent / "_internal" / "offers_engine"
    return None


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
        "frozen_mode": "physical-meipass-offers-engine",
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "ROUTER_MODULE_NAME",
    "_frozen_engine_root",
    "_load_physical_router",
]
