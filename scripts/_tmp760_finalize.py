#!/usr/bin/env python3
"""Finalize the reconstructed TURTO CRM 7.6 source before validation."""
from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ZakazkyApp_base_6.1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Missing patch target: {label}")
    return text.replace(old, new, 1)


def patch_app_tree() -> None:
    path = SOURCE / "app.py"
    text = path.read_text(encoding="utf-8")
    old = (
        '        for c,w in zip(cols,widths):\n'
        '            t.heading(c,text=c,command=lambda col=c,tree=t:self.sort_tree(tree,col))\n'
        '            t.column(c,width=w,anchor="w")\n'
    )
    new = (
        '        for c,w in zip(cols,widths):\n'
        '            # The heading follows the alignment of its data cells immediately.\n'
        '            t.column(c,width=w,anchor="w")\n'
        '            t.heading(c,text=c,anchor=t.column(c,"anchor"),\n'
        '                      command=lambda col=c,tree=t:self.sort_tree(tree,col))\n'
    )
    path.write_text(
        replace_once(text, old, new, "canonical App.tree heading alignment"),
        encoding="utf-8",
    )


def patch_v760_treeview() -> None:
    path = SOURCE / "v760_table_activity_performance.py"
    text = path.read_text(encoding="utf-8")

    start = text.index("        def sync_heading_anchors(tree: Any) -> None:\n")
    end = text.index("        def tree_xview(self: Any, *args: Any):\n", start)
    wrapper = textwrap.indent(
        textwrap.dedent(
            '''\
def _fallback_column_token(tree: Any, column: Any) -> Any:
    """Resolve a dynamic symbolic column through its stable numeric position."""
    target = str(column)
    columns = _all_columns(tree)
    if target in columns:
        return f"#{columns.index(target) + 1}"
    return column


def _original_heading_call(
    tree: Any, column: Any, option: Any = None, **kwargs: Any
):
    try:
        return original_heading(tree, column, option, **kwargs)
    except Exception:
        fallback = _fallback_column_token(tree, column)
        if str(fallback) == str(column):
            raise
        return original_heading(tree, fallback, option, **kwargs)


def _original_column_call(
    tree: Any, column: Any, option: Any = None, **kwargs: Any
):
    try:
        return original_column(tree, column, option, **kwargs)
    except Exception:
        fallback = _fallback_column_token(tree, column)
        if str(fallback) == str(column):
            raise
        return original_column(tree, fallback, option, **kwargs)


def sync_heading_anchors(tree: Any) -> None:
    for column in _all_columns(tree):
        try:
            anchor = _normalize_anchor(
                _original_column_call(tree, column, "anchor")
            )
            _original_heading_call(tree, column, anchor=anchor)
        except Exception:
            pass


def install_tree_polish(tree: Any) -> None:
    if not _exists(tree):
        return
    first_install = not getattr(tree, "_v760_table_polish", False)
    if first_install:
        tree._v760_table_polish = True
        for sequence in (
            "<Configure>",
            "<Map>",
            "<B1-Motion>",
            "<ButtonRelease-1>",
        ):
            tree.bind(
                sequence,
                lambda _event, current=tree: schedule_separators(current),
                add="+",
            )
    sync_heading_anchors(tree)
    schedule_separators(tree, 0)
    if first_install:
        schedule_separators(tree, 90)


def tree_init(self: Any, *args: Any, **kwargs: Any):
    original_init(self, *args, **kwargs)
    try:
        self.after_idle(lambda current=self: install_tree_polish(current))
    except Exception:
        pass


def tree_heading(self: Any, column: Any, option: Any = None, **kwargs: Any):
    mutating = bool(kwargs)
    if mutating:
        try:
            kwargs["anchor"] = _normalize_anchor(
                _original_column_call(self, column, "anchor")
            )
        except Exception:
            pass
    result = _original_heading_call(self, column, option, **kwargs)
    if mutating:
        schedule_separators(self)
    return result


def tree_column(self: Any, column: Any, option: Any = None, **kwargs: Any):
    mutating = bool(kwargs)
    result = _original_column_call(self, column, option, **kwargs)
    if mutating:
        try:
            _original_heading_call(
                self,
                column,
                anchor=_normalize_anchor(
                    _original_column_call(self, column, "anchor")
                ),
            )
        except Exception:
            pass
        schedule_separators(self)
    return result


def tree_configure(self: Any, cnf: Any = None, **kwargs: Any):
    result = original_configure(self, cnf, **kwargs)
    if cnf is not None or kwargs:
        try:
            sync_heading_anchors(self)
            schedule_separators(self)
        except Exception:
            pass
    return result

'''
        ),
        "        ",
    )
    text = text[:start] + wrapper + text[end:]

    start = text.index("    def add_project_activity_column(app: Any) -> None:\n")
    end = text.index("\n    def refresh_projects(self: Any) -> None:\n", start)
    block = text[start:end]
    needle = "        install_tree_polish(tree)\n"
    replacement = (
        "        # Old 7.5 layouts do not know this additive column yet.\n"
        "        visible_now = _displayed_columns(tree)\n"
        "        if LAST_ACTIVITY_COLUMN not in visible_now:\n"
        "            tree.configure(\n"
        "                displaycolumns=tuple(visible_now + [LAST_ACTIVITY_COLUMN])\n"
        "            )\n"
        "        install_tree_polish(tree)\n"
    )
    if block.count(needle) != 1:
        raise SystemExit("Unexpected project activity column implementation")
    text = text[:start] + block.replace(needle, replacement, 1) + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_commercial_titles() -> None:
    path = SOURCE / "price_lists_domain" / "platform" / "commercial_workspace.py"
    text = path.read_text(encoding="utf-8")

    price_title = '    app.title_label(page, "Ceníky")\n'
    price_title_row = (
        '    price_import = getattr(app, "import_price_list", None)\n'
        '    title_row = M.ttk.Frame(page, style="App.TFrame")\n'
        '    title_row.pack(fill="x", pady=(0, 12))\n'
        '    M.ttk.Label(\n'
        '        title_row, text="Ceníky", style="Title.TLabel"\n'
        '    ).pack(side="left", anchor="n")\n'
        '    if callable(price_import):\n'
        '        M.ttk.Button(\n'
        '            title_row, text="+ Importovat Ceník", style="Accent.TButton",\n'
        '            command=lambda: _run_after_invalidation(\n'
        '                app, price_import, prices=True\n'
        '            ),\n'
        '        ).pack(side="right", anchor="n", pady=(2, 0))\n'
    )
    price_button = (
        '    M.ttk.Button(\n'
        '        command, text="+ Importovat Ceník", style="Accent.TButton",\n'
        '        command=lambda: _run_after_invalidation(app, app.import_price_list, prices=True),\n'
        '    ).pack(side="left")\n'
    )
    text = replace_once(text, price_title, price_title_row, "price-list title row")
    text = replace_once(text, price_button, "", "price-list legacy toolbar button")

    offer_title = (
        '    app._offer_drop_area_ready = True\n'
        '    app.title_label(page, "Přijaté nabídky")\n'
    )
    offer_title_row = (
        '    app._offer_drop_area_ready = True\n'
        '    offer_import = getattr(app, "import_offer_sources", None)\n'
        '    title_row = M.ttk.Frame(page, style="App.TFrame")\n'
        '    title_row.pack(fill="x", pady=(0, 12))\n'
        '    M.ttk.Label(\n'
        '        title_row, text="Přijaté nabídky", style="Title.TLabel"\n'
        '    ).pack(side="left", anchor="n")\n'
        '    if callable(offer_import):\n'
        '        M.ttk.Button(\n'
        '            title_row, text="📥 Zpracovat nabídku", style="Accent.TButton",\n'
        '            command=lambda: _run_after_invalidation(\n'
        '                app, offer_import, offers=True\n'
        '            ),\n'
        '        ).pack(side="right", anchor="n", pady=(2, 0))\n'
    )
    offer_button = (
        '    if callable(getattr(app, "import_offer_sources", None)):\n'
        '        M.ttk.Button(\n'
        '            command, text="📥 Zpracovat nabídku", style="Accent.TButton",\n'
        '            command=lambda: _run_after_invalidation(app, app.import_offer_sources, offers=True),\n'
        '        ).pack(side="left")\n'
    )
    text = replace_once(text, offer_title, offer_title_row, "received-offer title row")
    text = replace_once(text, offer_button, "", "received-offer legacy toolbar button")
    path.write_text(text, encoding="utf-8")


