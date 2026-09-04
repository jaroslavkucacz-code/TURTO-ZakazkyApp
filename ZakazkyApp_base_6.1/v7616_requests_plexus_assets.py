"""TURTO CRM 7.6.16 - request table polish and deduplicated PLEXUS images.

This final compatibility layer fixes three regressions without rewriting business
history:
- Poptavky uses a complete nine-column geometry and headings follow row anchors;
- requests waiting at least seven days are bold again, without warning glyphs;
- Nevoga PLEXUS drawings live once per PLEXUS type in a shared DB asset table.

Existing Nevoga item images are migrated transactionally.  Only after the shared
asset is stored successfully are duplicate item/canonical blobs removed.  Other
suppliers are untouched.
"""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3


REQUEST_COLUMNS = (
    "Stav",
    "Řeší",
    "Poptáno",
    "Obdrženo",
    "Odběratel",
    "Dodavatel",
    "Akce",
    "Poptáváno",
    "Příjemci",
)
REQUEST_WIDTHS = (100, 150, 90, 90, 190, 280, 220, 300, 280)
OVERDUE_TAG = "req_overdue_bold"
_TYPE_RE = re.compile(r"(?:^|\|)\s*typ\s+([A-Z]{1,2})(?=\s|\||$)", re.I)


def _is_nevoga_name(value):
    folded = str(value or "").strip().casefold()
    return any(token in folded for token in ("nevoga", "nevegar", "reinforcement systems"))


def _row_get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        try:
            return getattr(row, key)
        except Exception:
            return default


def _clean_date_text(value):
    text = str(value or "")
    for marker in ("⚠️ ", "⚠ ", "⚠️", "⚠", "● ", "●"):
        text = text.replace(marker, "")
    return text.strip()


def _plexus_type(value):
    match = _TYPE_RE.search(str(value or "").upper())
    return match.group(1).upper() if match else ""


def _asset_key(type_code):
    code = str(type_code or "").strip().upper()
    return f"nevoga:plexus:{code}" if code else ""


