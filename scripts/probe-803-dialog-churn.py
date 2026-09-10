#!/usr/bin/env python3
"""Exercise repeated dialog/autocomplete creation in the real TURTO CRM Tk runtime.

Development/CI only. Uses an isolated data root, never opens a business dialog or
modifies user data. The probe repeatedly creates and destroys lightweight
Toplevels containing real AutocompleteEntry widgets and drives the Tk event loop.
It verifies that process-wide autocomplete registration, dialog z-order
coalescing and widget/reference lifetime return to their baseline state.
"""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import sys
import time
import traceback
import tracemalloc
import weakref


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"

CYCLES = 80
ENTRIES_PER_DIALOG = 3
VALUES = tuple(f"Benchmark hodnota {index:03d}" for index in range(120))


def walk_count(widget) -> int:
    total = 1
    try:
        for child in widget.winfo_children():
            total += walk_count(child)
    except Exception:
        pass
    return total


def live_toplevel_count(root) -> int:
    total = 0
    try:
        for child in root.winfo_children():
            try:
                if child.winfo_class() == "Toplevel" and child.winfo_exists():
                    total += 1
            except Exception:
                pass
    except Exception:
        pass
    return total


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_CHURN_RESULT", "")).strip()
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
    app.App.maybe_show_morning_overview = lambda self: None

    root = None
    callback_errors: list[str] = []
    entry_refs: list[weakref.ReferenceType] = []
    top_refs: list[weakref.ReferenceType] = []
    try:
        root = app.App()

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append(
                "".join(traceback.format_exception(exc_type, exc, tb)).strip()
            )

        root.report_callback_exception = report_callback_exception
        root.update()
        baseline_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        baseline_widgets = walk_count(root)
        baseline_toplevels = live_toplevel_count(root)

        # Start after normal startup transients have settled, so the memory delta
        # describes churn rather than initial imports/Tk initialization.
        gc.collect()
        tracemalloc.start()
        before_current, before_peak = tracemalloc.get_traced_memory()
        started = time.perf_counter()

        for cycle in range(CYCLES):
            top = app.tk.Toplevel(root)
            top.title(f"TURTO churn {cycle}")
            top.transient(root)
            frame = app.ttk.Frame(top, padding=8)
            frame.pack(fill="both", expand=True)

            entries = []
            for index in range(ENTRIES_PER_DIALOG):
                variable = app.tk.StringVar(value=f"Benchmark {cycle}-{index}")
                entry = app.AutocompleteEntry(
                    frame,
                    textvariable=variable,
                    values=VALUES,
                )
                entry.pack(fill="x", pady=2)
                entries.append(entry)
                entry_refs.append(weakref.ref(entry))

            top_refs.append(weakref.ref(top))
            top.update_idletasks()
            # Drive real Map/Focus propagation. This is the event pattern that
            # historically caused hundreds of recursive dialog-chain sweeps.
            try:
                entries[0].focus_set()
                top.lift()
            except Exception:
                pass
            root.update()

            top.destroy()
            del entries, frame, top
            root.update()

            # Fail early if the process-wide registry grows monotonically.
            registry_now = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
            if registry_now > baseline_registry:
                raise AssertionError(
                    f"Autocomplete registry leaked after cycle {cycle}: "
                    f"{registry_now} > baseline {baseline_registry}"
                )

        # Let every coalesced after_idle/focus callback complete, then force Python
        # collection to expose references held beyond the lifetime of destroyed Tk widgets.
        for _ in range(4):
            root.update()
            time.sleep(0.01)
        gc.collect()
        elapsed = time.perf_counter() - started
        after_current, after_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        final_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        final_widgets = walk_count(root)
        final_toplevels = live_toplevel_count(root)
        alive_entries = sum(1 for ref in entry_refs if ref() is not None)
        alive_toplevels = sum(1 for ref in top_refs if ref() is not None)
        pending_dialog_raise = getattr(root, "_turto_dialog_raise_after", None)
        coalesced_events = int(
            getattr(root, "_turto_dialog_raise_events_coalesced", 0) or 0
        )
        memory_delta = int(after_current - before_current)

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))
        if final_registry != baseline_registry:
            raise AssertionError(
                f"Autocomplete registry did not return to baseline: "
                f"{final_registry} != {baseline_registry}"
            )
        if final_toplevels != baseline_toplevels:
            raise AssertionError(
                f"Toplevel count did not return to baseline: "
                f"{final_toplevels} != {baseline_toplevels}"
            )
        if final_widgets > baseline_widgets + 3:
            raise AssertionError(
                f"Tk widget count grew after churn: {final_widgets} vs {baseline_widgets}"
            )
        if alive_entries:
            raise AssertionError(f"Destroyed AutocompleteEntry references still alive: {alive_entries}")
        if alive_toplevels:
            raise AssertionError(f"Destroyed Toplevel references still alive: {alive_toplevels}")
        if pending_dialog_raise is not None:
            raise AssertionError(
                f"Dialog-chain coalescer left a pending callback: {pending_dialog_raise!r}"
            )

        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "cycles": CYCLES,
                "entries_per_dialog": ENTRIES_PER_DIALOG,
                "entries_created": CYCLES * ENTRIES_PER_DIALOG,
                "elapsed_seconds": round(elapsed, 6),
                "baseline_autocomplete_registry": baseline_registry,
                "final_autocomplete_registry": final_registry,
                "baseline_widgets": baseline_widgets,
                "final_widgets": final_widgets,
                "baseline_toplevels": baseline_toplevels,
                "final_toplevels": final_toplevels,
                "alive_entry_refs": alive_entries,
                "alive_toplevel_refs": alive_toplevels,
                "dialog_events_coalesced": coalesced_events,
                "pending_dialog_raise": pending_dialog_raise,
                "python_memory_delta_bytes": memory_delta,
                "python_memory_peak_bytes": int(after_peak - before_peak),
                "tk_callback_errors": callback_errors,
            }
        )
    finally:
        try:
            tracemalloc.stop()
        except Exception:
            pass
        if root is not None:
            try:
                root.destroy()
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
