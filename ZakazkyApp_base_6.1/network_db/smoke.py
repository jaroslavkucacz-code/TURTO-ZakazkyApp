"""Explicit CI-only interaction with the actual frozen Tk executable."""
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4


def run(config, report):
    from . import settings
    profile, schema = settings.load(config)
    if not schema.startswith('turto_pilot_ci_') or not profile.dbname.startswith('turto_pilot_test'):
        raise ValueError('Automatická zkouška je povolena jen v samostatné CI databázi a schématu.')
    password = os.environ['TURTO_PILOT_TEST_PASSWORD']
    result = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False))}
    import tkinter as tk
    from tkinter import messagebox
    from .ui import open_pilot
    from .connection_ui import ConnectionDialog
    root = tk.Tk(); root.withdraw()
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(kind.__name__)
    def unexpected(*args, **kwargs):
        raise AssertionError('Unexpected error dialog')
    messagebox.showerror = unexpected
    win = open_pilot(root)
    def settle():
        deadline = time.monotonic() + 40
        while True:
            root.update()
            if not win.busy:
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Network UI did not finish')
            time.sleep(0.02)
    def select(cid):
        win.tree.selection_set(str(cid)); root.update()
        win.open_button.invoke(); settle()
        assert win.editor.winfo_exists()
        return win.editor
    try:
        # Use the same form shipped to users, including certificate selection,
        # persistent choices and the separate password-only login step.
        dialog = ConnectionDialog(win); root.update()
        for key, var in dialog.variables.items():
            var.set(schema if key == 'schema' else str(getattr(profile, key)))
        dialog.save_button.invoke(); root.update()
        assert not dialog.winfo_exists()
        stored = settings.default_path().read_text(encoding='utf-8')
        assert password not in stored and '"password"' not in stored
        win.password.set(password); win.connect_button.invoke(); settle()
        assert win.identity and win.password.get() == ''
        with profile.connect(password=password) as con:
            assert con.pgconn.ssl_in_use, 'Frozen client must verify an actual TLS server'
        if win.identity['companies'] == 2:
            name = 'Pilot EXE ' + uuid4().hex[:10]
            win.new_button.invoke(); root.update()
            win.editor.variables['official_name'].set(name)
            win.editor.save_button.invoke(); settle()
            win.query.set(name); win.refresh_button.invoke(); settle()
            ids = win.tree.get_children(); assert len(ids) == 1
            editor = select(ids[0])
            editor.note.insert('end', 'Ověřeno ve Windows EXE přes TLS.')
            editor.save_button.invoke(); settle()
            row = win.client.company(int(ids[0]))['company']
            assert row['network_revision'] == 2
            assert row['note'] == 'Ověřeno ve Windows EXE přes TLS.'
            history = win.client.history(row['id']); assert len(history) == 2
            win.tree.selection_set(str(row['id'])); root.update()
            win.history_button.invoke(); settle()
            history_windows = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel) and 'Historie' in w.title()]
            assert len(history_windows) == 1
            history_windows[0].destroy()
            result.update(company_id=row['id'], revision=2, history_count=2, permission='edit')
        else:
            assert win.identity['companies'] == 1 and win.new_button.instate(['disabled'])
            cid = win.tree.get_children()[0]
            editor = select(cid)
            assert editor.save_button.instate(['disabled'])
            editor.close()
            result['permission'] = 'read'
        from PIL import ImageGrab
        root.update(); ImageGrab.grab().save(str(Path(report).with_suffix('.png')))
        win.disconnect_button.invoke(); root.update()
        assert win.client is None
        assert not errors, errors
        result['ok'] = True
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        # No credentials or connection strings in machine-readable build output.
        if win.busy:
            try: settle()
            except Exception: pass
        root.destroy()
        if errors:
            result.update(ok=False, callback_errors=errors)
        with Path(report).open('x', encoding='utf-8') as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
    return 0 if result['ok'] else 1
