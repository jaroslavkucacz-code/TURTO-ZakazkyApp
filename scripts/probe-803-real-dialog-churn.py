#!/usr/bin/env python3
"""Long-session lifecycle probe using real TURTO CRM business dialogs.

Development/CI only. Uses an isolated data root and creates a tiny synthetic set
of companies/actions/materials needed to populate suggesters. It opens and closes
real dialogs without saving: Příležitost, Poptávka, Úkol, Společnost and Osoba.
The probe verifies that real dialog wrappers, AutocompleteEntry popups/traces and
Tk callbacks return to their settled baseline after repeated use.
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

ROUNDS = 8


def _columns(con, table: str):
    return list(con.execute(f'PRAGMA table_info("{table}")').fetchall())


def _insert_compatible(con, table: str, values: dict) -> int:
    info = _columns(con, table)
    names = {str(row[1]): row for row in info}
    payload = {key: value for key, value in values.items() if key in names and key != "id"}
    for name, row in names.items():
        if name == "id" or name in payload:
            continue
        col_type = str(row[2] or "").upper()
        notnull = bool(row[3])
        default = row[4]
        pk = bool(row[5])
        if pk or not notnull or default is not None:
            continue
        payload[name] = 0 if any(token in col_type for token in ("INT", "REAL", "NUM")) else ""
    columns = list(payload)
    marks = ",".join("?" for _ in columns)
    quoted = ",".join(f'"{name}"' for name in columns)
    cur = con.execute(
        f'INSERT INTO "{table}" ({quoted}) VALUES ({marks})',
        tuple(payload[name] for name in columns),
    )
    return int(cur.lastrowid)


def seed_minimal(app) -> dict[str, int]:
    with app.db() as con:
        company_id = _insert_compatible(
            con,
            "companies",
            {
                "short_name": "CHURN SUPPLIER",
                "official_name": "Churn Supplier s.r.o.",
                "ico": "99000001",
                "active": 1,
            },
        )
        customer_id = _insert_compatible(
            con,
            "companies",
            {
                "short_name": "CHURN CUSTOMER",
                "official_name": "Churn Customer s.r.o.",
                "ico": "99000002",
                "active": 1,
            },
        )
        project_id = _insert_compatible(
            con,
            "projects",
            {
                "name": "Churn test Akce",
                "active": 1,
                "created_by": "TURTO CI",
            },
        )
        action_id = _insert_compatible(
            con,
            "actions",
            {
                "name": "Churn test Příležitost",
                "company_id": customer_id,
                "project_id": project_id,
                "status": "Rozpracováno",
                "created_date": "2026-09-10",
                "products": "Izolační nosníky",
            },
        )
        _insert_compatible(con, "salespeople", {"name": "TURTO CI", "active": 1})
        _insert_compatible(con, "materials", {"name": "Izolační nosníky", "active": 1})
    return {
        "supplier_company_id": company_id,
        "customer_company_id": customer_id,
        "project_id": project_id,
        "action_id": action_id,
    }


def walk(widget):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from walk(child)
    except Exception:
        return


def widget_count(root) -> int:
    return sum(1 for _ in walk(root))


def toplevel_count(root) -> int:
    total = 0
    for widget in walk(root):
        if widget is root:
            continue
        try:
            if widget.winfo_class() == "Toplevel" and widget.winfo_exists():
                total += 1
        except Exception:
            pass
    return total


def autocomplete_entries(app, dialog):
    return [widget for widget in walk(dialog) if isinstance(widget, app.AutocompleteEntry)]


def settle(root, seconds: float = 0.12):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(0.005)


def open_close_one(app, root, label: str, factory, refs: dict[str, list]) -> dict:
    dialog = factory()
    refs["dialogs"].append(weakref.ref(dialog))
    root.update_idletasks()
    root.update()
    entries = autocomplete_entries(app, dialog)
    refs["entries"].extend(weakref.ref(entry) for entry in entries)
    if entries:
        entry = entries[0]
        try:
            entry.focus_set()
            root.update()
            # Trigger the real write-trace/show path without changing business data.
            current = str(entry.var.get() or "")
            entry.var.set(current)
            root.update()
        except Exception:
            pass
    dialog.destroy()
    del entries, dialog
    root.update()
    return {"dialog": label}


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_REAL_DIALOG_RESULT", "")).strip()
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
    ids = seed_minimal(app)
    app.App.maybe_show_morning_overview = lambda self: None

    root = None
    callback_errors: list[str] = []
    refs = {"dialogs": [], "entries": []}
    try:
        root = app.App()

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append(
                "".join(traceback.format_exception(exc_type, exc, tb)).strip()
            )

        root.report_callback_exception = report_callback_exception
        settle(root, 4.2)

        factories = (
            ("Příležitost", lambda: app.ActionDialog(root)),
            ("Poptávka", lambda: app.RequestDialog(root)),
            ("Úkol", lambda: app.TaskDialog(root)),
            ("Společnost", lambda: app.CompanyDialog(root)),
            ("Osoba", lambda: app.PersonDialog(root)),
        )

        # Warm each constructor once so the baseline includes any legitimate
        # one-time Tk objects that a real dialog family creates lazily.
        warm_refs = {"dialogs": [], "entries": []}
        for label, factory in factories:
            open_close_one(app, root, label, factory, warm_refs)
        settle(root, 0.25)
        del warm_refs
        gc.collect()

        baseline_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        baseline_widgets = widget_count(root)
        baseline_toplevels = toplevel_count(root)

        gc.collect()
        tracemalloc.start()
        before_current, before_peak = tracemalloc.get_traced_memory()
        started = time.perf_counter()
        opened = []

        for _round in range(ROUNDS):
            for label, factory in factories:
                opened.append(open_close_one(app, root, label, factory, refs))
                registry_now = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
                if registry_now != baseline_registry:
                    raise AssertionError(
                        f"Autocomplete registry changed after {label}: "
                        f"{registry_now} != {baseline_registry}"
                    )

        settle(root, 0.3)
        gc.collect()
        elapsed = time.perf_counter() - started
        after_current, after_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        final_registry = len(list(getattr(app, "_AUTOCOMPLETE_ENTRIES", ()) or ()))
        final_widgets = widget_count(root)
        final_toplevels = toplevel_count(root)
        alive_dialogs = sum(1 for ref in refs["dialogs"] if ref() is not None)
        alive_entries = sum(1 for ref in refs["entries"] if ref() is not None)
        pending_dialog_raise = getattr(root, "_turto_dialog_raise_after", None)

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))
        if final_registry != baseline_registry:
            raise AssertionError(f"Registry leak: {final_registry} != {baseline_registry}")
        if final_widgets != baseline_widgets:
            raise AssertionError(f"Widget leak: {final_widgets} != {baseline_widgets}")
        if final_toplevels != baseline_toplevels:
            raise AssertionError(f"Toplevel leak: {final_toplevels} != {baseline_toplevels}")
        if alive_dialogs:
            raise AssertionError(f"Destroyed real dialogs still alive: {alive_dialogs}")
        if alive_entries:
            raise AssertionError(f"Destroyed real-dialog autocomplete entries still alive: {alive_entries}")
        if pending_dialog_raise is not None:
            raise AssertionError(f"Dialog coalescer left pending callback: {pending_dialog_raise!r}")

        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "rounds": ROUNDS,
                "dialog_types": [label for label, _factory in factories],
                "dialogs_opened": len(opened),
                "seed_ids": ids,
                "elapsed_seconds": round(elapsed, 6),
                "baseline_autocomplete_registry": baseline_registry,
                "final_autocomplete_registry": final_registry,
                "baseline_widgets": baseline_widgets,
                "final_widgets": final_widgets,
                "baseline_toplevels": baseline_toplevels,
                "final_toplevels": final_toplevels,
                "autocomplete_entries_observed": len(refs["entries"]),
                "alive_dialog_refs": alive_dialogs,
                "alive_entry_refs": alive_entries,
                "pending_dialog_raise": pending_dialog_raise,
                "python_memory_delta_bytes": int(after_current - before_current),
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
