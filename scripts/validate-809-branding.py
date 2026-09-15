#!/usr/bin/env python3
"""Branding regressions: upgraded installs, frozen paths and native icon sizes."""
import hashlib
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / "ZakazkyApp_base_6.1"
sys.path.insert(0, str(BASE))
import branding
from PIL import Image


def main():
    # Fingerprint of the exact logo supplied by the user (not a redrawn logo).
    source_hash = "303ea4c6a931e112ba8bc1526d9bc72eb7b085745fa6aa26e5060b9c8671f05b"
    assert hashlib.sha256((BASE / "turto_logo.png").read_bytes()).hexdigest() == source_hash
    with Image.open(BASE / "turto_logo.png") as im:
        assert im.mode == "RGBA" and im.getextrema()[3] == (0, 255)
    with Image.open(BASE / "turto_icon.png") as png:
        alpha = png.getchannel("A")
        # Empty space INSIDE the image must stay transparent (rounded white
        # cards passed the former corner-only transparency checks).
        assert alpha.getpixel((128, 12)) == 0
        assert sum(alpha.histogram()[:16]) > 256 * 256 * 0.65
        assert png.getpixel((128, 12)) == (0, 0, 0, 0)
    with Image.open(BASE / "turto_logo.ico") as im:
        for size in im.ico.sizes():
            alpha = im.ico.getimage(size).convert("RGBA").getchannel("A")
            assert sum(alpha.histogram()[:32]) > size[0] * size[1] * 0.6

        assert {(n, n) for n in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)} <= im.ico.sizes()
        with Image.open(BASE / "turto_icon.png") as png:
            assert png.size == (256, 256)
            assert im.ico.getimage((256, 256)).tobytes() == png.convert("RGBA").tobytes()

    with tempfile.TemporaryDirectory(prefix="turto-branding-") as td:
        root = Path(td)
        bundle = root / "_internal"
        bundle.mkdir()
        # Simulate an old installation plus a new PyInstaller onedir payload.
        for name in ("turto_crm.ico", "turto_crm.png", "turto_logo.ico", "turto_logo.png"):
            (root / name).write_bytes(b"OLD")
        for name in ("turto_logo.ico", "turto_logo.png", "turto_icon.png"):
            (bundle / name).write_bytes(b"NEW")
        expected = (bundle / "turto_logo.ico", bundle / "turto_icon.png", "packaged-logo")
        assert branding.icon_pair(root) == expected
        assert branding.logo_path(root) == bundle / "turto_logo.png"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", str(bundle), create=True):
            assert branding.icon_pair(root / "unrelated-working-directory") == expected
            assert branding.logo_path(root) == bundle / "turto_logo.png"
        # Current source installs take priority over historical generated icons.
        for path in bundle.iterdir():
            path.unlink()
        assert branding.icon_pair(root)[0] == root / "turto_logo.ico"
        for name in ("turto_logo.ico", "turto_logo.png"):
            (root / name).unlink()
        assert branding.icon_pair(root) is None
    print("TURTO CRM 8.0.10 transparent branding assets and upgrade paths: OK")


if __name__ == "__main__":
    main()
