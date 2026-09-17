#!/usr/bin/env python3
"""Grouped routes retain lazy refresh; real Windows buttons, state and bounds."""
import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import grouped_navigation as navigation, lazy_refresh


def source_checks(td):
    spec = importlib.util.spec_from_file_location('navigation_fixture', REPO / 'scripts/validate-ui-navigation.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)

    class Row:
        def __init__(self):
            self.manager = ''
        def pack(self, **kwargs):
            self.manager = 'pack'
        def pack_forget(self):
            self.manager = ''
        def winfo_manager(self):
            return self.manager

    class App(fixture.FakeApp):
        pass

    module = SimpleNamespace(App=App, DATA_ROOT=Path(td), messagebox=fixture.FakeMessagebox)
    lazy_refresh.install(module)
    app = App()
    app.main_nav = Row()
    app.nav_groups = {key: Row() for key in navigation.GROUPS}
    app._nav_last_pages = {}
    app.nav.update({key: fixture.FakeWidget() for key in navigation.GROUPS})
    original_pages = dict(app.tabs)

    app.show_page('directory')
    app.run_all()
    assert app._current_page == 'companies'
    assert app.refresh_counts == {'companies': 1}
    app.show_page('people')
    app.run_all()
    assert app._current_page == 'people'
    app.show_page('technical')
    app.run_all()
    assert app._current_page == 'actions'
    app.show_page('requests')
    app.run_all()
    counts = dict(app.refresh_counts)
    for _ in range(40):
        app.show_page('directory')
        assert app._current_page == 'people'
        app.show_page('technical')
        assert app._current_page == 'requests'
    app.run_all()
    assert app.refresh_counts == counts, 'Clean groups must not reload their pages'

    app._turto_mark_dirty({'requests', 'companies'})
    for _ in range(40):
        app.show_page('companies')
        app.show_page('technical')
    assert len(app._events) == 1
    app.run_all()
    assert app.refresh_counts['requests'] == counts['requests'] + 1
    assert app.refresh_counts['companies'] == counts['companies'], 'Hidden dirty page refreshed'
    assert app.nav['technical'].options['style'] == 'TopNavActive.TButton'
    assert app.nav['requests'].options['style'] == 'SubNavActive.TButton'
    assert app.nav['directory'].options['style'] == 'TopNav.TButton'
    assert app.nav_groups['technical'].manager == 'pack'
    assert app.nav_groups['directory'].manager == ''
    app.show_page('directory')
    app.run_all()
    assert app._current_page == 'companies'
    assert app.refresh_counts['companies'] == counts['companies'] + 1
    app.show_page('settings')
    assert all(not row.manager for row in app.nav_groups.values())
    assert app.tabs == original_pages and app.old_show_calls == 0
    assert app.legacy_layout_runs == 0
    app.close_app()
    app.show_page('technical')
    app.run_all()
    assert app._current_page == 'settings' and not app._events
    print('8.0.26: group defaults, remembered tabs, direct links, active levels, deferred dirty refresh and shutdown OK', flush=True)


def settle(root, seconds=.35):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(.01)


def ui_checks(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app, data_location, runtime_bootstrap
    from PIL import ImageGrab
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.APP_VERSION = (REPO / 'build/windows/version.txt').read_text().strip()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    errors = []
    app.messagebox.showerror = lambda *a, **k: errors.append(str(a))
    app.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    with app.db() as con:
        cid = con.execute("INSERT INTO companies(short_name,official_name) VALUES('826 Alpha','826 Alpha')").lastrowid
        con.execute("INSERT INTO companies(short_name,official_name) VALUES('826 Beta','826 Beta')")
    root = app.App()
    try:
        root.state('normal')
        root.geometry('1220x800+0+0')
        settle(root, 4)
        original_pages = dict(root.tabs)
        assert 'directory' not in root.tabs and 'technical' not in root.tabs

        def keys(parent):
            return [next(k for k, b in root.nav.items() if b is widget) for widget in parent.pack_slaves()]

        def hierarchy():
            assert keys(root.main_nav) == ['dash', 'technical', 'pricelists', 'issued_offers', 'received_orders', 'projects', 'directory']
            assert keys(root.nav_groups['directory']) == ['companies', 'people']
            assert keys(root.nav_groups['technical']) == ['actions', 'requests', 'mivo', 'offers', 'tasks']
            for key in navigation.PAGE_GROUP:
                assert root.nav[key].master is root.nav_groups[navigation.PAGE_GROUP[key]]

        def current(key):
            assert root._current_page == key
            assert root.tabs[key].winfo_ismapped()
            group = navigation.PAGE_GROUP.get(key)
            for name, row in root.nav_groups.items():
                assert bool(row.winfo_viewable()) == (name == group), (key, name)
            for name, button in root.nav.items():
                assert ('Active.' in button.cget('style')) == (name == key or name == group), (key, name)
                if button.winfo_viewable():
                    assert button.winfo_width() >= button.winfo_reqwidth(), (key, name, 'clipped label')
                    assert root.winfo_rootx() <= button.winfo_rootx()
                    assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width(), (key, name, 'outside window')
                    assert button.winfo_rooty() + button.winfo_height() <= root.host.winfo_rooty(), (key, name, 'overlapping content')
            if group:
                assert root.nav[key].winfo_rooty() >= root.main_nav.winfo_rooty() + root.main_nav.winfo_height()

        def click(key):
            button = root.nav[key]
            assert button.winfo_viewable(), key
            button.event_generate('<Enter>')
            button.event_generate('<ButtonPress-1>', x=8, y=8)
            button.event_generate('<ButtonRelease-1>', x=8, y=8)
            settle(root)

        hierarchy()
        current('dash')
        click('directory')
        current('companies')
        bar = root._table_searches['companies']
        bar.draft.set('826 Alpha')
        settle(root, .7)
        tree = root.company_tree
        iid = 'c' + str(cid)
        assert tree.get_children() == (iid,), tree.get_children()
        tree.selection_set(iid)
        before_columns = tuple((c, tree.column(c, 'width')) for c in tree['columns'])
        before_values = tree.item(iid, 'values')
        click('technical')
        current('actions')
        for key in ('requests', 'mivo', 'offers', 'tasks'):
            click(key)
            current(key)
        click('directory')
        current('companies')
        assert bar.draft.get() == '826 Alpha'
        assert tree.get_children() == (iid,) and tree.selection() == (iid,)
        assert tree.item(iid, 'values') == before_values
        assert tuple((c, tree.column(c, 'width')) for c in tree['columns']) == before_columns
        click('people')
        current('people')
        click('technical')
        current('tasks')
        click('directory')
        current('people')

        # The existing show_page calls used by dialog/dashboard links must reveal
        # the correct parent even when the other group is open.
        root.show_page('requests')
        settle(root)
        current('requests')
        root.show_page('companies')
        settle(root)
        current('companies')
        root.nav['technical'].focus_force()
        root.nav['technical'].event_generate('<Return>')
        settle(root)
        current('requests')
        for key in ('pricelists', 'issued_offers', 'projects', 'dash'):
            click(key)
            current(key)
        root.help_button.invoke()
        settle(root)
        current('help')
        root.show_page('settings')
        settle(root)
        current('settings')

        output = REPO / 'build/validation/navigation-826'
        output.mkdir(parents=True, exist_ok=True)
        for theme in ('Světlý', 'Tmavý'):
            root.apply_theme(theme)
            for key in ('technical', 'directory'):
                click(key)
                current('requests' if key == 'technical' else 'companies')
                hierarchy()  # Delayed legacy callbacks must not flatten the groups.
                ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                    root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height()),
                    all_screens=True).save(output / (key + ('-light.png' if theme == 'Světlý' else '-dark.png')))
        root.geometry('1500x900+0+0')
        settle(root)
        current('companies')
        click('technical')
        current('requests')
        root.geometry('1220x800+0+0')
        settle(root)
        current('requests')
        assert root.tabs == original_pages, 'Navigation rebuilt a data page'
        assert not errors, errors
        print('8.0.26: Windows two-level buttons, Enter, direct links, remembered tabs, filters/selection/widths, themes and resize OK', flush=True)
    finally:
        try:
            root._turto_closing = True
            for token in root.tk.splitlist(root.tk.call('after', 'info')):
                root.after_cancel(token)
            root.destroy()
        except Exception:
            pass


if __name__ == '__main__':
    if '--ui-worker' in sys.argv:
        ui_checks(sys.argv[sys.argv.index('--ui-worker') + 1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-navigation-826-') as td:
            source_checks(td)
            if '--source-only' not in sys.argv:
                # Windows releases every legacy SQLite handle when the UI
                # process exits, before the parent removes its temporary DB.
                subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                '--ui-worker', td], check=True)
