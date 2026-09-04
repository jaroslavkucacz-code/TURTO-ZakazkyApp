"""TURTO CRM 7.6.8 - keep table dates free of emoji/status markers.

Older table code prefixed warning symbols (⚠ / ●) to date text. On Windows/Tk
those glyphs can be rendered by the colour emoji font as a magenta/pink box.
Urgency remains represented by the existing row/status colours; dates stay plain.
"""


def _plain_date(value):
    text = str(value or "")
    # Strip both text and emoji-presentation variants. Only date cells are passed
    # through this helper, so legitimate note/description text is untouched.
    for marker in ("⚠️ ", "⚠ ", "⚠️", "⚠", "● ", "●"):
        text = text.replace(marker, "")
    return text.strip()


def apply(M):
    def clean_action_deadline_highlights(self, rows):
        """Legacy compatibility hook: clean Deadline text, never add symbols."""
        tree = getattr(self, "action_tree", None)
        if tree is None:
            return
        for item in rows or ():
            iid = item[0] if item else None
            if not iid:
                continue
            try:
                if not tree.exists(iid):
                    continue
                raw = str(tree.set(iid, "Deadline") or "")
                clean = _plain_date(raw)
                if clean != raw:
                    tree.set(iid, "Deadline", clean)
            except Exception:
                continue

    def clean_request_date_highlights(self, tree, rows):
        """Legacy compatibility hook: clean Poptáno text, never add symbols."""
        if tree is None:
            return
        for item in rows or ():
            iid = item[0] if item else None
            if not iid:
                continue
            try:
                if not tree.exists(iid):
                    continue
                raw = str(tree.set(iid, "Poptáno") or "")
                clean = _plain_date(raw)
                if clean != raw:
                    tree.set(iid, "Poptáno", clean)
            except Exception:
                continue

    # These are intentionally the final owners of the two callbacks. Existing
    # refresh code can keep calling them after_idle, but they only sanitize text.
    M.App._refresh_action_deadline_highlights = clean_action_deadline_highlights
    M.App._refresh_request_date_highlights = clean_request_date_highlights
    M.V768_TABLE_MARKERS_CLEAN = True
