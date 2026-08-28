"""Canonical TURTO CRM Ceníky domain."""
from . import context
from .app_integration import _install_app_page,_install_settings
from .archive import price_list_archive_root
from .offer_integration import _install_offer_integration
from .opportunity import _install_new_project_button
from .parser import parse_price_list_file
from .schema import ensure_price_list_schema


def apply(module):
    context.M=module
    old_ensure=module.ensure_schema
    def ensure_schema():
        old_ensure()
        ensure_price_list_schema()
    module.ensure_schema=ensure_schema
    module.ensure_price_list_schema=ensure_price_list_schema
    module.price_list_archive_root=price_list_archive_root
    module.parse_price_list_file=parse_price_list_file
    _install_new_project_button(module)
    _install_offer_integration(module)
    _install_app_page(module)
    _install_settings(module)


__all__=["apply","ensure_price_list_schema","price_list_archive_root","parse_price_list_file"]
