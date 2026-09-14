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
import time
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
REPO = ROOT.parents[1]
VERSION = '1.0.2'
MAIN_EXE = 'TURTO_Mesicni_Prehledy.exe'
UPDATER_EXE = 'TURTO_Mesicni_Prehledy_Updater.exe'
SETUP_EXE = f'TURTO_Mesicni_Prehledy_Setup_{VERSION}.exe'


def clean(root: pathlib.Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def clean_python_cache(root: pathlib.Path) -> None:
    for cache in list(root.rglob('__pycache__')):
        shutil.rmtree(cache, ignore_errors=True)
    for pyc in list(root.rglob('*.pyc')):
        pyc.unlink(missing_ok=True)


def find_iscc() -> pathlib.Path:
    candidates=[]
    for key in ('ProgramFiles(x86)','ProgramFiles'):
        base=os.environ.get(key)
        if base:
            for ver in ('6','7'):
                candidates.append(pathlib.Path(base)/f'Inno Setup {ver}'/'ISCC.exe')
    for p in candidates:
        if p.exists():return p
    raise FileNotFoundError('ISCC.exe nebyl nalezen.')


def download(url: str, expected_sha: str, target: pathlib.Path) -> bytes:
    req=urllib.request.Request(url,headers={'User-Agent':'TURTO-Reporting-Release'})
    with urllib.request.urlopen(req,timeout=120) as r:
        data=r.read()
    digest=hashlib.sha256(data).hexdigest()
    assert digest.lower()==expected_sha.lower(), (target.name,digest,expected_sha)
    target.write_bytes(data)
    return data


def make_package_manifest(stage: pathlib.Path) -> dict:
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='package_files.json'}
    (stage/'package_files.json').write_text(
        json.dumps({'app_id':'cz.turto.mesicni-prehledy','version':VERSION,'files':files},ensure_ascii=False,indent=2)+'\n',
        encoding='utf-8')
    return files


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


def test_graph_rules(stage: pathlib.Path) -> None:
    sys.path.insert(0,str(stage.resolve()))
    try:
        from src.charts import _display_colors, MIN_DONUT_DEGREES
        from src.constants import COLORS
        from src import report_svg
        sales=[{'label':'Milan'},{'label':'Honza'},{'label':'Jirka'},{'label':'Nezařazené'}]
        cmap=_display_colors(sales)
        assert cmap['Milan']==COLORS['teal']
        assert cmap['Honza']==COLORS['blue']
        assert cmap['Jirka']==COLORS['amber']
        assert len(set(cmap.values()))==4
        generic=_display_colors([{'label':f'Firma {i}'} for i in range(1,7)])
        assert len(set(generic.values()))==6
        # Reprodukce screenshotu: 227 Kč z cca 3,33 mil. Kč je prakticky nulový řez.
        # Takový extent nesmí být předán Tk Canvas, kde může po zaokrouhlení překreslit celý donut.
        tiny_degrees=359.99*227/3_332_327
        assert tiny_degrees < MIN_DONUT_DEGREES
        sample=[
            {'name':'Milan','revenue':1_666_481},
            {'name':'Honza','revenue':902_523},
            {'name':'Jirka','revenue':763_095},
            {'name':'Nezařazené','revenue':227},
        ]
        svg=report_svg.shares(sample,'revenue','name',w=700,h=220)
        assert report_svg.TEAL in svg and report_svg.BLUE in svg and report_svg.AMBER in svg and '#8291A6' in svg
        bars=report_svg.bars([{'customer':f'Zákazník {i}','profit':1000-i*50} for i in range(6)],'profit','customer',w=700,h=220,limit=6)
        for color in report_svg.PALETTE[:6]:
            assert color in bars
    finally:
        try:sys.path.remove(str(stage.resolve()))
        except ValueError:pass
        for key in list(sys.modules):
            if key=='src' or key.startswith('src.'):
                sys.modules.pop(key,None)


