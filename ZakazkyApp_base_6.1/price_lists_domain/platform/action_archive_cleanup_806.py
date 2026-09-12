"""Single-pass archive visibility for TURTO CRM Příležitosti (8.0.6).

The original archive owner filtered archived Actions in ``action_rows``.  A later
v760 grouped-query optimization replaced that method and exposed an internal
``_v760_action_rows_active_only`` flag for dashboards, while v750 compensated by
running a second archive-ID query and walking the freshly filled Treeview after
every Příležitosti refresh.

This late compatibility cleanup restores the original contract without changing
business data or archive controls:
- ordinary Příležitosti refreshes set the existing v760 query flag when
  ``Zobrazit archivované`` is off;
- when the checkbox is on, archived rows remain in the primary query and the
  existing archive tag owner marks them ``status_cancel``;
- the known v750 post-refresh DB + Treeview visibility pass is bypassed;
- dashboard/header callers that already force ``_v760_action_rows_active_only``
  remain active-only regardless of the checkbox.

Installation is deliberately fail-closed against the exact current wrapper
chain.  If a future version changes ownership, this module leaves the historical
path untouched instead of guessing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.action_archive_cleanup_806"


def _closure_value(function: Any, name: str, default: Any = None) -> Any:
    try:
        cells = function.__closure__ or ()
        names = function.__code__.co_freevars
        return dict(zip(names, (cell.cell_contents for cell in cells))).get(name, default)
    except Exception:
        return default


def _origin(function: Any) -> tuple[str, str]:
    code = getattr(function, "__code__", None)
    if code is None:
        return "", ""
    filename = Path(str(getattr(code, "co_filename", ""))).name
    return filename, str(getattr(code, "co_name", ""))


def _show_archived(app: Any) -> bool:
    variable = getattr(app, "action_show_archived", None)
    if variable is None:
        return False
    try:
        return bool(variable.get())
    except Exception:
        return False


def _resolve_refresh_chain(M: Any):
    """Return the exact v750 base refresh underneath ui_cleanup, else None."""
    current = getattr(M.App, "refresh_actions", None)
    if not callable(current) or not getattr(current, "_turto_context_refresh", False):
        return None

    workspace_key = _closure_value(current, "workspace_key")
    v750_refresh = _closure_value(current, "function")
    if workspace_key != "actions" or not callable(v750_refresh):
        return None
    if _origin(v750_refresh) != ("v750_context_filters_offer_format.py", "refresh_actions"):
        return None

    postpass = _closure_value(v750_refresh, "apply_action_archive_visibility")
    base_refresh = _closure_value(v750_refresh, "previous_refresh_actions")
    if not callable(postpass) or not callable(base_refresh):
        return None
    if _origin(postpass) != (
        "v750_context_filters_offer_format.py",
        "apply_action_archive_visibility",
    ):
        return None
    return current, base_refresh, postpass


def _install_primary_query_filter(M: Any, rows_function: Any) -> Any:
    def action_rows(self: Any, *args: Any, **kwargs: Any):
        had_flag = hasattr(self, "_v760_action_rows_active_only")
        previous_flag = bool(getattr(self, "_v760_action_rows_active_only", False))
        if not _show_archived(self):
            self._v760_action_rows_active_only = True
        try:
            return rows_function(self, *args, **kwargs)
        finally:
            try:
                if had_flag:
                    self._v760_action_rows_active_only = previous_flag
                else:
                    delattr(self, "_v760_action_rows_active_only")
            except Exception:
                pass

    action_rows._turto_806_action_archive_primary_query = True
    action_rows._turto_original = rows_function
    M.App.action_rows = action_rows
    return action_rows


def apply(M: Any) -> None:
    if getattr(M, "_turto_action_archive_cleanup_806", False):
        return

    rows_function = getattr(M.App, "action_rows", None)
    chain = _resolve_refresh_chain(M)
    if (
        not callable(rows_function)
        or _origin(rows_function) != ("v760_table_activity_performance.py", "action_rows")
        or chain is None
    ):
        M.ACTION_ARCHIVE_CLEANUP_806 = {
            "owner": POLICY_OWNER,
            "installed": False,
            "reason": "unexpected-wrapper-chain",
            "database_rows_rewritten": False,
        }
        return

    current_refresh, base_refresh, _historical_postpass = chain
    try:
        from price_lists_domain.platform import ui_cleanup_793
        workspace_sync = getattr(ui_cleanup_793, "_schedule_workspace_sync", None)
    except Exception:
        workspace_sync = None
    if not callable(workspace_sync):
        M.ACTION_ARCHIVE_CLEANUP_806 = {
            "owner": POLICY_OWNER,
            "installed": False,
            "reason": "missing-ui-cleanup-sync",
            "database_rows_rewritten": False,
        }
        return

    _install_primary_query_filter(M, rows_function)

    def refresh_actions(self: Any, *args: Any, **kwargs: Any):
        result = base_refresh(self, *args, **kwargs)
        try:
            workspace_sync(M, self, "actions")
        except Exception:
            pass
        return result

    # Preserve the marker expected by later context-aware wrappers while
    # deliberately removing only v750's archive visibility post-pass.
    refresh_actions._turto_context_refresh = True
    refresh_actions._turto_806_action_archive_single_pass = True
    refresh_actions._turto_original = current_refresh
    refresh_actions._turto_v750_base = base_refresh
    M.App.refresh_actions = refresh_actions

    M._turto_action_archive_cleanup_806 = True
    M.ACTION_ARCHIVE_CLEANUP_806 = {
        "owner": POLICY_OWNER,
        "installed": True,
        "visibility_owner": "v760-primary-query",
        "show_archived_source": "action_show_archived",
        "archived_tag_owner": "price_lists_domain.platform.archive",
        "v750_postpass": "retired",
        "dashboard_active_only_flag": "preserved",
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_closure_value",
    "_origin",
    "_show_archived",
    "_resolve_refresh_chain",
]
