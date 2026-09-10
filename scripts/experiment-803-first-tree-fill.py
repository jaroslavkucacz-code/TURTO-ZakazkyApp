#!/usr/bin/env python3
"""Measure first Příležitosti fill with the page visible or hidden.

CI/development experiment only. Run each mode in a fresh Python process and an
isolated TURTO_CRM_DATA_ROOT so Tk/widget warm-up does not mix the two cases.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def load_scaled_benchmark():
    path = REPO / "scripts" / "benchmark-803-scaled-tables.py"
    spec = importlib.util.spec_from_file_location("turto_scaled_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "visible").strip().casefold()
    if mode not in {"visible", "hidden"}:
        raise SystemExit("mode must be visible or hidden")

    import data_location
    import app
    import runtime_bootstrap

    benchmark = load_scaled_benchmark()
    data_location.apply_to_app(app)
    app.cleanup_stale_test_session()
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    counts = benchmark.seed_data(app)
    app.App.maybe_show_morning_overview = lambda self: None

    window = None
    callback_errors: list[str] = []
    try:
        window = app.App()

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append(
                "".join(traceback.format_exception(exc_type, exc, tb)).strip()
            )

        window.report_callback_exception = report_callback_exception
        window.update_idletasks()
        page = window.tabs["actions"]
        tree = window.action_tree
        for iid in tree.get_children(""):
            tree.delete(iid)

        if mode == "visible":
            window.show_page("actions")
            window.update_idletasks()
        else:
            # Simulate filling before the first page raise. lazy_refresh.show_page
            # can restore this page with its normal grid geometry afterwards.
            try:
                page.grid_remove()
            except Exception:
                pass
            window.show_page("dash")
            window.update_idletasks()

        refresh_started = time.perf_counter()
        window.refresh_actions()
        refresh_seconds = time.perf_counter() - refresh_started

        idle_started = time.perf_counter()
        window.update_idletasks()
        idle_seconds = time.perf_counter() - idle_started

        reveal_seconds = 0.0
        if mode == "hidden":
            reveal_started = time.perf_counter()
            window.show_page("actions")
            window.update_idletasks()
            reveal_seconds = time.perf_counter() - reveal_started

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))

        payload = {
            "ok": True,
            "mode": mode,
            "seed_counts": counts,
            "rows": len(tree.get_children("")),
            "refresh_seconds": round(refresh_seconds, 6),
            "idle_seconds": round(idle_seconds, 6),
            "reveal_seconds": round(reveal_seconds, 6),
            "total_seconds": round(refresh_seconds + idle_seconds + reveal_seconds, 6),
            "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
            "callback_errors": callback_errors,
        }
        target = str(os.environ.get("TURTO_CRM_FILL_RESULT", "")).strip()
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if target:
            Path(target).write_text(text, encoding="utf-8")
        print(text, end="")
    finally:
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        payload = {
            "ok": False,
            "exception_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        target = str(os.environ.get("TURTO_CRM_FILL_RESULT", "")).strip()
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if target:
            Path(target).write_text(text, encoding="utf-8")
        print(text, end="")
        raise
