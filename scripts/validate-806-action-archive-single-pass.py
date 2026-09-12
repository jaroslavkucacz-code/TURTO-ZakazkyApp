#!/usr/bin/env python3
"""Real-Tk regression for single-pass Příležitosti archive visibility in 8.0.6."""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import sys
import traceback

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_806_ARCHIVE_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def normalized(sql: str) -> str:
    return " ".join(str(sql or "").upper().split())


def contains_marker(function, marker: str) -> bool:
    pending = [function]
    seen = set()
    while pending:
        current = pending.pop()
        if not inspect.isfunction(current) or id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, marker, False):
            return True
        for cell in current.__closure__ or ():
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if inspect.isfunction(value):
                pending.append(value)
    return False


def clear_action_filters(window) -> None:
    for name in (
        "action_name_filter",
        "action_company_filter",
        "action_status",
        "action_sp",
        "action_received_filter",
        "action_date_filter",
    ):
        variable = getattr(window, name, None)
        if variable is not None:
            try:
                variable.set("")
            except Exception:
                pass


def main() -> None:
    if not os.environ.get("TURTO_CRM_DATA_ROOT"):
        raise AssertionError("isolated TURTO_CRM_DATA_ROOT required")

    import app, data_location, runtime_bootstrap
    data_location.apply_to_app(app)
    app.cleanup_stale_test_session(); app.ensure_schema(); runtime_bootstrap.apply_all(app)
    app.ensure_schema(); app.ensure_test_user(); app.migrate_v41_visual_once()
    app.App.maybe_show_morning_overview = lambda self: None

    policy = getattr(app, "ACTION_ARCHIVE_CLEANUP_806", {}) or {}
    if not policy.get("installed"):
        raise AssertionError(f"Action archive cleanup did not install: {policy!r}")
    if policy.get("v750_postpass") != "retired":
        raise AssertionError(f"Unexpected archive post-pass policy: {policy!r}")
    if not contains_marker(app.App.refresh_actions, "_turto_806_action_archive_single_pass"):
        raise AssertionError("Clean single-pass refresh owner is not in refresh_actions chain")
    if not getattr(app.App.action_rows, "_turto_806_action_archive_primary_query", False):
        raise AssertionError("Primary action_rows archive filter is not installed")

    window = None
    original_db = app.db
    traces: list[str] = []
    ids: dict[str, int] = {}
    try:
        window = app.App()
        clear_action_filters(window)
        variable = getattr(window, "action_show_archived", None)
        if variable is None:
            raise AssertionError("Missing action_show_archived control")

        with original_db() as con:
            active_id = con.execute(
                "INSERT INTO actions(name,created_date,status,archived) VALUES(?,?,?,0)",
                ("806 ACTIVE SENTINEL", "2026-09-12", "Rozpracováno"),
            ).lastrowid
            archived_id = con.execute(
                "INSERT INTO actions(name,created_date,status,archived) VALUES(?,?,?,1)",
                ("806 ARCHIVED SENTINEL", "2026-09-11", "Rozpracováno"),
            ).lastrowid
            con.commit()
        ids = {"active": int(active_id), "archived": int(archived_id)}

        def traced_db():
            con = original_db()
            con.set_trace_callback(lambda sql: traces.append(str(sql)))
            return con
        app.db = traced_db

        variable.set(False)
        traces.clear()
        window.refresh_actions()
        active_iid = f"a{ids['active']}"
        archived_iid = f"a{ids['archived']}"
        if not window.action_tree.exists(active_iid):
            raise AssertionError("Active Příležitost disappeared with archive hidden")
        if window.action_tree.exists(archived_iid):
            raise AssertionError("Archived Příležitost remained visible with archive hidden")
        hidden_sql = [normalized(sql) for sql in traces]
        if not any(
            "FROM ACTIONS A" in sql and "WHERE COALESCE(A.ARCHIVED,0)=0" in sql
            for sql in hidden_sql
        ):
            raise AssertionError("Primary action query did not apply archive visibility filter")
        forbidden = "SELECT ID FROM ACTIONS WHERE COALESCE(ARCHIVED,0)=1"
        if any(forbidden in sql for sql in hidden_sql):
            raise AssertionError("Historical v750 archive-ID post-pass query still executed")

        variable.set(True)
        traces.clear()
        window.refresh_actions()
        if not window.action_tree.exists(active_iid) or not window.action_tree.exists(archived_iid):
            raise AssertionError("Zobrazit archivované did not expose both active and archived rows")
        archived_tags = tuple(window.action_tree.item(archived_iid, "tags") or ())
        if "status_cancel" not in archived_tags:
            raise AssertionError(f"Archived row lost status_cancel tag: {archived_tags!r}")
        shown_sql = [normalized(sql) for sql in traces]
        if any(forbidden in sql for sql in shown_sql):
            raise AssertionError("Historical archive-ID post-pass query executed with archive shown")
        primary_queries = [sql for sql in shown_sql if "FROM ACTIONS A" in sql and "COALESCE(W.WAITING,0) WAITING" in sql]
        if not primary_queries:
            raise AssertionError("Primary action query was not observed with archive shown")
        if any("WHERE COALESCE(A.ARCHIVED,0)=0" in sql for sql in primary_queries):
            raise AssertionError("Archive-visible primary query incorrectly stayed active-only")

        write_result({
            "ok": True,
            "platform": sys.platform,
            "ids": ids,
            "hidden_primary_filter": True,
            "show_archived_visible": True,
            "archived_tags": list(archived_tags),
            "historical_postpass_query_seen": False,
            "policy": policy,
            "database": str(app.DB),
        })
    finally:
        app.db = original_db
        if window is not None:
            try: window.destroy()
            except Exception: pass


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write_result({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        raise
