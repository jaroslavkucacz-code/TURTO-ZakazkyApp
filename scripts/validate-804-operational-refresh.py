#!/usr/bin/env python3
"""Pure regression checks for TURTO CRM 8.0.4 operational refresh optimization."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("turto_operational_refresh_804_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeTree:
    def __init__(self):
        self.rows = {}
        self.order = []
        self.configured_tags = {}
        self._sort_state = {}
        self._active_sort = None

    def tag_configure(self, tag, **kwargs):
        self.configured_tags[tag] = dict(kwargs)

    def insert(self, parent, index, iid=None, **kw):
        iid = iid or f"row-{len(self.order)+1}"
        self.rows[iid] = {
            "values": tuple(kw.get("values") or ()),
            "tags": tuple(kw.get("tags") or ()),
        }
        self.order.append(iid)
        return iid

    def item(self, iid, option=None, **kw):
        if iid not in self.rows:
            raise KeyError(iid)
        if kw:
            if "tags" in kw:
                self.rows[iid]["tags"] = tuple(kw["tags"] or ())
            if "values" in kw:
                self.rows[iid]["values"] = tuple(kw["values"] or ())
        if option == "tags":
            return self.rows[iid]["tags"]
        if option == "values":
            return self.rows[iid]["values"]
        return dict(self.rows[iid])

    def cget(self, option):
        if option == "columns":
            return ("Stav", "Přijato", "Deadline")
        raise KeyError(option)

    def get_children(self, parent=""):
        return tuple(self.order)

    def set(self, iid, column):
        columns = self.cget("columns")
        return self.rows[iid]["values"][columns.index(column)]

    def move(self, iid, parent, position):
        self.order.remove(iid)
        self.order.insert(position, iid)


class FakeApp:
    def __init__(self):
        self.action_tree = FakeTree()
        self.task_tree = FakeTree()
        self.after_idle_calls = 0

    def after_idle(self, callback):
        self.after_idle_calls += 1
        callback()
        return f"idle-{self.after_idle_calls}"

    def effective(self, row):
        return row.get("status") or "Rozpracováno"


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    base = repo / "ZakazkyApp_base_6.1"
    path = base / "price_lists_domain" / "platform" / "operational_refresh_804.py"
    bootstrap = (base / "runtime_bootstrap.py").read_text(encoding="utf-8")
    module = load_module(path)

    # Date formatting is pure and repeated operational dates must hit the cache.
    calls = []

    def original_fmt(value):
        calls.append(value)
        return f"fmt:{value}"

    M = SimpleNamespace(fmt_date=original_fmt)
    assert module._install_cached_date_format(M) is True
    assert M.fmt_date("2026-09-11") == "fmt:2026-09-11"
    assert M.fmt_date("2026-09-11") == "fmt:2026-09-11"
    assert calls == ["2026-09-11"]
    assert M.fmt_date.cache_info().hits >= 1

    # Sparse action attention must not touch ordinary rows or rewrite Deadline.
    app = FakeApp()
    app.action_tree.insert("", "end", iid="a1", values=("Rozpracováno", "01.09.2026", "20.09.2026"), tags=("status_active",))
    app.action_tree.insert("", "end", iid="a2", values=("Rozpracováno", "01.09.2026", "10.09.2026"), tags=("status_active",))
    app.action_tree.insert("", "end", iid="a3", values=("Nabídka", "01.09.2026", "12.09.2026"), tags=("status_offer",))

    class ActionOwner:
        soon = lambda self, row: False

    fake_M = SimpleNamespace(App=ActionOwner)
    assert module._install_fast_action_deadlines(fake_M) is True
    callback = ActionOwner._refresh_action_deadline_highlights
    ActionOwner.action_tree = app.action_tree
    callback(ActionOwner(), (("a1", False, False), ("a2", True, False), ("a3", False, True)))
    assert app.action_tree.rows["a1"]["tags"] == ("status_active",)
    assert app.action_tree.rows["a2"]["tags"] == ("status_active", module.ATTENTION_TAG)
    assert app.action_tree.rows["a3"]["tags"] == ("status_offer", module.ATTENTION_TAG)
    assert app.action_tree.rows["a2"]["values"][2] == "10.09.2026"

    # Manual-sort fallback still restores Přijato descending when it is needed.
    tree = FakeTree()
    tree.insert("", "end", iid="a1", values=("", "01.09.2026", ""))
    tree.insert("", "end", iid="a2", values=("", "11.09.2026", ""))
    tree.insert("", "end", iid="a3", values=("", "05.09.2026", ""))
    tree._active_sort = "Příležitost"
    module._sort_action_default(tree)
    assert tree.order == ["a2", "a3", "a1"]
    assert tree._active_sort is None and tree._sort_state == {}

    # Inline task attention preserves the existing status tag and adds exactly
    # the same v770 attention tag for Po termínu / Dnes / Brzy only.
    target = FakeTree()
    original_insert = target.insert
    module._task_attention_insert(
        original_insert, "", "end", "t1",
        values=("Po termínu", "Jaroslav", "10.09.2026"), tags=("status_late",),
    )
    module._task_attention_insert(
        original_insert, "", "end", "t2",
        values=("Brzy", "Jaroslav", "13.09.2026"), tags=("status_wait",),
    )
    module._task_attention_insert(
        original_insert, "", "end", "t3",
        values=("Čeká", "Jaroslav", "20.09.2026"), tags=("status_active",),
    )
    module._task_attention_insert(
        original_insert, "", "end", "t4",
        values=("Hotovo", "Jaroslav", "10.09.2026"), tags=("status_done",),
    )
    assert target.rows["t1"]["tags"] == ("status_late", module.ATTENTION_TAG)
    assert target.rows["t2"]["tags"] == ("status_wait", module.ATTENTION_TAG)
    assert target.rows["t3"]["tags"] == ("status_active",)
    assert target.rows["t4"]["tags"] == ("status_done",)

    marker = '"price_lists_domain.platform.operational_refresh_804"'
    autocomplete = '"price_lists_domain.platform.autocomplete_event_compat_803"'
    assert marker in bootstrap and autocomplete in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(autocomplete)

    print("TURTO CRM 8.0.4 operational refresh optimization: OK")


if __name__ == "__main__":
    main()
