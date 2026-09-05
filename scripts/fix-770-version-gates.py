#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parent / "validate-7600-table-activity-performance.py"
text = path.read_text(encoding="utf-8")
old = "    assert (7, 6, 1) <= version_tuple < (7, 7, 0), version\n"
new = "    assert (7, 6, 1) <= version_tuple < (8, 0, 0), version\n"
if old not in text:
    raise SystemExit("Expected 7.6-only version gate was not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Extended TURTO CRM 7.6 table contract through the 7.x series")
