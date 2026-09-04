#!/usr/bin/env python3
"""One-shot extractor for the generated TURTO CRM 7.7 repository payload."""
from __future__ import annotations

import base64
import io
from pathlib import Path, PurePosixPath
import tarfile
import zlib

ALLOWED = {
    '.github/workflows/validate-770-runtime.yml',
    'ARCHITECTURE_AUDIT_7.7.md',
    'ZakazkyApp_base_6.1/ZakazkyCRM.pyw',
    'ZakazkyApp_base_6.1/runtime_bootstrap.py',
    'ZakazkyApp_base_6.1/turto_crm.ico',
    'ZakazkyApp_base_6.1/turto_crm.png',
    'ZakazkyApp_base_6.1/v7616_requests_plexus_assets.py',
    'ZakazkyApp_base_6.1/v767_offer_reprocess_images.py',
    'ZakazkyApp_base_6.1/v768_clean_table_markers.py',
    'ZakazkyApp_base_6.1/v770_runtime_policy.py',
    'release_notes.txt',
    'release_version.txt',
    'scripts/audit-runtime-overrides.py',
    'scripts/validate-7610-nevoga-exact-red-excel.py',
    'scripts/validate-768-clean-table-markers.py',
    'scripts/validate-770-runtime-policy.py',
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    chunk_dir = root / 'scripts' / '_770_payload'
    parts = sorted(chunk_dir.glob('part*.b85'))
    if len(parts) != 12:
        raise SystemExit(f'Expected 12 payload chunks, found {len(parts)}')
    encoded = b''.join(path.read_bytes() for path in parts)
    raw = zlib.decompress(base64.b85decode(encoded))
    seen: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for member in archive.getmembers():
            pure = PurePosixPath(member.name)
            if member.name not in ALLOWED or pure.is_absolute() or '..' in pure.parts:
                raise SystemExit(f'Unexpected payload path: {member.name}')
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f'Payload member has no content: {member.name}')
            target = root.joinpath(*pure.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())
            seen.add(member.name)
    missing = sorted(ALLOWED - seen)
    if missing:
        raise SystemExit('Missing payload members: ' + ', '.join(missing))
    print(f'Applied {len(seen)} TURTO CRM 7.7 files')


if __name__ == '__main__':
    main()
