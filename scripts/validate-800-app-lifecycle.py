#!/usr/bin/env python3
"""Validate the single-owner App.__init__ lifecycle introduced for CRM 8.0."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    lifecycle = _load(source / "app_lifecycle.py", "turto_app_lifecycle_test")

    events: list[str] = []

    class App:
        def __init__(self, marker="base"):
            events.append(marker)

    M = SimpleNamespace(App=App)
    lifecycle.apply(M)
    lifecycle.register(
        M,
        "first",
        before=lambda _app, _args, _kwargs: events.append("pre:first"),
        after=lambda _app, _result, _args, _kwargs: events.append("post:first"),
    )
    lifecycle.register(
        M,
        "second",
        before=lambda _app, _args, _kwargs: events.append("pre:second"),
        after=lambda _app, _result, _args, _kwargs: events.append("post:second"),
    )
    App()
    assert events == [
        "pre:second",
        "pre:first",
        "base",
        "post:first",
        "post:second",
    ], events

    # Re-registering a named hook updates it without changing order or stacking
    # another App.__init__ wrapper.
    wrapped = M.App.__init__
    lifecycle.register(
        M,
        "first",
        after=lambda _app, _result, _args, _kwargs: events.append("post:first:v2"),
    )
    assert M.App.__init__ is wrapped
    assert [hook.name for hook in M.APP_INIT_HOOKS] == ["first", "second"]

    bootstrap = (source / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert '_apply("app_lifecycle", M)' in bootstrap
    assert bootstrap.index('_apply("app_lifecycle", M)') < bootstrap.index('for name in EARLY_LAYERS:')

    migrated = (
        "crm_features.py",
        "crm_runtime.py",
        "v608_stability.py",
        "v620_outlookdrop.py",
        "v623_exports.py",
        "v625_stability.py",
        "v628_modernui_resize.py",
        "v632_offerlinks.py",
        "v636_action_offers_stabletable.py",
        "v637_project_offer_model.py",
        "v638_table_updatefix.py",
        "v640_warning_cleanup.py",
        "v631_diskdrop.py",
        "v740_offer_defaults.py",
        "v750_context_filters_offer_format.py",
        "price_lists_domain/issued_offers/professional_workflow.py",
        "v770_runtime_policy.py",
        "v710_cleanup.py",
        "price_lists_domain/platform/automatic_updates.py",
    )
    for filename in migrated:
        text = (source / filename).read_text(encoding="utf-8")
        assert ("register_app_init_hook(" in text or "app_lifecycle.register(" in text), filename
        assert "M.App.__init__ =" not in text, filename
        assert "module.App.__init__=" not in text.replace(" ", ""), filename

    for filename in ("v644_default_date_sort.py", "v760_table_activity_performance.py"):
        text = (source / filename).read_text(encoding="utf-8")
        assert "App.__init__ =" not in text, filename
        assert "M.App.__init__ =" not in text, filename


    assignments = []
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            compact = line.replace(" ", "")
            if "App.__init__=" in compact or "M.App.__init__=" in compact:
                assignments.append((path.relative_to(source).as_posix(), lineno, line.strip()))
    assert assignments == [("app_lifecycle.py", 67, "M.App.__init__ = lifecycle_init")], assignments

    post_baseline = source.parent / "post_baseline.py"
    if post_baseline.exists():
        text = post_baseline.read_text(encoding="utf-8")
        assert "App.__init__ =" not in text
        assert "register_app_init_hook" in text

    print("OK: App lifecycle order, idempotent registration and migrated prefix ownership")


if __name__ == "__main__":
    main()
