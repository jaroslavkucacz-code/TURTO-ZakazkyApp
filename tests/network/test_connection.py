"""Persistent endpoint, transport failures and TLS rules for office/VPN use."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from network_db import settings
from network_db.profile import Profile
from network_db.client import DirectoryClient, ConnectionUnavailable, UncertainWrite


class ConnectionTests(unittest.TestCase):
    def test_saved_endpoint_and_schema_roundtrip_without_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'connection.json'
            profile = Profile('crm.example.test', 'turto_crm_pilot', 'jana', sslrootcert=str(Path(tmp) / 'ca.pem'))
            settings.save(path, profile, 'turto_pilot_prvni')
            self.assertEqual(settings.load(path), (profile, 'turto_pilot_prvni'))
            settings.save(path, replace(profile, user='petr'), 'turto_pilot_druhy')
            self.assertEqual(settings.load(path)[0].user, 'petr')
            self.assertEqual(settings.load(path)[1], 'turto_pilot_druhy')
            self.assertNotIn('password', json.loads(path.read_text())['profile'])
            self.assertFalse(list(Path(tmp).glob('.connection-*')))

    def test_profile_import_resolves_public_ca_relative_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'profile.json'
            path.write_text(json.dumps(Profile('crm.example.test', 'pilot', 'jana', sslrootcert='ca.pem').public()))
            self.assertEqual(settings.load(path)[0].sslrootcert, str((Path(tmp) / 'ca.pem').resolve()))

    def test_profile_secrets_unknown_fields_and_unsafe_remote_tls_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'connection.json'
            p = Profile('crm.example.test', 'pilot', 'jana').public()
            for extra in ({'password': 'must-not-save'}, {'sslmode': 'disable'}):
                path.write_text(json.dumps({'format': settings.FORMAT, 'schema': 'turto_pilot_test', 'profile': p | extra}))
                with self.assertRaises(ValueError):
                    settings.load(path)

    def test_write_not_submitted_when_connection_fails(self):
        import psycopg
        client = DirectoryClient(Profile('127.0.0.1', 'pilot', 'jana', sslmode='disable'), 'turto_pilot_test', password='secret')
        with patch.object(Profile, 'connect', side_effect=psycopg.OperationalError('DO-NOT-EXPOSE secret')):
            with self.assertRaises(ConnectionUnavailable) as error:
                client.save(None, 0, {'official_name': 'Firma'})
            self.assertNotIn('secret', str(error.exception))
            self.assertIn('VPN', str(error.exception))
            self.assertNotIsInstance(error.exception, UncertainWrite)

    def test_atomic_settings_failure_keeps_previous_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'connection.json'
            profile = Profile('crm.example.test', 'pilot', 'jana')
            settings.save(path, profile, 'turto_pilot_prvni')
            with patch('os.replace', side_effect=OSError('disk error')), self.assertRaises(OSError):
                settings.save(path, replace(profile, user='petr'), 'turto_pilot_prvni')
            self.assertEqual(settings.load(path)[0].user, 'jana')
            self.assertFalse(list(Path(tmp).glob('.connection-*')))

    def test_windows_bom_and_interactive_password_do_not_mutate_environment(self):
        from network_db.__main__ import _InteractiveProfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'admin.json'
            profile = Profile('crm.example.test', 'pilot', 'admin')
            path.write_text(json.dumps(profile.public()), encoding='utf-8-sig')
            self.assertEqual(settings.load(path)[0], profile)
            before = dict(os.environ)
            prompted = _InteractiveProfile(profile, 'entered-only-in-prompt')
            with patch.object(Profile, 'connect') as connect:
                prompted.connect()
                connect.assert_called_once_with(password='entered-only-in-prompt')
            self.assertEqual(prompted.process_env()['PGPASSWORD'], 'entered-only-in-prompt')
            self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
