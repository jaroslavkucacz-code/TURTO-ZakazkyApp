# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd()
BASE = ROOT / "ZakazkyApp_base_6.1"
LAUNCHER = ROOT / "build" / "windows" / "launcher_800.pyw"
ICON = BASE / "turto_logo.ico"

sys.path.insert(0, str(BASE))
import runtime_bootstrap

hiddenimports = list(runtime_bootstrap.EARLY_LAYERS)
hiddenimports += list(runtime_bootstrap.STABILITY_PRIMED_LAYERS)
hiddenimports += list(runtime_bootstrap.LATE_LAYERS)
hiddenimports += [
    "post_baseline",
    "v631_diskdrop",
    "v644_default_date_sort",
    "crm_price_lists",
]
hiddenimports += collect_submodules("price_lists_domain")
hiddenimports += collect_submodules("offers_engine")
hiddenimports = sorted(set(hiddenimports))

datas = []
for name in ("turto_logo.png", "turto_logo.ico", "turto_crm.png", "turto_crm.ico", "README.txt"):
    path = BASE / name
    if path.is_file():
        datas.append((str(path), "."))
datas += collect_data_files("price_lists_domain")
datas += collect_data_files("tkinterdnd2")

a = Analysis(
    [str(LAUNCHER)],
    pathex=[str(BASE)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TURTO CRM Diagnostic",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TURTO CRM Diagnostic",
)
