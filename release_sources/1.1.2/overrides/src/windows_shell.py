"""Native Windows shortcut repair. Never changes application sources or business data."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

APP_ID='cz.turto.mesicni-prehledy'
APP_NAME='TURTO – Měsíční přehledy'
MAIN_EXE='TURTO_Mesicni_Prehledy.exe'
PROPERTY_FMT='9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3'


class GUID(ctypes.Structure):
    _fields_=[('a',ctypes.c_uint32),('b',ctypes.c_uint16),('c',ctypes.c_uint16),('d',ctypes.c_ubyte*8)]
    @classmethod
    def make(cls,value):return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

class PROPERTYKEY(ctypes.Structure):
    _fields_=[('fmtid',GUID),('pid',ctypes.c_uint32)]

class PVUNION(ctypes.Union):
    _fields_=[('text',ctypes.c_void_p),('storage',ctypes.c_ubyte*(16 if ctypes.sizeof(ctypes.c_void_p)==8 else 8))]

class PROPVARIANT(ctypes.Structure):
    _anonymous_=('value',)
    _fields_=[('vt',ctypes.c_uint16),('reserved',ctypes.c_uint16*3),('value',PVUNION)]


def checked(hr):
    if hr<0:raise OSError(f'Windows Shell HRESULT 0x{hr & 0xffffffff:08X}')
    return hr


def method(ptr,index,restype,*argtypes):
    table=ctypes.cast(ptr,ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype,ctypes.c_void_p,*argtypes)(table[index])


def release(ptr):
    if ptr:method(ptr,2,ctypes.c_ulong)(ptr)


def query(ptr,iid):
    result=ctypes.c_void_p();guid=GUID.make(iid)
    checked(method(ptr,0,ctypes.c_long,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p))(ptr,ctypes.byref(guid),ctypes.byref(result)))
    return result


@contextmanager
def com_scope():
    if sys.platform!='win32':raise OSError('Oprava zástupců je dostupná pouze ve Windows.')
    ole=ctypes.windll.ole32
    ole.CoInitializeEx.argtypes=[ctypes.c_void_p,ctypes.c_uint32];ole.CoInitializeEx.restype=ctypes.c_long
    hr=ole.CoInitializeEx(None,2)
    if hr<0 and (hr & 0xffffffff)!=0x80010106:checked(hr)
    try:yield
    finally:
        if hr>=0:ole.CoUninitialize()


def property_string(store,pid,value):
    key=PROPERTYKEY(GUID.make(PROPERTY_FMT),pid);pv=PROPVARIANT()
    buf=None
    if value is not None:
        buf=ctypes.create_unicode_buffer(str(value));pv.vt=31;pv.text=ctypes.cast(buf,ctypes.c_void_p)
    checked(method(store,6,ctypes.c_long,ctypes.POINTER(PROPERTYKEY),ctypes.POINTER(PROPVARIANT))(store,ctypes.byref(key),ctypes.byref(pv)))


def get_property_string(store,pid):
    key=PROPERTYKEY(GUID.make(PROPERTY_FMT),pid);pv=PROPVARIANT()
    try:
        checked(method(store,5,ctypes.c_long,ctypes.POINTER(PROPERTYKEY),ctypes.POINTER(PROPVARIANT))(store,ctypes.byref(key),ctypes.byref(pv)))
        return ctypes.wstring_at(pv.text) if pv.vt==31 and pv.text else ''
    finally:
        ctypes.windll.ole32.PropVariantClear(ctypes.byref(pv))


class ShellLink:
    def __init__(self,path=None):
        self.ptr=ctypes.c_void_p();self.persist=None;self.store=None
        clsid=GUID.make('00021401-0000-0000-C000-000000000046');iid=GUID.make('000214F9-0000-0000-C000-000000000046')
        create=ctypes.windll.ole32.CoCreateInstance
        create.argtypes=[ctypes.POINTER(GUID),ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(GUID),ctypes.POINTER(ctypes.c_void_p)];create.restype=ctypes.c_long
        checked(create(ctypes.byref(clsid),None,1,ctypes.byref(iid),ctypes.byref(self.ptr)))
        try:
            self.persist=query(self.ptr,'0000010B-0000-0000-C000-000000000046')
            self.store=query(self.ptr,'886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99')
            if path is not None:
                checked(method(self.persist,5,ctypes.c_long,ctypes.c_wchar_p,ctypes.c_uint32)(self.persist,str(path),0))
        except Exception:self.close();raise
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        for name in ('store','persist','ptr'):
            ptr=getattr(self,name,None)
            if ptr:release(ptr);setattr(self,name,None)
    def _get_text(self,index):
        buf=ctypes.create_unicode_buffer(32768)
        checked(method(self.ptr,index,ctypes.c_long,ctypes.c_wchar_p,ctypes.c_int)(self.ptr,buf,len(buf)))
        return buf.value
    def data(self):
        buf=ctypes.create_unicode_buffer(32768)
        checked(method(self.ptr,3,ctypes.c_long,ctypes.c_wchar_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32)(self.ptr,buf,len(buf),None,4))
        return {'target':buf.value,'arguments':self._get_text(10),'working_dir':self._get_text(8),'app_id':get_property_string(self.store,5)}
    def configure(self,target,arguments='',working_dir='',app_id=APP_ID):
        for index,value in [(20,target),(11,arguments),(9,working_dir),(7,APP_NAME)]:
            checked(method(self.ptr,index,ctypes.c_long,ctypes.c_wchar_p)(self.ptr,str(value)))
        checked(method(self.ptr,17,ctypes.c_long,ctypes.c_wchar_p,ctypes.c_int)(self.ptr,str(target),0))
        # Native executable shortcuts are the authoritative relaunch source.
        for pid in (2,3,4):property_string(self.store,pid,None)
        property_string(self.store,5,app_id)
        checked(method(self.store,7,ctypes.c_long)(self.store))
    def save(self,path):
        checked(method(self.persist,6,ctypes.c_long,ctypes.c_wchar_p,ctypes.c_int)(self.persist,str(path),1))


def read_link(path):
    with ShellLink(path) as link:return link.data()


def write_link(path,target,arguments='',working_dir='',app_id=APP_ID):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.turto-link-'+uuid.uuid4().hex+'.lnk')
    try:
        with ShellLink(path if path.exists() else None) as link:
            link.configure(target,arguments,working_dir,app_id);link.save(temp)
        check=read_link(temp)
        if os.path.normcase(check['target'])!=os.path.normcase(str(target)) or check['arguments']!=arguments or check['app_id']!=app_id:
            raise OSError('Kontrola uloženého zástupce selhala.')
        os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def shell_folder(csidl):
    buf=ctypes.create_unicode_buffer(32768)
    fn=ctypes.windll.shell32.SHGetFolderPathW
    fn.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_wchar_p];fn.restype=ctypes.c_long
    checked(fn(None,csidl,None,0,buf));return Path(buf.value)


def command_args(arguments):
    if not arguments.strip():return []
    count=ctypes.c_int();fn=ctypes.windll.shell32.CommandLineToArgvW
    fn.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)];fn.restype=ctypes.POINTER(ctypes.c_wchar_p)
    values=fn('placeholder.exe '+arguments,ctypes.byref(count))
    if not values:return []
    try:return [values[i] for i in range(1,count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(values,ctypes.c_void_p))


def legacy_root(info):
    target=Path(os.path.expandvars(info['target']));name=target.name.lower()
    if name in ('python.exe','pythonw.exe','py.exe','pyw.exe'):
        candidates=[Path(os.path.expandvars(x)) for x in command_args(info['arguments']) if x.lower().endswith('app.pyw')]
    elif name in ('app.pyw','start_turto.bat'):
        candidates=[target]
    else:return None
    for app in candidates:
        if not app.is_absolute():app=Path(info['working_dir'])/app
        root=app.parent;constants=root/'src/constants.py'
        try:
            if not constants.is_file() or constants.stat().st_size>65536:continue
            text=constants.read_text(encoding='utf-8-sig')
            if re.search(r"APP_NAME\s*=\s*['\"]TURTO\s*[–-]\s*Měsíční přehledy['\"]",text):return root
        except (OSError,UnicodeError):continue
    return None


def is_our_link(info):
    name=Path(os.path.expandvars(info['target'])).name.lower()
    if name==MAIN_EXE.lower():return True
    # An application-like filename alone is insufficient for Python shortcuts.
    return legacy_root(info) is not None


def same_target(info,exe):
    return (os.path.normcase(os.path.abspath(info['target']))==os.path.normcase(str(exe))
            and not info['arguments'] and info['app_id']==APP_ID
            and os.path.normcase(os.path.abspath(info['working_dir']))==os.path.normcase(str(exe.parent)))


def repair_shortcuts(exe,*,programs,desktop,pinned,backup_root,notify=True):
    """Repair only identified TURTO links; archive each original before mutation."""
    exe=Path(exe).resolve()
    if not exe.is_file() or exe.name!=MAIN_EXE:raise ValueError('Aktuální spustitelný soubor TURTO nebyl nalezen.')
    programs=Path(programs);desktop=Path(desktop);pinned=Path(pinned)
    canonical=programs/APP_NAME/(APP_NAME+'.lnk')
    result={'target':str(exe),'canonical':str(canonical),'updated':[],'archived':[],'errors':[],'backup':None}
    backup=Path(backup_root)/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    originals=[]
    def archive(path,action):
        backup.mkdir(parents=True,exist_ok=True)
        name=hashlib.sha256(str(path).encode()).hexdigest()[:12]+'_'+path.name
        destination=backup/name;shutil.copy2(path,destination)
        if destination.read_bytes()!=path.read_bytes():raise OSError('Záloha zástupce není úplná.')
        originals.append({'path':str(path),'backup':str(destination),'action':action})
        (backup/'originals.json').write_text(json.dumps(originals,ensure_ascii=False,indent=2),encoding='utf-8')
        result['backup']=str(backup)
    with com_scope():
        candidates=[]
        for kind,folder in [('programs',programs),('desktop',desktop),('pinned',pinned)]:
            if not folder.exists():continue
            paths=folder.rglob('*.lnk') if kind=='programs' else folder.glob('*.lnk')
            for path in paths:
                try:
                    info=read_link(path)
                    if is_our_link(info):candidates.append((kind,path,info))
                except OSError:
                    # An unreadable unrelated link is not grounds to replace it.
                    continue
        if canonical.exists():
            info=read_link(canonical)
            if not is_our_link(info):raise ValueError('Na místě hlavního zástupce je jiný program; nebyl přepsán.')
            if not same_target(info,exe):archive(canonical,'replace');write_link(canonical,exe,working_dir=exe.parent);result['updated'].append(str(canonical))
        else:write_link(canonical,exe,working_dir=exe.parent);result['updated'].append(str(canonical))
        # The verified canonical link exists before any redundant entry is removed.
        assert same_target(read_link(canonical),exe)
        desktop_links=[p for kind,p,info in candidates if kind=='desktop']
        preferred=next((p for p in desktop_links if p.name==APP_NAME+'.lnk'),desktop_links[0] if desktop_links else None)
        for kind,path,info in candidates:
            if path==canonical:continue
            try:
                if kind=='programs' or (kind=='desktop' and path!=preferred):
                    archive(path,'remove-duplicate');path.unlink();result['archived'].append(str(path))
                elif not same_target(info,exe):
                    archive(path,'replace');write_link(path,exe,working_dir=exe.parent);result['updated'].append(str(path))
            except (OSError,ValueError) as exc:result['errors'].append({'path':str(path),'error':str(exc)})
        if notify and (result['updated'] or result['archived']):
            # Notify Explorer; no forced restart and no taskbar registry edits.
            fn=ctypes.windll.shell32.SHChangeNotify
            fn.argtypes=[ctypes.c_long,ctypes.c_uint,ctypes.c_void_p,ctypes.c_void_p]
            fn(0x08000000,0,None,None)
    return result


def repair_current_user(force=True):
    from .config import user_data_root
    from .constants import APP_VERSION
    if sys.platform!='win32' or not getattr(sys,'frozen',False):
        return {'errors':[{'error':'Oprava zástupců je určena pro nainstalovanou Windows aplikaci.'}]}
    exe=Path(sys.executable).resolve();data=user_data_root();marker=data/'windows-shortcuts.json'
    if not force:
        try:
            previous=json.loads(marker.read_text(encoding='utf-8'))
            if previous.get('version')==APP_VERSION and previous.get('target')==str(exe) and not previous.get('errors'):return previous
        except (OSError,ValueError):pass
    try:
        result=repair_shortcuts(exe,programs=shell_folder(2),desktop=shell_folder(16),
             pinned=shell_folder(26)/'Microsoft/Internet Explorer/Quick Launch/User Pinned/TaskBar',backup_root=data/'shortcut-backups')
    except Exception as exc:result={'target':str(exe),'updated':[],'archived':[],'errors':[{'error':str(exc)}]}
    result['version']=APP_VERSION
    marker.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
