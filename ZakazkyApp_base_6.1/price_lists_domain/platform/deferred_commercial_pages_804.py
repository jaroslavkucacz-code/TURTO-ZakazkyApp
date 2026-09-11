"""Defer only the two newer commercial page bodies until first use.

The legacy CRM pages remain eagerly built because many historical compatibility
layers expect their widgets during App.__init__. Ceníky and Vydané nabídky were
added later through isolated app-integration wrappers and already participate in
the central lazy-refresh navigation owner. Their page frames/navigation buttons
can therefore be registered at startup while their expensive inner widget trees
are created on first navigation.

The policy is deliberately fail-closed: if the expected builders are missing or
a page was already built, normal behavior is retained. A failed deferred build
is logged and the page is not marked complete, so a later navigation can retry.
"""
from __future__ import annotations

from typing import Any
import traceback

POLICY_OWNER = "price_lists_domain.platform.deferred_commercial_pages_804"
PAGE_BUILDERS = {
    "pricelists": ("build_price_lists", "price_current_tree"),
    "issued_offers": ("build_issued_offers", "issued_offer_tree"),
}


def _restore_instance_attribute(obj: Any, name: str, had_instance: bool, value: Any) -> None:
    try:
        if had_instance:
            obj.__dict__[name] = value
        else:
            obj.__dict__.pop(name, None)
    except Exception:
        try:
            if had_instance:
                setattr(obj, name, value)
            else:
                delattr(obj, name)
        except Exception:
            pass


def _log(M: Any, app: Any, message: str) -> None:
    try:
        from price_lists_domain.platform import lazy_refresh
        lazy_refresh._log(M, "deferred-page", message)
    except Exception:
        pass


def _refresh_deferred_visuals(M: Any, app: Any) -> None:
    """Apply the active global theme to widgets that did not exist at startup."""
    try:
        theme = app.theme.get() if hasattr(app, "theme") else None
        app.apply_theme(theme, save=False)
    except TypeError:
        try:
            app.apply_theme(app.theme.get() if hasattr(app, "theme") else None)
        except Exception:
            pass
    except Exception:
        pass
    try:
        from price_lists_domain.platform import idle_cleanup_804
        idle_cleanup_804._apply_text_fonts_once(M, app)
    except Exception:
        pass


def _ensure_page_built(M: Any, app: Any, key: str) -> bool:
    builders = getattr(app, "_turto_deferred_page_builders_804", {}) or {}
    built = getattr(app, "_turto_deferred_pages_built_804", None)
    if not isinstance(built, set):
        built = set()
        app._turto_deferred_pages_built_804 = built
    if key in built or key not in builders:
        return True

    _method_name, marker = PAGE_BUILDERS[key]
    try:
        existing = getattr(app, marker, None)
        if existing is not None and bool(existing.winfo_exists()):
            built.add(key)
            return True
    except Exception:
        pass

    builder = builders.get(key)
    if not callable(builder):
        return False
    try:
        builder()
        marker_widget = getattr(app, marker, None)
        if marker_widget is None:
            raise RuntimeError(f"builder nevytvořil {marker}")
        try:
            if not marker_widget.winfo_exists():
                raise RuntimeError(f"widget {marker} neexistuje")
        except AttributeError:
            pass
        built.add(key)
        app._turto_deferred_pages_build_count_804 = int(
            getattr(app, "_turto_deferred_pages_build_count_804", 0) or 0
        ) + 1
        _refresh_deferred_visuals(M, app)
        return True
    except Exception:
        _log(M, app, f"{key}\n{traceback.format_exc(limit=10)}")
        return False


def apply(M: Any) -> None:
    if getattr(M, "_turto_deferred_commercial_pages_804", False):
        return
    M._turto_deferred_commercial_pages_804 = True
    App = M.App

    previous_build = getattr(App, "build", None)
    previous_show_page = getattr(App, "show_page", None)
    if not callable(previous_build) or not callable(previous_show_page):
        return

    def build(self: Any, *args: Any, **kwargs: Any):
        captured: dict[str, Any] = {}
        restored: dict[str, tuple[bool, Any]] = {}

        for key, (method_name, _marker) in PAGE_BUILDERS.items():
            builder = getattr(self, method_name, None)
            if not callable(builder):
                continue
            captured[key] = builder
            had_instance = method_name in getattr(self, "__dict__", {})
            previous_instance = getattr(self, "__dict__", {}).get(method_name)
            restored[method_name] = (had_instance, previous_instance)
            # app_integration wrappers still create the page + navigation; only
            # the body builder is suppressed during this one startup build.
            setattr(self, method_name, lambda *a, **k: None)

        try:
            result = previous_build(self, *args, **kwargs)
        finally:
            for method_name, (had_instance, previous_instance) in restored.items():
                _restore_instance_attribute(self, method_name, had_instance, previous_instance)

        self._turto_deferred_page_builders_804 = captured
        self._turto_deferred_pages_built_804 = set()
        self._turto_deferred_pages_startup_skipped_804 = tuple(sorted(captured))
        return result

    def show_page(self: Any, key: str, *args: Any, **kwargs: Any):
        if key in PAGE_BUILDERS:
            if not _ensure_page_built(M, self, key):
                try:
                    M.messagebox.showerror(
                        "Načtení záložky",
                        f"Záložku „{key}“ se nepodařilo vytvořit. Podrobnosti jsou v logs\\ui_navigation.log.",
                        parent=self,
                    )
                except Exception:
                    pass
                return None
        return previous_show_page(self, key, *args, **kwargs)

    build._turto_deferred_commercial_pages_804 = True
    build._turto_original = previous_build
    show_page._turto_deferred_commercial_pages_804 = True
    show_page._turto_original = previous_show_page
    App.build = build
    App.show_page = show_page

    M.DEFERRED_COMMERCIAL_PAGES_804 = {
        "owner": POLICY_OWNER,
        "pages": tuple(PAGE_BUILDERS),
        "legacy_crm_pages_deferred": False,
        "database_queries_changed": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "PAGE_BUILDERS",
    "_restore_instance_attribute",
    "_refresh_deferred_visuals",
    "_ensure_page_built",
]
