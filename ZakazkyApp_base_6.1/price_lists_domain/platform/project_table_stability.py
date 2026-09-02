"""Final Akce table stability owner for TURTO CRM 7.6.3.

The 7.6.2 startup fix correctly stopped process-wide Treeview monkey-patching.
On Windows/Python 3.14, however, the upgraded project table can expose the
symbolic name ``Poslední pohyb`` through ``cget('columns')`` while Tk accepts
only the positional ``#N`` token for direct column/heading calls.  The older
column editor used the symbolic id unconditionally and raised TclError.  Its
heading-normalization side effect was also the reason blank Akce headings only
appeared after opening that dialog.

This module is deliberately local: it patches no Tk class and walks no widget
tree.  It is installed before v760.apply() and wraps that one module so the
final owner is attached only after all 7.6 table composition is complete.
"""
from __future__ import annotations

import sys
from typing import Any


def _exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _columns(tree: Any) -> list[str]:
    try:
        raw = tree.cget("columns")
        if isinstance(raw, str):
            raw = tree.tk.splitlist(raw)
        return [str(value) for value in raw]
    except Exception:
        return []


def _token(tree: Any, column: str, columns: list[str] | None = None) -> str:
    """Return a Tk-safe identifier for a data column."""
    columns = columns or _columns(tree)
    try:
        tree.column(column, "width")
        return column
    except Exception:
        pass
    try:
        token = f"#{columns.index(column) + 1}"
        tree.column(token, "width")
        return token
    except Exception:
        return column


def _displayed(tree: Any, columns: list[str] | None = None) -> list[str]:
    columns = columns or _columns(tree)
    if not columns:
        return []
    try:
        raw = tree.cget("displaycolumns")
        if isinstance(raw, str):
            raw = tree.tk.splitlist(raw)
        values = [str(value) for value in raw]
    except Exception:
        values = ["#all"]
    if not values or values == ["#all"]:
        return list(columns)

    result: list[str] = []
    for value in values:
        if value == "#all":
            return list(columns)
        if value in columns:
            column = value
        elif value.startswith("#") and value[1:].isdigit():
            index = int(value[1:]) - 1
            if not 0 <= index < len(columns):
                continue
            column = columns[index]
        elif value.lstrip("-").isdigit():
            index = int(value)
            if not 0 <= index < len(columns):
                continue
            column = columns[index]
        else:
            continue
        if column not in result:
            result.append(column)
    return result or list(columns)


def _set_displayed(tree: Any, selected: list[str], columns: list[str] | None = None) -> bool:
    columns = columns or _columns(tree)
    selected = [column for column in selected if column in columns]
    if not selected:
        return False
    if selected == columns:
        try:
            tree.configure(displaycolumns="#all")
            return True
        except Exception:
            pass
    try:
        tree.configure(displaycolumns=tuple(selected))
        return True
    except Exception:
        pass
    try:
        # ttk displaycolumns also accepts zero-based data-column indices.
        tree.configure(displaycolumns=tuple(columns.index(column) for column in selected))
        return True
    except Exception:
        return False


def _heading_label(tree: Any, column: str, columns: list[str] | None = None) -> str:
    columns = columns or _columns(tree)
    labels = dict(getattr(tree, "_turto_heading_labels", {}) or {})
    token = _token(tree, column, columns)
    try:
        current = str(tree.heading(token, "text") or "").rstrip(" ▲▼").strip()
    except Exception:
        current = ""
    return current or str(labels.get(column) or column)


def _restore_project_headings(app: Any) -> None:
    tree = getattr(app, "project_tree", None)
    if not _exists(tree):
        return
    columns = _columns(tree)
    if not columns:
        return

    # Akce is a pure data table. Its heading row must always be visible.
    try:
        tree.configure(show="headings")
    except Exception:
        pass

    labels = dict(getattr(tree, "_turto_heading_labels", {}) or {})
    for column in columns:
        token = _token(tree, column, columns)
        try:
            current = str(tree.heading(token, "text") or "").rstrip(" ▲▼").strip()
        except Exception:
            current = ""
        if current:
            labels[column] = current
            continue
        label = str(labels.get(column) or column).rstrip(" ▲▼").strip() or column
        try:
            tree.heading(token, text=label)
            labels[column] = label
        except Exception:
            pass
    tree._turto_heading_labels = labels


def _save_layout(M: Any, tree: Any) -> None:
    saver = getattr(M, "save_persistent_tree_layout", None)
    if callable(saver):
        try:
            saver(tree)
        except Exception:
            pass


