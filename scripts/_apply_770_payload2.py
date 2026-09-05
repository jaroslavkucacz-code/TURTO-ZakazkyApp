#!/usr/bin/env python3
from __future__ import annotations
import base64,io,json
from pathlib import Path,PurePosixPath
import tarfile,zlib


def main():
    root=Path(__file__).resolve().parents[1]
    directory=root/'scripts'/'_770_apply2'
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    parts=sorted(directory.glob('part*.b85'))
    if len(parts)!=int(manifest['parts']):
        raise SystemExit(f"Expected {manifest['parts']} chunks, found {len(parts)}")
    encoded=b''.join(path.read_bytes() for path in parts)
    if len(encoded)!=int(manifest['encoded_bytes']):
        raise SystemExit('Payload byte count mismatch')
    raw=zlib.decompress(base64.b85decode(encoded))
    allowed=set(manifest['files'])
    seen=set()
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for member in archive.getmembers():
            pure=PurePosixPath(member.name)
            if member.name not in allowed or pure.is_absolute() or '..' in pure.parts:
                raise SystemExit(f'Unexpected payload path: {member.name}')
            source=archive.extractfile(member)
            if source is None:
                raise SystemExit(f'Missing payload data: {member.name}')
            target=root.joinpath(*pure.parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(source.read())
            if member.mode & 0o111:
                target.chmod(0o755)
            seen.add(member.name)
    if seen!=allowed:
        raise SystemExit('Missing files: '+', '.join(sorted(allowed-seen)))
    print(f'Applied {len(seen)} TURTO CRM 7.7 files')

if __name__=='__main__':
    main()
