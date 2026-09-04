"""TURTO CRM 7.6.15 - Nevoga commercial quantities and prices are per metre.

The supplier PDF contains pieces, element length and a CZK/m source price. The
provider converts the commercial quantity to total metres. This layer only makes
the received-offer UI headings explicit so no Nevoga price is labelled as Kč/ks.
"""
from __future__ import annotations


def _is_nevoga_name(value):
    folded = str(value or "").strip().casefold()
    return any(token in folded for token in ("nevoga", "nevegar", "reinforcement systems"))


def _meter_headings(tree):
    if tree is None:
        return
    for column, label in (
        ("Pův. cena", "Pův. cena/m"),
        ("Cena/ks", "Cena/m"),
    ):
        try:
            tree.heading(column, text=label)
        except Exception:
            pass


def _walk_treeviews(widget, callback):
    try:
        for child in widget.winfo_children():
            try:
                if child.winfo_class() == "Treeview":
                    callback(child)
            except Exception:
                pass
            _walk_treeviews(child, callback)
    except Exception:
        pass


def apply(M):
    if getattr(M, "_turto_v7615_nevoga_meter_units", False):
        return
    M._turto_v7615_nevoga_meter_units = True

    try:
        import crm_features
    except Exception:
        crm_features = None

    detail_classes = []
    for cls in (
        getattr(crm_features, "OfferDetailDialog", None) if crm_features else None,
        getattr(M, "OfferDetailDialog", None),
    ):
        if cls is not None and cls not in detail_classes:
            detail_classes.append(cls)

    for cls in detail_classes:
        if getattr(cls, "_turto_v7615_meter_headings", False):
            continue
        previous_build = cls._build

        def build(self, *args, __previous=previous_build, **kwargs):
            result = __previous(self, *args, **kwargs)
            try:
                offer = getattr(self, "offer_row", None)
                supplier = (offer["supplier"] if offer is not None else "") or ""
                if _is_nevoga_name(supplier):
                    _meter_headings(getattr(self, "tree", None))
            except Exception:
                pass
            return result

        cls._build = build
        cls._turto_v7615_meter_headings = True

    history_classes = []
    for cls in (
        getattr(crm_features, "OfferPriceHistoryDialog", None) if crm_features else None,
        getattr(M, "OfferPriceHistoryDialog", None),
    ):
        if cls is not None and cls not in history_classes:
            history_classes.append(cls)

    for cls in history_classes:
        if getattr(cls, "_turto_v7615_history_meter_headings", False):
            continue
        previous_init = cls.__init__

        def init(self, *args, __previous=previous_init, **kwargs):
            result = __previous(self, *args, **kwargs)
            try:
                supplier = kwargs.get("supplier")
                if supplier is None and len(args) >= 2:
                    supplier = args[1]
                if _is_nevoga_name(supplier):
                    _walk_treeviews(self, _meter_headings)
            except Exception:
                pass
            return result

        cls.__init__ = init
        cls._turto_v7615_history_meter_headings = True

    M.V7615_NEVOGA_METER_UNITS = {
        "commercial_unit": "m",
        "unit_price_label": "Cena/m",
        "source_piece_count_preserved_in_details": True,
    }
