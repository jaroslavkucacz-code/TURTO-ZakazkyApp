#!/usr/bin/env python3
"""Stable identities for every bundled Treeview construction site."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace

BASE = Path(__file__).resolve().parents[1] / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))
from price_lists_domain.platform.table_preferences_815 import key_for


class FakeTree:
    def __init__(self, name, columns=('A', 'B'), root=None):
        self._name, self.columns = name, columns
        self.root = root or SimpleNamespace()
    def _root(self): return self.root
    def winfo_toplevel(self): return self.root
    def cget(self, option): return self.columns


names = []
for path in BASE.rglob('*.py'):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'Treeview' or not ast.unparse(node.func.value).endswith('ttk'):
            continue
        name = next((k.value for k in node.keywords if k.arg == 'name'), None)
        assert isinstance(name, ast.Constant) and name.value.startswith('layout__'), (path, node.lineno)
        names.append(name.value)
assert len(names) >= 54 and len(set(names)) == len(names)
for name in names:
    assert key_for(FakeTree(name)) == key_for(FakeTree(name, ('B', 'A', 'New')))
assert key_for(FakeTree('layout__one')) != key_for(FakeTree('layout__two'))
root = SimpleNamespace()
root.dash_tree = FakeTree('layout__shared_factory', root=root)
root.action_tree = FakeTree('layout__shared_factory', root=root)
assert key_for(root.dash_tree) != key_for(root.action_tree)
replacement = SimpleNamespace()
replacement.dash_tree = FakeTree('layout__new_factory', root=replacement)
assert key_for(root.dash_tree) == key_for(replacement.dash_tree)
print(f'8.0.15: {len(names)} stable table roles; shared factories and schema evolution OK')
