#!/usr/bin/env python3
"""Instantiate and profile the real TURTO CRM UI once on an isolated database.

This is a CI/development probe only. It disables automatic updates and morning
modal dialogs, never touches production data, and records both the lightweight
8.0.3 timings and a cProfile view of the startup call stack. It also opens every
registered page once so later startup optimizations cannot silently break the
real page lifecycle.
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

PAGE_PROBES = {
    "dash": "dash_tree",
    "actions": "action_tree",
    "requests": "request_tree",
    "mivo": "mivo_tree",
    "offers": "offer_tree",
    "pricelists": "price_current_tree",
    "issued_offers": "issued_offer_tree",
    "tasks": "task_tree",
    "projects": "project_tree",
    "people": "people_tree",
    "companies": "company_tree",
    "help": "help_text",
    "settings": "theme",
}
EXPECTED_V628_COALESCED = (
    (1550, "apply_modern_palette"),
    (1750, "dashboard_layout"),
)


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


def profile_rows(profile: cProfile.Profile, *, repo_only: bool, limit: int = 40):
    """Return compact cumulative-time rows without relying on formatted pstats text."""
    stats = pstats.Stats(profile).stats
    rows = []
    base_text = str(BASE.resolve()).casefold()
    repo_text = str(REPO.resolve()).casefold()
    for key, values in stats.items():
        filename, lineno, function = key
        primitive_calls, total_calls, own_time, cumulative_time, _callers = values
        normalized = str(Path(filename).resolve()).casefold() if filename else ""
        if repo_only and not (normalized.startswith(base_text) or normalized.startswith(repo_text)):
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
    rows.sort(key=lambda row: (row["cumulative_seconds"], row["self_seconds"]), reverse=True)
    return rows[:limit]


def cache_info_payload(function):
    getter = getattr(function, "cache_info", None)
    if not callable(getter):
        return None
    try:
        info = getter()
        return {
            "hits": int(info.hits),
            "misses": int(info.misses),
            "maxsize": int(info.maxsize) if info.maxsize is not None else None,
            "currsize": int(info.currsize),
        }
    except Exception:
        return None


def initial_page_geometry(window) -> dict[str, str]:
    """Assert all built non-current pages are detached before the first idle turn."""
    tabs = getattr(window, "tabs", {}) or {}
    current = str(getattr(window, "_current_page", "") or "")
    if current not in tabs:
        raise AssertionError(f"Initial current page is invalid: {current!r}")
    managers = {}
    for key, page in tabs.items():
        managers[str(key)] = str(page.winfo_manager() or "")
    expected_hidden = {str(key) for key in tabs if str(key) != current}
    recorded = set(
        str(key)
        for key in (getattr(window, "_turto_hidden_pages_detached_immediately", ()) or ())
    )
    if recorded != expected_hidden:
        raise AssertionError(
            f"Immediate detach recorded {sorted(recorded)!r}, expected {sorted(expected_hidden)!r}"
        )
    still_managed = {key: managers[key] for key in expected_hidden if managers.get(key)}
    if still_managed:
        raise AssertionError(f"Hidden pages remain managed before first idle turn: {still_managed!r}")
    if not managers.get(current):
        raise AssertionError(f"Current page unexpectedly detached: {current}")
    return managers


def exercise_navigation(window) -> list[dict[str, str]]:
    """Open every current page and assert its primary UI object exists."""
    rows = []
    for key, attribute in PAGE_PROBES.items():
        if key not in getattr(window, "tabs", {}):
            raise AssertionError(f"Missing page registered in tabs: {key}")
        window.show_page(key)
        window.update_idletasks()
        current = str(getattr(window, "_current_page", ""))
        if current != key:
            raise AssertionError(f"Navigation did not activate {key}: {current}")
        target = getattr(window, attribute, None)
        if target is None:
            raise AssertionError(f"Page {key} did not expose {attribute}")
        rows.append({"page": key, "probe": attribute})
    window.show_page("dash")
    window.update_idletasks()
    if str(getattr(window, "_current_page", "")) != "dash":
        raise AssertionError("Navigation did not return to dashboard")
    return rows


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
    profiler = cProfile.Profile()
    callback_errors: list[str] = []
    started = time.perf_counter()
    try:
        profiler.enable()
        window = app.App()
        profiler.disable()
        wall = time.perf_counter() - started

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append(
                "".join(traceback.format_exception(exc_type, exc, tb)).strip()
            )

        # Validate geometry immediately, before any pending idle callback can
        # obscure whether 8.0.3 itself detached the already-built hidden pages.
        page_managers_before_idle = initial_page_geometry(window)

        # Install before driving idle/navigation callbacks. Any Python-level Tk
        # callback failure is a real regression even when Tk would only print it.
        window.report_callback_exception = report_callback_exception
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

        v628_coalesced = tuple(
            tuple(item)
            for item in (getattr(window, "_turto_v628_cosmetic_passes_coalesced", ()) or ())
        )
        if v628_coalesced != EXPECTED_V628_COALESCED:
            raise AssertionError(
                f"Unexpected v628 delayed cosmetic coalescing: {v628_coalesced!r}"
            )

        # These counters are useful diagnostics, but later compatibility wrappers
        # may intercept the same callback before this owner sees it. Their exact
        # value is therefore not a real-UI correctness contract; dedicated unit
        # tests validate the suppression predicates themselves.
        v760_coalesced = tuple(
            int(value)
            for value in (getattr(window, "_turto_v760_finalizers_coalesced", ()) or ())
        )
        v638_coalesced = tuple(
            int(value)
            for value in (getattr(window, "_turto_v638_startup_stabilizers_coalesced", ()) or ())
        )

        navigation = exercise_navigation(window)
        window.update_idletasks()
        if callback_errors:
            raise AssertionError(
                "Tk callback regression:\n" + "\n\n".join(callback_errors)
            )

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
            "profile_top_cumulative": profile_rows(profiler, repo_only=False, limit=40),
            "profile_top_repo_cumulative": profile_rows(profiler, repo_only=True, limit=60),
            "czech_sort_cache": cache_info_payload(getattr(app, "czech_sort_key", None)),
            "initial_page_managers": page_managers_before_idle,
            "initial_detached_page_count": len(
                getattr(window, "_turto_hidden_pages_detached_immediately", ()) or ()
            ),
            "navigation_pages": navigation,
            "navigation_page_count": len(navigation),
            "date_label_manager": date_manager,
            "today_summary_manager": summary_manager,
            "hidden_header_skip_verified": True,
            "tk_callback_errors": callback_errors,
            "v628_cosmetic_passes_coalesced": [list(item) for item in v628_coalesced],
            "v760_finalizers_coalesced": list(v760_coalesced),
            "v638_startup_stabilizers_coalesced": list(v638_coalesced),
            "performance_log": str(getattr(window, "_turto_performance_log", "")),
            "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
        }
        write_result(payload)
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
