#!/usr/bin/env python3
"""Regression test for TURTO CRM 7.6.8+ table-date marker cleanup."""
from __future__ import annotations

import pathlib
import sys


def main():
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    sys.path.insert(0, str(source))

    import v768_clean_table_markers as layer

    assert layer._plain_date("⚠ 28.08.2026") == "28.08.2026"
    assert layer._plain_date("⚠️ 28.08.2026") == "28.08.2026"
    assert layer._plain_date("● 03.09.2026") == "03.09.2026"
    assert layer._plain_date("04.09.2026") == "04.09.2026"

    class FakeTree:
        def __init__(self, rows):
            self.rows = rows

        def exists(self, iid):
            return iid in self.rows

        def set(self, iid, column, value=None):
            if value is None:
                return self.rows[iid].get(column, "")
            self.rows[iid][column] = value

    class App:
        pass

    class Module:
        pass

    Module.App = App
    module = Module()
    layer.apply(module)
    assert module.V768_TABLE_MARKERS_CLEAN is True

    app = App()
    app.action_tree = FakeTree({
        "a1": {"Deadline": "⚠ 03.09.2026"},
        "a2": {"Deadline": "● 06.09.2026"},
    })
    app._refresh_action_deadline_highlights([
        ("a1", True, False),
        ("a2", False, True),
    ])
    assert app.action_tree.set("a1", "Deadline") == "03.09.2026"
    assert app.action_tree.set("a2", "Deadline") == "06.09.2026"

    request_tree = FakeTree({
        "r1": {"Poptáno": "⚠️ 28.08.2026"},
        "r2": {"Poptáno": "04.09.2026"},
    })
    app._refresh_request_date_highlights(request_tree, [
        ("r1", True),
        ("r2", False),
    ])
    assert request_tree.set("r1", "Poptáno") == "28.08.2026"
    assert request_tree.set("r2", "Poptáno") == "04.09.2026"

    v767 = (source / "v767_offer_reprocess_images.py").read_text(encoding="utf-8")
    assert "import v768_clean_table_markers" in v767
    assert "v768_clean_table_markers.apply(M)" in v767
    v768 = (source / "v768_clean_table_markers.py").read_text(encoding="utf-8")
    assert "import v769_nevoga_offer" in v768
    assert "v769_nevoga_offer.apply(M)" in v768
    assert "import v7614_nevoga_canonical_export" in v768
    assert "v7614_nevoga_canonical_export.apply(M)" in v768
    assert "import v7615_nevoga_meter_units" in v768
    assert "v7615_nevoga_meter_units.apply(M)" in v768
    assert v768.index("v769_nevoga_offer.apply(M)") < v768.index(
        "v7614_nevoga_canonical_export.apply(M)"
    ) < v768.index("v7615_nevoga_meter_units.apply(M)")

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert "v768_clean_table_markers.apply(app)" in launcher
    assert launcher.index("v767_offer_reprocess_images.apply(app)") < launcher.index(
        "v768_clean_table_markers.apply(app)"
    )

    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    try:
        version_tuple = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise AssertionError(version) from exc
    assert (7, 6, 8) <= version_tuple < (7, 7, 0), version

    print("TURTO CRM 7.6.8+ clean table-date marker / Nevoga packaging bridge validation passed")


if __name__ == "__main__":
    main()
