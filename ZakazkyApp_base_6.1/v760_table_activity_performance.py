"""TURTO CRM 7.6 – consistent tables, archive parity and lean refreshes.

This additive layer keeps the existing data model and page owners intact while
making the table presentation uniform and removing a few expensive refresh
patterns.  It deliberately avoids rebuilding the commercial workspaces.
"""
from __future__ import annotations

from datetime import date, datetime
import time
from typing import Any, Callable, Iterable


LAST_ACTIVITY_COLUMN = "Poslední pohyb"


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "ne", "no", "off"}
    return bool(value)


def _exists(widget: Any) -> bool:
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


def _displayed_columns(tree: Any) -> list[str]:
    columns = _all_columns(tree)
    if not columns:
        return []
    try:
        raw = tree.cget("displaycolumns")
        if isinstance(raw, str):
            raw = tree.tk.splitlist(raw)
        values = [str(value) for value in raw]
    except Exception:
        values = ["#all"]
    if not values or values == ["#all"]:
        return columns
    result: list[str] = []
    for value in values:
        if value == "#all":
            return columns
        if value in columns:
            column = value
        elif value.lstrip("-").isdigit():
            index = int(value)
            if not 0 <= index < len(columns):
                continue
            column = columns[index]
        else:
            continue
        if column not in result:
            result.append(column)
    return result


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


