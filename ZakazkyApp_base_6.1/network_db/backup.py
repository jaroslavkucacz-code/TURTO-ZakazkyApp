"""Custom-format dump of one pilot schema. No password in command arguments."""
from pathlib import Path
import os
import subprocess
import tempfile
from .migration import schema_name, verify


def backup(profile, schema, target, allow_pilot_changes=False):
    schema_name(schema)
    target = Path(target).resolve()
    if target.exists():
        raise ValueError('Cílový soubor zálohy již existuje.')
    if not verify(profile, schema)['ok']:
        if not allow_pilot_changes:
            raise ValueError('Pilotní data se změnila; pro zálohu testovacích úprav použijte --allow-pilot-changes.')
        from psycopg import sql
        with profile.connect() as con:
            marker = con.execute(sql.SQL('SELECT manifest FROM {} WHERE id=1').format(
                sql.Identifier(schema, '_turto_pilot_manifest'))).fetchone()[0]
            if marker.get('directory_api_version') != 1 or marker.get('application_ready') is not False:
                raise ValueError('Záloha upraveného pilotu vyžaduje připravenou serverovou agendu.')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.turto_dump_', suffix='.partial', dir=target.parent)
    os.close(fd)
    try:
        result = subprocess.run(['pg_dump', '--no-password', '--format=custom', '--no-owner',
                                 '--no-privileges', '--schema=' + schema, '--file=' + tmp],
                                env=profile.process_env(), capture_output=True, timeout=600)
        if result.returncode:
            raise RuntimeError('pg_dump selhal; záloha nebyla dokončena.')
        result = subprocess.run(['pg_restore', '--list', tmp], capture_output=True, timeout=60)
        if result.returncode or not Path(tmp).stat().st_size:
            raise RuntimeError('Záloha neprošla kontrolou formátu.')
        with open(tmp, 'rb') as handle:
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and refuses an existing target, including
        # one created concurrently. The temporary file is in the same directory.
        os.link(tmp, target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return target
