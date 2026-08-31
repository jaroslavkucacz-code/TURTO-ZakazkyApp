#!/usr/bin/env python3
"""Correct retained markers in the temporary 6.3.41 transformer."""
from pathlib import Path

path = Path("scripts/apply-6341-offer-catalog-core.py")
text = path.read_text(encoding="utf-8")

old = """source_end = '''        ).fetchall()
    win = M.tk.Toplevel(parent)
'''
"""
new = """source_end = '''    win = M.tk.Toplevel(parent)
'''
"""
if text.count(old) != 1:
    raise SystemExit("source_end transformer marker mismatch")
text = text.replace(old, new, 1)

old = """        ).fetchall()
    win = M.tk.Toplevel(parent)
'''
text = replace_section(text, source_start, source_end, source_replacement, "product_catalog source dialog")
"""
new = """        ).fetchall()
'''
text = replace_section(text, source_start, source_end, source_replacement, "product_catalog source dialog")
"""
if text.count(old) != 1:
    raise SystemExit("source replacement transformer marker mismatch")
text = text.replace(old, new, 1)

old = """    M.open_product_catalog = lambda app, category_id=None, subgroup_id=None: open_product_catalog(
'''
text = replace_section(text, install_start, install_end, install_replacement, "product_catalog install hook")
"""
new = """'''
text = replace_section(text, install_start, install_end, install_replacement, "product_catalog install hook")
"""
if text.count(old) != 1:
    raise SystemExit("install replacement transformer marker mismatch")
text = text.replace(old, new, 1)

old = '''                  "nebo podskupinu; produkty lze upravit dvojklikem nebo přetáhnout na cílovou skupinu."),'''
new = '''                  "nebo podskupinu; produkty lze upravit dvojklikem nebo je myší přetáhnout přímo na cílovou skupinu."),'''
if text.count(old) != 1:
    raise SystemExit("workspace wording transformer marker mismatch")
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
print("Corrected temporary 6.3.41 transformer markers")
