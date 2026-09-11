#!/usr/bin/env python3
"""Trace the legacy call that overwrites the tuned dashboard status palette.

Development/CI only. Uses an isolated database and records repository stack frames
for status_active tag reconfiguration during refresh_dash().
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
TARGET_BG = "#B9D9EE"
TARGET_FG = "#103852"


def repo_frames(limit: int = 30) -> list[dict[str, object]]:
    result = []
    for frame in traceback.extract_stack(limit=limit)[:-2]:
        try:
            rel = Path(frame.filename).resolve().relative_to(REPO.resolve())
        except Exception:
            continue
        result.append(
            {
                "file": rel.as_posix(),
                "line": int(frame.lineno),
                "function": str(frame.name),
                "source": str(frame.line or "").strip(),
            }
        )
    return result


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

    root = app.App()
    events: list[dict[str, object]] = []
    try:
        root.apply_theme("Světlý", save=False)
        root.update_idletasks()
        tree = root.dash_tree
        tree_class = app.ttk.Treeview
        original = tree_class.tag_configure
        original_alias = getattr(tree_class, "tag_config", None)

        def traced(widget, tagname, option=None, **kwargs):
            if widget is tree and str(tagname) == "status_active" and kwargs:
                event = {
                    "background": str(kwargs.get("background", "")),
                    "foreground": str(kwargs.get("foreground", "")),
                    "frames": repo_frames(),
                }
                events.append(event)
            return original(widget, tagname, option, **kwargs)

        tree_class.tag_configure = traced
        if original_alias is original:
            tree_class.tag_config = traced
        try:
            root.refresh_dash()
            root.update_idletasks()
        finally:
            tree_class.tag_configure = original
            if original_alias is original:
                tree_class.tag_config = original_alias

        final = tree.tag_configure("status_active") or {}
        payload = {
            "ok": True,
            "final_background": str(final.get("background", "")),
            "final_foreground": str(final.get("foreground", "")),
            "events": events,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

        matching = [
            event for event in events
            if str(event.get("background", "")).upper() == TARGET_BG
            and str(event.get("foreground", "")).upper() == TARGET_FG
        ]
        if not matching:
            raise AssertionError(
                "Did not capture the known stale dashboard palette overwrite"
            )
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
