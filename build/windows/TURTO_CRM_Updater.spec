# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "ZakazkyApp_base_6.1"
SCRIPT = ROOT / "build" / "windows" / "updater_800.pyw"
ICON = BASE / "turto_logo.ico"

a = Analysis(
    [str(SCRIPT)],
    pathex=[str(BASE)],
    binaries=[],
    datas=[],
    hiddenimports=["data_location"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TURTO CRM Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
)
