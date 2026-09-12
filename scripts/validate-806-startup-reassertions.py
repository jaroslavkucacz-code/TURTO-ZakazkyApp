#!/usr/bin/env python3
"""Temporary real-Windows probe of delayed startup callback origins."""
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
WATCH = {0, 80, 180, 260, 650, 760, 1500, 1650}


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_806_REASSERT_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def main() -> None:
    if not os.environ.get("TURTO_CRM_DATA_ROOT"):
        raise AssertionError("isolated TURTO_CRM_DATA_ROOT required")
    import app, data_location, runtime_bootstrap
    data_location.apply_to_app(app)
    app.cleanup_stale_test_session(); app.ensure_schema(); runtime_bootstrap.apply_all(app)
    app.ensure_schema(); app.ensure_test_user(); app.migrate_v41_visual_once()
    app.App.maybe_show_morning_overview = lambda self: None

    seen = []
    original_after = app.App.after
    def traced_after(self, delay, callback=None, *args):
        try:
            ms = int(delay)
        except Exception:
            ms = -1
        if ms in WATCH and callable(callback):
            code = getattr(callback, "__code__", None)
            closure = []
            for cell in (getattr(callback, "__closure__", None) or ()):
                try:
                    value = cell.cell_contents
                    closure.append(str(getattr(value, "__name__", type(value).__name__)))
                except Exception:
                    closure.append("<unreadable>")
            seen.append({
                "delay": ms,
                "module": str(getattr(callback, "__module__", "")),
                "name": str(getattr(callback, "__name__", "")),
                "qualname": str(getattr(callback, "__qualname__", "")),
                "filename": str(getattr(code, "co_filename", "")) if code else "",
                "freevars": list(getattr(code, "co_freevars", ()) or ()) if code else [],
                "closure_names": closure,
            })
        return original_after(self, delay, callback, *args)
    app.App.after = traced_after

    window = None
    errors = []
    try:
        window = app.App()
        window.report_callback_exception = lambda *exc: errors.append(str(exc))
        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            window.update(); time.sleep(0.01)
        interesting = [row for row in seen if row["module"] in {
            "v710_cleanup", "v740_offer_defaults", "v750_context_filters_offer_format"
        } or any(name in {"tidy", "configure_workspaces", "register_configurable_tables"}
                 for name in row["closure_names"])]
        write_result({
            "ok": not errors,
            "platform": sys.platform,
            "interesting_callbacks": interesting,
            "all_watched_callbacks": seen,
            "tk_callback_errors": errors,
            "database": str(app.DB),
        })
        if errors:
            raise AssertionError(errors)
    finally:
        app.App.after = original_after
        if window is not None:
            try: window.destroy()
            except Exception: pass


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write_result({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        raise
