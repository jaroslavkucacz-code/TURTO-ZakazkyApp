"""Single-owner App.__init__ lifecycle for TURTO CRM 8.0.

Historical runtime layers wrapped ``App.__init__`` one after another.  That made
startup order hard to audit and made later cleanup risky.  This module owns one
wrapper and lets compatibility layers register named before/after hooks while
preserving the exact nested-wrapper execution order:

* before-hooks run in reverse registration order;
* the original App.__init__ runs once;
* after-hooks run in registration order.

The registry is intentionally small.  It is not a general event bus and it does
not hide version-layer activation; runtime_bootstrap still explicitly applies
all runtime layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

BeforeHook = Callable[[Any, tuple[Any, ...], dict[str, Any]], None]
AfterHook = Callable[[Any, Any, tuple[Any, ...], dict[str, Any]], None]


@dataclass
class _Hook:
    name: str
    before: BeforeHook | None = None
    after: AfterHook | None = None


def apply(M: Any) -> None:
    """Install the single lifecycle wrapper and public registration helper."""
    if getattr(M, "_turto_app_lifecycle_installed", False):
        return

    hooks: list[_Hook] = []
    original_init = M.App.__init__

    def register_app_init_hook(
        name: str,
        *,
        before: BeforeHook | None = None,
        after: AfterHook | None = None,
    ) -> None:
        key = str(name or "").strip()
        if not key:
            raise ValueError("App lifecycle hook must have a name")
        for index, hook in enumerate(hooks):
            if hook.name == key:
                # Updating in-place keeps deterministic registration order.
                hooks[index] = _Hook(key, before, after)
                return
        hooks.append(_Hook(key, before, after))

    def lifecycle_init(self: Any, *args: Any, **kwargs: Any) -> Any:
        snapshot = tuple(hooks)
        for hook in reversed(snapshot):
            if hook.before is not None:
                hook.before(self, args, kwargs)
        result = original_init(self, *args, **kwargs)
        for hook in snapshot:
            if hook.after is not None:
                hook.after(self, result, args, kwargs)
        return result

    M.App.__init__ = lifecycle_init
    M.register_app_init_hook = register_app_init_hook
    M.APP_INIT_HOOKS = hooks
    M._turto_app_lifecycle_installed = True


def register(
    M: Any,
    name: str,
    *,
    before: BeforeHook | None = None,
    after: AfterHook | None = None,
) -> None:
    """Register a hook, also supporting isolated compatibility-layer tests."""
    if not getattr(M, "_turto_app_lifecycle_installed", False):
        apply(M)
    M.register_app_init_hook(name, before=before, after=after)
