"""Actual personal logins, server authorization, concurrent edits and native Tk."""
from contextlib import closing
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from network_db.profile import Profile
from network_db import directory, migration, source
from network_db.client import DirectoryClient, AccessDenied, Conflict, DirectoryError, UncertainWrite


@unittest.skipUnless(os.environ.get('TURTO_TEST_POSTGRES'), 'Actual PostgreSQL required')
class DirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.profile = Profile('127.0.0.1', os.environ.get('TURTO_TEST_PG_DATABASE', 'turto_pilot_test'),
                              os.environ.get('TURTO_TEST_PG_USER', 'postgres'),
                              port=int(os.environ.get('TURTO_TEST_PG_PORT', '5432')), sslmode='disable')
        spec = importlib.util.spec_from_file_location('validate834', REPO / 'scripts/validate-834-user-access.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cls.app, _ = module.prepare(str(Path(cls.temp.name) / 'crm'))
        with closing(cls.app.db()) as con, con:
            cls.uid = {}
            for name, level in (('Editor', 2), ('Reader', 1), ('Hidden', 0)):
                cls.uid[name] = con.execute('INSERT INTO users(name,tab_permissions) VALUES(?,?)',
                    ('Network ' + name, json.dumps({'companies': level}))).lastrowid
            cls.company_id = con.execute("INSERT INTO companies(short_name,official_name,ico,address) VALUES('Network fixture','Network fixture s.r.o.','12345678','Plzeň')").lastrowid
        cls.snapshot = source.snapshot(cls.app.DB, Path(cls.temp.name) / 'template.db')

    def setUp(self):
        from psycopg import sql
        self.schema = 'turto_pilot_dir_' + uuid4().hex[:12]
        self.roles = {}
        self.clients = {}
        self.addCleanup(self.cleanup)
        migration.migrate(self.snapshot, self.profile, self.schema)
        directory.install(self.profile, self.schema)
        for name in ('Editor', 'Reader', 'Hidden'):
            role = 'turto_person_' + uuid4().hex[:14]
            self.roles[name] = role
            with self.profile.connect() as con:
                con.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}').format(
                    sql.Identifier(role), sql.Literal('pilot-person-test-only')))
            directory.authorize(self.profile, self.schema, role, self.uid[name])
            self.clients[name] = DirectoryClient(replace(self.profile, user=role), self.schema, password='pilot-person-test-only')

    def cleanup(self):
        from psycopg import sql
        with self.profile.connect() as con:
            con.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(self.schema)))
            for role in self.roles.values():
                con.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))

    def sql(self, statement, args=()):
        with self.profile.connect() as con:
            result = con.execute(statement.replace('__S__', self.schema), args)
            return result.fetchall() if result.description else []

    def current(self):
        return self.clients['Editor'].company(self.company_id)['company']

    def test_personal_identity_and_direct_sql_cannot_bypass_permissions(self):
        import psycopg
        editor = self.clients['Editor']
        self.assertEqual(editor.identity()['user_id'], self.uid['Editor'])
        with editor.profile.connect(password='pilot-person-test-only') as con:
            for statement in ('SELECT * FROM __S__.companies', 'SELECT * FROM __S__.users',
                              'UPDATE __S__.companies SET note=\'bypass\'',
                              'DELETE FROM __S__._network_company_audit', 'DROP TABLE __S__.companies',
                              'SELECT __S__.network_claims(0)'):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    con.execute(statement.replace('__S__', self.schema))
            con.execute("SET turto.active_user='ADMIN'; SET search_path=pg_temp,public")
            identity = con.execute(f'SELECT {self.schema}.network_identity()').fetchone()[0]
            self.assertEqual(identity['user_id'], self.uid['Editor'])
        with patch.dict(os.environ, {'TURTO_PG_PASSWORD': 'pilot-person-test-only'}), self.assertRaises(ValueError):
            directory.authorize(editor.profile, self.schema, self.roles['Reader'], self.uid['Editor'])

    def test_read_hidden_malformed_and_disabled_access(self):
        reader, hidden = self.clients['Reader'], self.clients['Hidden']
        self.assertTrue(reader.companies('Network fixture')['items'])
        self.assertEqual(reader.identity()['companies'], 1)
        with self.assertRaises(AccessDenied):
            reader.save(self.company_id, 0, {'note': 'denied'})
        self.assertEqual(hidden.identity()['companies'], 0)
        with self.assertRaises(AccessDenied):
            hidden.company(self.company_id)
        self.sql('UPDATE __S__.users SET tab_permissions=%s WHERE id=%s', ('bad json', self.uid['Editor']))
        with self.assertRaises(AccessDenied):
            self.clients['Editor'].identity()
        self.sql("UPDATE __S__.users SET tab_permissions='{}',active=0 WHERE id=%s", (self.uid['Reader'],))
        with self.assertRaises(AccessDenied):
            reader.companies()

    def test_revocation_applies_to_existing_authenticated_connection(self):
        import psycopg
        reader = self.clients['Reader']
        with reader.profile.connect(password='pilot-person-test-only') as con:
            con.execute(f'SELECT {self.schema}.network_identity()')
            directory.revoke(self.profile, self.schema, self.roles['Reader'])
            with self.assertRaises(psycopg.Error) as error:
                con.execute(f'SELECT {self.schema}.network_identity()')
            self.assertEqual(error.exception.sqlstate, 'P2001')
        self.sql('UPDATE __S__.users SET tab_permissions=%s WHERE id=%s', ('{"companies":1}', self.uid['Editor']))
        with self.assertRaises(AccessDenied):
            self.clients['Editor'].save(self.company_id, 0, {'note': 'denied after downgrade'})

    def test_create_edit_deactivate_and_audit_are_atomic(self):
        editor = self.clients['Editor']
        created = editor.save(None, 0, {'official_name': 'Nová česká firma', 'note': 'První\npoznámka', 'is_supplier': 1})
        self.assertEqual(created['network_revision'], 1)
        updated = editor.save(created['id'], 1, {'note': 'Druhá poznámka', 'active': 0})
        self.assertEqual(updated['network_revision'], 2)
        self.assertEqual(updated['active'], 0)
        history = editor.history(created['id'])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['user_name'], 'Network Editor')
        self.assertEqual(history[0]['db_login'], self.roles['Editor'])
        self.assertEqual(history[0]['previous']['note'], 'První\npoznámka')
        self.assertEqual(self.clients['Reader'].company(created['id'])['company']['note'], 'Druhá poznámka')

    def test_concurrent_edits_detect_conflict_without_lost_update(self):
        from concurrent.futures import ThreadPoolExecutor
        self.sql('UPDATE __S__.users SET tab_permissions=%s WHERE id=%s', ('{"companies":2}', self.uid['Reader']))
        def write(person):
            try:
                return self.clients[person].save(self.company_id, 0, {'note': person})['note']
            except Conflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ('Editor', 'Reader')))
        self.assertEqual(results.count('conflict'), 1)
        winner = self.current()['note']
        self.assertIn(winner, ('Editor', 'Reader'))
        self.assertEqual(self.current()['network_revision'], 1)
        history = self.clients['Editor'].history(self.company_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['db_login'], self.roles[winner])

    def test_repeated_request_creates_one_company_and_rejects_changed_payload(self):
        from concurrent.futures import ThreadPoolExecutor
        request = str(uuid4()); editor = self.clients['Editor']
        def create(_):
            return editor.save(None, 0, {'official_name': 'Network unique request'}, request)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (1, 2)))
        self.assertEqual(results[0]['id'], results[1]['id'])
        self.assertEqual(editor.operation(request)['id'], results[0]['id'])
        self.assertIsNone(self.clients['Reader'].operation(request))
        self.assertEqual(len(editor.history(results[0]['id'])), 1)
        with self.assertRaises(DirectoryError):
            editor.save(None, 0, {'official_name': 'different'}, request)

    def test_lost_response_can_be_verified_without_resending(self):
        import psycopg
        editor = self.clients['Editor']; original = editor.profile; request = str(uuid4())
        class LostConnection:
            def __init__(self, con): self.con = con
            def __enter__(self): self.con.__enter__(); return self
            def __exit__(self, *args): return self.con.__exit__(*args)
            def execute(self, query, *args):
                result = self.con.execute(query, *args)
                if 'network_save_company' in (query if isinstance(query, str) else query.as_string(self.con)):
                    result.fetchone()  # The actual PostgreSQL statement has committed.
                    raise psycopg.OperationalError('password=DO-NOT-EXPOSE')
                return result
        class LostProfile:
            def connect(self, password=None):
                return LostConnection(original.connect(password=password))
        editor.profile = LostProfile()
        try:
            with self.assertRaises(UncertainWrite) as error:
                editor.save(self.company_id, 0, {'note': 'Committed before connection loss'}, request)
            self.assertNotIn('DO-NOT-EXPOSE', str(error.exception))
        finally:
            editor.profile = original
        self.assertEqual(editor.operation(request)['note'], 'Committed before connection loss')
        self.assertEqual(len(editor.history(self.company_id)), 1)

    def test_audit_failure_rolls_back_company_and_request(self):
        self.sql('''CREATE FUNCTION __S__.reject_audit() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'audit write rejected'; END $$''')
        self.sql('CREATE TRIGGER reject_audit BEFORE INSERT ON __S__._network_company_audit FOR EACH ROW EXECUTE FUNCTION __S__.reject_audit()')
        request = str(uuid4()); before = self.current()
        with self.assertRaises(DirectoryError):
            self.clients['Editor'].save(self.company_id, 0, {'note': 'must roll back'}, request)
        self.assertEqual(self.current(), before)
        self.assertIsNone(self.clients['Editor'].operation(request))

    def test_validation_and_installer_are_fail_closed_and_idempotent(self):
        before = self.current()
        for values in ({'network_revision': 0}, {'active': 9}, {'note': None}, {'unknown': 'x'}):
            with self.assertRaises(DirectoryError):
                self.clients['Editor'].save(self.company_id, 0, values)
        self.assertEqual(self.current(), before)
        saved = self.clients['Editor'].save(self.company_id, 0, {'note': 'must survive reinstall'})
        directory.install(self.profile, self.schema)
        self.assertEqual(self.current(), saved)
        with self.assertRaises(ValueError):
            directory.authorize(self.profile, self.schema, self.profile.user, self.uid['Editor'])
        self.sql('GRANT SELECT ON __S__.companies TO ' + self.roles['Hidden'])
        with self.assertRaises(ValueError):
            directory.authorize(self.profile, self.schema, self.roles['Hidden'], self.uid['Hidden'])

    def test_wrong_password_is_rejected(self):
        client = DirectoryClient(self.clients['Editor'].profile, self.schema, password='incorrect')
        with self.assertRaises(DirectoryError):
            client.identity()

    def test_backup_restores_edited_directory_and_history(self):
        from psycopg import sql
        from network_db.backup import backup
        self.clients['Editor'].save(self.company_id, 0, {'note': 'Změna před zálohou'})
        restored_name = 'turto_dir_restore_' + uuid4().hex[:10]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                backup(self.profile, self.schema, Path(tmp) / 'rejected.dump')
            dump = backup(self.profile, self.schema, Path(tmp) / 'edited.dump', allow_pilot_changes=True)
            with self.profile.connect() as con:
                con.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_name)))
            restored = replace(self.profile, dbname=restored_name)
            try:
                result = subprocess.run(['pg_restore', '--no-password', '--exit-on-error', '--single-transaction',
                                         '--no-owner', '--no-privileges', '--dbname=' + restored_name, str(dump)],
                                        env=restored.process_env(), capture_output=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                directory.authorize(restored, self.schema, self.roles['Editor'], self.uid['Editor'])
                client = DirectoryClient(replace(restored, user=self.roles['Editor']), self.schema, password='pilot-person-test-only')
                self.assertEqual(client.company(self.company_id)['company']['note'], 'Změna před zálohou')
                self.assertEqual(len(client.history(self.company_id)), 1)
                import psycopg
                with client.profile.connect(password='pilot-person-test-only') as con:
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        con.execute(f'SELECT {self.schema}.network_claims(0)')
            finally:
                with self.profile.connect() as con:
                    con.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restored_name)))

    @unittest.skipUnless(os.environ.get('TURTO_TEST_UI'), 'Tk display and PostgreSQL required')
    def test_real_tk_login_edit_readonly_and_conflict(self):
        import tkinter as tk
        from network_db.ui import open_pilot
        root = tk.Tk(); root.withdraw()
        win = open_pilot(root)
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args[1]))
        def settle():
            deadline = time.monotonic() + 20
            while True:
                root.update()
                if not win.busy: break
                if time.monotonic() > deadline: self.fail('Tk network worker did not finish')
                time.sleep(0.02)
        def login(which):
            profile_path = Path(self.temp.name) / 'ui-profile.json'
            profile_path.write_text(json.dumps(self.clients[which].profile.public()), encoding='utf-8')
            win.profile_path.set(str(profile_path)); win.schema.set(self.schema)
            win.login.set(self.roles[which]); win.password.set('pilot-person-test-only')
            win.connect_button.invoke(); settle()
        def select_company():
            win.tree.selection_set(str(self.company_id))
            root.update()  # Deliver TreeviewSelect before invoking its enabled action.
            win.open_button.invoke(); settle()
        try:
            with patch('tkinter.messagebox.showerror') as error_box:
                login('Editor')
                self.assertEqual(win.identity['name'], 'Network Editor')
                self.assertEqual(win.password.get(), '')
                win.query.set('Network fixture'); win.refresh_button.invoke(); settle()
                select_company(); editor = win.editor
                with patch.object(editor, 'save') as save:
                    editor.save_key()
                    save.assert_not_called()
                editor.variables['official_name'].set('Network fixture upravená')
                editor.save_button.invoke(); settle()
                self.assertEqual(self.current()['official_name'], 'Network fixture upravená')
                select_company(); editor = win.editor
                self.clients['Editor'].save(self.company_id, 1, {'note': 'other workstation'})
                editor.variables['official_name'].set('must not overwrite')
                editor.save_button.invoke(); settle()
                self.assertIn('jiný uživatel', editor.status.get())
                self.assertEqual(self.current()['official_name'], 'Network fixture upravená')
                editor.close(); win.disconnect_button.invoke(); login('Reader')
                self.assertTrue(win.new_button.instate(['disabled']))
                win.query.set('Network fixture'); win.refresh_button.invoke(); settle()
                select_company()
                self.assertTrue(win.editor.save_button.instate(['disabled']))
                win.editor.close()
                Path('artifacts/network').mkdir(parents=True, exist_ok=True)
                from PIL import ImageGrab
                root.update(); ImageGrab.grab().save('artifacts/network/directory-readonly.png')
                self.assertFalse(error_box.called, error_box.call_args_list)
                self.assertFalse(errors, errors)
        finally:
            if win.winfo_exists(): win.close()
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
