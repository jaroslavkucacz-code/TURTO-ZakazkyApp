#!/usr/bin/env python3
"""Restart visibility and whole-transaction phase/error regressions."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import zipfile

spec = importlib.util.spec_from_file_location('base812', Path(__file__).with_name('validate-808-updater.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
u, s = base.updater, base.safety


class ProgressTests(unittest.TestCase):
    setUp = base.UpdaterSafetyTests.setUp

    def test_restart_waits_for_mapped_window(self):
        process = mock.Mock(pid=456, poll=mock.Mock(return_value=None))
        with mock.patch.dict(os.environ, {'TURTO_CRM_SMOKE_RESULT': ''}), mock.patch.object(u, '_has_visible_window', side_effect=[False, False, True]) as visible, mock.patch.object(u.time, 'sleep'):
            u._wait_for_restart(process)
        self.assertEqual(visible.call_count, 3)
        process.terminate.assert_not_called()

    def test_restart_exit_and_timeout_are_reported_without_killing(self):
        for code, timeout in ((1, 10), (None, 0)):
            with self.subTest(code=code):
                process = mock.Mock(poll=mock.Mock(return_value=code))
                with mock.patch.dict(os.environ, {'TURTO_CRM_SMOKE_RESULT': ''}):
                    with self.assertRaises(RuntimeError):
                        u._wait_for_restart(process, timeout)
                process.terminate.assert_not_called()
                process.kill.assert_not_called()

    def run_transaction(self, restart_wait):
        package = self.root / 'update.zip'
        with zipfile.ZipFile(package, 'w') as archive:
            for path in self.new.rglob('*'):
                if path.is_file():
                    archive.write(path, Path('payload') / path.relative_to(self.new))
        args = ['updater', '--install', str(package), str(self.old), '0', 'update', '8.0.8', s.digest(package)]
        events = []
        with mock.patch.object(sys, 'argv', args), mock.patch.object(u, '_database_backup', return_value=None), mock.patch.object(u, '_restart', return_value=mock.Mock()), mock.patch.object(u, '_wait_for_restart', side_effect=restart_wait), mock.patch.object(u, '_restore_program_snapshot') as restore:
            try:
                u.main(lambda stage, *args, **kwargs: events.append(stage))
            finally:
                restore.assert_not_called()
                u._PROGRESS = None
        return events

    def test_real_transaction_reports_backup_install_and_restart_in_order(self):
        events = self.run_transaction(None)
        expected = ['Čekám na bezpečné uzavření CRM…', 'Zálohuji databázi…',
                    'Zálohuji původní verzi programu…', 'Instaluji novou verzi…', 'Spouštím TURTO CRM…']
        positions = [events.index(stage) for stage in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(u._validate_release(self.old, installed=True), '8.0.8')
        self.assertEqual((self.root / 'data/zakazky.db').read_bytes(), b'business-data-sentinel')

    def test_restart_visibility_failure_does_not_replace_live_program(self):
        with self.assertRaisesRegex(RuntimeError, 'still starting'):
            self.run_transaction(RuntimeError('still starting'))
        self.assertEqual(u._validate_release(self.old, installed=True), '8.0.8')
        self.assertEqual((self.root / 'data/zakazky.db').read_bytes(), b'business-data-sentinel')


if __name__ == '__main__':
    unittest.main(verbosity=2)
