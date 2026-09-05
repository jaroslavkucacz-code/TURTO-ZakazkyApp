"""TURTO CRM 7.5 – synchronized filters, row menus and supplier offer labels.

The layer is deliberately additive.  It keeps the existing commercial data model
and PDF renderer while making five UI contracts explicit:

* filter cells follow the visible Treeview column order and disappear together
  with hidden columns;
* opportunity, request and MIVO row actions live in a right-click row menu while
  double-click remains the primary edit gesture;
* archive controls occupy the same toolbar positions in all three workspaces;
* rows copied from a received offer retain the supplier's designation, carry no
  customer-facing code and may append a short designation note;
* issued offers visibly state their fixed A4 output format.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "ne", "no", "off"}
    return bool(value)


def _widget_exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _all_columns(tree: Any) -> list[str]:
    try:
        raw = tree.cget("columns")
        if isinstance(raw, str):
            raw = tree.tk.splitlist(raw)
        return [str(column) for column in raw]
    except Exception:
        return []


def displayed_columns(tree: Any) -> list[str]:
    """Return canonical column names in the exact current display order."""
    all_columns = _all_columns(tree)
    if not all_columns:
        return []
    try:
        raw = tree.cget("displaycolumns")
        if isinstance(raw, str):
            raw = tree.tk.splitlist(raw)
        values = [str(value) for value in raw]
    except Exception:
        values = ["#all"]
    if not values or values == ["#all"]:
        return all_columns
    result: list[str] = []
    for value in values:
        if value == "#all":
            return all_columns
        if value in all_columns:
            column = value
        elif value.lstrip("-").isdigit():
            index = int(value)
            if not 0 <= index < len(all_columns):
                continue
            column = all_columns[index]
        else:
            continue
        if column not in result:
            result.append(column)
    return result


def _table_columns(con: Any, table: str) -> set[str]:
    try:
        return {
            str(row[1])
            for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
    except Exception:
        return set()


def _table_exists(con: Any, table: str) -> bool:
    try:
        return bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
        )
    except Exception:
        return False


def _selected_ids(tree: Any, prefix: str) -> list[int]:
    result: list[int] = []
    for iid in tree.selection() if _widget_exists(tree) else ():
        value = str(iid)
        if not value.startswith(prefix):
            continue
        token = value[len(prefix) :]
        if token.isdigit():
            result.append(int(token))
    return list(dict.fromkeys(result))


def _closure_value(function: Any, name: str) -> Any:
    try:
        cells = function.__closure__ or ()
        return dict(zip(function.__code__.co_freevars, (cell.cell_contents for cell in cells))).get(name)
    except Exception:
        return None


def apply(M: Any) -> None:
    if getattr(M, "_turto_v750_context_filters_offer_format_installed", False):
        return

    try:
        from price_lists_domain.issued_offers import editor as issued_editor
        from price_lists_domain.issued_offers import service
    except Exception:
        M._turto_v750_context_filters_offer_format_installed = True
        return

    # ------------------------------------------------------------------
    # Filter cells follow displaycolumns (order + visibility), not the original
    # structural column indices.  Width drag and horizontal scrolling also
    # trigger a synchronized redraw.
    # ------------------------------------------------------------------
    def schedule_filter_sync(tree: Any, delay: int = 0) -> None:
        """Coalesce redraws without entering a nested Tcl/Tk idle loop."""
        if not _widget_exists(tree):
            return
        callback = getattr(tree, "_sync_filter_bar", None)
        if not callable(callback):
            return
        try:
            delay = max(0, int(delay))
            token_name = (
                "_v750_filter_sync_after"
                if delay
                else "_v750_filter_sync_idle"
            )
            pending = getattr(tree, token_name, None)
            if pending is not None:
                try:
                    tree.after_cancel(pending)
                except Exception:
                    pass
                try:
                    setattr(tree, token_name, None)
                except Exception:
                    pass

            def run() -> None:
                try:
                    setattr(tree, token_name, None)
                except Exception:
                    pass
                if not _widget_exists(tree):
                    return
                current = getattr(tree, "_sync_filter_bar", None)
                if callable(current):
                    current()

            token = tree.after(delay, run) if delay else tree.after_idle(run)
            setattr(tree, token_name, token)
        except Exception:
            # Never invoke a geometry redraw synchronously as a fallback.
            # This function is itself called from Configure/xscroll events;
            # immediate re-entry into Tcl/Tk is the native crash condition.
            pass

    def attach_filter_bar(tree: Any, filter_frame: Any) -> None:
        try:
            columns = _all_columns(tree)
            cells: list[tuple[str, Any]] = []
            for widget in filter_frame.winfo_children():
                if getattr(widget, "_filter_overlay_control", False):
                    continue
                try:
                    info = widget.grid_info()
                    index = int(info.get("column", 0))
                except Exception:
                    continue
                if not 0 <= index < len(columns):
                    try:
                        widget.place_forget()
                    except Exception:
                        pass
                    continue
                cells.append((columns[index], widget))
            if not cells or not columns:
                return

            height = max(
                [int(widget.winfo_reqheight()) for _column, widget in cells] + [34]
            ) + 2
            try:
                filter_frame.configure(height=height)
            except Exception:
                pass

            def sync(*_args: Any) -> None:
                if (
                    not _widget_exists(tree)
                    or not _widget_exists(filter_frame)
                    or getattr(tree, "_v750_filter_sync_running", False)
                ):
                    return
                tree._v750_filter_sync_running = True
                try:
                    # Never call update_idletasks() here. sync() is reached from
                    # Configure, xscrollcommand and after callbacks; a nested Tcl
                    # event loop can execute another layout callback while the
                    # current Treeview command is still active on Windows/Tk 8.6.
                    visible = displayed_columns(tree)
                    widths: dict[str, int] = {}
                    for column in visible:
                        try:
                            widths[column] = max(
                                1, int(tree.column(column, "width"))
                            )
                        except Exception:
                            continue
                    visible = [column for column in visible if column in widths]
                    if not visible:
                        return
                    total = max(1, sum(widths.values()))
                    try:
                        first = float(tree.xview()[0])
                    except Exception:
                        first = 0.0
                    offset = int(round(first * total))
                    starts: dict[str, int] = {}
                    cursor = 0
                    for column in visible:
                        starts[column] = cursor
                        cursor += widths[column]
                    for column, widget in cells:
                        if not _widget_exists(widget):
                            continue
                        if column not in starts:
                            try:
                                widget.place_forget()
                            except Exception:
                                pass
                            continue
                        try:
                            widget.place(
                                x=starts[column] - offset,
                                y=0,
                                width=widths[column],
                                height=height,
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                finally:
                    try:
                        tree._v750_filter_sync_running = False
                    except Exception:
                        pass

            tree._filter_frame = filter_frame
            tree._filter_cells = [widget for _column, widget in cells]
            tree._filter_cell_columns = [column for column, _widget in cells]
            tree._sync_filter_bar = sync
            tree._v750_filter_displaycolumns = True

            for sequence in ("<Configure>", "<B1-Motion>", "<ButtonRelease-1>", "<Map>"):
                tree.bind(
                    sequence,
                    lambda _event, current=tree: schedule_filter_sync(current),
                    add="+",
                )
            filter_frame.bind(
                "<Configure>",
                lambda _event, current=tree: schedule_filter_sync(current),
                add="+",
            )

            # A Treeview reports every xview change through xscrollcommand.
            # Preserve the already connected scrollbar command and add only the
            # filter redraw; this catches scrollbar drags and mouse-wheel shifts.
            if not getattr(tree, "_v750_xscroll_hook", False):
                tree._v750_xscroll_hook = True
                original = tree.cget("xscrollcommand")
                tree._v750_original_xscrollcommand = original

                def xscroll(first: Any, last: Any) -> None:
                    if original:
                        try:
                            tree.tk.call(original, first, last)
                        except Exception:
                            pass
                    schedule_filter_sync(tree)

                tree.configure(xscrollcommand=xscroll)
            schedule_filter_sync(tree)
        except Exception:
            pass

    M.attach_filter_bar = attach_filter_bar
    M.schedule_v750_filter_sync = schedule_filter_sync
    M.v750_displayed_columns = displayed_columns

    for api_name in (
        "save_persistent_tree_layout",
        "install_persistent_tree_layout",
        "open_tree_columns_dialog",
    ):
        previous = getattr(M, api_name, None)
        if not callable(previous):
            continue

        def make_layout_wrapper(function: Any):
            def wrapped(tree: Any, *args: Any, **kwargs: Any):
                result = function(tree, *args, **kwargs)
                schedule_filter_sync(tree, 0)
                schedule_filter_sync(tree, 80)
                return result

            return wrapped

        setattr(M, api_name, make_layout_wrapper(previous))

    # ------------------------------------------------------------------
    # Additive storage for archived opportunities and supplier presentation.
    # ------------------------------------------------------------------
    def ensure_v750_schema() -> None:
        with M.db() as con:
            if _table_exists(con, "actions"):
                columns = _table_columns(con, "actions")
                for name, declaration in (
                    ("archived", "INTEGER NOT NULL DEFAULT 0"),
                    ("archived_at", "TEXT DEFAULT ''"),
                    ("archived_by", "TEXT DEFAULT ''"),
                ):
                    if name not in columns:
                        con.execute(
                            f'ALTER TABLE actions ADD COLUMN "{name}" {declaration}'
                        )
            if _table_exists(con, "requests"):
                columns = _table_columns(con, "requests")
                for name, declaration in (
                    ("archived", "INTEGER NOT NULL DEFAULT 0"),
                    ("archived_at", "TEXT DEFAULT ''"),
                    ("archived_by", "TEXT DEFAULT ''"),
                ):
                    if name not in columns:
                        con.execute(
                            f'ALTER TABLE requests ADD COLUMN "{name}" {declaration}'
                        )
            if _table_exists(con, "business_document_items"):
                columns = _table_columns(con, "business_document_items")
                for name, declaration in (
                    ("supplier_presentation_snapshot", "INTEGER NOT NULL DEFAULT 0"),
                    ("supplier_name_snapshot", "TEXT DEFAULT ''"),
                    ("name_note_snapshot", "TEXT DEFAULT ''"),
                ):
                    if name not in columns:
                        con.execute(
                            f'ALTER TABLE business_document_items '
                            f'ADD COLUMN "{name}" {declaration}'
                        )

    previous_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(previous_ensure_schema):
        def ensure_schema() -> Any:
            result = previous_ensure_schema()
            ensure_v750_schema()
            return result

        M.ensure_schema = ensure_schema
    M.ensure_v750_schema = ensure_v750_schema

    # ------------------------------------------------------------------
    # Received-offer rows keep the supplier designation and no displayed code.
    # A separate suffix is appended without overwriting the supplier snapshot.
    # ------------------------------------------------------------------
    previous_normalize_item = service.normalize_item

    def normalize_item(raw: Any, position: int | None = None, recalculate_sale: bool = False):
        source = dict(raw or {})
        item = previous_normalize_item(source, position, recalculate_sale)
        supplier_presentation = _truthy(
            source.get(
                "supplier_presentation_snapshot",
                item.get("supplier_presentation_snapshot", 0),
            )
        )
        item["supplier_presentation_snapshot"] = 1 if supplier_presentation else 0
        item["supplier_name_snapshot"] = _text(
            source.get("supplier_name_snapshot")
            or item.get("supplier_name_snapshot")
        )
        item["name_note_snapshot"] = _text(
            source.get("name_note_snapshot") or item.get("name_note_snapshot")
        )

        if (
            supplier_presentation
            and _text(item.get("row_type"), "product").casefold() == "product"
        ):
            base_name = _text(
                source.get("supplier_name_snapshot")
                or item.get("supplier_name_snapshot")
                or source.get("_v740_source_name")
                or item.get("_v740_source_name")
                or source.get("name")
                or item.get("name"),
                "Položka",
            )
            note = _text(
                source.get("name_note_snapshot") or item.get("name_note_snapshot")
            )
            expected = base_name + (f" – {note}" if note else "")
            edited_name = _text(source.get("name"))
            # The standard item dialog edits the visible designation.  Interpret
            # any change as a suffix so the supplier's original text is retained.
            if edited_name and edited_name != expected:
                if edited_name == base_name:
                    note = ""
                elif edited_name.startswith(base_name):
                    note = edited_name[len(base_name) :].lstrip(" \t–—-:;,. ")
                else:
                    note = edited_name
                expected = base_name + (f" – {note}" if note else "")
            item.update(
                supplier_presentation_snapshot=1,
                supplier_name_snapshot=base_name,
                name_note_snapshot=note,
                product_code="",
                internal_code_snapshot="",
                internal_name_snapshot="",
                name=expected,
                _v740_missing_internal_identity=False,
            )
        return item

    service.normalize_item = normalize_item

    previous_draft_from_supplier_offer = service.draft_from_supplier_offer

    def draft_from_supplier_offer(module: Any, offer_id: int):
        document, items = previous_draft_from_supplier_offer(module, offer_id)
        source_rows: dict[int, dict[str, Any]] = {}
        source_ids = [
            int(item.get("source_supplier_offer_item_id"))
            for item in items
            if item.get("source_supplier_offer_item_id")
        ]
        if source_ids:
            try:
                with module.db() as con:
                    marks = ",".join("?" for _ in source_ids)
                    source_rows = {
                        int(row["id"]): dict(row)
                        for row in con.execute(
                            f"SELECT * FROM supplier_offer_items WHERE id IN ({marks})",
                            source_ids,
                        ).fetchall()
                    }
            except Exception:
                source_rows = {}

        prepared = []
        for index, raw in enumerate(items, 1):
            item = dict(raw or {})
            source_id = item.get("source_supplier_offer_item_id")
            source_row = source_rows.get(int(source_id)) if source_id else None
            if (
                source_row
                and _text(item.get("row_type"), "product").casefold() == "product"
            ):
                supplier_name = _text(
                    source_row.get("original_name")
                    or source_row.get("item_key")
                    or source_row.get("product_code")
                    or item.get("_v740_source_name")
                    or item.get("name"),
                    "Položka",
                )
                item.update(
                    supplier_presentation_snapshot=1,
                    supplier_name_snapshot=supplier_name,
                    name_note_snapshot="",
                    product_code="",
                    item_key=_text(
                        source_row.get("item_key")
                        or source_row.get("product_code")
                        or supplier_name
                    ),
                    name=supplier_name,
                    description=_text(
                        source_row.get("details") or item.get("description")
                    ),
                    internal_code_snapshot="",
                    internal_name_snapshot="",
                    _v740_source_code=_text(
                        source_row.get("product_code")
                        or source_row.get("item_key")
                    ),
                    _v740_source_name=supplier_name,
                    _v740_missing_internal_identity=False,
                )
            prepared.append(normalize_item(item, index))
        return document, prepared

    service.draft_from_supplier_offer = draft_from_supplier_offer

    previous_save_document = service.save_document

    def save_document(module: Any, values: Any, items: Iterable[Any], document_id: int | None = None):
        ensure_v750_schema()
        prepared = [
            normalize_item(dict(item or {}), index)
            for index, item in enumerate(list(items), 1)
        ]
        result = previous_save_document(module, values, prepared, document_id)
        try:
            with module.db() as con:
                rows = con.execute(
                    """SELECT id FROM business_document_items
                         WHERE document_id=? ORDER BY position,id""",
                    (int(result),),
                ).fetchall()
                for row, item in zip(rows, prepared):
                    con.execute(
                        """UPDATE business_document_items
                              SET supplier_presentation_snapshot=?,
                                  supplier_name_snapshot=?,
                                  name_note_snapshot=?
                            WHERE id=?""",
                        (
                            1 if _truthy(item.get("supplier_presentation_snapshot")) else 0,
                            _text(item.get("supplier_name_snapshot")),
                            _text(item.get("name_note_snapshot")),
                            int(row["id"]),
                        ),
                    )
        except Exception:
            pass
        return result

    service.save_document = save_document

    # ------------------------------------------------------------------
    # Issued-offer output guard: catalogue/manual product rows still require
    # TURTO identity, while supplier-presentation rows deliberately carry none.
    # ------------------------------------------------------------------
    Editor = issued_editor.IssuedOfferEditor

    def missing_customer_identity_indices(instance: Any) -> list[int]:
        missing: list[int] = []
        for index, raw in enumerate(instance.items):
            item = normalize_item(raw, index + 1)
            if _text(item.get("row_type"), "product").casefold() != "product":
                continue
            if _truthy(item.get("supplier_presentation_snapshot")):
                continue
            code = _text(item.get("internal_code_snapshot"))
            name = _text(item.get("internal_name_snapshot"))
            if not code or not name:
                missing.append(index)
        return missing

    def require_customer_identity(instance: Any, action_text: str) -> bool:
        missing = missing_customer_identity_indices(instance)
        if not missing:
            return True
        first = missing[0]
        try:
            instance.tree.selection_set(f"r{first}")
            instance.tree.see(f"r{first}")
        except Exception:
            pass
        M.messagebox.showwarning(
            "Interní kódy a názvy",
            f"Nelze {action_text}.\n\n"
            f"{len(missing)} produktových položek vložených mimo Přijatou "
            "nabídku nemá interní kód nebo interní název TURTO. Doplňte "
            "označené řádky a akci zopakujte.",
            parent=instance.win,
        )
        return False

    current_generate_pdf = Editor.generate_pdf
    underlying_generate_pdf = (
        _closure_value(current_generate_pdf, "previous_generate_pdf")
        or current_generate_pdf
    )

    def generate_pdf(self: Any, *args: Any, **kwargs: Any):
        if not require_customer_identity(self, "vytvořit zákaznické PDF"):
            return None
        return underlying_generate_pdf(self, *args, **kwargs)

    Editor.generate_pdf = generate_pdf

    current_outlook_draft = Editor.outlook_draft
    underlying_outlook_draft = (
        _closure_value(current_outlook_draft, "previous_outlook_draft")
        or current_outlook_draft
    )

    def outlook_draft(self: Any, *args: Any, **kwargs: Any):
        if not require_customer_identity(self, "vytvořit Outlook koncept"):
            return None
        return underlying_outlook_draft(self, *args, **kwargs)

    Editor.outlook_draft = outlook_draft
    Editor._turto_v750_supplier_presentation_guard = True

    def reset_tree_columns(tree: Any) -> None:
        try:
            defaults = getattr(tree, "_v700_default_widths", {}) or {}
            design = getattr(tree, "_turto_design_widths", {}) or {}
            for column in _all_columns(tree):
                if column in defaults:
                    width = int(defaults[column])
                    design[column] = width
                    tree.column(column, width=width, minwidth=30)
            tree._turto_design_widths = design
            tree.configure(displaycolumns="#all")
            saver = getattr(M, "save_persistent_tree_layout", None)
            if callable(saver):
                saver(tree)
            schedule_filter_sync(tree)
        except Exception:
            pass

    def append_supplier_name_note(instance: Any, index: int) -> None:
        if not 0 <= int(index) < len(instance.items):
            return
        item = normalize_item(instance.items[int(index)], int(index) + 1)
        if not _truthy(item.get("supplier_presentation_snapshot")):
            return
        note = M.simpledialog.askstring(
            "Doplnění názvu",
            "Text bude připojen za původní název dodavatele:",
            initialvalue=_text(item.get("name_note_snapshot")),
            parent=instance.win,
        )
        if note is None:
            return
        item["name_note_snapshot"] = _text(note)
        base_name = _text(item.get("supplier_name_snapshot"), "Položka")
        item["name"] = base_name + (
            f" – {item['name_note_snapshot']}"
            if item["name_note_snapshot"]
            else ""
        )
        instance.items[int(index)] = normalize_item(item, int(index) + 1)
        instance.refresh_items()
        try:
            instance.tree.selection_set(f"r{int(index)}")
            instance.tree.see(f"r{int(index)}")
        except Exception:
            pass

    def install_issued_context(instance: Any) -> None:
        tree = getattr(instance, "tree", None)
        if not _widget_exists(tree):
            return
        header_menu = M.tk.Menu(tree, tearoff=False)
        header_menu.add_command(
            label="Nastavit zobrazené sloupce…",
            command=lambda: getattr(
                M, "open_tree_columns_dialog", lambda _tree: None
            )(tree),
        )
        header_menu.add_command(
            label="Obnovit výchozí sloupce",
            command=lambda: reset_tree_columns(tree),
        )
        row_menu = M.tk.Menu(tree, tearoff=False)
        row_state = {"index": None}

        def rebuild_row_menu(index: int) -> None:
            row_menu.delete(0, "end")
            row_menu.add_command(
                label="Otevřít / upravit položku",
                command=instance.edit_item,
            )
            item = normalize_item(instance.items[index], index + 1)
            if _truthy(item.get("supplier_presentation_snapshot")):
                row_menu.add_command(
                    label="Doplnit text k názvu…",
                    command=lambda current=index: append_supplier_name_note(
                        instance, current
                    ),
                )
                if _text(item.get("name_note_snapshot")):
                    def clear_note(current: int = index) -> None:
                        current_item = normalize_item(
                            instance.items[current], current + 1
                        )
                        current_item["name_note_snapshot"] = ""
                        current_item["name"] = _text(
                            current_item.get("supplier_name_snapshot"), "Položka"
                        )
                        instance.items[current] = normalize_item(
                            current_item, current + 1
                        )
                        instance.refresh_items()
                        instance.tree.selection_set(f"r{current}")

                    row_menu.add_command(
                        label="Vymazat doplnění názvu",
                        command=clear_note,
                    )
            row_menu.add_separator()
            row_menu.add_command(
                label="Odebrat vybrané položky",
                command=instance.remove_items,
            )

        def popup(event: Any):
            region = tree.identify_region(event.x, event.y)
            menu = None
            if region in {"heading", "separator"}:
                menu = header_menu
            else:
                iid = str(tree.identify_row(event.y) or "")
                if not iid.startswith("r") or not iid[1:].isdigit():
                    return "break"
                index = int(iid[1:])
                if not 0 <= index < len(instance.items):
                    return "break"
                if iid not in tree.selection():
                    tree.selection_set(iid)
                row_state["index"] = index
                rebuild_row_menu(index)
                menu = row_menu
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
            return "break"

        tree.bind("<Button-3>", popup, add=False)
        tree._v750_header_menu = header_menu
        tree._v750_row_menu = row_menu
        tree._v750_context_owner = True

    previous_editor_init = Editor.__init__

    def editor_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_editor_init(self, *args, **kwargs)
        try:
            heading = None
            for child in self.outer.winfo_children():
                info = child.grid_info()
                if int(info.get("row", -1)) == 0:
                    heading = child
                    break
            if heading is not None and not _widget_exists(
                getattr(self, "page_format_label", None)
            ):
                self.page_format_label = M.ttk.Label(
                    heading,
                    text="Formát výstupu: A4 · 210 × 297 mm",
                    style="PageSubtitle.TLabel",
                )
                self.page_format_label.grid(
                    row=2,
                    column=0,
                    sticky="w",
                    pady=(2, 0),
                )
            hint = _text(self.status_hint.get())
            extra = (
                "Položky převzaté z Přijaté nabídky nemají kód a zachovávají "
                "název dodavatele; doplnění názvu je dostupné pravým tlačítkem."
            )
            if extra not in hint:
                self.status_hint.set((hint + " " + extra).strip())
        except Exception:
            pass
        install_issued_context(self)
        return result

    Editor.__init__ = editor_init
    M.ISSUED_OFFER_PAGE_FORMAT = {
        "name": "A4",
        "width_mm": 210,
        "height_mm": 297,
    }

    # ------------------------------------------------------------------
    # Unified archive storage helpers and row-context actions.
    # ------------------------------------------------------------------
    def active_user(app: Any) -> str:
        try:
            return _text(app.active_user.get(), "Výchozí")
        except Exception:
            try:
                return _text(M.get_setting("active_user", ""), "Výchozí")
            except Exception:
                return "Výchozí"

    def set_archived_rows(
        app: Any,
        table: str,
        ids: Iterable[int],
        archived: bool,
    ) -> int:
        unique = list(dict.fromkeys(int(value) for value in ids))
        if not unique:
            return 0
        ensure_v750_schema()
        with M.db() as con:
            columns = _table_columns(con, table)
            if "archived" not in columns:
                return 0
            assignments = ["archived=?"]
            values: list[Any] = [1 if archived else 0]
            if "archived_at" in columns:
                assignments.append("archived_at=?")
                values.append(
                    datetime.now().isoformat(timespec="seconds") if archived else ""
                )
            if "archived_by" in columns:
                assignments.append("archived_by=?")
                values.append(active_user(app) if archived else "")
            if "updated_at" in columns:
                assignments.append("updated_at=CURRENT_TIMESTAMP")
            marks = ",".join("?" for _ in unique)
            con.execute(
                f"UPDATE {table} SET {','.join(assignments)} WHERE id IN ({marks})",
                tuple(values + unique),
            )
        return len(unique)

    def archive_actions(app: Any, archived: bool) -> None:
        tree = getattr(app, "action_tree", None)
        ids = _selected_ids(tree, "a") if tree is not None else []
        if not ids:
            return M.messagebox.showinfo(
                "Příležitosti",
                "Vyberte alespoň jednu příležitost.",
                parent=app,
            )
        if archived and not M.messagebox.askyesno(
            "Příležitosti",
            f"Archivovat {len(ids)} vybraných příležitostí?",
            parent=app,
        ):
            return
        set_archived_rows(app, "actions", ids, archived)
        app.refresh_actions()

    def archive_requests(app: Any, tree: Any, archived: bool) -> None:
        ids = _selected_ids(tree, "r")
        if not ids:
            return M.messagebox.showinfo(
                "Poptávky",
                "Vyberte alespoň jednu poptávku.",
                parent=app,
            )
        if archived and not M.messagebox.askyesno(
            "Poptávky",
            f"Archivovat {len(ids)} vybraných poptávek?",
            parent=app,
        ):
            return
        set_archived_rows(app, "requests", ids, archived)
        if tree is getattr(app, "mivo_tree", None):
            app.refresh_mivo_requests()
        else:
            app.refresh_requests()

    def request_action(app: Any, tree: Any, method_name: str) -> Any:
        callback = getattr(app, method_name, None)
        if not callable(callback):
            return None
        if tree is getattr(app, "mivo_tree", None):
            runner = getattr(app, "_run_on_request_tree", None)
            if callable(runner):
                return runner(tree, callback)
        return callback()

    def apply_action_archive_visibility(app: Any) -> None:
        tree = getattr(app, "action_tree", None)
        if not _widget_exists(tree):
            return
        try:
            with M.db() as con:
                if "archived" not in _table_columns(con, "actions"):
                    return
                archived_ids = {
                    int(row[0])
                    for row in con.execute(
                        "SELECT id FROM actions WHERE coalesce(archived,0)=1"
                    ).fetchall()
                }
        except Exception:
            return
        show = _truthy(
            getattr(app, "action_show_archived", None).get()
            if getattr(app, "action_show_archived", None) is not None
            else False
        )
        for iid in list(tree.get_children("")):
            value = str(iid)
            if not value.startswith("a") or not value[1:].isdigit():
                continue
            action_id = int(value[1:])
            if action_id not in archived_ids:
                continue
            if not show:
                tree.delete(iid)
                continue
            try:
                tags = list(tree.item(iid, "tags") or ())
                if "status_cancel" not in tags:
                    tags.append("status_cancel")
                tree.item(iid, tags=tuple(tags))
            except Exception:
                pass

    previous_refresh_actions = getattr(M.App, "refresh_actions", None)
    if callable(previous_refresh_actions):
        def refresh_actions(self: Any, *args: Any, **kwargs: Any):
            result = previous_refresh_actions(self, *args, **kwargs)
            apply_action_archive_visibility(self)
            return result

        M.App.refresh_actions = refresh_actions

    def find_toolbar(app: Any, key: str, markers: tuple[str, ...]) -> Any:
        stored = getattr(app, f"_v750_{key}_toolbar", None)
        if _widget_exists(stored):
            return stored
        page = getattr(app, "tabs", {}).get(key)
        if not _widget_exists(page):
            return None

        def walk(widget: Any):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        for widget in walk(page):
            try:
                texts = [
                    _text(child.cget("text"))
                    for child in widget.winfo_children()
                    if child.winfo_class().endswith(("Button", "Checkbutton"))
                ]
            except Exception:
                continue
            if any(
                marker.casefold() in text.casefold()
                for marker in markers
                for text in texts
            ):
                setattr(app, f"_v750_{key}_toolbar", widget)
                return widget
        return None

    def configure_archive_toolbar(app: Any, key: str) -> None:
        if key == "actions":
            toolbar = find_toolbar(app, key, ("Připomínka", "Poptat", "Smazat"))
            variable_name = "action_show_archived"
            refresh_name = "refresh_actions"
            archive_command = lambda: archive_actions(app, True)
            restore_command = lambda: archive_actions(app, False)
        elif key == "requests":
            toolbar = find_toolbar(app, key, ("Bez odezvy", "Obdrženo dnes", "Editovat"))
            variable_name = "req_show_archived"
            refresh_name = "refresh_requests"
            tree = getattr(app, "request_tree", None)
            archive_command = lambda: archive_requests(app, tree, True)
            restore_command = lambda: archive_requests(app, tree, False)
        else:
            toolbar = find_toolbar(app, key, ("Bez odezvy", "Obdrženo dnes", "Editovat"))
            variable_name = "mivo_show_archived"
            refresh_name = "refresh_mivo_requests"
            tree = getattr(app, "mivo_tree", None)
            archive_command = lambda: archive_requests(app, tree, True)
            restore_command = lambda: archive_requests(app, tree, False)
        if not _widget_exists(toolbar):
            return

        # Remove legacy row-action controls even when an older layer placed one
        # of them in a neighbouring frame.  The title's "+ Nová ..." action
        # and filter inputs are not part of this explicit label set.
        forbidden = {
            "🗑 smazat",
            "smazat",
            "🔔 připomínka",
            "připomínka",
            "✉ poptat",
            "poptat",
            "✎ editovat",
            "editovat",
            "vytvořit e-mail",
            "obdrženo dnes",
            "bez odezvy",
            "↩ obnovit",
            "↩ obnovit vybrané",
            "obnovit vybrané",
            "📦 archivovat",
            "📦 archivovat vybrané",
            "archivovat vybrané",
            "zobrazit archivované",
        }
        page = getattr(app, "tabs", {}).get(key)

        def remove_legacy(widget: Any) -> None:
            for child in list(widget.winfo_children()):
                try:
                    if not getattr(child, "_v750_archive_control", False):
                        widget_class = child.winfo_class()
                        label = _text(child.cget("text")).casefold()
                        if (
                            widget_class.endswith("Button")
                            or widget_class.endswith("Checkbutton")
                        ) and label in forbidden:
                            child.destroy()
                            continue
                except Exception:
                    pass
                try:
                    remove_legacy(child)
                except Exception:
                    pass

        if _widget_exists(page):
            remove_legacy(page)

        variable = getattr(app, variable_name, None)
        if variable is None:
            variable = M.tk.BooleanVar(value=False)
            setattr(app, variable_name, variable)

        controls_name = f"_v750_{key}_archive_controls"
        controls = getattr(app, controls_name, None)
        if not controls or not all(_widget_exists(control) for control in controls):
            checkbox = M.ttk.Checkbutton(
                toolbar,
                text="Zobrazit archivované",
                variable=variable,
                command=getattr(app, refresh_name),
            )
            restore = M.ttk.Button(
                toolbar,
                text="↩ Obnovit vybrané",
                style="Toolbar.TButton",
                command=restore_command,
            )
            archive = M.ttk.Button(
                toolbar,
                text="📦 Archivovat vybrané",
                style="Toolbar.TButton",
                command=archive_command,
            )
            for control in (checkbox, restore, archive):
                control._v750_archive_control = True
            checkbox.pack(side="left")
            restore.pack(side="right", padx=4)
            archive.pack(side="right", padx=4)
            controls = (checkbox, archive, restore)
            setattr(app, controls_name, controls)
        if key == "actions":
            try:
                app.action_tree.configure(selectmode="extended")
            except Exception:
                pass

    def install_workspace_context(app: Any, key: str, tree: Any) -> None:
        if not _widget_exists(tree):
            return
        header_menu = M.tk.Menu(tree, tearoff=False)
        header_menu.add_command(
            label="Nastavit zobrazené sloupce…",
            command=lambda: getattr(
                M, "open_tree_columns_dialog", lambda _tree: None
            )(tree),
        )
        header_menu.add_command(
            label="Obnovit výchozí sloupce",
            command=lambda: reset_tree_columns(tree),
        )
        row_menu = M.tk.Menu(tree, tearoff=False)
        if key == "actions":
            row_menu.add_command(
                label="Otevřít / upravit",
                command=lambda: app.edit_action(tree),
            )
            row_menu.add_command(
                label="Vytvořit poptávku",
                command=app.request_from_selected_action,
            )
            row_menu.add_command(
                label="Přidat připomínku",
                command=app.task_from_selected_action,
            )
            row_menu.add_separator()
            row_menu.add_command(
                label="Archivovat vybrané",
                command=lambda: archive_actions(app, True),
            )
            row_menu.add_command(
                label="Obnovit vybrané",
                command=lambda: archive_actions(app, False),
            )
            row_menu.add_separator()
            row_menu.add_command(
                label="Smazat / zrušit",
                command=app.delete_action,
            )
        else:
            row_menu.add_command(
                label="Otevřít / upravit",
                command=lambda: request_action(app, tree, "edit_request"),
            )
            row_menu.add_command(
                label="Vytvořit e-mail",
                command=lambda: request_action(app, tree, "mail_selected"),
            )
            row_menu.add_command(
                label="Obdrženo dnes",
                command=lambda: request_action(app, tree, "mark_received"),
            )
            row_menu.add_command(
                label="Bez odezvy",
                command=lambda: request_action(app, tree, "mark_no_response"),
            )
            row_menu.add_separator()
            row_menu.add_command(
                label="Archivovat vybrané",
                command=lambda: archive_requests(app, tree, True),
            )
            row_menu.add_command(
                label="Obnovit vybrané",
                command=lambda: archive_requests(app, tree, False),
            )
            row_menu.add_separator()
            row_menu.add_command(
                label="Trvale smazat z evidence",
                command=lambda: request_action(app, tree, "hard_delete_request"),
            )

        def popup(event: Any):
            region = tree.identify_region(event.x, event.y)
            if region in {"heading", "separator"}:
                menu = header_menu
            else:
                iid = str(tree.identify_row(event.y) or "")
                if not iid:
                    return "break"
                if iid not in tree.selection():
                    tree.selection_set(iid)
                menu = row_menu
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
            return "break"

        tree.bind("<Button-3>", popup, add=False)
        tree._v750_header_menu = header_menu
        tree._v750_row_menu = row_menu
        tree._v750_context_owner = key

    def configure_workspaces(app: Any) -> None:
        for key in ("actions", "requests", "mivo"):
            configure_archive_toolbar(app, key)
        install_workspace_context(
            app, "actions", getattr(app, "action_tree", None)
        )
        install_workspace_context(
            app, "requests", getattr(app, "request_tree", None)
        )
        install_workspace_context(
            app, "mivo", getattr(app, "mivo_tree", None)
        )
        apply_action_archive_visibility(app)

    for method_name, key in (
        ("build_actions", "actions"),
        ("build_requests", "requests"),
        ("build_mivo", "mivo"),
    ):
        previous = getattr(M.App, method_name, None)
        if not callable(previous):
            continue

        def make_build_wrapper(function: Any, workspace_key: str):
            def wrapped(self: Any, *args: Any, **kwargs: Any):
                result = function(self, *args, **kwargs)
                configure_archive_toolbar(self, workspace_key)
                tree = getattr(
                    self,
                    {
                        "actions": "action_tree",
                        "requests": "request_tree",
                        "mivo": "mivo_tree",
                    }[workspace_key],
                    None,
                )
                install_workspace_context(self, workspace_key, tree)
                return result

            return wrapped

        setattr(M.App, method_name, make_build_wrapper(previous, key))

    previous_app_init = M.App.__init__

    def app_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_app_init(self, *args, **kwargs)
        for delay in (0, 80, 260, 760, 1650):
            try:
                self.after(delay, lambda current=self: configure_workspaces(current))
            except Exception:
                pass
        return result

    M.App.__init__ = app_init
    M._turto_v750_context_filters_offer_format_installed = True


__all__ = ["apply", "displayed_columns"]