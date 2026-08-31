#!/usr/bin/env python3
from pathlib import Path

path = Path("scripts/validate-real-ui.py")
text = path.read_text(encoding="utf-8")
old = '''        structure_trees = [
            tree for tree in catalogue_trees
            if {"Produktů", "Ceníků", "Nabídek"}.issubset(set(tree["columns"]))
            and not required_product_columns.issubset(set(tree["columns"]))
        ]
'''
new = '''        structure_trees = [
            tree for tree in catalogue_trees
            if {"Produktů", "Ceníků"}.issubset(set(tree["columns"]))
            and "Nabídek" not in set(tree["columns"])
            and not required_product_columns.issubset(set(tree["columns"]))
        ]
'''
if text.count(old) != 1:
    raise SystemExit("real UI catalogue structure marker mismatch")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
