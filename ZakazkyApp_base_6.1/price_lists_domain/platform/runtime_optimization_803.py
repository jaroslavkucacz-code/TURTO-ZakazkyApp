"""Low-risk runtime optimization and observability for TURTO CRM 8.0.3-dev.

The canonical lazy-refresh owner already keeps hidden data pages dirty and loads
only the visible page. This layer deliberately does not replace navigation or
refresh_all. It removes redundant hidden-header database work, releases destroyed
autocomplete widgets from their process-wide registry, caches deterministic
Czech sort keys used repeatedly by SQLite collations, coalesces repeated dialog
z-order sweeps, immediately detaches already-built hidden pages, and records
compact timings from real Windows execution.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
import time
from typing import Any, Callable

POLICY_OWNER = "price_lists_domain.platform.runtime_optimization_803"
PERFORMANCE_LOG = "performance.log"
PERFORMANCE_LOG_MAX_BYTES = 1024 * 1024
CZECH_SORT_CACHE_SIZE = 8192

BUILD_METHODS = (
    "build_dash",
    "build_actions",
    "build_requests",
    "build_mivo",
    "build_offers",
    "build_price_lists",
    "build_issued_offers",
    "build_tasks",
    "build_projects",
    "build_people",
    "build_companies",
    "build_help",
    "build_settings",
)


def _widget_managed(widget: Any) -> bool:
    """True only when a widget exists and is actually managed on screen."""
    if widget is None:
        return False
    try:
        return bool(widget.winfo_exists() and str(widget.winfo_manager() or "").strip())
    except Exception:
        return False


def _header_refresh_needed(app: Any) -> bool:
    """Preserve future/header variants while skipping today's two hidden labels."""
    has_date = hasattr(app, "date_label")
    has_summary = hasattr(app, "today_summary")
    if not has_date and not has_summary:
        return True
    return _widget_managed(getattr(app, "date_label", None)) or _widget_managed(
        getattr(app, "today_summary", None)
    )


def _make_dialog_chain_coalescer(function: Callable[..., Any]) -> Callable[..., Any]:
    """Collapse repeated Map/FocusIn sweeps while keeping modal grabs immediate."""
    def coalesced(app: Any, event: Any = None):
        # A modal grab needs immediate focus protection and can be handled without
        # recursively walking the full application widget tree.
        try:
            grabbed = app.grab_current()
            if grabbed is not None and grabbed.winfo_exists():
                grabbed.lift()
                grabbed.focus_force()
                return None
        except Exception:
            pass

        pending = getattr(app, "_turto_dialog_raise_after", None)
        if pending is not None:
            try:
                app._turto_dialog_raise_events_coalesced = int(
                    getattr(app, "_turto_dialog_raise_events_coalesced", 0) or 0
                ) + 1
            except Exception:
                pass
            return pending

        def run() -> None:
            try:
                function(app)
            finally:
                try:
                    app._turto_dialog_raise_after = None
                except Exception:
                    pass

        try:
            token = app.after_idle(run)
            app._turto_dialog_raise_after = token
            return token
        except Exception:
            try:
                return function(app, event)
            except TypeError:
                return function(app)

    coalesced._turto_803_dialog_chain = True
    coalesced._turto_original_dialog_chain = function
    return coalesced


def _install_dialog_chain_coalescing() -> bool:
    """Patch the global referenced by crm_runtime's already-installed bindings."""
    try:
        import crm_runtime
    except Exception:
        return False
    previous = getattr(crm_runtime, "_raise_dialog_chain", None)
    if not callable(previous):
        return False
    if getattr(previous, "_turto_803_dialog_chain", False):
        return True
    crm_runtime._raise_dialog_chain = _make_dialog_chain_coalescer(previous)
    return True


def _detach_hidden_pages_now(app: Any) -> tuple[str, ...]:
    """Remove already-built hidden pages from geometry before the first idle turn.

    This is deliberately not deferred construction: every builder and historical
    compatibility wrapper has already completed. It only performs the same
    ``grid_remove`` policy that older UI layers applied later, preventing hidden
    Treeviews from receiving startup Configure/Map work in the meantime.
    """
    try:
        tabs = getattr(app, "tabs", {}) or {}
        current = str(getattr(app, "_current_page", "") or "")
        if not isinstance(tabs, dict) or not current or current not in tabs:
            return ()
    except Exception:
        return ()

    detached: list[str] = []
    for key, page in list(tabs.items()):
        if str(key) == current:
            continue
        try:
            if page is None or not page.winfo_exists():
                continue
        except Exception:
            # Minimal/fake page objects used by tests may not expose winfo_exists;
            # grid_remove itself remains the authoritative capability check.
            pass
        try:
            page.grid_remove()
            detached.append(str(key))
        except Exception:
            pass
    try:
        app._turto_hidden_pages_detached_immediately = tuple(detached)
    except Exception:
        pass
    return tuple(detached)


