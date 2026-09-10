#!/usr/bin/env python3
"""Profile a few seconds of an otherwise idle real TURTO CRM Tk main loop.

Development/CI only. The isolated data root and disabled automatic updater ensure
this cannot touch user data or open network update UI. The goal is to identify
periodic legacy sweeps that still consume UI time after startup has settled.
"""
from __future__ import annotations

import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import time
import traceback


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"
PROFILE_SECONDS = 4.4


def profile_rows(profile: cProfile.Profile, limit: int = 50) -> list[dict]:
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


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_SETTLED_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target:
        Path(target).write_text(text, encoding="utf-8")
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
    app.App.maybe_show_morning_overview = lambda self: None

    window = None
    callback_errors: list[str] = []
    profiler = cProfile.Profile()
    try:
        window = app.App()

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append(
                "".join(traceback.format_exception(exc_type, exc, tb)).strip()
            )

        window.report_callback_exception = report_callback_exception
        window.update_idletasks()

        started = time.perf_counter()
        profiler.enable()
        while time.perf_counter() - started < PROFILE_SECONDS:
            window.update()
            time.sleep(0.005)
        profiler.disable()
        elapsed = time.perf_counter() - started

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))

        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "profile_window_seconds": round(elapsed, 6),
                "repo_top_cumulative": profile_rows(profiler),
                "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
                "dialog_events_coalesced": int(
                    getattr(window, "_turto_dialog_raise_events_coalesced", 0) or 0
                ),
                "callback_errors": callback_errors,
            }
        )
    finally:
        try:
            profiler.disable()
        except Exception:
            pass
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
