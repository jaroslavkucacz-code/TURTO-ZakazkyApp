"""Final product-name cleanup for TURTO CRM 8.0.2.

This layer is deliberately presentation-only. It normalizes the visible product
name after all historical UI builders have run, without changing navigation,
business workflows, database schema or stored records.
"""
from __future__ import annotations

from typing import Any

POLICY_OWNER = "price_lists_domain.platform.branding_polish_802"


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _polish_visible_branding(app: Any, M: Any) -> None:
    """Normalize only exact historical product labels, never business text."""
    try:
        app.title(f"TURTO CRM {getattr(M, 'APP_VERSION', '')}".rstrip())
    except Exception:
        pass

    for widget in _walk(app):
        try:
            if widget.winfo_class() != "TLabel":
                continue
            text = str(widget.cget("text") or "")
            if text == "  |  Zakázky CRM":
                widget.configure(text="  CRM")
        except Exception:
            continue

    help_text = getattr(app, "help_text", None)
    if help_text is not None:
        try:
            previous_state = str(help_text.cget("state") or "normal")
            help_text.configure(state="normal")
            content = help_text.get("1.0", "end-1c")
            content = content.replace("TURTO Zakázky – verze", "TURTO CRM – verze")
            help_text.delete("1.0", "end")
            help_text.insert("1.0", content)
            help_text.configure(state=previous_state)
        except Exception:
            try:
                help_text.configure(state="disabled")
            except Exception:
                pass


def apply(M: Any) -> None:
    if getattr(M, "_turto_branding_polish_802", False):
        return
    M._turto_branding_polish_802 = True

    App = M.App
    old_build = App.build

    def build(self, *args, **kwargs):
        result = old_build(self, *args, **kwargs)
        _polish_visible_branding(self, M)
        return result

    App.build = build
    M.BRANDING_POLISH_OWNER = POLICY_OWNER


__all__ = ["apply", "POLICY_OWNER"]