def _timing_store(instance: Any) -> dict[str, list[float]]:
    data = getattr(instance, "_turto_perf_timings", None)
    if not isinstance(data, dict):
        data = {}
        try:
            instance._turto_perf_timings = data
        except Exception:
            pass
    return data


def _record_timing(instance: Any, name: str, elapsed: float) -> None:
    try:
        store = _timing_store(instance)
        values = store.setdefault(str(name), [])
        values.append(max(0.0, float(elapsed)))
        if len(values) > 8:
            del values[:-8]
    except Exception:
        pass


def _performance_log_path(M: Any) -> Path:
    root = Path(getattr(M, "DATA_ROOT", Path.home() / "Documents" / "TURTO Zakazky"))
    return root / "logs" / PERFORMANCE_LOG


def _rotate_log(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size <= PERFORMANCE_LOG_MAX_BYTES:
            return
        old = path.with_name(path.name + ".1")
        try:
            old.unlink(missing_ok=True)
        except Exception:
            pass
        path.replace(old)
    except Exception:
        pass


def _write_startup_profile(M: Any, instance: Any, total: float) -> None:
    """Append one compact line per application start; failures are non-fatal."""
    try:
        path = _performance_log_path(M)
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log(path)
        store = dict(_timing_store(instance))
        latest = {
            key: float(values[-1])
            for key, values in store.items()
            if values
        }
        ordered = []
        for key in ("build_total", *BUILD_METHODS, "apply_theme"):
            if key in latest:
                ordered.append(f"{key}={latest[key]:.4f}s")
        extras = sorted(
            (key, value)
            for key, value in latest.items()
            if key not in {"build_total", *BUILD_METHODS, "apply_theme", "app_init"}
        )
        ordered.extend(f"{key}={value:.4f}s" for key, value in extras)
        skips = int(getattr(instance, "_turto_hidden_header_refresh_skips", 0) or 0)
        dialog_coalesced = int(getattr(instance, "_turto_dialog_raise_events_coalesced", 0) or 0)
        detached_pages = len(
            getattr(instance, "_turto_hidden_pages_detached_immediately", ()) or ()
        )
        line = (
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"version={getattr(M, 'APP_VERSION', '')} app_init={float(total):.4f}s "
            f"hidden_header_skips={skips} "
            f"dialog_raise_coalesced={dialog_coalesced} hidden_pages_detached={detached_pages}"
        )
        cache_info = getattr(getattr(M, "czech_sort_key", None), "cache_info", None)
        if callable(cache_info):
            try:
                info = cache_info()
                line += (
                    f" czech_cache_hits={int(info.hits)}"
                    f" czech_cache_misses={int(info.misses)}"
                    f" czech_cache_size={int(info.currsize)}"
                )
            except Exception:
                pass
        if ordered:
            line += " " + " ".join(ordered)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
        try:
            instance._turto_performance_log = str(path)
        except Exception:
            pass
    except Exception:
        # Profiling must never be able to prevent CRM startup.
        pass


def _timed_method(function: Callable[..., Any], name: str) -> Callable[..., Any]:
    def wrapped(self: Any, *args: Any, **kwargs: Any):
        started = time.perf_counter()
        try:
            return function(self, *args, **kwargs)
        finally:
            _record_timing(self, name, time.perf_counter() - started)

    wrapped._turto_perf_timed = True
    wrapped._turto_perf_name = name
    return wrapped


def _install_czech_sort_cache(M: Any) -> bool:
    """Cache only string inputs while preserving the exact historical sort key."""
    previous = getattr(M, "czech_sort_key", None)
    if not callable(previous):
        return False
    if getattr(previous, "_turto_803_cached", False):
        return True

    @lru_cache(maxsize=CZECH_SORT_CACHE_SIZE)
    def cached_text(value: str):
        return previous(value)

    def czech_sort_key(value: Any):
        # SQLite collations pass strings. Non-string callers keep the historical
        # behavior exactly, including any custom __str__ implementation.
        if isinstance(value, str):
            return cached_text(value)
        return previous(value)

    czech_sort_key._turto_803_cached = True
    czech_sort_key.cache_info = cached_text.cache_info
    czech_sort_key.cache_clear = cached_text.cache_clear
    M.czech_sort_key = czech_sort_key
    return True


def _install_autocomplete_cleanup(M: Any) -> bool:
    """Remove destroyed AutocompleteEntry objects from the legacy global list."""
    Entry = getattr(M, "AutocompleteEntry", None)
    registry = getattr(M, "_AUTOCOMPLETE_ENTRIES", None)
    if Entry is None or not isinstance(registry, list):
        return False
    if getattr(Entry, "_turto_803_registry_cleanup", False):
        return True

    previous_init = Entry.__init__

    def entry_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_init(self, *args, **kwargs)

        def unregister(event: Any = None) -> None:
            if event is not None and getattr(event, "widget", self) is not self:
                return
            try:
                registry[:] = [item for item in registry if item is not self]
            except Exception:
                pass

        try:
            self.bind("<Destroy>", unregister, add="+")
            self._turto_registry_unregister = unregister
        except Exception:
            pass
        return result

    Entry.__init__ = entry_init
    Entry._turto_803_registry_cleanup = True
    return True


def apply(M: Any) -> None:
    if getattr(M, "_turto_runtime_optimization_803", False):
        return
    M._turto_runtime_optimization_803 = True

    App = M.App

    # Install before App() exists so every startup ORDER BY ... COLLATE CZECH
    # benefits while _czech_collate continues using the same public function name.
    _install_czech_sort_cache(M)
    _install_dialog_chain_coalescing()

    # Keep price_lists_domain.platform.lazy_refresh as the single navigation and
    # dirty-page owner. We only optimize the final chrome callback it invokes.
    previous_header = getattr(App, "refresh_header", None)
    if callable(previous_header) and not getattr(previous_header, "_turto_803_header", False):
        def refresh_header(self: Any, *args: Any, **kwargs: Any):
            if not _header_refresh_needed(self):
                try:
                    self._turto_hidden_header_refresh_skips = int(
                        getattr(self, "_turto_hidden_header_refresh_skips", 0) or 0
                    ) + 1
                except Exception:
                    pass
                return None
            return previous_header(self, *args, **kwargs)

        refresh_header._turto_803_header = True
        App.refresh_header = refresh_header

    _install_autocomplete_cleanup(M)

    # Time the final composed builders. This does not change their return value,
    # call order, widget ownership or database behavior.
    for method_name in BUILD_METHODS:
        function = getattr(App, method_name, None)
        if not callable(function) or getattr(function, "_turto_perf_timed", False):
            continue
        setattr(App, method_name, _timed_method(function, method_name))

    build = getattr(App, "build", None)
    if callable(build) and not getattr(build, "_turto_perf_timed", False):
        App.build = _timed_method(build, "build_total")

    apply_theme = getattr(App, "apply_theme", None)
    if callable(apply_theme) and not getattr(apply_theme, "_turto_perf_timed", False):
        App.apply_theme = _timed_method(apply_theme, "apply_theme")

    previous_init = App.__init__
    if not getattr(previous_init, "_turto_803_init_timed", False):
        def app_init(self: Any, *args: Any, **kwargs: Any):
            started = time.perf_counter()
            try:
                result = previous_init(self, *args, **kwargs)
                _detach_hidden_pages_now(self)
                return result
            finally:
                elapsed = time.perf_counter() - started
                _record_timing(self, "app_init", elapsed)
                _write_startup_profile(M, self, elapsed)

        app_init._turto_803_init_timed = True
        App.__init__ = app_init

    M.RUNTIME_OPTIMIZATION_803 = {
        "owner": POLICY_OWNER,
        "navigation_owner_preserved": "price_lists_domain.platform.lazy_refresh",
        "hidden_header_database_work": "skipped-while-unmanaged",
        "autocomplete_registry": "destroy-unregister",
        "czech_sort_cache_size": CZECH_SORT_CACHE_SIZE,
        "dialog_focus_sweep": "map-focus-events-coalesced",
        "initial_page_geometry": "built-then-hidden-pages-grid-removed",
        "startup_profile": PERFORMANCE_LOG,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "BUILD_METHODS",
    "PERFORMANCE_LOG",
    "CZECH_SORT_CACHE_SIZE",
    "_widget_managed",
    "_header_refresh_needed",
    "_make_dialog_chain_coalescer",
    "_install_dialog_chain_coalescing",
    "_detach_hidden_pages_now",
    "_install_czech_sort_cache",
    "_install_autocomplete_cleanup",
]
