"""Canonical performance, catalogue and lifecycle layer for TURTO CRM."""
from __future__ import annotations


def install(module) -> None:
    """Install each owner exactly once, with navigation installed last."""
    from .database import install_fast_db, patch_schema
    from .fast_ocr import install as install_ocr
    from .integration import install as install_price_integration
    from .offers import install as install_offers
    from .archive import install as install_archive
    from .worksets import install as install_worksets
    from .finalize import install as install_finalize
    from .compat import install as install_compat
    from .lazy_refresh import install as install_lazy_refresh

    if getattr(module, "_turto_platform_v6331", False):
        return

    install_fast_db(module)
    patch_schema(module)
    install_ocr(module)
    install_price_integration(module)
    install_offers(module)
    install_archive(module)
    install_worksets(module)
    install_finalize(module)
    install_compat(module)
    # This must be the final UI step. It replaces the accumulated legacy
    # show_page wrapper chain with one responsive navigation owner.
    install_lazy_refresh(module)

    module._turto_platform_v6331 = True


__all__ = ["install"]
