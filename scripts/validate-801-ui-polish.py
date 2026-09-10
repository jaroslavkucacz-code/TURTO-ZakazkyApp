#!/usr/bin/env python3
"""Static/pure regression checks for the post-8.0 TURTO CRM UI cleanup."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_ui_polish_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    polish_path = base / "price_lists_domain" / "platform" / "ui_polish_801.py"
    bootstrap_path = base / "runtime_bootstrap.py"
    app_path = base / "app.py"

    assert polish_path.is_file(), "UI polish owner is missing"
    polish = load_module(polish_path)
    assert polish.SUPPORTED_THEMES == ("Světlý", "Tmavý")
    assert polish._is_dark("#0b1014") is True
    assert polish._is_dark("#f2f4f5") is False

    source = polish_path.read_text(encoding="utf-8")
    required = (
        "def _theme_aware_calendar",
        'text == "Vybrat složku…"',
        'text.startswith("Výchozí kanál:")',
        'text == "Zkontrolovat aktualizace"',
        "Produkční Windows kanál",
        'footer.configure(text=f"Databáze:',
        'style.configure(\n        "Muted.TLabel"',
        'M.DatePicker.open_calendar = _theme_aware_calendar',
    )
    for token in required:
        assert token in source, token

    bootstrap = bootstrap_path.read_text(encoding="utf-8")
    marker = '"price_lists_domain.platform.ui_polish_801"'
    assert marker in bootstrap
    assert bootstrap.index(marker) > bootstrap.index('"price_lists_domain.platform.startup_optimization"')

    # The cleanup exists because the historical UI still exposes these legacy
    # constructs. If the base app is later cleaned directly, update this test
    # and consider retiring the compatibility layer instead of stacking patches.
    app = app_path.read_text(encoding="utf-8")
    assert 'values=["Světlý","Šedomodrý","Teplý","Tmavý"]' in app
    assert 'text="Vybrat složku…"' in app
    assert 'text=f"Databáze: zakazky.db (schéma {APP_VERSION.rsplit' in app
    assert 'pop.configure(background="#f4f7fa")' in app

    print("TURTO CRM 8.x UI polish: OK")


if __name__ == "__main__":
    main()
