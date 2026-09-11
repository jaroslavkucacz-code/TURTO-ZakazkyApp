from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

CHUNKS = 10

def apply_patch(root):
    root=Path(root)
    constants=root/'src'/'constants.py'
    icon=root/'assets'/'app_icon.ico'
    helper=root/'src'/'windows_integration.py'
    try:
        if constants.exists() and "APP_VERSION = '0.1.8'" in constants.read_text(encoding='utf-8') and icon.exists() and helper.exists():
            return
    except Exception:
        pass
    encoded=''.join((root/f'patch_v018_data_s{i}.txt').read_text(encoding='ascii').strip() for i in range(1,CHUNKS+1))
    payload=base64.b64decode(encoded)
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        z.extractall(root)
