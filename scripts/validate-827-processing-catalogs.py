#!/usr/bin/env python3
"""Explicit catalog writes, concurrent multi-user assignment and real Tk events."""
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import action_assignees as assignees, catalog_selection as catalogs


def prepare(td, runtime=False):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app, data_location
    data_location.apply_to_app(app)
    app.ensure_schema()
    if runtime:
        import runtime_bootstrap
        runtime_bootstrap.apply_all(app)
        app.ensure_schema()
        app.ensure_test_user()
    return app


def rejects(callback):
    try:
        callback()
    except (ValueError, sqlite3.IntegrityError):
        return
    raise AssertionError('An invalid/stale write was accepted')


def source_checks(td):
    app = prepare(td)
    app.set_setting('active_user', '827 Editor')
    with app.db() as con:
        con.execute("INSERT INTO users(name) VALUES('827 Editor'),('827 Layout')")
        uid = con.execute("INSERT INTO users(name) VALUES('827 Alena')").lastrowid
        second = con.execute("INSERT INTO users(name) VALUES('827 Bára')").lastrowid
        inactive = con.execute("INSERT INTO users(name,active) VALUES('827 Old',0)").lastrowid
        aid = con.execute("INSERT INTO actions(name) VALUES('827 Příležitost')").lastrowid
        assert con.execute('SELECT assignees_json FROM actions WHERE id=?', (aid,)).fetchone()[0] == '[]'
        for table in catalogs.TABLES:
            catalogs.create_name(con, table, '827 Celý název')
            assert catalogs.create_name(con, table, '827 CELÝ NÁZEV') == '827 Celý název'
            assert catalogs.existing_name(con, table, '827 celý název') == '827 Celý název'
            rejects(lambda: catalogs.existing_name(con, table, '827 Celý'))
            assert catalogs.existing_name(con, table, 'Historická hodnota', ('Historická hodnota',)) == 'Historická hodnota'
            con.execute(f'UPDATE {table} SET active=0 WHERE name=?', ('827 Celý název',))
            rejects(lambda: catalogs.existing_name(con, table, '827 Celý název'))
            rejects(lambda: catalogs.create_name(con, table, '827 Celý název'))
            rejects(lambda: catalogs.create_name(con, table, '  '))
    def row():
        with app.db() as con:
            return con.execute('SELECT assignees_json FROM actions WHERE id=?', (aid,)).fetchone()[0]
    def history():
        with app.db() as con:
            return [tuple(r) for r in con.execute('SELECT * FROM action_history WHERE action_id=?', (aid,))]
    assert assignees.save(app, aid, '[]', [uid, second])
    saved = row()
    assert assignees.decode(saved) == {uid: '827 Alena', second: '827 Bára'}
    before = history()
    assert len(before) == 1
    assert not assignees.save(app, aid, saved, [second, uid, uid])
    assert history() == before
    rejects(lambda: assignees.save(app, aid, '[]', []))
    rejects(lambda: assignees.save(app, aid, saved, [inactive]))
    rejects(lambda: assignees.save(app, aid, saved, [999999]))
    assert row() == saved and history() == before
    with app.db() as con:
        con.execute('UPDATE users SET active=0 WHERE id=?', (uid,))
        con.execute('DELETE FROM users WHERE id=?', (second,))
    assert not assignees.save(app, aid, saved, [uid, second])
    assert assignees.save(app, aid, saved, [second])
    assert assignees.display(row()) == '827 Bára', 'Deleted user lost their saved name'
    saved = row()
    before = history()
    with app.db() as con:
        con.execute("CREATE TRIGGER reject_827_history BEFORE INSERT ON action_history BEGIN SELECT RAISE(ABORT,'test failure'); END")
    rejects(lambda: assignees.save(app, aid, saved, []))
    assert row() == saved and history() == before, 'History failure did not roll back assignment'
    with app.db() as con:
        con.execute('DROP TRIGGER reject_827_history')
    assert assignees.save(app, aid, saved, []) and row() == '[]'
    # Emulate an existing pre-8.0.27 schema and legacy free text. Startup adds
    # only the new column; it does not repopulate catalogues from records.
    with app.db() as con:
        con.execute('ALTER TABLE actions DROP COLUMN assignees_json')
        for table in ('work_topics', 'person_roles', 'materials'):
            con.execute(f'DELETE FROM {table}')
        con.execute("UPDATE actions SET products='Rozepsaný / import; 827' WHERE id=?", (aid,))
        con.execute("INSERT INTO people(name,email,role) VALUES('827 Legacy','827-legacy@example.test','827 Zkrácená funkce')")
        con.execute("INSERT INTO requests(item) VALUES('827 Zkrácený materiál')")
    app.ensure_schema()
    app.ensure_schema()
    with app.db() as con:
        assert con.execute('SELECT assignees_json FROM actions WHERE id=?', (aid,)).fetchone()[0] == '[]'
        for table in ('work_topics', 'person_roles', 'materials'):
            assert con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0, table
    print('8.0.27: additive migration, explicit catalogues, multiple users, inactive/deleted users, stale writes and atomic history OK', flush=True)


