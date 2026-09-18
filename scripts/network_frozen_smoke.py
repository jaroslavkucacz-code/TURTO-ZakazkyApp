"""Run the shipped admin EXE and two GUI EXE sessions against real PostgreSQL/TLS."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from network_db import settings
from network_db.profile import Profile
from network_db.client import DirectoryClient, DirectoryError


def main():
    from psycopg import sql
    bundle = (REPO / 'dist/TURTO-CRM-Sitovy-Pilot').resolve()
    admin, gui = bundle / 'TURTO-CRM-Pilot-Admin.exe', bundle / 'TURTO-CRM-Sitovy-Pilot.exe'
    schema = 'turto_pilot_ci_' + uuid4().hex[:12]
    roles = []
    profile = Profile('localhost', 'turto_pilot_test', 'postgres', port=55432,
                      sslrootcert=os.environ['TURTO_TEST_CA'])
    output = REPO / 'artifacts/network/windows'; output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        runtime_env = os.environ.copy()
        pg_root = os.environ['PGROOT'].replace('\\', '/').rstrip('/').casefold()
        runtime_env['PATH'] = os.pathsep.join(part for part in os.environ['PATH'].split(os.pathsep)
            if not part.replace('\\', '/').rstrip('/').casefold().startswith(pg_root))
        profile_path = Path(tmp) / 'admin.json'
        profile_path.write_text(json.dumps(profile.public()), encoding='utf-8')
        def cli(*args):
            result = subprocess.run([str(admin), *args], capture_output=True, timeout=120,
                                    cwd=tmp, env=runtime_env | {'PYTHONIOENCODING': 'utf-8'})
            if result.returncode:
                raise AssertionError('Packaged admin command failed: ' + result.stderr.decode('utf-8', errors='replace'))
            return result.stdout.decode('utf-8-sig')
        try:
            assert 'prepare-demo' in cli('--help')
            cli('check', '--profile', str(profile_path))
            people = json.loads(cli('prepare-demo', '--profile', str(profile_path), '--schema', schema))
            assert any(p['name'] == 'Pilot – editor' for p in people)
            for title, level in (('Pilot – editor', 'edit'), ('Pilot – čtenář', 'read')):
                role = 'turto_ci_' + uuid4().hex[:14]; roles.append(role)
                with profile.connect() as con:
                    con.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}').format(
                        sql.Identifier(role), sql.Literal('pilot-person-test-only')))
                uid = next(p['id'] for p in people if p['name'] == title)
                cli('directory-authorize', '--profile', str(profile_path), '--schema', schema, '--login', role, '--user-id', str(uid))
                choice = Path(tmp) / (level + '.json')
                personal = replace(profile, user=role)
                settings.save(choice, personal, schema)
                # Prove hostname verification, not just TLS encryption.
                wrong_host = DirectoryClient(replace(personal, host='127.0.0.1'), schema, 'pilot-person-test-only')
                try:
                    wrong_host.identity()
                except DirectoryError:
                    pass
                else:
                    raise AssertionError('TLS hostname mismatch was accepted')
                report = output / (level + '.json')
                env = runtime_env | {'TURTO_PILOT_TEST_PASSWORD': 'pilot-person-test-only',
                                    'TURTO_PILOT_CONFIG_ROOT': str(Path(tmp) / ('config-' + level))}
                result = subprocess.run([str(gui), '--smoke-test', '--config', str(choice), '--report', str(report)],
                                        cwd=tmp, env=env, timeout=120)
                data = json.loads(report.read_text(encoding='utf-8'))
                assert result.returncode == 0 and data['ok'] and data['frozen'], data
                assert data['permission'] == level
                print('Frozen GUI and verified TLS:', level, 'OK')
            listed = json.loads(cli('directory-users', '--profile', str(profile_path), '--schema', schema))
            assert len(listed) == len(people)
        finally:
            with profile.connect() as con:
                con.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
                for role in roles:
                    con.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))


if __name__ == '__main__':
    main()
