from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"Expected one replacement in {path}: {old[:120]!r}; got {text.count(old)}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Package and validate the new runtime layer.
publish = "scripts/publish-update.sh"
replace_once(
    publish,
    'python scripts/validate-7400-issued-pricing-columns.py "$BASE_DIR"\nrm -rf "$STAGE"',
    'python scripts/validate-7400-issued-pricing-columns.py "$BASE_DIR"\n'
    'python scripts/validate-7500-context-filters-offer-format.py "$BASE_DIR"\n'
    'rm -rf "$STAGE"',
)
replace_once(
    publish,
    "v644_default_date_sort.py v710_cleanup.py v720_visual_offer.py v730_polish.py v740_offer_defaults.py post_baseline.py",
    "v644_default_date_sort.py v710_cleanup.py v720_visual_offer.py v730_polish.py v740_offer_defaults.py v750_context_filters_offer_format.py post_baseline.py",
)
replace_once(
    publish,
    "post_baseline,v710_cleanup,v720_visual_offer,v730_polish,v740_offer_defaults\n",
    "post_baseline,v710_cleanup,v720_visual_offer,v730_polish,v740_offer_defaults,v750_context_filters_offer_format\n",
)
replace_once(
    publish,
    "v730_polish.apply(app);v740_offer_defaults.apply(app)\napp.cleanup_stale_test_session()",
    "v730_polish.apply(app);v740_offer_defaults.apply(app);v750_context_filters_offer_format.apply(app)\napp.cleanup_stale_test_session()",
)
replace_once(
    publish,
    'test -e "$DIR/_runtime/v740_offer_defaults.py"\ntest -e "$DIR/_runtime/v631_diskdrop.py"',
    'test -e "$DIR/_runtime/v740_offer_defaults.py"\n'
    'test -e "$DIR/_runtime/v750_context_filters_offer_format.py"\n'
    'test -e "$DIR/_runtime/v631_diskdrop.py"',
)
replace_once(
    publish,
    'grep -q "crm_features.install_offer_ui(app);crm_price_lists.apply(app);v710_cleanup.apply(app);v720_visual_offer.apply(app);v730_polish.apply(app);v740_offer_defaults.apply(app)" "$DIR/ZakazkyCRM.pyw"',
    'grep -q "crm_features.install_offer_ui(app);crm_price_lists.apply(app);v710_cleanup.apply(app);v720_visual_offer.apply(app);v730_polish.apply(app);v740_offer_defaults.apply(app);v750_context_filters_offer_format.apply(app)" "$DIR/ZakazkyCRM.pyw"',
)
replace_once(
    publish,
    'grep -q "tree.bind(\\\"<Button-3>\\\", popup, add=False)" "$DIR/_runtime/v740_offer_defaults.py"\ngrep -q "Barvy jsou upozornění"',
    'grep -q "tree.bind(\\\"<Button-3>\\\", popup, add=False)" "$DIR/_runtime/v740_offer_defaults.py"\n'
    'grep -q "Formát výstupu: A4" "$DIR/_runtime/v750_context_filters_offer_format.py"\n'
    'grep -q "supplier_presentation_snapshot" "$DIR/_runtime/v750_context_filters_offer_format.py"\n'
    'grep -q "displayed_columns(tree)" "$DIR/_runtime/v750_context_filters_offer_format.py"\n'
    'grep -q "Přidat připomínku" "$DIR/_runtime/v750_context_filters_offer_format.py"\n'
    'grep -q "Barvy jsou upozornění"',
)
replace_once(
    publish,
    "assert text.index('v730_polish.apply(app)') < text.index('v740_offer_defaults.apply(app)')\nPY",
    "assert text.index('v730_polish.apply(app)') < text.index('v740_offer_defaults.apply(app)')\n"
    "assert text.index('v740_offer_defaults.apply(app)') < text.index('v750_context_filters_offer_format.apply(app)')\n"
    "PY",
)

