"""Narrow Python 3.14/Tk event compatibility for AutocompleteEntry teardown.

Hosted Tk 8.6 can invoke a widget binding without an Event argument while a
Toplevel is being torn down. TURTO CRM already carries the same scoped workaround
for the category manager. AutocompleteEntry still has a few historical lambdas
from the base widget and its v615/v618 init wrappers that require one positional
event even though they never inspect it.

Do not patch Tkinter globally for normal runtime. Intercept bind() only while one
AutocompleteEntry is being constructed, adapt only the known historical lambda
qualnames, and restore Misc.bind immediately afterwards.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.autocomplete_event_compat_803"


def _needs_optional_event(callback: Any) -> bool:
    if not callable(callback):
        return False
    qualname = str(getattr(callback, "__qualname__", "") or "")
    return (
        qualname.startswith("AutocompleteEntry.__init__.<locals>.<lambda>")
        or qualname.startswith("apply.<locals>.init.<locals>.<lambda>")
    )


def apply(M: Any) -> None:
    Entry = getattr(M, "AutocompleteEntry", None)
    if Entry is None or getattr(Entry, "_turto_803_optional_event_compat", False):
        return

    previous_init = Entry.__init__

    def compatible_init(self: Any, *args: Any, **kwargs: Any):
        misc = M.tk.Misc
        original_bind = misc.bind

        def compatible_bind(widget, sequence=None, func=None, add=None):
            callback = func
            if _needs_optional_event(callback):
                def optional_event(event=None, _callback=callback):
                    return _callback(event)

                optional_event._turto_803_optional_event = True
                func = optional_event
            return original_bind(widget, sequence, func, add)

        misc.bind = compatible_bind
        try:
            return previous_init(self, *args, **kwargs)
        finally:
            if misc.bind is compatible_bind:
                misc.bind = original_bind

    compatible_init._turto_803_optional_event_compat = True
    compatible_init._turto_original_init = previous_init
    Entry.__init__ = compatible_init
    Entry._turto_803_optional_event_compat = True

    M.AUTOCOMPLETE_EVENT_COMPAT_803 = {
        "owner": POLICY_OWNER,
        "scope": "AutocompleteEntry construction only",
        "event_argument": "optional for historical bound lambdas",
        "tkinter_global_patch_retained": False,
        "database_rows_rewritten": False,
    }


__all__ = ["apply", "POLICY_OWNER", "_needs_optional_event"]
