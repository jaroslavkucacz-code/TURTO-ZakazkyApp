"""Connection choices only. This directory never contains CRM data or passwords."""
import json
import os
from pathlib import Path
import tempfile

from .profile import Profile
from .migration import schema_name

FORMAT = 'turto-network-connection-v1'


def default_path():
    root = os.environ.get('TURTO_PILOT_CONFIG_ROOT')
    if root:
        return Path(root) / 'connection.json'
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.config')) / 'TURTO' / 'CRM-Network-Pilot' / 'connection.json'


def load(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(data, dict) and data.get('format') == FORMAT:
        if set(data) != {'format', 'profile', 'schema'} or not isinstance(data['profile'], dict):
            raise ValueError('Neplatné nastavení připojení.')
        if set(data['profile']) - set(Profile.__dataclass_fields__):
            raise ValueError('Nastavení nesmí obsahovat heslo ani neznámé položky.')
        profile, schema = Profile(**data['profile']), schema_name(data['schema'])
    else:
        profile, schema = Profile.load(path), 'turto_pilot_prvni'
    # Shared client files may reference the public CA certificate next to them.
    if profile.sslrootcert and not Path(profile.sslrootcert).is_absolute():
        from dataclasses import replace
        profile = replace(profile, sslrootcert=str((path.parent / profile.sslrootcert).resolve()))
    return profile, schema


def save(path, profile, schema):
    schema_name(schema)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps({'format': FORMAT, 'profile': profile.public(), 'schema': schema}, ensure_ascii=False, indent=2) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.connection-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
