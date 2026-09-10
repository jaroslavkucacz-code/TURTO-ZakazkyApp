"""Lean startup policy for TURTO CRM 7.9.4+.

Historical compatibility layers deliberately used delayed safety passes. Once the
current explicit runtime bootstrap and final UI policy are present, some of those
passes are redundant. This module coalesces only callbacks with a precisely
identified historical origin and keeps the first/functional passes intact.

The Nevoga/PLEXUS compatibility backfill is also pruned to offers that still have
an unresolved PLEXUS image. Existing canonical images are never reparsed merely
because the application was started again.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

POLICY_OWNER = "price_lists_domain.platform.startup_optimization"
V760_REDUNDANT_FINALIZE_DELAYS = frozenset({260, 1200})
# v628 already schedules both of these operations through after_idle from the
# actual build/theme path. The later safety repeats only walk the same UI again.
# Keep 1450 ms detach_hidden_pages and 1900 ms Outlook indicator untouched.
V628_REDUNDANT_COSMETIC_DELAYS = {
    1550: "apply_modern_palette",
    1750: "dashboard_layout",
}


def _callback_origin(callback: Any) -> tuple[str, str]:
    code = getattr(callback, "__code__", None)
    if code is None:
        return "", ""
    filename = Path(str(getattr(code, "co_filename", ""))).name
    name = str(getattr(code, "co_name", ""))
    return filename, name


def _is_redundant_v760_finalize(delay: Any, callback: Any) -> bool:
    try:
        milliseconds = int(delay)
    except Exception:
        return False
    if milliseconds not in V760_REDUNDANT_FINALIZE_DELAYS or not callable(callback):
        return False
    return _callback_origin(callback) == ("v760_table_activity_performance.py", "finalize")


def _closure_map(function: Any) -> dict[str, Any]:
    try:
        cells = function.__closure__ or ()
        names = function.__code__.co_freevars
        return {
            str(name): cell.cell_contents
            for name, cell in zip(names, cells)
        }
    except Exception:
        return {}


def _closure_callable_names(function: Any) -> set[str]:
    names: set[str] = set()
    for value in _closure_map(function).values():
        if callable(value):
            name = str(getattr(value, "__name__", "") or "").strip()
            if name:
                names.add(name)
    return names


def _redundant_v628_cosmetic(delay: Any, callback: Any) -> str | None:
    """Return the exact redundant v628 cosmetic target, otherwise None."""
    try:
        milliseconds = int(delay)
    except Exception:
        return None
    expected = V628_REDUNDANT_COSMETIC_DELAYS.get(milliseconds)
    if not expected or not callable(callback):
        return None
    if _callback_origin(callback) != ("v628_modernui_resize.py", "<lambda>"):
        return None
    return expected if expected in _closure_callable_names(callback) else None


def _is_v770_plexus_backfill(delay: Any, callback: Any) -> bool:
    try:
        milliseconds = int(delay)
    except Exception:
        return False
    if milliseconds != 800 or not callable(callback):
        return False
    if _callback_origin(callback) != ("v770_runtime_policy.py", "step"):
        return False
    return isinstance(_closure_map(callback).get("ids"), list)


def _table_columns(con: Any, table: str) -> set[str]:
    try:
        return {
            str(row[1])
            for row in con.execute(f'PRAGMA table_info("{table}")').fetchall()
        }
    except Exception:
        return set()


def _table_exists(con: Any, table: str) -> bool:
    try:
        return bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
        )
    except Exception:
        return False


def prune_plexus_backfill_ids(M: Any, ids: list[int]) -> tuple[int, int]:
    """Mutate ``ids`` to unresolved PLEXUS offers only.

    Returns ``(before, after)``. On an unknown/legacy schema the list is left
    untouched, so compatibility repair still runs exactly as before.
    """
    before = len(ids)
    if not ids:
        return before, before
    try:
        unique = list(dict.fromkeys(int(value) for value in ids))
    except Exception:
        return before, before

    try:
        with M.db() as con:
            item_columns = _table_columns(con, "supplier_offer_items")
            if "image_asset_key" not in item_columns:
                return before, before
            if not _table_exists(con, "offer_image_assets"):
                return before, before
            marks = ",".join("?" for _ in unique)
            rows = con.execute(
                f"""SELECT DISTINCT i.offer_id
                       FROM supplier_offer_items i
                       LEFT JOIN offer_image_assets a
                         ON a.asset_key=i.image_asset_key
                      WHERE i.offer_id IN ({marks})
                        AND lower(
                              coalesce(i.original_name,'') || ' ' ||
                              coalesce(i.item_key,'')
                            ) LIKE '%plexus%'
                        AND (
                              trim(coalesce(i.image_asset_key,''))=''
                              OR a.asset_key IS NULL
                              OR a.image_blob IS NULL
                              OR length(a.image_blob)=0
                            )""",
                tuple(unique),
            ).fetchall()
        unresolved = {int(row[0]) for row in rows}
    except Exception:
        return before, before

    ids[:] = [value for value in unique if value in unresolved]
    return before, len(ids)


def _call_previous_init_optimized(M: Any, instance: Any, previous_init: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        original_after = instance.after
    except Exception:
        return previous_init(instance, *args, **kwargs)

    state = getattr(instance, "__dict__", {})
    had_instance_after = "after" in state
    previous_instance_after = state.get("after")
    v760_suppressed: list[int] = []
    v628_suppressed: list[tuple[int, str]] = []
    plexus_before = 0
    plexus_after = 0

    def after_proxy(delay: Any, callback: Any = None, *callback_args: Any):
        nonlocal plexus_before, plexus_after
        if _is_redundant_v760_finalize(delay, callback):
            v760_suppressed.append(int(delay))
            return f"turto-coalesced-v760-{len(v760_suppressed)}"

        cosmetic = _redundant_v628_cosmetic(delay, callback)
        if cosmetic:
            v628_suppressed.append((int(delay), cosmetic))
            return f"turto-coalesced-v628-{len(v628_suppressed)}"

        if _is_v770_plexus_backfill(delay, callback):
            closure = _closure_map(callback)
            ids = closure.get("ids")
            if isinstance(ids, list):
                before, after = prune_plexus_backfill_ids(M, ids)
                plexus_before += before
                plexus_after += after
                if before and not after:
                    return "turto-skipped-complete-plexus-backfill"

        return original_after(delay, callback, *callback_args)

    try:
        instance.after = after_proxy
        return previous_init(instance, *args, **kwargs)
    finally:
        try:
            if had_instance_after:
                instance.after = previous_instance_after
            else:
                instance.__dict__.pop("after", None)
            instance._turto_v760_finalizers_coalesced = tuple(v760_suppressed)
            instance._turto_v628_cosmetic_passes_coalesced = tuple(v628_suppressed)
            instance._turto_plexus_backfill_candidates = plexus_before
            instance._turto_plexus_backfill_pending = plexus_after
        except Exception:
            pass


def apply(M: Any) -> None:
    if getattr(M, "_turto_startup_optimization", False):
        return
    M._turto_startup_optimization = True

    previous_init = M.App.__init__
    if not getattr(previous_init, "_turto_startup_optimized", False):
        def app_init(self, *args: Any, **kwargs: Any):
            return _call_previous_init_optimized(
                M,
                self,
                previous_init,
                *args,
                **kwargs,
            )

        app_init._turto_startup_optimized = True
        M.App.__init__ = app_init

    M.V794_STARTUP_OPTIMIZATION = {
        "owner": POLICY_OWNER,
        "v760_zero_ms_finalize_preserved": True,
        "v760_delayed_finalizers_suppressed": tuple(sorted(V760_REDUNDANT_FINALIZE_DELAYS)),
        "v628_after_idle_cosmetics_preserved": True,
        "v628_delayed_cosmetics_suppressed": tuple(sorted(V628_REDUNDANT_COSMETIC_DELAYS.items())),
        "v628_hidden_page_detach_preserved_ms": 1450,
        "v628_outlook_indicator_preserved_ms": 1900,
        "plexus_backfill": "unresolved-assets-only",
        "database_rows_rewritten_at_startup": False,
    }


__all__ = [
    "apply",
    "prune_plexus_backfill_ids",
    "V760_REDUNDANT_FINALIZE_DELAYS",
    "V628_REDUNDANT_COSMETIC_DELAYS",
]
