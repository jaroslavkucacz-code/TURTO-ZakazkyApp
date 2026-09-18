"""Copy the runner's native PostgreSQL distribution, without its data/services."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = Path(os.environ['PGROOT'])
target = ROOT / 'dist/TURTO-CRM-Sitovy-Pilot/postgresql'
target.mkdir(parents=True, exist_ok=False)
# Preserve distribution DLLs, extensions, locale files and bundled notices.
for name in ('bin', 'lib', 'share', 'doc'):
    shutil.copytree(source / name, target / name, ignore=shutil.ignore_patterns('*.pdb'))
for path in source.iterdir():
    if path.is_file() and path.suffix.lower() in ('.txt', '.md', '.html'):
        shutil.copyfile(path, target / path.name)
notices = [str(path.relative_to(target)) for path in target.rglob('*') if path.is_file()
           and any(word in path.name.lower() for word in ('license', 'licence', 'copyright', 'legalnotice'))]
assert notices, 'PostgreSQL distribution license notices must accompany the binaries'
version = subprocess.check_output([str(target / 'bin/postgres.exe'), '--version'], text=True).strip()
metadata = {'version': version, 'source': 'GitHub windows-2025 PostgreSQL distribution',
            'license_notices': notices, 'installed_service': False, 'contains_company_data': False}
(target / 'runtime-metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
size = sum(path.stat().st_size for path in target.rglob('*') if path.is_file())
print('Bundled', version, 'bytes:', size, 'license notices:', len(notices))
