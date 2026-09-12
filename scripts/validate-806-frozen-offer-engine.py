#!/usr/bin/env python3
"""Regression checks for the 8.0.6 frozen Offer Engine bundle contract."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import zipfile

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
MODULE = BASE / "price_lists_domain" / "platform" / "frozen_offer_engine_806.py"
SPEC = REPO / "build" / "windows" / "TURTO_CRM.spec"
UPDATER = REPO / "build" / "windows" / "updater_800.pyw"
BOOTSTRAP = BASE / "runtime_bootstrap.py"
LAUNCHER = REPO / "build" / "windows" / "launcher_800.pyw"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def reset_materialized(layer) -> None:
    root = getattr(layer, "_FROZEN_ENGINE_ROOT", None)
    if root is not None:
        text = str(root)
        while text in sys.path:
            sys.path.remove(text)
    holder = getattr(layer, "_FROZEN_ENGINE_TEMP", None)
    if holder is not None:
        holder.cleanup()
    layer._FROZEN_ENGINE_TEMP = None
    layer._FROZEN_ENGINE_ROOT = None


def write_bundle(path: Path, *, complete: bool = True) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "Nabidky_Router.py",
            "def parsers():\n"
            "    return [{'supplier':'GEROtop'}, {'supplier':'Leviat'}, "
            "{'supplier':'PohlCon Česká republika s.r.o.'}]\n",
        )
        if complete:
            archive.writestr("Leviat_Nabidky.pyw", "# test\n")
            archive.writestr("Gerotop_Parser_767.py", "# test\n")
            archive.writestr("providers/pohlcon.py", "# test\n")


def write_release(root: Path, version: str, bundle: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "TURTO CRM.exe").write_bytes(b"main")
    (root / "TURTO CRM Updater.exe").write_bytes(b"updater")
    (root / "version.json").write_text(
        json.dumps({"version": version, "channel": "windows", "build": "test"}),
        encoding="utf-8",
    )
    internal = root / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle, internal / "offers_engine_bundle.zip")


def main() -> None:
    sys.path.insert(0, str(BASE))
    layer = load_module("frozen_offer_engine_806_test", MODULE)

    # Source mode must preserve the historical loader exactly.
    source_calls = []
    source_marker = object()
    fake = SimpleNamespace(_load_offer_router=lambda: (source_calls.append("source"), source_marker)[1])
    layer.apply(fake)
    assert fake._load_offer_router() is source_marker
    assert source_calls == ["source"]
    assert fake.FROZEN_OFFER_ENGINE_806["source_mode"] == "historical-loader"
    assert fake.FROZEN_OFFER_ENGINE_806["frozen_mode"] == "temporary-runtime-archive"

    old_frozen = getattr(sys, "frozen", None)
    had_frozen = hasattr(sys, "frozen")
    old_meipass = getattr(sys, "_MEIPASS", None)
    had_meipass = hasattr(sys, "_MEIPASS")
    old_router = sys.modules.pop(layer.ROUTER_MODULE_NAME, None)
    try:
        with tempfile.TemporaryDirectory(prefix="turto-offer-engine-") as td:
            root = Path(td)
            bundle = root / layer.BUNDLE_NAME
            write_bundle(bundle)
            sys.frozen = True
            sys._MEIPASS = str(root)

            assert layer._frozen_bundle_path() == bundle
            engine = layer._frozen_engine_root()
            assert engine is not None and engine.is_dir()
            assert engine.parent != root
            assert (engine / "providers" / "pohlcon.py").is_file()
            router = layer._load_physical_router(engine)
            names = [row["supplier"] for row in router.parsers()]
            assert names == ["GEROtop", "Leviat", "PohlCon Česká republika s.r.o."]

            # The exact payload form must still be accepted by the strict updater
            # already shipped in 8.0.5: only a .zip data file is present, never
            # loose .py/.pyw files.
            updater = load_module("turto_updater_806_bundle_test", UPDATER)
            release = root / "release"
            write_release(release, "8.0.6", bundle)
            assert updater._validate_release(release, "8.0.6") == "8.0.6"

            rogue = release / "_internal" / "rogue.py"
            rogue.write_text("x=1\n", encoding="utf-8")
            try:
                updater._validate_release(release, "8.0.6")
            except RuntimeError as exc:
                assert "nepovolen" in str(exc).casefold()
            else:
                raise AssertionError("Updater accepted loose Python outside Offer Engine bundle")
            rogue.unlink()

            physical_engine = release / "_internal" / "offers_engine"
            physical_engine.mkdir()
            loose_provider = physical_engine / "provider.py"
            loose_provider.write_text("x=1\n", encoding="utf-8")
            try:
                updater._validate_release(release, "8.0.6")
            except RuntimeError as exc:
                assert "nepovolen" in str(exc).casefold()
            else:
                raise AssertionError("Updater accepted loose Offer Engine Python source")
            shutil.rmtree(physical_engine)

            # Incomplete internal archives fail closed before a router is used.
            reset_materialized(layer)
            sys.modules.pop(layer.ROUTER_MODULE_NAME, None)
            write_bundle(bundle, complete=False)
            try:
                layer._frozen_engine_root()
            except RuntimeError as exc:
                assert "neúpl" in str(exc).casefold()
            else:
                raise AssertionError("Incomplete Offer Engine bundle did not fail closed")
    finally:
        reset_materialized(layer)
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
        'import zipfile',
        'offer_engine_bundle = generated_dir / "offers_engine_bundle.zip"',
        'archive.write(source, source.relative_to(offer_engine_root).as_posix())',
        'datas.append((str(offer_engine_bundle), "."))',
        'offer_engine_root / "providers" / "pohlcon.py"',
        'collect_submodules("offers_engine")',
    ):
        assert token in spec_text, token
    assert 'relative_parent = source.parent.relative_to(BASE)' not in spec_text

    updater_text = UPDATER.read_text(encoding="utf-8")
    strict_suffixes = 'FORBIDDEN_PAYLOAD_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".py", ".pyw", ".pyc"}'
    assert strict_suffixes in updater_text
    assert "_allowed_offer_engine_source" not in updater_text

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

    print("TURTO CRM 8.0.6 frozen Offer Engine bundle contract: OK")


if __name__ == "__main__":
    main()
