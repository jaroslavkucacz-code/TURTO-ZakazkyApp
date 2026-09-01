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
    import v710_cleanup
    import v720_visual_offer
    import v730_polish
    import v740_offer_defaults
    import v750_context_filters_offer_format

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
    v710_cleanup.apply(app)
    v720_visual_offer.apply(app)
    v730_polish.apply(app)
    v740_offer_defaults.apply(app)
    v750_context_filters_offer_format.apply(app)

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

    # One legacy Windows-only startup layer requests wm_state('zoomed'). X11/Tk
    # supports only normal/iconic/withdrawn, so preserve the call on Windows and
    # translate it to a harmless current-state read in this Linux/Xvfb test.
    original_state = app.App.state

    def portable_state(self, newstate=None):
        if newstate == "zoomed" and not sys.platform.startswith("win"):
            return original_state(self)
        if newstate is None:
            return original_state(self)
        return original_state(self, newstate)

    app.App.state = portable_state

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
        mivo_tree = getattr(root, "mivo_tree", None)
        assert mivo_tree is not None and mivo_tree.winfo_exists()
        assert bool(getattr(mivo_tree, "_turto_configurable_columns", False))
        assert bool(getattr(mivo_tree, "_v700_columns_menu", False))
        assert getattr(root, "_v710_mivo_columns_button", None) is None
        assert "help" not in root.nav
        assert getattr(root, "help_button", None) is not None
        assert root.help_button.winfo_exists()

        def control_labels(widget):
            labels = []
            for child in widget.winfo_children():
                try:
                    if child.winfo_class().endswith(("Button", "Checkbutton")):
                        labels.append(str(child.cget("text") or "").strip())
                except Exception:
                    pass
                labels.extend(control_labels(child))
            return labels

        forbidden_by_tab = {
            "actions": {"🗑 Smazat", "🔔 Připomínka", "✉ Poptat", "✎ Editovat"},
            "requests": {
                "🗑 Smazat", "✎ Editovat", "Vytvořit e-mail",
                "Obdrženo dnes", "Bez odezvy",
            },
            "mivo": {
                "🗑 Smazat", "✎ Editovat", "Vytvořit e-mail",
                "Obdrženo dnes", "Bez odezvy",
            },
        }
        for tab_key, forbidden in forbidden_by_tab.items():
            labels = set(control_labels(root.tabs[tab_key]))
            assert not labels.intersection(forbidden), (tab_key, labels)
            assert "Zobrazit archivované" in labels
            assert "📦 Archivovat vybrané" in labels
            assert "↩ Obnovit vybrané" in labels
        assert getattr(root.action_tree, "_v750_context_owner", None) == "actions"
        assert getattr(root.request_tree, "_v750_context_owner", None) == "requests"
        assert getattr(root.mivo_tree, "_v750_context_owner", None) == "mivo"
        with app.db() as con:
            action_columns = {
                str(row[1]) for row in con.execute("PRAGMA table_info(actions)")
            }
            assert {"archived", "archived_at", "archived_by"} <= action_columns

        def button_labels(widget):
            labels = []
            for child in widget.winfo_children():
                try:
                    if child.winfo_class().endswith("Button"):
                        labels.append(str(child.cget("text") or "").strip())
                except Exception:
                    pass
                labels.extend(button_labels(child))
            return labels

        assert "Sloupce…" not in button_labels(root.tabs["mivo"])
        for column in mivo_tree["columns"]:
            assert str(mivo_tree.heading(column, "text") or "").strip(), column
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

        # The current-price page must expose the 6.3.39 hierarchy, SQL sort and
        # direct-edit controls in the fully composed production application.
        root.show_page("pricelists")
        until = time.monotonic() + 1.0
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)
        assert root._current_page == "pricelists"
        price_taxonomy = getattr(root, "price_taxonomy_tree", None)
        assert price_taxonomy is not None and price_taxonomy.winfo_exists()
        assert price_taxonomy.exists("pt_all") and price_taxonomy.exists("pt_unassigned")
        assert any(str(iid).startswith("pt_g") for iid in price_taxonomy.get_children(""))
        assert getattr(root, "price_sort_mode", None) is not None
        assert getattr(root, "price_undo_move_button", None) is not None
        assert getattr(root, "price_edit_product_button", None) is not None
        assert not callback_errors, "\n".join(callback_errors)
        root.show_page("dash")
        root.update()

        # Open the actual catalogue against the isolated additive schema. This
        # catches modal-grab, SQL-column and Treeview integration regressions.
        root.open_product_catalog()
        root.update()
        catalogue_windows = [
            child for child in root.winfo_children()
            if isinstance(child, app.tk.Toplevel) and child.winfo_exists() and child.title() == "Katalog produktů"
        ]
        assert len(catalogue_windows) == 1, catalogue_windows
        catalogue = catalogue_windows[0]

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        catalogue_trees = [widget for widget in walk(catalogue) if isinstance(widget, app.ttk.Treeview)]
        assert len(catalogue_trees) >= 2, "Katalog produktů musí obsahovat strom skupin i tabulku produktů"
        required_product_columns = {
            "Výrobce", "Interní kód", "Interní označení", "Produktová skupina", "Podskupina",
            "Marže", "Sleva", "Výsledná cena",
        }
        product_trees = [tree for tree in catalogue_trees if required_product_columns.issubset(set(tree["columns"]))]
        structure_trees = [
            tree for tree in catalogue_trees
            if {"Produktů", "Ceníků"}.issubset(set(tree["columns"]))
            and "Nabídek" not in set(tree["columns"])
            and not required_product_columns.issubset(set(tree["columns"]))
        ]
        assert len(product_trees) == 1, [set(tree["columns"]) for tree in catalogue_trees]
        assert len(structure_trees) == 1, [set(tree["columns"]) for tree in catalogue_trees]
        structure = structure_trees[0]
        assert structure.exists("all") and structure.exists("unassigned")
        assert any(str(iid).startswith("g") for iid in structure.get_children(""))
        workspace_api = getattr(catalogue, "_turto_product_workspace", None)
        assert workspace_api and workspace_api["structure_tree"] is structure
        assert workspace_api["product_tree"] is product_trees[0]
        assert callable(workspace_api.get("undo_last_move"))
        assert workspace_api.get("sort_mode") is not None
        catalogue.destroy()
        root.update()
        assert not callback_errors, "\n".join(callback_errors)

        # The hierarchy manager is modal by design. Schedule inspection and close
        # it from inside Tk's nested event loop to verify the real split editor.
        from price_lists_domain.platform import categories as category_manager
        manager_result = {}

        def inspect_category_manager():
            manager = next((
                child for child in root.winfo_children()
                if isinstance(child, app.tk.Toplevel) and child.winfo_exists()
                and child.title() == "Produktové skupiny a podskupiny"
            ), None)
            try:
                assert manager is not None
                manager_trees = [widget for widget in walk(manager) if isinstance(widget, app.ttk.Treeview)]
                assert len(manager_trees) == 1
                assert {"Typ", "Stav", "Produktů", "Ceníků", "Nabídek"}.issubset(
                    set(manager_trees[0]["columns"])
                )
                manager_result["ok"] = True
            except Exception:
                manager_result["error"] = traceback.format_exc()
            finally:
                if manager is not None and manager.winfo_exists():
                    manager.destroy()

        root.after(80, inspect_category_manager)
        category_manager.manage_categories(app, root)
        assert manager_result.get("ok"), manager_result.get("error") or manager_result
        root.update()
        assert not callback_errors, "\n".join(callback_errors)

        # Received offers expose the same persistent column manager as other
        # commercial tables, and company records support deliberate two-row merge.
        offer_tree = getattr(root, "offer_tree", None)
        assert offer_tree is not None and offer_tree.winfo_exists()
        assert bool(getattr(offer_tree, "_turto_configurable_columns", False))
        assert getattr(root, "_v730_offer_table_tools", None) is not None
        assert bool(getattr(offer_tree, "_v740_context_owner", False))
        assert "Sloupce…" not in button_labels(root.tabs["offers"])
        company_tree = getattr(root, "company_tree", None)
        assert company_tree is not None and company_tree.winfo_exists()
        assert str(company_tree.cget("selectmode")) == "extended"
        assert getattr(root, "_v730_company_merge_button", None) is not None
        with app.db() as con:
            columns = {str(row[1]) for row in con.execute("PRAGMA table_info(companies)")}
            assert {"merged_into_company_id", "merged_at", "merged_by"} <= columns
            assert con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='company_merge_history'"
            ).fetchone()

        # Poptávky: a manually chosen width must survive refresh/page switches,
        # and the release handler that persists a real separator drag must still
        # be registered after all delayed legacy startup work has completed.
        request_tree = getattr(root, "request_tree", None)
        assert request_tree is not None and request_tree.winfo_exists()
        assert request_tree.bind("<ButtonRelease-1>"), "Chybí ukládání šířky po tažení"
        width_column = "Dodavatel"
        request_tree._turto_design_widths[width_column] = 347
        request_tree.column(width_column, width=347)
        app.save_persistent_tree_layout(request_tree)
        root.refresh_requests()
        root.show_page("requests")
        until = time.monotonic() + 0.8
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)
        assert int(request_tree._turto_design_widths[width_column]) == 347
        assert int(request_tree.column(width_column, "width")) == 347

        # Filter cells must follow displaycolumns and hidden columns.
        filter_map = dict(zip(
            getattr(request_tree, "_filter_cell_columns", ()),
            getattr(request_tree, "_filter_cells", ()),
        ))
        candidates = [column for column in request_tree["columns"] if column in filter_map]
        assert len(candidates) >= 3, candidates
        first, hidden, second = candidates[:3]
        request_tree.configure(displaycolumns=(second, first))
        request_tree._sync_filter_bar()
        root.update()
        assert not filter_map[hidden].place_info(), hidden
        assert int(filter_map[second].place_info()["x"]) < int(
            filter_map[first].place_info()["x"]
        )
        request_tree.configure(displaycolumns="#all")
        request_tree._sync_filter_bar()
        root.update()
        assert filter_map[hidden].place_info(), hidden

        # Open the real visual issued-offer editor without saving. Its canvas is
        # rendered by the production PDF renderer and therefore must not reserve
        # a CN number, create a document or record a PDF revision.
        from price_lists_domain.issued_offers import service as issued_service
        preview_number = issued_service.preview_document_number(app, "2026-09-01")
        editor = root.open_issued_offer_editor(
            initial_document={
                "customer_name_snapshot": "TEST ODBĚRATEL",
                "offer_subject": "Vizuální kontrola",
                "issue_date": "2026-09-01",
            },
            initial_items=[
                issued_service.normalize_item(
                    {
                        "row_type": "product",
                        "name": "Testovací výrobek",
                        "product_code": "T-001",
                        "quantity": 2,
                        "unit": "ks",
                        "purchase_unit_price": 100,
                        "margin_pct": 25,
                        "discount_pct": 10,
                        "vat_rate": 21,
                    },
                    recalculate_sale=True,
                )
            ],
        )
        assert getattr(editor, "_v720_preview", None) is not None
        assert getattr(editor, "_v720_internal_panel", None) is not None
        assert getattr(editor, "_v720_mode_button", None) is not None
        assert {"Zákl. marže", "Zákl. sleva", "Zdroj základu"}.issubset(
            set(editor.tree["columns"])
        )
        assert getattr(editor._v720_internal_panel, "_v740_basis", None) is not None
        assert getattr(editor, "page_format_label", None) is not None
        assert "A4" in str(editor.page_format_label.cget("text"))
        assert bool(getattr(editor.tree, "_v750_context_owner", False))
        until = time.monotonic() + 1.8
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)
        visual = editor._v720_preview
        assert visual.images, "Vizuální editor nevykreslil produkční PDF"
        assert visual.canvas.find_all()
        assert getattr(visual, "_turto_v730_preview", False)
        # Repeated zoom and redraw used to reuse a stale PyMuPDF font resource.
        # Every cycle must keep an actual page image and report no render error.
        for delta in (10, -10, 20, -20, 10, -10):
            visual.change_zoom(delta)
            until = time.monotonic() + 0.65
            while time.monotonic() < until:
                root.update()
                time.sleep(0.01)
            assert visual.images and visual.canvas.find_all()
            assert not getattr(visual, "_v730_last_error", ""), visual._v730_last_error
        visual.set_zoom_100()
        until = time.monotonic() + 0.7
        while time.monotonic() < until:
            root.update()
            time.sleep(0.01)
        assert visual.zoom == 100
        assert visual.images and visual.canvas.find_all()
        assert not getattr(visual, "_v730_last_error", ""), visual._v730_last_error
        visual.select(0)
        panel = editor._v720_internal_panel
        panel.margin.set("30")
        panel.discount.set("5")
        panel.apply(True)
        assert abs(float(editor.items[0]["margin_pct"]) - 30.0) < 1e-9
        assert abs(float(editor.items[0]["discount_pct"]) - 5.0) < 1e-9
        with app.db() as con:
            assert int(con.execute("SELECT COUNT(*) FROM business_documents").fetchone()[0]) == 0
            assert int(con.execute("SELECT COUNT(*) FROM business_document_revisions").fetchone()[0]) == 0
        assert issued_service.preview_document_number(app, "2026-09-01") == preview_number
        editor.win.destroy()
        root.update()
        assert not callback_errors, "\n".join(callback_errors)

        price_browser = root.open_product_prices()
        root.update()
        assert getattr(price_browser, "supplier_filter", None) is not None
        assert price_browser.supplier_filter.get() == "Všichni dodavatelé"
        price_browser.destroy()
        root.update()

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
        print(f"TURTO CRM 7.5 real Tk navigation test: OK ({click_elapsed:.3f} s / 240 clicks)")
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
