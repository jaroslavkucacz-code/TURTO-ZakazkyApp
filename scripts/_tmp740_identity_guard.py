from pathlib import Path

layer_path = Path("ZakazkyApp_base_6.1/v740_offer_defaults.py")
text = layer_path.read_text(encoding="utf-8")
old = '''        for key in (
            "_v740_missing_internal_identity",
            "_v740_internal_product_id",
            "_v740_source_code",
            "_v740_source_name",
        ):
            if key in source:
                item[key] = source[key]
        return item
'''
new = '''        for key in (
            "_v740_missing_internal_identity",
            "_v740_internal_product_id",
            "_v740_source_code",
            "_v740_source_name",
        ):
            if key in source:
                item[key] = source[key]
        if _text(item.get("row_type"), "product").casefold() == "product":
            internal_code = _text(
                item.get("internal_code_snapshot") or item.get("product_code")
            )
            internal_name = _text(
                item.get("internal_name_snapshot") or item.get("name")
            )
            item["_v740_missing_internal_identity"] = not bool(
                internal_code and internal_name
            )
        return item
'''
if text.count(old) != 1:
    raise SystemExit("normalize_item insertion point was not found exactly once")
text = text.replace(old, new, 1)

marker = '''    Editor.__init__ = editor_init
    Editor._turto_v740_pricing_basis = True

    # Warn visibly when a received offer could not be resolved to TURTO identity.
'''
guard = '''    Editor.__init__ = editor_init
    Editor._turto_v740_pricing_basis = True

    def missing_internal_identity_indices(instance):
        missing = []
        for index, raw in enumerate(instance.items):
            item = service.normalize_item(raw, index + 1)
            if _text(item.get("row_type"), "product").casefold() != "product":
                continue
            code = _text(
                item.get("internal_code_snapshot") or item.get("product_code")
            )
            name = _text(
                item.get("internal_name_snapshot") or item.get("name")
            )
            if not code or not name:
                missing.append(index)
        return missing

    def require_internal_identity(instance, action_text):
        missing = missing_internal_identity_indices(instance)
        if not missing:
            return True
        first = missing[0]
        try:
            instance.tree.selection_set(f"r{first}")
            instance.tree.see(f"r{first}")
        except Exception:
            pass
        M.messagebox.showwarning(
            "Interní kódy a názvy",
            f"Nelze {action_text}.\\n\\n"
            f"{len(missing)} produktových položek nemá vyplněný interní "
            "kód nebo interní název TURTO. Doplňte označené řádky a "
            "akci zopakujte.",
            parent=instance.win,
        )
        return False

    previous_generate_pdf = Editor.generate_pdf

    def generate_pdf(self, *args, **kwargs):
        if not require_internal_identity(self, "vytvořit zákaznické PDF"):
            return None
        return previous_generate_pdf(self, *args, **kwargs)

    Editor.generate_pdf = generate_pdf

    previous_outlook_draft = Editor.outlook_draft

    def outlook_draft(self, *args, **kwargs):
        if not require_internal_identity(self, "vytvořit Outlook koncept"):
            return None
        return previous_outlook_draft(self, *args, **kwargs)

    Editor.outlook_draft = outlook_draft
    Editor._turto_v740_internal_identity_guard = True

    # Warn visibly when a received offer could not be resolved to TURTO identity.
'''
if text.count(marker) != 1:
    raise SystemExit("issued editor guard insertion point was not found exactly once")
text = text.replace(marker, guard, 1)
layer_path.write_text(text, encoding="utf-8")

test_path = Path("scripts/validate-7400-issued-pricing-columns.py")
test = test_path.read_text(encoding="utf-8")
old_test = '''        assert normalized["margin_pct"] == 35
        assert normalized["discount_pct"] == 4

    layer = (source / "v740_offer_defaults.py").read_text(encoding="utf-8")
'''
new_test = '''        assert normalized["margin_pct"] == 35
        assert normalized["discount_pct"] == 4

        unresolved = service.normalize_item(
            {
                "row_type": "product",
                "product_code": "DOD-1",
                "name": "Dodavatelský název",
                "internal_code_snapshot": "",
                "internal_name_snapshot": "",
                "_v740_missing_internal_identity": True,
            }
        )
        assert unresolved["_v740_missing_internal_identity"]
        resolved = service.normalize_item(
            {
                **unresolved,
                "product_code": "TUR-001",
                "name": "Interní produkt TURTO",
                "internal_code_snapshot": "TUR-001",
                "internal_name_snapshot": "Interní produkt TURTO",
            }
        )
        assert not resolved["_v740_missing_internal_identity"]

    layer = (source / "v740_offer_defaults.py").read_text(encoding="utf-8")
'''
if test.count(old_test) != 1:
    raise SystemExit("7.4 validation insertion point was not found exactly once")
test = test.replace(old_test, new_test, 1)
needle = '    assert "remove_columns_buttons(mivo)" in layer\n'
replacement = (
    needle
    + '    assert "_turto_v740_internal_identity_guard" in layer\n'
    + '    assert "vytvořit zákaznické PDF" in layer\n'
)
if test.count(needle) != 1:
    raise SystemExit("7.4 validation static insertion point was not found exactly once")
test = test.replace(needle, replacement, 1)
test_path.write_text(test, encoding="utf-8")

print("Applied TURTO CRM 7.4 internal identity guard")
