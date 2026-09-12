#!/usr/bin/env python3
"""Regression checks for the 8.0.6 frozen Offer Engine loader and bundle contract."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
MODULE = BASE / "price_lists_domain" / "platform" / "frozen_offer_engine_806.py"
SPEC = REPO / "build" / "windows" / "TURTO_CRM.spec"
BOOTSTRAP = BASE / "runtime_bootstrap.py"
LAUNCHER = REPO / "build" / "windows" / "launcher_800.pyw"


def load_module():
    spec = importlib.util.spec_from_file_location("frozen_offer_engine_806_test", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    layer = load_module()

    # Source mode must preserve the historical loader exactly.
    source_calls = []
    source_marker = object()
    fake = SimpleNamespace(_load_offer_router=lambda: (source_calls.append("source"), source_marker)[1])
    layer.apply(fake)
    assert fake._load_offer_router() is source_marker
    assert source_calls == ["source"]
    assert fake.FROZEN_OFFER_ENGINE_806["source_mode"] == "historical-loader"

    # Frozen mode resolves the physical tree below _MEIPASS and can load a
    # file-based router without relying on Python's frozen module archive.
    old_frozen = getattr(sys, "frozen", None)
    had_frozen = hasattr(sys, "frozen")
    old_meipass = getattr(sys, "_MEIPASS", None)
    had_meipass = hasattr(sys, "_MEIPASS")
    old_router = sys.modules.pop(layer.ROUTER_MODULE_NAME, None)
    try:
        with tempfile.TemporaryDirectory(prefix="turto-offer-engine-") as td:
            root = Path(td)
            engine = root / "offers_engine"
            engine.mkdir()
            (engine / "Nabidky_Router.py").write_text(
                "def parsers():\n"
                "    return [{'supplier':'GEROtop'}, {'supplier':'Leviat'}, "
                "{'supplier':'PohlCon Česká republika s.r.o.'}]\n",
                encoding="utf-8",
            )
            sys.frozen = True
            sys._MEIPASS = str(root)
            assert layer._frozen_engine_root() == engine
            router = layer._load_physical_router(engine)
            names = [row["supplier"] for row in router.parsers()]
            assert names == ["GEROtop", "Leviat", "PohlCon Česká republika s.r.o."]

            sys.modules.pop(layer.ROUTER_MODULE_NAME, None)
            (engine / "Nabidky_Router.py").unlink()
            try:
                layer._load_physical_router(engine)
            except RuntimeError as exc:
                assert "offers_engine" in str(exc)
            else:
                raise AssertionError("Missing physical router did not fail closed")
    finally:
        sys.modules.pop(layer.ROUTER_MODULE_NAME, None)
        if old_router is not None:
            sys.modules[layer.ROUTER_MODULE_NAME] = old_router
        if had_frozen:
            sys.frozen = old_frozen
        else:
            try:
                del sys.frozen
            except AttributeError:
                pass
        if had_meipass:
            sys._MEIPASS = old_meipass
        else:
            try:
                del sys._MEIPASS
            except AttributeError:
                pass

    spec_text = SPEC.read_text(encoding="utf-8")
    for token in (
        'offer_engine_root = BASE / "offers_engine"',
        'source.suffix.lower() in {".py", ".pyw"}',
        'offer_engine_root / "providers" / "pohlcon.py"',
        'collect_submodules("offers_engine")',
    ):
        assert token in spec_text, token

    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    frozen_token = '"price_lists_domain.platform.frozen_offer_engine_806"'
    archive_token = '"price_lists_domain.platform.action_archive_cleanup_806"'
    assert frozen_token in bootstrap
    assert bootstrap.index(frozen_token) < bootstrap.index(archive_token)

    launcher = LAUNCHER.read_text(encoding="utf-8")
    for token in (
        'offer_parsers = _run_phase("offer-engine"',
        '"offer_parsers": offer_parsers',
        '"PohlCon": "pohlcon"',
        '"Leviat": "leviat"',
        '"GEROtop": "gerotop"',
    ):
        assert token in launcher, token

    print("TURTO CRM 8.0.6 frozen Offer Engine contract: OK")


if __name__ == "__main__":
    main()
