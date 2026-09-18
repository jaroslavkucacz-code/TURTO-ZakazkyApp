# Windows-only, explicit network client and local demonstration entry points.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path.cwd()
base = root / 'ZakazkyApp_base_6.1'
datas, binaries, hidden = collect_all('psycopg_binary')
datas += [(str(base / 'network_db/directory.sql'), 'network_db'),
          (str(root / 'build/network-pilot/generated/demo.db'), 'network_db'),
          (str(base / 'turto_logo.ico'), 'network_db')]
a = Analysis([str(root / 'build/network-pilot/launcher.py')], pathex=[str(base)],
             binaries=binaries, datas=datas, hiddenimports=hidden + ['psycopg', 'network_db.__main__'],
             excludes=['app', 'runtime_bootstrap', 'tkinterdnd2'], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TURTO-CRM-Sitovy-Pilot',
          console=False, upx=False, icon=str(base / 'turto_logo.ico'))
admin = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TURTO-CRM-Pilot-Admin',
            console=True, upx=False, icon=str(base / 'turto_logo.ico'))
demo = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TURTO-CRM-Mistni-Ukazka',
           console=False, upx=False, icon=str(base / 'turto_logo.ico'))
check = EXE(pyz, a.scripts, [], exclude_binaries=True, name='TURTO-CRM-Kontrola-Pripojeni',
            console=False, upx=False, icon=str(base / 'turto_logo.ico'))
coll = COLLECT(gui, admin, demo, check, a.binaries, a.datas, name='TURTO-CRM-Sitovy-Pilot', upx=False)