def settle(root, seconds=.25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(.01)


def ui_checks(td):
    app = prepare(td, runtime=True)
    from price_lists_domain.platform.form_behavior_817 import children
    from price_lists_domain.platform import table_preferences_815
    app.App.maybe_show_morning_overview = lambda self: None
    warnings, errors = [], []
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: warnings.append(a)
    app.messagebox.showerror = lambda *a, **k: errors.append(a)
    app.messagebox.askyesnocancel = lambda *a, **k: False
    app.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    app.set_setting('active_user', '827 Editor')
    with app.db() as con:
        con.execute("INSERT INTO users(name) VALUES('827 Editor'),('827 Layout')")
        uid = con.execute("INSERT INTO users(name) VALUES('827 Alena')").lastrowid
        second = con.execute("INSERT INTO users(name) VALUES('827 Bára')").lastrowid
        cid = con.execute("INSERT INTO companies(short_name,official_name) VALUES('827 Dodavatel','827 Dodavatel')").lastrowid
        aid = con.execute("INSERT INTO actions(name,company_id,created_date) VALUES('827 Ověření',?,'2026-09-17')", (cid,)).lastrowid
        con.execute("INSERT INTO work_topics(name) VALUES('827 Akustika'),('827 Dilatace')")
        con.execute("INSERT INTO person_roles(name) VALUES('827 Projektant')")
        con.execute("INSERT INTO materials(name) VALUES('827 Izolační nosník')")
        con.execute("INSERT INTO materials(name,active) VALUES('827 Neaktivní materiál',0)")
    root = app.App()
    def button(win, label):
        return next(w for w in children(win) if w.winfo_class() in {'Button', 'TButton'} and str(w.cget('text')) == label)
    def current():
        with app.db() as con:
            return con.execute('SELECT assignees_json FROM actions WHERE id=?', (aid,)).fetchone()[0]
    def snapshot():
        with app.db() as con:
            return {table: [tuple(r) for r in con.execute(f'SELECT * FROM {table} ORDER BY id')]
                    for table in ('work_topics', 'person_roles', 'materials', 'actions', 'people', 'requests')}
    try:
        root.state('normal'); root.geometry('1440x900+0+0'); settle(root, 4)
        assert root.nav['actions'].cget('text') == 'Ke zpracování'
        root.show_page('offers'); settle(root)
        assert root.offer_metric_vars == {}
        labels = [str(w.cget('text')) for w in children(root.tabs['offers']) if w.winfo_class() == 'TLabel']
        assert not any(s in labels for s in ('Aktivních nabídek', 'Nepřiřazených', 'Bez zařazení položek'))
        assert root.offer_tree.winfo_viewable()
        assert 'dash' in root.tabs
        root.show_page('actions'); settle(root)
        tree = root.action_tree
        assert 'Řeší' in tree['columns'], tree['columns']
        iid = f'a{aid}'
        assert iid in tree.get_children(), tree.get_children()
        assert button(root.tabs['actions'], 'Řeší…').winfo_viewable()
        # Existing saved layout: new column appears, hidden old column stays hidden.
        old_columns = [c for c in tree['columns'] if c != 'Řeší']
        old_visible = [c for c in old_columns if c != 'Poznámka']
        # Load a previously unused profile so an initial cached empty layout
        # does not hide the fixture written directly to user_settings.
        app.set_user_setting('827 Layout', table_preferences_815.key_for(tree),
                             json.dumps({'columns': old_columns, 'visible': old_visible, 'widths': {c: 120 for c in old_columns}}))
        root.active_user.set('827 Layout')
        app.set_setting('active_user', '827 Layout')
        app.install_persistent_tree_layout(tree, force=True); settle(root)
        assert 'Řeší' in tree['displaycolumns'] and 'Poznámka' not in tree['displaycolumns'], tree['displaycolumns']
        tree.selection_set(iid)
        picker = assignees.open_picker(app, root); settle(root)
        picker.assignee_variables[uid].set(True); picker.assignee_variables[second].set(True)
        assert current() == '[]'
        button(picker, 'Zrušit').invoke(); settle(root)
        assert current() == '[]'
        picker = assignees.open_picker(app, root); settle(root)
        picker.assignee_variables[uid].set(True); picker.assignee_variables[second].set(True)
        button(picker, 'Uložit').invoke(); settle(root)
        assert set(assignees.decode(current())) == {uid, second}
        assert tree.set(iid, 'Řeší') == '827 Alena, 827 Bára', tree.item(iid, 'values')
        root._table_searches['actions'].draft.set('827 Bára'); settle(root, .7)
        assert tree.get_children() == (iid,)
        root._table_searches['actions'].draft.set(''); settle(root, .7)
        # Reordered displayed column still routes its own double-click to picker.
        columns = list(tree['displaycolumns']); columns.remove('Řeší')
        tree.configure(displaycolumns=('Řeší', *columns)); settle(root)
        box = tree.bbox(iid, 'Řeší'); assert box, tree['displaycolumns']
        x, y, w, h = box
        tree.focus_force()
        for event, stamp in (('<ButtonPress-1>', 10000), ('<ButtonRelease-1>', 10010),
                             ('<ButtonPress-1>', 10100), ('<ButtonRelease-1>', 10110)):
            tree.event_generate(event, x=x+w//2, y=y+h//2, time=stamp)
        settle(root)
        assert not getattr(root, '_action_status_editor', None), 'Assignee column opened the status editor'
        picker = next(w for w in root.winfo_children() if hasattr(w, 'assignee_variables'))
        assert picker.assignee_variables[uid].get() and picker.assignee_variables[second].get()
        picker.assignee_variables[uid].set(False)
        picker.tk.call(picker.protocol('WM_DELETE_WINDOW')); settle(root)
        assert set(assignees.decode(current())) == {uid, second}

        before = snapshot()
        dialog = app.ActionDialog(root)
        dialog.name.set('827 Nový záznam')
        entry = dialog.topic_entry
        entry.focus_force(); settle(root)
        dialog.topic_entry_var.set('827'); settle(root)
        entry.event_generate('<Down>'); settle(root, .05)
        expected = entry.listbox.get(entry.listbox.curselection()[0])
        entry.event_generate('<Return>'); settle(root)
        assert dialog.topic_entry_var.get() == expected
        assert dialog.result is None and dialog.winfo_exists()
        assert snapshot() == before, 'Selecting suggestion wrote business/catalog data'
        button(dialog, '+ Přidat').invoke(); settle(root)
        assert expected in dialog.selected_topics and snapshot() == before
        # Leave a popup with a prior selection, then Enter before its 70 ms update.
        entry.focus_force(); dialog.topic_entry_var.set('827'); settle(root)
        dialog.topic_entry_var.set('827 Aku')
        assert root.focus_get() is entry, ('autocomplete focus', root.focus_get())
        entry.event_generate('<Return>'); settle(root)
        assert dialog.topic_entry_var.get() == '827 Akustika', dialog.topic_entry_var.get()
        assert snapshot() == before
        # Check the installed keypad binding as well. Tk on Windows can drop
        # synthesized keypad events; only in that case invoke its Tcl command.
        keys = []
        tag = 'Processing827KeyProbe'
        entry.bind_class(tag, '<KeyPress>', lambda e: keys.append(e.keysym))
        tags = entry.bindtags(); entry.bindtags((tag, *tags))
        dialog.topic_entry_var.set('827 Dil')
        entry.event_generate('<KP_Enter>'); settle(root, .05)
        if not keys:
            command = re.search(r'\[([^\s]+)', entry.bind('<KP_Enter>')).group(1)
            entry.tk.call(command)
        entry.bindtags(tags); entry.unbind_class(tag, '<KeyPress>')
        settle(root)
        assert dialog.topic_entry_var.get() == '827 Dilatace', (dialog.topic_entry_var.get(), keys)
        assert snapshot() == before
        dialog.topic_entry_var.set('827 Neznámý prefix')
        button(dialog, '+ Přidat').invoke(); settle(root)
        assert '827 Neznámý prefix' not in dialog.selected_topics
        dialog.ok(); settle(root)
        assert dialog.winfo_exists() and snapshot() == before
        dialog.topic_entry_var.set('827 Akustika')
        dialog.ok(); settle(root)
        assert dialog.result and not dialog.winfo_exists()
        with app.db() as con:
            assert con.execute('SELECT products FROM actions WHERE id=?', (dialog.result,)).fetchone()[0]
            assert con.execute("SELECT count(*) FROM work_topics WHERE name='827 Neznámý prefix'").fetchone()[0] == 0

        person = app.PersonDialog(root); settle(root)
        person.vars['name'].set('827 Nová osoba'); person.vars['email'].set('827@example.test')
        person.company.set('827 Dodavatel'); person.vars['role'].set('827 Proj')
        before = snapshot(); person.ok(); settle(root)
        assert person.winfo_exists() and snapshot() == before
        app.simpledialog.askstring = lambda *a, **k: None
        person.add_role(); assert snapshot() == before
        app.simpledialog.askstring = lambda *a, **k: '827 Nová funkce'
        person.add_role(); settle(root)
        assert person.vars['role'].get() == '827 Nová funkce'
        with app.db() as con:
            assert con.execute("SELECT count(*) FROM person_roles WHERE name='827 Nová funkce'").fetchone()[0] == 1
        person.ok(); settle(root); assert not person.winfo_exists() and person.result

        request = app.RequestDialog(root); settle(root)
        request.company.set('827 Dodavatel'); request.item.set('827 Izolační')
        request.asked.set('17.09.2026')
        assert '827 Neaktivní materiál' not in request.item_box.values
        before = snapshot(); request.ok(); settle(root)
        assert request.winfo_exists() and request.result is None and snapshot() == before
        app.simpledialog.askstring = lambda *a, **k: None
        request.new_material(); assert snapshot() == before
        request.item_box.focus_force(); request.item.set('827 Izolační'); settle(root)
        request.item_box.event_generate('<Return>'); settle(root)
        assert request.item.get() == '827 Izolační nosník' and request.result is None
        assert snapshot() == before
        request.ok(); settle(root)
        assert request.result and request.result['item'] == '827 Izolační nosník', (request.result, warnings)
        assert not errors, errors
        assert len(warnings) >= 3, warnings
        print('8.0.27: Windows cards, renamed tab, upgraded layout, multi-select Save/Cancel, history/search, Enter/KP Enter, fresh suggestions and explicit catalog writes OK', flush=True)
    finally:
        root._turto_closing = True
        for token in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(token)
        try:
            root.destroy()
        except (app.tk.TclError, TypeError):
            pass  # Child process exit releases any legacy Tcl/SQLite handles.


if __name__ == '__main__':
    if '--source-worker' in sys.argv:
        source_checks(sys.argv[-1])
    elif '--ui-worker' in sys.argv:
        ui_checks(sys.argv[-1])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-processing-827-') as td:
            subprocess.run([sys.executable, '-B', __file__, '--source-worker', str(Path(td) / 'source')], check=True)
            if '--source-only' not in sys.argv:
                subprocess.run([sys.executable, '-B', __file__, '--ui-worker', str(Path(td) / 'ui')], check=True)
