#!/usr/bin/env python3
"""Exercise real Tab, WM close and Escape events, including real DB saves."""
import os
from pathlib import Path
import sys
import tempfile
import time

BASE = Path(__file__).resolve().parents[1] / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def settle(win, seconds=.3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        win.update()
        time.sleep(.01)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform.form_behavior_817 import children, editable
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: 'ok'
    app.messagebox.showwarning = lambda *a, **k: 'ok'
    app.messagebox.showerror = lambda *a, **k: 'ok'
    replies, questions, errors = [], [], []
    def question(*args, **kwargs):
        questions.append((args, kwargs))
        assert replies, ('Unexpected close prompt', args)
        return replies.pop(0)
    app.messagebox.askyesnocancel = question
    window = app.App()
    window.report_callback_exception = lambda *exc: errors.append(str(exc))

    def cross(win):
        win.tk.call(win.protocol('WM_DELETE_WINDOW'))
        settle(window)

    def escape(win, field):
        field.focus_force()
        settle(window, .1)
        field.event_generate('<Escape>')
        settle(window)

    try:
        window.state('normal')
        window.geometry('1240x840+0+0')
        settle(window, 4.2)
        # Mixed native controls: only writable fields are in the Tab cycle.
        dialog = app.tk.Toplevel(window)
        first = app.ttk.Entry(dialog); first.pack()
        button = app.ttk.Button(dialog, text='Akce'); button.pack()
        app.ttk.Checkbutton(dialog, text='Volba').pack()
        read = app.ttk.Combobox(dialog, state='readonly', values=['A']); read.pack()
        disabled = app.ttk.Entry(dialog); disabled.state(['disabled']); disabled.pack()
        hidden = app.ttk.Entry(dialog); hidden.pack(); hidden.pack_forget()
        app.ttk.Treeview(dialog).pack()
        note = app.tk.Text(dialog, height=2); note.pack()
        combo = app.ttk.Combobox(dialog, values=['A']); combo.pack()
        last = app.ttk.Entry(dialog); last.pack()
        nested = app.tk.Toplevel(dialog)
        foreign = app.ttk.Entry(nested); foreign.pack()
        nested.withdraw()
        settle(window)
        first.focus_force(); settle(window, .1)
        for expected in (note, combo, last, first):
            current = window.focus_get()
            current.event_generate('<Tab>')
            settle(window, .1)
            assert window.focus_get() is expected, ('Tab', current, window.focus_get(), expected)
        assert note.get('1.0', 'end-1c') == '', 'Tab inserted into Text'
        for expected in (last, combo, note, first):
            window.focus_get().event_generate('<Shift-Tab>')
            settle(window, .1)
            assert window.focus_get() is expected, ('Shift-Tab', window.focus_get(), expected)
        button.focus_set(); button.event_generate('<Tab>'); settle(window, .1)
        assert window.focus_get() is note
        dialog.destroy()

        # Normal business dialogs: opening/navigating is clean; text and
        # multiline changes prompt; reverting a change becomes clean again.
        for cls in (app.CompanyDialog, app.PersonDialog, app.ProjectDialog,
                    app.TaskDialog, app.ActionDialog, app.RequestDialog):
            dialog = cls(window)
            settle(window, .6)
            guard = dialog._turto_form_guard
            assert not guard.changed(), (cls.__name__, 'false initial dirty', guard.baseline, guard.snapshot())
            field = next(w for w in children(dialog) if editable(w) and w.winfo_class() == 'Text')
            field.insert('end', '817 rozepsaná poznámka')
            replies.append(None)
            cross(dialog)
            assert dialog.winfo_exists() and guard.changed(), cls.__name__
            assert '817' in field.get('1.0', 'end-1c')
            replies.append(False)
            escape(dialog, field)
            assert not dialog.winfo_exists(), (cls.__name__, 'Escape failed to discard')
            dialog = cls(window)
            settle(window, .5)
            field = next(w for w in children(dialog) if editable(w) and w.winfo_class() == 'Text')
            old = field.get('1.0', 'end-1c')
            field.insert('end', 'temporary')
            field.delete('1.0', 'end'); field.insert('1.0', old)
            before = len(questions)
            cross(dialog)
            assert not dialog.winfo_exists() and len(questions) == before, (cls.__name__, 'reverted change prompted')
            print('Form close OK:', cls.__name__, flush=True)

        # Saving from the close prompt uses the actual Task validation and DB.
        dialog = app.TaskDialog(window)
        settle(window)
        field = next(w for w in children(dialog) if editable(w) and w.winfo_class() == 'Text')
        field.insert('end', '817 save draft')
        replies.append(True)
        cross(dialog)
        assert dialog.winfo_exists(), 'Invalid task was discarded after failed save'
        # The description is the required field in the normal task editor.
        dialog.text.set('817 persisted task')
        with app.db() as con:
            con.execute("INSERT INTO actions(name) VALUES('817 test opportunity')")
        dialog.action.set('817 test opportunity')
        replies.append(True)
        cross(dialog)
        assert not dialog.winfo_exists(), 'Valid task did not save and close'
        with app.db() as con:
            assert con.execute("SELECT 1 FROM tasks WHERE text=?", ('817 persisted task',)).fetchone()

        # Private notes: searching is not editing, save-and-close persists the
        # note once and respects the existing notebook cleanup callback.
        notes = app.UserNotesDialog(window)
        settle(window)
        notes.search_var.set('search only'); settle(window)
        assert not notes._turto_form_guard.changed()
        notes.editor.insert('end', '817 private note')
        replies.append(True); cross(notes)
        assert not notes.winfo_exists()
        with app.db() as con:
            assert con.execute('SELECT COUNT(*) FROM user_notes WHERE text=?', ('817 private note',)).fetchone()[0] == 1

        # Editors with their own document fingerprints must use those same
        # guards for the title-bar close button, not only their footer button.
        editor = app.IssuedOfferEditor(app, window)
        settle(window, .6)
        editor.customer_note.insert('end', '817 pending issued offer')
        replies.append(None); cross(editor.win)
        assert editor.win.winfo_exists()
        replies.append(False); cross(editor.win)
        assert not editor.win.winfo_exists()
        from price_lists_domain.issued_offers.template_settings import TemplateEditor
        template = TemplateEditor(app, window)
        settle(window, .5)
        template.name.set('817 unsaved template')
        replies.append(None); cross(template.win)
        assert template.win.winfo_exists()
        replies.append(False); cross(template.win)
        assert not template.win.winfo_exists()

        from price_lists_domain.platform import categories
        category_result = []
        def inspect_categories():
            try:
                manager = next(w for w in window.winfo_children() if isinstance(w, app.tk.Toplevel)
                               and w.title() == 'Produktové skupiny a podskupiny')
                entries = [w for w in children(manager) if isinstance(w, app.ttk.Entry)]
                entries[0].insert(0, 'search only')
                assert not manager._turto_form_guard.changed()
                entries[1].insert(0, '817 unsaved group')
                replies.append(None); cross(manager)
                assert manager.winfo_exists()
                replies.append(False); cross(manager)
                assert not manager.winfo_exists()
                category_result.append(True)
            except Exception as exc:
                category_result.append(repr(exc))
                for w in tuple(window.winfo_children()):
                    if isinstance(w, app.tk.Toplevel):
                        w.destroy()
        window.after(150, inspect_categories)
        categories.manage_categories(app, window)
        assert category_result == [True], category_result

        # Functional forms constructed without bind_dialog_keys are enrolled
        # too. A failed save and an exception both retain the original draft.
        generic = app.tk.Toplevel(window)
        entry = app.ttk.Entry(generic); entry.pack()
        state = {'mode': 'invalid'}
        def save():
            if state['mode'] == 'error':
                raise RuntimeError('simulated unavailable storage')
            if state['mode'] == 'valid':
                generic.destroy()
        app.ttk.Button(generic, text='Uložit', command=save).pack()
        app.ttk.Button(generic, text='Zrušit', command=generic.destroy).pack()
        settle(window)
        entry.insert(0, 'pending')
        replies.append(True); cross(generic)
        assert generic.winfo_exists() and entry.get() == 'pending'
        # Invoke through a Python callback to test propagated storage errors;
        # normal Tk callbacks route exceptions to the app handler instead.
        generic._turto_form_guard.save = save
        state['mode'] = 'error'
        replies.append(True); cross(generic)
        assert generic.winfo_exists() and entry.get() == 'pending'
        state['mode'] = 'valid'
        replies.append(True); cross(generic)
        assert not generic.winfo_exists()

        # Main-window close also honors a cancelled child form close.
        dialog = app.TaskDialog(window); settle(window)
        field = next(w for w in children(dialog) if editable(w) and w.winfo_class() == 'Text')
        field.insert('end', 'keep open')
        replies.append(None)
        window.close_app(); settle(window)
        assert window.winfo_exists() and dialog.winfo_exists()
        dialog.destroy()
        assert not replies, replies
        assert not errors, errors
        print('8.0.17: input-only Tab, six business forms, real save, cancel/discard, notes, offers, templates, categories and generic forms OK', flush=True)
    finally:
        window._turto_closing = True
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='turto-form-behavior-', ignore_cleanup_errors=True) as td:
        run(td)
