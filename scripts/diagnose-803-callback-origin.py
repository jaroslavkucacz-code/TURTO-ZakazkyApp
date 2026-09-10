#!/usr/bin/env python3
"""Diagnostic-only Tk callback provenance probe for TURTO CRM 8.0.3 work.

It instruments tkinter.CallWrapper only inside this process so callback errors
include the real source filename, first line and qualified function name. No
production code or user data is modified.
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

CYCLES = 12
VALUES = tuple(f"Diagnostika {i:03d}" for i in range(40))


def callback_meta(func, exc, args):
    code = getattr(func, "__code__", None)
    return {
        "file": str(getattr(code, "co_filename", "") or ""),
        "line": int(getattr(code, "co_firstlineno", 0) or 0),
        "name": str(getattr(code, "co_name", "") or ""),
        "qualname": str(getattr(func, "__qualname__", "") or ""),
        "repr": repr(func),
        "args_count": len(args),
        "exception": f"{type(exc).__name__}: {exc}",
    }


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

    root = app.App()
    errors = []
    provenance = []

    def report_callback_exception(exc_type, exc, tb):
        errors.append("".join(traceback.format_exception(exc_type, exc, tb)).strip())

    root.report_callback_exception = report_callback_exception
    root.update()

    CallWrapper = app.tk.CallWrapper
    original_call = CallWrapper.__call__

    def traced_call(self, *args):
        try:
            call_args = args
            if self.subst:
                call_args = self.subst(*call_args)
            return self.func(*call_args)
        except SystemExit:
            raise
        except BaseException as exc:
            try:
                provenance.append(callback_meta(self.func, exc, call_args if 'call_args' in locals() else args))
            except Exception:
                pass
            try:
                self.widget._report_exception()
            except Exception:
                pass
            return None

    CallWrapper.__call__ = traced_call
    try:
        for cycle in range(CYCLES):
            top = app.tk.Toplevel(root)
            frame = app.ttk.Frame(top)
            frame.pack(fill="both", expand=True)
            entries = []
            for idx in range(3):
                var = app.tk.StringVar(value=f"{cycle}-{idx}")
                entry = app.AutocompleteEntry(frame, textvariable=var, values=VALUES)
                entry.pack(fill="x")
                entries.append(entry)
            top.update_idletasks()
            entries[0].focus_set()
            top.lift()
            root.update()
            top.destroy()
            root.update()
        for _ in range(3):
            root.update()
            time.sleep(0.01)
    finally:
        CallWrapper.__call__ = original_call
        try:
            root.destroy()
        except Exception:
            pass

    unique = []
    seen = set()
    for row in provenance:
        key = (row["file"], row["line"], row["qualname"], row["exception"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    payload = {
        "ok": True,
        "cycles": CYCLES,
        "callback_error_count": len(errors),
        "provenance_count": len(provenance),
        "unique_origins": unique,
        "errors": errors[:20],
    }
    target = str(os.environ.get("TURTO_CRM_CALLBACK_ORIGIN_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if target:
        Path(target).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
