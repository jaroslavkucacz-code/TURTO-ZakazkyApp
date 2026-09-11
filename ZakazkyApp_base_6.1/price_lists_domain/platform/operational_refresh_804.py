"""Measured high-volume refresh optimizations for TURTO CRM 8.0.4.

The Windows scaled profile showed that database time is already small. The
remaining avoidable costs were repeated pure date formatting, duplicate date
sorts, a second full Příležitosti deadline pass, and repeated generic row/text
helpers inside the high-volume Úkoly fill. This late layer removes only those
duplicates; it does not change filters, status rules, columns, colors or business
records.
"""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.operational_refresh_804"
ATTENTION_TAG = "v770_deadline_attention"
ATTENTION_TASK_STATES = frozenset(("po termínu", "dnes", "brzy"))
ATTENTION_TASK_TAGS = ("status_late", "status_soon", "status_wait")


def _closure_value(function: Any, name: str, default: Any = None) -> Any:
    try:
        cells = function.__closure__ or ()
        return dict(zip(function.__code__.co_freevars, (c.cell_contents for c in cells))).get(
            name, default
        )
    except Exception:
        return default


def _fast_iso_display(value: Any):
    """Return dd.mm.yyyy for the canonical DB date shape, else None."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    if value[4] != "-" or value[7] != "-":
        return None
    digits = value[:4] + value[5:7] + value[8:10]
    if not digits.isdigit():
        return None
    return f"{value[8:10]}.{value[5:7]}.{value[:4]}"


def _install_cached_date_format(M: Any) -> bool:
    current = getattr(M, "fmt_date", None)
    if not callable(current) or getattr(current, "_turto_804_cached", False):
        return bool(callable(current))

    @lru_cache(maxsize=4096)
    def cached(value: Any):
        fast = _fast_iso_display(value)
        return fast if fast is not None else current(value)

    def fmt_date(value: Any):
        try:
            return cached(value)
        except TypeError:
            # Preserve the historical fallback for unusual unhashable caller data.
            return current(value)

    fmt_date._turto_804_cached = True
    fmt_date._turto_original = current
    fmt_date.cache_info = cached.cache_info
    fmt_date.cache_clear = cached.cache_clear
    M.fmt_date = fmt_date
    return True


@lru_cache(maxsize=1024)
def _iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _install_fast_action_deadlines(M: Any) -> bool:
    App = getattr(M, "App", None)
    if App is None:
        return False

    previous_soon = getattr(App, "soon", None)
    if callable(previous_soon) and not getattr(previous_soon, "_turto_804_fast", False):
        def soon(self: Any, row: Any) -> bool:
            try:
                raw = str(row["deadline"] or "").strip()
                if not raw or self.effective(row) in ("Hotovo", "Zrušeno"):
                    return False
                difference = (_iso_date(raw) - date.today()).days
                return 0 <= difference <= 2
            except Exception:
                return False

        soon._turto_804_fast = True
        soon._turto_original = previous_soon
        App.soon = soon

    def attention(self: Any, rows: Any) -> None:
        tree = getattr(self, "action_tree", None)
        if tree is None:
            return
        try:
            tree.tag_configure(ATTENTION_TAG, font=("Calibri", 10, "bold"))
        except Exception:
            pass

        # Rows have just been recreated by refresh_actions, so none carries the
        # attention tag yet. Ignore ordinary rows entirely and touch only the
        # late/soon subset. The old v770 callback read/wrote Deadline and tags
        # for every row merely to remove visual markers that are no longer
        # inserted by the current refresh owner.
        for item in rows or ():
            if not item or len(item) < 3 or not (bool(item[1]) or bool(item[2])):
                continue
            iid = item[0]
            try:
                tags = tuple(tree.item(iid, "tags") or ())
                if ATTENTION_TAG not in tags:
                    tree.item(iid, tags=(*tags, ATTENTION_TAG))
            except Exception:
                pass

    attention._turto_804_sparse_attention = True
    App._refresh_action_deadline_highlights = attention
    return True


def _sort_action_default(tree: Any) -> None:
    """Restore the historical default only after an actual manual sort."""
    try:
        columns = tuple(tree.cget("columns") or ())
        column = next(
            (name for name in ("Přijato", "Datum přijetí", "Přijetí") if name in columns),
            None,
        )
        if not column:
            return

        @lru_cache(maxsize=512)
        def key(value: str):
            text = str(value or "").strip()
            for marker in ("⚠️", "⚠", "▲", "△"):
                text = text.replace(marker, "")
            text = " ".join(text.split())
            for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
                try:
                    return datetime.strptime(text, fmt)
                except Exception:
                    pass
            return datetime.min

        rows = list(tree.get_children(""))
        rows.sort(key=lambda iid: key(str(tree.set(iid, column) or "")), reverse=True)
        for position, iid in enumerate(rows):
            tree.move(iid, "", position)
        tree._sort_state = {}
        tree._active_sort = None
    except Exception:
        pass


def _install_action_native_default_order(M: Any) -> bool:
    """Trust action_rows SQL order unless a manual sort must be reset."""
    try:
        import v644_default_date_sort as v644
    except Exception:
        return False
    if "actions" not in getattr(v644, "PAGE_SORTS", {}):
        return True

    v644.PAGE_SORTS.pop("actions", None)

    previous = getattr(M.App, "refresh_actions", None)
    if not callable(previous) or getattr(previous, "_turto_804_native_default", False):
        return bool(callable(previous))

    def refresh_actions(self: Any, *args: Any, **kwargs: Any):
        tree = getattr(self, "action_tree", None)
        had_manual_sort = bool(getattr(tree, "_active_sort", None)) if tree is not None else False
        result = previous(self, *args, **kwargs)
        if had_manual_sort and tree is not None:
            try:
                self.after_idle(lambda current=tree: _sort_action_default(current))
            except Exception:
                _sort_action_default(tree)
        return result

    refresh_actions._turto_804_native_default = True
    refresh_actions._turto_original = previous
    M.App.refresh_actions = refresh_actions
    return True


def _install_request_mivo_native_default_order() -> bool:
    """Trust worksets SQL order for ordinary Poptávky/MIVO refreshes."""
    try:
        import v644_default_date_sort as v644
    except Exception:
        return False
    sorts = getattr(v644, "PAGE_SORTS", None)
    if not isinstance(sorts, dict):
        return False
    sorts.pop("requests", None)
    sorts.pop("mivo", None)
    return "requests" not in sorts and "mivo" not in sorts


def _configure_task_attention_tags(tree: Any) -> bool:
    """Reuse the task status tags themselves for the historical bold attention."""
    if tree is None:
        return False
    try:
        for tag in ATTENTION_TASK_TAGS:
            tree.tag_configure(tag, font=("Calibri", 10, "bold"))
        tree._turto_804_task_attention_status_tags = True
        return True
    except Exception:
        return False


def _task_text(value: Any) -> str:
    return str(value or "").strip()


def _task_truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "ne", "no", "off"}
    return bool(value)


def _task_due_difference(raw: str, today: date, cache: dict[str, int]) -> int:
    """Match v760's strict YYYY-MM-DD parser with a refresh-local cache."""
    if raw in cache:
        return cache[raw]
    difference = 999999
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            difference = (date.fromisoformat(raw) - today).days
        except Exception:
            pass
    cache[raw] = difference
    return difference