def zip_deterministic(stage: pathlib.Path) -> bytes:
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(stage.rglob('*')):
            if not p.is_file():continue
            rel=p.relative_to(stage).as_posix()
            info=zipfile.ZipInfo(rel,date_time=(2026,9,14,18,45,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644 << 16
            z.writestr(info,p.read_bytes())
    data=buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
    return data


def run() -> None:
    os.chdir(REPO)
    sys.dont_write_bytecode=True
    ready=json.loads((ROOT/'ready.json').read_text(encoding='utf-8'))
    assert ready['version']==VERSION

    previous_manifest=json.loads((REPO/'update_manifest.json').read_text(encoding='utf-8'))
    assert previous_manifest['version']=='1.0.1', previous_manifest['version']

    previous_zip_path=pathlib.Path('_previous_102.zip')
    previous=download(previous_manifest['url'],previous_manifest['sha256'],previous_zip_path)
    previous_dir=pathlib.Path('_previous_102')
    clean(previous_dir);previous_dir.mkdir()
    with zipfile.ZipFile(io.BytesIO(previous)) as z:
        assert z.testzip() is None
        z.extractall(previous_dir)

    stage=pathlib.Path('_stage_102')
    clean(stage);shutil.copytree(previous_dir,stage)
    # Instalační payload 1.0.1 byl pouze most pro starou 0.2.8 a do dalších buildů nepatří.
    for p in (stage/'src').glob('setup_payload_*.py'):
        p.unlink(missing_ok=True)
    (stage/'src/setup_payload_meta.py').unlink(missing_ok=True)
    (stage/'update_installer.py').unlink(missing_ok=True)
    (stage/'package_files.json').unlink(missing_ok=True)
    for p in stage.glob('ZMENY_*.txt'):
        p.unlink(missing_ok=True)

    from patch_graphs import apply as apply_graph_patch
    apply_graph_patch(stage)
    patch_version(stage)
    note=(ROOT/'ZMENY_1.0.2.txt').read_text(encoding='utf-8')
    (stage/'ZMENY_1.0.2.txt').write_text(note,encoding='utf-8')
    changelog=stage/'CHANGELOG.txt'
    if changelog.exists():changelog.write_text(note.rstrip()+'\n\n'+changelog.read_text(encoding='utf-8'),encoding='utf-8')
    clean_python_cache(stage)
    for p in list(stage.rglob('*.py'))+list(stage.rglob('*.pyw')):
        compile(p.read_bytes(),p.as_posix(),'exec')
    test_graph_rules(stage)

    version_file=pathlib.Path('_turto_reporting_102_version.txt')
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=(1,0,2,0),prodvers=(1,0,2,0),mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),kids=[StringFileInfo([StringTable('040504B0',[StringStruct('CompanyName','TURTO s.r.o.'),StringStruct('FileDescription','TURTO – Měsíční přehledy'),StringStruct('FileVersion','1.0.2'),StringStruct('InternalName','TURTO_Mesicni_Prehledy'),StringStruct('OriginalFilename','TURTO_Mesicni_Prehledy.exe'),StringStruct('ProductName','TURTO – Měsíční přehledy'),StringStruct('ProductVersion','1.0.2')])]),VarFileInfo([VarStruct('Translation',[1029,1200])])])\n",
        encoding='utf-8')

    dist_main=pathlib.Path('_dist_main_102').resolve();work_main=pathlib.Path('_work_main_102').resolve();spec_main=pathlib.Path('_spec_main_102').resolve()
    for p in (dist_main,work_main,spec_main):clean(p)
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
         '--name','TURTO_Mesicni_Prehledy','--icon',str((stage/'assets/app_icon.ico').resolve()),
         '--version-file',str(version_file.resolve()),'--add-data',str((stage/'assets').resolve())+os.pathsep+'assets',
         '--collect-all','xlsxwriter','--distpath',str(dist_main),'--workpath',str(work_main),'--specpath',str(spec_main),
         str((stage/'app.pyw').resolve())]
    subprocess.run(cmd,check=True,cwd=stage)
    main_dir=dist_main/'TURTO_Mesicni_Prehledy';main_exe=main_dir/MAIN_EXE
    assert main_exe.exists() and (main_dir/'_internal').is_dir()
    shutil.copytree(stage/'assets',main_dir/'assets',dirs_exist_ok=True)

    smoke_data=pathlib.Path('_smoke_data_102').resolve();clean(smoke_data)
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(smoke_data)
    cp=subprocess.run([str(main_exe),'--turto-self-test'],cwd=main_dir,env=env,timeout=60)
    assert cp.returncode==0,cp.returncode

    # Updater helper remains intentionally compatible with 1.0.1.
    helper_source=pathlib.Path('_native_update_helper_102.py')
    helper_source.write_bytes((REPO/'release_sources/1.0.1/native_update_helper.py.txt').read_bytes())
    dist_helper=pathlib.Path('_dist_helper_102').resolve();work_helper=pathlib.Path('_work_helper_102').resolve();spec_helper=pathlib.Path('_spec_helper_102').resolve()
    for p in (dist_helper,work_helper,spec_helper):clean(p)
    cmd=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onefile',
         '--name','TURTO_Mesicni_Prehledy_Updater','--icon',str((stage/'assets/app_icon.ico').resolve()),
         '--paths',str(stage.resolve()),'--distpath',str(dist_helper),'--workpath',str(work_helper),'--specpath',str(spec_helper),str(helper_source.resolve())]
    subprocess.run(cmd,check=True,cwd=stage)
    helper=dist_helper/UPDATER_EXE
    assert helper.exists() and helper.stat().st_size>500_000

    app_dist=pathlib.Path('dist')/'TURTO Mesicni Prehledy'
    clean(app_dist);shutil.copytree(main_dir,app_dist)
    shutil.copy2(helper,app_dist/UPDATER_EXE)
    if (stage/'README.txt').exists():shutil.copy2(stage/'README.txt',app_dist/'README.txt')

    iscc=find_iscc();iss=ROOT/'TURTO_Mesicni_Prehledy.iss'
    subprocess.run([str(iscc),f'/DMyAppVersion={VERSION}',str(iss.resolve())],check=True,cwd=REPO)
    setup=pathlib.Path('dist/reporting-installer')/SETUP_EXE
    assert setup.exists() and setup.stat().st_size>1_000_000

    # Normální aktualizační balíček pro nainstalovanou 1.0.1: jen runtime, žádná uživatelská data.
    update_stage=pathlib.Path('_update_stage_102')
    clean(update_stage);update_stage.mkdir()
    shutil.copy2(main_exe,update_stage/MAIN_EXE)
    shutil.copytree(main_dir/'_internal',update_stage/'_internal')
    shutil.copytree(main_dir/'assets',update_stage/'assets')
    make_package_manifest(update_stage)

    old_spec=importlib.util.spec_from_file_location('old_release_safety_102',stage/'src/release_safety.py')
    old=importlib.util.module_from_spec(old_spec);old_spec.loader.exec_module(old)
    spec=old.validate_folder(update_stage)
    assert spec['version']==VERSION

    # End-to-end test: skutečný instalátor 1.0.1 -> jeho updater -> 1.0.2.
    previous_setup=pathlib.Path('_previous_setup_101.exe')
    previous_setup_data=download(previous_manifest['installer_url'],previous_manifest['installer_sha256'],previous_setup)
    assert len(previous_setup_data)>1_000_000
    prev_install=pathlib.Path('_installed_prev_102').resolve();prev_data=pathlib.Path('_installed_prev_data_102').resolve()
    clean(prev_install);clean(prev_data)
    args=[str(previous_setup.resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={prev_install}']
    cp=subprocess.run(args,timeout=180);assert cp.returncode==0,cp.returncode
    prev_exe=prev_install/MAIN_EXE;prev_helper=prev_install/UPDATER_EXE
    assert prev_exe.exists() and prev_helper.exists()
    prev_data.mkdir(parents=True,exist_ok=True);(prev_data/'KEEP.txt').write_text('keep-data',encoding='utf-8')
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(prev_data)
    cp=subprocess.run([str(prev_exe),'--turto-self-test'],cwd=prev_install,env=env,timeout=60);assert cp.returncode==0,cp.returncode
    cp=subprocess.run([str(prev_helper),str(update_stage.resolve()),str(prev_install.resolve())],cwd=prev_install,env=env,timeout=180)
    assert cp.returncode==0,cp.returncode
    time.sleep(2)
    subprocess.run(['taskkill','/F','/IM',MAIN_EXE],capture_output=True,text=True)
    cp=subprocess.run([str(prev_exe),'--turto-self-test'],cwd=prev_install,env=env,timeout=60);assert cp.returncode==0,cp.returncode
    assert (prev_data/'KEEP.txt').read_text(encoding='utf-8')=='keep-data'
    old_uninstaller=next(iter(sorted(prev_install.glob('unins*.exe'))),None);assert old_uninstaller is not None
    cp=subprocess.run([str(old_uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],timeout=120);assert cp.returncode==0,cp.returncode
    assert (prev_data/'KEEP.txt').read_text(encoding='utf-8')=='keep-data'

    # Fresh-install / uninstall safety test for 1.0.2.
    install_root=pathlib.Path('_installed_102').resolve();test_data=pathlib.Path('_installed_data_102').resolve()
    clean(install_root);clean(test_data)
    args=[str(setup.resolve()),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',f'/DIR={install_root}']
    cp=subprocess.run(args,timeout=180);assert cp.returncode==0,cp.returncode
    installed_exe=install_root/MAIN_EXE
    assert installed_exe.exists() and (install_root/UPDATER_EXE).exists()
    test_data.mkdir(parents=True,exist_ok=True);(test_data/'KEEP.txt').write_text('keep',encoding='utf-8')
    env=os.environ.copy();env['TURTO_REPORTING_DATA_ROOT']=str(test_data)
    cp=subprocess.run([str(installed_exe),'--turto-self-test'],cwd=install_root,env=env,timeout=60);assert cp.returncode==0,cp.returncode
    uninstaller=next(iter(sorted(install_root.glob('unins*.exe'))),None);assert uninstaller is not None
    cp=subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],timeout=120);assert cp.returncode==0,cp.returncode
    assert (test_data/'KEEP.txt').read_text(encoding='utf-8')=='keep'

    update_data=zip_deterministic(update_stage)
    assert len(update_data)<120*1024*1024
    release_dir=pathlib.Path('releases')/VERSION;release_dir.mkdir(parents=True,exist_ok=True)
    update_path=release_dir/f'TURTO_update_{VERSION}.zip';update_path.write_bytes(update_data)
    shutil.copy2(setup,release_dir/SETUP_EXE)
    pathlib.Path('_v102_update_sha.txt').write_text(hashlib.sha256(update_data).hexdigest(),encoding='ascii')
    pathlib.Path('_v102_setup_sha.txt').write_text(hashlib.sha256(setup.read_bytes()).hexdigest(),encoding='ascii')
    print('TURTO_1_0_2_OK','update=',len(update_data),'setup=',setup.stat().st_size)


if __name__=='__main__':
    run()
