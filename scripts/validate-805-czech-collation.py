#!/usr/bin/env python3
"""Exact-equivalence checks for the 8.0.5 SQLite Czech collation hot path."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    path = base / "price_lists_domain" / "platform" / "runtime_optimization_803.py"
    optimization = load_module(path, "turto_805_czech_collation_test")

    calls: list[object] = []

    def historical_sort_key(value):
        calls.append(value)
        text = str(value or "").strip().casefold()
        # A deterministic stand-in is sufficient here: the optimization must
        # preserve *whatever* tuple the historical public key returns.
        return tuple((ord(ch), ch) for ch in text)

    def legacy_collate(a, b):
        ka = historical_sort_key(a)
        kb = historical_sort_key(b)
        return (ka > kb) - (ka < kb)

    module = SimpleNamespace(
        czech_sort_key=historical_sort_key,
        _czech_collate=legacy_collate,
    )

    samples = [
        "Adam 2",
        "Adam 10",
        "Česká firma",
        "ČEZ",
        "Ch Projekt 2",
        "CH Projekt 10",
        "Ejpovice",
        "Leviat",
        "MAVI Monolity s.r.o.",
        "Řezáč",
        "Škoda",
        "TURTO",
        "ŽPSV",
        "Zruč-Senec",
    ]
    expected_pairs = {
        (a, b): legacy_collate(a, b)
        for a in samples
        for b in samples
    }

    assert optimization._install_czech_sort_cache(module) is True
    fast_collate = module._czech_collate
    public_key = module.czech_sort_key
    assert getattr(fast_collate, "_turto_805_direct_cached_text", False)
    assert getattr(fast_collate, "_turto_original", None) is legacy_collate
    assert callable(getattr(public_key, "cache_info", None))
    assert callable(getattr(public_key, "cache_clear", None))

    # Direct pairwise equivalence and cache behavior.
    public_key.cache_clear()
    calls.clear()
    for a in samples:
        for b in samples:
            assert fast_collate(a, b) == expected_pairs[(a, b)], (a, b)
    assert len(calls) == len(set(samples)), (
        "SQLite hot path should compute each unique text key once, "
        f"got {len(calls)} historical-key calls"
    )
    info = public_key.cache_info()
    assert info.misses == len(set(samples))
    assert info.hits > info.misses

    # Public API semantics remain exact for strings and non-strings.
    before = len(calls)
    expected = tuple((ord(ch), ch) for ch in "česká firma".casefold())
    assert public_key("Česká firma") == expected
    assert len(calls) == before, "cached public string call unexpectedly recomputed"
    none_expected = historical_sort_key(None)
    before = len(calls)
    assert public_key(None) == none_expected
    assert len(calls) == before + 1, "non-string public call must keep historical path"

    # Defensive non-text collation fallback remains the historical callback.
    assert fast_collate(None, "Adam 2") == legacy_collate(None, "Adam 2")

    # Real SQLite ORDER BY must produce exactly the same order as the legacy
    # callback, including stable row-id tie breaking.
    con = sqlite3.connect(":memory:")
    try:
        con.create_collation("LEGACY_CZECH", legacy_collate)
        con.create_collation("FAST_CZECH", fast_collate)
        con.execute("CREATE TABLE names(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        for value in reversed(samples):
            con.execute("INSERT INTO names(value) VALUES(?)", (value,))
        legacy_rows = [
            row[0]
            for row in con.execute(
                "SELECT value FROM names ORDER BY value COLLATE LEGACY_CZECH, id"
            )
        ]
        fast_rows = [
            row[0]
            for row in con.execute(
                "SELECT value FROM names ORDER BY value COLLATE FAST_CZECH, id"
            )
        ]
        assert fast_rows == legacy_rows
    finally:
        con.close()

    # Installer is idempotent; a second call must not stack another wrapper.
    before_collate = module._czech_collate
    before_key = module.czech_sort_key
    assert optimization._install_czech_sort_cache(module) is True
    assert module._czech_collate is before_collate
    assert module.czech_sort_key is before_key

    print("TURTO CRM 8.0.5 Czech SQLite collation equivalence: OK")


if __name__ == "__main__":
    main()
