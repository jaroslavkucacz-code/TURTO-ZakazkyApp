"""Final Excel-export command owner for Nevoga / Reinforcement Systems.

The historical v624 layer intentionally owns the legacy Leviat/GEROtop layout and
binds UI commands directly to its local ``export_legacy`` closure.  Later Nevoga
support replaces ``module.export_offer_excel`` with a supplier-aware dispatcher,
but the already-bound Offers/detail commands otherwise keep calling the legacy
closure.  Install a hook before v769.apply() runs and take ownership only after
that layer has finished composing the final supplier-aware exporter.
"""
from __future__ import annotations

import sys


def _widget_exists(widget) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _install_final_owner(module) -> None:
    if getattr(module, "_turto_nevoga_export_route_final", False):
        return

    previous_selected = getattr(module.App, "export_selected_offer_excel", None)

    def export_selected_offer_excel(self):
        offer_id = self._selected_offer_id() if hasattr(self, "_selected_offer_id") else None
        if not offer_id:
            try:
                return module.messagebox.showinfo(
                    "Extrakce dat", "Vyberte nabídku.", parent=self
                )
            except Exception:
                return None

        exporter = getattr(module, "export_offer_excel", None)
        if callable(exporter):
            return exporter(self, offer_id, parent=self)
        if callable(previous_selected):
            return previous_selected(self)
        return None

    module.App.export_selected_offer_excel = export_selected_offer_excel
    module._turto_nevoga_export_selected_dynamic = True

    # v624 also rewires a historical detail-dialog button to its local legacy
    # exporter.  Rewire that button after v769 has added its rich Nevoga preview
    # so both entry points use the same final supplier-aware dispatcher.
    try:
        import crm_features
    except Exception:
        crm_features = None

    candidates = []
    for cls in (
        getattr(crm_features, "OfferDetailDialog", None) if crm_features else None,
        getattr(module, "OfferDetailDialog", None),
    ):
        if cls is not None and cls not in candidates:
            candidates.append(cls)

    for cls in candidates:
        if getattr(cls, "_turto_nevoga_export_route_final", False):
            continue
        previous_build = getattr(cls, "_build", None)
        if not callable(previous_build):
            continue

        def build(self, *args, __previous=previous_build, **kwargs):
            result = __previous(self, *args, **kwargs)
            try:
                root = getattr(self, "f", None)
                if not _widget_exists(root):
                    return result

                def walk(widget):
                    for child in widget.winfo_children():
                        try:
                            text = str(child.cget("text") or "").strip()
                        except Exception:
                            text = ""
                        if text in {
                            "Exportovat do Excelu",
                            "Extrakce dat do Excelu",
                            "Extrakce dat",
                        }:
                            try:
                                child.configure(
                                    text="Extrakce dat do Excelu",
                                    command=lambda current=self: getattr(
                                        module, "export_offer_excel"
                                    )(
                                        current.parent_app,
                                        current.oid,
                                        parent=current,
                                    ),
                                )
                            except Exception:
                                pass
                        walk(child)

                walk(root)
            except Exception:
                pass
            return result

        cls._build = build
        cls._turto_nevoga_export_route_final = True

    module._turto_nevoga_export_route_final = True


def install(module) -> None:
    """Hook v769.apply so the final UI command owner is installed afterwards."""
    if getattr(module, "_turto_nevoga_export_route_hook", False):
        return

    target = sys.modules.get("v769_nevoga_offer")
    original_apply = getattr(target, "apply", None) if target is not None else None
    if not callable(original_apply):
        return

    def apply(final_module):
        result = original_apply(final_module)
        _install_final_owner(final_module)
        return result

    target.apply = apply
    module._turto_nevoga_export_route_hook = True


__all__ = ["install"]
