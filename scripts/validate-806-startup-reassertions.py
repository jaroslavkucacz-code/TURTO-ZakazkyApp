#!/usr/bin/env python3
"""Real-Windows/Tk regression for coalesced v740/v750 startup safety passes.

Runs only on an isolated CI data root. The optimization is deliberately
fail-closed: exact historical callback origins are suppressed, while the first
v750 workspace pass and the v740 passes that follow v710 legacy writers remain.
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


def write_result(payload: dict) -> None:
    target = str(os.environ.get("TURTO_CRM_806_REASSERT_RESULT", "")).strip()
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text, end="")


def widget_exists(widget) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def button_texts(root) -> list[str]:
    result: list[str] = []
    stack = [root]
    while stack:
        widget = stack.pop()
        try:
            children = list(widget.winfo_children())
        except Exception:
            continue
        stack.extend(children)
        for child in children:
            try:
                if child.winfo_class().endswith(("Button", "Checkbutton")):
                    result.append(str(child.cget("text") or "").strip())
            except Exception:
                pass
    return result


def menu_state(tree, owner: str) -> dict:
    state = getattr(tree, "_turto_context_menu_binding", None)
    if not isinstance(state, dict):
        raise AssertionError(f"Missing context-menu lifecycle state for {owner}")
    if str(state.get("owner") or "") != owner:
        raise AssertionError(f"Unexpected menu owner {state.get('owner')!r}, expected {owner!r}")
    menus = tuple(state.get("menus", ()))
    if len(menus) != 2 or not all(widget_exists(menu) for menu in menus):
        raise AssertionError(f"Incomplete live menu set for {owner}")
    command = str(state.get("command") or "")
    script = str(state.get("script") or "")
    if not command or not script:
        raise AssertionError(f"Missing Tcl callback for {owner}")
    try:
        if not tree.tk.call("info", "commands", command):
            raise AssertionError(f"Dead Tcl callback for {owner}")
        if str(tree.bind("<Button-3>") or "") != script:
            raise AssertionError(f"Right-click binding drift for {owner}")
    except AssertionError:
        raise
    except Exception as exc:
        raise AssertionError(f"Cannot validate context menu for {owner}: {exc}") from exc
    return {"owner": owner, "menus": len(menus), "callback": command}


def main() -> None:
    if not os.environ.get("TURTO_CRM_DATA_ROOT"):
        raise AssertionError("TURTO_CRM_DATA_ROOT must point to an isolated CI directory")

    import app
    import data_location
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

        v750 = tuple(getattr(window, "_turto_v750_workspace_passes_coalesced", ()) or ())
        v740 = tuple(getattr(window, "_turto_v740_tidy_passes_coalesced", ()) or ())
        if v750 != (80, 260, 760, 1650):
            raise AssertionError(f"Unexpected v750 coalesced passes: {v750!r}")
        if v740 != (80,):
            raise AssertionError(f"Unexpected v740 coalesced passes: {v740!r}")

        policy = getattr(app, "V794_STARTUP_OPTIMIZATION", {}) or {}
        if tuple(policy.get("v750_redundant_workspace_passes_suppressed", ())) != (80, 260, 760, 1650):
            raise AssertionError("v750 startup policy metadata drift")
        if tuple(policy.get("v740_functional_tidy_passes_preserved_ms", ())) != (0, 260, 760, 1650):
            raise AssertionError("v740 preserved-pass metadata drift")
        if tuple(policy.get("v740_redundant_tidy_passes_suppressed", ())) != (80,):
            raise AssertionError("v740 suppressed-pass metadata drift")

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append("".join(traceback.format_exception(exc_type, exc, tb)).strip())

        window.report_callback_exception = report_callback_exception

        # Allow all preserved v710/v740 startup passes (through 1650 ms) and
        # ordinary zero-delay v750 setup to run on real Tk.
        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)

        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))

        results = []
        for key, attr in (("actions", "action_tree"), ("requests", "request_tree"), ("mivo", "mivo_tree")):
            tree = getattr(window, attr, None)
            if not widget_exists(tree):
                raise AssertionError(f"Missing live tree {attr}")
            controls = tuple(getattr(window, f"_v750_{key}_archive_controls", ()) or ())
            if len(controls) != 3 or not all(widget_exists(control) for control in controls):
                raise AssertionError(f"Archive toolbar incomplete for {key}: {len(controls)}")
            state = menu_state(tree, f"v750:{key}")
            state["archive_controls"] = len(controls)
            results.append(state)

        offer_tree = getattr(window, "offer_tree", None)
        if not widget_exists(offer_tree):
            raise AssertionError("Missing live offer_tree")
        results.append(menu_state(offer_tree, "v740:offers"))

        obsolete: dict[str, list[str]] = {}
        for key in ("mivo", "offers"):
            page = getattr(window, "tabs", {}).get(key)
            if not widget_exists(page):
                raise AssertionError(f"Missing page {key}")
            texts = [text for text in button_texts(page) if text == "Sloupce…"]
            obsolete[key] = texts
            if texts:
                raise AssertionError(f"Obsolete Sloupce… button survived on {key}: {texts!r}")

        legacy_button = getattr(window, "_v710_mivo_columns_button", None)
        if widget_exists(legacy_button):
            raise AssertionError("Legacy v710 MIVO Sloupce… button survived final v740 cleanup")

        write_result({
            "ok": True,
            "platform": sys.platform,
            "v750_coalesced_ms": list(v750),
            "v740_coalesced_ms": list(v740),
            "v740_preserved_ms": list(policy.get("v740_functional_tidy_passes_preserved_ms", ())),
            "menu_states": results,
            "obsolete_columns_buttons": obsolete,
            "tk_callback_errors": callback_errors,
            "database": str(app.DB),
        })
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
        write_result({
            "ok": False,
            "exception_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })
        raise
