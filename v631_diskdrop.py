# TURTO CRM 6.0.31 - Explorer CF_HDROP + Outlook virtual drop in one native target
import os, traceback
from pathlib import Path


def apply(M):
    def _log_path():
        try:
            p = Path(M.DATA_ROOT) / 'logs'
        except Exception:
            p = Path.home() / 'Documents' / 'TURTO Zakazky' / 'logs'
        p.mkdir(parents=True, exist_ok=True)
        return p / 'offer_drop_crash.log'

    def _log(stage, exc=None):
        try:
            from datetime import datetime
            with _log_path().open('a', encoding='utf-8') as f:
                f.write('\n[' + datetime.now().isoformat(timespec='seconds') + '] ' + str(stage) + '\n')
                if exc is not None:
                    f.write(repr(exc) + '\n' + traceback.format_exc() + '\n')
        except Exception:
            pass

    def _process_real_files(app, paths):
        from tkinter import messagebox
        good=[]; errors=[]; messages=0; attachments=0
        for raw in paths:
            try:
                p=Path(str(raw))
                if not p.exists():
                    errors.append(f'{p}: soubor nebyl nalezen'); continue
                ext=p.suffix.lower()
                if ext=='.msg':
                    r=M.process_offer_msg(app,p)
                    messages += 1
                    attachments += int((r or {}).get('attachments') or 0)
                    good.extend((r or {}).get('offers') or [])
                    errors.extend((r or {}).get('errors') or [])
                    for x in (r or {}).get('results') or []:
                        if isinstance(x,dict) and x.get('error'): errors.append(x.get('error'))
                elif ext=='.pdf':
                    good.append(M.process_offer_pdf(app,p))
                else:
                    errors.append(f'{p.name}: nepodporovaný formát')
            except Exception as exc:
                _log('Explorer file processing failed: '+str(raw), exc)
                errors.append(f'{Path(str(raw)).name}: {exc}')
        try: app.refresh_offers()
        except Exception: pass
        text=f'Zpracováno. Nabídky: {len(good)}'
        if messages: text += f'   •   MSG: {messages}   •   přílohy: {attachments}'
        if errors: text += '\n\nChyby:\n' + '\n'.join(errors[:12])
        try: messagebox.showinfo('Nabídky – přetažení', text, parent=app)
        except Exception: pass
        return good

    def _install_unified_target(app):
        if os.name != 'nt': return False
        try:
            import pythoncom, win32clipboard, win32con, win32com.server.policy
            from win32comext.shell import shell, shellcon
        except Exception as exc:
            _log('v631 imports failed', exc); return False

        try:
            hwnd=int(app.winfo_id())
            try: pythoncom.RevokeDragDrop(hwnd)
            except Exception: pass

            fmt_w=win32clipboard.RegisterClipboardFormat('FileGroupDescriptorW')
            fmt_a=win32clipboard.RegisterClipboardFormat('FileGroupDescriptor')

            def qget(obj, fmt, tymed):
                try:
                    obj.QueryGetData((fmt,None,pythoncom.DVASPECT_CONTENT,-1,tymed)); return True
                except Exception: return False

            def real_paths(obj):
                if not qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL): return []
                try:
                    data=obj.GetData((win32con.CF_HDROP,None,pythoncom.DVASPECT_CONTENT,-1,pythoncom.TYMED_HGLOBAL))
                    h=getattr(data,'data_handle',None)
                    if not h: return []
                    count=shell.DragQueryFileW(h,-1)
                    return [shell.DragQueryFileW(h,i) for i in range(count)]
                except Exception as exc:
                    _log('CF_HDROP extraction failed',exc); return []

            def virtual_outlook(obj):
                if qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL): return False
                return qget(obj,fmt_w,pythoncom.TYMED_HGLOBAL) or qget(obj,fmt_a,pythoncom.TYMED_HGLOBAL)

            class UnifiedDropTarget(win32com.server.policy.DesignatedWrapPolicy):
                _public_methods_=['DragEnter','DragOver','DragLeave','Drop']
                _com_interfaces_=[pythoncom.IID_IDropTarget]
                def __init__(self,owner):
                    self._wrap_(self); self.owner=owner; self.kind=None
                def DragEnter(self,obj,key_state,point,effect):
                    try:
                        if qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL): self.kind='files'
                        elif virtual_outlook(obj): self.kind='outlook'
                        else: self.kind=None
                        return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('v631 DragEnter failed',exc); self.kind=None; return shellcon.DROPEFFECT_NONE
                def DragOver(self,key_state,point,effect):
                    return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE
                def DragLeave(self): self.kind=None
                def Drop(self,obj,key_state,point,effect):
                    try:
                        kind=self.kind; self.kind=None
                        if kind=='files' or qget(obj,win32con.CF_HDROP,pythoncom.TYMED_HGLOBAL):
                            paths=real_paths(obj)
                            supported=[p for p in paths if Path(p).suffix.lower() in ('.pdf','.msg')]
                            if supported:
                                _log('Explorer drop accepted: '+', '.join(supported))
                                self.owner.after(120,lambda ps=tuple(supported):_process_real_files(self.owner,ps))
                                return shellcon.DROPEFFECT_COPY
                            return shellcon.DROPEFFECT_NONE
                        if kind=='outlook' or virtual_outlook(obj):
                            _log('Outlook virtual drop accepted by v631')
                            self.owner.after(650,self.owner.import_selected_outlook_offer)
                            return shellcon.DROPEFFECT_COPY
                        return shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('v631 Drop failed',exc); return shellcon.DROPEFFECT_NONE

            pythoncom.OleInitialize()
            target=UnifiedDropTarget(app)
            wrapped=pythoncom.WrapObject(target,pythoncom.IID_IDropTarget,pythoncom.IID_IDropTarget)
            pythoncom.RegisterDragDrop(hwnd,wrapped)
            app._v631_drop_target=target; app._v631_drop_target_wrapped=wrapped; app._v631_drop_hwnd=hwnd
            _log('v631 unified file/outlook drop target registered')
            return True
        except Exception as exc:
            _log('v631 unified target registration failed',exc); return False

    old_init=M.App.__init__
    def init(self,*a,**k):
        result=old_init(self,*a,**k)
        # Replace v630 target last.
        try:self.after(3000,lambda:_install_unified_target(self))
        except Exception:pass
        return result
    M.App.__init__=init
