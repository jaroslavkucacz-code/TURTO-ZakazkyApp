from __future__ import annotations

import base64
import hashlib
import io
import json
import lzma
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

MANIFEST_URL = 'https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/izolacni-nosniky/update_manifest.json'
USER_AGENT = 'TURTO-Izolacni-nosniky-Installer/1.0'


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def get_bundle(here: Path, manifest: dict) -> bytes:
    whole = here / 'TURTO_update_bundle.b85'
    if whole.exists():
        return whole.read_bytes()
    local_parts = sorted(here.glob('TURTO_update_bundle.b85.part*'))
    if local_parts:
        return b''.join(p.read_bytes() for p in local_parts)
    if manifest.get('bundle_url'):
        return download(str(manifest['bundle_url']))
    parts = list(manifest.get('bundle_parts') or [])
    if not parts:
        raise RuntimeError('Manifest neobsahuje instalační balíček.')
    chunks=[]
    for part in parts:
        data=download(str(part['url']))
        expected=str(part.get('sha256','')).lower()
        if expected and hashlib.sha256(data).hexdigest().lower()!=expected:
            raise RuntimeError(f"Kontrolní součet části {part.get('name','?')} nesouhlasí.")
        chunks.append(data)
    return b''.join(chunks)


def decode_bundle(text: bytes) -> bytes:
    return lzma.decompress(base64.b85decode(b''.join(text.split())))


def safe_extract(data: bytes, dest: Path) -> None:
    dest = dest.resolve()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tf:
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if dest not in target.parents and target != dest:
                raise RuntimeError('Neplatná cesta v instalačním balíčku.')
        tf.extractall(dest)


def main() -> int:
    ui=tk.Tk(); ui.withdraw()
    try:
        here=Path(__file__).resolve().parent
        local_manifest=here/'update_manifest.json'
        manifest=json.loads(local_manifest.read_text(encoding='utf-8')) if local_manifest.exists() else json.loads(download(MANIFEST_URL).decode('utf-8'))
        bundle=get_bundle(here, manifest)
        if hashlib.sha256(bundle).hexdigest().lower()!=str(manifest['bundle_sha256']).lower():
            raise RuntimeError('Kontrolní součet instalačního balíčku nesouhlasí.')
        safe_extract(decode_bundle(bundle),here)
        program=here/'TURTO_Izolacni_nosniky'
        if not program.is_dir():
            raise RuntimeError('Program se nepodařilo rozbalit.')
        messagebox.showinfo('TURTO – instalace', f'Verze {manifest["version"]} byla připravena.\n\nProgram je ve složce:\n{program}', parent=ui)
        launcher=program/'Spustit_program.vbs'
        if launcher.exists() and sys.platform=='win32':
            os.startfile(str(launcher))  # type: ignore[attr-defined]
        return 0
    except Exception as exc:
        messagebox.showerror('TURTO – chyba instalace', f'Instalace se nepodařila.\n\n{exc}', parent=ui)
        return 1
    finally:
        ui.destroy()

if __name__=='__main__':
    raise SystemExit(main())
