#!/usr/bin/env python3
"""Profile the composed high-volume operational refreshes on Windows CI data.

This is development/CI only. It reuses the synthetic data generator from the
8.0.3 scaled benchmark, runs in an isolated TURTO_CRM_DATA_ROOT and records the
repository-side cumulative profile for Příležitosti, Poptávky and Úkoly.
"""
from __future__ import annotations

import cProfile
import importlib.util
import json
import os
from pathlib import Path
import pstats
import sys
import traceback


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def load_scaled_benchmark():
    path = REPO / "scripts" / "benchmark-803-scaled-tables.py"
    spec = importlib.util.spec_from_file_location("turto_scaled_benchmark_804", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def profile_rows(profile: cProfile.Profile, limit: int = 55) -> list[dict]:
    base_text = str(BASE.resolve()).casefold()
    rows = []
    for (filename, lineno, function), values in pstats.Stats(profile).stats.items():
        primitive_calls, total_calls, own_time, cumulative_time, _callers = values
        normalized = str(Path(filename).resolve()).casefold() if filename else ""
        if not normalized.startswith(base_text):
            continue
        rows.append(
            {
                "function": function,
                "file": str(filename),
                "line": int(lineno),
                "primitive_calls": int(primitive_calls),
                "total_calls": int(total_calls),
                "self_seconds": round(float(own_time), 6),
                "cumulative_seconds": round(float(cumulative_time), 6),
            }
        )
    rows.sort(
        key=lambda row: (row["cumulative_seconds"], row["self_seconds"]),
        reverse=True,
    )
    return rows[:limit]


def profile_refresh(window, page: str, method_name: str, tree_name: str) -> dict:
    window.show_page(page)
    window.update_idletasks()
    tree = getattr(window, tree_name)
    profile = cProfile.Profile()
    profile.enable()
    getattr(window, method_name)()
    window.update_idletasks()
    profile.disable()
    return {
        "page": page,
        "method": method_name,
        "rows": len(tree.get_children("")),
        "repo_top_cumulative": profile_rows(profile),
    }


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_OPERATION_PROFILE", "")).strip()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def main() -> None:
    benchmark = load_scaled_benchmark()
    import data_location
    import app
    import runtime_bootstrap

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
        profiles = [
            profile_refresh(window, "actions", "refresh_actions", "action_tree"),
            profile_refresh(window, "requests", "refresh_requests", "request_tree"),
            profile_refresh(window, "tasks", "refresh_tasks", "task_tree"),
        ]
        window.update_idletasks()
        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))
        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "seed_counts": counts,
                "profiles": profiles,
                "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
                "callback_errors": callback_errors,
            }
        )
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
        write_result(
            {
                "ok": False,
                "exception_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        raise
