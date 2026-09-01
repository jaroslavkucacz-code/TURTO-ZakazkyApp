"""TURTO CRM 7.3 – stable PDF preview, received-offer UX and company merge.

The layer is additive and deliberately conservative:
- fonts are registered on the actual PyMuPDF page, never by a reusable object id;
- a failed preview refresh keeps the last valid page image visible;
- received offers expose the common persistent-column manager and a colour legend;
- duplicate companies are merged in one SQLite transaction while historical
  document snapshots and existing PDFs remain immutable.
"""
from __future__ import annotations

import base64
import json
import tempfile
import types
from collections import defaultdict
from datetime import datetime
from typing import Any


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _q(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _widget_exists(widget) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def apply(M) -> None:
    if getattr(M, "_turto_v730_polish_installed", False):
        return

    # ------------------------------------------------------------------
    # PDF font lifetime and visual-preview resilience.
    # ------------------------------------------------------------------
    try:
        import fitz
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import font_support, pdf_renderer
    except Exception:
        fitz = issued_editor = font_support = pdf_renderer = None

    if font_support is not None and not getattr(font_support, "_turto_v730_fonts", False):
        regular_bytes = None
        bold_bytes = None
        try:
            regular_file, bold_file = font_support._font_files()
            if regular_file is not None and regular_file.is_file():
                regular_bytes = regular_file.read_bytes()
            if bold_file is not None and bold_file.is_file():
                bold_bytes = bold_file.read_bytes()
            elif regular_bytes:
                bold_bytes = regular_bytes
        except Exception:
            regular_bytes = bold_bytes = None

        def registered_fonts(page):
            """Register local OS fonts for this exact page/document only.

            PyMuPDF font resources belong to one document. Caching by ``id(doc)``
            is unsafe because Python may reuse that id after a preview document
            is closed. Storing the result on the live Page object avoids that
            lifetime mismatch. If the object rejected attributes, re-registering
            the same font on the page is harmless and still correct.
            """
            cached = getattr(page, "_turto_v730_registered_fonts", None)
            if cached:
                return cached
            regular_name, bold_name = "helv", "hebo"
            if regular_bytes:
                try:
                    regular_name = "TURTORegular"
                    page.insert_font(fontname=regular_name, fontbuffer=regular_bytes)
                except Exception:
                    regular_name = "helv"
            if bold_bytes:
                try:
                    bold_name = "TURTOBold"
                    page.insert_font(fontname=bold_name, fontbuffer=bold_bytes)
                except Exception:
                    bold_name = regular_name if regular_name != "helv" else "hebo"
            elif regular_name != "helv":
                bold_name = regular_name
            result = (regular_name, bold_name)
            try:
                page._turto_v730_registered_fonts = result
            except Exception:
                pass
            return result

        font_support._registered_fonts = registered_fonts
        try:
            font_support._PAGE_FONTS.clear()
        except Exception:
            pass
        font_support._turto_v730_fonts = True

    if issued_editor is not None and fitz is not None and not getattr(
        issued_editor.IssuedOfferEditor, "_turto_v730_preview", False
    ):
        Editor = issued_editor.IssuedOfferEditor
        previous_editor_init = Editor.__init__

        def closure_values(method):
            function = getattr(method, "__func__", method)
            code = getattr(function, "__code__", None)
            cells = getattr(function, "__closure__", None) or ()
            names = code.co_freevars if code is not None else ()
            return {name: cell.cell_contents for name, cell in zip(names, cells)}

        def install_preview(instance):
            preview = getattr(instance, "_v720_preview", None)
            if preview is None or getattr(preview, "_turto_v730_preview", False):
                return
            preview._turto_v730_preview = True
            closures = closure_values(preview.refresh)
            render_snapshot = closures.get("render_preview_pdf")
            region_builder = closures.get("row_regions")
            if not callable(render_snapshot) or not callable(region_builder):
                return

            try:
                if preview.after_id is not None:
                    preview.frame.after_cancel(preview.after_id)
            except Exception:
                pass
            preview.after_id = None
            preview._v730_rendering = False
            preview._v730_refresh_pending = False
            preview._v730_restore_view = None
            preview._v730_last_width = 0
            preview._v730_last_error = ""

            def friendly_error(exc):
                message = _text(exc, "Neznámá chyba náhledu")
                lowered = message.casefold()
                if "need font file or buffer" in lowered or "font" in lowered:
                    return (
                        "Nepodařilo se načíst písmo PDF. Při dalším obnovení se "
                        "použije bezpečné lokální písmo."
                    )
                if "memory" in lowered:
                    return (
                        "Pro vykreslení není dostatek paměti. Snižte přiblížení "
                        "nebo přepněte na datovou tabulku."
                    )
                return "Náhled se nepodařilo aktualizovat. Data nabídky zůstala zachována."

            def safe_refresh(self):
                self.after_id = None
                if not self.visible:
                    return
                try:
                    if not self.instance.win.winfo_exists():
                        return
                except Exception:
                    return
                if self._v730_rendering:
                    self._v730_refresh_pending = True
                    return
                self._v730_rendering = True
                self._v730_refresh_pending = False
                restore = self._v730_restore_view
                self._v730_restore_view = None
                try:
                    current_x = float(self.canvas.xview()[0])
                    current_y = float(self.canvas.yview()[0])
                except Exception:
                    current_x = current_y = 0.0
                if restore is not None:
                    current_x, current_y = restore
                self.close_inline()
                try:
                    self.status.set("Aktualizuji živý náhled PDF…")
                    try:
                        self.frame.update_idletasks()
                    except Exception:
                        pass
                    with tempfile.TemporaryDirectory(prefix="turto_cn_preview_") as temp:
                        target = f"{temp}/preview.pdf"
                        document, items = render_snapshot(self.instance, target)
                        pdf = fitz.open(target)
                        scale = self.zoom / 100.0
                        page_gap = 18
                        page_x = 22
                        y = page_gap
                        new_images = []
                        page_specs = []
                        page_offsets = []
                        try:
                            for page in pdf:
                                pix = page.get_pixmap(
                                    matrix=fitz.Matrix(scale, scale), alpha=False
                                )
                                encoded = base64.b64encode(
                                    pix.tobytes("png")
                                ).decode("ascii")
                                image = M.tk.PhotoImage(data=encoded)
                                width = int(image.width())
                                height = int(image.height())
                                new_images.append(image)
                                page_specs.append((image, page_x, y, width, height))
                                page_offsets.append((page_x, y))
                                y += height + page_gap
                            page_count = int(pdf.page_count)
                        finally:
                            pdf.close()

                        new_regions = []
                        for region in region_builder(document, items):
                            page_no = int(region["page"])
                            if not 0 <= page_no < len(page_offsets):
                                continue
                            offset_x, offset_y = page_offsets[page_no]
                            new_regions.append(
                                {
                                    "index": int(region["index"]),
                                    "x0": offset_x + region["x0"] * scale,
                                    "y0": offset_y + region["y0"] * scale,
                                    "x1": offset_x + region["x1"] * scale,
                                    "y1": offset_y + region["y1"] * scale,
                                }
                            )

                        # Do not remove the last valid preview until the complete
                        # replacement (all pages + hit regions) exists.
                        self.canvas.delete("all")
                        self.images = new_images
                        self.canvas_regions = new_regions
                        for image, x, page_y, width, height in page_specs:
                            self.canvas.create_rectangle(
                                x + 5,
                                page_y + 6,
                                x + width + 5,
                                page_y + height + 6,
                                fill="#4f555b",
                                outline="",
                            )
                            self.canvas.create_image(x, page_y, anchor="nw", image=image)
                            self.canvas.create_rectangle(
                                x,
                                page_y,
                                x + width,
                                page_y + height,
                                outline="#c9cdd1",
                                width=1,
                            )
                        bbox = self.canvas.bbox("all") or (0, 0, 100, 100)
                        self.canvas.configure(
                            scrollregion=(
                                0,
                                0,
                                max(bbox[2] + 22, self.canvas.winfo_width()),
                                bbox[3] + page_gap,
                            )
                        )
                        self.status.set(
                            f"Živý náhled finálního PDF · {page_count} "
                            f"{'strana' if page_count == 1 else 'strany'} · "
                            "dvojklik upraví řádek"
                        )
                        self._v730_last_error = ""
                        self.draw_selection()
                        try:
                            self.canvas.update_idletasks()
                            self.canvas.xview_moveto(
                                0.0 if self.auto_fit else max(0.0, min(1.0, current_x))
                            )
                            self.canvas.yview_moveto(max(0.0, min(1.0, current_y)))
                        except Exception:
                            pass
                except Exception as exc:
                    self._v730_last_error = _text(exc)
                    message = friendly_error(exc)
                    if self.images and self.canvas.find_all():
                        self.status.set("Poslední platný náhled zůstal zobrazen · " + message)
                    else:
                        self.canvas.delete("all")
                        self.canvas.create_text(
                            24,
                            24,
                            anchor="nw",
                            fill="white",
                            font=("Calibri", 12, "bold"),
                            text="Náhled PDF zatím není dostupný.",
                        )
                        self.canvas.create_text(
                            24,
                            54,
                            anchor="nw",
                            fill="white",
                            width=720,
                            font=("Calibri", 10),
                            text=(
                                message
                                + "\n\nNabídku lze bez omezení upravovat po přepnutí "
                                "na Datovou tabulku."
                            ),
                        )
                        self.status.set("Náhled není dostupný – data nabídky jsou v pořádku.")
                finally:
                    self._v730_rendering = False
                    if self._v730_refresh_pending and self.visible:
                        self._v730_refresh_pending = False
                        self.schedule(90)

            def safe_change_zoom(self, delta):
                try:
                    view = (float(self.canvas.xview()[0]), float(self.canvas.yview()[0]))
                except Exception:
                    view = (0.0, 0.0)
                self.auto_fit = False
                self.zoom = max(45, min(220, int(self.zoom + delta)))
                self.zoom_label.set(f"{self.zoom} %")
                self._v730_restore_view = view
                self.schedule(35)

            def set_zoom_100(self):
                try:
                    view = (0.0, float(self.canvas.yview()[0]))
                except Exception:
                    view = (0.0, 0.0)
                self.auto_fit = False
                self.zoom = 100
                self.zoom_label.set("100 %")
                self._v730_restore_view = view
                self.schedule(35)

            def safe_fit_width(self):
                try:
                    current_y = float(self.canvas.yview()[0])
                except Exception:
                    current_y = 0.0
                width = max(320, int(self.canvas.winfo_width() or 800) - 54)
                self.zoom = max(
                    45,
                    min(220, int(width / float(pdf_renderer.A4_WIDTH) * 100)),
                )
                self.auto_fit = True
                self.zoom_label.set(f"{self.zoom} %")
                self._v730_restore_view = (0.0, current_y)
                self.schedule(35)

            def safe_configure(self, event):
                if not self.auto_fit:
                    return
                width = int(getattr(event, "width", 0) or self.canvas.winfo_width() or 0)
                if width <= 0 or abs(width - self._v730_last_width) < 12:
                    return
                self._v730_last_width = width
                try:
                    current_y = float(self.canvas.yview()[0])
                except Exception:
                    current_y = 0.0
                usable = max(320, width - 54)
                self.zoom = max(
                    45,
                    min(220, int(usable / float(pdf_renderer.A4_WIDTH) * 100)),
                )
                self.zoom_label.set(f"{self.zoom} %")
                self._v730_restore_view = (0.0, current_y)
                self.schedule(230)

            def safe_mousewheel(self, event):
                delta = int(getattr(event, "delta", 0) or 0)
                control = bool(int(getattr(event, "state", 0) or 0) & 0x0004)
                if control and delta:
                    self.change_zoom(10 if delta > 0 else -10)
                    return "break"
                if delta:
                    self.canvas.yview_scroll(-3 if delta > 0 else 3, "units")
                    return "break"
                return None

            preview.refresh = types.MethodType(safe_refresh, preview)
            preview.change_zoom = types.MethodType(safe_change_zoom, preview)
            preview.set_zoom_100 = types.MethodType(set_zoom_100, preview)
            preview.fit_width = types.MethodType(safe_fit_width, preview)
            preview.on_configure = types.MethodType(safe_configure, preview)
            preview.on_mousewheel = types.MethodType(safe_mousewheel, preview)
            preview.canvas.bind("<MouseWheel>", preview.on_mousewheel, add=False)
            preview.canvas.bind("<Configure>", preview.on_configure, add=False)
            preview.canvas.bind(
                "<Control-plus>", lambda _event: (preview.change_zoom(10), "break")[1], add="+"
            )
            preview.canvas.bind(
                "<Control-minus>", lambda _event: (preview.change_zoom(-10), "break")[1], add="+"
            )
            preview.canvas.bind(
                "<Control-0>", lambda _event: (preview.set_zoom_100(), "break")[1], add="+"
            )

            try:
                bar = next(
                    child
                    for child in preview.frame.winfo_children()
                    if int(child.grid_info().get("row", -1)) == 0
                )
                for child in bar.winfo_children():
                    try:
                        if _text(child.cget("text")) == "Přizpůsobit":
                            child.configure(text="Na šířku", command=preview.fit_width)
                    except Exception:
                        pass
                if not _widget_exists(getattr(preview, "_v730_zoom_100_button", None)):
                    button = M.ttk.Button(
                        bar,
                        text="100 %",
                        takefocus=False,
                        command=preview.set_zoom_100,
                    )
                    button.pack(side="right", padx=(4, 7))
                    preview._v730_zoom_100_button = button
            except Exception:
                pass
            preview.schedule(20)

        def editor_init(self, *args, **kwargs):
            result = previous_editor_init(self, *args, **kwargs)
            try:
                install_preview(self)
            except Exception:
                pass
            return result

        Editor.__init__ = editor_init
        Editor._turto_v730_preview = True

    # ------------------------------------------------------------------
    # Transactional company merge.
    # ------------------------------------------------------------------
    def table_columns(con, table):
        try:
            return [str(row[1]) for row in con.execute(f"PRAGMA table_info({_q(table)})")]
        except Exception:
            return []

    def table_names(con):
        return [
            str(row[0])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]

    def ensure_company_merge_schema():
        with M.db() as con:
            columns = set(table_columns(con, "companies"))
            for name, declaration in (
                ("merged_into_company_id", "INTEGER"),
                ("merged_at", "TEXT DEFAULT ''"),
                ("merged_by", "TEXT DEFAULT ''"),
            ):
                if name not in columns:
                    con.execute(f"ALTER TABLE companies ADD COLUMN {_q(name)} {declaration}")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS company_merge_history(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_company_id INTEGER NOT NULL,
                  target_company_id INTEGER NOT NULL,
                  merged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  merged_by TEXT DEFAULT '',
                  source_snapshot_json TEXT NOT NULL DEFAULT '{}',
                  target_snapshot_json TEXT NOT NULL DEFAULT '{}',
                  report_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_company_merge_source
                  ON company_merge_history(source_company_id,merged_at DESC);
                CREATE INDEX IF NOT EXISTS idx_company_merge_target
                  ON company_merge_history(target_company_id,merged_at DESC);
                """
            )

    old_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(old_ensure_schema):
        def ensure_schema():
            result = old_ensure_schema()
            ensure_company_merge_schema()
            return result
        M.ensure_schema = ensure_schema

    COMPANY_COLUMN_NAMES = {
        "company_id",
        "requested_for_company_id",
        "supplier_company_id",
        "customer_company_id",
        "related_company_id",
        "issuer_company_id",
        "owner_company_id",
        "recipient_company_id",
        "vendor_company_id",
        "purchaser_company_id",
        "invoice_company_id",
        "contractor_company_id",
        "general_contractor_company_id",
        "investor_company_id",
    }
    PERSON_COLUMN_NAMES = {
        "person_id",
        "contact_id",
        "customer_contact_id",
        "supplier_contact_id",
        "recipient_person_id",
        "owner_person_id",
        "responsible_person_id",
    }

    def foreign_reference_columns(con, table, referenced_table, candidates):
        columns = set(table_columns(con, table))
        result = {column for column in candidates if column in columns}
        try:
            for row in con.execute(f"PRAGMA foreign_key_list({_q(table)})"):
                if _text(row[2]).casefold() == referenced_table.casefold():
                    result.add(str(row[3]))
        except Exception:
            pass
        return sorted(result)

    def unique_indexes(con, table):
        indexes = []
        try:
            for row in con.execute(f"PRAGMA index_list({_q(table)})"):
                if not int(row[2] or 0):
                    continue
                name = str(row[1])
                columns = [
                    str(info[2])
                    for info in con.execute(f"PRAGMA index_info({_q(name)})")
                    if info[2] is not None
                ]
                if columns:
                    indexes.append(columns)
        except Exception:
            pass
        return indexes

    def find_collision(con, table, row, changed_column, target_id):
        rowid = row["__rowid__"]
        for columns in unique_indexes(con, table):
            if changed_column not in columns:
                continue
            clauses = []
            params = []
            for column in columns:
                clauses.append(f"{_q(column)} IS ?")
                params.append(target_id if column == changed_column else row[column])
            try:
                hit = con.execute(
                    f"SELECT rowid AS __rowid__,* FROM {_q(table)} "
                    f"WHERE {' AND '.join(clauses)} AND rowid<>? LIMIT 1",
                    params + [rowid],
                ).fetchone()
            except Exception:
                hit = None
            if hit:
                return hit
        return None

    def merge_duplicate_row(con, table, source_row, target_row, protected=()):
        columns = table_columns(con, table)
        assignments = []
        params = []
        protected = set(protected) | {"id"}
        for column in columns:
            if column in protected:
                continue
            source_value = source_row[column]
            target_value = target_row[column]
            value = None
            if column == "active":
                value = max(int(source_value or 0), int(target_value or 0))
            elif column in {"updated_at", "modified_at"}:
                value = datetime.now().isoformat(timespec="seconds")
            elif target_value in (None, "") and source_value not in (None, ""):
                value = source_value
            if value is not None and value != target_value:
                assignments.append(f"{_q(column)}=?")
                params.append(value)
        if assignments:
            con.execute(
                f"UPDATE {_q(table)} SET {','.join(assignments)} WHERE rowid=?",
                params + [target_row["__rowid__"]],
            )
        con.execute(f"DELETE FROM {_q(table)} WHERE rowid=?", (source_row["__rowid__"],))

    def repoint_column(con, table, column, source_id, target_id):
        try:
            count = int(
                con.execute(
                    f"SELECT COUNT(*) FROM {_q(table)} WHERE {_q(column)}=?",
                    (source_id,),
                ).fetchone()[0]
                or 0
            )
        except Exception:
            return 0
        if not count:
            return 0
        try:
            con.execute(
                f"UPDATE {_q(table)} SET {_q(column)}=? WHERE {_q(column)}=?",
                (target_id, source_id),
            )
            return count
        except Exception:
            rows = con.execute(
                f"SELECT rowid AS __rowid__,* FROM {_q(table)} WHERE {_q(column)}=?",
                (source_id,),
            ).fetchall()
            moved = 0
            for row in rows:
                try:
                    con.execute(
                        f"UPDATE {_q(table)} SET {_q(column)}=? WHERE rowid=?",
                        (target_id, row["__rowid__"]),
                    )
                except Exception:
                    collision = find_collision(con, table, row, column, target_id)
                    if collision is None:
                        raise
                    merge_duplicate_row(
                        con, table, row, collision, protected={column}
                    )
                moved += 1
            return moved

    def repoint_entity(con, referenced_table, source_id, target_id, candidates, excludes=()):
        report = {}
        excluded = set(excludes) | {referenced_table}
        for table in table_names(con):
            if table in excluded:
                continue
            for column in foreign_reference_columns(
                con, table, referenced_table, candidates
            ):
                moved = repoint_column(con, table, column, source_id, target_id)
                if moved:
                    report[f"{table}.{column}"] = moved
        return report

    def merge_customer_discounts(con, source_id, target_id):
        if "customer_product_discounts" not in set(table_names(con)):
            return {"moved": 0, "combined": 0}
        moved = combined = 0
        rows = con.execute(
            "SELECT * FROM customer_product_discounts WHERE company_id=? ORDER BY id",
            (source_id,),
        ).fetchall()
        for row in rows:
            if row["action_id"] is None:
                target = con.execute(
                    """SELECT * FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id IS NULL
                       ORDER BY id LIMIT 1""",
                    (row["product_id"], target_id),
                ).fetchone()
            else:
                target = con.execute(
                    """SELECT * FROM customer_product_discounts
                       WHERE product_id=? AND company_id=? AND action_id=?
                       ORDER BY id LIMIT 1""",
                    (row["product_id"], target_id, row["action_id"]),
                ).fetchone()
            if target:
                # The retained company's commercial rule remains authoritative.
                # Only missing note/active metadata may be completed.
                note = _text(target["note"]) or _text(row["note"])
                active = max(int(target["active"] or 0), int(row["active"] or 0))
                con.execute(
                    """UPDATE customer_product_discounts
                       SET note=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (note, active, target["id"]),
                )
                con.execute(
                    "DELETE FROM customer_product_discounts WHERE id=?",
                    (row["id"],),
                )
                combined += 1
            else:
                con.execute(
                    """UPDATE customer_product_discounts
                       SET company_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (target_id, row["id"]),
                )
                moved += 1
        return {"moved": moved, "combined": combined}

    def merge_notes(target_note, source_note, source_name):
        target_note = _text(target_note)
        source_note = _text(source_note)
        if not source_note or source_note in target_note:
            return target_note
        prefix = f"Poznámka ze sloučené společnosti {source_name}:"
        return (target_note + "\n\n" if target_note else "") + prefix + "\n" + source_note

    def merge_company_fields(con, source, target):
        columns = set(table_columns(con, "companies"))
        protected = {
            "id", "active", "merged_into_company_id", "merged_at", "merged_by"
        }
        updates = {}
        source_name = _text(
            source["official_name"] or source["short_name"], f"ID {source['id']}"
        )
        for column in columns - protected:
            source_value = source[column]
            target_value = target[column]
            if column == "note":
                value = merge_notes(target_value, source_value, source_name)
            elif column == "ares_checked":
                value = max(_text(target_value), _text(source_value))
            elif target_value in (None, "") and source_value not in (None, ""):
                value = source_value
            else:
                value = target_value
            if value != target_value:
                updates[column] = value
        updates["active"] = 1
        if updates:
            con.execute(
                f"UPDATE companies SET {','.join(f'{_q(k)}=?' for k in updates)} WHERE id=?",
                list(updates.values()) + [target["id"]],
            )

    def deduplicate_people(con, target_company_id, target_original_people):
        if "people" not in set(table_names(con)):
            return 0, {}
        rows = con.execute(
            "SELECT rowid AS __rowid__,* FROM people WHERE company_id=? ORDER BY active DESC,id",
            (target_company_id,),
        ).fetchall()
        groups = defaultdict(list)
        for row in rows:
            email = _text(row["email"]).casefold()
            if email:
                groups[email].append(row)
        combined = 0
        references = {}
        for members in groups.values():
            if len(members) < 2:
                continue
            keeper = next(
                (row for row in members if int(row["id"]) in target_original_people),
                members[0],
            )
            keeper_id = int(keeper["id"])
            for duplicate in members:
                duplicate_id = int(duplicate["id"])
                if duplicate_id == keeper_id:
                    continue
                current = con.execute(
                    "SELECT rowid AS __rowid__,* FROM people WHERE id=?",
                    (keeper_id,),
                ).fetchone()
                updates = {}
                for field in ("name", "email", "phone", "role", "note"):
                    if current[field] in (None, "") and duplicate[field] not in (None, ""):
                        updates[field] = duplicate[field]
                updates["active"] = max(
                    int(current["active"] or 0), int(duplicate["active"] or 0)
                )
                if updates:
                    con.execute(
                        f"UPDATE people SET {','.join(f'{_q(k)}=?' for k in updates)} WHERE id=?",
                        list(updates.values()) + [keeper_id],
                    )
                for key, value in repoint_entity(
                    con,
                    "people",
                    duplicate_id,
                    keeper_id,
                    PERSON_COLUMN_NAMES,
                    excludes={"company_merge_history"},
                ).items():
                    references[key] = references.get(key, 0) + value
                try:
                    con.execute("DELETE FROM people WHERE id=?", (duplicate_id,))
                except Exception:
                    note = _text(duplicate["note"])
                    marker = f"Sloučeno do kontaktu ID {keeper_id}."
                    con.execute(
                        "UPDATE people SET active=0,email='',note=? WHERE id=?",
                        ((note + "\n" if note else "") + marker, duplicate_id),
                    )
                combined += 1
        return combined, references

    def company_merge_stats(company_id):
        ensure_company_merge_schema()
        result = {
            "contacts": 0,
            "opportunities": 0,
            "requests": 0,
            "received_offers": 0,
            "issued_offers": 0,
            "price_lists": 0,
            "discounts": 0,
        }
        statements = {
            "contacts": ("people", ("company_id",)),
            "opportunities": ("actions", ("company_id",)),
            "requests": ("requests", ("company_id", "requested_for_company_id")),
            "received_offers": (
                "supplier_offers", ("supplier_company_id", "customer_company_id")
            ),
            "issued_offers": ("business_documents", ("company_id",)),
            "price_lists": ("price_lists", ("supplier_company_id",)),
            "discounts": ("customer_product_discounts", ("company_id",)),
        }
        with M.db() as con:
            tables = set(table_names(con))
            for key, (table, requested_columns) in statements.items():
                if table not in tables:
                    continue
                available = set(table_columns(con, table))
                columns = [column for column in requested_columns if column in available]
                if not columns:
                    continue
                where = " OR ".join(f"{_q(column)}=?" for column in columns)
                result[key] = int(
                    con.execute(
                        f"SELECT COUNT(*) FROM {_q(table)} WHERE {where}",
                        tuple(company_id for _column in columns),
                    ).fetchone()[0]
                    or 0
                )
        return result

    def merge_company_records(source_id, target_id, user_name=""):
        ensure_company_merge_schema()
        source_id = int(source_id)
        target_id = int(target_id)
        if source_id == target_id:
            raise ValueError("Zdrojová a cílová společnost musí být rozdílné.")
        with M.db() as con:
            source = con.execute(
                "SELECT * FROM companies WHERE id=?", (source_id,)
            ).fetchone()
            target = con.execute(
                "SELECT * FROM companies WHERE id=?", (target_id,)
            ).fetchone()
            if not source or not target:
                raise ValueError("Jedna z vybraných společností už neexistuje.")
            if source["merged_into_company_id"]:
                raise ValueError("Zdrojová společnost už byla dříve sloučena.")
            if target["merged_into_company_id"]:
                raise ValueError("Cílová společnost už byla sloučena do jiného záznamu.")

            tables = set(table_names(con))
            target_original_people = set()
            if "people" in tables:
                target_original_people = {
                    int(row[0])
                    for row in con.execute(
                        "SELECT id FROM people WHERE company_id=?", (target_id,)
                    ).fetchall()
                }
            report = {
                "source_id": source_id,
                "target_id": target_id,
                "references": {},
                "contacts_moved": 0,
                "contacts_combined": 0,
                "discounts": {},
            }

            merge_company_fields(con, source, target)
            report["discounts"] = merge_customer_discounts(con, source_id, target_id)
            if "people" in tables:
                report["contacts_moved"] = int(
                    con.execute(
                        "SELECT COUNT(*) FROM people WHERE company_id=?", (source_id,)
                    ).fetchone()[0]
                    or 0
                )
                con.execute(
                    "UPDATE people SET company_id=? WHERE company_id=?",
                    (target_id, source_id),
                )

            report["references"] = repoint_entity(
                con,
                "companies",
                source_id,
                target_id,
                COMPANY_COLUMN_NAMES,
                excludes={
                    "people",
                    "companies",
                    "customer_product_discounts",
                    "company_merge_history",
                },
            )
            combined, person_refs = deduplicate_people(
                con, target_id, target_original_people
            )
            report["contacts_combined"] = combined
            if person_refs:
                report["person_references"] = person_refs

            now = datetime.now().isoformat(timespec="seconds")
            source_name = _text(
                source["official_name"] or source["short_name"], f"ID {source_id}"
            )
            target_after = con.execute(
                "SELECT * FROM companies WHERE id=?", (target_id,)
            ).fetchone()
            target_name = _text(
                target_after["official_name"] or target_after["short_name"],
                f"ID {target_id}",
            )
            source_note = _text(source["note"])
            marker = f"Sloučeno do společnosti {target_name} (ID {target_id}) dne {now}."
            con.execute(
                """UPDATE companies
                   SET active=0,merged_into_company_id=?,merged_at=?,merged_by=?,note=?
                   WHERE id=?""",
                (
                    target_id,
                    now,
                    _text(user_name),
                    (source_note + "\n\n" if source_note else "") + marker,
                    source_id,
                ),
            )
            report["source_name"] = source_name
            report["target_name"] = target_name
            con.execute(
                """INSERT INTO company_merge_history(
                     source_company_id,target_company_id,merged_at,merged_by,
                     source_snapshot_json,target_snapshot_json,report_json
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    source_id,
                    target_id,
                    now,
                    _text(user_name),
                    json.dumps(dict(source), ensure_ascii=False, default=str),
                    json.dumps(dict(target), ensure_ascii=False, default=str),
                    json.dumps(report, ensure_ascii=False, default=str),
                ),
            )
            return report

    M.ensure_company_merge_schema = ensure_company_merge_schema
    M.merge_company_records = merge_company_records
    M.company_merge_stats = company_merge_stats

    # ------------------------------------------------------------------
    # Company merge UI.
    # ------------------------------------------------------------------
    def selected_company_ids(app):
        tree = getattr(app, "company_tree", None)
        result = []
        for iid in tree.selection() if tree is not None else ():
            value = str(iid)
            if value.startswith("c") and value[1:].isdigit():
                result.append(int(value[1:]))
        return list(dict.fromkeys(result))

    def company_score(row, stats):
        important = (
            "ico", "dic", "address", "legal_form", "date_created",
            "cz_nace", "ares_checked", "ares_raw_json",
        )
        return sum(3 for field in important if _text(row.get(field))) + int(
            stats.get("contacts", 0)
        )

    def merge_companies_dialog(app):
        ids = selected_company_ids(app)
        if len(ids) != 2:
            return M.messagebox.showinfo(
                "Sloučit společnosti",
                "Označte právě dvě společnosti pomocí Ctrl + kliknutí a spusťte sloučení znovu.",
                parent=app,
            )
        ensure_company_merge_schema()
        with M.db() as con:
            rows = [
                con.execute(
                    "SELECT * FROM companies WHERE id=?", (company_id,)
                ).fetchone()
                for company_id in ids
            ]
        if any(row is None for row in rows):
            return M.messagebox.showerror(
                "Sloučit společnosti",
                "Jedna z vybraných společností už v databázi neexistuje.",
                parent=app,
            )
        rows = [dict(row) for row in rows]
        if any(row.get("merged_into_company_id") for row in rows):
            return M.messagebox.showwarning(
                "Sloučit společnosti",
                "Jedna z vybraných společností už byla sloučena. Vyberte dva samostatné záznamy.",
                parent=app,
            )
        stats = {row["id"]: company_merge_stats(row["id"]) for row in rows}
        default_target = max(
            rows, key=lambda row: company_score(row, stats[row["id"]])
        )["id"]

        win = M.tk.Toplevel(app)
        win.title("Sloučit duplicitní společnosti")
        win.transient(app)
        win.grab_set()
        M.enable_dialog_maximize(win, 1180, 720)
        outer = M.scrollable_dialog_frame(win, 16)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        M.ttk.Label(
            outer,
            text="Vyberte společnost, která zůstane",
            font=("Calibri", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        M.ttk.Label(
            outer,
            text=(
                "Vyplněné údaje ponechané společnosti mají přednost. Prázdná pole se doplní "
                "z druhého záznamu, kontakty a živé vazby se přesunou. Historické textové "
                "snímky a existující PDF se nemění."
            ),
            style="PageSubtitle.TLabel",
            wraplength=1080,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))
        target_var = M.tk.IntVar(value=int(default_target))

        field_labels = (
            ("official_name", "Oficiální název"),
            ("short_name", "Krátký název"),
            ("ico", "IČO"),
            ("dic", "DIČ"),
            ("address", "Sídlo"),
            ("legal_form", "Právní forma"),
            ("cz_nace", "CZ-NACE"),
            ("ares_checked", "Kontrola ARES"),
            ("web", "Web"),
        )

        for column, row in enumerate(rows):
            card = M.ttk.Frame(outer, style="Card.TFrame", padding=12)
            card.grid(
                row=2,
                column=column,
                sticky="nsew",
                padx=(0, 6) if column == 0 else (6, 0),
            )
            card.columnconfigure(1, weight=1)
            M.ttk.Radiobutton(
                card,
                text="Ponechat tuto společnost",
                variable=target_var,
                value=int(row["id"]),
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            M.ttk.Label(
                card,
                text=_text(
                    row.get("official_name") or row.get("short_name"),
                    f"ID {row['id']}",
                ),
                font=("Calibri", 14, "bold"),
                wraplength=470,
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 9))
            line = 2
            for field, label in field_labels:
                M.ttk.Label(card, text=label, style="PageSubtitle.TLabel").grid(
                    row=line, column=0, sticky="nw", padx=(0, 9), pady=2
                )
                M.ttk.Label(
                    card,
                    text=_text(row.get(field), "—"),
                    wraplength=350,
                    justify="left",
                ).grid(row=line, column=1, sticky="w", pady=2)
                line += 1
            summary = stats[row["id"]]
            M.ttk.Separator(card).grid(
                row=line, column=0, columnspan=2, sticky="ew", pady=(8, 6)
            )
            line += 1
            summary_text = (
                f"Kontakty: {summary['contacts']} · Příležitosti: {summary['opportunities']} · "
                f"Poptávky: {summary['requests']}\n"
                f"Přijaté nabídky: {summary['received_offers']} · "
                f"Vydané nabídky: {summary['issued_offers']} · "
                f"Ceníky: {summary['price_lists']} · Slevy: {summary['discounts']}"
            )
            M.ttk.Label(
                card,
                text=summary_text,
                style="PageSubtitle.TLabel",
                wraplength=450,
                justify="left",
            ).grid(row=line, column=0, columnspan=2, sticky="w")

        buttons = M.ttk.Frame(outer)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        M.ttk.Button(buttons, text="Zrušit", command=win.destroy).pack(side="right")

        def perform_merge():
            target_id = int(target_var.get())
            source_id = next(company_id for company_id in ids if company_id != target_id)
            source = next(row for row in rows if row["id"] == source_id)
            target = next(row for row in rows if row["id"] == target_id)
            source_name = _text(
                source.get("official_name") or source.get("short_name"), str(source_id)
            )
            target_name = _text(
                target.get("official_name") or target.get("short_name"), str(target_id)
            )
            if not M.messagebox.askyesno(
                "Potvrdit sloučení",
                f"Sloučit „{source_name}“ do „{target_name}“?\n\n"
                "Zdrojová společnost bude označena jako neaktivní. Operace proběhne v jedné "
                "databázové transakci a při chybě se celá vrátí zpět.",
                parent=win,
            ):
                return
            try:
                backup = getattr(M, "backup_now", None)
                if callable(backup):
                    backup("before_company_merge")
            except Exception:
                pass
            try:
                try:
                    user = _text(app.active_user.get())
                except Exception:
                    user = _text(M.get_setting("active_user", ""))
                report = merge_company_records(source_id, target_id, user)
            except Exception as exc:
                return M.messagebox.showerror(
                    "Sloučení společností",
                    "Sloučení nebylo provedeno. Databáze zůstala beze změny.\n\n"
                    + str(exc),
                    parent=win,
                )
            win.destroy()
            try:
                app.refresh_all()
            except Exception:
                app.refresh_companies()
            iid = f"c{target_id}"
            try:
                if app.company_tree.exists(iid):
                    app.company_tree.selection_set(iid)
                    app.company_tree.see(iid)
            except Exception:
                pass
            reference_count = sum(report.get("references", {}).values())
            M.messagebox.showinfo(
                "Sloučení dokončeno",
                f"Ponecháno: {report['target_name']}\n"
                f"Sloučeno: {report['source_name']}\n\n"
                f"Přesunuté kontakty: {report['contacts_moved']}\n"
                f"Sloučené duplicitní kontakty: {report['contacts_combined']}\n"
                f"Aktualizované živé vazby: {reference_count}\n"
                f"Sloučené konfliktní slevy: "
                f"{report['discounts'].get('combined', 0)}",
                parent=app,
            )

        M.ttk.Button(
            buttons,
            text="Sloučit společnosti",
            style="Accent.TButton",
            command=perform_merge,
        ).pack(side="right", padx=(0, 6))
        try:
            M.center_dialog(win, app)
        except Exception:
            pass

    M.App.merge_companies = merge_companies_dialog

    old_build_companies = getattr(M.App, "build_companies", None)
    if callable(old_build_companies):
        def build_companies(self, *args, **kwargs):
            result = old_build_companies(self, *args, **kwargs)
            tree = getattr(self, "company_tree", None)
            if tree is not None:
                try:
                    tree.configure(selectmode="extended")
                    tree._turto_configurable_columns = True
                    installer = getattr(M, "install_persistent_tree_layout", None)
                    if callable(installer):
                        installer(tree, force=True)
                except Exception:
                    pass
            page = getattr(self, "tabs", {}).get("companies")
            if page is not None and not _widget_exists(
                getattr(self, "_v730_company_merge_button", None)
            ):
                toolbar = None
                for child in page.winfo_children():
                    try:
                        labels = [
                            _text(widget.cget("text"))
                            for widget in child.winfo_children()
                            if widget.winfo_class().endswith("Button")
                        ]
                    except Exception:
                        labels = []
                    if any("Aktualizovat všechny z ARES" in label for label in labels):
                        toolbar = child
                        break
                if toolbar is not None:
                    button = M.ttk.Button(
                        toolbar,
                        text="⇄ Sloučit společnosti…",
                        command=lambda: self.merge_companies(),
                    )
                    button.pack(side="right", padx=5)
                    self._v730_company_merge_button = button
                    M.ttk.Label(
                        toolbar,
                        text="Pro sloučení označte 2 řádky pomocí Ctrl.",
                        style="PageSubtitle.TLabel",
                    ).pack(side="left", padx=(10, 0))
            return result
        M.App.build_companies = build_companies

    old_refresh_companies = getattr(M.App, "refresh_companies", None)
    if callable(old_refresh_companies):
        def refresh_companies(self, *args, **kwargs):
            result = old_refresh_companies(self, *args, **kwargs)
            tree = getattr(self, "company_tree", None)
            if tree is None:
                return result
            try:
                with M.db() as con:
                    rows = con.execute(
                        """SELECT c.id,t.official_name target_name,t.short_name target_short
                           FROM companies c LEFT JOIN companies t
                             ON t.id=c.merged_into_company_id
                           WHERE c.merged_into_company_id IS NOT NULL"""
                    ).fetchall()
                for row in rows:
                    iid = f"c{row['id']}"
                    if not tree.exists(iid):
                        continue
                    current = _text(tree.set(iid, "Oficiální název"))
                    target = _text(
                        row["target_name"] or row["target_short"], f"ID {row['id']}"
                    )
                    if "→ sloučeno do" not in current:
                        tree.set(
                            iid,
                            "Oficiální název",
                            f"{current}  → sloučeno do {target}",
                        )
            except Exception:
                pass
            return result
        M.App.refresh_companies = refresh_companies

    # ------------------------------------------------------------------
    # Received offers: explicit column manager and visible colour legend.
    # ------------------------------------------------------------------
    old_build_offers = getattr(M.App, "build_offers", None)
    if callable(old_build_offers):
        def build_offers(self, *args, **kwargs):
            result = old_build_offers(self, *args, **kwargs)
            tree = getattr(self, "offer_tree", None)
            page = getattr(self, "tabs", {}).get("offers")
            if tree is None or page is None:
                return result
            try:
                tree.configure(selectmode="extended")
                tree._turto_configurable_columns = True
                installer = getattr(M, "install_persistent_tree_layout", None)
                if callable(installer):
                    installer(tree, force=True)
            except Exception:
                pass
            if not _widget_exists(getattr(self, "_v730_offer_table_tools", None)):
                body = tree.master
                while body is not None:
                    try:
                        if "Panedwindow" in body.winfo_class():
                            break
                    except Exception:
                        pass
                    body = getattr(body, "master", None)
                tools = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 6))
                if body is not None:
                    tools.pack(fill="x", pady=(0, 6), before=body)
                else:
                    tools.pack(fill="x", pady=(0, 6))
                M.ttk.Label(
                    tools,
                    text="Barvy jsou upozornění:",
                    style="PageSubtitle.TLabel",
                ).pack(side="left", padx=(0, 6))
                badges = (
                    (" bez vazby ", "#f7e7b2", "#5b4308"),
                    (" nezařazené položky ", "#f4d8b8", "#65350a"),
                    (" také Ceník ", "#dce9f4", "#203d55"),
                    (" archiv ", "#dfe3e6", "#515960"),
                )
                for label, background, foreground in badges:
                    M.tk.Label(
                        tools,
                        text=label,
                        background=background,
                        foreground=foreground,
                        font=("Calibri", 9),
                        padx=4,
                        pady=2,
                    ).pack(side="left", padx=(0, 5))
                M.ttk.Button(
                    tools,
                    text="Sloupce…",
                    takefocus=False,
                    command=lambda: getattr(
                        M, "open_tree_columns_dialog", lambda _tree: None
                    )(tree),
                ).pack(side="right")
                self._v730_offer_table_tools = tools
                for widget in page.winfo_children():
                    try:
                        for child in widget.winfo_children():
                            if _text(child.cget("text")) == "Sloupce:":
                                child.configure(text="Předvolba:")
                    except Exception:
                        pass
            return result
        M.App.build_offers = build_offers

    # ------------------------------------------------------------------
    # Help additions.
    # ------------------------------------------------------------------
    old_show_help = getattr(M.App, "show_help_topic", None)
    if callable(old_show_help):
        def show_help_topic(self, key):
            result = old_show_help(self, key)
            additions = {
                "help_directory": (
                    "\n\nSloučení duplicitních společností\n"
                    "Ve Společnostech označte dva řádky pomocí Ctrl a zvolte "
                    "„Sloučit společnosti“. Vyberete záznam, který zůstane; "
                    "kontakty a živé vazby se přesunou a prázdné firemní údaje "
                    "se doplní. Historické PDF a textové snímky se nemění."
                ),
                "help_colors": (
                    "\n\nPřijaté nabídky\n"
                    "Žlutá upozorňuje na chybějící vazbu, oranžová na nezařazené "
                    "položky, modrá označuje nabídku evidovanou také jako Ceník "
                    "a šedá archiv. Barva není obchodní výsledek nabídky."
                ),
            }
            extra = additions.get(key)
            text = getattr(self, "help_text", None)
            if extra and text is not None:
                try:
                    text.configure(state="normal")
                    text.insert("end", extra)
                    text.configure(state="disabled")
                except Exception:
                    pass
            return result
        M.App.show_help_topic = show_help_topic

    M._turto_v730_polish_installed = True


__all__ = ["apply"]
