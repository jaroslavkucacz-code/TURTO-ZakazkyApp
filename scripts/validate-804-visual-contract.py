#!/usr/bin/env python3
"""Real-Windows visual regression contract for the stable TURTO CRM 8.x UI.

The 8.0.3 runtime cleanup deliberately suppresses one historical full-window
palette repaint after data refreshes. This probe verifies the presentation work
we spent time tuning remains owned by stable theme/style layers instead of that
redundant repaint.

CI/development only: uses an isolated database, disables automatic updates and
never opens the morning overview.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback


REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "ZakazkyApp_base_6.1"
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"

STATUS_PALETTES = {
    "Tmavý": {
        "status_active": ("#244E73", "#F4FAFF"),
        "status_offer": ("#176A63", "#F1FFFC"),
        "status_wait": ("#7A5A12", "#FFF5CF"),
        "status_done": ("#2D6A48", "#F2FFF7"),
        "status_cancel": ("#753743", "#FFF3F5"),
        "status_late": ("#8A3434", "#FFF3F3"),
        "status_soon": ("#7A5A12", "#FFF5CF"),
        "req_fresh": ("#7A5A12", "#FFF5CF"),
        "req_received": ("#176A63", "#F1FFFC"),
    },
    "Světlý": {
        "status_active": ("#CFE7FA", "#173A55"),
        "status_offer": ("#CBEDE7", "#124D48"),
        "status_wait": ("#F9E4A4", "#5B420C"),
        "status_done": ("#CDE9D8", "#1E4F35"),
        "status_cancel": ("#F0C9D0", "#66303A"),
        "status_late": ("#F3C1C1", "#6D2C2C"),
        "status_soon": ("#F9E4A4", "#5B420C"),
        "req_fresh": ("#F9E4A4", "#5B420C"),
        "req_received": ("#CBEDE7", "#124D48"),
    },
}

SELECTION = {
    "Tmavý": ("#2F6F9F", "#FFFFFF"),
    "Světlý": ("#A9D2F0", "#102C42"),
}

TREE_NAMES = (
    "dash_tree",
    "action_tree",
    "request_tree",
    "mivo_tree",
    "offer_tree",
    "task_tree",
    "project_tree",
    "people_tree",
    "company_tree",
)

REFRESH_METHODS = (
    "refresh_dash",
    "refresh_actions",
    "refresh_requests",
    "refresh_mivo_requests",
    "refresh_offers",
    "refresh_tasks",
    "refresh_projects",
    "refresh_people",
    "refresh_companies",
)


def norm(value) -> str:
    return str(value or "").strip().upper()


def selected_color(style, style_name: str, option: str) -> str:
    try:
        rows = style.map(style_name, query_opt=option) or []
    except Exception:
        rows = []
    for row in rows:
        values = tuple(str(item) for item in row)
        if any(item == "selected" for item in values[:-1]):
            return norm(values[-1])
    return ""


def row_height(style, style_name: str) -> int:
    try:
        value = (style.configure(style_name) or {}).get("rowheight", "")
        return int(float(str(value)))
    except Exception:
        return 0


def tag_option(tree, tag: str, option: str) -> str:
    """Read a ttk.Treeview tag option using Tkinter's supported API."""
    try:
        config = tree.tag_configure(tag) or {}
        return str(config.get(option, "") or "")
    except Exception:
        return ""


def walk(widget):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from walk(child)
    except Exception:
        return


def theme_combobox_values(window) -> tuple[str, ...]:
    variable = str(getattr(window, "theme", ""))
    try:
        page = window.tabs["settings"]
    except Exception:
        return ()
    for widget in walk(page):
        try:
            if widget.winfo_class() != "TCombobox":
                continue
            if str(widget.cget("textvariable")) != variable:
                continue
            return tuple(str(value) for value in widget.cget("values"))
        except Exception:
            continue
    return ()


def assert_tree_palette(window, theme: str) -> dict[str, dict]:
    style = window.ttk.Style(window) if hasattr(window, "ttk") else None
    if style is None:
        import tkinter.ttk as ttk
        style = ttk.Style(window)

    expected = STATUS_PALETTES[theme]
    selected_bg, selected_fg = SELECTION[theme]
    results = {}
    for name in TREE_NAMES:
        tree = getattr(window, name, None)
        if tree is None:
            raise AssertionError(f"Missing tuned Treeview: {name}")
        style_name = str(tree.cget("style") or "Treeview")
        height = row_height(style, style_name)
        if height != 30:
            raise AssertionError(f"{name}: rowheight {height}, expected 30")

        bg = selected_color(style, style_name, "background")
        fg = selected_color(style, style_name, "foreground")
        if bg != norm(selected_bg) or fg != norm(selected_fg):
            raise AssertionError(
                f"{name}: selected colors {(bg, fg)!r}, expected {(selected_bg, selected_fg)!r}"
            )

        tag_results = {}
        for tag, (expected_bg, expected_fg) in expected.items():
            actual_bg = norm(tag_option(tree, tag, "background"))
            actual_fg = norm(tag_option(tree, tag, "foreground"))
            if actual_bg != norm(expected_bg) or actual_fg != norm(expected_fg):
                raise AssertionError(
                    f"{name}/{tag}: {(actual_bg, actual_fg)!r}, "
                    f"expected {(expected_bg, expected_fg)!r}"
                )
            tag_results[tag] = {"background": actual_bg, "foreground": actual_fg}

        results[name] = {
            "style": style_name,
            "rowheight": height,
            "selected_background": bg,
            "selected_foreground": fg,
            "tags": tag_results,
        }
    return results


