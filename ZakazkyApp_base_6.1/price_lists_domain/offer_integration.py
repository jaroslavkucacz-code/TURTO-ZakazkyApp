"""Classification bridge between Nabídky and Ceníky."""
from __future__ import annotations
import json,tempfile
from pathlib import Path
from . import context as ctx
from .metadata import _metadata_dialog
from .model import _base_item
from .parser import parse_price_list_file
from .storage import _save_price_list
from .common import _number

def classify_selected_offer_as_price_list(app):
    selection = getattr(app, "offer_tree", None).selection() if getattr(app, "offer_tree", None) is not None else ()
    if len(selection) != 1:
        return ctx.M.messagebox.showinfo("Nabídky", "Vyberte jednu nabídku.", parent=app)
    offer_id = int(str(selection[0])[1:])
    with ctx.M.db() as con:
        existing = con.execute("SELECT id FROM price_lists WHERE source_offer_id=?", (offer_id,)).fetchone()
        offer = con.execute(
            """SELECT o.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(o.supplier_name),''),'') supplier
               FROM supplier_offers o LEFT JOIN companies c ON c.id=o.supplier_company_id WHERE o.id=?""",
            (offer_id,),
        ).fetchone()
        attachment = con.execute(
            """SELECT filename,content_blob FROM offer_source_attachments
               WHERE offer_id=? AND content_blob IS NOT NULL
               ORDER BY CASE WHEN lower(extension)='.pdf' THEN 0 ELSE 1 END,id LIMIT 1""",
            (offer_id,),
        ).fetchone()
        offer_items = con.execute(
            """SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id""",
            (offer_id,),
        ).fetchall()
    if existing:
        return ctx.M.messagebox.showinfo("Nabídky", "Tato nabídka už je evidovaná jako Ceník.", parent=app)
    if not offer:
        return
    temp = None
    source_path = Path(str(offer["source_pdf"] or ""))
    try:
        if source_path.is_file():
            path = source_path
        elif attachment and attachment["content_blob"]:
            temp = tempfile.TemporaryDirectory(prefix="turto_offer_to_pricelist_")
            filename = Path(str(attachment["filename"] or "cenik.pdf")).name
            path = Path(temp.name) / filename
            path.write_bytes(bytes(attachment["content_blob"]))
        else:
            return ctx.M.messagebox.showwarning("Nabídky", "Původní soubor nabídky už není dostupný v DB ani na disku.", parent=app)
        try:
            parsed = parse_price_list_file(path)
        except Exception as exc:
            if not offer_items:
                raise
            parsed = {
                "supplier": offer["supplier"] or "",
                "title": offer["reference"] or offer["offer_number"] or path.stem,
                "valid_from": offer["offer_date"] or "",
                "valid_to": "", "product_group": "", "branch": "", "currency": offer["currency"] or "CZK",
                "items": [], "terms_text": "", "raw_text": "", "ocr_text": "", "ocr_layout_json": "", "ocr_engine": "",
                "parse_status": "Položky převzaty z uložené nabídky; zdrojový parser: " + str(exc)[:300],
                "source_type": path.suffix.lstrip(".").upper(), "suggested_update_mode": "partial",
            }
        if offer_items:
            parsed["items"] = [
                _base_item(
                    row_no=int(row["position"] or index),
                    product_code=str(row["product_code"] or ""),
                    item_key=str(row["item_key"] or ""),
                    name=str(row["original_name"] or row["item_key"] or ""),
                    description=str(row["details"] or ""),
                    unit=str(row["unit"] or ""),
                    source_price=_number(row["original_unit_price"] or row["unit_price"]),
                    normalized_unit_price=_number(row["unit_price"]),
                    discount_pct=_number(row["discount_pct"]),
                    minimum_qty=_number(row["quantity"]),
                    source_row_json=json.dumps(dict(row), ensure_ascii=False, default=str),
                )
                for index, row in enumerate(offer_items, 1)
            ]
            parsed["parse_status"] = "Položky převzaty z uložené nabídky"
        if not parsed.get("supplier"):parsed["supplier"] = offer["supplier"] or ""
        if not parsed.get("title"):parsed["title"] = offer["reference"] or offer["offer_number"] or path.stem
        if not parsed.get("valid_from"):parsed["valid_from"] = offer["offer_date"] or ""
        metadata = _metadata_dialog(app, parsed, path, offer_id)
        if not metadata:return
        _save_price_list(path, parsed, metadata)
        app.refresh_price_lists(); app.refresh_offers()
    except Exception as exc:
        ctx.M.messagebox.showerror("Nabídky → Ceník", str(exc), parent=app)
    finally:
        try:
            if temp:temp.cleanup()
        except Exception:pass


def _install_offer_integration(module):
    old_build = module.App.build_offers
    old_refresh = module.App.refresh_offers

    def build_offers(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        try:
            tree = self.offer_tree
            columns = list(tree.cget("columns"))
            if "Typ" not in columns:
                columns.append("Typ")
                tree.configure(columns=columns, displaycolumns=columns)
                tree.heading("Typ", text="Typ")
                tree.column("Typ", width=90, minwidth=70, stretch=False, anchor="w")
            page = self.tabs["offers"]
            toolbar = module.ttk.Frame(page, style="Panel.TFrame", padding=(10, 5))
            toolbar.pack(fill="x", before=tree.master, pady=(0, 6))
            module.ttk.Button(toolbar, text="Označit jako Ceník…", style="Toolbar.TButton",
                              command=lambda: classify_selected_offer_as_price_list(self)).pack(side="right")
            self.offer_type_filter = module.tk.StringVar(value="Vše")
            module.ttk.Label(toolbar, text="Zobrazit:", style="PageSubtitle.TLabel").pack(side="left")
            box = module.safe_combobox(toolbar, textvariable=self.offer_type_filter,
                                       values=["Vše", "Nabídky", "Ceníky"], state="readonly", width=12)
            box.pack(side="left", padx=(5, 0))
            self.offer_type_filter.trace_add("write", lambda *_: self.refresh_offers())
            self.refresh_offers()
        except Exception:
            pass
        return result

    def refresh_offers(self, *args, **kwargs):
        result = old_refresh(self, *args, **kwargs)
        tree = getattr(self, "offer_tree", None)
        if tree is None:
            return result
        try:
            ids = [int(str(iid)[1:]) for iid in tree.get_children("") if str(iid).startswith("o")]
            linked = set()
            if ids:
                placeholders = ",".join("?" for _ in ids)
                with module.db() as con:
                    linked = {int(row[0]) for row in con.execute(
                        f"SELECT source_offer_id FROM price_lists WHERE source_offer_id IN ({placeholders})", tuple(ids)
                    ).fetchall()}
            type_var = getattr(self, "offer_type_filter", None)
            mode = type_var.get() if type_var is not None else "Vše"
            for iid in list(tree.get_children("")):
                offer_id = int(str(iid)[1:])
                is_price_list = offer_id in linked
                try:tree.set(iid, "Typ", "Ceník" if is_price_list else "Nabídka")
                except Exception:pass
                if mode == "Ceníky" and not is_price_list:tree.delete(iid)
                elif mode == "Nabídky" and is_price_list:tree.delete(iid)
        except Exception:
            pass
        return result

    module.App.build_offers = build_offers
    module.App.refresh_offers = refresh_offers
