from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ZakazkyApp_base_6.1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# 1) Build the Akce table with Poslední pohyb from the beginning.  The 7.6.0
# package still constructed the seven-column 7.5 table and added the eighth
# column lazily.  A saved Windows/Tk layout could then reject the symbolic name.
app_path = SOURCE / "app.py"
app_text = app_path.read_text(encoding="utf-8")
start = app_text.index("    def build_projects(self):\n")
end = app_text.index("\n    def build_people(self):\n", start)
block = app_text[start:end]
block = replace_once(
    block,
    "        widths=(300,300,220,220,100,100,90)\n",
    "        widths=(300,300,220,220,100,100,90,150)\n",
    "Akce widths",
)
block = replace_once(
    block,
    '        self.project_tree=self.tree(p,("Název Akce","Adresa","Investor","Generální dodavatel","Zahájení","Dokončení","Příležitostí"),list(widths))\n',
    '        self.project_tree=self.tree(p,("Název Akce","Adresa","Investor","Generální dodavatel","Zahájení","Dokončení","Příležitostí","Poslední pohyb"),list(widths))\n',
    "Akce columns",
)
app_text = app_text[:start] + block + app_text[end:]
app_path.write_text(app_text, encoding="utf-8")


# 2) Make displaycolumns tolerant of the Windows/Tk symbolic-column failure.
# Symbolic names remain the preferred readable form; when Tk rejects one, the
# same order is applied through stable zero-based numeric column indices.
layer_path = SOURCE / "v760_table_activity_performance.py"
layer_text = layer_path.read_text(encoding="utf-8")
if "def _set_displayed_columns(" not in layer_text:
    anchor = "\n\ndef _table_exists(con: Any, table: str) -> bool:\n"
    helper = '''\n\ndef _set_displayed_columns(tree: Any, ordered: Iterable[Any]) -> bool:
    """Apply visible columns with a numeric fallback for Windows/Tk.

    Some upgraded 7.5 layouts can report the new symbolic column but reject the
    same name when it is written back to ``displaycolumns``.  Numeric indices are
    part of the native Treeview contract and preserve the exact requested order.
    A failed cosmetic layout update must never make the whole Akce page unusable.
    """
    columns = _all_columns(tree)
    desired: list[str] = []
    for raw in ordered:
        column = str(raw)
        if column in columns and column not in desired:
            desired.append(column)
    if not desired:
        return False
    try:
        tree.configure(displaycolumns=tuple(desired))
        return True
    except Exception:
        try:
            numeric = tuple(columns.index(column) for column in desired)
            tree.configure(displaycolumns=numeric)
            return True
        except Exception:
            return False
'''
    if anchor not in layer_text:
        raise SystemExit("v760 helper insertion point not found")
    layer_text = layer_text.replace(anchor, helper + anchor, 1)