def assert_calibri_contract(window) -> dict[str, str]:
    import tkinter.ttk as ttk

    style = ttk.Style(window)
    muted_font = str((style.configure("Muted.TLabel") or {}).get("font", ""))
    if "calibri" not in muted_font.casefold():
        raise AssertionError(f"Muted.TLabel lost Calibri: {muted_font!r}")

    # refresh_requests owns both current request emphasis tags directly. v770
    # uses Calibri bold for the older overdue warning, while historical v637
    # uses red Calibri bold after more than three unanswered days.
    window.refresh_requests()
    window.update_idletasks()
    attention_font = tag_option(window.request_tree, "v770_request_attention", "font")
    if "calibri" not in attention_font.casefold() or "bold" not in attention_font.casefold():
        raise AssertionError(
            f"Request attention tag lost Calibri bold formatting: {attention_font!r}"
        )

    urgent_font = tag_option(window.request_tree, "deadline_urgent", "font")
    urgent_foreground = norm(tag_option(window.request_tree, "deadline_urgent", "foreground"))
    if "calibri" not in urgent_font.casefold() or "bold" not in urgent_font.casefold():
        raise AssertionError(
            f"Urgent request tag lost Calibri bold formatting: {urgent_font!r}"
        )
    if urgent_foreground != "#C62828":
        raise AssertionError(
            f"Urgent request foreground regressed: {urgent_foreground!r}, expected '#C62828'"
        )

    help_font = ""
    try:
        help_font = str(window.help_text.cget("font") or "")
        if "calibri" not in help_font.casefold():
            raise AssertionError(f"Help text lost Calibri: {help_font!r}")
    except Exception:
        # Some Tk builds expose a named font here. Resolve it through Tk before
        # deciding the family is not Calibri.
        try:
            import tkinter.font as tkfont
            actual = tkfont.Font(window, font=window.help_text.cget("font")).actual("family")
            help_font = str(actual)
            if "calibri" not in help_font.casefold():
                raise AssertionError(f"Help text lost Calibri: {help_font!r}")
        except AssertionError:
            raise
        except Exception as exc:
            raise AssertionError(f"Could not verify help font: {exc}") from exc

    return {
        "muted_label_font": muted_font,
        "request_attention_font": attention_font,
        "urgent_request_font": urgent_font,
        "urgent_request_foreground": urgent_foreground,
        "help_font": help_font,
    }


def exercise_refreshes(window, theme: str) -> list[str]:
    """Run every main-page refresh and identify the first visual overwrite."""
    completed = []
    for name in REFRESH_METHODS:
        method = getattr(window, name, None)
        if not callable(method):
            raise AssertionError(f"Missing refresh method: {name}")
        method()
        window.update_idletasks()
        try:
            assert_tree_palette(window, theme)
        except AssertionError as exc:
            raise AssertionError(f"after {name}: {exc}") from exc
        completed.append(name)
    return completed


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_VISUAL_RESULT", "")).strip()
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

        if not str(window.title()).startswith("TURTO CRM"):
            raise AssertionError(f"Visible branding regressed: {window.title()!r}")

        themes = theme_combobox_values(window)
        if set(themes) != {"Světlý", "Tmavý"} or len(themes) != 2:
            raise AssertionError(f"Theme selector regressed: {themes!r}")

        calendar_name = str(getattr(app.DatePicker.open_calendar, "__name__", ""))
        calendar_module = str(getattr(app.DatePicker.open_calendar, "__module__", ""))
        if calendar_name != "_theme_aware_calendar" or "ui_polish_801" not in calendar_module:
            raise AssertionError(
                f"DatePicker lost theme-aware calendar: {calendar_module}.{calendar_name}"
            )

        calibri = assert_calibri_contract(window)
        theme_results = {}
        for theme in ("Světlý", "Tmavý"):
            window.apply_theme(theme, save=False)
            window.update_idletasks()
            before = assert_tree_palette(window, theme)
            refreshed = exercise_refreshes(window, theme)
            after = assert_tree_palette(window, theme)
            if before != after:
                raise AssertionError(f"{theme}: visual Treeview contract changed after refresh")
            theme_results[theme] = {
                "before_refresh": before,
                "after_refresh": after,
                "refreshes": refreshed,
            }

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))

        write_result(
            {
                "ok": True,
                "platform": sys.platform,
                "app_version": str(getattr(app, "APP_VERSION", "")),
                "branding_title": str(window.title()),
                "theme_selector": list(themes),
                "date_picker": f"{calendar_module}.{calendar_name}",
                "calibri": calibri,
                "themes": theme_results,
                "tk_callback_errors": callback_errors,
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
