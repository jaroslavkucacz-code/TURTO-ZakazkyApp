"""Scoped Python 3.14/Tk event and teardown compatibility for AutocompleteEntry.

Hosted Tk 8.6 can invoke a widget binding without an Event argument while a
Toplevel is being torn down. TURTO CRM already carries the same scoped workaround
for the category manager. AutocompleteEntry still has historical lambdas from the
base widget and its v615/v618 init wrappers that require one positional event even
though they never inspect it.

Long-session churn also exposed two lifecycle resources that must be released when
an AutocompleteEntry is destroyed: its pending popup callback/popup window and the
``StringVar.trace_add('write', self._changed)`` command created by the historical
base widget. Tcl owns that trace command independently of the Tk entry widget, so
without an explicit ``trace_remove`` it keeps the Python AutocompleteEntry alive.

Do not patch Tkinter globally for normal runtime. Intercept ``bind()`` and
``Variable.trace_add()`` only while one AutocompleteEntry is being constructed,
record only traces whose callback is bound to that exact entry, restore both Tk
methods immediately, then release only those owned resources on Destroy.
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


def _callback_belongs_to(entry: Any, callback: Any) -> bool:
    """True only for a bound method whose owner is exactly this entry."""
    return callable(callback) and getattr(callback, "__self__", None) is entry


def _cleanup_entry_teardown(entry: Any, event: Any = None) -> None:
    """Release only resources owned by the AutocompleteEntry being destroyed."""
    if event is not None and getattr(event, "widget", entry) is not entry:
        return

    # A Variable trace creates a Tcl command that owns the bound Python callback.
    # Remove only trace tokens captured from this entry's own bound methods during
    # construction; never touch unrelated traces on a caller-provided StringVar.
    owned_traces = tuple(
        getattr(entry, "_turto_803_owned_variable_traces", ()) or ()
    )
    try:
        entry._turto_803_owned_variable_traces = ()
    except Exception:
        pass
    for variable, mode, token in owned_traces:
        try:
            variable.trace_remove(mode, token)
        except Exception:
            pass

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

    # runtime_optimization_803 stores its registry cleanup callback on the entry.
    # Once that earlier Destroy binding has run, the attribute is only a self-cycle.
    try:
        entry.__dict__.pop("_turto_registry_unregister", None)
    except Exception:
        pass


def apply(M: Any) -> None:
    Entry = getattr(M, "AutocompleteEntry", None)
    if Entry is None or getattr(Entry, "_turto_803_optional_event_compat", False):
        return

    previous_init = Entry.__init__

    def compatible_init(self: Any, *args: Any, **kwargs: Any):
        misc = M.tk.Misc
        variable_cls = M.tk.Variable
        original_bind = misc.bind
        original_trace_add = variable_cls.trace_add
        owned_traces: list[tuple[Any, Any, str]] = []

        def compatible_bind(widget, sequence=None, func=None, add=None):
            callback = func
            if _needs_optional_event(callback):
                def optional_event(event=None, _callback=callback):
                    return _callback(event)

                optional_event._turto_803_optional_event = True
                func = optional_event
            return original_bind(widget, sequence, func, add)

        def compatible_trace_add(variable, mode, callback):
            token = original_trace_add(variable, mode, callback)
            if _callback_belongs_to(self, callback):
                owned_traces.append((variable, mode, token))
            return token

        misc.bind = compatible_bind
        variable_cls.trace_add = compatible_trace_add
        try:
            result = previous_init(self, *args, **kwargs)
        finally:
            if variable_cls.trace_add is compatible_trace_add:
                variable_cls.trace_add = original_trace_add
            if misc.bind is compatible_bind:
                misc.bind = original_bind

        try:
            self._turto_803_owned_variable_traces = tuple(owned_traces)
        except Exception:
            pass

        def teardown(event=None):
            _cleanup_entry_teardown(self, event)

        try:
            # Use the restored original bind implementation. The callback command
            # belongs to the widget and Tk deletes it when the widget is destroyed.
            original_bind(self, "<Destroy>", teardown, "+")
        except Exception:
            pass
        return result

    compatible_init._turto_803_optional_event_compat = True
    compatible_init._turto_original_init = previous_init
    Entry.__init__ = compatible_init
    Entry._turto_803_optional_event_compat = True

    M.AUTOCOMPLETE_EVENT_COMPAT_803 = {
        "owner": POLICY_OWNER,
        "scope": "AutocompleteEntry construction and owned-resource teardown only",
        "event_argument": "optional for historical bound lambdas",
        "variable_trace_teardown": "remove only traces bound to the destroyed entry",
        "teardown": "remove owned write trace, cancel pending show and destroy owned popup",
        "tkinter_global_patch_retained": False,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_needs_optional_event",
    "_callback_belongs_to",
    "_cleanup_entry_teardown",
]
