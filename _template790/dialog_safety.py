from pathlib import Path
import hashlib,json
root=Path('.')
p=root/'ZakazkyApp_base_6.1/v770_runtime_policy.py';s=p.read_text(encoding='utf-8')
old='        win.update_idletasks()\n        parent.update_idletasks()\n';assert old in s
s=s.replace(old,'        # Placement already runs in a deferred callback. Never nest the Tk\n        # event loop while a child window or its font resources are changing.\n',1)
s=s.replace('                popup.update_idletasks()\n','                # Read settled geometry without re-entering a widget event.\n',1);p.write_text(s,encoding='utf-8')
p=root/'scripts/validate-7900-runtime-integration.py';s=p.read_text(encoding='utf-8')
s=s.replace('        import runtime_bootstrap\n',"        import runtime_bootstrap\n        import inspect\n        import v770_runtime_policy\n        assert 'update_idletasks(' not in inspect.getsource(v770_runtime_policy._place_dialog)\n",1);p.write_text(s,encoding='utf-8')
checks={'ZakazkyApp_base_6.1/v770_runtime_policy.py':'79420f8abe5bcab75a6d9ac482347aba2a90ab7eb21f8a3439951caa929840db','scripts/validate-7900-runtime-integration.py':'d980637dde3059c90cb51eb8c9473221cdd3cf9d54b1d0a2ec74b26fefbdca57'}
for name,digest in checks.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
files=json.loads(Path('.applied790.json').read_text())
files.append('ZakazkyApp_base_6.1/v770_runtime_policy.py')
Path('.applied790.json').write_text(json.dumps(files),encoding='utf-8')
print('Verified deferred dialog placement without nested event loop')
