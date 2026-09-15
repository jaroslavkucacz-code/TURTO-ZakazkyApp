#!/usr/bin/env python3
"""Exercise real persistence across separate CRM processes and dialog lifetimes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def settle(win, seconds=.4):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        win.update()
        time.sleep(.01)


def walk(win):
    yield win
    for child in win.winfo_children():
        yield from walk(child)


def run(td, phase):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform.table_preferences_815 import key_for
    from v760_table_activity_performance import _displayed_columns
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    app.APP_NAME = 'Zakázky' if phase == 'write' else 'TURTO CRM po přeinstalaci'
    app.APP_VERSION = '8.0.15' if phase == 'write' else '9.9.9'
    window = app.App()
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(str(exc))
    state_path = Path(td) / 'expected-layouts.json'

    def snapshot(tree):
        return {'visible': _displayed_columns(tree),
                'widths': dict(tree._turto_design_widths)}

    def alter(tree, width):
        columns = list(map(str, tree.cget('columns')))
        assert columns
        assert getattr(tree, '_v700_layout_installed', False), str(tree)
        assert getattr(tree, '_v700_columns_menu', False), str(tree)
        tree._turto_design_widths.update({c: width + 11*i for i, c in enumerate(columns)})
        if '#0' in tree._turto_design_widths:
            tree._turto_design_widths['#0'] = 173
        visible = [columns[0], *reversed(columns[1:-1])] if len(columns) > 1 else columns
        tree.configure(displaycolumns=tuple(visible))
        app.save_persistent_tree_layout(tree)
        app.install_persistent_tree_layout(tree)
        with app.db() as con:
            assert con.execute('SELECT value FROM user_settings WHERE user_name=? AND key=?',
                (window.active_user.get(), key_for(tree))).fetchone(), str(tree)
        return snapshot(tree)

    try:
        window.state('normal')
        window.geometry('1220x760+0+0')
        settle(window, 4.2)  # include the delayed legacy column contracts
        assert not errors, errors
        main_trees = {name: tree for name, tree in vars(window).items()
                      if name.endswith('_tree') and isinstance(tree, app.ttk.Treeview)
                      and tree.cget('columns')}
        assert len(main_trees) >= 13, sorted(main_trees)
        assert len({key_for(t) for t in main_trees.values()}) == len(main_trees)
        if phase == 'write':
            expected = {name: alter(tree, 139+i) for i, (name, tree) in enumerate(main_trees.items())}
        else:
            expected = json.loads(state_path.read_text(encoding='utf-8'))
            for name, tree in main_trees.items():
                assert snapshot(tree) == expected[name], (name, snapshot(tree), expected[name])

        # Every business Treeview, including less-used catalog and history
        # tables, is registered without patching any native Treeview method.
        for tree in (w for w in walk(window) if isinstance(w, app.ttk.Treeview)):
            if tree.cget('columns'):
                assert getattr(tree, '_v700_layout_installed', False), str(tree)

        # Real Company dialog: mouse resize, close immediately on release,
        # reopen with different title/counters, then restart the whole process.
        dialog = app.CompanyDialog(window)
        settle(window)
        people = dialog.people_tree
        assert people._v700_columns_menu
        if phase == 'write':
            first = _displayed_columns(people)[0]
            people.insert('', 'end', iid='815-resize', values=('Test', '', '', ''))
            settle(window)
            box = people.bbox('815-resize', first)
            x, y = box[0] + box[2] - 1, 10
            assert people.identify_region(x, y) == 'separator'
            before = int(people.column(first, 'width'))
            people.event_generate('<ButtonPress-1>', x=x, y=y)
            people.event_generate('<B1-Motion>', x=x+27, y=y, state=256)
            people.event_generate('<ButtonRelease-1>', x=x+27, y=y)
            after = int(people.column(first, 'width'))
            # Tk's separator hit area can start one pixel before the exact
            # boundary. Compare persistence with the actual native drag result.
            assert after > before + 10, ('mouse did not resize', before, after)
            assert int(people._turto_design_widths[first]) == after, ('resize not saved', before, after, people._turto_design_widths)
            expected['company_dialog'] = snapshot(people)
        else:
            assert snapshot(people) == expected['company_dialog']
        dialog.destroy()  # deliberately no idle/event pump after mouse release
        dialog = app.CompanyDialog(window)
        dialog.title('Společnost – jiné jméno a jiná verze 99.1')
        settle(window)
        assert snapshot(dialog.people_tree) == expected['company_dialog']
        dialog.destroy()

        # Public column dialog: hide a column and commit with the actual button.
        if phase == 'write':
            tree = window.dash_tree
            tops = set(w for w in walk(window) if isinstance(w, app.tk.Toplevel))
            app.open_tree_columns_dialog(tree)
            settle(window)
            columns_dialog = next(w for w in walk(window) if isinstance(w, app.tk.Toplevel) and w not in tops)
            listing = next(w for w in walk(columns_dialog) if isinstance(w, app.ttk.Treeview))
            listing.selection_set(listing.get_children('')[0])
            def button(text):
                return next(w for w in walk(columns_dialog) if w.winfo_class() in ('Button', 'TButton')
                            and str(w.cget('text')) == text)
            button('Zobrazit / skrýt').invoke()
            button('Použít').invoke()
            settle(window)
            expected['dash_tree'] = snapshot(tree)

        user = window.active_user.get()
        window.active_user.set('Denisa Kovalová' if user != 'Denisa Kovalová' else 'Jaroslav Kučera')
        window.on_user_changed()
        settle(window)
        assert snapshot(window.dash_tree) != expected['dash_tree'], 'Another user inherited this profile'
        window.active_user.set(user)
        window.on_user_changed()
        settle(window)
        assert snapshot(window.dash_tree) == expected['dash_tree'], 'Switching back lost the profile'

        # Migrate an old title-based profile, then survive a renamed window.
        legacy = {'visible': ['B', 'A'], 'widths': {'A': 151, 'B': 181, 'C': 199}}
        old_key = 'tree_layout_v700_' + hashlib.sha1(b'Historie|A|B|C').hexdigest()[:20]
        if phase == 'write':
            with app.db() as con:
                con.execute('INSERT INTO user_settings(user_name,key,value) VALUES(?,?,?)',
                            (user, old_key, json.dumps(legacy)))
        custom = app.tk.Toplevel(window)
        custom.title('Historie 8.0.14' if phase == 'write' else 'Nový název')
        tree = app.ttk.Treeview(custom, columns=('A', 'B', 'C'), show='headings', name='layout__migration_probe')
        tree.pack(fill='both', expand=True)
        settle(window)
        assert _displayed_columns(tree) == legacy['visible']
        assert tree._turto_design_widths == legacy['widths']
        # A new column is offered without unhiding a previously hidden one.
        tree.configure(columns=('A', 'B', 'C', 'New'))
        app.install_persistent_tree_layout(tree)
        settle(window)
        assert _displayed_columns(tree) == ['B', 'A', 'New']
        custom.destroy()
        if phase == 'write':
            state_path.write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding='utf-8')
        assert not errors, errors
        print(f'8.0.15 {phase}: {len(main_trees)} main tables, live dialogs, real mouse/button saves, users and legacy migration OK')
    finally:
        window._turto_closing = True
        window.destroy()


if __name__ == '__main__':
    if len(sys.argv) == 3:
        run(sys.argv[1], sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-preferences-') as td:
            for phase in ('write', 'read'):
                subprocess.run([sys.executable, str(Path(__file__).resolve()), td, phase], check=True, timeout=180)
