"""Single-owner database schema lifecycle for TURTO CRM 8.0.

Historical feature layers replaced ``ensure_schema`` one after another.  The
result worked only because every wrapper remembered to call the previous one in
exactly the right order.  This module owns the function once and lets layers
register named additive migrations while keeping the established execution
order visible and deterministic.

The base application schema always runs first. Registered migrations then run
in registration order. Re-registering the same name updates that migration in
place without changing its position.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

SchemaMigration = Callable[[], Any]


@dataclass
class _Migration:
    name: str
    function: SchemaMigration


def apply(M: Any) -> None:
    """Install the single ``ensure_schema`` owner and migration registry."""
    if getattr(M, "_turto_schema_lifecycle_installed", False):
        return

    original_ensure = getattr(M, "ensure_schema", None)
    if not callable(original_ensure):
        raise AttributeError("TURTO schema lifecycle requires callable ensure_schema")

    migrations: list[_Migration] = []

    def register_schema_migration(name: str, function: SchemaMigration) -> None:
        key = str(name or "").strip()
        if not key:
            raise ValueError("Schema migration must have a name")
        if not callable(function):
            raise TypeError("Schema migration must be callable")
        for index, migration in enumerate(migrations):
            if migration.name == key:
                migrations[index] = _Migration(key, function)
                return
        migrations.append(_Migration(key, function))

    def ensure_schema() -> Any:
        result = original_ensure()
        for migration in tuple(migrations):
            migration.function()
        return result

    M.ensure_schema = ensure_schema
    M.register_schema_migration = register_schema_migration
    M.SCHEMA_MIGRATIONS = migrations
    M._turto_schema_lifecycle_installed = True


def register(M: Any, name: str, function: SchemaMigration) -> None:
    """Register a migration, also supporting isolated compatibility-layer tests."""
    if not getattr(M, "_turto_schema_lifecycle_installed", False):
        apply(M)
    M.register_schema_migration(name, function)