function_start = layer_text.index("    def add_project_activity_column(app: Any) -> None:\n")
function_end = layer_text.index("\n    def refresh_projects(self: Any) -> None:\n", function_start)
new_function = '''    def add_project_activity_column(app: Any) -> None:
        tree = getattr(app, "project_tree", None)
        if not _exists(tree):
            return
        columns = _all_columns(tree)
        if LAST_ACTIVITY_COLUMN not in columns:
            visible_before = _displayed_columns(tree)
            columns.append(LAST_ACTIVITY_COLUMN)
            try:
                tree.configure(columns=tuple(columns))
            except Exception:
                return
            # Re-read Tk's authoritative structure before addressing the column.
            columns = _all_columns(tree)
            if LAST_ACTIVITY_COLUMN not in columns:
                return
            try:
                tree.heading(
                    LAST_ACTIVITY_COLUMN,
                    text=LAST_ACTIVITY_COLUMN,
                    command=lambda current=tree: app.sort_tree(
                        current, LAST_ACTIVITY_COLUMN
                    ),
                )
            except Exception:
                pass
            try:
                tree.column(
                    LAST_ACTIVITY_COLUMN,
                    width=150,
                    minwidth=105,
                    stretch=False,
                    anchor="w",
                )
            except Exception:
                pass
            try:
                defaults = dict(getattr(tree, "_v700_default_widths", {}) or {})
                defaults[LAST_ACTIVITY_COLUMN] = 150
                tree._v700_default_widths = defaults
                design = dict(getattr(tree, "_turto_design_widths", {}) or {})
                design[LAST_ACTIVITY_COLUMN] = 150
                tree._turto_design_widths = design
            except Exception:
                pass
            if LAST_ACTIVITY_COLUMN not in visible_before:
                _set_displayed_columns(
                    tree, visible_before + [LAST_ACTIVITY_COLUMN]
                )
            saver = getattr(M, "save_persistent_tree_layout", None)
            if callable(saver):
                try:
                    saver(tree)
                except Exception:
                    pass
        # Existing 7.5 layouts may explicitly list only the original columns.
        # Never send an unguarded symbolic identifier back to Tk here.
        visible_now = _displayed_columns(tree)
        if LAST_ACTIVITY_COLUMN not in visible_now:
            _set_displayed_columns(tree, visible_now + [LAST_ACTIVITY_COLUMN])
        install_tree_polish(tree)
'''
layer_text = layer_text[:function_start] + new_function + layer_text[function_end:]
layer_path.write_text(layer_text, encoding="utf-8")


# 3) Extend the static/unit validator with the exact numeric-fallback contract
# and verify that the canonical app now owns all eight Akce columns.
validator_path = ROOT / "scripts" / "validate-7600-table-activity-performance.py"
validator = validator_path.read_text(encoding="utf-8")
parse_anchor = '    assert layer._parse_activity_datetime("—") is None\n\n'
fallback_test = '''    assert layer._parse_activity_datetime("—") is None

    class SymbolicDisplayFallbackTree:
        def __init__(self):
            self.columns = ("Název Akce", layer.LAST_ACTIVITY_COLUMN)
            self.displaycolumns = ("Název Akce",)
            self.tk = SimpleNamespace(splitlist=lambda value: tuple(value))
            self.symbolic_attempts = 0

        def cget(self, option):
            return self.columns if option == "columns" else self.displaycolumns

        def configure(self, *args, **kwargs):
            display = kwargs.get("displaycolumns")
            if display is None:
                return None
            values = tuple(display)
            if any(str(value) == layer.LAST_ACTIVITY_COLUMN for value in values):
                self.symbolic_attempts += 1
                raise RuntimeError('Invalid column index "Poslední pohyb"')
            self.displaycolumns = values
            return None

    fallback_tree = SymbolicDisplayFallbackTree()
    assert layer._set_displayed_columns(
        fallback_tree, ["Název Akce", layer.LAST_ACTIVITY_COLUMN]
    )
    assert fallback_tree.symbolic_attempts == 1
    assert fallback_tree.displaycolumns == (0, 1), fallback_tree.displaycolumns

'''
validator = replace_once(
    validator, parse_anchor, fallback_test, "numeric display-column regression test"
)
validator = replace_once(
    validator,
    '        "sync_heading_anchors",\n',
    '        "sync_heading_anchors",\n        "_set_displayed_columns",\n',
    "v760 token list",
)
launcher_anchor = '    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")\n'
app_contract = '''    app_text = (source / "app.py").read_text(encoding="utf-8")
    project_start = app_text.index("    def build_projects(self):\\n")
    project_end = app_text.index("\\n    def build_people(self):\\n", project_start)
    project_block = app_text[project_start:project_end]
    assert "widths=(300,300,220,220,100,100,90,150)" in project_block
    assert '"Příležitostí","Poslední pohyb"' in project_block

    launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
'''
validator = replace_once(
    validator, launcher_anchor, app_contract, "canonical Akce table validation"
)
validator = replace_once(
    validator,
    '    assert version == "7.6.0", version\n',
    '    assert version == "7.6.1", version\n',
    "release version assertion",
)
validator = replace_once(
    validator,
    '        "OK 7.6.0: headings follow cells, commercial actions share title rows, "\n        "projects/tasks archive consistently and activity/performance queries are lean"\n',
    '        "OK 7.6.1: Akce opens with a canonical last-activity column, "\n        "legacy layouts use a numeric fallback and all 7.6 contracts remain valid"\n',
    "validator success message",
)
validator_path.write_text(validator, encoding="utf-8")


