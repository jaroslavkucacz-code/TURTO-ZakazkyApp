"""Windows release gate: real .lnk migration and ShellExecute relaunch."""
import ctypes
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

stage=Path(sys.argv[1]);exe=Path(sys.argv[2]).resolve();output=Path(sys.argv[3]);output.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(stage))
from src.windows_shell import (APP_ID,APP_NAME,MAIN_EXE,ShellLink,com_scope,read_link,write_link,repair_shortcuts,
                               GUID,checked,get_property_string,release,same_target)
from src.constants import APP_VERSION
from src.config import DEFAULT_CONFIG


def windows():
    user=ctypes.windll.user32;result=[]
    callback=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p)
    user.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
    def visit(hwnd,unused):
        title=ctypes.create_unicode_buffer(1024);user.GetWindowTextW(hwnd,title,len(title))
        if title.value==f'{APP_NAME}  {APP_VERSION}':result.append(hwnd)
        return 1
    user.EnumWindows.argtypes=[callback,ctypes.c_void_p];user.EnumWindows(callback(visit),None)
    return result


def window_properties(hwnd):
    fn=ctypes.windll.shell32.SHGetPropertyStoreForWindow
    fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];fn.restype=ctypes.c_long
    iid=GUID.make('886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99');store=ctypes.c_void_p()
    checked(fn(hwnd,ctypes.byref(iid),ctypes.byref(store)))
    try:return {pid:get_property_string(store,pid) for pid in (2,3,4,5)}
    finally:release(store)


