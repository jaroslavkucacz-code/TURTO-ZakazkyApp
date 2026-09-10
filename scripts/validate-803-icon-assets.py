#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.3 packaged icon reuse."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeWindow:
    def __init__(self):
        self.bitmap = None
        self.photo = None
        self._turto_crm_icon_photo = None
        self._turto_icon_asset_source = None
        self.bitmap_calls = 0
        self.photo_calls = 0

    def iconbitmap(self, *, default):
        self.bitmap_calls += 1
        self.bitmap = default

    def iconphoto(self, default, image):
        assert default is True
        self.photo_calls += 1
        self.photo = image


class FakeTk:
    calls = []

    @classmethod
    def PhotoImage(cls, *, file):
        cls.calls.append(file)
        return ("photo", file)


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    path = base / "price_lists_domain" / "platform" / "icon_assets_803.py"
    bootstrap = (base / "runtime_bootstrap.py").read_text(encoding="utf-8")
    module = load_module(path, "turto_icon_assets_803_test")

    with tempfile.TemporaryDirectory(prefix="turto-icon-803-") as td:
        root = Path(td)
        logo_ico = root / "turto_logo.ico"
        logo_png = root / "turto_logo.png"
        logo_ico.write_bytes(b"ICO")
        logo_png.write_bytes(b"PNG")

        ensure_calls = []
        configure_calls = []

        def old_ensure(M):
            ensure_calls.append("fallback")
            (Path(M.ROOT) / "turto_crm.ico").write_bytes(b"GENERATED-ICO")
            (Path(M.ROOT) / "turto_crm.png").write_bytes(b"GENERATED-PNG")

        def old_configure(M, win):
            configure_calls.append("fallback")

        fake_v770 = SimpleNamespace(
            _ensure_icon_assets=old_ensure,
            _configure_identity=old_configure,
        )
        previous_v770 = sys.modules.get("v770_runtime_policy")
        sys.modules["v770_runtime_policy"] = fake_v770
        try:
            FakeTk.calls.clear()
            M = SimpleNamespace(ROOT=root, tk=FakeTk)
            assert module._existing_icon_pair(M) == (logo_ico, logo_png, "packaged-logo")
            assert module._install_v770_icon_reuse(M) is True

            # A normal packaged/source checkout already contains turto_logo.*.
            # The historical Pillow renderer must not run and no generated files
            # should be written merely to configure the window identity.
            pair = fake_v770._ensure_icon_assets(M)
            assert pair == (logo_ico, logo_png, "packaged-logo")
            assert ensure_calls == []
            assert not (root / "turto_crm.ico").exists()
            assert not (root / "turto_crm.png").exists()

            window = FakeWindow()
            fake_v770._configure_identity(M, window)
            assert ensure_calls == []
            assert configure_calls == []
            assert Path(window.bitmap) == logo_ico
            assert window.photo == ("photo", str(logo_png))
            assert window._turto_icon_asset_source == "packaged-logo"
            assert window.bitmap_calls == 1
            assert window.photo_calls == 1
            assert FakeTk.calls == [str(logo_png)]

            # v770 reaches the same window through two historical identity paths.
            # The second identical pass must be a no-op and must not decode PNG again.
            fake_v770._configure_identity(M, window)
            assert window.bitmap_calls == 1
            assert window.photo_calls == 1
            assert FakeTk.calls == [str(logo_png)]
            assert window._turto_icon_identity_reuse_skips == 1

            # Existing legacy-generated assets keep priority, preserving the
            # visual identity of an installation that already has them. A changed
            # pair invalidates the per-window signature and is applied once.
            crm_ico = root / "turto_crm.ico"
            crm_png = root / "turto_crm.png"
            crm_ico.write_bytes(b"OLD-ICO")
            crm_png.write_bytes(b"OLD-PNG")
            assert module._existing_icon_pair(M) == (crm_ico, crm_png, "legacy-generated")
            fake_v770._configure_identity(M, window)
            assert window.bitmap_calls == 2
            assert window.photo_calls == 2
            assert window._turto_icon_asset_source == "legacy-generated"

            # If neither complete pair exists, the original renderer remains the
            # fallback and its newly generated pair is returned.
            for candidate in (crm_ico, crm_png, logo_ico, logo_png):
                candidate.unlink(missing_ok=True)
            pair = fake_v770._ensure_icon_assets(M)
            assert ensure_calls == ["fallback"]
            assert pair == (crm_ico, crm_png, "legacy-generated")
        finally:
            if previous_v770 is None:
                sys.modules.pop("v770_runtime_policy", None)
            else:
                sys.modules["v770_runtime_policy"] = previous_v770

    marker = '"price_lists_domain.platform.icon_assets_803"'
    v770 = '"v770_runtime_policy"'
    runtime = '"price_lists_domain.platform.runtime_optimization_803"'
    assert marker in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(v770)
    assert bootstrap.index(marker) > bootstrap.index(runtime)

    print("TURTO CRM 8.0.3 packaged icon reuse: OK")


if __name__ == "__main__":
    main()
