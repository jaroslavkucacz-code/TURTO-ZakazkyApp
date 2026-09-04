"""TURTO CRM 7.6.9 - Nevoga / Reinforcement Systems rich offer descriptions.

Technical dimensions stay inside one product-description string. The existing
`details_rich_json` text field stores presentation metadata only (which fragments
were red/bold in the supplier PDF); no supplier-specific geometry columns are
added to the CRM schema.
"""
from __future__ import annotations

import json


def _is_nevoga_name(value):
    folded = str(value or "").strip().casefold()
    return any(token in folded for token in ("nevoga", "nevegar", "reinforcement systems"))


def _normalized_segments(raw_segments):
    result = []
    for segment in raw_segments or ():
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "")
        if not text:
            continue
        color = str(segment.get("color") or "").strip()
        changed = bool(segment.get("changed")) or color.upper() in {
            "#FF0000", "FF0000", "#C62828", "C62828",
        }
        current = {
            "text": text,
            "bold": bool(segment.get("bold")),
            "color": "#FF0000" if changed else color,
            "changed": changed,
        }
        if (
            result
            and result[-1]["bold"] == current["bold"]
            and result[-1]["color"] == current["color"]
            and result[-1]["changed"] == current["changed"]
        ):
            result[-1]["text"] += current["text"]
        else:
            result.append(current)
    return result


def _decode_segments(raw):
    try:
        value = json.loads(str(raw or ""))
    except Exception:
        return []
    return _normalized_segments(value if isinstance(value, list) else [])


def _has_supplier_change(raw):
    return any(segment.get("changed") for segment in _decode_segments(raw))


