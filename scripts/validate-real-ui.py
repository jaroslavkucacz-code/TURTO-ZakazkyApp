#!/usr/bin/env python3
"""Run the real TURTO Tk application under Xvfb and stress tab navigation."""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import time
import traceback


def main() -> None:
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    repository = source.parent
    home = pathlib.Path(tempfile.mkdtemp(prefix="turto6331_real_ui_"))
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    # The navigation test must never contact or install from the live release
    # channel. Automatic updating has its own deterministic regression test.
    os.environ["TURTO_DISABLE_AUTO_UPDATE"] = "1"
    os.chdir(source)
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(repository))

    import app
    import crm_features
    import crm_runtime
    import crm_v605
    import crm_price_lists
    import v606_features
    import v608_stability
    import v611_audit
    import v613_ui
    import v614_next
    import v615_input
    import v616_stability
    import v617_offerhub
    import v618_inputfix
    import v619_fixes
    import v620_outlookdrop
    import v621_prices
    import v623_exports
    import v624_legacy_exports
    import v625_stability
    import v628_modernui_resize
    import v631_diskdrop
    import v632_offerlinks
    import v633_offerassign_deadlines
    import v636_action_offers_stabletable
    import v637_project_offer_model
    import v638_table_updatefix
    import v640_warning_cleanup
    import v644_default_date_sort
    import post_baseline

    callback_errors = []
    dialog_errors = []

    def quiet(*args, **kwargs):
        if args:
            dialog_errors.append(" | ".join(str(value) for value in args[:2]))
        return False

    for name in ("showerror", "showwarning", "showinfo"):
        setattr(app.messagebox, name, quiet)
    app.messagebox.askyesno = lambda *args, **kwargs: False
    app.messagebox.askokcancel = lambda *args, **kwargs: False

    # crm_runtime initializes its ADMIN tables immediately. Existing customer
    # installations already contain the base schema; create the same baseline in
    # this isolated HOME before applying the runtime wrappers.
    app.cleanup_stale_test_session()
    app.ensure_schema()

    # Match the generated ZakazkyCRM.pyw layer order.
    crm_features.apply(app)
    crm_runtime.apply(app)
    crm_v605.apply(app)
    v606_features.apply(app)
    v608_stability.apply(app)
    v611_audit.apply(app)
    v613_ui.apply(app)
    v614_next.apply(app)
    v615_input.apply(app)
    v616_stability.apply(app)
    v617_offerhub.apply(app)
    v618_inputfix.apply(app)
    v619_fixes.apply(app)
    v620_outlookdrop.apply(app)
    v621_prices.apply(app)
    v623_exports.apply(app)
    v625_stability.apply(app)
    v628_modernui_resize.apply(app)
    v632_offerlinks.apply(app)
    v633_offerassign_deadlines.apply(app)
    v636_action_offers_stabletable.apply(app)
    v637_project_offer_model.apply(app)
    v638_table_updatefix.apply(app)
    v640_warning_cleanup.apply(app)
    post_baseline.apply(app)
    v631_diskdrop.apply(app)
    v644_default_date_sort.apply(app)
    crm_features.install_offer_ui(app)
    crm_price_lists.apply(app)

    # Run the fully wrapped schema owner once more for additive platform tables.
    app.ensure_schema()
    app.ensure_test_user()
    try:
        app.set_setting("active_user", "TEST")
    except Exception:
        pass

    # The production morning overview is intentionally modal. It is unrelated to
    # navigation and would wait forever in a headless stress test with no user to
    # close it, so suppress only this test-time callback.
    app.App.maybe_show_morning_overview = lambda self: None

    root = None
    try:
        root = app.App()
        root.withdraw()

        def callback_exception(exc_type, exc_value, exc_tb):
            callback_errors.append("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))

        root.report_callback_exception = callback_exception

        # Let delayed startup work, including older one-off layout callbacks,
        # complete before the actual stress cycle.
        until = time.monotonic() + 1.7
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)

        assert getattr(root, "_turto_navigation_owner", "") == "price_lists_domain.platform.lazy_refresh"
        keys = [key for key in (
            "dash", "actions", "requests", "mivo", "offers", "pricelists",
            "companies", "projects", "tasks", "people", "help", "settings",
        ) if key in root.tabs]
        assert len(keys) >= 10, keys

        started = time.monotonic()
        for index in range(240):
            root.show_page(keys[index % len(keys)])
        root.show_page("dash")
        click_elapsed = time.monotonic() - started
        assert click_elapsed < 1.5, f"240 tab switches took {click_elapsed:.3f} s"

        # Process the one debounced final refresh and all resulting idle work.
        until = time.monotonic() + 2.5
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)

        assert root._current_page == "dash"
        assert not callback_errors, "\n".join(callback_errors)

        # Reproduce the attached-log failure path: a delayed notification
        # refresh must ignore an already destroyed button.
        bell = getattr(root, "bell_button", None)
        if bell is not None and bell.winfo_exists():
            bell.destroy()
        root.refresh_notifications()
        root.update()
        assert not callback_errors, "\n".join(callback_errors)

        # Dialog errors during startup indicate a real integration failure.
        assert not dialog_errors, dialog_errors
        print(f"TURTO CRM 6.3.31 real Tk navigation test: OK ({click_elapsed:.3f} s / 240 clicks)")
    finally:
        try:
            if root is not None and root.winfo_exists():
                root.close_app()
                root.update()
        except Exception:
            try:
                root.destroy()
            except Exception:
                pass
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
