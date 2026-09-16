#!/usr/bin/env python3
"""Search glyph ranges and native Windows column drags without delayed settling."""
import os
from pathlib import Path
import sys
import tempfile
import time
import runpy

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import universal_search as search


def source_checks():
    assert search.match_ranges('Žluťoučká Praha', ['zlutoucka', 'PRA']) == [(0, 9), (10, 13)]
    assert search.match_ranges('Ladislav / LAD', ['lad', 'islav']) == [(0, 8), (11, 14)]
    assert search.match_ranges('Straße', ['STRASSE']) == [(0, 6)]
    assert search.match_ranges('C\u030cesko', ['c']) == [(0, 2)]
    assert search.match_ranges('a  \t b', ['a b']) == [(0, 6)]
    assert search.match_ranges('100%_!', ['%_!']) == [(3, 6)]
    assert search.match_ranges('bananana', ['ana', 'nan']) == [(1, 8)]
    assert search.match_ranges('16.09.2026', ['09.2026']) == [(3, 10)]
    assert search.match_ranges('Žluťoučká', ['', '  ', 'nic']) == []
    print('8.0.22: accent/case/combining/expanding glyphs, whitespace, overlaps and literal highlights OK', flush=True)


def settle(root, seconds=.25):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from PIL import ImageGrab
    from price_lists_domain.platform.calm_theme_820 import SEARCH, walk
    assert_aligned = runpy.run_path(str(REPO/'scripts/validate-814-table-layout-ui.py'))['assert_aligned']
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    root = app.App()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    try:
        root.state('normal')
        root.geometry('1240x840+0+0')
        settle(root, 4)
        # Every production SearchBar owns exactly its result tree, including
        # paginated commercial tables; taxonomy trees must not inherit terms.
        for page in ('actions', 'requests', 'mivo', 'projects', 'people', 'companies',
                     'tasks', 'offers', 'issued_offers', 'pricelists'):
            root.show_page(page)
            settle(root, .1)
        for bar in root._table_searches.values():
            assert bar.trees and all(t._table_search is bar for t in bar.trees), bar

        win = app.tk.Toplevel(root)
        bar = search.SearchBar(win, lambda: None)
        bar.pack(fill='x')
        t = app.ttk.Treeview(win, columns=('Stav', 'Název', 'Společnost', 'Částka'), show='headings')
        t.pack(fill='both', expand=True)
        search.attach_tree(t, bar)
        for col, width in zip(t.cget('columns'), (140, 260, 260, 180)):
            t.heading(col, text=col)
            t.column(col, width=width, stretch=False, anchor='e' if col=='Částka' else 'w')
        for i in range(10000):
            t.insert('', 'end', iid=str(i), values=('Hotovo', 'Ladislav Žluťoučký '+str(i), 'ARDEM Praha', '1 200,00'))
        settle(root)
        d = t._turto_cells_820
        original = tuple(t.item('0', 'values'))
        bar.draft.set('LAD')
        root.update_idletasks()
        assert bar.cget('style') == 'ActiveSearch.TFrame'
        assert 'Filtrování aktivní' in bar.hint.cget('text')
        assert ('0', 'Název', ((0, 3),)) in d.matches, d.matches
        bar.confirm()
        bar.draft.set('ARDE')
        bar.confirm()
        bar.draft.set('zlutoucky')
        root.update_idletasks()
        assert ('0', 'Název', ((0, 3), (9, 17))) in d.matches, d.matches
        assert ('0', 'Společnost', ((0, 4),)) in d.matches
        assert len(d.canvases) < 150, len(d.canvases)
        assert tuple(t.item('0', 'values')) == original
        assert t.get_children()[-1] == '9999'
        output = REPO/'dist/branding-preview'
        output.mkdir(parents=True, exist_ok=True)
        for theme in ('Světlý', 'Tmavý'):
            root.apply_theme(theme)
            settle(root)
            assert d.matches and bar.terms == ['lad', 'arde', 'zlutoucky']
            match_canvas = next(c for c in d.canvases if c.find_withtag('search-match'))
            assert match_canvas.itemcget(match_canvas.find_withtag('search-match')[0], 'fill') == SEARCH[theme=='Tmavý']['match']
            ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(),
                win.winfo_rootx()+win.winfo_width(), win.winfo_rooty()+win.winfo_height()), all_screens=True).save(
                    output/('filter-822-'+('light' if theme=='Světlý' else 'dark')+'.png'))

        # Press/drag/release go through Tk's native Treeview class binding.
        # Flush ONLY idle paint, never sleep for a debounce timer between moves.
        def drag(tree, column, distances):
            row = tree.identify_row(tree._v760_body_top + 1)
            x, y, width, _ = tree.bbox(row, column)
            start, header = x+width, max(3, y//2)
            initial = tree.column(column, 'width')
            tree.event_generate('<ButtonPress-1>', x=start, y=header)
            for delta in distances:
                tree.event_generate('<B1-Motion>', x=start+delta, y=header, state=256)
                root.update_idletasks()
                assert_aligned(tree, ('during-drag', column, delta))
                assert tree._v760_separator_after is None
            tree.event_generate('<ButtonRelease-1>', x=start+distances[-1], y=header)
            root.update_idletasks()
            assert tree.column(column, 'width') != initial, (column, initial)
        drag(t, 'Název', list(range(5, 101, 5)))
        drag(t, 'Název', list(range(-5, -81, -5)))
        for c, record in zip(d.canvases, d.rendered):
            x, _, _, _ = t.bbox(record[0], record[1])
            assert abs(int(c.place_info()['x']) - max(1, x+1)) <= 1

        # Real clicks on highlighted text retain selection, double-click and menu.
        import win32api
        import win32con
        double, context = [], []
        t.bind('<Double-Button-1>', lambda e: double.append(t.identify_row(e.y)))
        t.bind('<Button-3>', lambda e: context.append(t.identify_row(e.y)))
        idx = next(i for i, r in enumerate(d.rendered) if r[:2] == ('0', 'Název'))
        c = d.canvases[idx]
        win32api.SetCursorPos((c.winfo_rootx()+12, c.winfo_rooty()+10))
        for _ in range(2):
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN,0,0,0,0)
            settle(root,.025)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,0,0,0,0)
            settle(root,.025)
        assert t.selection() == ('0',) and double == ['0'], (t.selection(), double)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN,0,0,0,0)
        win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP,0,0,0,0)
        settle(root)
        assert context == ['0'], context
        assert tuple(t.item('0','values')) == original
        t.yview_moveto(.7)
        root.update_idletasks()
        assert int(d.matches[0][0]) > 5000
        t.configure(displaycolumns=('Společnost','Částka'))
        root.update_idletasks()
        assert all(col == 'Společnost' for _, col, _ in d.matches)
        bar.buttons[1].invoke()  # Remove ARDE; hidden-name matches remain valid.
        root.update_idletasks()
        assert not d.matches and 'Filtrování aktivní' in bar.hint.cget('text')
        t.configure(displaycolumns=('Společnost','Název','Stav','Částka'))
        t.column('Společnost', width=1100)
        t.xview_moveto(1)
        root.update_idletasks()
        assert_aligned(t, 'horizontal-scroll')
        assert any(col == 'Název' for _,col,_ in d.matches)
        bar.clear()
        root.update_idletasks()
        assert not d.matches and not bar.terms and bar.cget('style') == 'Panel.TFrame'
        assert all(not c.find_withtag('search-match') for c in d.canvases if c.winfo_ismapped())
        count = d.draw_count
        settle(root, .5)
        assert d.draw_count == count, (count, d.draw_count)
        d.schedule()
        win.destroy()
        settle(root)
        assert d.pending is None and not errors, errors
        print('8.0.22: 10000 rows, draft/chips/clear, both themes, native continuous drags, text clicks, hidden/reordered/scrolled columns, unchanged values and idle/teardown OK', flush=True)
    finally:
        root._turto_closing = True
        root.destroy()


if __name__ == '__main__':
    source_checks()
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-822-', ignore_cleanup_errors=True) as td:
            run(td)
