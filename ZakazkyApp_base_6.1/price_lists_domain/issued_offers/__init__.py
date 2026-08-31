"""Canonical TURTO CRM domain for issued business documents."""
from __future__ import annotations

from .schema import ensure_business_documents_schema
from .app_integration import install


def apply(module) -> None:
    if getattr(module, "_turto_business_documents_domain_v6337", False):
        return
    old_ensure = module.ensure_schema

    def ensure_schema():
        old_ensure()
        ensure_business_documents_schema(module)

    module.ensure_schema = ensure_schema
    module.ensure_business_documents_schema = lambda: ensure_business_documents_schema(module)
    install(module)
    module._turto_business_documents_domain_v6337 = True


__all__ = ["apply", "ensure_business_documents_schema"]