def _refresh_tasks_fast(M: Any, app: Any, schedule_separators: Any = None) -> None:
    """Equivalent v760 task fill without tens of thousands of generic helpers."""
    tree = getattr(app, "task_tree", None)
    if tree is None:
        return

    query = _task_text(app.task_q.get() if hasattr(app, "task_q") else "").casefold()
    show_done = _task_truthy(app.task_show_done.get() if hasattr(app, "task_show_done") else False)
    show_archived = _task_truthy(
        app.task_show_archived.get() if hasattr(app, "task_show_archived") else False
    )
    user_filter = _task_text(
        app.task_user_filter.get() if hasattr(app, "task_user_filter") else "Všichni",
    ) or "Všichni"

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
    due_cache: dict[str, int] = {}
    user_filter_cf = user_filter.casefold()
    filter_user = user_filter != "Všichni"

    for row in rows:
        # sqlite.Row is guaranteed by the CRM DB owner here. Read each field once
        # instead of routing every value through _row_value + _text repeatedly.
        action_name = _task_text(row["action_name"])
        text = _task_text(row["text"])
        note = _task_text(row["note"])
        assigned_user = _task_text(row["assigned_user"])

        if query:
            haystack = f"{action_name} {text} {note} {assigned_user}".casefold()
            if query not in haystack:
                continue
        if filter_user and user_filter_cf not in assigned_user.casefold():
            continue

        archived = int(row["archived"] or 0) == 1
        done = int(row["done"] or 0) == 1
        if archived:
            state, tag = "Archivováno", "status_cancel"
        elif done:
            state, tag = "Hotovo", "status_done"
        else:
            due_text = _task_text(row["due_date"])
            difference = _task_due_difference(due_text, today, due_cache)
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
            iid=f"t{int(row['id'] or 0)}",
            values=(
                state,
                assigned_user,
                M.fmt_date(row["due_date"]),
                action_name,
                text,
                _task_text(row["created_by"]),
                _task_text(row["done_by"]),
            ),
            tags=(tag,),
        )

    reapply = getattr(app, "reapply_tree_sort", None)
    if callable(reapply):
        reapply(tree)
    if callable(schedule_separators):
        schedule_separators(tree, 0)


