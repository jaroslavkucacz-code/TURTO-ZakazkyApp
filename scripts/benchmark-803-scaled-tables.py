#!/usr/bin/env python3
"""Benchmark key TURTO CRM tables against a synthetic medium/large dataset.

Development/CI only. The benchmark uses TURTO_CRM_DATA_ROOT, creates synthetic
records in that isolated database, instantiates the real Tk UI and measures the
final composed refresh methods. It never opens or modifies a user's database.
"""
from __future__ import annotations

import cProfile
from datetime import date, timedelta
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

COMPANIES = 240
PROJECTS = 600
ACTIONS = 1200
REQUESTS = 4000
TASKS = 1800


def columns(con, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def insert_many(con, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    available = columns(con, table)
    names = [name for name in rows[0] if name in available and name != "id"]
    if not names:
        raise AssertionError(f"No compatible columns for {table}")
    marks = ",".join("?" for _ in names)
    sql = f'INSERT INTO "{table}" ({",".join(names)}) VALUES ({marks})'
    con.executemany(sql, [tuple(row.get(name) for name in names) for row in rows])


def seed_data(app) -> dict[str, int]:
    today = date.today()
    with app.db() as con:
        company_rows = []
        for index in range(COMPANIES):
            label = f"Benchmark společnost {index:04d}"
            company_rows.append(
                {
                    "short_name": f"BENCH-{index:04d}",
                    "official_name": label,
                    "ico": f"99{index:06d}",
                    "dic": "",
                    "address": f"Testovací {index}, Plzeň",
                    "legal_form": "s.r.o.",
                    "active": 1,
                }
            )
        company_rows.append(
            {
                "short_name": "MIVO",
                "official_name": "MIVO Benchmark",
                "ico": "",
                "dic": "",
                "address": "",
                "legal_form": "",
                "active": 1,
            }
        )
        insert_many(con, "companies", company_rows)
        company_ids = [
            int(row[0])
            for row in con.execute(
                "SELECT id FROM companies WHERE short_name LIKE 'BENCH-%' ORDER BY id"
            ).fetchall()
        ]
        mivo_id = int(
            con.execute(
                "SELECT id FROM companies WHERE official_name='MIVO Benchmark' ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        )

        project_rows = []
        for index in range(PROJECTS):
            project_rows.append(
                {
                    "name": f"Benchmark Akce {index:04d}",
                    "address": f"Projektová {index}, Plzeň",
                    "investor": f"Investor {index % 40:02d}",
                    "general_contractor": f"Generální dodavatel {index % 30:02d}",
                    "start_date": (today - timedelta(days=index % 400)).isoformat(),
                    "end_date": (today + timedelta(days=30 + index % 500)).isoformat(),
                    "note": "syntetický benchmark",
                    "created_by": "Jaroslav Kučera",
                    "active": 1,
                }
            )
        insert_many(con, "projects", project_rows)
        project_ids = [
            int(row[0])
            for row in con.execute(
                "SELECT id FROM projects WHERE name LIKE 'Benchmark Akce %' ORDER BY id"
            ).fetchall()
        ]

        statuses = ("Rozpracováno", "Čeká", "Nabídka", "Hotovo", "Zrušeno")
        action_rows = []
        for index in range(ACTIONS):
            action_rows.append(
                {
                    "name": f"Benchmark Příležitost {index:05d}",
                    "company_id": company_ids[index % len(company_ids)],
                    "project_id": project_ids[index % len(project_ids)],
                    "created_date": (today - timedelta(days=index % 365)).isoformat(),
                    "deadline": (today + timedelta(days=(index % 80) - 20)).isoformat(),
                    "status": statuses[index % len(statuses)],
                    "products": "Izolační nosníky; Akustika" if index % 2 else "Vibroizolace",
                    "next_step": "Benchmark",
                    "note": f"Poznámka {index}",
                    "updated_by": "Jaroslav Kučera",
                    "archived": 1 if index % 37 == 0 else 0,
                }
            )
        insert_many(con, "actions", action_rows)
        action_ids = [
            int(row[0])
            for row in con.execute(
                "SELECT id FROM actions WHERE name LIKE 'Benchmark Příležitost %' ORDER BY id"
            ).fetchall()
        ]

        request_rows = []
        for index in range(REQUESTS):
            asked = today - timedelta(days=index % 120)
            received = "" if index % 4 else (asked + timedelta(days=2)).isoformat()
            request_rows.append(
                {
                    "company_id": mivo_id if index % 8 == 0 else company_ids[index % len(company_ids)],
                    "requested_for_company_id": company_ids[(index + 17) % len(company_ids)],
                    "action_id": action_ids[index % len(action_ids)],
                    "asked_date": asked.isoformat(),
                    "received_date": received,
                    "item": f"Benchmark materiál {index % 90:03d}",
                    "note": "syntetický benchmark",
                    "mail_subject": f"Benchmark poptávka {index}",
                    "include_project_in_subject": 1,
                    "recipients_snapshot": f"kontakt{index % 200}@example.invalid",
                    "cc_snapshot": "",
                    "updated_by": "Jaroslav Kučera",
                    "assigned_user": "Jaroslav Kučera" if index % 3 else "Denisa Kovalová",
                    "no_response": 1 if index % 31 == 0 else 0,
                    "archived": 1 if index % 29 == 0 else 0,
                }
            )
        insert_many(con, "requests", request_rows)

        task_rows = []
        for index in range(TASKS):
            task_rows.append(
                {
                    "action_id": action_ids[index % len(action_ids)],
                    "due_date": (today + timedelta(days=(index % 45) - 10)).isoformat(),
                    "text": f"Benchmark úkol {index:05d}",
                    "note": "syntetický benchmark",
                    "assigned_user": "Jaroslav Kučera" if index % 2 else "Denisa Kovalová",
                    "created_by": "Jaroslav Kučera",
                    "done": 1 if index % 7 == 0 else 0,
                    "archived": 1 if index % 41 == 0 else 0,
                }
            )
        insert_many(con, "tasks", task_rows)

    return {
        "companies": len(company_ids) + 1,
        "projects": len(project_ids),
        "actions": len(action_ids),
        "requests": REQUESTS,
        "tasks": TASKS,
    }


def measure(window, page: str, method_name: str, tree_name: str) -> dict:
    window.show_page(page)
    window.update_idletasks()
    method = getattr(window, method_name)
    samples = []
    row_count = None
    for _ in range(2):
        started = time.perf_counter()
        method()
        window.update_idletasks()
        samples.append(time.perf_counter() - started)
        tree = getattr(window, tree_name, None)
        if tree is not None:
            row_count = len(tree.get_children(""))
    return {
        "page": page,
        "method": method_name,
        "rows": row_count,
        "samples_seconds": [round(value, 6) for value in samples],
        "best_seconds": round(min(samples), 6),
    }


def profile_rows(profile: cProfile.Profile, limit: int = 35) -> list[dict]:
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


def profile_request_refresh(window) -> list[dict]:
    window.show_page("requests")
    window.update_idletasks()
    profile = cProfile.Profile()
    profile.enable()
    window.refresh_requests()
    window.update_idletasks()
    profile.disable()
    return profile_rows(profile)


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_SCALE_RESULT", "")).strip()
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
    counts = seed_data(app)

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
        results = [
            measure(window, "actions", "refresh_actions", "action_tree"),
            measure(window, "requests", "refresh_requests", "request_tree"),
            measure(window, "mivo", "refresh_mivo_requests", "mivo_tree"),
            measure(window, "tasks", "refresh_tasks", "task_tree"),
            measure(window, "projects", "refresh_projects", "project_tree"),
            measure(window, "companies", "refresh_companies", "company_tree"),
        ]
        request_profile = profile_request_refresh(window)
        window.update_idletasks()
        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))
        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "seed_counts": counts,
                "results": results,
                "request_refresh_profile_repo_top": request_profile,
                "navigation_owner": str(getattr(app.App, "_turto_navigation_owner", "")),
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
