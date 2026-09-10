#!/usr/bin/env python3
"""Instantiate the real TURTO CRM UI once and persist startup timing data.

This is a CI/development probe only. It uses an isolated temporary data root,
disables automatic updates and morning dialogs, and never touches production data.
"""
from __future__ import annotations

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


def latest_timings(instance) -> dict[str, float]:
    raw = getattr(instance, "_turto_perf_timings", {}) or {}
    result = {}
    for key, values in raw.items():
        try:
            if values:
                result[str(key)] = round(float(values[-1]), 6)
        except Exception:
            continue
    return result


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_PERF_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def main() -> None:
    import data_location
    import app
    import runtime_bootstrap

    data_location.apply_to_app(app)
    app.cleanup_stale_test_session()
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.migrate_v41_visual_once()

    # The probe must never create a modal morning overview on the hosted runner.
    app.App.maybe_show_morning_overview = lambda self: None

    window = None
    started = time.perf_counter()
    try:
        window = app.App()
        wall = time.perf_counter() - started
        window.update_idletasks()

        date_widget = getattr(window, "date_label", None)
        summary_widget = getattr(window, "today_summary", None)
        date_manager = str(date_widget.winfo_manager() or "") if date_widget is not None else "missing"
        summary_manager = str(summary_widget.winfo_manager() or "") if summary_widget is not None else "missing"

        # Exercise the optimized final header method once. With the current UI it
        # must stay DB-free because both historical widgets are intentionally hidden.
        before_skips = int(getattr(window, "_turto_hidden_header_refresh_skips", 0) or 0)
        window.refresh_header()
        after_skips = int(getattr(window, "_turto_hidden_header_refresh_skips", 0) or 0)
        if date_manager or summary_manager:
            raise AssertionError("Header widgets unexpectedly became visible in the startup probe")
        if after_skips != before_skips + 1:
            raise AssertionError("Hidden header refresh was not skipped")

        timings = latest_timings(window)
        required = ("app_init", "build_total", "apply_theme")
        missing = [key for key in required if key not in timings]
        if missing:
            raise AssertionError("Missing startup timings: " + ", ".join(missing))

        builders = {
            key: value
            for key, value in timings.items()
            if key.startswith("build_") and key != "build_total"
        }
        slowest = sorted(builders.items(), key=lambda item: item[1], reverse=True)
        payload = {
            "ok": True,
            "platform": sys.platform,
            "version": str(getattr(app, "APP_VERSION", "")),
            "database": str(app.DB),
            "wall_app_init_seconds": round(wall, 6),
            "timings_seconds": timings,
            "slowest_builders": slowest,
            "date_label_manager": date_manager,
            "today_summary_manager": summary_manager,
            "hidden_header_skip_verified": True,
            "performance_log": str(getattr(window, "_turto_performance_log", "")),
            "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
        }
        write_result(payload)
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
