#!/usr/bin/env python3
"""Compile native Windows icon sizes from the unmodified supplied TURTO logo."""
from pathlib import Path
from PIL import Image

BASE = Path(__file__).resolve().parents[1] / "ZakazkyApp_base_6.1"
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def main():
    with Image.open(BASE / "turto_logo.png") as source:
        logo = source.convert("RGBA")
    # Keep the complete logo, including its tagline, in its original proportions.
    # Preserve alpha throughout: neither PNG nor ICO contains a background tile.
    logo.thumbnail((240, 240), Image.Resampling.LANCZOS)
    icon = Image.new("RGBA", (256, 256))
    icon.alpha_composite(logo, ((256 - logo.width) // 2, (256 - logo.height) // 2))
    icon.save(BASE / "turto_icon.png", optimize=True)
    icon.save(BASE / "turto_logo.ico", format="ICO", sizes=[(n, n) for n in SIZES])
    # A new Shell resource path prevents reuse of the former white-tile cache.
    (BASE / "turto_taskbar_transparent.ico").write_bytes((BASE / "turto_logo.ico").read_bytes())


if __name__ == "__main__":
    main()