def apply(M):
    if getattr(M, "_turto_v769_nevoga_offer", False):
        return
    M._turto_v769_nevoga_offer = True

    previous_ensure_schema = M.ensure_schema

    def ensure_schema():
        result = previous_ensure_schema()
        with M.db() as con:
            columns = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(supplier_offer_items)")
            }
            if "details_rich_json" not in columns:
                con.execute(
                    "ALTER TABLE supplier_offer_items "
                    "ADD COLUMN details_rich_json TEXT DEFAULT ''"
                )
        return result

    M.ensure_schema = ensure_schema
    try:
        ensure_schema()
    except Exception:
        # The canonical launcher runs schema setup again after all layers apply.
        pass

    def store_rich_descriptions(offer_id, parsed):
        parsed_items = list((parsed or {}).get("items") or [])
        expected = [
            item for item in parsed_items
            if _normalized_segments(item.get("rich_segments") or [])
        ]
        if not expected:
            return 0

        with M.db() as con:
            columns = {
                str(row[1])
                for row in con.execute("PRAGMA table_info(supplier_offer_items)")
            }
            if "details_rich_json" not in columns:
                con.execute(
                    "ALTER TABLE supplier_offer_items "
                    "ADD COLUMN details_rich_json TEXT DEFAULT ''"
                )

            rows = con.execute(
                "SELECT id,position FROM supplier_offer_items "
                "WHERE offer_id=? ORDER BY position,id",
                (int(offer_id),),
            ).fetchall()
            by_position = {}
            for row in rows:
                by_position.setdefault(int(row["position"] or 0), []).append(int(row["id"]))

            stored = 0
            for item in parsed_items:
                segments = _normalized_segments(item.get("rich_segments") or [])
                if not segments:
                    continue
                position = int(item.get("position") or 0)
                candidates = by_position.get(position) or []
                if not candidates:
                    continue
                item_id = candidates.pop(0)
                con.execute(
                    "UPDATE supplier_offer_items SET details_rich_json=? WHERE id=?",
                    (
                        json.dumps(segments, ensure_ascii=False, separators=(",", ":")),
                        item_id,
                    ),
                )
                stored += 1
        return stored

    M.store_offer_rich_descriptions = store_rich_descriptions

    previous_save_offer_import = M.save_offer_import

    def save_offer_import(*args, **kwargs):
        result = previous_save_offer_import(*args, **kwargs)
        try:
            offer_id = int(result[0])
            parsed = result[3] if len(result) > 3 else {}
            supplier_before = str((parsed or {}).get("supplier") or "")

            # Historical development builds called this provider "Nevegar".
            # Normalize the user-facing identity to the actual supplier name
            # used in the enquiry mail: Nevoga. This also improves company match.
            if _is_nevoga_name(supplier_before):
                parsed["supplier"] = "Nevoga"
                with M.db() as con:
                    company_id = None
                    resolver = getattr(M, "_company_id_by_name", None)
                    if callable(resolver):
                        try:
                            company_id = resolver(con, "Nevoga")
                        except Exception:
                            company_id = None
                    if company_id:
                        con.execute(
                            "UPDATE supplier_offers SET supplier_name='Nevoga', "
                            "supplier_company_id=coalesce(supplier_company_id,?) WHERE id=?",
                            (company_id, offer_id),
                        )
                    else:
                        con.execute(
                            "UPDATE supplier_offers SET supplier_name='Nevoga' WHERE id=?",
                            (offer_id,),
                        )

            expected = sum(
                1
                for item in list((parsed or {}).get("items") or [])
                if _normalized_segments(item.get("rich_segments") or [])
            )
            if expected:
                stored = store_rich_descriptions(offer_id, parsed)
                if _is_nevoga_name(parsed.get("supplier")) and stored != expected:
                    raise RuntimeError(
                        "Nepodařilo se zachovat červené/formátované části "
                        "popisu nabídky Nevoga. Import nebyl označen za kompletní."
                    )
        except RuntimeError:
            raise
        except Exception:
            # Non-rich/legacy suppliers keep their established import path.
            pass
        return result

    M.save_offer_import = save_offer_import

    # ------------------------------------------------------------------
    # Received-offer detail: Treeview cannot colour only part of one cell.
    # Mark the whole supplier-changed row in red. The exact changed fragments
    # remain stored in details_rich_json and are rendered partially red in Excel.
    # ------------------------------------------------------------------
    try:
        import crm_features
    except Exception:
        crm_features = None

    candidates = []
    for cls in (
        getattr(crm_features, "OfferDetailDialog", None) if crm_features else None,
        getattr(M, "OfferDetailDialog", None),
    ):
        if cls is not None and cls not in candidates:
            candidates.append(cls)

    for cls in candidates:
        if getattr(cls, "_turto_v769_nevoga_detail", False):
            continue
        previous_build = cls._build

        def build(self, *args, __previous=previous_build, **kwargs):
            result = __previous(self, *args, **kwargs)
            try:
                offer = getattr(self, "offer_row", None)
                supplier = (offer["supplier"] if offer is not None else "") or ""
                if not _is_nevoga_name(supplier):
                    return result
                tree = getattr(self, "tree", None)
                if tree is None:
                    return result

                try:
                    tree.heading("Původní název", text="Popis výrobku")
                except Exception:
                    pass
                tree.tag_configure(
                    "supplier_changed",
                    foreground="#C62828",
                    font=("Calibri", 10, "bold"),
                )
                with M.db() as con:
                    rows = con.execute(
                        "SELECT id,details_rich_json FROM supplier_offer_items "
                        "WHERE offer_id=?",
                        (int(self.oid),),
                    ).fetchall()
                for row in rows:
                    if not _has_supplier_change(row["details_rich_json"]):
                        continue
                    iid = f"i{row['id']}"
                    if not tree.exists(iid):
                        continue
                    tags = list(tree.item(iid, "tags") or ())
                    if "supplier_changed" not in tags:
                        tags.append("supplier_changed")
                    tree.item(iid, tags=tuple(tags))
            except Exception:
                pass
            return result

        cls._build = build
        cls._turto_v769_nevoga_detail = True

    # ------------------------------------------------------------------
    # Canonical DB export. v624 treats every unknown supplier as Leviat, so
    # Nevoga is routed back to its own provider to preserve partial red text
    # and the product-type picture.
    # ------------------------------------------------------------------
    previous_export_offer_excel = getattr(M, "export_offer_excel", None)

    def export_offer_excel(app, offer_id, parent=None):
        with M.db() as con:
            offer = con.execute(
                """SELECT o.*,
                          coalesce(nullif(trim(s.official_name),''),
                                   nullif(trim(s.short_name),''),
                                   nullif(trim(o.supplier_name),''),'') supplier
                   FROM supplier_offers o
                   LEFT JOIN companies s ON s.id=o.supplier_company_id
                   WHERE o.id=?""",
                (int(offer_id),),
            ).fetchone()
        if not offer or not _is_nevoga_name(offer["supplier"]):
            if callable(previous_export_offer_excel):
                return previous_export_offer_excel(app, offer_id, parent=parent)
            return None

        from tkinter import filedialog, messagebox

        initial = (
            M.offer_export_filename(offer_id)
            if callable(getattr(M, "offer_export_filename", None))
            else f"Extrakce dat CN {offer['offer_number'] or 'nabidka'}.xlsx"
        )
        path = filedialog.asksaveasfilename(
            parent=parent or app,
            title="Extrakce dat nabídky",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=initial,
        )
        if not path:
            return None

        try:
            with M.db() as con:
                items = con.execute(
                    "SELECT * FROM supplier_offer_items "
                    "WHERE offer_id=? ORDER BY position,id",
                    (int(offer_id),),
                ).fetchall()

            parsed_items = []
            for item in items:
                parsed_items.append(
                    {
                        "position": item["position"],
                        "product": item["product_code"] or "",
                        "description": item["original_name"] or item["item_key"] or "",
                        "item_key": item["item_key"] or item["original_name"] or "",
                        "details": item["details"] or "",
                        "rich_segments": _decode_segments(item["details_rich_json"]),
                        "quantity": item["quantity"] or 0,
                        "unit": item["unit"] or "ks",
                        "original_unit_price": item["original_unit_price"] or item["unit_price"] or 0,
                        "discount_pct": item["discount_pct"] or 0,
                        "unit_price": item["unit_price"] or 0,
                        "item_total": item["total_price"] or 0,
                        "image_bytes": bytes(item["image_blob"]) if item["image_blob"] else None,
                        "image_ext": item["image_ext"] or "png",
                    }
                )

            router = M._load_offer_router()
            provider = next(
                (
                    entry for entry in router.parsers()
                    if _is_nevoga_name(entry.get("supplier"))
                ),
                None,
            )
            if not provider or not callable(provider.get("export")):
                raise RuntimeError("Chybí Excel export pro nabídky Nevoga.")

            data = {
                "supplier": "Nevoga",
                "offer_no": offer["offer_number"] or "",
                "date": offer["offer_date"] or "",
                "reference": offer["reference"] or "",
                "net": float(offer["net_value"] or offer["total_value"] or 0),
                "total": float(offer["total_value"] or offer["net_value"] or 0),
                "currency": offer["currency"] or "CZK",
                "items": parsed_items,
            }
            provider["export"](data, path, price_alerts=None)
            messagebox.showinfo(
                "Extrakce dat",
                f"Extrakce vytvořena:\n{path}",
                parent=parent or app,
            )
            return path
        except Exception as exc:
            messagebox.showerror(
                "Extrakce dat",
                str(exc),
                parent=parent or app,
            )
            return None

    if callable(previous_export_offer_excel):
        M.export_offer_excel = export_offer_excel

    M.V769_NEVOGA_RICH_DESCRIPTION = {
        "technical_columns_added": False,
        "description_owner": "supplier_offer_items.original_name",
        "rich_format_owner": "supplier_offer_items.details_rich_json",
        "supplier_red_preserved": True,
        "excel_partial_red": True,
        "detail_changed_rows_red": True,
    }
