#!/usr/bin/env python3
"""Measure the 8.0.5 same-user restore fast path against the legacy path.

The comparison runs both implementations inside one real Tk/Windows process on
an isolated CI database, avoiding cross-runner wall-time noise. Correctness is
checked structurally: the fast path must not call ``on_user_changed`` when the
locally remembered user is already active; the legacy path must call it once.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import sys
import time
import traceback


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_SAME_USER_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    # Hosted Windows runners may expose a cp1252 console. Keep the artifact
    # human-readable UTF-8, but escape non-ASCII characters for console output.
    print(json.dumps(payload, ensure_ascii=True, indent=2))


def timed(fn, repeats: int) -> list[float]:
    values: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        values.append((time.perf_counter() - started) * 1000.0)
    return values


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
    app.App.maybe_show_morning_overview = lambda self: None

    window = None
    try:
        window = app.App()
        window.update_idletasks()

        import crm_runtime

        fast = getattr(crm_runtime, "_restore_local_user", None)
        legacy = getattr(fast, "_turto_original", None)
        if not callable(fast) or not getattr(fast, "_turto_804_same_user_fast", False):
            raise AssertionError("8.0.5 same-user restore fast path is not installed")
        if not callable(legacy):
            raise AssertionError("Legacy restore function is not available for A/B comparison")

        current = str(window.active_user.get() or "").strip()
        with app.db() as con:
            valid = [
                row["name"]
                for row in con.execute(
                    "SELECT name FROM users WHERE active=1 AND upper(trim(name))<>'ADMIN' ORDER BY name COLLATE CZECH"
                )
            ]
        if current not in valid:
            if not valid:
                raise AssertionError("No non-ADMIN user available for same-user benchmark")
            current = str(valid[0])
            window.active_user.set(current)
            app.set_setting("active_user", current)
            window.on_user_changed()
            window.update_idletasks()

        cfg_writer = getattr(crm_runtime, "_save_cfg", None)
        if not callable(cfg_writer):
            raise AssertionError("crm_runtime._save_cfg is unavailable")
        cfg_writer(last_user=current)

        original_user_changed = window.on_user_changed
        calls = {"count": 0}

        def counted_user_changed(*args, **kwargs):
            calls["count"] += 1
            return original_user_changed(*args, **kwargs)

        window.on_user_changed = counted_user_changed

        before_skips = int(getattr(window, "_turto_same_user_restore_skips_804", 0) or 0)
        calls["count"] = 0
        fast(window)
        window.update_idletasks()
        fast_user_changed_calls = calls["count"]
        after_skips = int(getattr(window, "_turto_same_user_restore_skips_804", 0) or 0)
        if fast_user_changed_calls != 0:
            raise AssertionError(f"Fast path called on_user_changed {fast_user_changed_calls} times")
        if after_skips != before_skips + 1:
            raise AssertionError("Fast path did not record exactly one skipped duplicate restore")

        calls["count"] = 0
        legacy(window)
        window.update_idletasks()
        legacy_user_changed_calls = calls["count"]
        if legacy_user_changed_calls != 1:
            raise AssertionError(f"Legacy path called on_user_changed {legacy_user_changed_calls} times")

        # Warm both paths once before timing. The legacy call intentionally performs
        # the full historical theme/button/refresh cycle; no business values change.
        fast(window)
        legacy(window)
        window.update_idletasks()

        fast_times = timed(lambda: fast(window), 7)
        legacy_times = timed(lambda: legacy(window), 5)
        window.update_idletasks()

        fast_median = statistics.median(fast_times)
        legacy_median = statistics.median(legacy_times)
        payload = {
            "ok": True,
            "platform": sys.platform,
            "active_user": current,
            "fast_user_changed_calls": fast_user_changed_calls,
            "legacy_user_changed_calls": legacy_user_changed_calls,
            "fast_ms": [round(v, 4) for v in fast_times],
            "legacy_ms": [round(v, 4) for v in legacy_times],
            "fast_median_ms": round(fast_median, 4),
            "legacy_median_ms": round(legacy_median, 4),
            "median_saved_ms": round(legacy_median - fast_median, 4),
            "legacy_to_fast_ratio": round(legacy_median / fast_median, 3) if fast_median > 0 else None,
            "skip_counter": int(getattr(window, "_turto_same_user_restore_skips_804", 0) or 0),
            "database": str(app.DB),
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
