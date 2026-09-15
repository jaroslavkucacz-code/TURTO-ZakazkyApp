#!/usr/bin/env python3
"""Keep the old CI entry point on the current verified onedir/handshake contract.

The 8.0.7 fixture expected a single EXE and deletion of its stage on startup.
Since 8.0.8 a verified runtime and its receipt must persist, including after a
blocked launch. Run the current behavioral suite instead of those retired
expectations, retaining the separate legacy TEMP cleanup regression below.
"""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('staging_current', Path(__file__).with_name('validate-808-updater.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
UpdaterSafetyTests = base.UpdaterSafetyTests


class LegacyCleanupTests(unittest.TestCase):
    def test_only_stale_legacy_temp_copies_are_removed(self):
        with tempfile.TemporaryDirectory(prefix='turto-legacy-stage-test-') as td:
            root = Path(td)
            old, recent = root / 'turto_crm_updater_old', root / 'turto_crm_updater_recent'
            for path in (old, recent):
                path.mkdir()
                (path / base.safety.UPDATER_EXE).write_bytes(b'legacy')
            now = time.time()
            os.utime(old, (now - 3600, now - 3600))
            with mock.patch.object(base.policy.tempfile, 'gettempdir', return_value=td):
                removed = base.policy._cleanup_stale_legacy_updaters(now=now)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(removed, [str(old)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
