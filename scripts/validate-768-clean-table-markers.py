#!/usr/bin/env python3
"""Validate clean date text and explicit 7.7 runtime composition."""
from __future__ import annotations

import pathlib
import sys


def main():
    source = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    repository = source.parent
    sys.path.insert(0, str(source))
    import v768_clean_table_markers as layer

    assert layer._plain_date("⚠ 28.08.2026") == "28.08.2026"
    assert layer._plain_date("⚠️ 28.08.2026") == "28.08.2026"
    assert layer._plain_date("● 03.09.2026") == "03.09.2026"
    assert layer._plain_date("▲ 04.09.2026") == "04.09.2026"

    class FakeTree:
        def __init__(self):
            self.rows = {"a1": {"Deadline": "⚠ 03.09.2026"}, "r1": {"Poptáno": "● 28.08.2026"}}
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
    app = App()
    app.action_tree = FakeTree()
    app._refresh_action_deadline_highlights([("a1", True, False)])
    assert app.action_tree.set("a1", "Deadline") == "03.09.2026"
    request_tree = FakeTree()
    app._refresh_request_date_highlights(request_tree, [("r1", True)])
    assert request_tree.set("r1", "Poptáno") == "28.08.2026"

    text = (source / "v768_clean_table_markers.py").read_text(encoding="utf-8")
    for hidden in (
        "import v769_nevoga_offer",
        "import v7614_nevoga_canonical_export",
        "import v7615_nevoga_meter_units",
        "import v7616_requests_plexus_assets",
    ):
        assert hidden not in text, hidden

    bootstrap = (source / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert '"v768_clean_table_markers"' in bootstrap
    assert '"v769_nevoga_offer"' in bootstrap
    assert '"v7614_nevoga_canonical_export"' in bootstrap
    assert '"v7615_nevoga_meter_units"' in bootstrap
    assert '"v7616_requests_plexus_assets"' in bootstrap
    assert '"v770_runtime_policy"' in bootstrap
    assert bootstrap.index('"v768_clean_table_markers"') < bootstrap.index('"v769_nevoga_offer"')
    assert bootstrap.index('"v769_nevoga_offer"') < bootstrap.index('"v7614_nevoga_canonical_export"')
    assert bootstrap.index('"v7616_requests_plexus_assets"') < bootstrap.index('"v770_runtime_policy"')

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
    assert "runtime_bootstrap.apply_all(app)" in launcher

    version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
    assert tuple(int(part) for part in version.split(".")) >= (7, 7, 0)
    print("OK 7.7: clean dates are independent and runtime order is explicit")


if __name__ == "__main__":
    main()
