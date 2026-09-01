"""Offer-side performance fixes and lazy photograph controls."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from . import categories, product_catalog


def _patch_offer_detail(M) -> None:
    try:
        import crm_features
    except Exception:
        return
    candidates = []
    for cls in (getattr(crm_features, "OfferDetailDialog", None), getattr(M, "OfferDetailDialog", None)):
        if cls is not None and cls not in candidates:
            candidates.append(cls)

    for cls in candidates:
        if getattr(cls, "_turto_lazy_photo_v630", False):
            continue

        def load(self, _M=M):
            with _M.db() as con:
                header = con.execute(
                    """SELECT o.*,
                              coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),
                                       nullif(trim(o.supplier_name),''),'') supplier,
                              c.official_name customer,
                              CASE
                                WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,ra.name,'')
                                WHEN o.action_id IS NOT NULL THEN coalesce(op.name,oa.name,'')
                                WHEN o.project_id IS NOT NULL THEN coalesce(pd.name,'')
                                ELSE ''
                              END action_name
                       FROM supplier_offers o
                       LEFT JOIN companies s ON s.id=o.supplier_company_id
                       LEFT JOIN companies c ON c.id=o.customer_company_id
                       LEFT JOIN projects pd ON pd.id=o.project_id
                       LEFT JOIN requests rq ON rq.id=o.request_id
                       LEFT JOIN actions ra ON ra.id=rq.action_id
                       LEFT JOIN projects pr ON pr.id=ra.project_id
                       LEFT JOIN actions oa ON oa.id=o.action_id
                       LEFT JOIN projects op ON op.id=oa.project_id
                       WHERE o.id=?""",
                    (self.oid,),
                ).fetchone()
                # Deliberately exclude image_blob.  A thumbnail/full image is read only
                # after the user explicitly requests it.
                items = con.execute(
                    """SELECT id,offer_id,position,original_name,item_key,quantity,unit,
                              unit_price,discount,net_price,total_price,image_path,
                              image_source_offer_date,image_ext,product_code,details,
                              original_unit_price,discount_pct,category_id,subgroup_id
                       FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id""",
                    (self.oid,),
                ).fetchall()
            return header, items

        old_build = cls._build

        def build(self, *args, __old=old_build, _M=M, **kwargs):
            result = __old(self, *args, **kwargs)
            try:
                tree = getattr(self, "tree", None)
                if tree is not None:
                    columns = list(tree["columns"])
                    for name, width in (("Výrobce", 180), ("Interní kód", 130), ("Interní označení", 250), ("Produktová skupina", 250), ("Podskupina", 290)):
                        if name not in columns:
                            columns.append(name)
                    tree.configure(columns=tuple(columns), selectmode="extended")
                    for name, width in (("Výrobce", 180), ("Interní kód", 130), ("Interní označení", 250), ("Produktová skupina", 250), ("Podskupina", 290)):
                        tree.heading(name, text=name)
                        tree.column(name, width=width, minwidth=120, anchor="w", stretch=False)
                    with _M.db() as con:
                        taxonomy_rows = con.execute(
                            """SELECT i.id,i.category_id,i.subgroup_id,
                                      coalesce(c.name,'') category,coalesce(s.name,'') subgroup,
                                      coalesce(cp.manufacturer_name,'') manufacturer,
                                      coalesce(cp.internal_code,'') internal_code,
                                      coalesce(cp.internal_name,'') internal_name
                               FROM supplier_offer_items i
                               LEFT JOIN catalog_products cp ON cp.id=i.catalog_product_id
                               LEFT JOIN product_subgroups s ON s.id=i.subgroup_id
                               LEFT JOIN product_categories c ON c.id=coalesce(s.category_id,i.category_id)
                               WHERE i.offer_id=?""", (self.oid,)
                        ).fetchall()
                    for row in taxonomy_rows:
                        iid = f"i{row['id']}"
                        if tree.exists(iid):
                            tree.set(iid, "Výrobce", row["manufacturer"] or "")
                            tree.set(iid, "Interní kód", row["internal_code"] or "")
                            tree.set(iid, "Interní označení", row["internal_name"] or "")
                            tree.set(iid, "Produktová skupina", row["category"] or "Nezařazeno")
                            tree.set(iid, "Podskupina", row["subgroup"] or "")

                photo_button = None

                def walk(widget):
                    nonlocal photo_button
                    for child in widget.winfo_children():
                        try:
                            if child.winfo_class() == "TButton":
                                text = str(child.cget("text") or "")
                                if "Obrázek položky" in text or "Zobrazit obrázek" in text:
                                    photo_button = child
                                    return
                        except Exception:
                            pass
                        walk(child)
                        if photo_button is not None:
                            return

                walk(self)
                if photo_button is None:
                    return result

                def assign_taxonomy():
                    selection = tuple(tree.selection()) if tree is not None else ()
                    ids = [int(str(iid)[1:]) for iid in selection if str(iid).startswith("i")]
                    if not ids:
                        return _M.messagebox.showinfo(
                            "Nabídky", "Vyberte jednu nebo více položek nabídky.", parent=self
                        )
                    first = None
                    with _M.db() as con:
                        first = con.execute(
                            "SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=?", (ids[0],)
                        ).fetchone()
                    selected = categories.choose_taxonomy(
                        _M, self, "Přiřadit produktovou skupinu a podskupinu",
                        first["category_id"] if first else None,
                        first["subgroup_id"] if first else None,
                    )
                    if selected == "cancel":
                        return
                    category_id, subgroup_id = selected
                    categories.set_item_taxonomy(
                        _M, "supplier_offer_items", ids, category_id, subgroup_id
                    )
                    self._build()

                _M.ttk.Button(
                    photo_button.master, text="Přiřadit skupinu / podskupinu…",
                    command=assign_taxonomy,
                ).pack(side="left", padx=5)
                _M.ttk.Button(
                    photo_button.master, text="Katalog produktů…",
                    command=lambda: product_catalog.open_product_catalog(_M, self),
                ).pack(side="left", padx=5)
                user = _M.get_setting("active_user", "")
                enabled = _M.get_user_setting(user, "load_product_photos", "0") == "1"
                self._turto_photo_enabled = _M.tk.BooleanVar(value=enabled)
                photo_button.configure(text="Zobrazit obrázek")

                def sync():
                    active = bool(self._turto_photo_enabled.get())
                    photo_button.state(["!disabled"] if active else ["disabled"])
                    _M.set_user_setting(user, "load_product_photos", "1" if active else "0")

                check = _M.ttk.Checkbutton(
                    photo_button.master,
                    text="Načítat fotografie",
                    variable=self._turto_photo_enabled,
                    command=sync,
                )
                check.pack(side="left", padx=5)
                sync()
            except Exception:
                pass
            return result

        cls._load = load
        cls._build = build
        cls._turto_lazy_photo_v630 = True


def _patch_offer_to_price_list(M) -> None:
    from .. import offer_integration
    from ..common import _number
    from ..model import _base_item

    def classify_selected_offer_as_price_list(app):
        tree = getattr(app, "offer_tree", None)
        selection = tree.selection() if tree is not None else ()
        if len(selection) != 1:
            return M.messagebox.showinfo("Nabídky", "Vyberte jednu nabídku.", parent=app)
        offer_id = int(str(selection[0])[1:])
        with M.db() as con:
            existing = con.execute("SELECT id FROM price_lists WHERE source_offer_id=?", (offer_id,)).fetchone()
            offer = con.execute(
                """SELECT o.*,coalesce(nullif(trim(c.official_name),''),
                                        nullif(trim(o.supplier_name),''),'') supplier
                   FROM supplier_offers o LEFT JOIN companies c ON c.id=o.supplier_company_id
                   WHERE o.id=?""",
                (offer_id,),
            ).fetchone()
            tables = {str(row[0]) for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            attachment = None
            if "offer_source_attachments" in tables:
                attachment = con.execute(
                    """SELECT filename,content_blob FROM offer_source_attachments
                       WHERE offer_id=? AND content_blob IS NOT NULL
                       ORDER BY CASE WHEN lower(extension)='.pdf' THEN 0 ELSE 1 END,id LIMIT 1""",
                    (offer_id,),
                ).fetchone()
            offer_items = con.execute(
                """SELECT id,position,original_name,item_key,quantity,unit,unit_price,total_price,
                          product_code,details,original_unit_price,discount_pct,category_id,subgroup_id
                   FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id""",
                (offer_id,),
            ).fetchall()
        if existing:
            return M.messagebox.showinfo("Nabídky", "Tato nabídka už je evidovaná jako Ceník.", parent=app)
        if not offer:
            return

        temporary = None
        source_path = Path(str(offer["source_pdf"] or ""))
        try:
            if source_path.is_file():
                path = source_path
            elif attachment and attachment["content_blob"]:
                temporary = tempfile.TemporaryDirectory(prefix="turto_offer_to_pricelist_")
                filename = Path(str(attachment["filename"] or "cenik.pdf")).name
                path = Path(temporary.name) / filename
                path.write_bytes(bytes(attachment["content_blob"]))
            else:
                return M.messagebox.showwarning(
                    "Nabídky", "Původní soubor nabídky už není dostupný v databázi ani na disku.", parent=app
                )

            try:
                parsed = offer_integration.parse_price_list_file(path)
            except Exception as exc:
                if not offer_items:
                    raise
                parsed = {
                    "supplier": offer["supplier"] or "",
                    "title": offer["reference"] or offer["offer_number"] or path.stem,
                    "valid_from": offer["offer_date"] or "",
                    "valid_to": "", "product_group": "", "branch": "",
                    "currency": offer["currency"] or "CZK", "items": [],
                    "terms_text": "", "raw_text": "", "ocr_text": "",
                    "ocr_layout_json": "", "ocr_engine": "",
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
                        category_id=row["category_id"], subgroup_id=row["subgroup_id"],
                        source_row_json=json.dumps(
                            {
                                "id": row["id"], "position": row["position"],
                                "product_code": row["product_code"], "item_key": row["item_key"],
                                "original_name": row["original_name"], "details": row["details"],
                                "quantity": row["quantity"], "unit": row["unit"],
                                "original_unit_price": row["original_unit_price"],
                                "discount_pct": row["discount_pct"], "unit_price": row["unit_price"],
                                "total_price": row["total_price"],
                                "category_id": row["category_id"], "subgroup_id": row["subgroup_id"],
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    )
                    for index, row in enumerate(offer_items, 1)
                ]
                parsed["parse_status"] = "Položky převzaty z uložené nabídky"
            if not parsed.get("supplier"):
                parsed["supplier"] = offer["supplier"] or ""
            if not parsed.get("title"):
                parsed["title"] = offer["reference"] or offer["offer_number"] or path.stem
            if not parsed.get("valid_from"):
                parsed["valid_from"] = offer["offer_date"] or ""
            metadata = offer_integration._metadata_dialog(app, parsed, path, offer_id)
            if not metadata:
                return
            offer_integration._save_price_list(path, parsed, metadata)
            app.refresh_price_lists()
            app.refresh_offers()
        except Exception as exc:
            M.messagebox.showerror("Nabídky → Ceník", str(exc), parent=app)
        finally:
            try:
                if temporary:
                    temporary.cleanup()
            except Exception:
                pass

    offer_integration.classify_selected_offer_as_price_list = classify_selected_offer_as_price_list


def install(M) -> None:
    _patch_offer_detail(M)
    _patch_offer_to_price_list(M)
