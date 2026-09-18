"""Validate the shipped demonstration with its own DB and actual Tk widgets."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo-smoke-test', action='store_true')
    parser.add_argument('--report', required=True)
    parser.add_argument('--wait-for-termination', action='store_true')
    args = parser.parse_args()
    if os.environ.get('TURTO_TEST_LOCAL_DEMO') != '1':
        raise ValueError('Automatická zkouška místní ukázky je určena jen pro CI.')
    import tkinter as tk
    from tkinter import messagebox
    from .client import AccessDenied
    from .local_demo_ui import DemoApplication
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda kind, value, tb: errors.append(kind.__name__)
    messagebox.showerror = lambda *a, **kw: errors.append('error_dialog')
    result = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False))}
    app = DemoApplication(root)
    def settle():
        deadline = time.monotonic() + 150
        while True:
            root.update()
            if app.error or errors:
                raise AssertionError('UI preparation or callback failed: ' + str(app.error or errors))
            if app.ready and app.windows and not any(win.busy for win in app.windows):
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('Local demonstration did not finish')
            time.sleep(0.02)
    report = Path(args.report)
    try:
        settle()
        session = app.session
        assert session.profiles['editor1'].dbname == 'turto_local_demo'
        with session.profiles['editor1'].connect() as con:
            assert con.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1'
            assert con.execute('SELECT host(inet_server_addr())').fetchone()[0] == '127.0.0.1'
            assert con.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0] is False
        hba = (session.cluster / 'pg_hba.conf').read_text()
        assert hba == 'host all all 127.0.0.1/32 scram-sha-256\n'
        assert not (session.folder / 'initial-password.txt').exists()
        if args.wait_for_termination:
            pending = report.with_suffix('.pending')
            pending.write_text(json.dumps({'ready': True, 'port': session.port, 'pid': session.server_pid}), encoding='utf-8')
            pending.replace(report)
            root.mainloop()  # Parent CI deliberately kills this process to verify OS child cleanup.
            return 1
        first = next(iter(app.windows))
        assert first.identity['companies'] == 2
        first.new_button.invoke(); root.update()
        first.editor.variables['official_name'].set('Místní ukázka – ověřená společnost')
        first.editor.save_button.invoke(); settle()
        first.query.set('Místní ukázka – ověřená společnost'); first.refresh_button.invoke(); settle()
        cid = int(first.tree.get_children()[0])
        first.demo_window_button.invoke(); settle()
        second = next(win for win in app.windows if win is not first)
        def select(win):
            win.query.set('Místní ukázka – ověřená společnost'); win.refresh_button.invoke(); settle()
            win.tree.selection_set(str(cid)); root.update(); win.open_button.invoke(); settle()
        select(first); select(second)
        first.editor.note.insert('end', 'Změna prvního editora')
        first.editor.save_button.invoke(); settle()
        second.editor.note.insert('end', 'Tuto zastaralou úpravu nesmí přepsat')
        second.editor.save_button.invoke(); settle()
        assert 'jiný uživatel' in second.editor.status.get()
        assert second.editor.winfo_exists()
        assert second.client.company(cid)['company']['note'] == 'Změna prvního editora'
        second.editor.close()
        assert len(first.client.history(cid)) == 2
        first.tree.selection_set(str(cid)); root.update()
        first.history_button.invoke(); settle()
        histories = [w for w in first.winfo_children() if isinstance(w, tk.Toplevel) and 'Historie' in w.title()]
        assert len(histories) == 1; histories[0].destroy()
        reader_button = next(button for button, role in second.demo_buttons if role == 'reader')
        reader_button.invoke(); settle()
        assert second.identity['companies'] == 1 and second.new_button.instate(['disabled'])
        select(second)
        assert second.editor.save_button.instate(['disabled'])
        try:
            second.client.save(cid, 2, {'note': 'Must be rejected by server'})
        except AccessDenied:
            pass
        else:
            raise AssertionError('Reader API write was accepted')
        second.editor.close()
        from PIL import ImageGrab
        root.update(); ImageGrab.grab().save(str(report.with_suffix('.png')))
        folder, port = session.folder, session.port
        second.close(); root.update()
        assert first.client.company(cid)['company']['network_revision'] == 2
        first.close(); root.update()
        app.stop()
        assert not folder.exists()
        with socket.socket() as probe:
            probe.settimeout(2)
            assert probe.connect_ex(('127.0.0.1', port)) != 0
        assert not errors, errors
        result.update(ok=True, editor=True, reader=True, concurrent_conflict=True, history=True,
                      graceful_stop=True, temporary_data_removed=True, loopback_only=True)
    except Exception as exc:
        result.update(error_type=type(exc).__name__, phase=app.session.phase)
        result['failure_location'] = [f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
            for frame in traceback.extract_tb(exc.__traceback__)]
        if isinstance(exc, AssertionError):
            result['assertion'] = str(exc)
        if app.session.failure_log:
            result['startup_log'] = app.session.failure_log
        # Test-only diagnostic avoids connection strings/passwords.
        result['callback_errors'] = errors
    finally:
        try: app.stop()
        except Exception: result.update(ok=False, cleanup_error=True)
        root.destroy()
        if not args.wait_for_termination:
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
