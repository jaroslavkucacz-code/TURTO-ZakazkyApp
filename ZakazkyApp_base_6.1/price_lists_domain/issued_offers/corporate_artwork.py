"""Native PDF paths and selectable text for the standard TURTO stationery.

Coordinates follow the original artwork. Only the empty middle of the header
changes width; both ends use the same uniform scale. No bitmap or OCR overlay.
"""
from pathlib import Path
import os
import fitz

NAVY = (14 / 255, 53 / 255, 74 / 255)
RED = (195 / 255, 31 / 255, 64 / 255)
GREY = (160 / 255,) * 3
WHITE = (1, 1, 1)


def header(layout, rect):
    page = layout.page
    scale = min(rect.height / 156, rect.width / 810)
    left, top = rect.x0, rect.y0 + (rect.height - 156 * scale) / 2

    def box(x0, y0, x1, y1, color):
        page.draw_rect(fitz.Rect(left + x0 * scale, top + y0 * scale,
                                 left + x1 * scale, top + y1 * scale), color=None, fill=color)

    width = rect.width / scale
    box(0, 0, width, 48, GREY)
    box(0, 48, width, 144, NAVY)
    # The architectural mark keeps its original geometry and stroke widths.
    for points in (((0, 40), (52, 10), (52, 144)),
                   ((12, 144), (12, 67), (105, 17), (137, 35), (137, 144)),
                   ((31, 144), (31, 84), (64, 65), (183, 133), (183, 144))):
        page.draw_polyline([(left + x * scale, top + y * scale) for x, y in points],
                           color=(.79, .80, .79), width=5 * scale)
    box(121, 76, 669, 135, RED)
    box(width - 61, 11, width, 156, RED)

    # Use a locally installed condensed face where available, embedded as text.
    path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "ARIALNB.TTF"
    font = fitz.Font(fontfile=str(path)) if path.is_file() else layout.fonts[1]
    page.insert_font(fontname="TRCaption", fontbuffer=font.buffer)
    title = layout.style["title"]
    title_width = (250 if layout.number_in_header else 528) * scale
    size = min(42 * scale, title_width / max(.001, font.text_length(title, fontsize=1)))
    # Center visible glyphs vertically, retaining real Unicode text in the PDF.
    baseline = top + 111 * scale
    page.insert_text((left + 127 * scale, baseline), title, fontname="TRCaption", fontsize=size, color=WHITE)
    if layout.number_in_header:
        number = str(layout.document.get("document_number") or "KONCEPT")
        font = layout.fonts[1]
        size = min(27 * scale, 273 * scale / max(.001, font.text_length(number, fontsize=1)))
        if size < 4:
            raise ValueError("Číslo je příliš dlouhé pro horní pruh. Vypněte číslo v záhlaví v nastavení šablony.")
        page.insert_text((left + 655 * scale - font.text_length(number, fontsize=size), baseline),
                         number, fontname="TRBold", fontsize=size, color=WHITE)
    page.insert_text((rect.x1 - 18 * scale, top + 134 * scale), "TURTO", fontname="TRBold",
                     fontsize=36 * scale, color=WHITE, rotate=90)


def footer(layout, rect):
    page = layout.page
    scale = min(rect.width / 1645, rect.height / 150)
    left = rect.x0 + (rect.width - 1645 * scale) / 2
    top = rect.y0 + (rect.height - 150 * scale) / 2

    def text(x, y, value, bold=False, right=None, size=21):
        font = layout.fonts[int(bold)]
        available = 351 if right == 351 else 445 if right == 1046 else 1645 - x
        size = min(size, available / max(.001, font.text_length(value, fontsize=1)))
        width = font.text_length(value, fontsize=size * scale)
        px = left + (right * scale - width if right is not None else x * scale)
        page.insert_text((px, top + y * scale), value, fontname="TRBold" if bold else "TRRegular",
                         fontsize=size * scale, color=layout.ink)

    for x, bottom in ((364, 130), (1058, 108)):
        page.draw_line((left + x * scale, top + 23 * scale),
                       (left + x * scale, top + bottom * scale), color=RED, width=3 * scale)
    text(0, 40, "Fakturační adresa / sídlo společnosti:", True, right=351, size=22)
    text(0, 64, "TURTO s. r. o.", True, right=351, size=22)
    text(0, 94, "Kaprova 42/14", right=351)
    text(0, 116, "110 00 Praha 1", right=351)
    text(376, 94, "IČ: 24196231")
    text(376, 116, "DIČ: CZ24196231")
    text(0, 40, "Sklad a provozovna:", True, right=1046, size=22)
    text(0, 72, "Masarykova 234/30", right=1046)
    text(0, 94, "268 01 Hořovice", right=1046)
    hours = layout.style["opening_hours"] if layout.style["edit_opening_hours"] else "Po – Čt: 7:30 – 15:30\nPá: 8:30 – 15:00"
    if hours:
        lines = ["Prodejní sklad – provozní doba"] + hours.splitlines()
        size = min(21, 94 / (len(lines) * 1.2))
        size = min(size, 557 / max(1, max(layout.fonts[0].text_length(line, fontsize=1) for line in lines)))
        for index, line in enumerate(lines):
            text(1070, 63 + index * size * 1.2, line, size=size)