def _install_inline_task_attention(M: Any) -> bool:
    """Preserve v760 semantics while removing per-row helper/proxy overhead."""
    current = getattr(M.App, "refresh_tasks", None)
    if not callable(current) or getattr(current, "_turto_804_inline_attention", False):
        return bool(callable(current))

    # Validate the expected historical chain before replacing it. This keeps the
    # optimization fail-closed if a future version changes the task owner.
    v770_refresh = _closure_value(current, "function")
    if not callable(v770_refresh) or not getattr(v770_refresh, "_turto_v770_deadline_bold", False):
        return False
    base_refresh = _closure_value(v770_refresh, "previous_refresh_tasks")
    if not callable(base_refresh):
        return False

    try:
        from price_lists_domain.platform import ui_cleanup_793
        workspace_sync = getattr(ui_cleanup_793, "_schedule_workspace_sync", None)
    except Exception:
        workspace_sync = None
    try:
        import v760_table_activity_performance as v760
        schedule_separators = getattr(v760, "schedule_separators", None)
    except Exception:
        schedule_separators = None

    def refresh_tasks(self: Any, *args: Any, **kwargs: Any):
        tree = getattr(self, "task_tree", None)
        _configure_task_attention_tags(tree)
        result = _refresh_tasks_fast(M, self, schedule_separators)
        if callable(workspace_sync):
            try:
                workspace_sync(M, self, "tasks")
            except Exception:
                pass
        return result

    refresh_tasks._turto_804_inline_attention = True
    refresh_tasks._turto_context_refresh = True
    refresh_tasks._turto_original = current
    refresh_tasks._turto_v760_base = base_refresh
    refresh_tasks._turto_task_attention_mode = "status-tag-fonts-fast-row-path"
    M.App.refresh_tasks = refresh_tasks
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_operational_refresh_804", False):
        return
    M._turto_operational_refresh_804 = True

    cached_dates = _install_cached_date_format(M)
    action_deadlines = _install_fast_action_deadlines(M)
    action_order = _install_action_native_default_order(M)
    request_mivo_order = _install_request_mivo_native_default_order()
    task_attention = _install_inline_task_attention(M)

    M.OPERATIONAL_REFRESH_804 = {
        "owner": POLICY_OWNER,
        "fmt_date": "lru-4096-iso-fast-path" if cached_dates else "unchanged",
        "action_soon": "date.fromisoformat-lru-1024" if action_deadlines else "unchanged",
        "action_attention": "sparse-tag-only" if action_deadlines else "unchanged",
        "action_default_order": "trust-sql-unless-manual-sort" if action_order else "unchanged",
        "request_mivo_default_order": "trust-sql-lazy-manual-reset" if request_mivo_order else "unchanged",
        "task_attention": "status-tag-fonts-fast-row-path" if task_attention else "unchanged",
        "database_queries_changed": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "ATTENTION_TAG",
    "ATTENTION_TASK_STATES",
    "ATTENTION_TASK_TAGS",
    "_closure_value",
    "_fast_iso_display",
    "_install_cached_date_format",
    "_install_fast_action_deadlines",
    "_sort_action_default",
    "_install_action_native_default_order",
    "_install_request_mivo_native_default_order",
    "_configure_task_attention_tags",
    "_task_text",
    "_task_truthy",
    "_task_due_difference",
    "_refresh_tasks_fast",
    "_install_inline_task_attention",
]
