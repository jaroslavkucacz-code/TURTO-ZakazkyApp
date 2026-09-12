#!/usr/bin/env python3
"""Real-Windows/Tk regression for the remaining v740/v750 startup safety passes.

v750 delayed workspace rebuilds are already owned by ui_cleanup_793.  This test
also proves that startup_optimization suppresses only v740's redundant 80-ms
pass while preserving the passes that follow delayed v710 legacy work.
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
    if not isinstance(state, dict) or str(state.get("owner") or "") != owner:
        raise AssertionError(f"Context-menu owner drift for {owner}: {state!r}")
    menus = tuple(state.get("menus", ()))
    if len(menus) != 2 or not all(widget_exists(menu) for menu in menus):
        raise AssertionError(f"Incomplete live menu set for {owner}")
    command = str(state.get("command") or "")
    script = str(state.get("script") or "")
    if not command or not script or not tree.tk.call("info", "commands", command):
        raise AssertionError(f"Missing live Tcl callback for {owner}")
    if str(tree.bind("<Button-3>") or "") != script:
        raise AssertionError(f"Right-click binding drift for {owner}")
    return {"owner": owner, "menus": len(menus)}


def main() -> None:
    if not os.environ.get("TURTO_CRM_DATA_ROOT"):
        raise AssertionError("isolated TURTO_CRM_DATA_ROOT required")

    import app, data_location, runtime_bootstrap
    data_location.apply_to_app(app)
    app.cleanup_stale_test_session(); app.ensure_schema(); runtime_bootstrap.apply_all(app)
    app.ensure_schema(); app.ensure_test_user(); app.migrate_v41_visual_once()
    app.App.maybe_show_morning_overview = lambda self: None

    window = None
    callback_errors: list[str] = []
    try:
        window = app.App()

        v750 = tuple(getattr(window, "_turto_v750_rebuilds_coalesced", ()) or ())
        v740 = tuple(getattr(window, "_turto_v740_tidy_passes_coalesced", ()) or ())
        if v750 != (80, 260, 760, 1650):
            raise AssertionError(f"ui_cleanup v750 suppression drift: {v750!r}")
        if v740 != (80,):
            raise AssertionError(f"startup v740 suppression drift: {v740!r}")

        ui_policy = getattr(app, "V794_UI_OPTIMIZATION", {}) or {}
        startup_policy = getattr(app, "V794_STARTUP_OPTIMIZATION", {}) or {}
        if tuple(ui_policy.get("legacy_v750_delayed_rebuilds_suppressed", ())) != (80, 260, 760, 1650):
            raise AssertionError("v750 policy metadata drift")
        if tuple(startup_policy.get("v740_functional_tidy_passes_preserved_ms", ())) != (0, 260, 760, 1650):
            raise AssertionError("v740 preserved-pass metadata drift")
        if tuple(startup_policy.get("v740_redundant_tidy_passes_suppressed", ())) != (80,):
            raise AssertionError("v740 suppressed-pass metadata drift")

        def report_callback_exception(exc_type, exc, tb):
            callback_errors.append("".join(traceback.format_exception(exc_type, exc, tb)).strip())
        window.report_callback_exception = report_callback_exception

        # v710's final legacy writer runs at 1500 ms and v740's preserved cleanup
        # at 1650 ms.  Settle past both before validating the final UI.
        deadline = time.monotonic() + 2.2
        while time.monotonic() < deadline:
            window.update(); time.sleep(0.01)
        if callback_errors:
            raise AssertionError("Tk callback regression:\n" + "\n\n".join(callback_errors))

        menus = []
        for key, attr in (("actions", "action_tree"), ("requests", "request_tree"), ("mivo", "mivo_tree")):
            tree = getattr(window, attr, None)
            if not widget_exists(tree):
                raise AssertionError(f"Missing live tree {attr}")
            controls = tuple(getattr(window, f"_v750_{key}_archive_controls", ()) or ())
            if len(controls) != 3 or not all(widget_exists(control) for control in controls):
                raise AssertionError(f"Archive toolbar incomplete for {key}")
            state = menu_state(tree, f"v750:{key}")
            state["archive_controls"] = len(controls)
            menus.append(state)

        offer_tree = getattr(window, "offer_tree", None)
        if not widget_exists(offer_tree):
            raise AssertionError("Missing live offer tree")
        menus.append(menu_state(offer_tree, "v740:offers"))

        obsolete = {}
        for key in ("mivo", "offers"):
            page = getattr(window, "tabs", {}).get(key)
            if not widget_exists(page):
                raise AssertionError(f"Missing page {key}")
            values = [text for text in button_texts(page) if text == "Sloupce…"]
            obsolete[key] = values
            if values:
                raise AssertionError(f"Obsolete Sloupce… button survived on {key}")
        if widget_exists(getattr(window, "_v710_mivo_columns_button", None)):
            raise AssertionError("Legacy v710 MIVO columns button survived final cleanup")

        write_result({
            "ok": True,
            "platform": sys.platform,
            "v750_suppressed_ms": list(v750),
            "v740_suppressed_ms": list(v740),
            "v740_preserved_ms": list(startup_policy.get("v740_functional_tidy_passes_preserved_ms", ())),
            "menu_states": menus,
            "obsolete_columns_buttons": obsolete,
            "tk_callback_errors": callback_errors,
            "database": str(app.DB),
        })
    finally:
        if window is not None:
            try: window.destroy()
            except Exception: pass


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        write_result({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        raise
