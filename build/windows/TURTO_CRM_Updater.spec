# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
ROOT = Path.cwd()
BASE = ROOT / "ZakazkyApp_base_6.1"
SCRIPT = ROOT / "build" / "windows" / "updater_800.pyw"
ICON = BASE / "turto_logo.ico"
a = Analysis([str(SCRIPT)], pathex=[str(BASE)], binaries=[], datas=[(str(ICON), ".")],
    hiddenimports=["data_location", "updater_safety", "update_progress"], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TURTO CRM Updater",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=True, icon=str(ICON),
    contents_directory="_updater_runtime")
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="TURTO CRM Updater")
