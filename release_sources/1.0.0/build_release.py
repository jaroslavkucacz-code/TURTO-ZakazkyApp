from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def _check_zip(data: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(data), 'r') as z:
        assert z.testzip() is None


def run() -> None:
    os.chdir(REPO)
    root = pathlib.Path('release_sources/1.0.0')
    ready = json.loads((root/'ready.json').read_text(encoding='utf-8'))
    assert ready['version'] == '1.0.0'
    with urllib.request.urlopen(ready['previous_url'], timeout=60) as r:
        previous = r.read()
    assert hashlib.sha256(previous).hexdigest() == ready['previous_sha256']

    previous_dir = pathlib.Path('_previous_100')
    shutil.rmtree(previous_dir, ignore_errors=True)
    previous_dir.mkdir()
    _check_zip(previous)
    with zipfile.ZipFile(io.BytesIO(previous)) as z:
        z.extractall(previous_dir)
    old_safety_path = pathlib.Path('_old_release_safety.py')
    old_safety_path.write_bytes((previous_dir/'src/release_safety.py').read_bytes())

    stage = pathlib.Path('_stage_100')
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(previous_dir, stage)
    mapping = {
        'app.pyw.txt': 'app.pyw',
        'config.py.txt': 'src/config.py',
        'updater.py.txt': 'src/updater.py',
        'release_safety.py.txt': 'src/release_safety.py',
        'update_installer.py.txt': 'update_installer.py',
        'windows_integration.py.txt': 'src/windows_integration.py',
        'START_TURTO.bat.txt': 'START_TURTO.bat',
        'INSTALL.bat.txt': 'INSTALL.bat',
        'README.txt': 'README.txt',
    }
    for src, dst in mapping.items():
        p = stage/dst
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((root/src).read_bytes())

    constants = stage/'src/constants.py'
    text = constants.read_text(encoding='utf-8')
    text, count = re.subn(r"APP_VERSION = '[^']+'", "APP_VERSION = '1.0.0'", text, count=1)
    assert count == 1
    constants.write_text(text, encoding='utf-8')
    (stage/'src/windows_identity_fix.py').unlink(missing_ok=True)

    note = (root/'ZMENY_1.0.0.txt').read_text(encoding='utf-8')
    for f in stage.glob('ZMENY_*.txt'):
        f.unlink()
    (stage/'ZMENY_1.0.0.txt').write_text(note, encoding='utf-8')
    changelog = stage/'CHANGELOG.txt'
    changelog.write_text(note.rstrip()+'\n\n'+changelog.read_text(encoding='utf-8'), encoding='utf-8')
    (stage/'package_files.json').unlink(missing_ok=True)
    for p in list(stage.rglob('*.py')) + list(stage.rglob('*.pyw')):
        compile(p.read_bytes(), p.as_posix(), 'exec')

    version_file = pathlib.Path('_turto_version_info.txt')
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(1,0,0,0),prodvers=(1,0,0,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040504B0',[StringStruct('CompanyName','TURTO'),StringStruct('FileDescription','TURTO – Měsíční přehledy'),StringStruct('FileVersion','1.0.0'),StringStruct('InternalName','TURTO_Mesicni_Prehledy'),StringStruct('OriginalFilename','TURTO_Mesicni_Prehledy.exe'),StringStruct('ProductName','TURTO – Měsíční přehledy'),StringStruct('ProductVersion','1.0.0')])]),VarFileInfo([VarStruct('Translation',[1029,1200])])])\n",
        encoding='utf-8',
    )

    dist_main = pathlib.Path('_dist_main').resolve()
    work_main = pathlib.Path('_work_main').resolve()
    spec_main = pathlib.Path('_spec_main').resolve()
    shutil.rmtree(dist_main, ignore_errors=True)
    shutil.rmtree(work_main, ignore_errors=True)
    shutil.rmtree(spec_main, ignore_errors=True)
    cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir',
        '--name', 'TURTO_Mesicni_Prehledy', '--icon', str((stage/'assets/app_icon.ico').resolve()),
        '--version-file', str(version_file.resolve()),
        '--add-data', str((stage/'assets').resolve())+os.pathsep+'assets',
        '--collect-all', 'xlsxwriter', '--distpath', str(dist_main), '--workpath', str(work_main),
        '--specpath', str(spec_main), str((stage/'app.pyw').resolve()),
    ]
    subprocess.run(cmd, check=True, cwd=stage)
    main_dir = dist_main/'TURTO_Mesicni_Prehledy'
    main_exe = main_dir/'TURTO_Mesicni_Prehledy.exe'
    assert main_exe.exists() and (main_dir/'_internal').is_dir()
    cp = subprocess.run([str(main_exe), '--turto-self-test'], timeout=30)
    assert cp.returncode == 0, cp.returncode

    dist_helper = pathlib.Path('_dist_helper').resolve()
    work_helper = pathlib.Path('_work_helper').resolve()
    spec_helper = pathlib.Path('_spec_helper').resolve()
    shutil.rmtree(dist_helper, ignore_errors=True)
    shutil.rmtree(work_helper, ignore_errors=True)
    shutil.rmtree(spec_helper, ignore_errors=True)
    cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onefile',
        '--name', 'TURTO_Update_Helper', '--icon', str((stage/'assets/app_icon.ico').resolve()),
        '--distpath', str(dist_helper), '--workpath', str(work_helper), '--specpath', str(spec_helper),
        str((stage/'update_installer.py').resolve()),
    ]
    subprocess.run(cmd, check=True, cwd=stage)
    helper = dist_helper/'TURTO_Update_Helper.exe'
    assert helper.exists() and helper.stat().st_size > 500_000

    native_buf = io.BytesIO()
    with zipfile.ZipFile(native_buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(main_exe, 'TURTO_Mesicni_Prehledy.exe')
        for p in sorted((main_dir/'_internal').rglob('*')):
            if p.is_file():
                rel = pathlib.PurePosixPath('_internal')/p.relative_to(main_dir/'_internal').as_posix()
                z.write(p, rel.as_posix())
        z.write(helper, 'TURTO_Update_Helper.exe')
    native_data = native_buf.getvalue()
    _check_zip(native_data)
    native_sha = hashlib.sha256(native_data).hexdigest()
    assert len(native_data) < 70*1024*1024, len(native_data)

    for p in (stage/'src').glob('native_payload_*.py'):
        p.unlink()
    chunk_size = 2*1024*1024
    for idx, start in enumerate(range(0, len(native_data), chunk_size)):
        raw = native_data[start:start+chunk_size]
        b64 = base64.b64encode(raw).decode('ascii')
        body = '\n'.join(textwrap.wrap(b64, 76))
        (stage/'src'/f'native_payload_{idx:03d}.py').write_text(
            '# TURTO native 1.0 payload chunk\nDATA = """\n'+body+'\n"""\n', encoding='ascii'
        )
    (stage/'src/native_payload_meta.py').write_text(
        f"NATIVE_SHA256='{native_sha}'\nNATIVE_SIZE={len(native_data)}\n", encoding='ascii'
    )

    files = {
        p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file() and p.name != 'package_files.json'
    }
    (stage/'package_files.json').write_text(
        json.dumps({'app_id': ready['app_id'], 'version': '1.0.0', 'files': files}, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8',
    )

    spec = importlib.util.spec_from_file_location('old_release_safety', old_safety_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    old.validate_folder(stage)

    install_test = pathlib.Path('_install_test')
    shutil.rmtree(install_test, ignore_errors=True)
    shutil.copytree(previous_dir, install_test)
    (install_test/'data').mkdir(exist_ok=True)
    (install_test/'data/KEEP.txt').write_text('keep', encoding='utf-8')
    (install_test/'config.json').write_text('{"keep": true}', encoding='utf-8')
    sys.path.insert(0, str(stage.resolve()))
    inst_spec = importlib.util.spec_from_file_location('turto_installer_100', stage/'update_installer.py')
    inst = importlib.util.module_from_spec(inst_spec)
    inst_spec.loader.exec_module(inst)
    inst.copy_update(stage, install_test)
    assert (install_test/'data/KEEP.txt').read_text(encoding='utf-8') == 'keep'
    assert json.loads((install_test/'config.json').read_text(encoding='utf-8'))['keep'] is True
    installed_exe = install_test/'TURTO_Mesicni_Prehledy.exe'
    assert installed_exe.exists()
    cp = subprocess.run([str(installed_exe), '--turto-self-test'], timeout=30)
    assert cp.returncode == 0, cp.returncode

    update_buf = io.BytesIO()
    with zipfile.ZipFile(update_buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026,9,13,21,15,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    update_data = update_buf.getvalue()
    _check_zip(update_data)
    assert len(update_data) < 78*1024*1024, len(update_data)
    release_dir = pathlib.Path('releases/1.0.0')
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir/'TURTO_update_1.0.0.zip').write_bytes(update_data)
    pathlib.Path('_v100_update_sha.txt').write_text(hashlib.sha256(update_data).hexdigest(), encoding='ascii')

    portable = io.BytesIO()
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        with zipfile.ZipFile(io.BytesIO(native_data)) as nz:
            for info in nz.infolist():
                if not info.is_dir():
                    z.writestr(info, nz.read(info.filename))
        z.writestr('START_TURTO.bat', (root/'START_TURTO.bat.txt').read_bytes())
        z.writestr('README.txt', (root/'README.txt').read_bytes())
    portable_data = portable.getvalue()
    _check_zip(portable_data)
    (release_dir/'TURTO_Mesicni_Prehledy_1.0.0_Windows.zip').write_bytes(portable_data)
    print('TURTO_1_0_OK', 'update=', len(update_data), 'native=', len(native_data), 'chunks=', len(list((stage/'src').glob('native_payload_*.py'))))


if __name__ == '__main__':
    run()
