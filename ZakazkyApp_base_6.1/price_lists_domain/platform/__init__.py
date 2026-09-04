"""Canonical performance, catalogue and lifecycle layer for TURTO CRM."""
from __future__ import annotations


def install(module) -> None:
    """Install each owner exactly once; navigation and updates are final."""
    from .database import install_fast_db, patch_schema
    from .fast_ocr import install as install_ocr
    from .integration import install as install_price_integration
    from .product_catalog import install as install_product_catalog
    from .product_workspace import install as install_product_workspace
    from .offers import install as install_offers
    from .archive import install as install_archive
    from .worksets import install as install_worksets
    from .finalize import install as install_finalize
    from .compat import install as install_compat
    from .clarity import install as install_clarity
    from .commercial_workspace import install as install_commercial_workspace
    from .lazy_refresh import install as install_lazy_refresh
    from .project_table_stability import install as install_project_table_stability
    from .nevoga_export_routing import install as install_nevoga_export_routing
    from .automatic_updates import install as install_automatic_updates

    if getattr(module, "_turto_platform_v6339", False):
        return

    install_fast_db(module)
    patch_schema(module)
    install_ocr(module)
    install_price_integration(module)
    install_product_catalog(module)
    # The catalogue service above owns identity and propagation. This dedicated
    # workspace is its only presentation owner and is reused by Ceníky and the
    # hierarchy manager instead of layering another data implementation.
    install_product_workspace(module)
    install_offers(module)
    install_archive(module)
    install_worksets(module)
    install_finalize(module)
    install_compat(module)
    # One dedicated presentation owner follows the data/query owners. It adds
    # price-list validity context and MIVO ageing without rebuilding hidden tabs.
    install_clarity(module)
    # Ceníky and Nabídky share one final CRM presentation owner. It follows
    # all data and compatibility owners and does not wrap their page builders.
    install_commercial_workspace(module)
    # Navigation replaces the accumulated legacy show_page wrapper chain.
    install_lazy_refresh(module)
    # Register the Akce table stabilizer before v760.apply() runs. The hook
    # installs its final owner only after v760 has finished composing the table.
    install_project_table_stability(module)
    # v624 binds received-offer Excel buttons directly to its legacy closure.
    # Register this hook now; it takes final ownership only after v769.apply()
    # has installed the supplier-aware Nevoga exporter.
    install_nevoga_export_routing(module)
    # The updater is installed last so no older runtime layer can restore a
    # confirmation dialog or a second competing startup check.
    install_automatic_updates(module)

    module._turto_platform_v6339 = True


__all__ = ["install"]
