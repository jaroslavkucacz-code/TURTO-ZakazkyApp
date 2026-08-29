"""Small compatibility guards applied after the 6.3.30 platform patches."""
from __future__ import annotations

from . import categories, finalize


def install(M) -> None:
    """Accept both historical ``classify_text(M, value)`` and compact one-arg calls."""
    if getattr(M, "_turto_compat_v630", False):
        return

    def classify_text(module_or_value, value=None):
        actual = module_or_value if value is None else value
        hay = finalize._norm(actual)
        if not hay:
            return None
        rules, fallback = finalize._load_rules(M)
        for category_id, needles in rules:
            if any(needle in hay for needle in needles):
                return category_id
        return fallback

    categories.classify_text = classify_text
    M._turto_compat_v630 = True
