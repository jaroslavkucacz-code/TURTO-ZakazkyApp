"""Local PDF rendering and Outlook draft creation for issued offers.

PyMuPDF is already a required TURTO dependency. The renderer therefore avoids a
second PDF framework while still providing deterministic multi-page output,
repeated table headings and uploaded PNG/JPG/PDF header/footer assets.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import service

A4_WIDTH = 595.276
A4_HEIGHT = 841.890
MM = 72.0 / 25.4


def _fit_text(page, rect, text: str, fontsize=9.0, fontname="helv", align=0, color=(0.08, 0.12, 0.16), lineheight=1.2):
    import fitz

    value = str(text or "")
    size = float(fontsize)
    while size >= 6.0:
        rc = page.insert_textbox(
            rect, value, fontsize=size, fontname=fontname, color=color,
            align=align, lineheight=lineheight,
        )
        if rc >= -0.5:
            return size
        size -= 0.5
    page.insert_textbox(rect, value, fontsize=6.0, fontname=fontname, color=color, align=align, lineheight=lineheight)
    return 6.0


def _asset_bytes(path: str | Path, target_rect) -> tuple[bytes | None, int | None]:
    path = Path(str(path or ""))
    if not path.is_file():
        return None, None
    if path.suffix.lower() == ".pdf":
        try:
            import fitz
            source = fitz.open(path)
            if not source.page_count:
                source.close()
                return None, None
            pdf_bytes = source.tobytes(garbage=3, deflate=True)
            source.close()
            return pdf_bytes, 0
        except Exception:
            return None, None
    return path.read_bytes(), None


def _draw_asset(page, rect, path: str | Path) -> None:
    payload, pdf_page = _asset_bytes(path, rect)
    if not payload:
        return
    try:
        if pdf_page is None:
            page.insert_image(rect, stream=payload, keep_proportion=True, overlay=True)
        else:
            import fitz
            source = fitz.open(stream=payload, filetype="pdf")
            page.show_pdf_page(rect, source, pdf_page, keep_proportion=True, overlay=True)
            source.close()
    except Exception:
        pass


def _money(value, currency="CZK") -> str:
    text = f"{service.number(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency or 'CZK'}"


def _number(value, decimals=2) -> str:
    text = f"{service.number(value):,.{decimals}f}".replace(",", " ").replace(".", ",")
    return text.rstrip("0").rstrip(",") if "," in text else text


def _contact_lines(document: dict[str, Any], prefix: str) -> list[str]:
    labels = {
        "issuer": (
            "issuer_name_snapshot", "issuer_address_snapshot", "issuer_ico_snapshot", "issuer_dic_snapshot",
            "issuer_contact_snapshot", "issuer_email_snapshot", "issuer_phone_snapshot", "issuer_bank_snapshot",
        ),
        "customer": (
            "customer_name_snapshot", "customer_address_snapshot", "customer_ico_snapshot", "customer_dic_snapshot",
            "customer_contact_snapshot", "customer_email_snapshot", "customer_phone_snapshot", "",
        ),
    }
    keys = labels[prefix]
    lines = [str(document.get(keys[0]) or "")]
    if document.get(keys[1]): lines.append(str(document.get(keys[1])))
    ids = []
    if document.get(keys[2]): ids.append("IČ: " + str(document.get(keys[2])))
    if document.get(keys[3]): ids.append("DIČ: " + str(document.get(keys[3])))
    if ids: lines.append("   |   ".join(ids))
    if document.get(keys[4]): lines.append("Kontakt: " + str(document.get(keys[4])))
    contact = "   |   ".join(str(document.get(key)) for key in keys[5:7] if key and document.get(key))
    if contact: lines.append(contact)
    if keys[7] and document.get(keys[7]): lines.append("Bankovní spojení: " + str(document.get(keys[7])))
    return [line for line in lines if line.strip()]


def render_offer_pdf(M, document_id: int, output_path: str | Path | None = None, open_after: bool = False) -> Path:
    import fitz

    document, items = service.load_document(M, int(document_id))
    template = service.load_template(M, document.get("template_id"))
    revision = service.next_revision_no(M, int(document_id))
    if output_path:
        target = Path(output_path)
    else:
        target = service.document_archive_dir(M, document) / f"{service.safe_filename(document['document_number'])}_R{revision:02d}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    margin_left = service.number(template.get("margin_left_mm"), 14) * MM
    margin_right = service.number(template.get("margin_right_mm"), 14) * MM
    header_height = service.number(template.get("header_height_mm"), 25) * MM
    footer_height = service.number(template.get("footer_height_mm"), 14) * MM
    body_top_gap = service.number(template.get("body_top_gap_mm"), 5) * MM
    body_bottom_gap = service.number(template.get("body_bottom_gap_mm"), 5) * MM
    body_top = header_height + body_top_gap + 12
    body_bottom = A4_HEIGHT - footer_height - body_bottom_gap - 12
    page_width = A4_WIDTH - margin_left - margin_right
    currency = str(document.get("currency") or "CZK")
    accent = (0.09, 0.20, 0.29)
    gold = (0.78, 0.57, 0.10)
    line = (0.78, 0.81, 0.84)
    light = (0.95, 0.96, 0.97)

    pdf = fitz.open()
    state: dict[str, Any] = {"page": None, "y": 0.0, "page_no": 0}

    def new_page(first=False):
        page = pdf.new_page(width=A4_WIDTH, height=A4_HEIGHT)
        state["page"] = page
        state["page_no"] += 1
        if header_height > 0:
            rect = fitz.Rect(margin_left, 8, A4_WIDTH - margin_right, 8 + header_height)
            if first or int(template.get("header_every_page", 1)):
                _draw_asset(page, rect, template.get("header_path", ""))
        if footer_height > 0:
            rect = fitz.Rect(margin_left, A4_HEIGHT - footer_height - 8, A4_WIDTH - margin_right, A4_HEIGHT - 8)
            if first or int(template.get("footer_every_page", 1)):
                _draw_asset(page, rect, template.get("footer_path", ""))
        page.insert_text((A4_WIDTH - margin_right - 55, A4_HEIGHT - 7), f"Strana {state['page_no']}", fontsize=7.5, color=(0.35, 0.38, 0.42))
        state["y"] = body_top
        return page

    def ensure(height, repeat_table_header=False):
        if state["page"] is None:
            new_page(first=True)
        if state["y"] + height > body_bottom:
            new_page(first=False)
            if repeat_table_header:
                draw_table_header()
        return state["page"]

    def draw_line(y):
        state["page"].draw_line((margin_left, y), (A4_WIDTH - margin_right, y), color=line, width=0.6)

    def draw_table_header():
        page = ensure(22)
        y = state["y"]
        page.draw_rect(fitz.Rect(margin_left, y, A4_WIDTH - margin_right, y + 20), color=accent, fill=accent)
        columns = [
            (0, 26, "Poz.", 1),
            (26, 90, "Kód", 0),
            (90, page_width - 210, "Popis", 0),
            (page_width - 120, 48, "Mn.", 1),
            (page_width - 72, 34, "MJ", 1),
            (page_width - 38, 86, "Cena/MJ", 2),
            (page_width + 48, 96, "Celkem", 2),
        ]
        for x, width, label, align in columns:
            _fit_text(page, fitz.Rect(margin_left + x + 2, y + 4, margin_left + x + width - 2, y + 18), label, 8, "hebo", align, (1, 1, 1))
        state["y"] += 20

    page = new_page(first=True)
    _fit_text(page, fitz.Rect(margin_left, state["y"], A4_WIDTH - margin_right, state["y"] + 28), "CENOVÁ NABÍDKA", 18, "hebo", 1, accent)
    state["y"] += 25
    _fit_text(page, fitz.Rect(margin_left, state["y"], A4_WIDTH - margin_right, state["y"] + 18), document.get("document_number", ""), 11, "hebo", 1, gold)
    state["y"] += 28

    card_gap = 12
    card_width = (page_width - card_gap) / 2
    card_height = 83
    page.draw_rect(fitz.Rect(margin_left, state["y"], margin_left + card_width, state["y"] + card_height), color=line, fill=light, width=0.6)
    page.draw_rect(fitz.Rect(margin_left + card_width + card_gap, state["y"], A4_WIDTH - margin_right, state["y"] + card_height), color=line, fill=light, width=0.6)
    _fit_text(page, fitz.Rect(margin_left + 8, state["y"] + 7, margin_left + card_width - 8, state["y"] + 20), "DODAVATEL", 8, "hebo", 0, gold)
    _fit_text(page, fitz.Rect(margin_left + card_width + card_gap + 8, state["y"] + 7, A4_WIDTH - margin_right - 8, state["y"] + 20), "ODBĚRATEL", 8, "hebo", 0, gold)
    _fit_text(page, fitz.Rect(margin_left + 8, state["y"] + 23, margin_left + card_width - 8, state["y"] + card_height - 5), "\n".join(_contact_lines(document, "issuer")), 8.5, "helv", 0, accent)
    _fit_text(page, fitz.Rect(margin_left + card_width + card_gap + 8, state["y"] + 23, A4_WIDTH - margin_right - 8, state["y"] + card_height - 5), "\n".join(_contact_lines(document, "customer")), 8.5, "helv", 0, accent)
    state["y"] += card_height + 12

    details = [
        ("Datum vystavení", M.fmt_date(document.get("issue_date"))),
        ("Platnost do", M.fmt_date(document.get("valid_to"))),
        ("Akce", document.get("project_name") or document.get("action_name") or "—"),
        ("Reference zákazníka", document.get("customer_reference") or "—"),
        ("Předmět", document.get("offer_subject") or "—"),
    ]
    detail_height = max(46, 13 * len(details))
    ensure(detail_height)
    page = state["page"]
    page.draw_rect(fitz.Rect(margin_left, state["y"], A4_WIDTH - margin_right, state["y"] + detail_height), color=line, width=0.6)
    for index, (label, value) in enumerate(details):
        y = state["y"] + 7 + index * 12
        _fit_text(page, fitz.Rect(margin_left + 7, y, margin_left + 110, y + 11), label, 8, "hebo", 0, accent)
        _fit_text(page, fitz.Rect(margin_left + 112, y, A4_WIDTH - margin_right - 7, y + 11), str(value or ""), 8.5, "helv", 0, (0.12, 0.14, 0.16))
    state["y"] += detail_height + 13

    draw_table_header()
    product_position = 0
    for raw in items:
        item = service.normalize_item(raw)
        row_type = item.get("row_type")
        if row_type == "heading":
            ensure(27, True)
            page = state["page"]
            page.draw_rect(fitz.Rect(margin_left, state["y"], A4_WIDTH - margin_right, state["y"] + 24), color=(0.84, 0.86, 0.88), fill=(0.92, 0.93, 0.94), width=0.4)
            _fit_text(page, fitz.Rect(margin_left + 5, state["y"] + 5, A4_WIDTH - margin_right - 5, state["y"] + 20), item.get("name") or item.get("description"), 9, "hebo", 0, accent)
            state["y"] += 24
            continue
        if row_type == "text":
            text = str(item.get("description") or item.get("name") or "")
            lines = max(1, (len(text) // 105) + 1)
            height = max(24, 12 * lines + 8)
            ensure(height, True)
            _fit_text(state["page"], fitz.Rect(margin_left + 5, state["y"] + 4, A4_WIDTH - margin_right - 5, state["y"] + height - 3), text, 8.5, "helv", 0, (0.20, 0.22, 0.24))
            state["y"] += height
            continue

        product_position += 1
        description = str(item.get("name") or item.get("internal_name_snapshot") or item.get("description") or "")
        if item.get("description") and item.get("description") != description:
            description += "\n" + str(item.get("description"))
        if item.get("line_note"):
            description += "\n" + str(item.get("line_note"))
        lines = max(1, (len(description) // 58) + description.count("\n") + 1)
        height = max(25, 10 * lines + 7)
        ensure(height, True)
        page = state["page"]
        y = state["y"]
        if product_position % 2 == 0:
            page.draw_rect(fitz.Rect(margin_left, y, A4_WIDTH - margin_right, y + height), color=None, fill=(0.975, 0.978, 0.981))
        code = item.get("internal_code_snapshot") or item.get("product_code") or ""
        _fit_text(page, fitz.Rect(margin_left + 2, y + 4, margin_left + 24, y + height - 2), str(product_position), 8, "helv", 1)
        _fit_text(page, fitz.Rect(margin_left + 28, y + 4, margin_left + 88, y + height - 2), str(code), 7.8, "helv", 0)
        _fit_text(page, fitz.Rect(margin_left + 92, y + 4, A4_WIDTH - margin_right - 211, y + height - 2), description, 8.3, "helv", 0)
        _fit_text(page, fitz.Rect(A4_WIDTH - margin_right - 208, y + 4, A4_WIDTH - margin_right - 164, y + height - 2), _number(item.get("quantity")), 8.3, "helv", 2)
        _fit_text(page, fitz.Rect(A4_WIDTH - margin_right - 160, y + 4, A4_WIDTH - margin_right - 130, y + height - 2), str(item.get("unit") or ""), 8.3, "helv", 1)
        _fit_text(page, fitz.Rect(A4_WIDTH - margin_right - 125, y + 4, A4_WIDTH - margin_right - 50, y + height - 2), _money(item.get("unit_price"), currency), 8.0, "helv", 2)
        _fit_text(page, fitz.Rect(A4_WIDTH - margin_right - 47, y + 4, A4_WIDTH - margin_right - 3, y + height - 2), _money(item.get("total_price"), currency), 7.6, "helv", 2)
        draw_line(y + height)
        state["y"] += height

    totals = service.calculate_totals(items, document.get("global_discount_pct"))
    total_height = 88 if totals.global_discount else 72
    ensure(total_height)
    page = state["page"]
    x1 = A4_WIDTH - margin_right - 250
    x2 = A4_WIDTH - margin_right
    y = state["y"] + 8
    page.draw_rect(fitz.Rect(x1, state["y"], x2, state["y"] + total_height), color=line, fill=light, width=0.6)
    summary = [("Cena položek bez DPH", totals.items_subtotal)]
    if totals.global_discount:
        summary.append((f"Celková sleva {service.number(document.get('global_discount_pct')):g} %", -totals.global_discount))
    summary += [("Celkem bez DPH", totals.subtotal_net), ("DPH", totals.vat_total), ("Celkem s DPH", totals.total_gross)]
    for index, (label, value) in enumerate(summary):
        bold = index == len(summary) - 1
        row_y = y + index * 14
        _fit_text(page, fitz.Rect(x1 + 8, row_y, x1 + 135, row_y + 12), label, 8.5 if not bold else 9.5, "hebo" if bold else "helv", 0, accent)
        _fit_text(page, fitz.Rect(x1 + 138, row_y, x2 - 8, row_y + 12), _money(value, currency), 8.5 if not bold else 10, "hebo" if bold else "helv", 2, accent)
    state["y"] += total_height + 14

    sections = [
        ("Platební podmínky", document.get("payment_terms")),
        ("Dodací podmínky", document.get("delivery_terms")),
        ("Termín dodání", document.get("delivery_time")),
        ("Poznámka", document.get("customer_note")),
    ]
    for label, value in sections:
        text = str(value or "").strip()
        if not text:
            continue
        lines = max(1, (len(text) // 100) + text.count("\n") + 1)
        height = 19 + 10 * lines
        ensure(height)
        page = state["page"]
        _fit_text(page, fitz.Rect(margin_left, state["y"], A4_WIDTH - margin_right, state["y"] + 13), label, 9, "hebo", 0, gold)
        _fit_text(page, fitz.Rect(margin_left, state["y"] + 15, A4_WIDTH - margin_right, state["y"] + height), text, 8.5, "helv", 0, (0.16, 0.18, 0.20))
        state["y"] += height + 4

    # Correct page counters after the final page count is known.
    total_pages = pdf.page_count
    for index, page in enumerate(pdf):
        page.insert_text((A4_WIDTH - margin_right - 70, A4_HEIGHT - 7), f"Strana {index + 1}/{total_pages}", fontsize=7.5, color=(0.35, 0.38, 0.42), overlay=True)

    temporary = target.with_suffix(target.suffix + ".tmp")
    pdf.save(temporary, garbage=3, deflate=True, clean=True)
    pdf.close()
    os.replace(temporary, target)
    snapshot = dict(document)
    snapshot["items"] = items
    snapshot["totals"] = totals.__dict__
    service.record_revision(M, int(document_id), revision, target, snapshot)
    if open_after:
        service.open_path(target)
    return target


def latest_or_render(M, document_id: int) -> Path:
    path = service.latest_pdf_path(M, document_id)
    return path or render_offer_pdf(M, document_id)


def create_outlook_draft(M, app, document_id: int) -> None:
    document, _items = service.load_document(M, document_id)
    email = str(document.get("customer_email_snapshot") or "").strip()
    pdf = latest_or_render(M, document_id)
    subject = f"Cenová nabídka {document.get('document_number') or ''}"
    if document.get("offer_subject"):
        subject += " – " + str(document["offer_subject"])
    body = "Dobrý den,\n\n\nv příloze zasíláme cenovou nabídku.\n\nPředem velice děkuji,\n"
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = email
        mail.CC = get_cc = str(getattr(M, "CC_ALWAYS", "info@turto.cz") or "info@turto.cz")
        mail.Subject = subject
        mail.Body = body
        mail.Attachments.Add(str(pdf))
        mail.Display()
        try:
            inspector = mail.GetInspector
            hwnd = int(getattr(inspector, "HWND", 0) or 0)
            if hwnd:
                import ctypes
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        service.set_status(M, document_id, "Odesláno")
        try:
            app.refresh_issued_offers()
        except Exception:
            pass
    except Exception as exc:
        M.messagebox.showerror(
            "Vydané nabídky",
            f"Koncept Outlooku se nepodařilo vytvořit:\n\n{exc}\n\nPDF zůstalo uloženo zde:\n{pdf}",
            parent=app,
        )


def install(M) -> None:
    M.render_issued_offer_pdf = lambda document_id, output_path=None, open_after=False: render_offer_pdf(
        M, document_id, output_path, open_after
    )
    M.create_issued_offer_outlook_draft = lambda app, document_id: create_outlook_draft(M, app, document_id)


__all__ = ["render_offer_pdf", "latest_or_render", "create_outlook_draft", "install"]