checks=[]
with tempfile.TemporaryDirectory(prefix='turto_shortcuts_') as temp,com_scope():
    root=Path(temp)/'Příliš žluťoučký test';root.mkdir()
    programs=root/'Programs';desktop=root/'Desktop';pinned=root/'TaskBar';backup=root/'Backups'
    old=root/'Programky/APP_TURTO_PŘEHLEDY';(old/'src').mkdir(parents=True);(old/'data').mkdir()
    (old/'src/constants.py').write_text("APP_NAME = 'TURTO – Měsíční přehledy'\nAPP_VERSION = '0.2.8'\n",encoding='utf-8')
    (old/'app.pyw').write_text('raise RuntimeError("OLD VERSION MUST NOT RUN")\n',encoding='utf-8')
    (old/'data/turto_dashboard.db').write_bytes(b'OLD BUSINESS DATA KEEP EXACTLY')
    (old/'config.json').write_text('{"database_path":"data/turto_dashboard.db"}',encoding='utf-8')
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in old.rglob('*') if p.is_file()}
    python=Path(sys.executable).with_name('pythonw.exe');assert python.exists()
    native_old=root/'Old native'/MAIN_EXE;native_old.parent.mkdir();native_old.write_bytes(b'old exe marker')
    legacy=programs/'TURTO - Mesicni prehledy.lnk'
    duplicate=programs/'Old/TURTO copy.lnk'
    canonical=programs/APP_NAME/(APP_NAME+'.lnk')
    desk=desktop/'TURTO - Mesicni prehledy.lnk'
    desk_duplicate=desktop/(APP_NAME+'.lnk')
    pin=pinned/'TURTO - Mesicni prehledy.lnk'
    for path in (legacy,desk,pin):write_link(path,python,arguments=f'"{old / "app.pyw"}"',working_dir=old)
    write_link(canonical,exe,working_dir=exe.parent,app_id='')
    write_link(duplicate,native_old,working_dir=native_old.parent)
    write_link(desk_duplicate,native_old,working_dir=native_old.parent)
    # Same display name and python host must not identify another TURTO application.
    other=root/'CRM';(other/'src').mkdir(parents=True);(other/'app.pyw').write_text('pass',encoding='utf-8')
    (other/'src/constants.py').write_text("APP_NAME = 'TURTO CRM'",encoding='utf-8')
    unrelated=programs/'Other/TURTO - Mesicni prehledy.lnk'
    write_link(unrelated,python,arguments=f'"{other / "app.pyw"}"',working_dir=other,app_id='cz.turto.crm')
    unrelated_before=unrelated.read_bytes()
    result=repair_shortcuts(exe,programs=programs,desktop=desktop,pinned=pinned,backup_root=backup,notify=False)
    assert not result['errors'],result
    assert not legacy.exists() and not duplicate.exists()
    assert len(list(desktop.glob('*.lnk')))==1
    for path in [canonical,desk_duplicate,pin]:assert same_target(read_link(path),exe),(path,read_link(path))
    assert unrelated.read_bytes()==unrelated_before
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==sha for p,sha in before.items())
    originals=json.loads((Path(result['backup'])/'originals.json').read_text(encoding='utf-8'))
    assert len(originals)==6,len(originals)
    for item in originals:assert Path(item['backup']).exists()
    checks.append('Legacy Python 0.2.8, native duplicate, desktop and existing taskbar links repaired; unrelated CRM and all old data unchanged')
    second=repair_shortcuts(exe,programs=programs,desktop=desktop,pinned=pinned,backup_root=backup,notify=False)
    assert second['updated']==[] and second['archived']==[] and not second['errors'],second
    checks.append('Repeated repair makes no changes and keeps backup intact')
    write_link(legacy,python,arguments=f'"{old / "app.pyw"}"',working_dir=old)
    old_link=legacy.read_bytes()
    with patch('src.windows_shell.shutil.copy2',side_effect=PermissionError('Backup cannot be written')):
        failed=repair_shortcuts(exe,programs=programs,desktop=desktop,pinned=pinned,backup_root=backup,notify=False)
    assert failed['errors'] and legacy.read_bytes()==old_link
    legacy.unlink();checks.append('If backup cannot be written, the original shortcut stays unchanged')
    # Real Explorer launch of the repaired pinned .lnk, with isolated app data.
    data=root/'New app data';data.mkdir()
    (data/'windows-shortcuts.json').write_text(json.dumps({'version':APP_VERSION,'target':str(exe),'errors':[]}),encoding='utf-8')
    (data/'config.json').write_text(json.dumps(DEFAULT_CONFIG),encoding='utf-8')
    prev=os.environ.get('TURTO_REPORTING_DATA_ROOT');os.environ['TURTO_REPORTING_DATA_ROOT']=str(data)
    hwnds=[]
    try:
        assert not windows(),'Unexpected preexisting application window'
        os.startfile(str(pin))
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            hwnds=windows()
            if hwnds:break
            time.sleep(.1)
        assert hwnds,'Repaired pinned shortcut did not launch the current version'
        time.sleep(.3)
        properties=window_properties(hwnds[0])
        assert properties[5]==APP_ID,properties
        assert not properties[2] and not properties[3] and not properties[4],properties
        user=ctypes.windll.user32
        user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
        pid=ctypes.c_uint32();user.GetWindowThreadProcessId(hwnds[0],ctypes.byref(pid))
        kernel=ctypes.windll.kernel32;kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        process=kernel.OpenProcess(0x1000|0x100000,False,pid.value);assert process
        try:
            buf=ctypes.create_unicode_buffer(32768);length=ctypes.c_uint32(len(buf))
            kernel.QueryFullProcessImageNameW.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_uint32)]
            assert kernel.QueryFullProcessImageNameW(process,0,buf,ctypes.byref(length))
            assert Path(buf.value).resolve()==exe,(buf.value,exe)
            user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
            for hwnd in hwnds:user.PostMessageW(hwnd,0x0010,0,0)
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
            assert kernel.WaitForSingleObject(process,15000)==0,'App did not close'
            hwnds=[]
        finally:
            kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(process)
        checks.append('ShellExecute of repaired pinned .lnk opens actual 1.1.2 EXE, matching window AppUserModelID with no legacy relaunch command')
    finally:
        for hwnd in hwnds:ctypes.windll.user32.PostMessageW(hwnd,0x0010,0,0)
        if prev is None:os.environ.pop('TURTO_REPORTING_DATA_ROOT',None)
        else:os.environ['TURTO_REPORTING_DATA_ROOT']=prev
(output/'shortcut-checks.json').write_text(json.dumps({'result':'PASS','checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
print('TURTO_SHORTCUT_CHECKS_OK',len(checks))
