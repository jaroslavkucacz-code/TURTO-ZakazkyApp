"""Canonical performance, catalogue and lifecycle layer for TURTO CRM."""
from __future__ import annotations


def install(module) -> None:
    from .database import install_fast_db, patch_schema
    from .fast_ocr import install as install_ocr
    from .integration import install as install_price_integration
    from .offers import install as install_offers
    from .archive import install as install_archive
    from .lazy_refresh import install as install_lazy_refresh

    if getattr(module, "_turto_platform_v630", False):
        return
    install_fast_db(module)
    patch_schema(module)
    install_ocr(module)
    install_price_integration(module)
    install_offers(module)
    install_archive(module)
    install_lazy_refresh(module)
    module._turto_platform_v630 = True


__all__ = ["install"]
