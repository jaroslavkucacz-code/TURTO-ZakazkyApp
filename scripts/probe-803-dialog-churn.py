#!/usr/bin/env python3
"""Exercise repeated dialog/autocomplete creation in the real TURTO CRM Tk runtime.

Development/CI only. Uses an isolated data root, never opens a business dialog or
modifies user data. The probe repeatedly creates and destroys lightweight
Toplevels containing real AutocompleteEntry widgets and drives the Tk event loop.
It verifies that process-wide autocomplete registration, dialog z-order
coalescing and widget/reference lifetime return to their settled baseline state.
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
WARMUP_CYCLES = 3
STARTUP_SETTLE_SECONDS = 4.2
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


def settle(root, seconds: float) -> None:
    """Run Tk while delayed startup/idle callbacks become eligible."""
    deadline = time.perf_counter() + max(0.0, float(seconds))
    while True:
        root.update()
        if time.perf_counter() >= deadline:
            break
        time.sleep(0.02)
    for _ in range(3):
        root.update()


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
        cold_widgets = walk_count(root)
        cold_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        cold_toplevels = live_toplevel_count(root)

        # App.__init__ intentionally schedules a handful of delayed stability and
        # presentation callbacks (up to several seconds after construction). A
        # long-session leak test must not mistake those one-time startup effects
        # for widgets retained by dialog churn, so first let the real Tk runtime
        # settle and materialize the autocomplete path a few times.
        settle(root, STARTUP_SETTLE_SECONDS)

        def exercise_cycle(cycle: int, *, track_refs: bool) -> None:
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
                if track_refs:
                    entry_refs.append(weakref.ref(entry))

            if track_refs:
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

        for cycle in range(WARMUP_CYCLES):
            exercise_cycle(-(cycle + 1), track_refs=False)
        settle(root, 0.15)
        gc.collect()

        if callback_errors:
            raise AssertionError(
                "Tk callback regression during settled warm-up:\n"
                + "\n\n".join(callback_errors)
            )
        warm_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        if warm_registry != cold_registry:
            raise AssertionError(
                f"Autocomplete registry changed during warm-up: "
                f"{warm_registry} != {cold_registry}"
            )

        # This is the meaningful long-session baseline: startup timers have fired
        # and one-time Tk/autocomplete structures are already materialized. Any
        # subsequent monotonic growth is therefore attributable to measured churn.
        baseline_registry = warm_registry
        baseline_widgets = walk_count(root)
        baseline_toplevels = live_toplevel_count(root)

        tracemalloc.start()
        before_current, before_peak = tracemalloc.get_traced_memory()
        started = time.perf_counter()

        for cycle in range(CYCLES):
            exercise_cycle(cycle, track_refs=True)

            # Fail early if the process-wide registry grows monotonically.
            registry_now = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
            if registry_now > baseline_registry:
                raise AssertionError(
                    f"Autocomplete registry leaked after cycle {cycle}: "
                    f"{registry_now} > baseline {baseline_registry}"
                )

        # Let every coalesced after_idle/focus callback complete, then force Python
        # collection to expose references held beyond the lifetime of destroyed Tk widgets.
        settle(root, 0.08)
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
        widget_delta = int(final_widgets - baseline_widgets)

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
                f"Tk widget count grew after settled churn: "
                f"{final_widgets} vs {baseline_widgets}"
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
                "warmup_cycles": WARMUP_CYCLES,
                "startup_settle_seconds": STARTUP_SETTLE_SECONDS,
                "entries_per_dialog": ENTRIES_PER_DIALOG,
                "entries_created": CYCLES * ENTRIES_PER_DIALOG,
                "elapsed_seconds": round(elapsed, 6),
                "cold_autocomplete_registry": cold_registry,
                "baseline_autocomplete_registry": baseline_registry,
                "final_autocomplete_registry": final_registry,
                "cold_widgets": cold_widgets,
                "baseline_widgets": baseline_widgets,
                "final_widgets": final_widgets,
                "widget_delta_after_settled_baseline": widget_delta,
                "cold_toplevels": cold_toplevels,
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
