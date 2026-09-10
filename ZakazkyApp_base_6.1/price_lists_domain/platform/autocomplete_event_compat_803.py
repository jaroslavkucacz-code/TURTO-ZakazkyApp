"""Scoped Python 3.14/Tk event and teardown compatibility for AutocompleteEntry.

Hosted Tk 8.6 can invoke a widget binding without an Event argument while a
Toplevel is being torn down. TURTO CRM already carries the same scoped workaround
for the category manager. AutocompleteEntry still has historical lambdas from the
base widget and its v615/v618 init wrappers that require one positional event even
though they never inspect it.

A long-session churn probe also showed that an autocomplete popup can outlive the
entry that created it. The popup is four Tk widgets (Toplevel, Frame, Listbox and
Scrollbar). Explicitly cancel the entry's pending show callback and destroy that
popup when the entry itself receives Destroy.

Do not patch Tkinter globally for normal runtime. Intercept bind() only while one
AutocompleteEntry is being constructed, adapt only known historical lambda
qualnames, restore Misc.bind immediately afterwards, then add one scoped Destroy
handler for lifecycle cleanup.
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


def _cleanup_entry_teardown(entry: Any, event: Any = None) -> None:
    """Release only resources owned by the AutocompleteEntry being destroyed."""
    if event is not None and getattr(event, "widget", entry) is not entry:
        return

    token = getattr(entry, "after_id", None)
    if token is not None:
        try:
            entry.after_cancel(token)
        except Exception:
            pass
        try:
            entry.after_id = None
        except Exception:
            pass

    popup = getattr(entry, "popup", None)
    if popup is not None:
        try:
            if popup.winfo_exists():
                popup.destroy()
        except Exception:
            pass
        try:
            entry.popup = None
            entry.listbox = None
        except Exception:
            pass


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
            result = previous_init(self, *args, **kwargs)
        finally:
            if misc.bind is compatible_bind:
                misc.bind = original_bind

        def teardown(event=None):
            _cleanup_entry_teardown(self, event)

        try:
            self.bind("<Destroy>", teardown, add="+")
            self._turto_803_teardown_callback = teardown
        except Exception:
            pass
        return result

    compatible_init._turto_803_optional_event_compat = True
    compatible_init._turto_original_init = previous_init
    Entry.__init__ = compatible_init
    Entry._turto_803_optional_event_compat = True

    M.AUTOCOMPLETE_EVENT_COMPAT_803 = {
        "owner": POLICY_OWNER,
        "scope": "AutocompleteEntry construction and owned popup teardown only",
        "event_argument": "optional for historical bound lambdas",
        "teardown": "cancel pending show and destroy owned popup",
        "tkinter_global_patch_retained": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_needs_optional_event",
    "_cleanup_entry_teardown",
]
