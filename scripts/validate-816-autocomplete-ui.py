#!/usr/bin/env python3
"""Real Windows events: popup focus, filtering, selection and modal ownership."""
import os
from pathlib import Path
import sys
import tempfile
import time

BASE = Path(__file__).resolve().parents[1] / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def settle(win, seconds=.35):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        win.update()
        time.sleep(.01)


def walk(win):
    yield win
    for child in win.winfo_children():
        yield from walk(child)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    import crm_runtime
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
    fixtures = [('Alpha company', 81601), ('Alpine supplier', 81602), ('Beta company', 81603)]

    def exercise(entry, label):
        entry.set_values(fixtures)
        entry.var.set('')
        entry.winfo_toplevel().focus_force()
        entry.event_generate('<ButtonPress-1>', x=8, y=8)
        entry.event_generate('<ButtonRelease-1>', x=8, y=8)
        settle(window, .7)
        def visible():
            return bool(entry.popup and entry.popup.winfo_viewable())
        assert window.focus_get() is entry and visible(), (
            label, 'click lost focus/popup', str(window.focus_get()),
            str(entry), visible())
        # The real root activation safeguard must never activate a suggestion.
        crm_runtime._raise_dialog_chain(window)
        settle(window)
        assert window.focus_get() is entry and visible(), (label, 'activation stole focus')
        unmapped = []
        token = entry.popup.bind('<Unmap>', lambda e: unmapped.append(str(e.widget)), add='+')
        for key in ('a', 'l'):
            entry.event_generate('<KeyPress>', keysym=key)
            entry.event_generate('<KeyRelease>', keysym=key)
        settle(window)
        assert entry.get() == 'al', (label, entry.get())
        assert list(entry.listbox.get(0, 'end')) == ['Alpha company', 'Alpine supplier']
        assert window.focus_get() is entry and visible(), (label, 'typing lost popup')
        assert entry.popup.winfo_height() >= 50, (label, 'clipped result rows')
        assert not unmapped, (label, 'popup remapped while typing', unmapped)
        entry.popup.unbind('<Unmap>', token)
        entry.event_generate('<Down>')
        settle(window, .1)
        assert entry.listbox.curselection() == (1,), (label, 'arrow selection')
        entry.event_generate('<Return>')
        settle(window)
        assert entry.get() == 'Alpine supplier' and entry.selected_payload == 81602, (
            label, 'Enter ignored selected row', entry.get(), entry.selected_payload)
        assert not visible() and entry.winfo_toplevel().winfo_exists()
        # Reopen, select by real listbox press/release, then continue typing.
        entry.var.set('be')
        settle(window)
        assert visible() and list(entry.listbox.get(0, 'end')) == ['Beta company']
        box = entry.listbox.bbox(0)
        entry.listbox.event_generate('<ButtonPress-1>', x=box[0]+5, y=box[1]+5)
        entry.listbox.event_generate('<ButtonRelease-1>', x=box[0]+5, y=box[1]+5)
        settle(window)
        assert entry.selected_payload == 81603 and not visible(), (label, 'mouse selection')
        entry.var.set('no matching value')
        settle(window)
        assert not visible(), (label, 'empty results')
        entry.var.set('al')
        settle(window)
        assert visible()
        entry.event_generate('<Escape>')
        settle(window)
        assert not visible() and entry.winfo_toplevel().winfo_exists(), (label, 'Escape closed dialog')
        print('Autocomplete OK:', label, flush=True)

    try:
        window.state('normal')
        window.geometry('1250x820+0+0')
        settle(window, 4.2)
        tested = set()
        for page in ('actions', 'projects', 'requests', 'mivo', 'companies', 'people', 'tasks', 'pricelists', 'offers'):
            if page not in window.tabs:
                continue
            window.show_page(page)
            settle(window)
            for entry in tuple(app._AUTOCOMPLETE_ENTRIES):
                if entry not in tested and entry.winfo_ismapped() and entry.winfo_toplevel() is window:
                    exercise(entry, page + ':' + str(entry))
                    tested.add(entry)
        assert tested, 'No main-page autocomplete exercised'
        for cls in (app.PersonDialog, app.TaskDialog, app.RequestDialog, app.ActionDialog):
            dialog = cls(window)
            settle(window, .5)
            entries = [w for w in walk(dialog) if isinstance(w, app.AutocompleteEntry) and w.winfo_ismapped()]
            assert entries, cls.__name__
            # First two visible fields cover shared popup lifecycle with a modal grab.
            for entry in entries[:2]:
                exercise(entry, cls.__name__ + ':' + str(entry))
                assert window.grab_current() is dialog, 'Suggestion changed modal grab'
            # A pending text-change callback must not take focus back after Tab
            # or another field receives it, even if a popup already exists.
            entry = entries[0]
            entry.focus_set()
            settle(window)
            entry.var.set('al')
            other = entries[1] if len(entries) > 1 else dialog
            other.focus_set()
            settle(window)
            assert window.focus_get() is other, (cls.__name__, 'debounce stole focus')
            assert not entry.popup.winfo_viewable(), (cls.__name__, 'old popup stayed open')
            entry.var.set('al')  # destruction with a pending debounce
            dialog.destroy()
            settle(window)
        assert not errors, errors
        print(f'8.0.16 autocomplete: {len(tested)} main fields and four real dialogs OK', flush=True)
    finally:
        window._turto_closing = True
        window.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='turto-autocomplete-', ignore_cleanup_errors=True) as td:
        run(td)
