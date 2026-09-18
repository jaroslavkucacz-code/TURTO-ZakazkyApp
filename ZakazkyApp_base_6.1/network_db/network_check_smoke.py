"""CI-only verification of the actual frozen connectivity window."""
import json
import os
from pathlib import Path
import socket
import sys
import time


def main(report_path):
    if os.environ.get('TURTO_TEST_LOCAL_DEMO') != '1':
        raise ValueError('Tato automatická zkouška je určena jen pro CI.')
    import tkinter as tk
    from .network_check_ui import NetworkCheck
    root = tk.Tk(); app = NetworkCheck(root)
    result = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False))}
    def settle():
        deadline = time.monotonic() + 15
        while app.run_button.instate(['disabled']):
            root.update()
            if time.monotonic() > deadline: raise TimeoutError('Network check did not finish')
            time.sleep(0.02)
    try:
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0)); server.listen()
            app.host.set('127.0.0.1'); app.port.set(str(server.getsockname()[1]))
            app.run_button.invoke(); settle()
            assert app.report['database_tcp']['reachable']
            app.copy_button.invoke(); root.update()
            assert json.loads(root.clipboard_get()) == app.report
        app.run_button.invoke(); settle()
        assert not app.report['database_tcp']['reachable']
        assert 'nedostupný' in app.text.get('1.0', 'end')
        app.host.set('\\\\192.168.8.240\\turto'); app.run_button.invoke(); settle()
        assert app.report is None and app.copy_button.instate(['disabled'])
        result.update(ok=True, open_closed_ports=True, copy=True, invalid_path_rejected=True)
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    finally:
        root.destroy()
        Path(report_path).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1
