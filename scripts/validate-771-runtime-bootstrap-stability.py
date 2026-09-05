#!/usr/bin/env python3
"""Regression guard for TURTO CRM 7.7.1 runtime-bootstrap Tk stability."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import SimpleNamespace


def load_bootstrap(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("turto_runtime_bootstrap_771", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nelze načíst {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    bootstrap_path = source / "runtime_bootstrap.py"
    stability_path = source / "v644_default_date_sort.py"

    bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    stability_text = stability_path.read_text(encoding="utf-8")

    assert "STABILITY_PRIMED_LAYERS" in bootstrap_text
    assert '"v710_cleanup"' in bootstrap_text
    assert '"v760_table_activity_performance"' in bootstrap_text
    assert "_prime_startup_stability_layers()" in bootstrap_text
    assert 'sys.modules.get("v710_cleanup")' in stability_text
    assert 'sys.modules.get("v760_table_activity_performance")' in stability_text

    # The regression was composition order: under the explicit sequential
    # bootstrap v644 ran before v710/v760 had been imported, so its bridge had
    # no modules to wrap. Simulate apply_all() and require both modules to have
    # been imported before v644.apply() executes.
    bootstrap = load_bootstrap(bootstrap_path)
    imported: list[str] = []
    applied: list[str] = []
    primed_when_v644_ran: list[bool] = []

    class FakeModule:
        def __init__(self, name: str):
            self.name = name

        def apply(self, _target) -> None:
            applied.append(self.name)
            if self.name == "v644_default_date_sort":
                primed_when_v644_ran.append(
                    "v710_cleanup" in imported
                    and "v760_table_activity_performance" in imported
                )

        def install_offer_ui(self, _target) -> None:
            applied.append("crm_features.install_offer_ui")

    modules: dict[str, FakeModule] = {}

    def fake_import(name: str):
        imported.append(name)
        return modules.setdefault(name, FakeModule(name))

    bootstrap.import_module = fake_import
    target = SimpleNamespace()
    bootstrap.apply_all(target)

    assert primed_when_v644_ran == [True], (
        "v644 se spustil dříve, než byly v710 a v760 dostupné k bezpečnému obalení"
    )
    assert applied.count("v710_cleanup") == 1
    assert applied.count("v760_table_activity_performance") == 1
    assert applied.index("v644_default_date_sort") < applied.index("v710_cleanup")
    assert applied.index("v644_default_date_sort") < applied.index(
        "v760_table_activity_performance"
    )
    assert target._turto_runtime_bootstrap_complete is True
    assert "import:v710_cleanup" in target.RUNTIME_BOOTSTRAP_ORDER
    assert "import:v760_table_activity_performance" in target.RUNTIME_BOOTSTRAP_ORDER

    # Idempotence is part of the startup contract; a second call may not apply
    # or import another layer.
    imported_before = len(imported)
    applied_before = len(applied)
    bootstrap.apply_all(target)
    assert len(imported) == imported_before
    assert len(applied) == applied_before

    print("TURTO CRM 7.7.1 runtime bootstrap stability validation passed.")


if __name__ == "__main__":
    main()
