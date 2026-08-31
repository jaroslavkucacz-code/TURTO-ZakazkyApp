#!/usr/bin/env python3
"""Update existing regression suites and publication workflow for 6.3.41."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = "scripts/validate-6334-product-catalog.py"
text = read(path)
text = replace_once(
    text,
    '''    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 1
''',
    '''    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 0
    assert product_catalog.count_unlinked(m) == 0
''',
    "validate 6334 sync expectations",
)
text = replace_once(text, '        assert linked == product_id == linked_offer\n', '        assert linked == product_id\n        assert linked_offer is None\n', "validate 6334 offer linkage")
text = replace_once(
    text,
    '''        row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        assert row[0] == group and row[1] == subgroup
''',
    '''        row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        offer_row = con.execute("SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=1").fetchone()
        assert row[0] == group and row[1] == subgroup
        assert tuple(offer_row) == (None, None)
''',
    "validate 6334 taxonomy separation",
)
write(path, text)


path = "scripts/validate-6335-product-workspace.py"
text = read(path)
text = replace_once(text, '    "Změna se automaticky projeví ve všech jejich Ceníkách i cenových Nabídkách",\n', '    "Přijaté nabídky zůstanou beze změny",\n', "validate 6335 UI wording")
text = replace_once(
    text,
    '''    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 1
''',
    '''    assert product_catalog.sync_price_list(m, 1) == 1
    assert product_catalog.sync_supplier_offer(m, 1) == 0
''',
    "validate 6335 sync expectations",
)
text = replace_once(
    text,
    '''    # Moving the stable product must immediately propagate to both source domains.
    product_catalog.set_product_taxonomy(m, [product_id], group_b, None)
    with m.db() as con:
        master = con.execute("SELECT category_id,subgroup_id FROM catalog_products WHERE id=?", (product_id,)).fetchone()
        price_row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        offer_row = con.execute("SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=1").fetchone()
        assert tuple(master) == tuple(price_row) == tuple(offer_row) == (group_b, None)
''',
    '''    # Moving the stable product propagates to Ceníky only. A received offer
    # keeps its own local classification and remains outside the catalogue.
    product_catalog.set_product_taxonomy(m, [product_id], group_b, None)
    with m.db() as con:
        master = con.execute("SELECT category_id,subgroup_id FROM catalog_products WHERE id=?", (product_id,)).fetchone()
        price_row = con.execute("SELECT category_id,subgroup_id FROM price_list_items WHERE id=1").fetchone()
        offer_row = con.execute("SELECT category_id,subgroup_id FROM supplier_offer_items WHERE id=1").fetchone()
        assert tuple(master) == tuple(price_row) == (group_b, None)
        assert tuple(offer_row) == (None, None)
''',
    "validate 6335 taxonomy contract",
)
write(path, text)


path = "scripts/validate-6336-commercial-workspace.py"
text = read(path)
text = replace_once(
    text,
    '''        "Pracovní pohled", "Cenový základ", "Nezařazených cen", "Bez zařazení produktů",
''',
    '''        "Pracovní pohled", "Cenový základ", "Nezařazených cen", "Bez zařazení položek",
        "Překlopit do Vydané nabídky",
''',
    "validate 6336 received-offer UI",
)
write(path, text)


path = "scripts/validate-6341-offer-catalog-separation.py"
text = read(path)
text = replace_once(
    text,
    '''            CREATE TABLE projects(
              id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1
            );
''',
    '''            CREATE TABLE business_document_templates(
              id INTEGER PRIMARY KEY, document_type TEXT, active INTEGER DEFAULT 1,
              is_default INTEGER DEFAULT 0
            );
            CREATE TABLE projects(
              id INTEGER PRIMARY KEY, name TEXT, active INTEGER DEFAULT 1
            );
''',
    "validate 6341 issued-offer template fixture",
)
write(path, text)


path = ".github/workflows/publish-update.yml"
text = read(path)
text = replace_once(text, '      - scripts/validate-6340-manual-products-pricing.py\n', '      - scripts/validate-6340-manual-products-pricing.py\n      - scripts/validate-6341-offer-catalog-separation.py\n', "publish workflow test path")
text = replace_once(text, '      - .github/workflows/validate-6340-manual-pricing.yml\n', '      - .github/workflows/validate-6340-manual-pricing.yml\n      - .github/workflows/validate-6341-offer-catalog-separation.yml\n', "publish workflow validation path")
text = replace_once(
    text,
    '''      - name: Build, validate and publish
''',
    '''      - name: Validate received-offer and catalogue separation
        shell: bash
        run: python scripts/validate-6341-offer-catalog-separation.py ZakazkyApp_base_6.1

      - name: Build, validate and publish
''',
    "publish workflow validation step",
)
write(path, text)

print("Applied TURTO CRM 6.3.41 tests and publish workflow")
