#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "validate-7616-requests-plexus-assets.py"
text = path.read_text(encoding="utf-8")
needle = "        assert '\"v7616_requests_plexus_assets\"' < 'z'\n"
if needle not in text:
    raise SystemExit("Temporary validator assertion not found")
path.write_text(text.replace(needle, "", 1), encoding="utf-8")
print("Removed temporary TURTO CRM 7.7 validator assertion")
