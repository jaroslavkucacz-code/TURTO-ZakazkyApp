from __future__ import annotations

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
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
VERSION = '1.1.0'
MAIN_EXE = 'TURTO_Mesicni_Prehledy.exe'
OLD_HELPER = 'TURTO_Mesicni_Prehledy_Updater.exe'
SETUP_EXE = f'TURTO_Mesicni_Prehledy_Setup_{VERSION}.exe'
BASE_SOURCE_URL = 'https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/939c4ac189fd37b6aa98ea8528b553aaefee7093/releases/1.0.1/TURTO_update_1.0.1.zip'
BASE_SOURCE_SHA = '3892d1fa9ebc8864e0fdf006849b89f852f7e3be423d4d79c0aa12e7f790b258'
BASE_INSTALLER_URL = 'https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/939c4ac189fd37b6aa98ea8528b553aaefee7093/releases/1.0.1/TURTO_Mesicni_Prehledy_Setup_1.0.1.exe'
BASE_INSTALLER_SHA = 'e4aeef3a459b1c7a6d4d4bc4f98572a4bf43a7470326999fb178d9a894368994'


def clean(path: pathlib.Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def clean_python_cache(root: pathlib.Path) -> None:
    for p in list(root.rglob('__pycache__')):
        shutil.rmtree(p, ignore_errors=True)
    for p in list(root.rglob('*.pyc')):
        p.unlink(missing_ok=True)


def download(url: str, sha: str, target: pathlib.Path) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent':'TURTO-Reporting-Release'})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    digest = hashlib.sha256(data).hexdigest()
    assert digest.lower() == sha.lower(), (target.name, digest, sha)
    target.write_bytes(data)
    return data


def find_iscc() -> pathlib.Path:
    candidates=[]
    for key in ('ProgramFiles(x86)','ProgramFiles'):
        base=os.environ.get(key)
        if base:
            for ver in ('6','7'):
                candidates.append(pathlib.Path(base)/f'Inno Setup {ver}'/'ISCC.exe')
    for p in candidates:
        if p.exists(): return p
    raise FileNotFoundError('ISCC.exe nebyl nalezen.')


def patch_version(stage: pathlib.Path) -> None:
    constants=stage/'src/constants.py'
    text=constants.read_text(encoding='utf-8')
    text,n=re.subn(r"APP_VERSION = '[^']+'",f"APP_VERSION = '{VERSION}'",text,count=1)
    assert n==1
    constants.write_text(text,encoding='utf-8')
    app=stage/'app.pyw'
    text=app.read_text(encoding='utf-8')
    text,n=re.subn(r"if APP_VERSION != '[^']+':",f"if APP_VERSION != '{VERSION}':",text,count=1)
    assert n==1
    app.write_text(text,encoding='utf-8')


def make_package_manifest(stage: pathlib.Path) -> None:
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='package_files.json'}
    (stage/'package_files.json').write_text(
        json.dumps({'app_id':'cz.turto.mesicni-prehledy','version':VERSION,'files':files},ensure_ascii=False,indent=2)+'\n',
        encoding='utf-8')


