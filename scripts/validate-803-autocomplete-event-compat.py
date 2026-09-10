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
    def __init__(self):
        self.exists = True
        self.destroy_calls = 0

    def winfo_exists(self):
        return int(self.exists)

    def destroy(self):
        self.destroy_calls += 1
        self.exists = False


class FakeVariable:
    def __init__(self):
        self.removed = []

    def trace_remove(self, mode, token):
        self.removed.append((mode, token))


class FakeEntry:
    def __init__(self):
        self.after_id = "after-show"
        self.cancelled = []
        self.popup = FakePopup()
        self.listbox = object()
        self.var = FakeVariable()
        self._turto_803_owned_variable_traces = (
            (self.var, "write", "trace-owned"),
        )
        self._turto_registry_unregister = lambda: self

    def after_cancel(self, token):
        self.cancelled.append(token)


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

    print("TURTO CRM 8.0.3 autocomplete event/trace teardown compatibility: OK")


if __name__ == "__main__":
    main()
