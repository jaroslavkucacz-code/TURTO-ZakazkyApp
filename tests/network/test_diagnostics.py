"""Observable startup reports and real loopback probes, without company access."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ZakazkyApp_base_6.1'))
from network_db.diagnostics import check_network, probe, save_report
from network_db.local_demo import LocalDemo, LocalDemoError


class DiagnosticsTests(unittest.TestCase):
    def test_actual_open_closed_and_invalid_tcp_endpoint(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0)); server.listen()
            port = server.getsockname()[1]
            self.assertTrue(probe('127.0.0.1', port)['reachable'])
        self.assertFalse(probe('127.0.0.1', port)['reachable'])
        for host, number in [('\\\\192.168.8.240\\turto', 5432), ('', 5432), ('localhost', 65536)]:
            with self.assertRaises(ValueError): check_network(host, number)

    def test_original_failure_survives_cleanup_and_passwords_are_redacted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LOCALAPPDATA=tmp):
            session = LocalDemo()
            session.folder = Path(tmp) / 'session'; session.folder.mkdir()
            secret = 'generated-demo-secret-that-must-not-appear'
            session._secrets.append(secret)
            (session.folder / 'startup.log').write_text('Startup\n' + 'x' * 100 + secret + 'y' * 5980)
            original = LocalDemoError('initdb detail ' + secret, 'initdb.exe', 7)
            with patch.object(session, '_start', side_effect=original), patch.object(session, 'stop', side_effect=OSError('cleanup')):
                with self.assertRaises(LocalDemoError) as result: session.start()
            self.assertIs(result.exception, original)
            report = json.loads(session.report_path.read_text(encoding='utf-8'))
            self.assertEqual(report['returncode'], 7)
            self.assertEqual(report['cleanup_error_type'], 'OSError')
            self.assertNotIn(secret, json.dumps(report))
            self.assertNotIn(secret[-15:], report['startup_log'])
            self.assertIn('[HESLO VYNECHÁNO]', report['message'])

    def test_report_files_do_not_overwrite_previous_result(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LOCALAPPDATA=tmp):
            first = save_report({'attempt': 1}, 'pripojeni')
            second = save_report({'attempt': 2}, 'pripojeni')
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text()), {'attempt': 1})

    @unittest.skipUnless(os.environ.get('TURTO_TEST_UI') == '1', 'Requires display')
    def test_real_tk_check_and_copy_without_database_credentials(self):
        import tkinter as tk
        from network_db.network_check_ui import NetworkCheck
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LOCALAPPDATA=tmp), socket.socket() as server:
            server.bind(('127.0.0.1', 0)); server.listen()
            root = tk.Tk(); app = NetworkCheck(root)
            try:
                app.host.set('127.0.0.1'); app.port.set(str(server.getsockname()[1]))
                app.run_button.invoke()
                deadline = time.monotonic() + 15
                while app.report is None:
                    root.update()
                    if time.monotonic() >= deadline: self.fail('Network check UI timed out')
                    time.sleep(0.02)
                self.assertTrue(app.report['database_tcp']['reachable'])
                app.copy_button.invoke(); root.update()
                self.assertEqual(json.loads(root.clipboard_get()), app.report)
                self.assertTrue(list(Path(tmp).rglob('pripojeni-*.json')))
            finally:
                root.destroy()


if __name__ == '__main__': unittest.main(verbosity=2)
