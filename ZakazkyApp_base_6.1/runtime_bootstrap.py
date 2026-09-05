"""Explicit TURTO CRM runtime composition.

Older releases grew through hidden imports between compatibility layers.  The
launcher now calls this single module, so startup order is visible and auditable.
The final policy module is intentionally last and owns only cross-cutting rules.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

EARLY_LAYERS = (
    "crm_features",
    "crm_runtime",
    "crm_v605",
    "v606_features",
    "v608_stability",
    "v611_audit",
    "v613_ui",
    "v614_next",
    "v615_input",
    "v616_stability",
    "v617_offerhub",
    "v618_inputfix",
    "v619_fixes",
    "v620_outlookdrop",
    "v621_prices",
    "v623_exports",
    "v625_stability",
    "v628_modernui_resize",
    "v632_offerlinks",
    "v633_offerassign_deadlines",
    "v636_action_offers_stabletable",
    "v637_project_offer_model",
    "v638_table_updatefix",
    "v640_warning_cleanup",
)

LATE_LAYERS = (
    "v710_cleanup",
    "v720_visual_offer",
    "v730_polish",
    "v740_offer_defaults",
    "v750_context_filters_offer_format",
    "v760_table_activity_performance",
    "v767_offer_reprocess_images",
    "v768_clean_table_markers",
    "v769_nevoga_offer",
    "v7614_nevoga_canonical_export",
    "v7615_nevoga_meter_units",
    "v7616_requests_plexus_assets",
    "v770_runtime_policy",
)


def _apply(module_name: str, target: Any) -> None:
    module = import_module(module_name)
    function = getattr(module, "apply", None)
    if callable(function):
        function(target)


def apply_all(M: Any) -> None:
    if getattr(M, "_turto_runtime_bootstrap_complete", False):
        return

    for name in EARLY_LAYERS:
        _apply(name, M)

    _apply("post_baseline", M)
    _apply("v631_diskdrop", M)
    _apply("v644_default_date_sort", M)

    crm_features = import_module("crm_features")
    install_offer_ui = getattr(crm_features, "install_offer_ui", None)
    if callable(install_offer_ui):
        install_offer_ui(M)

    _apply("crm_price_lists", M)

    for name in LATE_LAYERS:
        _apply(name, M)

    M._turto_runtime_bootstrap_complete = True
    M.RUNTIME_BOOTSTRAP_ORDER = (
        *EARLY_LAYERS,
        "post_baseline",
        "v631_diskdrop",
        "v644_default_date_sort",
        "crm_features.install_offer_ui",
        "crm_price_lists",
        *LATE_LAYERS,
    )
