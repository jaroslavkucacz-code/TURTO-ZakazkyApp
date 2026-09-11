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

TURTO CRM 8.0.4 also consolidates the historical per-entry Toplevel <Configure>
binding. A main page can contain around twenty AutocompleteEntry widgets; binding
one reposition lambda per entry multiplied every window resize by that count even
when no popup existed. Construction now installs one handler per host Toplevel.
It schedules one idle reposition only when at least one popup is actually visible.

Do not patch Tkinter globally for normal runtime. Intercept ``bind()`` and
``Variable.trace_add()`` only while one AutocompleteEntry is being constructed,
record only traces whose callback is bound to that exact entry, restore both Tk
methods immediately, then release only those owned resources on Destroy.
"""
from __future__ import annotations

from typing import Any
import weakref

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


def _visible_popup_on_host(entry: Any, host: Any) -> bool:
    try:
        if not entry.winfo_exists() or entry.winfo_toplevel() is not host:
            return False
        popup = getattr(entry, "popup", None)
        return bool(
            popup is not None
            and popup.winfo_exists()
            and popup.winfo_viewable()
        )
    except Exception:
        return False


def _install_shared_configure_binding(M: Any, host: Any, original_bind: Any) -> bool:
    """Install one coalesced popup reposition handler for one host Toplevel."""
    if getattr(host, "_turto_autocomplete_configure_804", False):
        return True
    registry = getattr(M, "_AUTOCOMPLETE_ENTRIES", None)
    if not isinstance(registry, list):
        return False
    try:
        host_ref = weakref.ref(host)
    except Exception:
        return False

    def configured(event: Any = None) -> None:
        current = host_ref()
        if current is None:
            return
        if event is not None and getattr(event, "widget", current) is not current:
            return

        # In the normal idle CRM every popup is None/withdrawn. Avoid creating
        # any Tk after_idle command at all unless there is visible work to do.
        if not any(_visible_popup_on_host(entry, current) for entry in tuple(registry)):
            return

        pending = getattr(current, "_turto_autocomplete_reposition_after_804", None)
        if pending is not None:
            try:
                current._turto_autocomplete_configure_coalesced_804 = int(
                    getattr(current, "_turto_autocomplete_configure_coalesced_804", 0) or 0
                ) + 1
            except Exception:
                pass
            return

        def run() -> None:
            owner = host_ref()
            if owner is None:
                return
            try:
                owner._turto_autocomplete_reposition_after_804 = None
            except Exception:
                pass
            for entry in tuple(registry):
                if not _visible_popup_on_host(entry, owner):
                    continue
                try:
                    entry._reposition_popup()
                except Exception:
                    pass

        try:
            current._turto_autocomplete_reposition_after_804 = current.after_idle(run)
        except Exception:
            try:
                run()
            except Exception:
                pass

    try:
        original_bind(host, "<Configure>", configured, "+")
        host._turto_autocomplete_configure_804 = True
        host._turto_autocomplete_configure_handler_804 = configured
        return True
    except Exception:
        return False


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

            # Base AutocompleteEntry historically bound one Configure lambda to
            # its host Toplevel for every entry. Suppress that individual binding
            # and install one shared, visibility-aware handler for the host.
            if sequence == "<Configure>" and _needs_optional_event(callback):
                try:
                    host = self.winfo_toplevel()
                    if widget is host and _install_shared_configure_binding(
                        M, host, original_bind
                    ):
                        return "turto-autocomplete-configure-shared"
                except Exception:
                    pass

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
        "host_configure": "one shared handler; visible popups only; idle-coalesced",
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
    "_visible_popup_on_host",
    "_install_shared_configure_binding",
    "_cleanup_entry_teardown",
]
