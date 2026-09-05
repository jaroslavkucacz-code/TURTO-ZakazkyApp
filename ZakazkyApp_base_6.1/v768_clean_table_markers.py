"""TURTO CRM 7.6.8+ compatibility: keep date text free of glyph markers.

Runtime composition is explicit in runtime_bootstrap.py.  This module no longer
imports or applies later release layers; it owns only its small compatibility job.
The final 7.7 policy may add font emphasis without changing stored/displayed dates.
"""


def _plain_date(value):
    text = str(value or "")
    for marker in ("⚠️ ", "⚠ ", "⚠️", "⚠", "● ", "●", "▲ ", "△ "):
        text = text.replace(marker, "")
    return text.strip()


def apply(M):
    if getattr(M, "_turto_v768_clean_table_markers", False):
        return
    M._turto_v768_clean_table_markers = True

    def clean_action_deadline_highlights(self, rows):
        tree = getattr(self, "action_tree", None)
        if tree is None:
            return
        for item in rows or ():
            iid = item[0] if item else None
            if not iid:
                continue
            try:
                if tree.exists(iid):
                    raw = str(tree.set(iid, "Deadline") or "")
                    clean = _plain_date(raw)
                    if clean != raw:
                        tree.set(iid, "Deadline", clean)
            except Exception:
                pass

    def clean_request_date_highlights(self, tree, rows):
        if tree is None:
            return
        for item in rows or ():
            iid = item[0] if item else None
            if not iid:
                continue
            try:
                if tree.exists(iid):
                    raw = str(tree.set(iid, "Poptáno") or "")
                    clean = _plain_date(raw)
                    if clean != raw:
                        tree.set(iid, "Poptáno", clean)
            except Exception:
                pass

    M.App._refresh_action_deadline_highlights = clean_action_deadline_highlights
    M.App._refresh_request_date_highlights = clean_request_date_highlights
    M.V768_TABLE_MARKERS_CLEAN = True