# 4) Reproduce the user's Windows error in the complete Tk application.  The
# test hides the additive column like a saved 7.5 layout and deliberately makes
# symbolic displaycolumns fail once.  The refresh must transparently retry with
# numeric indices and leave the page usable.
real_ui_path = ROOT / "scripts" / "validate-real-ui.py"
real_ui = real_ui_path.read_text(encoding="utf-8")
project_assert = '        assert "Poslední pohyb" in root.project_tree["columns"]\n'
real_ui_regression = '''        assert "Poslední pohyb" in root.project_tree["columns"]

        project_tree = root.project_tree
        project_columns = tuple(str(column) for column in project_tree.cget("columns"))
        legacy_project_columns = tuple(
            column for column in project_columns if column != "Poslední pohyb"
        )
        original_project_configure = project_tree.configure
        original_project_configure(displaycolumns=legacy_project_columns)
        symbolic_failures = {"count": 0}

        def windows_like_project_configure(cnf=None, **kwargs):
            options = {}
            if isinstance(cnf, dict):
                options.update(cnf)
            options.update(kwargs)
            display = options.get("displaycolumns")
            if display is not None:
                if isinstance(display, str):
                    values = project_tree.tk.splitlist(display)
                else:
                    values = tuple(display)
                if any(str(value) == "Poslední pohyb" for value in values):
                    symbolic_failures["count"] += 1
                    raise app.tk.TclError('Invalid column index "Poslední pohyb"')
            return original_project_configure(cnf, **kwargs)

        project_tree.configure = windows_like_project_configure
        project_tree.config = windows_like_project_configure
        try:
            root.refresh_projects()
        finally:
            del project_tree.configure
            del project_tree.config
        assert symbolic_failures["count"] == 1, symbolic_failures
        raw_display = project_tree.cget("displaycolumns")
        if isinstance(raw_display, str):
            raw_display = project_tree.tk.splitlist(raw_display)
        display_tokens = [str(value) for value in raw_display]
        if not display_tokens or display_tokens == ["#all"]:
            visible_project_columns = list(project_columns)
        else:
            visible_project_columns = []
            for value in display_tokens:
                if value.lstrip("-").isdigit():
                    index = int(value)
                    if 0 <= index < len(project_columns):
                        visible_project_columns.append(project_columns[index])
                elif value in project_columns:
                    visible_project_columns.append(value)
        assert "Poslední pohyb" in visible_project_columns, visible_project_columns
'''
real_ui = replace_once(
    real_ui, project_assert, real_ui_regression, "real Tk Akce regression"
)
real_ui_path.write_text(real_ui, encoding="utf-8")


# 5) Publish as a patch release.  No database or business document migration is
# needed; this only changes table construction and layout compatibility.
(ROOT / "release_version.txt").write_text("7.6.1\n", encoding="utf-8")
(ROOT / "release_notes.txt").write_text(
    "• Opravena chyba, při které po aktualizaci z verze 7.5.0 mohla záložka Akce skončit hlášením „Invalid column index Poslední pohyb“.\n"
    "• Sloupec Poslední pohyb je nyní součástí tabulky Akce už při jejím vytvoření, nikoli až při prvním otevření záložky.\n"
    "• U starších uložených rozložení tabulek se při nekompatibilitě symbolického názvu automaticky použije bezpečný číselný index sloupce.\n"
    "• Oprava nemění databázi, ceny, nabídky, vazby ani historické PDF revize.\n",
    encoding="utf-8",
)

print("Prepared TURTO CRM 7.6.1 Akce-tab hotfix")
