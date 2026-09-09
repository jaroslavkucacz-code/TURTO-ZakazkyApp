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
import tkinterdnd2

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

# tkinterdnd2 ships native payloads for many platforms and architectures. TURTO
# CRM 8.0 is a Windows x64 build, so include only the two x64 variants required
# by current/legacy Tcl runtimes. Python 3.14 uses Tcl/Tk 9, therefore the
# win-x64-tcl9 directory is mandatory; win-x64 remains as a compatibility path.
tkdnd_package = Path(tkinterdnd2.__file__).resolve().parent
tkdnd_root = tkdnd_package / "tkdnd"
for variant in ("win-x64", "win-x64-tcl9"):
    source_root = tkdnd_root / variant
    if not source_root.is_dir():
        raise RuntimeError(f"Required tkinterdnd2 payload missing: {source_root}")
    for source in source_root.rglob("*"):
        if source.is_file():
            relative_parent = source.parent.relative_to(tkdnd_package)
            datas.append((str(source), str(Path("tkinterdnd2") / relative_parent)))

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
    name="TURTO CRM",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TURTO CRM",
)
