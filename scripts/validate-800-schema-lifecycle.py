#!/usr/bin/env python3
"""Architecture guard for the single-owner TURTO CRM schema lifecycle."""
from __future__ import annotations

import ast
import pathlib
import sys
from types import SimpleNamespace


EXPECTED_RUNTIME_MIGRATIONS = [
    "price_lists.core",
    "price_lists.platform",
    "price_lists.finalize",
    "price_lists.issued_offers",
    "price_lists.customer_pricing",
    "v710.commercial",
    "v730.company_merge",
    "v740.offer_defaults",
    "v750.context_filters",
    "v760.table_activity",
    "v767.offer_reprocess_images",
    "v769.nevoga_rich_description",
    "v7616.plexus_assets",
    "v770.runtime_policy",
]


def _assignment_owners(source: pathlib.Path) -> list[tuple[str, int, str]]:
    owners: list[tuple[str, int, str]] = []
    for path in sorted(source.rglob("*.py")) + sorted(source.rglob("*.pyw")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "ensure_schema":
                    base = target.value.id if isinstance(target.value, ast.Name) else "?"
                    owners.append((path.relative_to(source).as_posix(), node.lineno, base))
    return owners


def main() -> None:
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    source_text = str(source)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)

    import schema_lifecycle

    events: list[str] = []

    def base_schema():
        events.append("base")
        return "base-result"

    M = SimpleNamespace(ensure_schema=base_schema)
    schema_lifecycle.apply(M)
    owner = M.ensure_schema
    schema_lifecycle.register(M, "first", lambda: events.append("first-old"))
    schema_lifecycle.register(M, "second", lambda: events.append("second"))
    schema_lifecycle.register(M, "first", lambda: events.append("first-new"))

    assert M.ensure_schema is owner, "registration may not replace the lifecycle owner"
    assert [item.name for item in M.SCHEMA_MIGRATIONS] == ["first", "second"]
    assert M.ensure_schema() == "base-result"
    assert events == ["base", "first-new", "second"], events

    events.clear()
    M.ensure_schema()
    assert events == ["base", "first-new", "second"], events

    owners = _assignment_owners(source)
    assert [(file, base) for file, _line, base in owners] == [("schema_lifecycle.py", "M")], owners

    bootstrap = (source / "runtime_bootstrap.py").read_text(encoding="utf-8")
    assert bootstrap.index('_apply("app_lifecycle", M)') < bootstrap.index(
        '_apply("schema_lifecycle", M)'
    ) < bootstrap.index("for name in EARLY_LAYERS:")
    assert '"schema_lifecycle"' in bootstrap

    registrations = []
    for path in sorted(source.rglob("*.py")):
        if path.name == "schema_lifecycle.py":
            continue
        text = path.read_text(encoding="utf-8-sig")
        if "schema_lifecycle.register" in text:
            registrations.append(path.relative_to(source).as_posix())
    assert len(registrations) == 14, registrations

    print("TURTO CRM 8.0 schema lifecycle validation passed.")


if __name__ == "__main__":
    main()
