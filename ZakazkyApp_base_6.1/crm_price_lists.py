"""Canonical owner entry point for TURTO CRM Ceníky and catalogue pricing."""
from price_lists_domain import (
    apply as _apply_price_lists,
    ensure_price_list_schema,
    price_list_archive_root,
    parse_price_list_file,
)
from price_lists_domain.platform.customer_pricing import install as install_customer_pricing


def apply(module):
    _apply_price_lists(module)
    # The complete Ceníky / Vydané nabídky domain is composed first. Customer
    # pricing then extends its stable catalogue and final document service
    # without changing importers or historical price-list rows.
    install_customer_pricing(module)


__all__ = [
    "apply", "ensure_price_list_schema", "price_list_archive_root",
    "parse_price_list_file", "install_customer_pricing",
]