def patch_issued_offer_title() -> None:
    path = SOURCE / "price_lists_domain" / "issued_offers" / "page.py"
    text = path.read_text(encoding="utf-8")
    old_title = '    app.title_label(page, "Vydané nabídky")\n'
    new_title = (
        '    title_row = M.ttk.Frame(page, style="App.TFrame")\n'
        '    title_row.pack(fill="x", pady=(0, 12))\n'
        '    M.ttk.Label(\n'
        '        title_row, text="Vydané nabídky", style="Title.TLabel"\n'
        '    ).pack(side="left", anchor="n")\n'
        '    M.ttk.Button(\n'
        '        title_row, text="+ Nová nabídka", style="Accent.TButton",\n'
        '        command=lambda: app.open_issued_offer_editor(),\n'
        '    ).pack(side="right", anchor="n", pady=(2, 0))\n'
    )
    old_button = (
        '    M.ttk.Button(toolbar, text="+ Nová nabídka", style="Accent.TButton", '
        'command=lambda: app.open_issued_offer_editor()).pack(side="left")\n'
    )
    text = replace_once(text, old_title, new_title, "issued-offer title row")
    text = replace_once(text, old_button, "", "issued-offer legacy toolbar button")
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app_tree()
    patch_v760_treeview()
    patch_commercial_titles()
    patch_issued_offer_title()
    print("Finalized TURTO CRM 7.6 source")


if __name__ == "__main__":
    main()
