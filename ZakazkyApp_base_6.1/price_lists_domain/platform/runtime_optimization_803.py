"""Low-risk runtime optimization and observability for TURTO CRM 8.0.3-dev.

The canonical lazy-refresh owner already keeps hidden data pages dirty and loads
only the visible page.  This layer deliberately does not replace navigation or
refresh_all.  It removes one remaining redundant database refresh (the historical
header summary while both header widgets are not displayed) and records one
compact startup timing line so later optimization can be based on real Windows
measurements instead of guesses.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

POLICY_OWNER = "price_lists_domain.platform.runtime_optimization_803"
PERFORMANCE_LOG = "performance.log"
PERFORMANCE_LOG_MAX_BYTES = 1024 * 1024

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
        # A startup normally calls each builder once. Keep a small cap so an
        # unusually long session cannot grow diagnostic state indefinitely.
        if len(values) > 8:
            del values[:-8]
    except Exception:
        pass


def _latest_timing(instance: Any, name: str) -> float | None:
    try:
        values = _timing_store(instance).get(name) or []
        return float(values[-1]) if values else None
    except Exception:
        return None


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
        line = (
            f"[{datetime.now():%Y-%m-%d %H:%M:%S}] "
            f"version={getattr(M, 'APP_VERSION', '')} app_init={float(total):.4f}s "
            f"hidden_header_skips={skips}"
        )
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


def apply(M: Any) -> None:
    if getattr(M, "_turto_runtime_optimization_803", False):
        return
    M._turto_runtime_optimization_803 = True

    App = M.App

    # Keep price_lists_domain.platform.lazy_refresh as the single navigation and
    # dirty-page owner.  We only optimize the final chrome callback it invokes.
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

    # Time the final composed builders.  This does not change their return value,
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
                return previous_init(self, *args, **kwargs)
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
        "startup_profile": PERFORMANCE_LOG,
        "database_rows_rewritten": False,
    }


__all__ = [
    "apply",
    "POLICY_OWNER",
    "BUILD_METHODS",
    "PERFORMANCE_LOG",
    "_widget_managed",
    "_header_refresh_needed",
]
