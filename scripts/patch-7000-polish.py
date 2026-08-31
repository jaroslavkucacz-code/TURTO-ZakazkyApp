#!/usr/bin/env python3
"""Small follow-up adjustments after the first successful 7.0 integration run."""
from pathlib import Path

path = Path("ZakazkyApp_base_6.1/v700_ux.py")
text = path.read_text(encoding="utf-8")

old = '''            group_no = 0\n            for token in group_offer_items(normalized):\n'''
new = '''            group_no = 0\n            display_no = 0\n            for token in group_offer_items(normalized):\n'''
if text.count(old) != 1:
    raise SystemExit(f"editor display counter marker: {text.count(old)}")
text = text.replace(old, new, 1)

old = '''                original_index = int(token["index"])\n                item = service.normalize_item(token["item"], original_index + 1)\n'''
new = '''                original_index = int(token["index"])\n                display_no += 1\n                item = service.normalize_item(token["item"], original_index + 1)\n'''
if text.count(old) != 1:
    raise SystemExit(f"editor item marker: {text.count(old)}")
text = text.replace(old, new, 1)

old = '''                    original_index + 1,\n                    service.ROW_TYPES.get(item.get("row_type"), item.get("row_type")),\n'''
new = '''                    display_no,\n                    service.ROW_TYPES.get(item.get("row_type"), item.get("row_type")),\n'''
if text.count(old) != 1:
    raise SystemExit(f"editor visible position marker: {text.count(old)}")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Applied TURTO CRM 7.0 display-order polish")
