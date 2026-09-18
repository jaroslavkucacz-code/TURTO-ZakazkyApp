"""Package only the tested standalone directory client, never the CRM updater."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
bundle = ROOT / 'dist/TURTO-CRM-Sitovy-Pilot'
output = ROOT / 'artifacts/network/package'
output.mkdir(parents=True, exist_ok=True)
for name in ('TURTO-CRM-Sitovy-Pilot.exe', 'TURTO-CRM-Pilot-Admin.exe', 'TURTO-CRM-Mistni-Ukazka.exe',
             'postgresql/bin/postgres.exe', 'postgresql/runtime-metadata.json',
             '_internal/network_db/demo.db', '_internal/network_db/directory.sql'):
    assert (bundle / name).is_file(), name
for permission in ('edit', 'read'):
    result = json.loads((ROOT / f'artifacts/network/windows/{permission}.json').read_text(encoding='utf-8'))
    assert result['ok'] and result['frozen'] and result['permission'] == permission
local_result = json.loads((ROOT / 'artifacts/network/windows/local-demo.json').read_text(encoding='utf-8'))
assert all(local_result[key] for key in ('ok', 'frozen', 'editor', 'reader', 'concurrent_conflict',
    'history', 'graceful_stop', 'forced_stop', 'temporary_data_removed', 'loopback_only', 'company_settings_unchanged'))
shutil.copyfile(ROOT / 'docs/network/TRY-PILOT.md', bundle / 'ZACNETE-ZDE.txt')
support = bundle / 'pro-spravce'; support.mkdir(exist_ok=True)
for name in ('SERVER.md', 'DIRECTORY.md', 'README.md', 'profile.example.json'):
    shutil.copyfile(ROOT / 'docs/network' / name, support / name)
manifest = {'pilot_version': '0.3.0', 'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'kind': 'standalone-network-pilot', 'production_updater': False, 'company_data': 'artificial-demo-only',
            'frozen_tls_login_edit_read_test': 'passed', 'local_demo_and_cleanup_test': 'passed'}
(bundle / 'pilot-version.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
archive = output / 'TURTO_CRM_Pilot_s_Mistni_Ukazkou_0.3.0_Windows_x64.zip'
with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zip_file:
    for path in sorted(bundle.rglob('*')):
        if path.is_file():
            assert path.name not in ('server.key', 'connection.json', 'zakazky.db', 'latest-windows.json')
            zip_file.write(path, path.relative_to(bundle.parent))
with archive.open('rb') as handle:
    digest = hashlib.file_digest(handle, 'sha256').hexdigest()
(output / (archive.name + '.sha256')).write_text(digest + '  ' + archive.name + '\n', encoding='utf-8')
print(archive.name, digest)
