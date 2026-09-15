#!/usr/bin/env python3
"""Compare real Tk cell boundaries and overlays without a manual column drag."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def settle(window, seconds=.35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        window.update()
        time.sleep(.01)


def assert_aligned(tree, context):
    from v760_table_activity_performance import _displayed_columns
    assert tree.winfo_ismapped(), context
    rows = tree.get_children('')
    assert rows, (context, 'missing fixture row')
    row = rows[0]
    expected = []
    for column in _displayed_columns(tree)[:-1]:
        box = tree.bbox(row, column)
        if box:
            right = box[0] + box[2]
            if 1 < right < tree.winfo_width() - 1:
                expected.append(right - 1)
    actual = sorted(int(float(line.place_info()['x']))
                    for line in getattr(tree, '_v760_separator_widgets', ())
                    if line.place_info())
    assert len(actual) == len(expected) and all(
        abs(a - e) <= 1 for a, e in zip(actual, expected)
    ), (context, 'misaligned separators', {'actual': actual, 'cell_edges': expected})


def seed(tree):
    if not tree.get_children(''):
        columns = tree.cget('columns')
        tree.insert('', 'end', iid='814-fixture', values=tuple(
            '15.09.2026' if any(word in str(c).lower() for word in ('datum', 'termín', 'deadline'))
            else f'{c} – ukázka' for c in columns))


def run_ui(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    window = app.App()
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(str(exc))
    try:
        window.state('normal')
        window.geometry('1020x720+0+0')
        settle(window, 1.5)
        pages = (
            ('dash', ('dash_tree', 'dash_tasks_tree', 'dash_requests_tree')),
            ('actions', ('action_tree',)), ('requests', ('request_tree',)),
            ('mivo', ('mivo_tree',)), ('projects', ('project_tree',)),
            ('offers', ('offer_tree',)), ('tasks', ('task_tree',)),
            ('companies', ('company_tree',)), ('people', ('people_tree',)),
        )
        for page, names in pages:
            window.show_page(page)
            settle(window, .6)
            for name in names:
                tree = getattr(window, name)
                seed(tree)
                settle(window)
                assert_aligned(tree, f'first-open/{name}')

        window.show_page('dash')
        settle(window)
        tree = window.dash_tree
        seed(tree)
        columns = tuple(tree.cget('columns'))
        # The width owner restores saved preferences after Map/Configure. The
        # outer widget size does not change, so no user resize event is sent.
        design = dict(tree._turto_design_widths)
        tree._turto_design_widths.update({columns[0]: 113, columns[1]: 157})
        app.install_persistent_tree_layout(tree)
        settle(window)
        assert tree.column(columns[0], 'width') == 113
        assert tree.column(columns[1], 'width') == 157
        assert_aligned(tree, 'late-saved-widths')

        # Equal-total-width changes must also redraw (scroll fractions can be
        # unchanged), including reordering and hiding a column via the dialog.
        first, second = (tree.column(c, 'width') for c in columns[:2])
        tree._turto_design_widths.update({columns[0]: first + 23, columns[1]: second - 23})
        app.install_persistent_tree_layout(tree)
        settle(window)
        assert tree.column(columns[0], 'width') == first + 23
        assert tree.column(columns[1], 'width') == second - 23
        assert_aligned(tree, 'same-total-width')
        # Late column contracts bypass the width owner, then invoke the
        # application's bounded final-layout callback.
        tree.column(columns[0], width=first)
        tree.column(columns[1], width=second)
        app.schedule_final_tree_layout(window)
        settle(window)
        assert_aligned(tree, 'late-column-contract')
        order = tuple(reversed(columns[:-1]))
        tree.configure(displaycolumns=order)
        app.install_persistent_tree_layout(tree)
        settle(window)
        assert_aligned(tree, 'hidden-reordered')
        tree.xview_moveto(.35)
        settle(window)
        assert tree.xview()[0] > 0
        assert_aligned(tree, 'horizontal-scroll')

        for theme in ('Tmavý', 'Světlý'):
            window.apply_theme(theme)
            settle(window)
            seed(tree)
            assert tuple(tree.cget('displaycolumns')) == order
            assert_aligned(tree, f'theme/{theme}')
        tree.configure(displaycolumns='#all')
        tree._turto_design_widths = design
        app.install_persistent_tree_layout(tree)
        tree.xview_moveto(0)
        settle(window)
        for name in pages[0][1]:
            seed(getattr(window, name))
        settle(window)
        from PIL import ImageGrab
        destination = REPO / 'dist/branding-preview'
        destination.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=(window.winfo_rootx(), window.winfo_rooty(),
            window.winfo_rootx()+window.winfo_width(), window.winfo_rooty()+window.winfo_height())).save(
                destination / 'table-layout-814.png')

        # An empty table gets its lines before data is loaded; repeated installs
        # must not accumulate callbacks, and teardown cancels pending redraws.
        dialog = app.tk.Toplevel(window)
        empty = app.ttk.Treeview(dialog, columns=('A', 'B', 'C'), show='headings')
        empty.pack(fill='both', expand=True)
        scrollbar = app.ttk.Scrollbar(dialog, orient='horizontal', command=empty.xview)
        scrollbar.pack(fill='x')
        # Pass a native Tcl command prefix, as existing table builders do.
        empty.configure(xscrollcommand=(str(scrollbar), 'set'))
        for c in ('A', 'B', 'C'):
            empty.column(c, width=90, stretch=False)
        app.install_v760_tree_polish(empty)
        settle(window)
        hook = str(empty.cget('xscrollcommand'))
        for _ in range(3):
            app.install_v760_tree_polish(empty)
        assert str(empty.cget('xscrollcommand')) == hook
        empty.column('A', width=125)
        settle(window)
        assert tuple(map(float, scrollbar.get())) == tuple(map(float, empty.xview()))
        assert getattr(empty, '_v760_separator_after', None) is None
        before = [dict(line.place_info()) for line in empty._v760_separator_widgets]
        empty.insert('', 'end', values=('A', 'B', 'C'))
        window.update_idletasks()
        assert before == [dict(line.place_info()) for line in empty._v760_separator_widgets]
        assert_aligned(empty, 'empty-before-first-row')
        app.schedule_v760_tree_separators(empty)
        dialog.destroy()
        settle(window)
        assert not errors, errors
    finally:
        window._turto_closing = True
        window.destroy()
    print('8.0.14: first-open tables, saved widths, order, scrolling, themes and teardown OK')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--data-root':
        run_ui(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-table-ui-') as td:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--data-root', td],
                           check=True, timeout=120)
