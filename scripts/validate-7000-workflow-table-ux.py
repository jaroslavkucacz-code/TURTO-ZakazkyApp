#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.0 workflow and table UX."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
REPOSITORY = ROOT.parent
sys.path.insert(0, str(ROOT))

from v700_ux import group_offer_items  # noqa: E402


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> None:
    layer = read(ROOT / "v700_ux.py")
    request_section = layer.split("def request_refresh_similar", 1)[1].split(
        "def selected_request_ids", 1
    )[0]
    assert "WHERE r.action_id=?" in request_section
    assert "lower(r.item)" not in request_section
    assert "if not action_id" in request_section

    archive_section = layer.split("def archive_requests", 1)[1].split(
        "# ------------------------------------------------------------------\n    # Opportunity", 1
    )[0]
    assert "tree.selection()" in layer
    assert "WHERE r.id IN ({marks})" in archive_section
    assert "Archivovat označené poptávky" in archive_section
    assert "refresh_after_request_change" in archive_section

    assert "takefocus=False" in layer
    assert "auxiliary_prefixes" in layer
    assert '"<Tab>"' in layer and '"<Shift-Tab>"' in layer
    assert 'text="+ Nová akce"' in layer
    assert "_v700_action_wrapper" in layer

    assert "tree_layout_v700_" in layer
    assert "save_layout" in layer
    assert "displaycolumns" in layer
    assert "stretch=bool(column == last" in layer
    assert "Nastavit zobrazené sloupce" in layer
    assert "Zobrazit / skrýt" in layer
    assert "is_commercial_tree" in layer

    assert '"Skupina", "Podskupina"' in layer
    assert "category_name_snapshot" in layer
    assert "subgroup_name_snapshot" in layer
    assert "grouped_pdf_items" in layer

    rows = [
        {
            "row_type": "product",
            "name": "A1",
            "category_name_snapshot": "Skupina A",
            "subgroup_name_snapshot": "Podskupina 1",
        },
        {"row_type": "text", "description": "Poznámka"},
        {
            "row_type": "product",
            "name": "B1",
            "category_name_snapshot": "Skupina B",
            "subgroup_name_snapshot": "Podskupina 2",
        },
        {
            "row_type": "product",
            "name": "A2",
            "category_name_snapshot": "Skupina A",
            "subgroup_name_snapshot": "Podskupina 1",
        },
        {"row_type": "service", "name": "Doprava"},
    ]
    plan = group_offer_items(rows)
    headings = [token["label"] for token in plan if token["kind"] == "group"]
    assert headings == ["Skupina A › Podskupina 1", "Skupina B › Podskupina 2"]
    assert headings.count("Skupina A › Podskupina 1") == 1
    item_indices = [token["index"] for token in plan if token["kind"] == "item"]
    assert item_indices == [0, 3, 1, 2, 4], item_indices

    schema = read(ROOT / "price_lists_domain" / "issued_offers" / "schema.py")
    assert '"category_name_snapshot TEXT DEFAULT \'\'"' in schema
    assert '"subgroup_name_snapshot TEXT DEFAULT \'\'"' in schema

    launcher = read(ROOT / "ZakazkyCRM.pyw")
    assert "import v700_ux" in launcher or ",v700_ux" in launcher
    assert "v700_ux.apply(app)" in launcher

    publish = read(REPOSITORY / "scripts" / "publish-update.sh")
    assert "v700_ux.py" in publish
    assert "v700_ux.apply(app)" in publish
    assert "validate-7000-workflow-table-ux.py" in publish

    real_ui = read(REPOSITORY / "scripts" / "validate-real-ui.py")
    assert "import v700_ux" in real_ui
    assert "v700_ux.apply(app)" in real_ui

    version = read(REPOSITORY / "release_version.txt").strip()
    assert version == "7.0.0", version

    print("OK 7.0.0: request workflow, persistent columns and grouped issued offers")


if __name__ == "__main__":
    main()
