#!/usr/bin/env python3
"""Background checks must never download, close CRM or start installation."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

BASE = Path(sys.argv.pop(1) if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else 'ZakazkyApp_base_6.1').resolve()


def load_module(root=BASE):
    spec = importlib.util.spec_from_file_location('updates_test', root / 'price_lists_domain/platform/automatic_updates.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpdateIntentTests(unittest.TestCase):
    def setUp(self):
        self.u = load_module()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.package = self.root / 'update.zip'
        self.package.write_bytes(b'PK-test')
        (self.root / 'crm_updater.pyw').write_text('# fixture')
        self.main_thread = threading.get_ident()
        test = self

        class FakeApp:
            def __init__(self):
                self.delayed = []
                self.closed = False
            def after(self, delay, callback):
                test.assertEqual(threading.get_ident(), test.main_thread, 'Worker called Tk.after')
                self.delayed.append((delay, callback))
            def winfo_exists(self):
                return not self.closed
            def close_app(self):
                self.closed = self._turto_closing = True
            def title(self, *_):
                pass
            def configure(self, **_):
                pass

        self.M = types.SimpleNamespace(App=FakeApp, ROOT=self.root, DATA_ROOT=self.root / 'data',
            APP_VERSION='8.0.11', messagebox=mock.Mock(), set_setting=mock.Mock(),
            _download_update_package=mock.Mock(return_value=self.package))
        self.manifest = {'version': '8.0.12', 'notes': 'Oprava aktualizací'}
        self.u._read_official_manifest = mock.Mock(return_value=self.manifest)
        self.u._show_available_update = mock.Mock()
        self.u._show_update_offer = mock.Mock()
        self.progress = mock.Mock()
        self.u._new_progress_window = mock.Mock(return_value=self.progress)
        self.popen = mock.patch.object(self.u.subprocess, 'Popen', return_value=types.SimpleNamespace(pid=1234))
        self.spawn = self.popen.start()
        self.addCleanup(self.popen.stop)
        env = mock.patch.dict(self.u.os.environ, {'TURTO_DISABLE_AUTO_UPDATE': ''})
        env.start()
        self.addCleanup(env.stop)
        self.u.install(self.M)
        self.app = self.M.App()

    def pump(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            pending, self.app.delayed = self.app.delayed, []
            for delay, callback in pending:
                if delay < 500:
                    callback()
                else:
                    self.app.delayed.append((delay, callback))
            if predicate():
                return
            time.sleep(.005)
        self.fail('Timed out waiting for update state')

    def check(self, silent=True):
        self.assertTrue(self.app.check_for_updates(silent=silent))
        self.pump(lambda: not self.app._turto_auto_update_running)

    def assert_no_install(self):
        self.M._download_update_package.assert_not_called()
        self.spawn.assert_not_called()
        self.assertFalse(self.app.closed)

    def test_startup_and_periodic_checks_only_publish_available_version(self):
        callbacks = dict(self.app.delayed)
        self.assertIn(self.u._PERIODIC_CHECK_MS, callbacks)
        callbacks[900]()
        self.pump(lambda: not self.app._turto_auto_update_running)
        self.assertEqual(self.app._turto_available_update, self.manifest)
        self.u._show_available_update.assert_called_once()
        self.u._show_update_offer.assert_not_called()
        self.app._turto_auto_update_last_check = 0
        callbacks[self.u._PERIODIC_CHECK_MS]()
        self.pump(lambda: not self.app._turto_auto_update_running)
        self.assert_no_install()
        self.M.messagebox.showinfo.assert_not_called()

    def test_manual_check_offers_then_only_button_downloads_and_closes(self):
        self.check(silent=False)
        self.u._show_update_offer.assert_called_once()
        self.assert_no_install()
        self.assertTrue(self.app.install_available_update())
        self.assertFalse(self.app.install_available_update(), 'Double click started a second install')
        self.pump(lambda: self.app.closed)
        self.M._download_update_package.assert_called_once_with(self.manifest)
        self.spawn.assert_called_once()
        self.assertEqual(self.spawn.call_args.args[0][2], str(self.package))
        self.M.set_setting.assert_any_call('pending_update', '8.0.12')
        self.progress.report.assert_called()

    def test_manual_check_is_visible_even_during_background_request(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.u._read_official_manifest.side_effect = lambda: (gate.wait(3), self.manifest)[1]
        self.assertTrue(self.app.check_for_updates(silent=True))
        self.assertFalse(self.app.check_for_updates())
        gate.set()
        self.pump(lambda: not self.app._turto_auto_update_running)
        self.u._show_update_offer.assert_called_once()
        self.assert_no_install()

    def test_current_version_and_manual_debounce(self):
        self.u._read_official_manifest.return_value = {'version': '8.0.11'}
        self.app._turto_auto_update_last_check = time.monotonic()
        self.check(silent=False)
        self.M.messagebox.showinfo.assert_called_once()
        self.assertIsNone(self.app._turto_available_update)
        self.assert_no_install()

    def test_failure_does_not_install_or_retry_on_periodic_check(self):
        self.check()
        self.M._download_update_package.side_effect = OSError('offline')
        self.app.install_available_update()
        self.pump(lambda: not self.app._turto_update_installing)
        self.progress.fail.assert_called_once()
        self.spawn.assert_not_called()
        self.assertFalse(self.app.closed)
        self.app._turto_auto_update_last_check = 0
        self.check()
        self.assertEqual(self.M._download_update_package.call_count, 1)

    def test_background_network_error_keeps_previous_offer_without_popup(self):
        self.check()
        self.u._read_official_manifest.side_effect = OSError('offline')
        self.app._turto_auto_update_last_check = 0
        self.check()
        self.assertEqual(self.app._turto_available_update, self.manifest)
        self.M.messagebox.showerror.assert_not_called()
        self.assert_no_install()

    def test_closing_during_download_never_launches_updater(self):
        self.check()
        gate = threading.Event()
        finished = threading.Event()
        self.addCleanup(gate.set)
        def download(_):
            gate.wait(3)
            finished.set()
            return self.package
        self.M._download_update_package.side_effect = download
        self.app.install_available_update()
        self.app.close_app()
        gate.set()
        self.assertTrue(finished.wait(3))
        self.pump(lambda: True)
        self.spawn.assert_not_called()

    def test_disabled_checks_never_access_network(self):
        with mock.patch.dict(self.u.os.environ, {'TURTO_DISABLE_AUTO_UPDATE': '1'}):
            self.assertFalse(self.app.check_for_updates(silent=True))
        self.u._read_official_manifest.assert_not_called()
        self.assert_no_install()


if __name__ == '__main__':
    unittest.main(verbosity=2)
