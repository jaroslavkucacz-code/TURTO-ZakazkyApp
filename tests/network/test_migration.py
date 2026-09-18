"""Read-only source safety and actual PostgreSQL integration (no mock server)."""
from contextlib import closing
from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from network_db import source, migration
from network_db.profile import Profile
from network_db.__main__ import main


def seed(path):
    with closing(sqlite3.connect(path)) as con:
        con.executescript('''
          CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,tab_permissions TEXT);
          CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE companies(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL);
          CREATE TABLE people(id INTEGER PRIMARY KEY,company_id INTEGER REFERENCES companies(id),name TEXT);
          CREATE TABLE projects(id INTEGER PRIMARY KEY,name TEXT);
          CREATE TABLE actions(id INTEGER PRIMARY KEY,project_id INTEGER REFERENCES projects(id),name TEXT);
          CREATE TABLE requests(id INTEGER PRIMARY KEY,action_id INTEGER REFERENCES actions(id),name TEXT);
          CREATE TABLE tasks(id INTEGER PRIMARY KEY,action_id INTEGER REFERENCES actions(id),name TEXT);
          CREATE TABLE lines(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER REFERENCES requests(id),qty REAL,attachment BLOB,note TEXT);
          CREATE TABLE composite(a TEXT,b INTEGER,PRIMARY KEY(a,b));
          CREATE TABLE child(a TEXT,b INTEGER,FOREIGN KEY(a,b) REFERENCES composite(a,b));
          CREATE TABLE duplicates(note TEXT);
          INSERT INTO users VALUES(1,'Čtenář','{"companies":1}');
          INSERT INTO users VALUES(77,'Deleted','{}');
          DELETE FROM users WHERE id=77;
          INSERT INTO companies VALUES(1,'Žluťoučká s.r.o.');
          INSERT INTO people VALUES(1,1,'Jméno');
          INSERT INTO projects VALUES(1,'Projekt');
          INSERT INTO actions VALUES(1,1,'Akce');
          INSERT INTO requests VALUES(1,1,'Poptávka');
          INSERT INTO tasks VALUES(1,1,'Úkol');
          INSERT INTO settings VALUES('key','');
          INSERT INTO composite VALUES('A',1);
          INSERT INTO child VALUES('A',1);
          INSERT INTO duplicates VALUES('stejné'),('stejné'),(NULL);
        ''')
        con.execute('INSERT INTO lines(request_id,qty,attachment,note) VALUES(1,?,?,?)',
                    (1234.123456789, bytes(range(256)), 'Více řádků\nČeský text\t\\'))
        con.commit()


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / 'origin.db'
        seed(self.src)

    def test_wal_snapshot_and_source_unchanged(self):
        with closing(sqlite3.connect(self.src)) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute("UPDATE companies SET name='Nová hodnota ve WAL'")
            con.commit()
            before = [Path(str(self.src) + suffix).read_bytes() for suffix in ('', '-wal')]
            copied = source.snapshot(self.src, self.root / 'snapshot.db')
            after = [Path(str(self.src) + suffix).read_bytes() for suffix in ('', '-wal')]
            self.assertEqual(before, after)
            with closing(source.readonly(copied)) as db:
                self.assertEqual(db.execute('SELECT name FROM companies').fetchone()[0], 'Nová hodnota ve WAL')
            self.assertEqual(len(source.inspect(copied)['tables']), 12)

    def test_snapshot_never_overwrites(self):
        before = self.src.read_bytes()
        for target in (self.src, self.root / 'exists.db'):
            target.write_bytes(before)
            with self.assertRaises((ValueError, FileExistsError)):
                source.snapshot(self.src, target)
            self.assertEqual(target.read_bytes(), before)

    def test_snapshot_missing_source_does_not_create_database(self):
        with self.assertRaises(FileNotFoundError):
            source.snapshot(self.root / 'missing.db', self.root / 'copy.db')
        self.assertFalse((self.root / 'missing.db').exists())
        self.assertFalse((self.root / 'copy.db').exists())

    def test_foreign_key_violation_fails_closed(self):
        with closing(sqlite3.connect(self.src)) as con, con:
            con.execute('UPDATE people SET company_id=999')
        with self.assertRaisesRegex(ValueError, 'vazeb'):
            source.inspect(self.src)

    def test_dynamic_type_mismatch_and_nul_are_rejected(self):
        with closing(sqlite3.connect(self.src)) as con, con:
            con.execute("UPDATE lines SET qty='not a number'")
        with self.assertRaises(ValueError):
            source.inspect(self.src)
        with closing(sqlite3.connect(self.src)) as con, con:
            con.execute('UPDATE lines SET qty=1,note=?', ('text\x00nul',))
        with self.assertRaises(ValueError):
            source.inspect(self.src)

    def test_null_primary_key_is_rejected(self):
        with closing(sqlite3.connect(self.src)) as con, con:
            con.execute('INSERT INTO settings VALUES(NULL,?)', ('no key',))
        with self.assertRaises(ValueError):
            source.inspect(self.src)

    def test_unknown_virtual_and_generated_columns_rejected(self):
        with closing(sqlite3.connect(self.src)) as con:
            con.execute('CREATE VIRTUAL TABLE unexpected USING fts5(text)')
        with self.assertRaises(ValueError):
            source.inspect(self.src)
        with closing(sqlite3.connect(self.src)) as con:
            con.execute('DROP TABLE unexpected')
            con.execute('ALTER TABLE lines ADD COLUMN generated REAL AS (qty*2)')
        with self.assertRaises(ValueError):
            source.inspect(self.src)

    def test_digest_is_order_independent_but_checks_duplicates_and_blobs(self):
        columns = [{'name': 'value', 'type': 'BLOB', 'pk': 0, 'notnull': 0}]
        a = source.content_digest([(b'abc',), (b'def',), (None,)], columns)
        self.assertEqual(a, source.content_digest([(None,), (b'def',), (b'abc',)], columns))
        self.assertNotEqual(a, source.content_digest([(None,), (b'def',), (b'abd',)], columns))
        self.assertNotEqual(a, source.content_digest([(None,), (b'def',), (b'abc',), (b'abc',)], columns))

    def test_profiles_reject_cleartext_remote_and_embedded_password(self):
        with self.assertRaises(ValueError):
            Profile('server', 'db', 'user', sslmode='disable')
        for port in (True, 0, 65536, '5432'):
            with self.assertRaises(ValueError):
                Profile('server', 'db', 'user', port=port)
        p = self.root / 'profile.json'
        p.write_text(json.dumps({'host': 'server', 'dbname': 'db', 'user': 'user', 'password': 'secret'}))
        with self.assertRaises(ValueError):
            Profile.load(p)
        self.assertNotIn('password', Profile('server', 'db', 'user').public())

    def test_backup_environment_ignores_ambient_redirect(self):
        with patch.dict(os.environ, {'PGSERVICE': 'other-db', 'PGHOSTADDR': '10.0.0.9',
                                     'PGPASSWORD': 'ambient', 'TURTO_PG_PASSWORD': 'wanted'}):
            env = Profile('server', 'db', 'user').process_env()
        self.assertNotIn('PGSERVICE', env)
        self.assertNotIn('PGHOSTADDR', env)
        self.assertEqual(env['PGPASSWORD'], 'wanted')

    def test_cli_does_not_overwrite_source_with_report(self):
        before = self.src.read_bytes()
        with patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(main(['inspect', '--source', str(self.src), '--report', str(self.src)]), 1)
        self.assertEqual(before, self.src.read_bytes())

    def test_overlong_identifiers_rejected(self):
        with closing(sqlite3.connect(self.src)) as con:
            con.execute('CREATE TABLE ' + ('a' * 64) + '(id INTEGER)')
        with self.assertRaises(ValueError):
            source.inspect(self.src)

    def test_schema_names_restricted_to_pilot(self):
        for name in ('public', 'turto', 'turto_pilot_', 'turto_pilot_x;DROP SCHEMA public'):
            with self.assertRaises(ValueError):
                migration.schema_name(name)


