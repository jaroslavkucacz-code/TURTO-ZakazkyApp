"""Narrow Tk callback compatibility fixes for TURTO CRM 8.0.3 work.

A long-session Windows churn probe proved that the historical AutocompleteEntry
FocusOut lambda can occasionally be invoked by Tk without an event argument
while a widget/dialog is being torn down. The callback never uses the event; it
only schedules the existing 120 ms hide check. Rebind only this one sequence with
an optional event parameter and preserve every other autocomplete binding.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.callback_compat_803"


def _install_autocomplete_focusout_compat(M: Any) -> bool:
    Entry = getattr(M, "AutocompleteEntry", None)
    if Entry is None:
        return False
    if getattr(Entry, "_turto_803_focusout_compat", False):
        return True

    previous_init = Entry.__init__

    def entry_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_init(self, *args, **kwargs)

        def focus_out(_event: Any = None) -> None:
            try:
                self.after(120, self._hide_if_needed)
            except Exception:
                pass

        try:
            # add=False deliberately replaces only the historical FocusOut
            # callback from app.py. Down/Up/Return/Escape/Click/FocusIn and the
            # Toplevel Configure callback remain owned by their original code.
            self.bind("<FocusOut>", focus_out, add=False)
            self._turto_focusout_callback = focus_out
        except Exception:
            pass
        return result

    entry_init._turto_803_focusout_compat = True
    entry_init._turto_original_init = previous_init
    Entry.__init__ = entry_init
    Entry._turto_803_focusout_compat = True
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_callback_compat_803", False):
        return
    M._turto_callback_compat_803 = True
    installed = _install_autocomplete_focusout_compat(M)
    M.CALLBACK_COMPAT_803 = {
        "owner": POLICY_OWNER,
        "autocomplete_focusout": "optional-event-preserve-120ms-hide",
        "installed": bool(installed),
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "_install_autocomplete_focusout_compat",
]
