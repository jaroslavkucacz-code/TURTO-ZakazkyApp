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
    """Retain the legacy layer marker without owning UI callbacks.

    Since 7.7 the final runtime policy owns both deadline/request highlighting
    and also strips historical glyph markers. Keeping another callback owner
    here only creates ordering-dependent behavior, so v768 is intentionally a
    compatibility marker plus the reusable _plain_date helper.
    """
    if getattr(M, "_turto_v768_clean_table_markers", False):
        return
    M._turto_v768_clean_table_markers = True
    M.V768_TABLE_MARKERS_CLEAN = True
