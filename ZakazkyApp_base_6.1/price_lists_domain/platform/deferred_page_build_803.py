"""Deferred construction of selected safe hidden pages for TURTO CRM 8.0.3-dev.

Only secondary pages whose containers/navigation already exist at startup are
included. Core workspaces (Akce/Příležitosti/Poptávky/MIVO/Přijaté nabídky/Úkoly)
stay eager because historical runtime layers interact with them more heavily.
The canonical lazy_refresh module remains the sole navigation owner.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.deferred_page_build_803"
DEFERRED_PAGE_BUILD_METHODS = {
    "pricelists": "build_price_lists",
    "issued_offers": "build_issued_offers",
    "settings": "build_settings",
}


def _built_pages(app: Any) -> set[str]:
    pages = getattr(app, "_turto_deferred_built_pages", None)
    if not isinstance(pages, set):
        pages = set()
        app._turto_deferred_built_pages = pages
    return pages


def _ensure_deferred_page(app: Any, key: str) -> bool:
    """Build one deferred page exactly once before its first navigation raise."""
    key = str(key or "")
    builders = getattr(type(app), "_turto_deferred_page_builders", {}) or {}
    builder = builders.get(key)
    if not callable(builder):
        return False
    built = _built_pages(app)
    if key in built:
        return False
    tabs = getattr(app, "tabs", {}) or {}
    if key not in tabs:
        raise KeyError(f"Deferred page container is missing: {key}")
    result = builder(app)
    built.add(key)
    try:
        app._turto_last_deferred_build = key
    except Exception:
        pass
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_deferred_page_build_803", False):
        return
    M._turto_deferred_page_build_803 = True

    App = M.App
    builders: dict[str, Any] = {}
    methods: dict[str, str] = {}
    for key, method_name in DEFERRED_PAGE_BUILD_METHODS.items():
        builder = getattr(App, method_name, None)
        if not callable(builder):
            continue
        builders[key] = builder
        methods[key] = method_name

    if not builders:
        M.DEFERRED_PAGE_BUILD_803 = {
            "owner": POLICY_OWNER,
            "pages": (),
            "navigation_owner_preserved": "price_lists_domain.platform.lazy_refresh",
        }
        return

    App._turto_deferred_page_builders = builders
    App._turto_deferred_page_methods = methods
    App._turto_ensure_deferred_page = _ensure_deferred_page

    # Mark only the initial composed App.build call. Its dynamic self.build_* calls
    # become cheap placeholders for selected secondary pages. Any explicit builder
    # call later keeps its historical semantics and constructs/reconstructs content.
    previous_build = App.build

    def build(self: Any, *args: Any, **kwargs: Any):
        previous = bool(getattr(self, "_turto_initial_deferred_build", False))
        self._turto_initial_deferred_build = True
        try:
            return previous_build(self, *args, **kwargs)
        finally:
            self._turto_initial_deferred_build = previous

    build._turto_803_deferred_build_scope = True
    App.build = build

    for key, method_name in methods.items():
        original = builders[key]

        def make_placeholder(page_key: str, function: Any):
            def placeholder(self: Any, *args: Any, **kwargs: Any):
                if getattr(self, "_turto_initial_deferred_build", False):
                    return None
                result = function(self, *args, **kwargs)
                _built_pages(self).add(page_key)
                return result

            placeholder._turto_deferred_page = page_key
            placeholder._turto_original_builder = function
            return placeholder

        setattr(App, method_name, make_placeholder(key, original))

    M.DEFERRED_PAGE_BUILD_803 = {
        "owner": POLICY_OWNER,
        "pages": tuple(builders),
        "navigation_owner_preserved": "price_lists_domain.platform.lazy_refresh",
        "core_workspaces_deferred": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "DEFERRED_PAGE_BUILD_METHODS",
    "_ensure_deferred_page",
]