def zip_deterministic(stage: pathlib.Path) -> bytes:
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if not p.is_file(): continue
            rel=p.relative_to(stage).as_posix()
            info=zipfile.ZipInfo(rel,date_time=(2026,9,14,19,15,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,p.read_bytes())
    data=buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
    return data


def graph_smoke(stage: pathlib.Path) -> None:
    sys.path.insert(0,str(stage.resolve()))
    try:
        from src.charts import _display_colors, MIN_DONUT_DEGREES
        from src.constants import COLORS
        cmap=_display_colors([{'label':'Milan'},{'label':'Honza'},{'label':'Jirka'},{'label':'Nezařazené'}])
        assert cmap['Milan']==COLORS['teal'] and cmap['Honza']==COLORS['blue'] and cmap['Jirka']==COLORS['amber']
        assert len(set(cmap.values()))==4
        assert 359.99*227/3_332_327 < MIN_DONUT_DEGREES
    finally:
        try: sys.path.remove(str(stage.resolve()))
        except ValueError: pass
        for key in list(sys.modules):
            if key=='src' or key.startswith('src.'):
                sys.modules.pop(key,None)


def run() -> None:
    os.chdir(REPO); sys.dont_write_bytecode=True

    base_zip=pathlib.Path('_base_source_110.zip')
    base=download(BASE_SOURCE_URL,BASE_SOURCE_SHA,base_zip)
    base_dir=pathlib.Path('_base_source_110');clean(base_dir);base_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        assert z.testzip() is None; z.extractall(base_dir)

    stage=pathlib.Path('_stage_110');clean(stage);shutil.copytree(base_dir,stage)
    for p in (stage/'src').glob('setup_payload_*.py'): p.unlink(missing_ok=True)
    (stage/'src/setup_payload_meta.py').unlink(missing_ok=True)
    (stage/'update_installer.py').unlink(missing_ok=True)
    (stage/'package_files.json').unlink(missing_ok=True)
    for p in stage.glob('ZMENY_*.txt'): p.unlink(missing_ok=True)

    # Zachovat všechny grafické opravy z 1.0.2.
    patch_path=REPO/'release_sources/1.0.2/patch_graphs.py'
    pspec=importlib.util.spec_from_file_location('turto_graph_patch_102',patch_path)
    patch=importlib.util.module_from_spec(pspec);pspec.loader.exec_module(patch)
    patch.apply(stage)

    # Nahradit blokovaný helper mechanismus installer-based updaterem.
    (stage/'src/updater.py').write_bytes((ROOT/'updater.py.txt').read_bytes())
    shutil.copytree(ROOT/'overrides',stage,dirs_exist_ok=True)
    patch_version(stage)
    note=(ROOT/'ZMENY_1.1.0.txt').read_text(encoding='utf-8')
    (stage/'ZMENY_1.1.0.txt').write_text(note,encoding='utf-8')
    changelog=stage/'CHANGELOG.txt'
    if changelog.exists(): changelog.write_text(note.rstrip()+'\n\n'+changelog.read_text(encoding='utf-8'),encoding='utf-8')
    clean_python_cache(stage)
    for p in list(stage.rglob('*.py'))+list(stage.rglob('*.pyw')):
        compile(p.read_bytes(),p.as_posix(),'exec')
    graph_smoke(stage)
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=stage,check=True)
    # Visible Windows UI and real Edge PDF export, using synthetic fixtures only.
    qa=pathlib.Path('releases/1.1.0/validation').resolve();qa.mkdir(parents=True,exist_ok=True)
    harness=ROOT/'visual_check.py'
    subprocess.run([sys.executable,str(harness.resolve()),str(stage.resolve()),str(qa)],check=True,timeout=180)
    source_stage=pathlib.Path('_source_110');clean(source_stage);shutil.copytree(stage,source_stage)
    clean_python_cache(source_stage)
    source_data=zip_deterministic(source_stage)
    pathlib.Path('releases/1.1.0/TURTO_source_1.1.0.zip').write_bytes(source_data)

    version_file=pathlib.Path('_turto_reporting_110_version.txt')
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(1,1,0,0),prodvers=(1,1,0,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040504B0',[StringStruct('CompanyName','TURTO s.r.o.'),StringStruct('FileDescription','TURTO – Měsíční přehledy'),StringStruct('FileVersion','1.1.0'),StringStruct('InternalName','TURTO_Mesicni_Prehledy'),StringStruct('OriginalFilename','TURTO_Mesicni_Prehledy.exe'),StringStruct('ProductName','TURTO – Měsíční přehledy'),StringStruct('ProductVersion','1.1.0')])]),VarFileInfo([VarStruct('Translation',[1029,1200])])])\n",
        encoding='utf-8')

    dist_main=pathlib.Path('_dist_main_110').resolve();work_main=pathlib.Path('_work_main_110').resolve();spec_main=pathlib.Path('_spec_main_110').resolve()
    for p in (dist_main,work_main,spec_main): clean(p)
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
         '--name','TURTO_Mesicni_Prehledy','--icon',str((stage/'assets/app_icon.ico').resolve()),
         '--version-file',str(version_file.resolve()),'--add-data',str((stage/'assets').resolve())+os.pathsep+'assets',
         '--collect-all','xlsxwriter','--distpath',str(dist_main),'--workpath',str(work_main),'--specpath',str(spec_main),
         str((stage/'app.pyw').resolve())]
    subprocess.run(cmd,check=True,cwd=stage)
    main_dir=dist_main/'TURTO_Mesicni_Prehledy';main_exe=main_dir/MAIN_EXE
    assert main_exe.exists() and (main_dir/'_internal').is_dir()
    shutil.copytree(stage/'assets',main_dir/'assets',dirs_exist_ok=True)

    smoke_data=pathlib.Path('_smoke_data_110').resolve();clean(smoke_data)
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(smoke_data)
    cp=subprocess.run([str(main_exe),'--turto-self-test'],cwd=main_dir,env=env,timeout=60)
    assert cp.returncode==0,cp.returncode
    cp=subprocess.run([str(main_exe),'--turto-ui-self-test'],cwd=main_dir,env=env,timeout=90)
    assert cp.returncode==0,cp.returncode

    app_dist=pathlib.Path('dist')/'TURTO Mesicni Prehledy';clean(app_dist);shutil.copytree(main_dir,app_dist)
    if (stage/'README.txt').exists(): shutil.copy2(stage/'README.txt',app_dist/'README.txt')
    assert not (app_dist/OLD_HELPER).exists()

    iscc=find_iscc();iss=ROOT/'TURTO_Mesicni_Prehledy.iss'
    subprocess.run([str(iscc),f'/DMyAppVersion={VERSION}',str(iss.resolve())],check=True,cwd=REPO)
    setup=pathlib.Path('dist/reporting-installer')/SETUP_EXE
    assert setup.exists() and setup.stat().st_size>1_000_000
    setup_sha=hashlib.sha256(setup.read_bytes()).hexdigest()

    # Fresh install bez elevace.
    install_root=pathlib.Path('_installed_110').resolve();test_data=pathlib.Path('_installed_data_110').resolve()
    clean(install_root);clean(test_data)
    args=[str(setup.resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={install_root}']
    cp=subprocess.run(args,timeout=180);assert cp.returncode==0,cp.returncode
    assert (install_root/MAIN_EXE).exists() and not (install_root/OLD_HELPER).exists()
    test_data.mkdir(parents=True,exist_ok=True);(test_data/'KEEP.txt').write_text('keep',encoding='utf-8')
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(test_data)
    cp=subprocess.run([str(install_root/MAIN_EXE),'--turto-self-test'],cwd=install_root,env=env,timeout=60);assert cp.returncode==0
    uninstaller=next(iter(sorted(install_root.glob('unins*.exe'))),None);assert uninstaller
    cp=subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],timeout=120);assert cp.returncode==0
    assert (test_data/'KEEP.txt').read_text(encoding='utf-8')=='keep'

    # Upgrade test: 1.0.1 obsahuje helper, 1.1.0 jej musí instalací odstranit.
    old_setup=pathlib.Path('_old_setup_101.exe')
    download(BASE_INSTALLER_URL,BASE_INSTALLER_SHA,old_setup)
    upgrade_root=pathlib.Path('_upgrade_110').resolve();upgrade_data=pathlib.Path('_upgrade_data_110').resolve()
    clean(upgrade_root);clean(upgrade_data)
    cp=subprocess.run([str(old_setup.resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={upgrade_root}'],timeout=180);assert cp.returncode==0
    assert (upgrade_root/OLD_HELPER).exists()
    upgrade_data.mkdir(parents=True,exist_ok=True);(upgrade_data/'KEEP.txt').write_text('upgrade-keep',encoding='utf-8')
    cp=subprocess.run([str(setup.resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={upgrade_root}'],timeout=180);assert cp.returncode==0
    assert (upgrade_root/MAIN_EXE).exists() and not (upgrade_root/OLD_HELPER).exists()
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(upgrade_data)
    cp=subprocess.run([str(upgrade_root/MAIN_EXE),'--turto-self-test'],cwd=upgrade_root,env=env,timeout=60);assert cp.returncode==0
    assert (upgrade_data/'KEEP.txt').read_text(encoding='utf-8')=='upgrade-keep'
    old_uninstaller=next(iter(sorted(upgrade_root.glob('unins*.exe'))),None);assert old_uninstaller
    subprocess.run([str(old_uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],timeout=120,check=True)

    # Runtime ZIP zůstává publikovaný jako kompatibilní fallback, ale 1.1.0+ preferuje installer_url.
    update_stage=pathlib.Path('_update_stage_110');clean(update_stage);update_stage.mkdir()
    shutil.copy2(main_exe,update_stage/MAIN_EXE)
    shutil.copytree(main_dir/'_internal',update_stage/'_internal')
    shutil.copytree(main_dir/'assets',update_stage/'assets')
    make_package_manifest(update_stage)
    rspec=importlib.util.spec_from_file_location('release_safety_110',stage/'src/release_safety.py')
    safety=importlib.util.module_from_spec(rspec);rspec.loader.exec_module(safety)
    spec=safety.validate_folder(update_stage);assert spec['version']==VERSION
    update_data=zip_deterministic(update_stage)

    release_dir=pathlib.Path('releases')/VERSION;release_dir.mkdir(parents=True,exist_ok=True)
    update_path=release_dir/f'TURTO_update_{VERSION}.zip';update_path.write_bytes(update_data)
    shutil.copy2(setup,release_dir/SETUP_EXE)
    pathlib.Path('_v110_update_sha.txt').write_text(hashlib.sha256(update_data).hexdigest(),encoding='ascii')
    pathlib.Path('_v110_setup_sha.txt').write_text(setup_sha,encoding='ascii')
    print('TURTO_1_1_0_OK', 'update=',len(update_data),'setup=',setup.stat().st_size)


if __name__=='__main__':
    run()