def _table_columns(con: Any, table: str) -> set[str]:
    try:
        return {
            str(row[1])
            for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
    except Exception:
        return set()


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    try:
        return row[name]
    except Exception:
        try:
            return getattr(row, name)
        except Exception:
            return default


def _selected_ids(tree: Any, prefix: str) -> list[int]:
    result: list[int] = []
    if not _exists(tree):
        return result
    for iid in tree.selection():
        value = str(iid)
        if value.startswith(prefix) and value[len(prefix) :].isdigit():
            result.append(int(value[len(prefix) :]))
    return list(dict.fromkeys(result))


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _normalize_anchor(value: Any) -> str:
    anchor = _text(value, "center").casefold()
    aliases = {
        "left": "w",
        "right": "e",
        "centre": "center",
        "c": "center",
        "n": "center",
        "s": "center",
    }
    anchor = aliases.get(anchor, anchor)
    return anchor if anchor in {"w", "e", "center"} else "center"


def _format_activity(value: Any) -> str:
    raw = _text(value)
    if not raw:
        return "—"
    candidate = raw.replace("Z", "+00:00")
    parsed = None
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except Exception:
                pass
    if parsed is None:
        return raw
    if parsed.hour or parsed.minute or parsed.second:
        return parsed.strftime("%d.%m.%Y %H:%M")
    return parsed.strftime("%d.%m.%Y")



def _parse_activity_datetime(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw or raw == "—":
        return None
    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    except Exception:
        pass
    for fmt in (
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None

def _timestamp_expr(alias: str, columns: set[str], candidates: Iterable[str]) -> str:
    """Return the newest non-empty ISO-like timestamp from one source row.

    Operational dates in the CRM are stored in ISO order, so a scalar text MAX
    is deterministic.  Empty fields use an empty sentinel and are converted back
    to NULL; unlike COALESCE this does not hide a later sent/accepted timestamp.
    """
    parts = [
        f'COALESCE(NULLIF(TRIM(COALESCE({alias}."{name}",\'\')),\'\'),\'\')'
        for name in candidates
        if name in columns
    ]
    if not parts:
        return "NULL"
    if len(parts) == 1:
        return f"NULLIF({parts[0]},'')"
    return "NULLIF(MAX(" + ",".join(parts) + "),'')"


def _project_activity_union(con: Any) -> str:
    parts: list[str] = []

    project_columns = _table_columns(con, "projects")
    project_ts = _timestamp_expr(
        "p",
        project_columns,
        ("updated_at", "archived_at", "created_at", "start_date"),
    )
    parts.append(f"SELECT p.id project_id,{project_ts} activity_at FROM projects p")

    action_columns = _table_columns(con, "actions")
    if action_columns and "project_id" in action_columns:
        action_ts = _timestamp_expr(
            "a",
            action_columns,
            ("updated_at", "created_at", "created_date"),
        )
        parts.append(
            f"SELECT a.project_id,{action_ts} activity_at FROM actions a "
            "WHERE a.project_id IS NOT NULL"
        )

    if _table_exists(con, "action_history") and action_columns:
        history_columns = _table_columns(con, "action_history")
        history_ts = _timestamp_expr(
            "h", history_columns, ("created_at", "event_date", "date_created")
        )
        parts.append(
            f"SELECT a.project_id,{history_ts} activity_at "
            "FROM action_history h JOIN actions a ON a.id=h.action_id "
            "WHERE a.project_id IS NOT NULL"
        )

    if _table_exists(con, "requests") and action_columns:
        request_columns = _table_columns(con, "requests")
        request_ts = _timestamp_expr(
            "r",
            request_columns,
            ("updated_at", "received_date", "asked_date", "created_at"),
        )
        parts.append(
            f"SELECT a.project_id,{request_ts} activity_at "
            "FROM requests r JOIN actions a ON a.id=r.action_id "
            "WHERE a.project_id IS NOT NULL"
        )

    if _table_exists(con, "tasks") and action_columns:
        task_columns = _table_columns(con, "tasks")
        task_ts = _timestamp_expr(
            "t", task_columns, ("updated_at", "done_at", "created_at")
        )
        parts.append(
            f"SELECT a.project_id,{task_ts} activity_at "
            "FROM tasks t JOIN actions a ON a.id=t.action_id "
            "WHERE a.project_id IS NOT NULL"
        )

    if _table_exists(con, "supplier_offers") and action_columns:
        offer_columns = _table_columns(con, "supplier_offers")
        if "action_id" in offer_columns:
            offer_ts = _timestamp_expr(
                "o",
                offer_columns,
                ("updated_at", "imported_at", "created_at", "offer_date"),
            )
            parts.append(
                f"SELECT a.project_id,{offer_ts} activity_at "
                "FROM supplier_offers o JOIN actions a ON a.id=o.action_id "
                "WHERE a.project_id IS NOT NULL"
            )

    if _table_exists(con, "business_documents"):
        document_columns = _table_columns(con, "business_documents")
        document_ts = _timestamp_expr(
            "d",
            document_columns,
            (
                "updated_at",
                "sent_at",
                "accepted_at",
                "rejected_at",
                "created_at",
                "issue_date",
            ),
        )
        if "project_id" in document_columns:
            parts.append(
                f"SELECT d.project_id,{document_ts} activity_at "
                "FROM business_documents d WHERE d.project_id IS NOT NULL"
            )
        if "action_id" in document_columns and action_columns:
            parts.append(
                f"SELECT a.project_id,{document_ts} activity_at "
                "FROM business_documents d JOIN actions a ON a.id=d.action_id "
                "WHERE a.project_id IS NOT NULL"
            )

    return " UNION ALL ".join(parts)


def apply(M: Any) -> None:
    if getattr(M, "_turto_v760_table_activity_performance_installed", False):
        return

    # ------------------------------------------------------------------
    # Additive schema and indexes.  No existing row is rewritten.
    # ------------------------------------------------------------------
    def create_index(con: Any, name: str, table: str, columns: tuple[str, ...]) -> None:
        if not _table_exists(con, table):
            return
        available = _table_columns(con, table)
        if not set(columns).issubset(available):
            return
        quoted = ",".join(f'"{column}"' for column in columns)
        con.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}"({quoted})')

    def ensure_v760_schema() -> None:
        with M.db() as con:
            if _table_exists(con, "projects"):
                columns = _table_columns(con, "projects")
                for name, declaration in (
                    ("updated_at", "TEXT DEFAULT ''"),
                    ("archived_at", "TEXT DEFAULT ''"),
                    ("archived_by", "TEXT DEFAULT ''"),
                ):
                    if name not in columns:
                        con.execute(
                            f'ALTER TABLE projects ADD COLUMN "{name}" {declaration}'
                        )
            if _table_exists(con, "tasks"):
                columns = _table_columns(con, "tasks")
                for name, declaration in (
                    ("updated_at", "TEXT DEFAULT ''"),
                    ("archived", "INTEGER NOT NULL DEFAULT 0"),
                    ("archived_at", "TEXT DEFAULT ''"),
                    ("archived_by", "TEXT DEFAULT ''"),
                ):
                    if name not in columns:
                        con.execute(
                            f'ALTER TABLE tasks ADD COLUMN "{name}" {declaration}'
                        )

            create_index(
                con,
                "idx_v760_actions_project_archived_updated",
                "actions",
                ("project_id", "archived", "updated_at"),
            )
            create_index(
                con,
                "idx_v760_requests_action_archived_dates",
                "requests",
                ("action_id", "archived", "asked_date", "received_date"),
            )
            create_index(
                con,
                "idx_v760_tasks_action_archived_due",
                "tasks",
                ("action_id", "archived", "done", "due_date"),
            )
            create_index(
                con,
                "idx_v760_action_history_action_created",
                "action_history",
                ("action_id", "created_at"),
            )
            create_index(
                con,
                "idx_v760_projects_active_updated",
                "projects",
                ("active", "updated_at"),
            )
            create_index(
                con,
                "idx_v760_supplier_offers_action_date",
                "supplier_offers",
                ("action_id", "offer_date"),
            )

    previous_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(previous_ensure_schema):
        def ensure_schema() -> Any:
            result = previous_ensure_schema()
            ensure_v760_schema()
            return result

        M.ensure_schema = ensure_schema
    M.ensure_v760_schema = ensure_v760_schema

    # ------------------------------------------------------------------
    # One lightweight presentation owner for every ttk.Treeview.
    # Heading anchor follows the corresponding data-cell anchor.  Vertical
    # separators are one-pixel overlays, one per visible column boundary.
    # ------------------------------------------------------------------
    Treeview = M.ttk.Treeview
    if not getattr(Treeview, "_turto_v760_table_polish_class", False):
        original_init = Treeview.__init__
        original_heading = Treeview.heading
        original_column = Treeview.column
        original_configure = Treeview.configure
        original_xview = Treeview.xview

        def separator_color(tree: Any) -> str:
            try:
                top = tree.winfo_toplevel()
                palette = getattr(top, "palette", {}) or {}
                if palette.get("border"):
                    return str(palette["border"])
            except Exception:
                pass
            try:
                style = M.ttk.Style(tree)
                return (
                    style.lookup("Treeview", "bordercolor")
                    or style.lookup("Treeview", "foreground")
                    or "#c8ced2"
                )
            except Exception:
                return "#c8ced2"

        def body_top(tree: Any) -> int:
            cached = getattr(tree, "_v760_body_top", None)
            if isinstance(cached, int) and cached >= 0:
                return cached
            result = 30
            try:
                limit = min(max(32, int(tree.winfo_height())), 90)
                for y in range(0, limit):
                    if tree.identify_region(4, y) in {"cell", "tree"}:
                        result = y
                        break
            except Exception:
                pass
            try:
                tree._v760_body_top = result
            except Exception:
                pass
            return result

        def draw_separators(tree: Any) -> None:
            try:
                tree._v760_separator_after = None
                if not _exists(tree) or not tree.winfo_ismapped():
                    return
                visible = _displayed_columns(tree)
                width = max(1, int(tree.winfo_width()))
                height = max(1, int(tree.winfo_height()))
                top = max(0, min(body_top(tree), height))
                widths = [max(1, int(original_column(tree, column, "width"))) for column in visible]
                total = max(1, sum(widths))
                try:
                    offset = int(round(float(original_xview(tree)[0]) * total))
                except Exception:
                    offset = 0

                boundaries: list[int] = []
                cursor = 0
                for column_width in widths[:-1]:
                    cursor += column_width
                    x = cursor - offset
                    if 0 < x < width:
                        boundaries.append(x)

                lines = list(getattr(tree, "_v760_separator_widgets", ()) or ())
                while len(lines) < len(boundaries):
                    line = M.tk.Frame(
                        tree,
                        background=separator_color(tree),
                        borderwidth=0,
                        highlightthickness=0,
                        takefocus=0,
                    )
                    lines.append(line)
                colour = separator_color(tree)
                for index, line in enumerate(lines):
                    if index >= len(boundaries):
                        line.place_forget()
                        continue
                    line.configure(background=colour)
                    line.place(
                        x=boundaries[index] - 1,
                        y=top,
                        width=1,
                        height=max(1, height - top),
                    )
                    line.lift()
                tree._v760_separator_widgets = lines
                tree._v760_separator_count = len(boundaries)
            except Exception:
                pass

        def schedule_separators(tree: Any, delay: int = 20) -> None:
            if not _exists(tree):
                return
            previous = getattr(tree, "_v760_separator_after", None)
            if previous is not None:
                try:
                    tree.after_cancel(previous)
                except Exception:
                    pass
            try:
                tree._v760_separator_after = tree.after(
                    max(0, int(delay)), lambda current=tree: draw_separators(current)
                )
            except Exception:
                pass

        def _fallback_column_token(tree: Any, column: Any) -> Any:
            """Resolve a dynamic symbolic column through its stable numeric position."""
            target = str(column)
            columns = _all_columns(tree)
            if target in columns:
                return f"#{columns.index(target) + 1}"
            return column


        def _original_heading_call(
            tree: Any, column: Any, option: Any = None, **kwargs: Any
        ):
            try:
                return original_heading(tree, column, option, **kwargs)
            except Exception:
                fallback = _fallback_column_token(tree, column)
                if str(fallback) == str(column):
                    raise
                return original_heading(tree, fallback, option, **kwargs)


        def _original_column_call(
            tree: Any, column: Any, option: Any = None, **kwargs: Any
        ):
            try:
                return original_column(tree, column, option, **kwargs)
            except Exception:
                fallback = _fallback_column_token(tree, column)
                if str(fallback) == str(column):
                    raise
                return original_column(tree, fallback, option, **kwargs)


        def sync_heading_anchors(tree: Any) -> None:
            for column in _all_columns(tree):
                try:
                    anchor = _normalize_anchor(
                        _original_column_call(tree, column, "anchor")
                    )
                    _original_heading_call(tree, column, anchor=anchor)
                except Exception:
                    pass


        def install_tree_polish(tree: Any) -> None:
            if not _exists(tree):
                return
            first_install = not getattr(tree, "_v760_table_polish", False)
            if first_install:
                tree._v760_table_polish = True
                for sequence in (
                    "<Configure>",
                    "<Map>",
                    "<B1-Motion>",
                    "<ButtonRelease-1>",
                ):
                    tree.bind(
                        sequence,
                        lambda _event, current=tree: schedule_separators(current),
                        add="+",
                    )
            sync_heading_anchors(tree)
            schedule_separators(tree, 0)
            if first_install:
                schedule_separators(tree, 90)


        def tree_init(self: Any, *args: Any, **kwargs: Any):
            original_init(self, *args, **kwargs)
            try:
                self.after_idle(lambda current=self: install_tree_polish(current))
            except Exception:
                pass


        def tree_heading(self: Any, column: Any, option: Any = None, **kwargs: Any):
            # Some older layers retain the original ttk method and can reset
            # a heading after composition. The data column is authoritative.
            if option == "anchor" and not kwargs:
                anchor = _original_column_call(self, column, "anchor")
                try:
                    _original_heading_call(
                        self, column, anchor=_normalize_anchor(anchor)
                    )
                except Exception:
                    pass
                return anchor

            mutating = bool(kwargs)
            if mutating:
                try:
                    kwargs["anchor"] = _normalize_anchor(
                        _original_column_call(self, column, "anchor")
                    )
                except Exception:
                    pass
            result = _original_heading_call(self, column, option, **kwargs)
            if mutating:
                schedule_separators(self)
            return result

        def tree_column(self: Any, column: Any, option: Any = None, **kwargs: Any):
            mutating = bool(kwargs)
            result = _original_column_call(self, column, option, **kwargs)
            if mutating:
                try:
                    _original_heading_call(
                        self,
                        column,
                        anchor=_normalize_anchor(
                            _original_column_call(self, column, "anchor")
                        ),
                    )
                except Exception:
                    pass
                schedule_separators(self)
            return result


        def tree_configure(self: Any, cnf: Any = None, **kwargs: Any):
            result = original_configure(self, cnf, **kwargs)
            if cnf is not None or kwargs:
                try:
                    sync_heading_anchors(self)
                    schedule_separators(self)
                except Exception:
                    pass
            return result

        def tree_xview(self: Any, *args: Any):
            result = original_xview(self, *args)
            if args:
                schedule_separators(self, 0)
            return result

        Treeview.__init__ = tree_init
        Treeview.heading = tree_heading
        Treeview.column = tree_column
        Treeview.configure = tree_configure
        Treeview.config = tree_configure
        Treeview.xview = tree_xview
        Treeview._turto_v760_table_polish_class = True
        Treeview._turto_v760_original_heading = original_heading
        Treeview._turto_v760_original_column = original_column
        M.install_v760_tree_polish = install_tree_polish
        M.draw_v760_tree_separators = draw_separators
        M.schedule_v760_tree_separators = schedule_separators
    else:
        install_tree_polish = getattr(M, "install_v760_tree_polish", lambda _tree: None)
        schedule_separators = getattr(M, "schedule_v760_tree_separators", lambda _tree, _delay=0: None)

    for api_name in (
        "save_persistent_tree_layout",
        "install_persistent_tree_layout",
        "open_tree_columns_dialog",
    ):
        previous = getattr(M, api_name, None)
        if not callable(previous) or getattr(previous, "_turto_v760_wrapped", False):
            continue

        def make_layout_wrapper(function: Callable[..., Any]):
            def wrapped(tree: Any, *args: Any, **kwargs: Any):
                result = function(tree, *args, **kwargs)
                try:
                    install_tree_polish(tree)
                    schedule_separators(tree, 80)
                except Exception:
                    pass
                return result

            wrapped._turto_v760_wrapped = True
            return wrapped

        setattr(M, api_name, make_layout_wrapper(previous))

    # ------------------------------------------------------------------
    # Shared UI helpers.
    # ------------------------------------------------------------------
    def active_user(app: Any) -> str:
        try:
            return _text(app.active_user.get(), "Výchozí")
        except Exception:
            try:
                return _text(M.get_setting("active_user", ""), "Výchozí")
            except Exception:
                return "Výchozí"

    def find_toolbar(app: Any, page_key: str, marker: str) -> Any:
        page = getattr(app, "tabs", {}).get(page_key)
        if not _exists(page):
            return None
        for child in page.winfo_children():
            texts: list[str] = []
            for widget in _walk(child):
                try:
                    if widget.winfo_class().endswith(("Button", "Checkbutton")):
                        texts.append(_text(widget.cget("text")))
                except Exception:
                    pass
            if any(marker.casefold() in value.casefold() for value in texts):
                return child
        return None

    def title_row(page: Any) -> Any:
        if not _exists(page):
            return None
        for child in page.winfo_children():
            for widget in _walk(child):
                try:
                    if (
                        widget.winfo_class().endswith("Label")
                        and _text(widget.cget("style")) == "Title.TLabel"
                    ):
                        return child
                except Exception:
                    pass
        return page.winfo_children()[0] if page.winfo_children() else None

    def promote_accent_button(app: Any, page_key: str, needle: str) -> None:
        stored = getattr(app, f"_v760_{page_key}_title_action", None)
        if _exists(stored):
            return
        page = getattr(app, "tabs", {}).get(page_key)
        if not _exists(page):
            return
        row = title_row(page)
        if not _exists(row):
            return
        original = None
        for widget in _walk(page):
            try:
                if not widget.winfo_class().endswith("Button"):
                    continue
                if needle.casefold() not in _text(widget.cget("text")).casefold():
                    continue
                if widget.master is row and getattr(widget, "_v760_title_action", False):
                    return
                original = widget
                break
            except Exception:
                continue
        if not _exists(original):
            return
        label = _text(original.cget("text"), needle)
        try:
            manager = original.winfo_manager()
            if manager == "pack":
                original.pack_forget()
            elif manager == "grid":
                original.grid_remove()
            elif manager == "place":
                original.place_forget()
        except Exception:
            pass
        promoted = M.ttk.Button(
            row,
            text=label,
            style="Accent.TButton",
            command=lambda button=original: button.invoke() if _exists(button) else None,
        )
        promoted._v760_title_action = True
        promoted.pack(side="right", anchor="n", pady=(2, 0))
        setattr(app, f"_v760_{page_key}_title_action", promoted)
        setattr(app, f"_v760_{page_key}_original_action", original)

    def repack_navigation(app: Any) -> None:
        nav = getattr(app, "nav", {}) or {}
        if not all(key in nav for key in ("people", "companies", "tasks")):
            return
        parent = nav["people"].master
        order: list[str] = []
        for widget in parent.pack_slaves():
            key = next((name for name, button in nav.items() if button is widget), None)
            if key and key not in order:
                order.append(key)
        for key in nav:
            if key not in order:
                order.append(key)
        current_order = tuple(order)
        order = [key for key in order if key not in {"companies", "tasks"}]
        people_index = order.index("people") if "people" in order else len(order)
        order.insert(people_index + 1, "companies")
        order.insert(people_index + 2, "tasks")
        if tuple(order) == current_order:
            app._v760_nav_order = tuple(order)
            return
        info: dict[str, dict[str, Any]] = {}
        for key in order:
            button = nav.get(key)
            if not _exists(button):
                continue
            try:
                data = dict(button.pack_info())
                data.pop("in", None)
                info[key] = data
                button.pack_forget()
            except Exception:
                pass
        for key in order:
            button = nav.get(key)
            if not _exists(button):
                continue
            try:
                button.pack(**info.get(key, {"side": "left", "padx": 2, "pady": (0, 2)}))
            except Exception:
                button.pack(side="left", padx=2, pady=(0, 2))
        app._v760_nav_order = tuple(order)

    # Poslední pohyb is displayed in Czech format but sorted as a real date.
    previous_sort_tree = getattr(M.App, "sort_tree", None)
    if callable(previous_sort_tree):
        def sort_tree(self: Any, tree: Any, column: str):
            if column != LAST_ACTIVITY_COLUMN:
                return previous_sort_tree(self, tree, column)
            descending = bool(getattr(tree, "_sort_state", {}).get(column, False))
            try:
                index = _all_columns(tree).index(column)
            except ValueError:
                return None
            dated: list[tuple[datetime, str]] = []
            empty: list[str] = []
            for iid in tree.get_children(""):
                values = tree.item(iid, "values") or ()
                value = values[index] if index < len(values) else ""
                parsed = _parse_activity_datetime(value)
                if parsed is None:
                    empty.append(str(iid))
                else:
                    dated.append((parsed, str(iid)))
            dated.sort(key=lambda pair: pair[0], reverse=descending)
            ordered = [iid for _stamp, iid in dated] + empty
            for position, iid in enumerate(ordered):
                tree.move(iid, "", position)
            tree._sort_state[column] = not descending
            tree._active_sort = (column, descending)
            for current in _all_columns(tree):
                label = current
                if current == column:
                    label += " ▼" if descending else " ▲"
                tree.heading(
                    current,
                    text=label,
                    command=lambda selected=current, current_tree=tree: self.sort_tree(
                        current_tree, selected
                    ),
                )
            schedule_separators(tree, 0)
            return None

        M.App.sort_tree = sort_tree

    # ------------------------------------------------------------------
    # Project/Akce archive + last activity.
    # ------------------------------------------------------------------
    def add_project_activity_column(app: Any) -> None:
        tree = getattr(app, "project_tree", None)
        if not _exists(tree):
            return
        columns = _all_columns(tree)
        if LAST_ACTIVITY_COLUMN not in columns:
            visible_before = _displayed_columns(tree)
            columns.append(LAST_ACTIVITY_COLUMN)
            tree.configure(columns=tuple(columns))
            tree.heading(
                LAST_ACTIVITY_COLUMN,
                text=LAST_ACTIVITY_COLUMN,
                command=lambda current=tree: app.sort_tree(current, LAST_ACTIVITY_COLUMN),
            )
            tree.column(
                LAST_ACTIVITY_COLUMN,
                width=150,
                minwidth=105,
                stretch=False,
                anchor="w",
            )
            try:
                defaults = dict(getattr(tree, "_v700_default_widths", {}) or {})
                defaults[LAST_ACTIVITY_COLUMN] = 150
                tree._v700_default_widths = defaults
                design = dict(getattr(tree, "_turto_design_widths", {}) or {})
                design[LAST_ACTIVITY_COLUMN] = 150
                tree._turto_design_widths = design
            except Exception:
                pass
            if LAST_ACTIVITY_COLUMN not in visible_before:
                tree.configure(displaycolumns=tuple(visible_before + [LAST_ACTIVITY_COLUMN]))
            saver = getattr(M, "save_persistent_tree_layout", None)
            if callable(saver):
                try:
                    saver(tree)
                except Exception:
                    pass
        # Old 7.5 layouts do not know this additive column yet.
        visible_now = _displayed_columns(tree)
        if LAST_ACTIVITY_COLUMN not in visible_now:
            tree.configure(
                displaycolumns=tuple(visible_now + [LAST_ACTIVITY_COLUMN])
            )
        install_tree_polish(tree)

    def refresh_projects(self: Any) -> None:
        tree = getattr(self, "project_tree", None)
        if not _exists(tree):
            return
        add_project_activity_column(self)
        query = _text(getattr(self, "project_q", None).get() if hasattr(self, "project_q") else "").casefold()
        show_archived = _truthy(
            self.project_show_archived.get()
            if hasattr(self, "project_show_archived")
            else False
        )
        for iid in tree.get_children(""):
            tree.delete(iid)
        with M.db() as con:
            activity_union = _project_activity_union(con)
            action_columns = _table_columns(con, "actions")
            active_extra = (
                " AND COALESCE(a.archived,0)=0" if "archived" in action_columns else ""
            )
            rows = con.execute(
                f"""WITH activity(project_id,activity_at) AS (
                         {activity_union}
                     ), activity_max AS (
                         SELECT project_id,MAX(activity_at) last_activity
                         FROM activity
                         WHERE project_id IS NOT NULL AND activity_at IS NOT NULL
                         GROUP BY project_id
                     ), opportunity_count AS (
                         SELECT a.project_id,
                                COUNT(a.id) opportunity_count,
                                SUM(CASE WHEN a.status NOT IN ('Hotovo','Zrušeno')
                                          {active_extra}
                                         THEN 1 ELSE 0 END) active_count
                         FROM actions a
                         WHERE a.project_id IS NOT NULL
                         GROUP BY a.project_id
                     )
                     SELECT p.*,
                            COALESCE(o.opportunity_count,0) opportunity_count,
                            COALESCE(o.active_count,0) active_count,
                            x.last_activity
                     FROM projects p
                     LEFT JOIN opportunity_count o ON o.project_id=p.id
                     LEFT JOIN activity_max x ON x.project_id=p.id
                     WHERE (?=1 OR COALESCE(p.active,1)=1)
                     ORDER BY COALESCE(p.active,1) DESC,
                              CASE WHEN x.last_activity IS NULL THEN 1 ELSE 0 END,
                              x.last_activity DESC,
                              p.id DESC""",
                (1 if show_archived else 0,),
            ).fetchall()
        for row in rows:
            haystack = " ".join(
                _text(_row_value(row, name))
                for name in ("name", "address", "investor", "general_contractor")
            ).casefold()
            if query and query not in haystack:
                continue
            active = int(_row_value(row, "active", 1) or 0) == 1
            tag = (
                "status_cancel"
                if not active
                else ("status_active" if int(_row_value(row, "active_count", 0) or 0) > 0 else "status_done")
            )
            tree.insert(
                "",
                "end",
                iid=f"p{int(_row_value(row, 'id', 0))}",
                values=(
                    _text(_row_value(row, "name")),
                    _text(_row_value(row, "address")),
                    _text(_row_value(row, "investor")),
                    _text(_row_value(row, "general_contractor")),
                    M.fmt_date(_row_value(row, "start_date")),
                    M.fmt_date(_row_value(row, "end_date")),
                    int(_row_value(row, "opportunity_count", 0) or 0),
                    _format_activity(_row_value(row, "last_activity")),
                ),
                tags=(tag,),
            )
        reapply = getattr(self, "reapply_tree_sort", None)
        if callable(reapply):
            reapply(tree)
        schedule_separators(tree, 0)

    def archive_projects(app: Any, archived: bool) -> None:
        tree = getattr(app, "project_tree", None)
        ids = _selected_ids(tree, "p")
        if not ids:
            return M.messagebox.showinfo(
                "Akce", "Vyberte alespoň jednu Akci.", parent=app
            )
        with M.db() as con:
            marks = ",".join("?" for _ in ids)
            rows = con.execute(
                f"SELECT id,name,active FROM projects WHERE id IN ({marks})",
                ids,
            ).fetchall()
        candidates = [
            row
            for row in rows
            if (int(_row_value(row, "active", 1) or 0) == 1) == bool(archived)
        ]
        if not candidates:
            return M.messagebox.showinfo(
                "Akce",
                "Vybrané Akce už jsou v požadovaném stavu.",
                parent=app,
            )
        verb = "Archivovat" if archived else "Obnovit"
        if archived and not M.messagebox.askyesno(
            "Akce",
            f"Archivovat {len(candidates)} vybraných Akcí?\n\n"
            "Příležitosti, Poptávky, nabídky ani historie se nesmažou.",
            parent=app,
        ):
            return
        user = active_user(app)
        ids_to_change = [int(_row_value(row, "id")) for row in candidates]
        with M.db() as con:
            marks = ",".join("?" for _ in ids_to_change)
            if archived:
                con.execute(
                    f"""UPDATE projects
                           SET active=0,archived_at=CURRENT_TIMESTAMP,archived_by=?,
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id IN ({marks})""",
                    tuple([user] + ids_to_change),
                )
            else:
                con.execute(
                    f"""UPDATE projects
                           SET active=1,archived_at='',archived_by='',
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id IN ({marks})""",
                    tuple(ids_to_change),
                )
            linked = con.execute(
                f"SELECT id,project_id FROM actions WHERE project_id IN ({marks})",
                tuple(ids_to_change),
            ).fetchall()
        names = {int(_row_value(row, "id")): _text(_row_value(row, "name")) for row in candidates}
        for action in linked:
            project_id = int(_row_value(action, "project_id", 0) or 0)
            try:
                M.log_history(
                    int(_row_value(action, "id", 0)),
                    "project_archive" if archived else "project_restore",
                    f"{verb} Akci",
                    names.get(project_id, "Akce"),
                    user_name=user,
                )
            except Exception:
                pass
        refresh_projects(app)
        marker = getattr(app, "_turto_mark_dirty", None)
        if callable(marker):
            marker({"projects", "actions", "dash"})

    def selected_project_archived(app: Any) -> bool:
        ids = _selected_ids(getattr(app, "project_tree", None), "p")
        if len(ids) != 1:
            return False
        with M.db() as con:
            row = con.execute("SELECT active FROM projects WHERE id=?", (ids[0],)).fetchone()
        return bool(row and int(_row_value(row, "active", 1) or 0) == 0)

    def install_project_context(app: Any) -> None:
        tree = getattr(app, "project_tree", None)
        if not _exists(tree) or getattr(tree, "_v760_context_owner", None) == "projects":
            return
        header = M.tk.Menu(tree, tearoff=False)
        header.add_command(
            label="Nastavit zobrazené sloupce…",
            command=lambda: getattr(M, "open_tree_columns_dialog", lambda _tree: None)(tree),
        )
        row = M.tk.Menu(tree, tearoff=False)
        row.add_command(label="Otevřít / upravit", command=app.edit_project)
        row.add_command(label="Sloučit s jinou Akcí", command=app.merge_project)
        row.add_separator()
        row.add_command(label="Archivovat vybrané", command=lambda: archive_projects(app, True))
        row.add_command(label="Obnovit vybrané", command=lambda: archive_projects(app, False))
        row.add_separator()
        row.add_command(label="Smazat", command=app.delete_project)

        def popup(event: Any):
            region = tree.identify_region(event.x, event.y)
            menu = header if region in {"heading", "separator"} else row
            if menu is row:
                iid = _text(tree.identify_row(event.y))
                if not iid:
                    return "break"
                if iid not in tree.selection():
                    tree.selection_set(iid)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
            return "break"

        tree.bind("<Button-3>", popup, add=False)
        tree._v760_header_menu = header
        tree._v760_row_menu = row
        tree._v760_context_owner = "projects"

    def configure_project_workspace(app: Any) -> None:
        tree = getattr(app, "project_tree", None)
        if not _exists(tree):
            return
        add_project_activity_column(app)
        tree.configure(selectmode="extended")
        toolbar = find_toolbar(app, "projects", "Sloučit s jinou Akcí")
        if _exists(toolbar) and not getattr(toolbar, "_v760_archive_layout", False):
            toolbar._v760_archive_layout = True
            controls: dict[str, Any] = {}
            for widget in toolbar.winfo_children():
                try:
                    label = _text(widget.cget("text")).casefold()
                except Exception:
                    continue
                if "editovat" in label:
                    controls["edit"] = widget
                elif "sloučit" in label:
                    controls["merge"] = widget
                elif "smazat" in label:
                    controls["delete"] = widget
                try:
                    widget.pack_forget()
                except Exception:
                    pass
            app.project_show_archived = getattr(
                app, "project_show_archived", M.tk.BooleanVar(value=False)
            )
            checkbox = M.ttk.Checkbutton(
                toolbar,
                text="Zobrazit archivované",
                variable=app.project_show_archived,
                command=app.refresh_projects,
            )
            archive_button = M.ttk.Button(
                toolbar,
                text="📦 Archivovat vybrané",
                style="Toolbar.TButton",
                command=lambda: archive_projects(app, True),
            )
            restore_button = M.ttk.Button(
                toolbar,
                text="↩ Obnovit vybrané",
                style="Toolbar.TButton",
                command=lambda: archive_projects(app, False),
            )
            checkbox.pack(side="left")
            for key in ("delete",):
                if _exists(controls.get(key)):
                    controls[key].pack(side="right", padx=5)
            restore_button.pack(side="right", padx=5)
            archive_button.pack(side="right", padx=5)
            for key in ("merge", "edit"):
                if _exists(controls.get(key)):
                    controls[key].pack(side="right", padx=5)
            app._v760_project_archive_controls = (
                checkbox,
                archive_button,
                restore_button,
            )
        install_project_context(app)

    previous_edit_project = getattr(M.App, "edit_project", None)
    if callable(previous_edit_project):
        def edit_project(self: Any, *args: Any, **kwargs: Any):
            if selected_project_archived(self):
                return M.messagebox.showinfo(
                    "Akce",
                    "Archivovanou Akci nejdřív obnovte.",
                    parent=self,
                )
            return previous_edit_project(self, *args, **kwargs)

        M.App.edit_project = edit_project

    previous_merge_project = getattr(M.App, "merge_project", None)
    if callable(previous_merge_project):
        def merge_project(self: Any, *args: Any, **kwargs: Any):
            if selected_project_archived(self):
                return M.messagebox.showinfo(
                    "Akce",
                    "Archivovanou Akci nejdřív obnovte.",
                    parent=self,
                )
            return previous_merge_project(self, *args, **kwargs)

        M.App.merge_project = merge_project

    M.App.refresh_projects = refresh_projects

    previous_build_projects = getattr(M.App, "build_projects", None)
    if callable(previous_build_projects):
        def build_projects(self: Any, *args: Any, **kwargs: Any):
            result = previous_build_projects(self, *args, **kwargs)
            configure_project_workspace(self)
            return result

        M.App.build_projects = build_projects

    # Project edits update the timestamp used by Poslední pohyb.
    ProjectDialog = getattr(M, "ProjectDialog", None)
    if ProjectDialog is not None and not getattr(ProjectDialog, "_turto_v760_timestamp", False):
        previous_project_ok = ProjectDialog.ok

        def project_ok(self: Any, *args: Any, **kwargs: Any):
            name = ""
            try:
                name = _text(self.vars["name"].get())
            except Exception:
                pass
            known_id = getattr(self, "pid", None)
            result = previous_project_ok(self, *args, **kwargs)
            if not getattr(self, "result", None):
                return result
            try:
                project_id = known_id
                if not project_id and name:
                    with M.db() as con:
                        row = con.execute(
                            """SELECT id FROM projects
                               WHERE lower(trim(name))=lower(trim(?))
                               ORDER BY id DESC LIMIT 1""",
                            (name,),
                        ).fetchone()
                    project_id = int(_row_value(row, "id", 0) or 0) if row else None
                if project_id:
                    with M.db() as con:
                        con.execute(
                            "UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (int(project_id),),
                        )
            except Exception:
                pass
            return result

        ProjectDialog.ok = project_ok
        ProjectDialog._turto_v760_timestamp = True

    # Preserve a link to an archived project while editing an existing
    # opportunity and reuse an archived project instead of creating a duplicate.
    ActionDialog = getattr(M, "ActionDialog", None)
    if ActionDialog is not None and not getattr(ActionDialog, "_turto_v760_archived_project", False):
        previous_action_init = ActionDialog.__init__
        previous_action_ok = ActionDialog.ok

        def action_init(self: Any, *args: Any, **kwargs: Any):
            result = previous_action_init(self, *args, **kwargs)
            self._v760_original_project = None
            try:
                aid = getattr(self, "aid", None)
                if aid:
                    with M.db() as con:
                        row = con.execute(
                            """SELECT p.id,p.name,p.active
                               FROM actions a LEFT JOIN projects p ON p.id=a.project_id
                               WHERE a.id=?""",
                            (int(aid),),
                        ).fetchone()
                    if row:
                        self._v760_original_project = dict(row)
            except Exception:
                pass
            return result

        def action_ok(self: Any, *args: Any, **kwargs: Any):
            try:
                requested_name = _text(self.name.get())
            except Exception:
                requested_name = ""
            temporary_id = None
            keep_archived = False
            try:
                if requested_name:
                    with M.db() as con:
                        inactive = con.execute(
                            """SELECT id,name,active FROM projects
                               WHERE lower(trim(name))=lower(trim(?))
                                 AND COALESCE(active,1)=0
                               ORDER BY id LIMIT 1""",
                            (requested_name,),
                        ).fetchone()
                        if inactive:
                            temporary_id = int(_row_value(inactive, "id", 0) or 0)
                            original = getattr(self, "_v760_original_project", None) or {}
                            keep_archived = bool(
                                getattr(self, "aid", None)
                                and int(original.get("id") or 0) == temporary_id
                                and int(original.get("active") or 0) == 0
                            )
                            con.execute(
                                """UPDATE projects
                                   SET active=1,archived_at='',archived_by='',
                                       updated_at=CURRENT_TIMESTAMP
                                   WHERE id=?""",
                                (temporary_id,),
                            )
            except Exception:
                temporary_id = None
                keep_archived = False
            succeeded = False
            try:
                result = previous_action_ok(self, *args, **kwargs)
                succeeded = bool(getattr(self, "result", None))
                return result
            finally:
                if temporary_id and (keep_archived or not succeeded):
                    try:
                        with M.db() as con:
                            con.execute(
                                """UPDATE projects
                                   SET active=0,archived_at=CASE WHEN trim(coalesce(archived_at,''))=''
                                                               THEN CURRENT_TIMESTAMP ELSE archived_at END,
                                       updated_at=CURRENT_TIMESTAMP
                                   WHERE id=?""",
                                (temporary_id,),
                            )
                    except Exception:
                        pass

        ActionDialog.__init__ = action_init
        ActionDialog.ok = action_ok
        ActionDialog._turto_v760_archived_project = True

    # ------------------------------------------------------------------
    # Task archive parity.
    # ------------------------------------------------------------------
    def refresh_tasks(self: Any) -> None:
        tree = getattr(self, "task_tree", None)
        if not _exists(tree):
            return
        query = _text(getattr(self, "task_q", None).get() if hasattr(self, "task_q") else "").casefold()
        show_done = _truthy(
            self.task_show_done.get() if hasattr(self, "task_show_done") else False
        )
        show_archived = _truthy(
            self.task_show_archived.get()
            if hasattr(self, "task_show_archived")
            else False
        )
        user_filter = _text(
            self.task_user_filter.get()
            if hasattr(self, "task_user_filter")
            else "Všichni",
            "Všichni",
        )
        for iid in tree.get_children(""):
            tree.delete(iid)
        with M.db() as con:
            rows = con.execute(
                """SELECT t.*,a.name action_name
                   FROM tasks t JOIN actions a ON a.id=t.action_id
                   WHERE (?=1 OR COALESCE(t.archived,0)=0)
                     AND (?=1 OR t.done=0 OR COALESCE(t.archived,0)=1)
                   ORDER BY COALESCE(t.archived,0),t.done,t.due_date,t.id""",
                (1 if show_archived else 0, 1 if show_done else 0),
            ).fetchall()
        today = date.today()
        for row in rows:
            haystack = " ".join(
                _text(_row_value(row, name))
                for name in ("action_name", "text", "note", "assigned_user")
            ).casefold()
            if query and query not in haystack:
                continue
            if (
                user_filter != "Všichni"
                and user_filter.casefold()
                not in _text(_row_value(row, "assigned_user")).casefold()
            ):
                continue
            archived = int(_row_value(row, "archived", 0) or 0) == 1
            done = int(_row_value(row, "done", 0) or 0) == 1
            if archived:
                state, tag = "Archivováno", "status_cancel"
            elif done:
                state, tag = "Hotovo", "status_done"
            else:
                try:
                    due = datetime.strptime(
                        _text(_row_value(row, "due_date")), "%Y-%m-%d"
                    ).date()
                    difference = (due - today).days
                except Exception:
                    difference = 999999
                if difference < 0:
                    state, tag = "Po termínu", "status_late"
                elif difference == 0:
                    state, tag = "Dnes", "status_soon"
                elif difference <= 3:
                    state, tag = "Brzy", "status_wait"
                else:
                    state, tag = "Čeká", "status_active"
            tree.insert(
                "",
                "end",
                iid=f"t{int(_row_value(row, 'id', 0))}",
                values=(
                    state,
                    _text(_row_value(row, "assigned_user")),
                    M.fmt_date(_row_value(row, "due_date")),
                    _text(_row_value(row, "action_name")),
                    _text(_row_value(row, "text")),
                    _text(_row_value(row, "created_by")),
                    _text(_row_value(row, "done_by")),
                ),
                tags=(tag,),
            )
        reapply = getattr(self, "reapply_tree_sort", None)
        if callable(reapply):
            reapply(tree)
        schedule_separators(tree, 0)

    def archive_tasks(app: Any, archived: bool) -> None:
        tree = getattr(app, "task_tree", None)
        ids = _selected_ids(tree, "t")
        if not ids:
            return M.messagebox.showinfo(
                "Úkoly", "Vyberte alespoň jeden úkol.", parent=app
            )
        with M.db() as con:
            marks = ",".join("?" for _ in ids)
            rows = con.execute(
                f"SELECT id,action_id,text,archived FROM tasks WHERE id IN ({marks})",
                ids,
            ).fetchall()
        candidates = [
            row
            for row in rows
            if (int(_row_value(row, "archived", 0) or 0) == 0) == bool(archived)
        ]
        if not candidates:
            return M.messagebox.showinfo(
                "Úkoly", "Vybrané úkoly už jsou v požadovaném stavu.", parent=app
            )
        if archived and not M.messagebox.askyesno(
            "Úkoly",
            f"Archivovat {len(candidates)} vybraných úkolů?",
            parent=app,
        ):
            return
        user = active_user(app)
        ids_to_change = [int(_row_value(row, "id", 0)) for row in candidates]
        with M.db() as con:
            marks = ",".join("?" for _ in ids_to_change)
            if archived:
                con.execute(
                    f"""UPDATE tasks
                           SET archived=1,archived_at=CURRENT_TIMESTAMP,archived_by=?,
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id IN ({marks})""",
                    tuple([user] + ids_to_change),
                )
            else:
                con.execute(
                    f"""UPDATE tasks
                           SET archived=0,archived_at='',archived_by='',
                               updated_at=CURRENT_TIMESTAMP
                         WHERE id IN ({marks})""",
                    tuple(ids_to_change),
                )
        for row in candidates:
            try:
                M.log_history(
                    _row_value(row, "action_id"),
                    "task_archive" if archived else "task_restore",
                    "Archivoval připomínku" if archived else "Obnovil připomínku",
                    _text(_row_value(row, "text")),
                    user_name=user,
                )
            except Exception:
                pass
        app.refresh_after_task_change()

    def selected_task_archived(app: Any) -> bool:
        ids = _selected_ids(getattr(app, "task_tree", None), "t")
        if len(ids) != 1:
            return False
        with M.db() as con:
            row = con.execute("SELECT archived FROM tasks WHERE id=?", (ids[0],)).fetchone()
        return bool(row and int(_row_value(row, "archived", 0) or 0) == 1)

    def install_task_context(app: Any) -> None:
        tree = getattr(app, "task_tree", None)
        if not _exists(tree) or getattr(tree, "_v760_context_owner", None) == "tasks":
            return
        header = M.tk.Menu(tree, tearoff=False)
        header.add_command(
            label="Nastavit zobrazené sloupce…",
            command=lambda: getattr(M, "open_tree_columns_dialog", lambda _tree: None)(tree),
        )
        row = M.tk.Menu(tree, tearoff=False)
        row.add_command(label="Otevřít / upravit", command=app.edit_task)
        row.add_command(label="Hotovo / znovu otevřít", command=app.complete_task)
        row.add_separator()
        row.add_command(label="Archivovat vybrané", command=lambda: archive_tasks(app, True))
        row.add_command(label="Obnovit vybrané", command=lambda: archive_tasks(app, False))
        row.add_separator()
        row.add_command(label="Smazat", command=app.delete_task)

        def popup(event: Any):
            region = tree.identify_region(event.x, event.y)
            menu = header if region in {"heading", "separator"} else row
            if menu is row:
                iid = _text(tree.identify_row(event.y))
                if not iid:
                    return "break"
                if iid not in tree.selection():
                    tree.selection_set(iid)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass
            return "break"

        tree.bind("<Button-3>", popup, add=False)
        tree._v760_header_menu = header
        tree._v760_row_menu = row
        tree._v760_context_owner = "tasks"

    def configure_task_workspace(app: Any) -> None:
        tree = getattr(app, "task_tree", None)
        if not _exists(tree):
            return
        tree.configure(selectmode="extended")
        toolbar = find_toolbar(app, "tasks", "Hotovo")
        if _exists(toolbar) and not getattr(toolbar, "_v760_archive_layout", False):
            toolbar._v760_archive_layout = True
            controls: dict[str, Any] = {}
            existing_show_done = None
            for widget in toolbar.winfo_children():
                try:
                    label = _text(widget.cget("text")).casefold()
                except Exception:
                    continue
                if "zobrazit hotové" in label:
                    existing_show_done = widget
                elif "editovat" in label:
                    controls["edit"] = widget
                elif "hotovo" in label:
                    controls["done"] = widget
                elif "smazat" in label:
                    controls["delete"] = widget
                try:
                    widget.pack_forget()
                except Exception:
                    pass
            app.task_show_archived = getattr(
                app, "task_show_archived", M.tk.BooleanVar(value=False)
            )
            checkbox = M.ttk.Checkbutton(
                toolbar,
                text="Zobrazit archivované",
                variable=app.task_show_archived,
                command=app.refresh_tasks,
            )
            archive_button = M.ttk.Button(
                toolbar,
                text="📦 Archivovat vybrané",
                style="Toolbar.TButton",
                command=lambda: archive_tasks(app, True),
            )
            restore_button = M.ttk.Button(
                toolbar,
                text="↩ Obnovit vybrané",
                style="Toolbar.TButton",
                command=lambda: archive_tasks(app, False),
            )
            checkbox.pack(side="left")
            if _exists(existing_show_done):
                existing_show_done.pack(side="left", padx=(12, 0))
            if _exists(controls.get("delete")):
                controls["delete"].pack(side="right", padx=5)
            restore_button.pack(side="right", padx=5)
            archive_button.pack(side="right", padx=5)
            for key in ("done", "edit"):
                if _exists(controls.get(key)):
                    controls[key].pack(side="right", padx=5)
            app._v760_task_archive_controls = (
                checkbox,
                archive_button,
                restore_button,
            )
        install_task_context(app)
        install_tree_polish(tree)

    previous_edit_task = getattr(M.App, "edit_task", None)
    if callable(previous_edit_task):
        def edit_task(self: Any, *args: Any, **kwargs: Any):
            if selected_task_archived(self):
                return M.messagebox.showinfo(
                    "Úkol",
                    "Archivovaný úkol nejdřív obnovte.",
                    parent=self,
                )
            return previous_edit_task(self, *args, **kwargs)

        M.App.edit_task = edit_task

    previous_complete_task = getattr(M.App, "complete_task", None)
    if callable(previous_complete_task):
        def complete_task(self: Any, *args: Any, **kwargs: Any):
            if selected_task_archived(self):
                return M.messagebox.showinfo(
                    "Úkol",
                    "Archivovaný úkol nejdřív obnovte.",
                    parent=self,
                )
            return previous_complete_task(self, *args, **kwargs)

        M.App.complete_task = complete_task

    previous_complete_task_by_id = getattr(M.App, "complete_task_by_id", None)
    if callable(previous_complete_task_by_id):
        def complete_task_by_id(self: Any, task_id: int, *args: Any, **kwargs: Any):
            with M.db() as con:
                row = con.execute("SELECT archived FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row and int(_row_value(row, "archived", 0) or 0) == 1:
                return M.messagebox.showinfo(
                    "Úkol",
                    "Archivovaný úkol nejdřív obnovte.",
                    parent=self,
                )
            return previous_complete_task_by_id(self, task_id, *args, **kwargs)

        M.App.complete_task_by_id = complete_task_by_id

    M.App.refresh_tasks = refresh_tasks

    previous_build_tasks = getattr(M.App, "build_tasks", None)
    if callable(previous_build_tasks):
        def build_tasks(self: Any, *args: Any, **kwargs: Any):
            result = previous_build_tasks(self, *args, **kwargs)
            configure_task_workspace(self)
            return result

        M.App.build_tasks = build_tasks

    # Task edits also move their parent project.
    TaskDialog = getattr(M, "TaskDialog", None)
    if TaskDialog is not None and not getattr(TaskDialog, "_turto_v760_timestamp", False):
        previous_task_ok = TaskDialog.ok

        def task_ok(self: Any, *args: Any, **kwargs: Any):
            known_id = getattr(self, "task_id", None)
            result = previous_task_ok(self, *args, **kwargs)
            if not getattr(self, "result", None):
                return result
            try:
                if known_id:
                    with M.db() as con:
                        con.execute(
                            "UPDATE tasks SET updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (int(known_id),),
                        )
            except Exception:
                pass
            return result

        TaskDialog.ok = task_ok
        TaskDialog._turto_v760_timestamp = True

    # ------------------------------------------------------------------
    # Leaner queries and resize refreshes.
    # ------------------------------------------------------------------
    def action_rows(self: Any):
        active_only = bool(getattr(self, "_v760_action_rows_active_only", False))
        action_filter = "WHERE COALESCE(a.archived,0)=0" if active_only else ""
        with M.db() as con:
            return con.execute(
                f"""WITH waiting AS (
                       SELECT r.action_id,COUNT(*) waiting
                       FROM requests r
                       LEFT JOIN companies rc ON rc.id=r.company_id
                       WHERE r.action_id IS NOT NULL
                         AND trim(coalesce(r.received_date,''))=''
                         AND coalesce(r.no_response,0)=0
                         AND coalesce(r.archived,0)=0
                         AND NOT (
                           lower(trim(coalesce(rc.short_name,'')))='mivo'
                           OR lower(trim(coalesce(rc.official_name,'')))='mivo'
                           OR lower(trim(coalesce(rc.official_name,''))) LIKE 'mivo %'
                           OR lower(trim(coalesce(rc.official_name,''))) LIKE 'mivo,%'
                           OR lower(trim(coalesce(rc.official_name,''))) LIKE 'mivo.%'
                         )
                       GROUP BY r.action_id
                   )
                   SELECT a.*,c.official_name company,s.name salesperson,
                          COALESCE(w.waiting,0) waiting
                   FROM actions a
                   LEFT JOIN companies c ON c.id=a.company_id
                   LEFT JOIN salespeople s ON s.id=a.salesperson_id
                   LEFT JOIN waiting w ON w.action_id=a.id
                   {action_filter}
                   ORDER BY CASE WHEN trim(coalesce(a.created_date,''))='' THEN 1 ELSE 0 END,
                            a.created_date DESC,a.id DESC"""
            ).fetchall()

    M.App.action_rows = action_rows

    def install_resize_guard(app: Any, tree: Any, method_name: str, token: str) -> None:
        if not _exists(tree) or getattr(tree, f"_v760_{token}_resize_guard", False):
            return
        setattr(tree, f"_v760_{token}_resize_guard", True)
        tag = f"V760ResizeGuard_{token}_{id(tree)}"
        tags = list(tree.bindtags())
        if tag not in tags:
            tags.insert(0, tag)
            tree.bindtags(tuple(tags))

        def mark(_event: Any = None) -> None:
            tree._v760_resize_until = time.monotonic() + 0.14

        tree.bind_class(tag, "<Configure>", mark, add="+")

    for method_name, tree_name, token in (
        ("refresh_requests", "request_tree", "requests"),
        ("refresh_mivo_requests", "mivo_tree", "mivo"),
    ):
        previous = getattr(M.App, method_name, None)
        if not callable(previous):
            continue

        def make_debounced_refresh(
            function: Callable[..., Any],
            attribute: str,
            name: str,
        ):
            def wrapped(self: Any, *args: Any, **kwargs: Any):
                tree = getattr(self, attribute, None)
                if _exists(tree) and time.monotonic() < float(
                    getattr(tree, "_v760_resize_until", 0.0) or 0.0
                ):
                    after_name = f"_v760_{name}_resize_after"
                    previous_after = getattr(self, after_name, None)
                    if previous_after is not None:
                        try:
                            self.after_cancel(previous_after)
                        except Exception:
                            pass

                    def run() -> None:
                        setattr(self, after_name, None)
                        try:
                            tree._v760_resize_until = 0.0
                        except Exception:
                            pass
                        function(self, *args, **kwargs)

                    try:
                        setattr(self, after_name, self.after(145, run))
                    except Exception:
                        pass
                    return None
                return function(self, *args, **kwargs)

            return wrapped

        setattr(M.App, method_name, make_debounced_refresh(previous, tree_name, token))

    # Aggregate SQL counts replace Python row loops and ignore archived work.
    def notification_count(self: Any) -> int:
        horizon = (date.today().toordinal() + 3)
        horizon_date = date.fromordinal(horizon).isoformat()
        today = date.today().isoformat()
        with M.db() as con:
            tasks = con.execute(
                """SELECT COUNT(*) FROM tasks
                   WHERE done=0 AND COALESCE(archived,0)=0
                     AND trim(coalesce(due_date,''))<>'' AND due_date<=?""",
                (horizon_date,),
            ).fetchone()[0]
            action_columns = _table_columns(con, "actions")
            action_archive = "AND COALESCE(archived,0)=0" if "archived" in action_columns else ""
            actions = con.execute(
                f"""SELECT COUNT(*) FROM actions
                    WHERE trim(coalesce(deadline,''))<>''
                      AND status NOT IN ('Hotovo','Zrušeno')
                      {action_archive}
                      AND deadline<=?""",
                (horizon_date,),
            ).fetchone()[0]
            requests = con.execute(
                """SELECT COUNT(*) FROM requests
                   WHERE trim(coalesce(received_date,''))=''
                     AND coalesce(no_response,0)=0
                     AND coalesce(archived,0)=0
                     AND trim(coalesce(asked_date,''))<>''
                     AND julianday(?) - julianday(asked_date) >= 3""",
                (today,),
            ).fetchone()[0]
        return int(tasks or 0) + int(actions or 0) + int(requests or 0)

    M.App.notification_count = notification_count

    # Notification centre uses the same archive contract as the main pages.
    NotificationCenter = getattr(M, "NotificationCenter", None)
    if NotificationCenter is not None:
        def notification_refresh(self: Any) -> None:
            for iid in self.tree.get_children(""):
                self.tree.delete(iid)
            today = date.today()
            horizon = date.fromordinal(today.toordinal() + 3)
            with M.db() as con:
                tasks = con.execute(
                    """SELECT t.*,a.name action_name FROM tasks t
                       JOIN actions a ON a.id=t.action_id
                       WHERE t.done=0 AND COALESCE(t.archived,0)=0
                         AND (trim(coalesce(t.assigned_user,''))='' OR t.assigned_user=?)
                         AND t.due_date<=?
                       ORDER BY t.due_date,t.id""",
                    (M.get_setting("active_user", ""), horizon.isoformat()),
                ).fetchall()
                actions = con.execute(
                    """SELECT id,name,deadline,status FROM actions
                       WHERE trim(coalesce(deadline,''))<>''
                         AND status NOT IN ('Hotovo','Zrušeno')
                         AND COALESCE(archived,0)=0
                         AND deadline<=?
                       ORDER BY deadline""",
                    (horizon.isoformat(),),
                ).fetchall()
                requests = con.execute(
                    """SELECT r.id,r.action_id,r.asked_date,r.item,
                              a.name action_name,c.official_name company
                       FROM requests r
                       LEFT JOIN actions a ON a.id=r.action_id
                       LEFT JOIN companies c ON c.id=r.company_id
                       WHERE trim(coalesce(r.received_date,''))=''
                         AND coalesce(r.no_response,0)=0
                         AND coalesce(r.archived,0)=0
                         AND trim(coalesce(r.asked_date,''))<>''
                         AND julianday(?) - julianday(r.asked_date) >= 3
                       ORDER BY r.asked_date""",
                    (today.isoformat(),),
                ).fetchall()
            for row in tasks:
                try:
                    due = datetime.strptime(_text(_row_value(row, "due_date")), "%Y-%m-%d").date()
                except Exception:
                    continue
                tag = "over" if due < today else ("today" if due == today else "soon")
                when = "Po termínu" if due < today else ("Dnes" if due == today else M.fmt_date(_row_value(row, "due_date")))
                self.tree.insert(
                    "",
                    "end",
                    iid=f"t{int(_row_value(row, 'id', 0))}",
                    values=(when, "Úkol", _text(_row_value(row, "action_name")), _text(_row_value(row, "text"))),
                    tags=(tag,),
                )
            for row in actions:
                try:
                    due = datetime.strptime(_text(_row_value(row, "deadline")), "%Y-%m-%d").date()
                except Exception:
                    continue
                tag = "over" if due < today else ("today" if due == today else "soon")
                when = "Po termínu" if due < today else ("Dnes" if due == today else M.fmt_date(_row_value(row, "deadline")))
                self.tree.insert(
                    "",
                    "end",
                    iid=f"a{int(_row_value(row, 'id', 0))}",
                    values=(when, "Deadline Akce", _text(_row_value(row, "name")), "Termín Akce"),
                    tags=(tag,),
                )
            for row in requests:
                try:
                    asked = datetime.strptime(_text(_row_value(row, "asked_date")), "%Y-%m-%d").date()
                    age = (today - asked).days
                except Exception:
                    continue
                self.tree.insert(
                    "",
                    "end",
                    iid=f"r{int(_row_value(row, 'id', 0))}",
                    values=(
                        f"čeká {age} dní",
                        "Poptávka",
                        _text(_row_value(row, "action_name"), "—"),
                        f"{_text(_row_value(row, 'company'), '—')} · {_text(_row_value(row, 'item'), '—')}",
                    ),
                    tags=("wait",),
                )

        NotificationCenter.refresh = notification_refresh

    # Dashboard/header reuse the existing renderers.  A short-lived query flag
    # keeps archived opportunities out without drawing the same dashboard twice;
    # only the legacy task/focus fragments are corrected afterwards.
    previous_refresh_dash = getattr(M.App, "refresh_dash", None)
    if callable(previous_refresh_dash):
        def refresh_dash(self: Any, *args: Any, **kwargs: Any):
            old_flag = bool(getattr(self, "_v760_action_rows_active_only", False))
            self._v760_action_rows_active_only = True
            try:
                result = previous_refresh_dash(self, *args, **kwargs)
            finally:
                self._v760_action_rows_active_only = old_flag
            try:
                if _exists(getattr(self, "dash_tasks_tree", None)):
                    for iid in self.dash_tasks_tree.get_children(""):
                        self.dash_tasks_tree.delete(iid)
                    user = M.get_setting("active_user", "")
                    with M.db() as con:
                        tasks = con.execute(
                            """SELECT t.id,t.due_date,t.text,a.name action_name
                               FROM tasks t LEFT JOIN actions a ON a.id=t.action_id
                               WHERE t.done=0 AND COALESCE(t.archived,0)=0
                                 AND (trim(coalesce(t.assigned_user,''))='' OR t.assigned_user=?)
                               ORDER BY t.due_date,t.id LIMIT 7""",
                            (user,),
                        ).fetchall()
                    for row in tasks:
                        self.dash_tasks_tree.insert(
                            "",
                            "end",
                            values=(
                                M.fmt_date(_row_value(row, "due_date")),
                                f"{_text(_row_value(row, 'text'))} · {_text(_row_value(row, 'action_name'))}",
                            ),
                        )
                if hasattr(self, "crm_focus"):
                    old_flag = bool(getattr(self, "_v760_action_rows_active_only", False))
                    self._v760_action_rows_active_only = True
                    try:
                        rows = self.action_rows()
                    finally:
                        self._v760_action_rows_active_only = old_flag
                    late_count = sum(self.late(row) for row in rows)
                    soon_count = sum(self.soon(row) for row in rows)
                    with M.db() as con:
                        old_requests, due_tasks = con.execute(
                            """SELECT
                                 (SELECT COUNT(*) FROM requests
                                   WHERE trim(coalesce(received_date,''))=''
                                     AND coalesce(no_response,0)=0
                                     AND coalesce(archived,0)=0
                                     AND trim(coalesce(asked_date,''))<>''
                                     AND julianday(?) - julianday(asked_date) >= 7),
                                 (SELECT COUNT(*) FROM tasks
                                   WHERE done=0 AND COALESCE(archived,0)=0 AND due_date<=?)""",
                            (date.today().isoformat(), date.today().isoformat()),
                        ).fetchone()
                    parts: list[str] = []
                    if late_count:
                        parts.append(f"{late_count} příležitostí po termínu")
                    if soon_count:
                        parts.append(f"{soon_count} deadline do 2 dnů")
                    if old_requests:
                        parts.append(f"{old_requests} poptávek bez odezvy 7+ dní")
                    if due_tasks:
                        parts.append(f"{due_tasks} úkolů k řešení")
                    self.crm_focus.set("  •  ".join(parts) if parts else "Dnes není žádná kritická položka.")
            except Exception:
                pass
            return result

        M.App.refresh_dash = refresh_dash

    previous_refresh_header = getattr(M.App, "refresh_header", None)
    if callable(previous_refresh_header):
        def refresh_header(self: Any, *args: Any, **kwargs: Any):
            old_flag = bool(getattr(self, "_v760_action_rows_active_only", False))
            self._v760_action_rows_active_only = True
            try:
                result = previous_refresh_header(self, *args, **kwargs)
                rows = self.action_rows()
            finally:
                self._v760_action_rows_active_only = old_flag
            try:
                late = sum(self.late(row) for row in rows)
                with M.db() as con:
                    waiting, tasks_today = con.execute(
                        """SELECT
                             (SELECT COUNT(*) FROM requests
                               WHERE trim(coalesce(received_date,''))=''
                                 AND coalesce(no_response,0)=0
                                 AND coalesce(archived,0)=0),
                             (SELECT COUNT(*) FROM tasks
                               WHERE done=0 AND COALESCE(archived,0)=0 AND due_date<=?)""",
                        (date.today().isoformat(),),
                    ).fetchone()
                self.today_summary.configure(
                    text=f"Dnes: {late} hořící termíny · {waiting} poptávek čeká na odpověď · {tasks_today} úkolů k řešení"
                )
            except Exception:
                pass
            return result

        M.App.refresh_header = refresh_header

    # ------------------------------------------------------------------
    # Build integration: navigation order, promoted gold actions and guards.
    # ------------------------------------------------------------------
    for method_name, page_key, needle in (
        ("build_offers", "offers", "Zpracovat nabídku"),
        ("build_price_lists", "pricelists", "Importovat Ceník"),
        ("build_issued_offers", "issued_offers", "Nová nabídka"),
    ):
        previous = getattr(M.App, method_name, None)
        if not callable(previous):
            continue

        def make_commercial_builder(
            function: Callable[..., Any],
            key: str,
            text: str,
        ):
            def wrapped(self: Any, *args: Any, **kwargs: Any):
                result = function(self, *args, **kwargs)
                promote_accent_button(self, key, text)
                return result

            return wrapped

        setattr(M.App, method_name, make_commercial_builder(previous, page_key, needle))

    previous_build = getattr(M.App, "build", None)
    if callable(previous_build):
        def build(self: Any, *args: Any, **kwargs: Any):
            result = previous_build(self, *args, **kwargs)
            repack_navigation(self)
            configure_project_workspace(self)
            configure_task_workspace(self)
            promote_accent_button(self, "offers", "Zpracovat nabídku")
            promote_accent_button(self, "pricelists", "Importovat Ceník")
            promote_accent_button(self, "issued_offers", "Nová nabídka")
            for widget in _walk(self):
                if isinstance(widget, Treeview):
                    install_tree_polish(widget)
            install_resize_guard(self, getattr(self, "request_tree", None), "refresh_requests", "requests")
            install_resize_guard(self, getattr(self, "mivo_tree", None), "refresh_mivo_requests", "mivo")
            return result

        M.App.build = build

    previous_apply_theme = getattr(M.App, "apply_theme", None)
    if callable(previous_apply_theme):
        def apply_theme(self: Any, *args: Any, **kwargs: Any):
            result = previous_apply_theme(self, *args, **kwargs)
            try:
                for widget in _walk(self):
                    if isinstance(widget, Treeview):
                        widget._v760_body_top = None
                        install_tree_polish(widget)
            except Exception:
                pass
            return result

        M.App.apply_theme = apply_theme

    previous_app_init = M.App.__init__

    def app_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_app_init(self, *args, **kwargs)

        def finalize() -> None:
            if not _exists(self):
                return
            repack_navigation(self)
            configure_project_workspace(self)
            configure_task_workspace(self)
            promote_accent_button(self, "offers", "Zpracovat nabídku")
            promote_accent_button(self, "pricelists", "Importovat Ceník")
            promote_accent_button(self, "issued_offers", "Nová nabídka")
            install_resize_guard(self, getattr(self, "request_tree", None), "refresh_requests", "requests")
            install_resize_guard(self, getattr(self, "mivo_tree", None), "refresh_mivo_requests", "mivo")
            for widget in _walk(self):
                if isinstance(widget, Treeview):
                    install_tree_polish(widget)

        for delay in (0, 260, 1200):
            try:
                self.after(delay, finalize)
            except Exception:
                pass
        return result

    M.App.__init__ = app_init

    M.V760_PERFORMANCE_CHANGES = {
        "action_waiting_query": "grouped_cte",
        "request_resize_refresh": "debounced",
        "mivo_resize_refresh": "debounced",
        "notification_counts": "aggregate_sql",
        "project_activity": "single_union_query",
        "table_separators": "one_widget_per_visible_boundary",
    }
    M._turto_v760_table_activity_performance_installed = True


__all__ = ["apply", "LAST_ACTIVITY_COLUMN"]
