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

    # Canonical DB dates take the allocation-only fast path; anything outside
    # YYYY-MM-DD keeps the historical formatter and is still cached.
    calls = []

    def original_fmt(value):
        calls.append(value)
        return f"fmt:{value}"

    assert module._fast_iso_display("2026-09-11") == "11.09.2026"
    assert module._fast_iso_display("2026-9-11") is None
    assert module._fast_iso_display("11.09.2026") is None
    assert module._fast_iso_display(None) is None

    M = SimpleNamespace(fmt_date=original_fmt)
    assert module._install_cached_date_format(M) is True
    assert M.fmt_date("2026-09-11") == "11.09.2026"
    assert M.fmt_date("2026-09-11") == "11.09.2026"
    assert calls == []
    assert M.fmt_date("legacy-date") == "fmt:legacy-date"
    assert M.fmt_date("legacy-date") == "fmt:legacy-date"
    assert calls == ["legacy-date"]
    assert M.fmt_date.cache_info().hits >= 2

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

    # worksets already returns Poptávky and MIVO as asked_date DESC. Retire only
    # those two redundant v644 post-refresh sorts; Příležitosti/Akce remain under
    # their dedicated policies.
    fake_v644 = SimpleNamespace(PAGE_SORTS={
        "actions": ("date", "action_tree", ("Přijato",)),
        "requests": ("date", "request_tree", ("Poptáno",)),
        "mivo": ("date", "mivo_tree", ("Poptáno",)),
        "projects": ("alpha", "project_tree", ("Akce",)),
    })
    previous_v644 = sys.modules.get("v644_default_date_sort")
    sys.modules["v644_default_date_sort"] = fake_v644
    try:
        assert module._install_request_mivo_native_default_order() is True
    finally:
        if previous_v644 is None:
            sys.modules.pop("v644_default_date_sort", None)
        else:
            sys.modules["v644_default_date_sort"] = previous_v644
    assert set(fake_v644.PAGE_SORTS) == {"actions", "projects"}

    # Task attention now reuses the existing v760 status tags. The three states
    # that v770 rendered bold get the same font once on the task Treeview; normal,
    # done and archived rows remain unchanged and no per-row insert proxy exists.
    target = FakeTree()
    target.insert("", "end", iid="t1", values=("Po termínu",), tags=("status_late",))
    target.insert("", "end", iid="t2", values=("Brzy",), tags=("status_wait",))
    target.insert("", "end", iid="t3", values=("Čeká",), tags=("status_active",))
    target.insert("", "end", iid="t4", values=("Hotovo",), tags=("status_done",))
    before_rows = {iid: dict(row) for iid, row in target.rows.items()}
    assert module._configure_task_attention_tags(target) is True
    assert target._turto_804_task_attention_status_tags is True
    for tag in module.ATTENTION_TASK_TAGS:
        assert target.configured_tags[tag]["font"] == ("Calibri", 10, "bold")
    assert set(target.configured_tags) == set(module.ATTENTION_TASK_TAGS)
    assert target.rows == before_rows
    source = path.read_text(encoding="utf-8")
    assert "tree.insert = insert" not in source
    assert "_task_attention_insert" not in source
    assert '"fmt_date": "lru-4096-iso-fast-path"' in source
    assert '"request_mivo_default_order": "trust-sql-lazy-manual-reset"' in source
    assert '"task_attention": "status-tag-fonts-no-insert-proxy"' in source

    marker = '"price_lists_domain.platform.operational_refresh_804"'
    autocomplete = '"price_lists_domain.platform.autocomplete_event_compat_803"'
    assert marker in bootstrap and autocomplete in bootstrap
    assert bootstrap.index(marker) > bootstrap.index(autocomplete)

    print("TURTO CRM 8.0.4 operational refresh optimization: OK")


if __name__ == "__main__":
    main()
