# TURTO CRM 6.0.30 - Safe Offer Drop / Outlook OLE crash hardening
import os, traceback
from pathlib import Path


def apply(M):
    """Harden direct Outlook drag/drop so a failed OLE/COM handoff cannot take
    the whole CRM down. Normal PDF/MSG processing remains on the existing path.
    """

    def _log_path():
        try:
            p = Path(M.DATA_ROOT) / 'logs'
        except Exception:
            p = Path.home() / 'Documents' / 'TURTO Zakazky' / 'logs'
        p.mkdir(parents=True, exist_ok=True)
        return p / 'offer_drop_crash.log'

    def _log(stage, exc=None):
        try:
            with _log_path().open('a', encoding='utf-8') as f:
                from datetime import datetime
                f.write('\n[' + datetime.now().isoformat(timespec='seconds') + '] ' + str(stage) + '\n')
                if exc is not None:
                    f.write(repr(exc) + '\n')
                    f.write(traceback.format_exc() + '\n')
        except Exception:
            pass

    # Enable Python fatal-error trace output as well. This is intentionally kept
    # open for the lifetime of the application so a native access violation has
    # somewhere to write diagnostics before the interpreter disappears.
    def _enable_faulthandler(app):
        try:
            import faulthandler
            fh = _log_path().open('a', encoding='utf-8')
            faulthandler.enable(file=fh, all_threads=True)
            app._v630_fault_log_handle = fh
        except Exception as exc:
            _log('faulthandler init failed', exc)

    # Wrap the already working Outlook selection importer with an explicit COM
    # apartment lifetime. The v6.0.27 OLE target calls this method after Drop.
    old_import = getattr(M.App, 'import_selected_outlook_offer', None)
    if callable(old_import):
        def import_selected_safe(self):
            pycom = None
            try:
                if os.name == 'nt':
                    import pythoncom as pycom
                    pycom.CoInitialize()
                _log('Outlook import start')
                return old_import(self)
            except Exception as exc:
                _log('Outlook import exception', exc)
                try:
                    M.messagebox.showerror('Zpracování nabídky',
                        'E-mail se nepodařilo bezpečně převzít z Outlooku. CRM zůstává spuštěné.\n\n'
                        'Podrobnosti byly zapsány do offer_drop_crash.log.', parent=self)
                except Exception:
                    pass
                return []
            finally:
                try:
                    if pycom is not None:
                        pycom.CoUninitialize()
                except Exception:
                    pass
                _log('Outlook import end')
        M.App.import_selected_outlook_offer = import_selected_safe

    def _install_safe_ole_target(app):
        if os.name != 'nt':
            return False
        try:
            import pythoncom
            import win32clipboard
            import win32con
            import win32com.server.policy
            from win32comext.shell import shellcon
        except Exception as exc:
            _log('safe OLE imports failed', exc)
            return False

        try:
            hwnd = int(app.winfo_id())
            # Replace the v6.0.27 root target. If it is already gone, ignore it.
            try:
                pythoncom.RevokeDragDrop(hwnd)
            except Exception:
                pass

            fmt_w = win32clipboard.RegisterClipboardFormat('FileGroupDescriptorW')
            fmt_a = win32clipboard.RegisterClipboardFormat('FileGroupDescriptor')

            def qget(data_object, fmt, tymed):
                try:
                    data_object.QueryGetData((fmt, None, pythoncom.DVASPECT_CONTENT, -1, tymed))
                    return True
                except Exception:
                    return False

            def is_outlook_virtual(data_object):
                # Real files from Explorer expose CF_HDROP and belong to TkDND.
                # Outlook MailItem drags use FileGroupDescriptor/FileContents.
                if qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return False
                return (qget(data_object, fmt_w, pythoncom.TYMED_HGLOBAL) or
                        qget(data_object, fmt_a, pythoncom.TYMED_HGLOBAL))

            class SafeOutlookDropTarget(win32com.server.policy.DesignatedWrapPolicy):
                _public_methods_ = ['DragEnter', 'DragOver', 'DragLeave', 'Drop']
                _com_interfaces_ = [pythoncom.IID_IDropTarget]

                def __init__(self, owner):
                    self._wrap_(self)
                    self.owner = owner
                    self.accept = False

                def DragEnter(self, data_object, key_state, point, effect):
                    try:
                        self.accept = is_outlook_virtual(data_object)
                        return shellcon.DROPEFFECT_COPY if self.accept else shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('DragEnter failed', exc)
                        self.accept = False
                        return shellcon.DROPEFFECT_NONE

                def DragOver(self, key_state, point, effect):
                    return shellcon.DROPEFFECT_COPY if self.accept else shellcon.DROPEFFECT_NONE

                def DragLeave(self):
                    self.accept = False

                def Drop(self, data_object, key_state, point, effect):
                    try:
                        ok = self.accept or is_outlook_virtual(data_object)
                        self.accept = False
                        if not ok:
                            return shellcon.DROPEFFECT_NONE
                        _log('Outlook OLE Drop accepted; scheduling delayed import')
                        # Important: do not enter Outlook COM immediately after the
                        # OLE Drop callback. Let Outlook/Windows finish the native
                        # drag transaction first, then import the selected MailItem.
                        try:
                            self.owner.after(650, self.owner.import_selected_outlook_offer)
                        except Exception as exc:
                            _log('could not schedule Outlook import', exc)
                            return shellcon.DROPEFFECT_NONE
                        return shellcon.DROPEFFECT_COPY
                    except Exception as exc:
                        _log('Drop callback failed', exc)
                        return shellcon.DROPEFFECT_NONE

            pythoncom.OleInitialize()
            target = SafeOutlookDropTarget(app)
            wrapped = pythoncom.WrapObject(target, pythoncom.IID_IDropTarget, pythoncom.IID_IDropTarget)
            pythoncom.RegisterDragDrop(hwnd, wrapped)
            app._v630_ole_target = target
            app._v630_ole_target_wrapped = wrapped
            app._v630_ole_hwnd = hwnd
            _log('safe OLE target registered')
            return True
        except Exception as exc:
            _log('safe OLE registration failed', exc)
            return False

    # Ensure Tk callback exceptions are logged and shown instead of silently
    # disappearing. This does not replace the normal GUI; it only guards drops.
    def _install_tk_exception_guard(app):
        try:
            old_report = getattr(app, 'report_callback_exception', None)
            def report(exc_type, exc_value, exc_tb):
                try:
                    with _log_path().open('a', encoding='utf-8') as f:
                        f.write('\nTk callback exception:\n')
                        traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                except Exception:
                    pass
                try:
                    M.messagebox.showerror('Chyba aplikace',
                        'Při zpracování vstupu nastala chyba, ale CRM zůstává spuštěné.\n'
                        'Podrobnosti jsou v offer_drop_crash.log.', parent=app)
                except Exception:
                    if callable(old_report):
                        try: old_report(exc_type, exc_value, exc_tb)
                        except Exception: pass
            app.report_callback_exception = report
        except Exception as exc:
            _log('Tk exception guard failed', exc)

    old_init = M.App.__init__
    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try: self.after(1700, lambda: _enable_faulthandler(self))
        except Exception: pass
        try: self.after(1800, lambda: _install_tk_exception_guard(self))
        except Exception: pass
        # Run after v6.0.27 has installed its native target, then replace it.
        try: self.after(2300, lambda: _install_safe_ole_target(self))
        except Exception: pass
        return result
    M.App.__init__ = init
