from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

PARTS = 5

def apply_patch(root: str | Path) -> None:
    root = Path(root)
    constants = root / "src" / "constants.py"
    try:
        if constants.exists() and "APP_VERSION = '0.2.1'" in constants.read_text(encoding="utf-8"):
            return
    except Exception:
        pass
    encoded = "".join((root / f"patch_v021_data_{i}.txt").read_text(encoding="ascii").strip() for i in range(1, PARTS + 1))
    payload = json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))
    for rel, text in payload.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
