"""Batch initial Treeview clears for high-volume TURTO CRM refreshes.

Historical refresh functions delete every old row with one Tk call per item before
repopulating the table.  On large worksets that means thousands of Tcl roundtrips
whose final state is identical to one ``tree.delete(*items)`` call.

This late policy is intentionally narrow and fail-closed.  It wraps only the
measured Příležitosti and Úkoly refresh owners.  Deletes are collected only until
the first insert; that insert flushes the old rows in one native call and all
later delete/insert operations run normally.  The original instance methods are
restored even when the refresh raises.
"""
from __future__ import annotations

from typing import Any, Callable

POLICY_OWNER = "price_lists_domain.platform.tree_clear_804"


def _restore_instance_method(obj: Any, name: str, had_instance: bool, previous: Any) -> None:
    try:
        if had_instance:
            obj.__dict__[name] = previous
        else:
            obj.__dict__.pop(name, None)
    except Exception:
        try:
            setattr(obj, name, previous)
        except Exception:
            pass


def _run_with_batched_initial_clear(
    tree: Any,
    function: Callable[..., Any],
    owner: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    """Collapse the leading per-row delete phase into one native Treeview call."""
    if tree is None:
        return function(owner, *args, **kwargs)

    original_delete = getattr(tree, "delete", None)
    original_insert = getattr(tree, "insert", None)
    if not callable(original_delete) or not callable(original_insert):
        return function(owner, *args, **kwargs)

    had_delete = "delete" in getattr(tree, "__dict__", {})
    had_insert = "insert" in getattr(tree, "__dict__", {})
    previous_delete = getattr(tree, "__dict__", {}).get("delete")
    previous_insert = getattr(tree, "__dict__", {}).get("insert")
    pending: list[Any] = []
    collecting = True
    flushed = False

    def flush() -> None:
        nonlocal collecting, flushed
        if not collecting:
            return
        collecting = False
        if pending:
            original_delete(*pending)
            pending.clear()
        flushed = True

    def delete(*items: Any) -> Any:
        if collecting:
            pending.extend(items)
            return None
        return original_delete(*items)

    def insert(parent: Any, index: Any, iid: Any = None, **options: Any) -> Any:
        flush()
        if iid is None:
            return original_insert(parent, index, **options)
        return original_insert(parent, index, iid=iid, **options)

    try:
        tree.delete = delete
        tree.insert = insert
        return function(owner, *args, **kwargs)
    finally:
        try:
            flush()
        finally:
            _restore_instance_method(tree, "delete", had_delete, previous_delete)
            _restore_instance_method(tree, "insert", had_insert, previous_insert)
            try:
                owner._turto_804_tree_clear_last = {
                    "rows": len(pending),
                    "flushed": bool(flushed),
                }
            except Exception:
                pass


def _install_refresh(M: Any, method_name: str, tree_name: str) -> bool:
    current = getattr(M.App, method_name, None)
    if not callable(current) or getattr(current, "_turto_804_batched_tree_clear", False):
        return bool(callable(current))

    def wrapped(self: Any, *args: Any, **kwargs: Any):
        tree = getattr(self, tree_name, None)
        return _run_with_batched_initial_clear(tree, current, self, args, kwargs)

    wrapped._turto_804_batched_tree_clear = True
    wrapped._turto_original = current
    wrapped._turto_tree_name = tree_name
    setattr(M.App, method_name, wrapped)
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_tree_clear_804", False):
        return
    M._turto_tree_clear_804 = True

    actions = _install_refresh(M, "refresh_actions", "action_tree")
    tasks = _install_refresh(M, "refresh_tasks", "task_tree")

    M.TREE_CLEAR_804 = {
        "owner": POLICY_OWNER,
        "actions": "batch-leading-delete" if actions else "unchanged",
        "tasks": "batch-leading-delete" if tasks else "unchanged",
        "database_queries_changed": False,
        "database_rows_rewritten": False,
        "visual_contract_changed": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_restore_instance_method",
    "_run_with_batched_initial_clear",
    "_install_refresh",
]
