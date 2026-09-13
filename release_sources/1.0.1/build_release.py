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
import tempfile
import textwrap
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
VERSION = '1.0.1'
MAIN_EXE = 'TURTO_Mesicni_Prehledy.exe'
UPDATER_EXE = 'TURTO_Mesicni_Prehledy_Updater.exe'
SETUP_EXE = f'TURTO_Mesicni_Prehledy_Setup_{VERSION}.exe'


def clean_python_cache(root: pathlib.Path) -> None:
    for cache in list(root.rglob('__pycache__')):
        shutil.rmtree(cache, ignore_errors=True)
    for pyc in list(root.rglob('*.pyc')):
        pyc.unlink(missing_ok=True)


def find_iscc() -> pathlib.Path:
    candidates = []
    for key in ('ProgramFiles(x86)', 'ProgramFiles'):
        base = os.environ.get(key)
        if not base:
            continue
        for ver in ('6', '7'):
            candidates.append(pathlib.Path(base)/f'Inno Setup {ver}'/'ISCC.exe')
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError('ISCC.exe nebyl po instalaci Inno Setup nalezen.')


def make_package_manifest(stage: pathlib.Path, version: str) -> dict:
    files = {
        p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*'))
        if p.is_file() and p.name != 'package_files.json'
    }
    (stage/'package_files.json').write_text(
        json.dumps({'app_id': 'cz.turto.mesicni-prehledy', 'version': version, 'files': files}, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8',
    )
    return files


def run() -> None:
    os.chdir(REPO)
    sys.dont_write_bytecode = True
    ready = json.loads((ROOT/'ready.json').read_text(encoding='utf-8'))
    assert ready['version'] == VERSION

    with urllib.request.urlopen(ready['previous_url'], timeout=60) as r:
        previous = r.read()
    assert hashlib.sha256(previous).hexdigest() == ready['previous_sha256']

    previous_dir = pathlib.Path('_previous_101')
    shutil.rmtree(previous_dir, ignore_errors=True)
    previous_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(previous)) as z:
        assert z.testzip() is None
        z.extractall(previous_dir)

    old_safety_path = pathlib.Path('_old_release_safety_101.py')
    old_safety_path.write_bytes((previous_dir/'src/release_safety.py').read_bytes())

    stage = pathlib.Path('_stage_101')
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(previous_dir, stage)

    mapping = {
        'app.pyw.txt': 'app.pyw',
        'config.py.txt': 'src/config.py',
        'updater.py.txt': 'src/updater.py',
        'release_safety.py.txt': 'src/release_safety.py',
        'transition_installer.py.txt': 'update_installer.py',
        'README.txt': 'README.txt',
    }
    for src, dst in mapping.items():
        p = stage/dst
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((ROOT/src).read_bytes())

    helper_source = stage/'native_update_helper.py'
    helper_source.write_bytes((ROOT/'native_update_helper.py.txt').read_bytes())

    constants = stage/'src/constants.py'
    text = constants.read_text(encoding='utf-8')
    text, count = re.subn(r"APP_VERSION = '[^']+'", f"APP_VERSION = '{VERSION}'", text, count=1)
    assert count == 1
    constants.write_text(text, encoding='utf-8')

    (stage/'src/windows_identity_fix.py').unlink(missing_ok=True)
    note = (ROOT/'ZMENY_1.0.1.txt').read_text(encoding='utf-8')
    for f in stage.glob('ZMENY_*.txt'):
        f.unlink()
    (stage/'ZMENY_1.0.1.txt').write_text(note, encoding='utf-8')
    changelog = stage/'CHANGELOG.txt'
    changelog.write_text(note.rstrip()+'\n\n'+changelog.read_text(encoding='utf-8'), encoding='utf-8')
    (stage/'package_files.json').unlink(missing_ok=True)
    clean_python_cache(stage)
    for p in list(stage.rglob('*.py')) + list(stage.rglob('*.pyw')):
        compile(p.read_bytes(), p.as_posix(), 'exec')

    version_file = pathlib.Path('_turto_reporting_101_version.txt')
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(1,0,1,0),prodvers=(1,0,1,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040504B0',[StringStruct('CompanyName','TURTO s.r.o.'),StringStruct('FileDescription','TURTO – Měsíční přehledy'),StringStruct('FileVersion','1.0.1'),StringStruct('InternalName','TURTO_Mesicni_Prehledy'),StringStruct('OriginalFilename','TURTO_Mesicni_Prehledy.exe'),StringStruct('ProductName','TURTO – Měsíční přehledy'),StringStruct('ProductVersion','1.0.1')])]),VarFileInfo([VarStruct('Translation',[1029,1200])])])\n",
        encoding='utf-8',
    )

    dist_main = pathlib.Path('_dist_main_101').resolve()
    work_main = pathlib.Path('_work_main_101').resolve()
    spec_main = pathlib.Path('_spec_main_101').resolve()
    for p in (dist_main, work_main, spec_main):
        shutil.rmtree(p, ignore_errors=True)
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
    main_exe = main_dir/MAIN_EXE
    assert main_exe.exists() and (main_dir/'_internal').is_dir()
    shutil.copytree(stage/'assets', main_dir/'assets', dirs_exist_ok=True)

    smoke_data = pathlib.Path('_smoke_data_101').resolve()
    shutil.rmtree(smoke_data, ignore_errors=True)
    env = os.environ.copy()
    env['TURTO_REPORTING_DATA_ROOT'] = str(smoke_data)
    cp = subprocess.run([str(main_exe), '--turto-self-test'], cwd=main_dir, env=env, timeout=60)
    assert cp.returncode == 0, cp.returncode

    dist_helper = pathlib.Path('_dist_helper_101').resolve()
    work_helper = pathlib.Path('_work_helper_101').resolve()
    spec_helper = pathlib.Path('_spec_helper_101').resolve()
    for p in (dist_helper, work_helper, spec_helper):
        shutil.rmtree(p, ignore_errors=True)
    cmd = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onefile',
        '--name', 'TURTO_Mesicni_Prehledy_Updater', '--icon', str((stage/'assets/app_icon.ico').resolve()),
        '--paths', str(stage.resolve()), '--distpath', str(dist_helper), '--workpath', str(work_helper),
        '--specpath', str(spec_helper), str(helper_source.resolve()),
    ]
    subprocess.run(cmd, check=True, cwd=stage)
    helper = dist_helper/UPDATER_EXE
    assert helper.exists() and helper.stat().st_size > 500_000

    app_dist = pathlib.Path('dist')/'TURTO Mesicni Prehledy'
    shutil.rmtree(app_dist, ignore_errors=True)
    shutil.copytree(main_dir, app_dist)
    shutil.copy2(helper, app_dist/UPDATER_EXE)
    shutil.copy2(ROOT/'README.txt', app_dist/'README.txt')

    iscc = find_iscc()
    iss = ROOT/'TURTO_Mesicni_Prehledy.iss'
    subprocess.run([str(iscc), f'/DMyAppVersion={VERSION}', str(iss.resolve())], check=True, cwd=REPO)
    setup = pathlib.Path('dist/reporting-installer')/SETUP_EXE
    assert setup.exists() and setup.stat().st_size > 1_000_000

    # Verify the installer itself works without elevation into a user-writable location.
    install_root = pathlib.Path('_installed_101').resolve()
    test_data = pathlib.Path('_installed_data_101').resolve()
    shutil.rmtree(install_root, ignore_errors=True)
    shutil.rmtree(test_data, ignore_errors=True)
    install_args = [str(setup.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', f'/DIR={install_root}']
    cp = subprocess.run(install_args, timeout=180)
    assert cp.returncode == 0, cp.returncode
    installed_exe = install_root/MAIN_EXE
    assert installed_exe.exists() and (install_root/UPDATER_EXE).exists()
    test_data.mkdir(parents=True, exist_ok=True)
    (test_data/'KEEP.txt').write_text('keep', encoding='utf-8')
    env = os.environ.copy()
    env['TURTO_REPORTING_DATA_ROOT'] = str(test_data)
    cp = subprocess.run([str(installed_exe), '--turto-self-test'], cwd=install_root, env=env, timeout=60)
    assert cp.returncode == 0, cp.returncode
    uninstaller = next(iter(sorted(install_root.glob('unins*.exe'))), None)
    assert uninstaller is not None
    cp = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], timeout=120)
    assert cp.returncode == 0, cp.returncode
    assert (test_data/'KEEP.txt').read_text(encoding='utf-8') == 'keep'

    # Bridge package for the existing 0.2.8 updater. The setup is embedded as safe src/*.py chunks.
    helper_source.unlink(missing_ok=True)
    setup_data = setup.read_bytes()
    setup_sha = hashlib.sha256(setup_data).hexdigest()
    for p in (stage/'src').glob('setup_payload_*.py'):
        p.unlink()
    chunk_size = 2*1024*1024
    for idx, start in enumerate(range(0, len(setup_data), chunk_size)):
        raw = setup_data[start:start+chunk_size]
        b64 = base64.b64encode(raw).decode('ascii')
        body = '\n'.join(textwrap.wrap(b64, 76))
        (stage/'src'/f'setup_payload_{idx:03d}.py').write_text(
            '# TURTO reporting 1.0.1 setup payload chunk\nDATA = """\n'+body+'\n"""\n',
            encoding='ascii',
        )
    (stage/'src/setup_payload_meta.py').write_text(
        f"SETUP_SHA256='{setup_sha}'\nSETUP_SIZE={len(setup_data)}\n",
        encoding='ascii',
    )
    clean_python_cache(stage)
    make_package_manifest(stage, VERSION)

    old_spec = importlib.util.spec_from_file_location('old_release_safety_101', old_safety_path)
    old = importlib.util.module_from_spec(old_spec)
    old_spec.loader.exec_module(old)
    old.validate_folder(stage)

    # End-to-end migration test: legacy 0.2.8 -> per-user 1.0.1 installer.
    legacy = pathlib.Path('_legacy_101')
    localapp = pathlib.Path('_localappdata_101').resolve()
    shutil.rmtree(legacy, ignore_errors=True)
    shutil.rmtree(localapp, ignore_errors=True)
    shutil.copytree(previous_dir, legacy)
    (legacy/'data').mkdir(exist_ok=True)
    (legacy/'data/KEEP.txt').write_text('legacy-data', encoding='utf-8')
    (legacy/'config.json').write_text('{"theme":"dark","keep":true}', encoding='utf-8')
    env = os.environ.copy()
    env['LOCALAPPDATA'] = str(localapp)
    env['TURTO_TRANSITION_TEST'] = '1'
    cp = subprocess.run([sys.executable, str((stage/'update_installer.py').resolve()), str(stage.resolve()), str(legacy.resolve())], env=env, timeout=300)
    assert cp.returncode == 0, cp.returncode
    migrated = localapp/'TURTO'/'MesicniPrehledy'
    assert (migrated/'data/KEEP.txt').read_text(encoding='utf-8') == 'legacy-data'
    assert json.loads((migrated/'config.json').read_text(encoding='utf-8'))['keep'] is True
    migrated_install = localapp/'Programs'/'TURTO Mesicni Prehledy'
    assert (migrated_install/MAIN_EXE).exists()

    update_buf = io.BytesIO()
    with zipfile.ZipFile(update_buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if not p.is_file():
                continue
            rel = p.relative_to(stage).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026,9,13,21,45,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    update_data = update_buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(update_data)) as z:
        assert z.testzip() is None
    assert len(update_data) < 120*1024*1024, len(update_data)

    release_dir = pathlib.Path('releases')/VERSION
    release_dir.mkdir(parents=True, exist_ok=True)
    update_path = release_dir/f'TURTO_update_{VERSION}.zip'
    update_path.write_bytes(update_data)
    shutil.copy2(setup, release_dir/SETUP_EXE)
    pathlib.Path('_v101_update_sha.txt').write_text(hashlib.sha256(update_data).hexdigest(), encoding='ascii')
    pathlib.Path('_v101_setup_sha.txt').write_text(setup_sha, encoding='ascii')
    print('TURTO_1_0_1_OK', 'update=', len(update_data), 'setup=', len(setup_data), 'chunks=', len(list((stage/'src').glob('setup_payload_*.py'))))


if __name__ == '__main__':
    run()
