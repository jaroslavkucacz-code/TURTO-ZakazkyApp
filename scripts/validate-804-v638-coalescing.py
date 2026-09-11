#!/usr/bin/env python3
"""Regression checks for TURTO CRM 8.0.4 v638 refresh coalescing."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_v638_coalescing_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeApp:
    def __init__(self):
        self._next = 0
        self.callbacks = {}
        self.cancelled = []

    def after(self, delay, callback):
        self._next += 1
        token = f"after-{self._next}"
        self.callbacks[token] = (int(delay), callback)
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)
        self.callbacks.pop(token, None)

    def tokens_for_delay(self, delay):
        return [token for token, (ms, _cb) in self.callbacks.items() if ms == delay]

    def run(self, token):
        _delay, callback = self.callbacks.pop(token)
        callback()


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1").resolve()
    path = root / "v638_table_updatefix.py"
    module = load_module(path)

    source = path.read_text(encoding="utf-8")
    assert "def _schedule_stabilize(" in source
    assert "_v638_stabilize_generation" in source
    assert "_v638_stabilize_sort_projects" in source
    assert "after_cancel" in source
    assert "for ms in (50,420)" not in source
    assert "for ms in (900,2200,3800)" in source
    assert "self.after(250" in source

    calls = []

    def stabilize(app, sort_projects=False):
        calls.append(bool(sort_projects))

    app = FakeApp()

    # First refresh creates exactly one fast/late pair.
    first = module._schedule_stabilize(app, stabilize, sort_projects=False)
    assert len(first) == 2
    assert sorted(ms for ms, _cb in app.callbacks.values()) == [50, 420]
    assert app._v638_stabilize_sort_projects is False

    # A project refresh replaces both old timers and promotes the pending pair
    # to the stronger sorting requirement.
    second = module._schedule_stabilize(app, stabilize, sort_projects=True)
    assert len(second) == 2
    assert len(app.cancelled) == 2
    assert len(app.callbacks) == 2
    assert app._v638_stabilize_sort_projects is True
    assert app._v638_stabilize_coalesced == 1

    # A weaker refresh in the same burst replaces the timers but must not lose
    # the already requested project sort.
    third = module._schedule_stabilize(app, stabilize, sort_projects=False)
    assert len(third) == 2
    assert len(app.cancelled) == 4
    assert len(app.callbacks) == 2
    assert app._v638_stabilize_sort_projects is True
    assert app._v638_stabilize_coalesced == 2

    fast = app.tokens_for_delay(50)
    late = app.tokens_for_delay(420)
    assert len(fast) == 1 and len(late) == 1
    app.run(fast[0])
    assert calls == [True]
    assert app._v638_stabilize_fast_after is None
    assert app._v638_stabilize_late_after == late[0]

    # A refresh between the fast and late pass cancels only the still-pending
    # late pass, starts a new pair, and preserves the stronger sort request.
    module._schedule_stabilize(app, stabilize, sort_projects=False)
    assert late[0] in app.cancelled
    assert len(app.callbacks) == 2
    assert app._v638_stabilize_sort_projects is True
    assert app._v638_stabilize_coalesced == 3

    fast = app.tokens_for_delay(50)
    late = app.tokens_for_delay(420)
    app.run(fast[0])
    app.run(late[0])
    assert calls == [True, True, True]
    assert app._v638_stabilize_fast_after is None
    assert app._v638_stabilize_late_after is None
    assert app._v638_stabilize_sort_projects is False

    # A new independent non-project burst is allowed to stay non-sorting.
    module._schedule_stabilize(app, stabilize, sort_projects=False)
    fast = app.tokens_for_delay(50)
    late = app.tokens_for_delay(420)
    app.run(fast[0])
    app.run(late[0])
    assert calls[-2:] == [False, False]
    assert app._v638_stabilize_sort_projects is False

    print("TURTO CRM 8.0.4 v638 refresh coalescing: OK")


if __name__ == "__main__":
    main()