PG = bool(os.environ.get('TURTO_TEST_POSTGRES'))


@unittest.skipUnless(PG, 'Set TURTO_TEST_POSTGRES=1 to run against actual PostgreSQL')
class PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = Profile('127.0.0.1', os.environ.get('TURTO_TEST_PG_DATABASE', 'turto_pilot_test'),
                              os.environ.get('TURTO_TEST_PG_USER', 'postgres'),
                              port=int(os.environ.get('TURTO_TEST_PG_PORT', '5432')), sslmode='disable')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'source.db'
        seed(self.src)
        self.schema = 'turto_pilot_test_' + uuid.uuid4().hex[:12]
        self.addCleanup(self.drop_schema)

    def drop_schema(self):
        from psycopg import sql
        with self.profile.connect() as pg:
            pg.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(self.schema)))

    def exists(self):
        with self.profile.connect() as pg:
            return bool(pg.execute('SELECT 1 FROM pg_namespace WHERE nspname=%s', (self.schema,)).fetchone())

    def test_copy_roundtrip_binary_unicode_duplicates_and_sequences(self):
        manifest = migration.migrate(self.src, self.profile, self.schema)
        self.assertFalse(manifest['application_ready'])
        self.assertTrue(migration.verify(self.profile, self.schema)['ok'])
        with self.profile.connect() as pg:
            next_id = pg.execute(f'INSERT INTO {self.schema}.users(name) VALUES(%s) RETURNING id', ('nový',)).fetchone()[0]
            self.assertEqual(next_id, 78)  # Deleted IDs must not be recycled.
        self.assertFalse(migration.verify(self.profile, self.schema)['ok'])

    def test_existing_schema_is_never_reused_or_overwritten(self):
        migration.migrate(self.src, self.profile, self.schema)
        with self.assertRaises(ValueError):
            migration.migrate(self.src, self.profile, self.schema)
        self.assertTrue(migration.verify(self.profile, self.schema)['ok'])

    def test_target_failure_rolls_back_entire_schema(self):
        original = migration.content_digest
        calls = []
        def mismatch(rows, columns):
            value = original(rows, columns)
            calls.append(value)
            if len(calls) > 12:  # First PostgreSQL verification after source preflight.
                value['sha256'] = 'wrong'
            return value
        with patch.object(migration, 'content_digest', side_effect=mismatch):
            with self.assertRaisesRegex(ValueError, 'neshoduje'):
                migration.migrate(self.src, self.profile, self.schema)
        self.assertFalse(self.exists())
        self.assertTrue(source.inspect(self.src)['tables'])

    def test_constraints_remain_enforced(self):
        import psycopg
        migration.migrate(self.src, self.profile, self.schema)
        with self.profile.connect() as pg:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                pg.execute(f'UPDATE {self.schema}.people SET company_id=999')
            with self.assertRaises(psycopg.errors.UniqueViolation):
                pg.execute(f"INSERT INTO {self.schema}.composite VALUES('A',1)")
        self.assertTrue(migration.verify(self.profile, self.schema)['ok'])

    def test_two_migrators_cannot_clobber_same_schema(self):
        from concurrent.futures import ThreadPoolExecutor
        def run():
            try:
                migration.migrate(self.src, self.profile, self.schema)
                return 'ok'
            except ValueError:
                return 'exists'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(lambda _: run(), range(2))), ['exists', 'ok'])
        self.assertTrue(migration.verify(self.profile, self.schema)['ok'])

    def test_cli_connection_failure_is_redacted_and_source_unchanged(self):
        profile_file = Path(self.tmp.name) / 'profile.json'
        profile_file.write_text(json.dumps(self.profile.public()))
        before = self.src.read_bytes()
        import psycopg
        with patch.object(Profile, 'connect', side_effect=psycopg.OperationalError('password=SECRET')), \
             patch('sys.stderr', new_callable=io.StringIO) as stderr:
            result = main(['migrate', '--source', str(self.src), '--profile', str(profile_file),
                           '--schema', self.schema, '--report', str(Path(self.tmp.name) / 'report.json')])
        self.assertEqual(result, 1)
        self.assertNotIn('SECRET', stderr.getvalue())
        self.assertEqual(self.src.read_bytes(), before)
        self.assertFalse(self.exists())

    def test_custom_backup_restores_to_separate_database(self):
        from psycopg import sql
        from network_db.backup import backup
        migration.migrate(self.src, self.profile, self.schema)
        dump = backup(self.profile, self.schema, Path(self.tmp.name) / 'test.dump')
        restored_db = 'turto_restore_' + uuid.uuid4().hex[:10]
        with self.profile.connect() as pg:
            pg.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_db)))
        try:
            restored = replace(self.profile, dbname=restored_db)
            result = subprocess.run(['pg_restore', '--no-password', '--exit-on-error', '--single-transaction',
                                     '--no-owner', '--no-privileges', '--dbname=' + restored_db, str(dump)],
                                    env=restored.process_env(), capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertTrue(migration.verify(restored, self.schema)['ok'])
            with self.assertRaises(ValueError):
                backup(self.profile, self.schema, dump)
        finally:
            with self.profile.connect() as pg:
                pg.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restored_db)))

    def test_full_current_crm_schema_with_real_business_records(self):
        fixture = Path(self.tmp.name) / 'crm'
        spec = importlib.util.spec_from_file_location('validate834', REPO / 'scripts/validate-834-user-access.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app, _ = mod.prepare(str(fixture))
        records = mod.seed(app)
        # Include embedded binary assets and a high-precision offer amount.
        with closing(app.db()) as con, con:
            con.execute('UPDATE supplier_offer_items SET image_blob=?,quantity=?,net_price=? WHERE id=?',
                        (bytes(range(256)) * 32, 12.75, 12345.678901, records['item']))
        copied = source.snapshot(app.DB, Path(self.tmp.name) / 'full.db')
        manifest = migration.migrate(copied, self.profile, self.schema)
        self.assertGreaterEqual(len(manifest['tables']), 50)
        self.assertIn('price_list_items_fts', manifest['excluded_derived_tables'])
        self.assertTrue(any(o['type'] == 'trigger' for o in manifest['source_schema']))
        self.assertTrue(migration.verify(self.profile, self.schema)['ok'])
        self.assertEqual(source.inspect(copied)['source_schema'], manifest['source_schema'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