def _schedule_fit(M: Any, tree: Any) -> None:
    # Prefer the existing public fit owner when one is available.  Otherwise
    # ask the already-bound Configure handler to re-fit without touching other
    # tables or windows.
    fitter = getattr(M, "schedule_persistent_tree_fit", None)
    if callable(fitter):
        try:
            fitter(tree, 20)
            return
        except Exception:
            pass
    try:
        tree.event_generate("<Configure>", when="tail")
    except Exception:
        pass


def _open_columns_dialog(M: Any, tree: Any) -> None:
    if not _exists(tree):
        return
    columns = _columns(tree)
    if not columns:
        return
    visible = _displayed(tree, columns)
    ordered = visible + [column for column in columns if column not in visible]
    rows = [{"column": column, "visible": column in visible} for column in ordered]

    host = tree.winfo_toplevel()
    dialog = M.tk.Toplevel(host)
    dialog.title("Nastavení sloupců")
    dialog.transient(host)
    dialog.grab_set()
    try:
        M.enable_dialog_maximize(dialog, 720, 590)
    except Exception:
        try:
            dialog.geometry("720x590")
        except Exception:
            pass

    frame = M.ttk.Frame(dialog, padding=14)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(2, weight=1)
    M.ttk.Label(
        frame,
        text="Zobrazení a pořadí sloupců",
        font=("Calibri", 16, "bold"),
    ).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        frame,
        text="Dvojklikem sloupec zobrazíte nebo skryjete. Šířku lze zadat číselně níže.",
    ).grid(row=1, column=0, sticky="w", pady=(2, 8))

    listing = M.ttk.Treeview(
        frame,
        columns=("Zobrazeno", "Sloupec", "Šířka"),
        show="headings",
        selectmode="browse",
    )
    for column, width in (("Zobrazeno", 95), ("Sloupec", 390), ("Šířka", 90)):
        listing.heading(column, text=column)
        listing.column(column, width=width, anchor="w")
    listing.grid(row=2, column=0, sticky="nsew")
    scroll = M.ttk.Scrollbar(frame, orient="vertical", command=listing.yview)
    scroll.grid(row=2, column=1, sticky="ns")
    listing.configure(yscrollcommand=scroll.set)

    width_bar = M.ttk.Frame(frame)
    width_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    M.ttk.Label(width_bar, text="Šířka vybraného sloupce [px]").pack(side="left")
    width_value = M.tk.StringVar(value="")
    width_entry = M.ttk.Entry(width_bar, textvariable=width_value, width=10)
    width_entry.pack(side="left", padx=6)

    def width_of(column: str) -> int:
        design = dict(getattr(tree, "_turto_design_widths", {}) or {})
        if column in design:
            try:
                return max(30, int(design[column]))
            except Exception:
                pass
        try:
            return max(30, int(tree.column(_token(tree, column, columns), "width")))
        except Exception:
            return 100

    def render(select_index: int | None = None) -> None:
        for iid in listing.get_children(""):
            listing.delete(iid)
        for index, row in enumerate(rows):
            column = row["column"]
            listing.insert(
                "",
                "end",
                iid=f"c{index}",
                values=(
                    "✓" if row["visible"] else "—",
                    _heading_label(tree, column, columns),
                    width_of(column),
                ),
            )
        if select_index is not None and 0 <= select_index < len(rows):
            iid = f"c{select_index}"
            listing.selection_set(iid)
            listing.focus(iid)
            listing.see(iid)

    def selected_index() -> int | None:
        selection = listing.selection()
        if not selection:
            return None
        try:
            return int(str(selection[0])[1:])
        except Exception:
            return None

    def sync_width(*_args: Any) -> None:
        index = selected_index()
        if index is None or not 0 <= index < len(rows):
            width_value.set("")
            return
        width_value.set(str(width_of(rows[index]["column"])))

    def apply_width(show_warning: bool = True) -> bool:
        index = selected_index()
        if index is None or not 0 <= index < len(rows):
            return True
        try:
            value = int(round(float(width_value.get().strip().replace(",", "."))))
        except Exception:
            if show_warning:
                M.messagebox.showwarning(
                    "Nastavení sloupců",
                    "Šířku zadejte jako celé číslo v pixelech.",
                    parent=dialog,
                )
            return False
        if not 30 <= value <= 2000:
            if show_warning:
                M.messagebox.showwarning(
                    "Nastavení sloupců",
                    "Povolená šířka sloupce je 30 až 2 000 px.",
                    parent=dialog,
                )
            return False

        column = rows[index]["column"]
        design = dict(getattr(tree, "_turto_design_widths", {}) or {})
        design[column] = value
        tree._turto_design_widths = design
        try:
            tree.column(_token(tree, column, columns), width=value, minwidth=30)
        except Exception:
            pass
        _save_layout(M, tree)
        render(index)
        _schedule_fit(M, tree)
        return True

    def toggle(*_args: Any) -> None:
        index = selected_index()
        if index is None:
            return
        rows[index]["visible"] = not rows[index]["visible"]
        render(index)

    def move(delta: int) -> None:
        index = selected_index()
        if index is None:
            return
        target = index + int(delta)
        if not 0 <= target < len(rows):
            return
        rows[index], rows[target] = rows[target], rows[index]
        render(target)

    def reset() -> None:
        defaults = dict(getattr(tree, "_v700_default_widths", {}) or {})
        design = dict(getattr(tree, "_turto_design_widths", {}) or {})
        for column in columns:
            if column not in defaults:
                continue
            try:
                value = max(30, int(defaults[column]))
                design[column] = value
                tree.column(_token(tree, column, columns), width=value, minwidth=30)
            except Exception:
                pass
        tree._turto_design_widths = design
        rows[:] = [{"column": column, "visible": True} for column in columns]
        render(0)

    def apply_changes(close: bool = False) -> None:
        if not apply_width(show_warning=True):
            return
        selected = [row["column"] for row in rows if row["visible"]]
        if not selected:
            M.messagebox.showwarning(
                "Nastavení sloupců",
                "Alespoň jeden sloupec musí zůstat zobrazený.",
                parent=dialog,
            )
            return
        if not _set_displayed(tree, selected, columns):
            M.messagebox.showwarning(
                "Nastavení sloupců",
                "Zvolené pořadí sloupců se nepodařilo použít. Tabulka zůstala beze změny.",
                parent=dialog,
            )
            return
        _save_layout(M, tree)
        _schedule_fit(M, tree)
        if close:
            dialog.destroy()

    listing.bind("<Double-1>", toggle)
    listing.bind("<<TreeviewSelect>>", sync_width, add="+")
    width_entry.bind("<Return>", lambda _event: apply_width(True))
    M.ttk.Button(
        width_bar,
        text="Použít šířku",
        command=lambda: apply_width(True),
    ).pack(side="left")

    tools = M.ttk.Frame(frame)
    tools.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(9, 0))
    M.ttk.Button(tools, text="Zobrazit / skrýt", command=toggle).pack(side="left")
    M.ttk.Button(tools, text="↑ Nahoru", command=lambda: move(-1)).pack(side="left", padx=4)
    M.ttk.Button(tools, text="↓ Dolů", command=lambda: move(1)).pack(side="left")
    M.ttk.Button(tools, text="Výchozí", command=reset).pack(side="left", padx=(12, 0))
    M.ttk.Button(tools, text="Zavřít", command=dialog.destroy).pack(side="right")
    M.ttk.Button(
        tools,
        text="Použít",
        style="Accent.TButton",
        command=lambda: apply_changes(True),
    ).pack(side="right", padx=5)

    render(0)
    sync_width()


