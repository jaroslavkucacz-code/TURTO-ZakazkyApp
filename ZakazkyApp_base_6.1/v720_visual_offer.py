"""TURTO CRM 7.2 – exact PDF preview and direct visual editing for issued offers.

The preview deliberately calls the production PDF renderer with an in-memory
document snapshot.  It therefore shows the same pagination, typography, assets,
group headings and totals as the final archived PDF, without creating a
document number, revision or database row.
"""
from __future__ import annotations

import base64
import tempfile
import threading
from typing import Any

_PREVIEW_LOCK = threading.RLock()


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value or 0)
    except Exception:
        return float(default)


def _fmt(value: Any, decimals: int = 2) -> str:
    return f"{_number(value):.{int(decimals)}f}".replace(".", ",")


def apply(M) -> None:
    if getattr(M, "_turto_v720_visual_offer_installed", False):
        return

    # Older post_baseline table fitters inspect this marker before binding.
    # It is set before App() is instantiated, so one persistent-width owner wins.
    M._turto_v720_width_owner = True

    try:
        import fitz
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import pdf_renderer, service
    except Exception:
        M._turto_v720_visual_offer_installed = True
        return

    def walk(widget):
        yield widget
        try:
            for child in widget.winfo_children():
                yield from walk(child)
        except Exception:
            return

    def grouped_rows(items):
        """Return renderer-order rows with their source editor index."""
        grouper = getattr(service, "group_offer_items", None)
        if callable(grouper):
            result = []
            for token in grouper(items):
                if token.get("kind") == "group":
                    result.append(
                        (
                            None,
                            {
                                "row_type": "heading",
                                "name": token.get("label") or "",
                                "_automatic_taxonomy_heading": True,
                            },
                        )
                    )
                else:
                    result.append((int(token.get("index", 0)), dict(token.get("item") or {})))
            return result
        return [(index, dict(item or {})) for index, item in enumerate(items)]

    def row_regions(document, items):
        """Simulate only the production renderer's item rectangles."""
        template = service.load_template(M, document.get("template_id"))
        MM = pdf_renderer.MM
        page_width = pdf_renderer.A4_WIDTH
        page_height = pdf_renderer.A4_HEIGHT
        margin_left = service.number(template.get("margin_left_mm"), 14) * MM
        margin_right = service.number(template.get("margin_right_mm"), 14) * MM
        header_height = service.number(template.get("header_height_mm"), 25) * MM
        footer_height = service.number(template.get("footer_height_mm"), 14) * MM
        body_top_gap = service.number(template.get("body_top_gap_mm"), 5) * MM
        body_bottom_gap = service.number(template.get("body_bottom_gap_mm"), 5) * MM
        body_top = header_height + body_top_gap + 12
        body_bottom = page_height - footer_height - body_bottom_gap - 12

        # Title + number + party cards + five detail rows + table heading.
        y = body_top + 25 + 28 + 83 + 12 + max(46, 13 * 5) + 13 + 20
        page_no = 0
        regions = []

        for source_index, raw in grouped_rows(items):
            item = service.normalize_item(dict(raw or {}))
            row_type = item.get("row_type")
            if row_type == "heading":
                height = 24
            elif row_type == "text":
                value = str(item.get("description") or item.get("name") or "")
                lines = max(1, (len(value) // 105) + 1)
                height = max(24, 12 * lines + 8)
            else:
                description = str(
                    item.get("name")
                    or item.get("internal_name_snapshot")
                    or item.get("description")
                    or ""
                )
                if item.get("description") and item.get("description") != description:
                    description += "\n" + str(item.get("description"))
                if item.get("line_note"):
                    description += "\n" + str(item.get("line_note"))
                lines = max(1, (len(description) // 58) + description.count("\n") + 1)
                height = max(25, 10 * lines + 7)

            if y + height > body_bottom:
                page_no += 1
                y = body_top + 20  # repeated table heading
            if source_index is not None:
                regions.append(
                    {
                        "page": page_no,
                        "index": int(source_index),
                        "x0": margin_left,
                        "y0": y,
                        "x1": page_width - margin_right,
                        "y1": y + height,
                    }
                )
            y += height
        return regions

    def preview_document(instance):
        try:
            document = instance.collect()
        except Exception:
            document = dict(getattr(instance, "document", {}) or {})
        if not _text(document.get("document_number")):
            try:
                document["document_number"] = service.preview_document_number(
                    M, document.get("issue_date")
                )
            except Exception:
                document["document_number"] = "CN00-00000"
        return document

    def render_preview_pdf(instance, target):
        """Render an unsaved snapshot through the real final-PDF function."""
        document = preview_document(instance)
        items = [dict(item or {}) for item in getattr(instance, "items", [])]
        with _PREVIEW_LOCK:
            original_load = service.load_document
            original_next = service.next_revision_no
            original_record = service.record_revision
            service.load_document = (
                lambda _module, _document_id: (
                    dict(document),
                    [dict(item or {}) for item in items],
                )
            )
            service.next_revision_no = lambda *_args, **_kwargs: 0
            service.record_revision = lambda *_args, **_kwargs: None
            try:
                pdf_renderer.render_offer_pdf(
                    M, -720, output_path=target, open_after=False
                )
            finally:
                service.load_document = original_load
                service.next_revision_no = original_next
                service.record_revision = original_record
        return document, items

    class InternalItemPanel:
        """Internal pricing controls; none of these labels are emitted to PDF."""

        def __init__(self, instance, notebook):
            self.instance = instance
            self.index = None
            self.loading = False
            self.page = M.ttk.Frame(notebook, padding=8)
            try:
                notebook.insert(0, self.page, text="Cena položky")
            except Exception:
                notebook.add(self.page, text="Cena položky")
            self.page.columnconfigure(1, weight=1)
            self.title = M.tk.StringVar(value="Vyberte položku v náhledu")
            self.taxonomy = M.tk.StringVar(value="")
            M.ttk.Label(
                self.page, textvariable=self.title, font=("Calibri", 11, "bold"),
                wraplength=300,
            ).grid(row=0, column=0, columnspan=2, sticky="w")
            M.ttk.Label(
                self.page,
                text="Interní cenové údaje – v PDF se nezobrazují.",
                style="PageSubtitle.TLabel",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))

            self.purchase = M.tk.StringVar()
            self.margin = M.tk.StringVar()
            self.recommended = M.tk.StringVar()
            self.discount = M.tk.StringVar()
            self.sale = M.tk.StringVar()
            self.vat = M.tk.StringVar()
            fields = (
                ("Nákupní cena / MJ", self.purchase),
                ("Marže [%]", self.margin),
                ("Doporučená cena / MJ", self.recommended),
                ("Sleva [%]", self.discount),
                ("Prodejní cena / MJ", self.sale),
                ("DPH [%]", self.vat),
            )
            self.entries = []
            row = 2
            for label, variable in fields:
                M.ttk.Label(self.page, text=label).grid(
                    row=row, column=0, sticky="w", padx=(0, 8), pady=3
                )
                entry = M.ttk.Entry(self.page, textvariable=variable)
                entry.grid(row=row, column=1, sticky="ew", pady=3)
                self.entries.append(entry)
                row += 1

            M.ttk.Label(self.page, text="Zařazení").grid(
                row=row, column=0, sticky="nw", padx=(0, 8), pady=(7, 3)
            )
            M.ttk.Label(
                self.page, textvariable=self.taxonomy, wraplength=220,
                style="PageSubtitle.TLabel",
            ).grid(row=row, column=1, sticky="w", pady=(7, 3))
            row += 1

            tools = M.ttk.Frame(self.page)
            tools.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(9, 0))
            self.recalculate_button = M.ttk.Button(
                tools, text="Přepočítat", command=lambda: self.apply(True)
            )
            self.recalculate_button.pack(side="left")
            self.apply_button = M.ttk.Button(
                tools, text="Použít", style="Accent.TButton",
                command=lambda: self.apply(False),
            )
            self.apply_button.pack(side="left", padx=5)
            self.taxonomy_button = M.ttk.Button(
                tools, text="Zařadit…", command=self.assign_taxonomy
            )
            self.taxonomy_button.pack(side="left")
            self.set_enabled(False)

        def set_enabled(self, enabled):
            enabled = bool(enabled and not getattr(self.instance, "locked", False))
            state = "!disabled" if enabled else "disabled"
            for widget in self.entries + [
                self.recalculate_button, self.apply_button, self.taxonomy_button
            ]:
                try:
                    widget.state([state])
                except Exception:
                    try:
                        widget.configure(state="normal" if enabled else "disabled")
                    except Exception:
                        pass

        def load(self, index):
            try:
                index = int(index)
            except Exception:
                index = -1
            if not 0 <= index < len(self.instance.items):
                self.index = None
                self.title.set("Vyberte položku v náhledu")
                self.taxonomy.set("")
                self.set_enabled(False)
                return
            self.index = index
            item = service.normalize_item(self.instance.items[index], index + 1)
            self.loading = True
            try:
                self.title.set(
                    _text(
                        item.get("name")
                        or item.get("internal_name_snapshot")
                        or item.get("description"),
                        "Položka",
                    )
                )
                self.purchase.set(_fmt(item.get("purchase_unit_price")))
                self.margin.set(_fmt(item.get("margin_pct")))
                self.recommended.set(_fmt(item.get("recommended_unit_price")))
                self.discount.set(_fmt(item.get("discount_pct")))
                self.sale.set(_fmt(item.get("unit_price")))
                self.vat.set(_fmt(item.get("vat_rate"), 2))
                category = _text(item.get("category_name_snapshot"), "Nezařazeno")
                subgroup = _text(
                    item.get("subgroup_name_snapshot"), "Bez podskupiny"
                )
                self.taxonomy.set(f"{category} › {subgroup}")
            finally:
                self.loading = False
            priced = item.get("row_type") not in {"heading", "text"}
            self.set_enabled(priced)

        def apply(self, recalculate):
            if self.loading or self.index is None:
                return
            index = self.index
            if not 0 <= index < len(self.instance.items):
                return
            item = dict(self.instance.items[index] or {})
            if item.get("row_type") in {"heading", "text"}:
                return
            purchase = _number(self.purchase.get())
            margin = _number(self.margin.get())
            discount = _number(self.discount.get())
            if recalculate:
                recommended = purchase * (1.0 + margin / 100.0)
                sale = recommended * (1.0 - discount / 100.0)
                self.recommended.set(_fmt(recommended))
                self.sale.set(_fmt(sale))
            else:
                recommended = _number(self.recommended.get())
                sale = _number(self.sale.get())
            item.update(
                purchase_unit_price=purchase,
                margin_pct=margin,
                recommended_unit_price=recommended,
                discount_pct=discount,
                unit_price=sale,
                vat_rate=max(0.0, _number(self.vat.get(), 21)),
                total_price=_number(item.get("quantity"), 1) * sale,
            )
            self.instance.items[index] = service.normalize_item(item, index + 1)
            self.instance.refresh_items()
            try:
                self.instance.tree.selection_set(f"r{index}")
            except Exception:
                pass
            self.load(index)

        def assign_taxonomy(self):
            if self.index is None:
                return
            try:
                self.instance.tree.selection_set(f"r{self.index}")
                self.instance.assign_selected_taxonomy()
                self.load(self.index)
            except Exception:
                pass

    class OfferPreview:
        def __init__(self, instance, parent, data_wrap):
            self.instance = instance
            self.parent = parent
            self.data_wrap = data_wrap
            self.after_id = None
            self.inline_window = None
            self.inline_frame = None
            self.images = []
            self.canvas_regions = []
            self.selected_index = None
            self.zoom = 125
            self.auto_fit = True
            self.visible = True

            self.frame = M.ttk.Frame(parent)
            self.frame.grid(row=1, column=0, sticky="nsew")
            self.frame.columnconfigure(0, weight=1)
            self.frame.rowconfigure(1, weight=1)

            bar = M.ttk.Frame(self.frame, style="Panel.TFrame", padding=(7, 5))
            bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))
            M.ttk.Label(
                bar,
                text="Vizuální náhled PDF",
                font=("Calibri", 11, "bold"),
            ).pack(side="left")
            self.status = M.tk.StringVar(
                value="Dvojklikem upravíte zákaznický řádek přímo v náhledu."
            )
            M.ttk.Label(
                bar, textvariable=self.status, style="PageSubtitle.TLabel"
            ).pack(side="left", padx=(10, 0))
            M.ttk.Button(
                bar, text="Obnovit", takefocus=False, command=self.refresh
            ).pack(side="right")
            M.ttk.Button(
                bar, text="+", width=3, takefocus=False,
                command=lambda: self.change_zoom(10),
            ).pack(side="right", padx=(4, 0))
            self.zoom_label = M.tk.StringVar(value=f"{self.zoom} %")
            M.ttk.Label(bar, textvariable=self.zoom_label, width=8).pack(side="right")
            M.ttk.Button(
                bar, text="−", width=3, takefocus=False,
                command=lambda: self.change_zoom(-10),
            ).pack(side="right")
            M.ttk.Button(
                bar, text="Přizpůsobit", takefocus=False, command=self.fit_width
            ).pack(side="right", padx=(0, 7))

            wrap = M.ttk.Frame(self.frame)
            wrap.grid(row=1, column=0, sticky="nsew")
            wrap.columnconfigure(0, weight=1)
            wrap.rowconfigure(0, weight=1)
            self.canvas = M.tk.Canvas(
                wrap, background="#697078", highlightthickness=0, bd=0
            )
            self.canvas.grid(row=0, column=0, sticky="nsew")
            ys = M.ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
            xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
            ys.grid(row=0, column=1, sticky="ns")
            xs.grid(row=1, column=0, sticky="ew")
            self.canvas.configure(
                yscrollcommand=ys.set, xscrollcommand=xs.set
            )
            self.canvas.bind("<Button-1>", self.on_click)
            self.canvas.bind("<Double-1>", self.on_double_click)
            self.canvas.bind("<Configure>", self.on_configure, add="+")
            self.canvas.bind("<MouseWheel>", self.on_mousewheel, add="+")
            self.canvas.bind("<Button-4>", lambda _event: self.canvas.yview_scroll(-3, "units"))
            self.canvas.bind("<Button-5>", lambda _event: self.canvas.yview_scroll(3, "units"))
            try:
                data_wrap.grid_remove()
            except Exception:
                pass
            self.schedule(120)

        def destroy(self):
            if self.after_id is not None:
                try:
                    self.frame.after_cancel(self.after_id)
                except Exception:
                    pass
                self.after_id = None
            self.close_inline()

        def on_mousewheel(self, event):
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                self.canvas.yview_scroll(-1 if delta > 0 else 1, "units")
                return "break"
            return None

        def on_configure(self, _event):
            if self.auto_fit:
                self.schedule(180)

        def fit_width(self):
            width = max(320, int(self.canvas.winfo_width() or 800) - 54)
            self.zoom = max(
                55, min(185, int(width / float(pdf_renderer.A4_WIDTH) * 100))
            )
            self.auto_fit = True
            self.zoom_label.set(f"{self.zoom} %")
            self.schedule(20)

        def change_zoom(self, delta):
            self.auto_fit = False
            self.zoom = max(45, min(220, int(self.zoom + delta)))
            self.zoom_label.set(f"{self.zoom} %")
            self.schedule(20)

        def toggle_mode(self):
            if self.visible:
                self.frame.grid_remove()
                self.data_wrap.grid()
                self.visible = False
                if getattr(self.instance, "_v720_mode_button", None):
                    self.instance._v720_mode_button.configure(
                        text="Vizuální nabídka"
                    )
            else:
                self.data_wrap.grid_remove()
                self.frame.grid()
                self.visible = True
                if getattr(self.instance, "_v720_mode_button", None):
                    self.instance._v720_mode_button.configure(
                        text="Datová tabulka"
                    )
                self.schedule(20)

        def schedule(self, delay=140):
            if not self.visible:
                return
            try:
                if self.after_id is not None:
                    self.frame.after_cancel(self.after_id)
                self.after_id = self.frame.after(delay, self.refresh)
            except Exception:
                self.after_id = None

        def refresh(self):
            self.after_id = None
            if not self.visible:
                return
            try:
                if not self.instance.win.winfo_exists():
                    return
            except Exception:
                return
            self.close_inline()
            try:
                with tempfile.TemporaryDirectory(prefix="turto_cn_preview_") as temp:
                    target = f"{temp}/preview.pdf"
                    document, items = render_preview_pdf(self.instance, target)
                    pdf = fitz.open(target)
                    scale = self.zoom / 100.0
                    self.canvas.delete("all")
                    self.images = []
                    self.canvas_regions = []
                    page_gap = 18
                    page_x = 22
                    page_offsets = []
                    y = page_gap
                    for page_no, page in enumerate(pdf):
                        pix = page.get_pixmap(
                            matrix=fitz.Matrix(scale, scale), alpha=False
                        )
                        encoded = base64.b64encode(pix.tobytes("png")).decode("ascii")
                        image = M.tk.PhotoImage(data=encoded)
                        self.images.append(image)
                        width = int(image.width())
                        height = int(image.height())
                        self.canvas.create_rectangle(
                            page_x + 5, y + 6, page_x + width + 5, y + height + 6,
                            fill="#4f555b", outline="",
                        )
                        self.canvas.create_image(
                            page_x, y, anchor="nw", image=image
                        )
                        self.canvas.create_rectangle(
                            page_x, y, page_x + width, y + height,
                            outline="#c9cdd1", width=1,
                        )
                        page_offsets.append((page_x, y))
                        y += height + page_gap
                    page_count = int(pdf.page_count)
                    pdf.close()

                    for region in row_regions(document, items):
                        page_no = int(region["page"])
                        if not 0 <= page_no < len(page_offsets):
                            continue
                        offset_x, offset_y = page_offsets[page_no]
                        self.canvas_regions.append(
                            {
                                "index": int(region["index"]),
                                "x0": offset_x + region["x0"] * scale,
                                "y0": offset_y + region["y0"] * scale,
                                "x1": offset_x + region["x1"] * scale,
                                "y1": offset_y + region["y1"] * scale,
                            }
                        )
                    bbox = self.canvas.bbox("all") or (0, 0, 100, 100)
                    self.canvas.configure(
                        scrollregion=(
                            0, 0, max(bbox[2] + 22, self.canvas.winfo_width()),
                            bbox[3] + page_gap,
                        )
                    )
                    self.status.set(
                        f"Náhled používá finální PDF renderer · {page_count} "
                        f"{'strana' if page_count == 1 else 'strany'}"
                    )
                    self.draw_selection()
            except Exception as exc:
                self.canvas.delete("all")
                self.images = []
                self.canvas.create_text(
                    24, 24, anchor="nw", fill="white",
                    font=("Calibri", 12, "bold"),
                    text="Náhled PDF se nepodařilo vytvořit.",
                )
                self.canvas.create_text(
                    24, 54, anchor="nw", fill="white", width=700,
                    font=("Calibri", 10), text=str(exc),
                )
                self.status.set("Náhled není dostupný – data lze dál upravovat v tabulce.")

        def region_at(self, x, y):
            for region in self.canvas_regions:
                if (
                    region["x0"] <= x <= region["x1"]
                    and region["y0"] <= y <= region["y1"]
                ):
                    return region
            return None

        def on_click(self, event):
            region = self.region_at(
                self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            )
            if region is None:
                return
            self.select(region["index"])

        def on_double_click(self, event):
            region = self.region_at(
                self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            )
            if region is None:
                return
            self.select(region["index"])
            self.open_inline(region)

        def select(self, index):
            self.selected_index = int(index)
            try:
                iid = f"r{self.selected_index}"
                if self.instance.tree.exists(iid):
                    self.instance.tree.selection_set(iid)
                    self.instance.tree.focus(iid)
            except Exception:
                pass
            panel = getattr(self.instance, "_v720_internal_panel", None)
            if panel is not None:
                panel.load(self.selected_index)
            self.draw_selection()

        def draw_selection(self):
            self.canvas.delete("v720_selection")
            if self.selected_index is None:
                return
            region = next(
                (
                    item for item in self.canvas_regions
                    if int(item["index"]) == int(self.selected_index)
                ),
                None,
            )
            if region is None:
                return
            self.canvas.create_rectangle(
                region["x0"], region["y0"], region["x1"], region["y1"],
                outline="#d7a51c", width=3, tags=("v720_selection",),
            )
            self.canvas.tag_raise("v720_selection")

        def close_inline(self):
            if self.inline_window is not None:
                try:
                    self.canvas.delete(self.inline_window)
                except Exception:
                    pass
                self.inline_window = None
            if self.inline_frame is not None:
                try:
                    self.inline_frame.destroy()
                except Exception:
                    pass
                self.inline_frame = None

        def open_inline(self, region):
            if getattr(self.instance, "locked", False):
                return
            index = int(region["index"])
            if not 0 <= index < len(self.instance.items):
                return
            self.close_inline()
            item = service.normalize_item(self.instance.items[index], index + 1)
            row_type = item.get("row_type")
            frame = M.ttk.Frame(
                self.canvas, style="Card.TFrame", padding=(7, 5)
            )
            self.inline_frame = frame

            if row_type in {"heading", "text"}:
                variable = M.tk.StringVar(
                    value=_text(
                        item.get("name")
                        if row_type == "heading"
                        else item.get("description")
                    )
                )
                M.ttk.Label(
                    frame,
                    text="Nadpis" if row_type == "heading" else "Text pro zákazníka",
                ).grid(row=0, column=0, sticky="w")
                entry = M.ttk.Entry(frame, textvariable=variable)
                entry.grid(row=1, column=0, sticky="ew", padx=(0, 6))
                frame.columnconfigure(0, weight=1)

                def commit():
                    current = dict(self.instance.items[index] or {})
                    if row_type == "heading":
                        current["name"] = variable.get().strip()
                    else:
                        current["description"] = variable.get().strip()
                    self.instance.items[index] = service.normalize_item(
                        current, index + 1
                    )
                    self.close_inline()
                    self.instance.refresh_items()
                    self.select(index)

            else:
                code = M.tk.StringVar(
                    value=_text(
                        item.get("internal_code_snapshot")
                        or item.get("product_code")
                    )
                )
                name = M.tk.StringVar(
                    value=_text(
                        item.get("name")
                        or item.get("internal_name_snapshot")
                        or item.get("description")
                    )
                )
                quantity = M.tk.StringVar(value=_fmt(item.get("quantity"), 3))
                unit = M.tk.StringVar(value=_text(item.get("unit")))
                sale = M.tk.StringVar(value=_fmt(item.get("unit_price")))
                definitions = (
                    ("Kód", code, 12, 0),
                    ("Označení / popis v nabídce", name, 36, 1),
                    ("Množství", quantity, 10, 0),
                    ("MJ", unit, 7, 0),
                    ("Cena / MJ", sale, 12, 0),
                )
                for column, (label, variable, width, weight) in enumerate(definitions):
                    M.ttk.Label(frame, text=label).grid(
                        row=0, column=column, sticky="w", padx=(0, 5)
                    )
                    M.ttk.Entry(
                        frame, textvariable=variable, width=width
                    ).grid(row=1, column=column, sticky="ew", padx=(0, 5))
                    frame.columnconfigure(column, weight=weight)

                def commit():
                    current = dict(self.instance.items[index] or {})
                    current.update(
                        product_code=code.get().strip(),
                        internal_code_snapshot=code.get().strip(),
                        name=name.get().strip(),
                        internal_name_snapshot=name.get().strip(),
                        quantity=max(0.0, _number(quantity.get(), 1)),
                        unit=unit.get().strip(),
                        unit_price=_number(sale.get()),
                    )
                    current["total_price"] = (
                        current["quantity"] * current["unit_price"]
                    )
                    self.instance.items[index] = service.normalize_item(
                        current, index + 1
                    )
                    self.close_inline()
                    self.instance.refresh_items()
                    self.select(index)

            button_bar = M.ttk.Frame(frame)
            button_bar.grid(
                row=2, column=0, columnspan=5, sticky="ew", pady=(5, 0)
            )
            M.ttk.Button(
                button_bar, text="Zrušit", command=self.close_inline
            ).pack(side="right")
            M.ttk.Button(
                button_bar, text="Použít", style="Accent.TButton", command=commit
            ).pack(side="right", padx=(0, 5))

            width = max(420, int(region["x1"] - region["x0"] - 16))
            self.inline_window = self.canvas.create_window(
                region["x0"] + 8, region["y0"] + 2,
                anchor="nw", window=frame, width=width,
            )
            self.canvas.tag_raise(self.inline_window)

    Editor = issued_editor.IssuedOfferEditor
    if not getattr(Editor, "_turto_v720_visual_editor", False):
        previous_init = Editor.__init__
        previous_refresh_items = Editor.refresh_items
        previous_save = Editor.save

        def refresh_items(self, *args, **kwargs):
            result = previous_refresh_items(self, *args, **kwargs)
            preview = getattr(self, "_v720_preview", None)
            if preview is not None:
                preview.schedule(100)
            panel = getattr(self, "_v720_internal_panel", None)
            if panel is not None:
                indices = self.selected_indices()
                panel.load(indices[0] if len(indices) == 1 else None)
            return result

        def init(self, *args, **kwargs):
            previous_init(self, *args, **kwargs)
            try:
                data_wrap = self.tree.master
                left = data_wrap.master
                preview = OfferPreview(self, left, data_wrap)
                self._v720_preview = preview

                toolbar = None
                for child in left.winfo_children():
                    try:
                        if int(child.grid_info().get("row", -1)) == 0:
                            toolbar = child
                            break
                    except Exception:
                        pass
                if toolbar is not None:
                    button = M.ttk.Button(
                        toolbar, text="Datová tabulka", takefocus=False,
                        command=preview.toggle_mode,
                    )
                    button.pack(side="right", padx=4)
                    self._v720_mode_button = button

                terms_notebook = None
                for widget in walk(self.win):
                    if not isinstance(widget, M.ttk.Notebook):
                        continue
                    try:
                        labels = {
                            _text(widget.tab(tab_id, "text"))
                            for tab_id in widget.tabs()
                        }
                    except Exception:
                        labels = set()
                    if {"Dodání", "Termín", "Pro zákazníka"} <= labels:
                        terms_notebook = widget
                        break
                if terms_notebook is not None:
                    self._v720_internal_panel = InternalItemPanel(
                        self, terms_notebook
                    )

                def tree_selection(_event=None):
                    indices = self.selected_indices()
                    index = indices[0] if len(indices) == 1 else None
                    if index is not None:
                        preview.selected_index = index
                        preview.draw_selection()
                    panel = getattr(self, "_v720_internal_panel", None)
                    if panel is not None:
                        panel.load(index)

                self.tree.bind(
                    "<<TreeviewSelect>>", tree_selection, add="+"
                )

                variables = [
                    getattr(self, name, None)
                    for name in (
                        "issue_date", "valid_to", "status", "currency",
                        "company", "contact", "action", "project", "subject",
                        "reference", "salesperson", "template",
                        "global_discount",
                    )
                ]
                for variable in variables:
                    if variable is not None:
                        try:
                            variable.trace_add(
                                "write",
                                lambda *_args, current=preview: current.schedule(),
                            )
                        except Exception:
                            pass
                for name in (
                    "payment_terms", "delivery_terms", "delivery_time",
                    "customer_note",
                ):
                    widget = getattr(self, name, None)
                    if widget is not None:
                        widget.bind(
                            "<KeyRelease>",
                            lambda _event, current=preview: current.schedule(),
                            add="+",
                        )
                        widget.bind(
                            "<FocusOut>",
                            lambda _event, current=preview: current.schedule(20),
                            add="+",
                        )
                self.win.bind(
                    "<F5>", lambda _event: (preview.refresh(), "break")[1],
                    add="+",
                )

                def destroy_preview(event, current=self, view=preview):
                    if event.widget is current.win:
                        view.destroy()

                self.win.bind("<Destroy>", destroy_preview, add="+")
                preview.fit_width()
            except Exception:
                pass

        def save(self, *args, **kwargs):
            result = previous_save(self, *args, **kwargs)
            if result:
                preview = getattr(self, "_v720_preview", None)
                if preview is not None:
                    preview.schedule(20)
            return result

        Editor.refresh_items = refresh_items
        Editor.__init__ = init
        Editor.save = save
        Editor._turto_v720_visual_editor = True

    M._turto_v720_visual_offer_installed = True


__all__ = ["apply"]
