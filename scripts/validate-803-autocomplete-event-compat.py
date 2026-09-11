#!/usr/bin/env python3
"""Pure regression checks for AutocompleteEntry event/teardown compatibility."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_autocomplete_event_803_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakePopup:
    def __init__(self, viewable=True):
        self.exists = True
        self.viewable = bool(viewable)
        self.destroy_calls = 0

    def winfo_exists(self):
        return int(self.exists)

    def winfo_viewable(self):
        return int(self.viewable and self.exists)

    def destroy(self):
        self.destroy_calls += 1
        self.exists = False


class FakeVariable:
    def __init__(self):
        self.removed = []

    def trace_remove(self, mode, token):
        self.removed.append((mode, token))


class FakeEntry:
    def __init__(self, host=None, popup=None):
        self.after_id = "after-show"
        self.cancelled = []
        self.popup = popup if popup is not None else FakePopup()
        self.listbox = object()
        self.var = FakeVariable()
        self.host = host
        self.exists = True
        self.repositions = 0
        self._turto_803_owned_variable_traces = (
            (self.var, "write", "trace-owned"),
        )
        self._turto_registry_unregister = lambda: self

    def after_cancel(self, token):
        self.cancelled.append(token)

    def winfo_exists(self):
        return int(self.exists)

    def winfo_toplevel(self):
        return self.host

    def _reposition_popup(self):
        self.repositions += 1


class FakeHost:
    def __init__(self):
        self.bindings = []
        self.pending = {}
        self._next = 0

    def bind(self, sequence, callback, add=None):
        self.bindings.append((sequence, callback, add))
        return f"bind-{len(self.bindings)}"

    def after_idle(self, callback):
        self._next += 1
        token = f"idle-{self._next}"
        self.pending[token] = callback
        return token

    def run_idle(self, token):
        callback = self.pending.pop(token)
        callback()


def callback_with_required_event(event):
    return event


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    path = base / "price_lists_domain" / "platform" / "autocomplete_event_compat_803.py"
    bootstrap = (base / "runtime_bootstrap.py").read_text(encoding="utf-8")
    module = load_module(path)

    callback_with_required_event.__qualname__ = "AutocompleteEntry.__init__.<locals>.<lambda>"
    assert module._needs_optional_event(callback_with_required_event) is True

    def historical_wrapper(event):
        return event
    historical_wrapper.__qualname__ = "apply.<locals>.init.<locals>.<lambda>"
    assert module._needs_optional_event(historical_wrapper) is True

    def unrelated(event):
        return event
    assert module._needs_optional_event(unrelated) is False

    owner = object()
    bound = SimpleNamespace(__self__=owner)
    assert module._callback_belongs_to(owner, bound) is False

    class Owner:
        def callback(self):
            return None
    owner = Owner()
    assert module._callback_belongs_to(owner, owner.callback) is True
    assert module._callback_belongs_to(Owner(), owner.callback) is False

    # One host Configure binding replaces N per-entry bindings. No idle callback
    # is created while every popup is hidden, and resize storms coalesce when a
    # popup is visible.
    host = FakeHost()
    hidden = FakeEntry(host=host, popup=FakePopup(viewable=False))
    visible = FakeEntry(host=host, popup=FakePopup(viewable=True))
    registry = [hidden]
    M = SimpleNamespace(_AUTOCOMPLETE_ENTRIES=registry)

    def original_bind(widget, sequence=None, func=None, add=None):
        return widget.bind(sequence, func, add)

    assert module._install_shared_configure_binding(M, host, original_bind) is True
    assert module._install_shared_configure_binding(M, host, original_bind) is True
    assert len(host.bindings) == 1
    sequence, configured, add = host.bindings[0]
    assert sequence == "<Configure>" and add == "+"

    configured(SimpleNamespace(widget=host))
    assert host.pending == {}
    assert hidden.repositions == 0

    registry.append(visible)
    configured(SimpleNamespace(widget=host))
    token = host._turto_autocomplete_reposition_after_804
    assert token in host.pending
    configured(SimpleNamespace(widget=host))
    assert len(host.pending) == 1
    assert host._turto_autocomplete_configure_coalesced_804 == 1
    host.run_idle(token)
    assert host._turto_autocomplete_reposition_after_804 is None
    assert hidden.repositions == 0
    assert visible.repositions == 1

    # Foreign Configure events are ignored even if delivered through unusual
    # bindtags during teardown.
    configured(SimpleNamespace(widget=object()))
    assert host.pending == {}

    entry = FakeEntry()
    foreign = object()
    module._cleanup_entry_teardown(entry, SimpleNamespace(widget=foreign))
    assert entry.after_id == "after-show"
    assert entry.cancelled == []
    assert entry.popup.destroy_calls == 0
    assert entry.var.removed == []

    popup = entry.popup
    module._cleanup_entry_teardown(entry, SimpleNamespace(widget=entry))
    assert entry.var.removed == [("write", "trace-owned")]
    assert entry._turto_803_owned_variable_traces == ()
    assert entry.cancelled == ["after-show"]
    assert entry.after_id is None
    assert popup.destroy_calls == 1
    assert entry.popup is None
    assert entry.listbox is None
    assert "_turto_registry_unregister" not in entry.__dict__

    # Repeated teardown is harmless: neither trace nor popup is removed twice.
    module._cleanup_entry_teardown(entry)
    assert entry.var.removed == [("write", "trace-owned")]
    assert popup.destroy_calls == 1

    marker = '"price_lists_domain.platform.autocomplete_event_compat_803"'
    runtime = '"price_lists_domain.platform.runtime_optimization_803"'
    assert marker in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(runtime)

    print("TURTO CRM 8.0.3/8.0.4 autocomplete compatibility and Configure coalescing: OK")


if __name__ == "__main__":
    main()