def _ensure_asset_schema(M):
    with M.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS offer_image_assets(
                 asset_key TEXT PRIMARY KEY,
                 supplier TEXT NOT NULL,
                 family TEXT NOT NULL DEFAULT '',
                 type_code TEXT NOT NULL DEFAULT '',
                 image_blob BLOB NOT NULL,
                 image_ext TEXT DEFAULT '',
                 image_hash TEXT DEFAULT '',
                 source_offer_no TEXT DEFAULT '',
                 source_offer_date TEXT DEFAULT '',
                 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        con.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_offer_image_assets_supplier_type
               ON offer_image_assets(supplier,family,type_code)"""
        )
        columns = {
            str(row[1])
            for row in con.execute("PRAGMA table_info(supplier_offer_items)").fetchall()
        }
        if "image_asset_key" not in columns:
            con.execute(
                "ALTER TABLE supplier_offer_items "
                "ADD COLUMN image_asset_key TEXT DEFAULT ''"
            )
        if "plexus_type" not in columns:
            con.execute(
                "ALTER TABLE supplier_offer_items "
                "ADD COLUMN plexus_type TEXT DEFAULT ''"
            )


def _upsert_asset(con, type_code, image_bytes, image_ext="png", offer_no="", offer_date=""):
    code = str(type_code or "").strip().upper()
    key = _asset_key(code)
    if not key:
        return ""
    current = con.execute(
        "SELECT asset_key,image_hash FROM offer_image_assets WHERE asset_key=?",
        (key,),
    ).fetchone()
    if not image_bytes:
        return key if current else ""

    blob = bytes(image_bytes)
    digest = hashlib.sha256(blob).hexdigest()
    if current and str(current["image_hash"] or "") == digest:
        con.execute(
            """UPDATE offer_image_assets
               SET source_offer_no=CASE WHEN trim(?)<>'' THEN ? ELSE source_offer_no END,
                   source_offer_date=CASE WHEN trim(?)<>'' THEN ? ELSE source_offer_date END,
                   updated_at=CURRENT_TIMESTAMP
               WHERE asset_key=?""",
            (offer_no or "", offer_no or "", offer_date or "", offer_date or "", key),
        )
        return key

    con.execute(
        """INSERT INTO offer_image_assets(
               asset_key,supplier,family,type_code,image_blob,image_ext,image_hash,
               source_offer_no,source_offer_date,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(asset_key) DO UPDATE SET
               image_blob=excluded.image_blob,
               image_ext=excluded.image_ext,
               image_hash=excluded.image_hash,
               source_offer_no=excluded.source_offer_no,
               source_offer_date=excluded.source_offer_date,
               updated_at=CURRENT_TIMESTAMP""",
        (
            key,
            "Nevoga",
            "PLEXUS",
            code,
            sqlite3.Binary(blob),
            str(image_ext or "png"),
            digest,
            str(offer_no or ""),
            str(offer_date or ""),
        ),
    )
    return key


def _delete_legacy_canonical(con, item_key):
    if not item_key:
        return
    table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='offer_product_images'"
    ).fetchone()
    if not table:
        return
    rows = con.execute(
        "SELECT supplier,item_key FROM offer_product_images WHERE item_key=?",
        (str(item_key),),
    ).fetchall()
    for row in rows:
        if _is_nevoga_name(row["supplier"]):
            con.execute(
                "DELETE FROM offer_product_images WHERE supplier=? AND item_key=?",
                (row["supplier"], row["item_key"]),
            )


def _migrate_existing_plexus_images(M):
    """Collapse legacy Nevoga item blobs to one asset per PLEXUS type."""
    _ensure_asset_schema(M)
    with M.db() as con:
        rows = con.execute(
            """SELECT i.id,i.item_key,i.original_name,i.image_blob,i.image_ext,
                      o.supplier_name,o.offer_number,o.offer_date
               FROM supplier_offer_items i
               JOIN supplier_offers o ON o.id=i.offer_id
               WHERE i.image_blob IS NOT NULL"""
        ).fetchall()
        migrated = 0
        for row in rows:
            if not _is_nevoga_name(row["supplier_name"]):
                continue
            code = _plexus_type(row["original_name"] or row["item_key"])
            if not code:
                continue
            key = _upsert_asset(
                con,
                code,
                row["image_blob"],
                row["image_ext"] or "png",
                row["offer_number"] or "",
                row["offer_date"] or "",
            )
            if not key:
                continue
            con.execute(
                """UPDATE supplier_offer_items
                   SET image_asset_key=?,plexus_type=?,image_blob=NULL,image_ext=''
                   WHERE id=?""",
                (key, code, int(row["id"])),
            )
            _delete_legacy_canonical(con, row["item_key"])
            migrated += 1
        return migrated


def _centralize_parsed_plexus(M, offer_id, parsed):
    if not _is_nevoga_name((parsed or {}).get("supplier")):
        return 0
    items = list((parsed or {}).get("items") or [])
    if not items:
        return 0
    _ensure_asset_schema(M)
    with M.db() as con:
        offer = con.execute(
            "SELECT offer_number,offer_date FROM supplier_offers WHERE id=?",
            (int(offer_id),),
        ).fetchone()
        offer_no = (offer["offer_number"] if offer else "") or (parsed or {}).get("offer_no") or ""
        offer_date = (offer["offer_date"] if offer else "") or (parsed or {}).get("date") or ""
        stored = con.execute(
            "SELECT id,position,item_key,original_name FROM supplier_offer_items "
            "WHERE offer_id=? ORDER BY position,id",
            (int(offer_id),),
        ).fetchall()
        by_position = {}
        for row in stored:
            by_position.setdefault(int(row["position"] or 0), []).append(row)

        linked = 0
        for parsed_item in items:
            code = str(parsed_item.get("plexus_type") or "").strip().upper()
            if not code:
                code = _plexus_type(parsed_item.get("description") or parsed_item.get("item_key"))
            if not code:
                continue
            key = _upsert_asset(
                con,
                code,
                parsed_item.get("image_bytes"),
                parsed_item.get("image_ext") or "png",
                offer_no,
                offer_date,
            )
            if not key:
                continue
            candidates = by_position.get(int(parsed_item.get("position") or 0)) or []
            if not candidates:
                continue
            row = candidates.pop(0)
            con.execute(
                """UPDATE supplier_offer_items
                   SET image_asset_key=?,plexus_type=?,image_blob=NULL,image_ext=''
                   WHERE id=?""",
                (key, code, int(row["id"])),
            )
            _delete_legacy_canonical(con, row["item_key"])
            linked += 1
        return linked


def _resolve_image(con, item, supplier=""):
    key = str(_row_get(item, "image_asset_key", "") or "").strip()
    code = str(_row_get(item, "plexus_type", "") or "").strip().upper()
    if not code:
        code = _plexus_type(
            _row_get(item, "original_name", "") or _row_get(item, "item_key", "")
        )
    if not key and code and _is_nevoga_name(supplier):
        key = _asset_key(code)

    if key:
        row = con.execute(
            """SELECT image_blob,image_ext,source_offer_no,source_offer_date,
                      asset_key,type_code
               FROM offer_image_assets WHERE asset_key=?""",
            (key,),
        ).fetchone()
        if row and row["image_blob"]:
            return dict(row)

    item_key = str(_row_get(item, "item_key", "") or "")
    if supplier and item_key:
        try:
            row = con.execute(
                """SELECT image_blob,image_ext,source_offer_no,source_offer_date
                   FROM offer_product_images WHERE supplier=? AND item_key=?""",
                (supplier, item_key),
            ).fetchone()
            if row and row["image_blob"]:
                return dict(row)
        except Exception:
            pass

    blob = _row_get(item, "image_blob")
    if blob:
        return {
            "image_blob": blob,
            "image_ext": _row_get(item, "image_ext", "") or "png",
            "source_offer_no": "",
            "source_offer_date": _row_get(item, "image_source_offer_date", "") or "",
            "asset_key": "",
            "type_code": code,
        }
    return None


def _repair_request_table(app):
    tree = getattr(app, "request_tree", None)
    if tree is None:
        return
    for column, width in zip(REQUEST_COLUMNS, REQUEST_WIDTHS):
        try:
            tree.column(column, width=width, anchor="w")
            tree.heading(column, anchor="w")
        except Exception:
            pass

    frame = getattr(tree, "_filter_frame", None)
    if frame is not None:
        for index, width in enumerate(REQUEST_WIDTHS):
            try:
                frame.columnconfigure(index, weight=width)
            except Exception:
                pass
    sync = getattr(tree, "_sync_filter_bar", None)
    if callable(sync):
        try:
            tree.after_idle(sync)
        except Exception:
            pass


def apply(M):
    if getattr(M, "_turto_v7616_requests_plexus_assets", False):
        return
    M._turto_v7616_requests_plexus_assets = True

    previous_ensure_schema = M.ensure_schema

    def ensure_schema():
        result = previous_ensure_schema()
        _ensure_asset_schema(M)
        _migrate_existing_plexus_images(M)
        return result

    M.ensure_schema = ensure_schema
    M.ensure_plexus_image_assets = lambda: _ensure_asset_schema(M)
    M.migrate_plexus_image_assets = lambda: _migrate_existing_plexus_images(M)
    M.resolve_offer_item_image = _resolve_image
    M.plexus_image_asset_key = _asset_key

    try:
        _ensure_asset_schema(M)
        _migrate_existing_plexus_images(M)
    except Exception:
        # Startup must remain usable; no duplicate blob is cleared unless its
        # shared asset insert completed in the same transaction.
        pass

    previous_save = M.save_offer_import

    def save_offer_import(*args, **kwargs):
        result = previous_save(*args, **kwargs)
        try:
            offer_id = int(result[0])
            parsed = result[3] if len(result) > 3 else {}
            if _is_nevoga_name((parsed or {}).get("supplier")):
                _centralize_parsed_plexus(M, offer_id, parsed)
        except Exception:
            # The original item blob stays intact when centralization fails.
            pass
        return result

    M.save_offer_import = save_offer_import

    previous_build_requests = M.App.build_requests

    def build_requests(self, *args, **kwargs):
        result = previous_build_requests(self, *args, **kwargs)
        _repair_request_table(self)
        try:
            self.request_tree.bind(
                "<Configure>",
                lambda _event, current=self: current.after_idle(
                    lambda: _repair_request_table(current)
                ),
                add="+",
            )
        except Exception:
            pass
        return result

    M.App.build_requests = build_requests

    def request_date_highlights(self, tree, rows):
        """Keep Poptáno plain text and restore bold emphasis for long waits."""
        if tree is None:
            return
        try:
            tree.tag_configure(OVERDUE_TAG, font=("Calibri", 10, "bold"))
        except Exception:
            pass
        for item in rows or ():
            iid = item[0] if item else None
            overdue = bool(item[1]) if len(item) > 1 else False
            if not iid:
                continue
            try:
                if not tree.exists(iid):
                    continue
                raw = str(tree.set(iid, "Poptáno") or "")
                clean = _clean_date_text(raw)
                if clean != raw:
                    tree.set(iid, "Poptáno", clean)
                tags = [tag for tag in (tree.item(iid, "tags") or ()) if tag != OVERDUE_TAG]
                if overdue:
                    tags.append(OVERDUE_TAG)
                tree.item(iid, tags=tuple(tags))
            except Exception:
                continue

    M.App._refresh_request_date_highlights = request_date_highlights

    try:
        import crm_features
    except Exception:
        crm_features = None

    detail_classes = []
    for cls in (
        getattr(crm_features, "OfferDetailDialog", None) if crm_features else None,
        getattr(M, "OfferDetailDialog", None),
    ):
        if cls is not None and cls not in detail_classes:
            detail_classes.append(cls)

    for cls in detail_classes:
        if getattr(cls, "_turto_v7616_shared_image", False):
            continue

        def open_image(self):
            item = self._selected_item()
            if not item:
                return M.messagebox.showinfo(
                    "Nabídky", "Vyberte položku nabídky.", parent=self
                )
            supplier = self.offer_row["supplier"] or self.offer_row["supplier_name"] or ""
            with M.db() as con:
                image = _resolve_image(con, item, supplier)
            if not image or not image.get("image_blob"):
                return M.messagebox.showinfo(
                    "Nabídky", "K této položce není uložen obrázek.", parent=self
                )
            try:
                from PIL import Image, ImageTk

                img = Image.open(io.BytesIO(bytes(image["image_blob"])))
                img.thumbnail((900, 620))
                dialog = M.tk.Toplevel(self)
                dialog.title(f"Obrázek – {item.get('original_name') or item.get('item_key') or ''}")
                dialog.transient(self)
                dialog.grab_set()
                photo = ImageTk.PhotoImage(img)
                label = M.ttk.Label(dialog, image=photo)
                label.image = photo
                label.pack(padx=14, pady=14)
                source_no = image.get("source_offer_no") or self.offer_row["offer_number"] or "—"
                source_date = image.get("source_offer_date") or self.offer_row["offer_date"] or ""
                M.ttk.Label(
                    dialog,
                    text=f"Zdroj: nabídka {source_no} z {M.fmt_date(source_date)}",
                    style="PageSubtitle.TLabel",
                ).pack(pady=(0, 8))
                M.ttk.Button(dialog, text="Zavřít", command=dialog.destroy).pack(pady=(0, 14))
            except Exception as exc:
                M.messagebox.showerror(
                    "Nabídky",
                    f"Obrázek se nepodařilo otevřít:\n{exc}",
                    parent=self,
                )

        cls.open_image = open_image
        cls._turto_v7616_shared_image = True

    previous_export = getattr(M, "export_offer_excel", None)
    if callable(previous_export):

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
                return previous_export(app, offer_id, parent=parent)

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
                try:
                    import v769_nevoga_offer as nevoga_layer
                    decode = nevoga_layer._decode_segments
                except Exception:
                    decode = lambda _raw: []

                with M.db() as con:
                    items = con.execute(
                        "SELECT * FROM supplier_offer_items "
                        "WHERE offer_id=? ORDER BY position,id",
                        (int(offer_id),),
                    ).fetchall()
                    parsed_items = []
                    for item in items:
                        image = _resolve_image(con, item, offer["supplier"])
                        parsed_items.append(
                            {
                                "position": item["position"],
                                "product": item["product_code"] or "",
                                "description": item["original_name"] or item["item_key"] or "",
                                "item_key": item["item_key"] or item["original_name"] or "",
                                "details": item["details"] or "",
                                "rich_segments": decode(item["details_rich_json"]),
                                "quantity": item["quantity"] or 0,
                                "unit": item["unit"] or "m",
                                "original_unit_price": item["original_unit_price"] or item["unit_price"] or 0,
                                "discount_pct": item["discount_pct"] or 0,
                                "unit_price": item["unit_price"] or 0,
                                "item_total": item["total_price"] or 0,
                                "plexus_type": item["plexus_type"] or _plexus_type(item["original_name"]),
                                "image_bytes": bytes(image["image_blob"]) if image and image.get("image_blob") else None,
                                "image_ext": image.get("image_ext") if image else "png",
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
                    "Extrakce dat", f"Extrakce vytvořena:\n{path}", parent=parent or app
                )
                return path
            except Exception as exc:
                messagebox.showerror("Extrakce dat", str(exc), parent=parent or app)
                return None

        M.export_offer_excel = export_offer_excel

    M.V7616_REQUESTS_PLEXUS_ASSETS = {
        "request_columns": REQUEST_COLUMNS,
        "overdue_days": 7,
        "overdue_style": "bold",
        "plexus_asset_scope": "one row per Nevoga PLEXUS type",
    }
