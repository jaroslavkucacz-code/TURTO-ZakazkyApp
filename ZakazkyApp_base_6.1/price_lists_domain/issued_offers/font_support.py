"""Unicode font support for issued-offer PDFs.

Windows production uses Calibri when it is installed. Linux CI and other
platforms fall back to a metrically stable Unicode sans font. Fonts are read
from the local operating system only and are embedded into the generated PDF;
no font file is distributed with TURTO CRM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_PAGE_FONTS: dict[tuple[int, int], tuple[str, str]] = {}
_FONT_FILES: tuple[Path | None, Path | None] | None = None


def _font_files() -> tuple[Path | None, Path | None]:
    global _FONT_FILES
    if _FONT_FILES is not None:
        return _FONT_FILES

    candidates: list[tuple[Path, Path]] = []
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        candidates.extend(
            (
                (root / "calibri.ttf", root / "calibrib.ttf"),
                (root / "arial.ttf", root / "arialbd.ttf"),
            )
        )
    elif sys.platform == "darwin":
        candidates.extend(
            (
                (Path("/Library/Fonts/Arial.ttf"), Path("/Library/Fonts/Arial Bold.ttf")),
                (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
            )
        )
    else:
        candidates.extend(
            (
                (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
                (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
                (Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf")),
            )
        )

    for regular, bold in candidates:
        if regular.is_file():
            _FONT_FILES = (regular, bold if bold.is_file() else regular)
            return _FONT_FILES
    _FONT_FILES = (None, None)
    return _FONT_FILES


def _registered_fonts(page) -> tuple[str, str]:
    key = (id(page.parent), int(getattr(page, "number", 0)))
    cached = _PAGE_FONTS.get(key)
    if cached:
        return cached

    regular_file, bold_file = _font_files()
    regular_name, bold_name = "helv", "hebo"
    if regular_file is not None:
        try:
            regular_name = "TURTORegular"
            page.insert_font(fontname=regular_name, fontfile=str(regular_file))
        except Exception:
            regular_name = "helv"
    if bold_file is not None:
        try:
            bold_name = "TURTOBold"
            page.insert_font(fontname=bold_name, fontfile=str(bold_file))
        except Exception:
            bold_name = regular_name if regular_name != "helv" else "hebo"
    elif regular_name != "helv":
        bold_name = regular_name

    result = (regular_name, bold_name)
    _PAGE_FONTS[key] = result
    return result


def fit_text(
    page,
    rect,
    text: str,
    fontsize=9.0,
    fontname="helv",
    align=0,
    color=(0.08, 0.12, 0.16),
    lineheight=1.2,
):
    """Insert searchable Czech text and shrink it only when the box is too small."""
    regular_name, bold_name = _registered_fonts(page)
    requested = str(fontname or "helv").casefold()
    actual_font = bold_name if requested in {"hebo", "bold", "turto-bold", "turtobold"} else regular_name
    value = str(text or "")
    size = float(fontsize)
    while size >= 6.0:
        result = page.insert_textbox(
            rect,
            value,
            fontsize=size,
            fontname=actual_font,
            color=color,
            align=align,
            lineheight=lineheight,
        )
        if result >= -0.5:
            return size
        size -= 0.5
    page.insert_textbox(
        rect,
        value,
        fontsize=6.0,
        fontname=actual_font,
        color=color,
        align=align,
        lineheight=lineheight,
    )
    return 6.0


__all__ = ["fit_text"]