# Compose 7.5 in the real Tk integration test and exercise the new contracts.
real_ui = "scripts/validate-real-ui.py"
replace_once(
    real_ui,
    "    import v740_offer_defaults\n",
    "    import v740_offer_defaults\n    import v750_context_filters_offer_format\n",
)
replace_once(
    real_ui,
    "    v740_offer_defaults.apply(app)\n\n    # Run the fully wrapped schema owner",
    "    v740_offer_defaults.apply(app)\n    v750_context_filters_offer_format.apply(app)\n\n    # Run the fully wrapped schema owner",
)
replace_once(
    real_ui,
    '        assert root.help_button.winfo_exists()\n\n        def button_labels(widget):',
    '''        assert root.help_button.winfo_exists()\n\n        def control_labels(widget):\n            labels = []\n            for child in widget.winfo_children():\n                try:\n                    if child.winfo_class().endswith(("Button", "Checkbutton")):\n                        labels.append(str(child.cget("text") or "").strip())\n                except Exception:\n                    pass\n                labels.extend(control_labels(child))\n            return labels\n\n        forbidden_by_tab = {\n            "actions": {"🗑 Smazat", "🔔 Připomínka", "✉ Poptat", "✎ Editovat"},\n            "requests": {\n                "🗑 Smazat", "✎ Editovat", "Vytvořit e-mail",\n                "Obdrženo dnes", "Bez odezvy",\n            },\n            "mivo": {\n                "🗑 Smazat", "✎ Editovat", "Vytvořit e-mail",\n                "Obdrženo dnes", "Bez odezvy",\n            },\n        }\n        for tab_key, forbidden in forbidden_by_tab.items():\n            labels = set(control_labels(root.tabs[tab_key]))\n            assert not labels.intersection(forbidden), (tab_key, labels)\n            assert "Zobrazit archivované" in labels\n            assert "📦 Archivovat vybrané" in labels\n            assert "↩ Obnovit vybrané" in labels\n        assert getattr(root.action_tree, "_v750_context_owner", None) == "actions"\n        assert getattr(root.request_tree, "_v750_context_owner", None) == "requests"\n        assert getattr(root.mivo_tree, "_v750_context_owner", None) == "mivo"\n        with app.db() as con:\n            action_columns = {\n                str(row[1]) for row in con.execute("PRAGMA table_info(actions)")\n            }\n            assert {"archived", "archived_at", "archived_by"} <= action_columns\n\n        def button_labels(widget):''',
)
replace_once(
    real_ui,
    '        assert int(request_tree.column(width_column, "width")) == 347\n\n        # Open the real visual issued-offer editor',
    '''        assert int(request_tree.column(width_column, "width")) == 347\n\n        # Filter cells must follow displaycolumns and hidden columns.\n        filter_map = dict(zip(\n            getattr(request_tree, "_filter_cell_columns", ()),\n            getattr(request_tree, "_filter_cells", ()),\n        ))\n        candidates = [column for column in request_tree["columns"] if column in filter_map]\n        assert len(candidates) >= 3, candidates\n        first, hidden, second = candidates[:3]\n        request_tree.configure(displaycolumns=(second, first))\n        request_tree._sync_filter_bar()\n        root.update()\n        assert not filter_map[hidden].place_info(), hidden\n        assert int(filter_map[second].place_info()["x"]) < int(\n            filter_map[first].place_info()["x"]\n        )\n        request_tree.configure(displaycolumns="#all")\n        request_tree._sync_filter_bar()\n        root.update()\n        assert filter_map[hidden].place_info(), hidden\n\n        # Open the real visual issued-offer editor''',
)
replace_once(
    real_ui,
    '        assert getattr(editor._v720_internal_panel, "_v740_basis", None) is not None\n',
    '        assert getattr(editor._v720_internal_panel, "_v740_basis", None) is not None\n'
    '        assert getattr(editor, "page_format_label", None) is not None\n'
    '        assert "A4" in str(editor.page_format_label.cget("text"))\n'
    '        assert bool(getattr(editor.tree, "_v750_context_owner", False))\n',
)
replace_once(
    real_ui,
    '        print(f"TURTO CRM 7.4 real Tk navigation test: OK ({click_elapsed:.3f} s / 240 clicks)")',
    '        print(f"TURTO CRM 7.5 real Tk navigation test: OK ({click_elapsed:.3f} s / 240 clicks)")',
)

# Generic validation and publication workflows also run the new regression.
validate = ".github/workflows/validate-6330.yml"
replace_once(
    validate,
    "      - name: Issued pricing defaults and uniform table controls test\n        run: python scripts/validate-7400-issued-pricing-columns.py ZakazkyApp_base_6.1\n",
    "      - name: Issued pricing defaults and uniform table controls test\n"
    "        run: python scripts/validate-7400-issued-pricing-columns.py ZakazkyApp_base_6.1\n\n"
    "      - name: Context menus, filter synchronization and A4 offer format test\n"
    "        run: python scripts/validate-7500-context-filters-offer-format.py ZakazkyApp_base_6.1\n",
)

publish_workflow = ".github/workflows/publish-update.yml"
replace_once(
    publish_workflow,
    "      - scripts/validate-7300-polish.py\n"
    "      - scripts/validate-7400-issued-pricing-columns.py\n"
    "      - scripts/validate-real-ui.py",
    "      - scripts/validate-7300-polish.py\n"
    "      - scripts/validate-7400-issued-pricing-columns.py\n"
    "      - scripts/validate-7500-context-filters-offer-format.py\n"
    "      - scripts/validate-real-ui.py",
)
replace_once(
    publish_workflow,
    "      - ZakazkyApp_base_6.1/v730_polish.py\n"
    "      - ZakazkyApp_base_6.1/v740_offer_defaults.py\n"
    "      - ZakazkyApp_base_6.1/price_lists_domain/issued_offers/**",
    "      - ZakazkyApp_base_6.1/v730_polish.py\n"
    "      - ZakazkyApp_base_6.1/v740_offer_defaults.py\n"
    "      - ZakazkyApp_base_6.1/v750_context_filters_offer_format.py\n"
    "      - ZakazkyApp_base_6.1/price_lists_domain/issued_offers/**",
)
replace_once(
    publish_workflow,
    "      - .github/workflows/validate-7300-polish.yml\n"
    "      - .github/workflows/validate-7400-issued-pricing-columns.yml\n"
    "permissions:",
    "      - .github/workflows/validate-7300-polish.yml\n"
    "      - .github/workflows/validate-7400-issued-pricing-columns.yml\n"
    "      - .github/workflows/validate-7500-context-filters-offer-format.yml\n"
    "permissions:",
)
replace_once(
    publish_workflow,
    "      - name: Validate 7.4 pricing defaults and uniform table controls\n"
    "        shell: bash\n"
    "        run: python scripts/validate-7400-issued-pricing-columns.py ZakazkyApp_base_6.1\n\n"
    "      - name: Build, validate and publish",
    "      - name: Validate 7.4 pricing defaults and uniform table controls\n"
    "        shell: bash\n"
    "        run: python scripts/validate-7400-issued-pricing-columns.py ZakazkyApp_base_6.1\n\n"
    "      - name: Validate 7.5 context menus, filters and A4 offer format\n"
    "        shell: bash\n"
    "        run: python scripts/validate-7500-context-filters-offer-format.py ZakazkyApp_base_6.1\n\n"
    "      - name: Build, validate and publish",
)

print("Applied TURTO CRM 7.5 integration patches")