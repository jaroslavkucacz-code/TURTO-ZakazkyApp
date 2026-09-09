"""Python 3.14/Tk compatibility for the product-category manager.

A hosted Tk 8.6 build can invoke one of the manager's bound lambdas without an
Event argument while a modal window is being torn down. The legacy callbacks
expect exactly one positional event. Keep the established manager intact and
adapt only callbacks registered from that function so they also accept None.
"""
from __future__ import annotations

from importlib import import_module


def apply(M) -> None:
    categories = import_module("price_lists_domain.platform.categories")
    original_manage = getattr(categories, "manage_categories", None)
    if not callable(original_manage) or getattr(original_manage, "_turto_event_compat_800", False):
        return

    def manage_categories(module, app, *args, **kwargs):
        misc = module.tk.Misc
        original_bind = misc.bind

        def compatible_bind(self, sequence=None, func=None, add=None):
            callback = func
            qualname = str(getattr(callback, "__qualname__", "")) if callable(callback) else ""
            if callable(callback) and qualname.startswith("manage_categories.<locals>.<lambda>"):
                def optional_event(event=None, _callback=callback):
                    return _callback(event)

                func = optional_event
            return original_bind(self, sequence, func, add)

        misc.bind = compatible_bind
        try:
            return original_manage(module, app, *args, **kwargs)
        finally:
            if misc.bind is compatible_bind:
                misc.bind = original_bind

    manage_categories._turto_event_compat_800 = True
    categories.manage_categories = manage_categories
    M.V800_CATEGORY_EVENT_COMPAT = {
        "scope": "manage_categories bound lambdas only",
        "event_argument": "optional",
        "legacy_manager_rewritten": False,
    }


__all__ = ["apply"]