def _install_final_owner(M: Any) -> None:
    if getattr(M, "_turto_v763_project_table_stability", False):
        return

    # The v760 project context menu resolves this public API at click time.
    # Replacing it here also removes the v750 wrapper chain from this operation.
    M.open_tree_columns_dialog = lambda tree: _open_columns_dialog(M, tree)

    previous_build = getattr(M.App, "build_projects", None)
    if callable(previous_build):
        def build_projects(self: Any, *args: Any, **kwargs: Any):
            result = previous_build(self, *args, **kwargs)
            _restore_project_headings(self)
            return result
        M.App.build_projects = build_projects

    previous_refresh = getattr(M.App, "refresh_projects", None)
    if callable(previous_refresh):
        def refresh_projects(self: Any, *args: Any, **kwargs: Any):
            result = previous_refresh(self, *args, **kwargs)
            _restore_project_headings(self)
            return result
        M.App.refresh_projects = refresh_projects

    M.restore_project_headings_v763 = _restore_project_headings
    M._turto_v763_project_table_stability = True


def install(module: Any) -> None:
    if getattr(module, "_turto_project_table_stability_hook_v763", False):
        return

    v760 = sys.modules.get("v760_table_activity_performance")
    original_apply = getattr(v760, "apply", None) if v760 is not None else None
    if not callable(original_apply):
        return
    if getattr(original_apply, "_turto_v763_wrapped", False):
        module._turto_project_table_stability_hook_v763 = True
        return

    def wrapped_apply(target: Any) -> Any:
        result = original_apply(target)
        _install_final_owner(target)
        return result

    wrapped_apply._turto_v763_wrapped = True
    v760.apply = wrapped_apply
    module._turto_project_table_stability_hook_v763 = True


__all__ = ["install"]
