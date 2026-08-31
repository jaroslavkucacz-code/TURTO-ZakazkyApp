"""Canonical TURTO CRM domain for issued business documents."""
from __future__ import annotations

# The renderer remains the owner of document layout. This helper only replaces
# its text primitive with a Unicode-aware implementation that uses local Calibri
# on Windows and a compatible fallback in CI.
from . import pdf_renderer as _pdf_renderer
from .font_support import fit_text as _unicode_fit_text
from .schema import ensure_business_documents_schema
from .app_integration import install

_pdf_renderer._fit_text = _unicode_fit_text


def apply(module) -> None:
    """Install the additive schema owner and the issued-offer UI exactly once."""
    if getattr(module, "_turto_business_documents_domain_v6338", False):
        return

    old_ensure = module.ensure_schema

    def ensure_schema():
        old_ensure()
        ensure_business_documents_schema(module)

    module.ensure_schema = ensure_schema
    module.ensure_business_documents_schema = lambda: ensure_business_documents_schema(module)
    install(module)
    module._turto_business_documents_domain_v6338 = True


__all__ = ["apply", "ensure_business_documents_schema"]
