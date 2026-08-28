# TURTO CRM - consolidated safe Explorer/Outlook drop runtime
#
# This module is the single owner of native file/Outlook drag-and-drop,
# COM lifetime protection, callback diagnostics and fatal-error logging.
import os
import traceback
from pathlib import Path


def apply(M):
    def _log_path():
        try:
            root = Path(M.DATA_ROOT)
        except Exception:
            root = Path.home() / 'Documents' / 'TURTO Zakazky'
        path = root / 'logs' / 'offer_drop_crash.log'
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _log(stage, exc=None):
        try:
            from datetime import datetime
            with _log_path().open('a', encoding='utf-8') as handle:
                handle.write('\n[' + datetime.now().isoformat(timespec='seconds') + '] ' + str(stage) + '\n')
                if exc is not None:
                    handle.write(repr(exc) + '\n')
                    handle.write(traceback.format_exc() + '\n')
        except Exception:
            pass

    # Keep a Python-level diagnostic stream open for native failures.
    def _enable_faulthandler(app):
        try:
            import faulthandler
            handle = _log_path().open('a', encoding='utf-8')
            faulthandler.enable(file=handle, all_threads=True)
            app._offer_fault_log_handle = handle
        except Exception as exc:
            _log('faulthandler init failed', exc)

    # Outlook COM import gets one explicit apartment lifetime and one error path.
    old_import = getattr(M.App, 'import_selected_outlook_offer', None)
    if callable(old_import):
        def import_selected_safe(self):
            pythoncom = None
            try:
                if os.name == 'nt':
                    import pythoncom
                    pythoncom.CoInitialize()
                _log('Outlook import start')
                return old_import(self)
            except Exception as exc:
                _log('Outlook import exception', exc)
                try:
                    M.messagebox.showerror(
                        'Zpracování nabídky',
                        'E-mail se nepodařilo bezpečně převzít z Outlooku. CRM zůstává spuštěné.\n\n'
                        'Podrobnosti byly zapsány do offer_drop_crash.log.',
                        parent=self,
                    )
                except Exception:
                    pass
                return []
            finally:
                try:
                    if pythoncom is not None:
                        pythoncom.CoUninitialize()
                except Exception:
                    pass
                _log('Outlook import end')

        M.App.import_selected_outlook_offer = import_selected_safe

    # Log Tk callback exceptions instead of losing them behind the GUI loop.
    def _install_tk_exception_guard(app):
        try:
            old_report = getattr(app, 'report_callback_exception', None)

            def report(exc_type, exc_value, exc_tb):
                try:
                    with _log_path().open('a', encoding='utf-8') as handle:
                        handle.write('\nTk callback exception:\n')
                        traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
                except Exception:
                    pass
                try:
                    M.messagebox.showerror(
                        'Chyba aplikace',
                        'Při zpracování vstupu nastala chyba, ale CRM zůstává spuštěné.\n'
                        'Podrobnosti jsou v offer_drop_crash.log.',
                        parent=app,
                    )
                except Exception:
                    if callable(old_report):
                        try:
                            old_report(exc_type, exc_value, exc_tb)
                        except Exception:
                            pass

            app.report_callback_exception = report
        except Exception as exc:
            _log('Tk exception guard failed', exc)

    def _process_real_files(app, paths):
        # Prefer the shared batch runner when present (progress, cancel, background).
        batch = getattr(app, '_start_offer_batch', None)
        if callable(batch):
            try:
                batch(tuple(paths))
                return []
            except Exception as exc:
                _log('Batch runner failed; using direct fallback', exc)

        from tkinter import messagebox
        good = []
        errors = []
        messages = 0
        attachments = 0
        for raw in paths:
            try:
                path = Path(str(raw))
                if not path.exists():
                    errors.append(f'{path}: soubor nebyl nalezen')
                    continue
                ext = path.suffix.lower()
                if ext == '.msg':
                    result = M.process_offer_msg(app, path)
                    messages += 1
                    attachments += int((result or {}).get('attachments') or 0)
                    good.extend((result or {}).get('offers') or [])
                    errors.extend((result or {}).get('errors') or [])
                    for item in (result or {}).get('results') or []:
                        if isinstance(item, dict) and item.get('error'):
                            errors.append(str(item['error']))
                elif ext == '.pdf':
                    good.append(M.process_offer_pdf(app, path))
                else:
                    errors.append(f'{path.name}: nepodporovaný formát')
            except Exception as exc:
                _log('Explorer file processing failed: ' + str(raw), exc)
                errors.append(f'{Path(str(raw)).name}: {exc}')

        try:
            app.refresh_offers()
        except Exception:
            pass
        text = f'Zpracováno. Nabídky: {len(good)}'
        if messages:
            text += f'   •   MSG: {messages}   •   přílohy: {attachments}'
        if errors:
            text += '\n\nChyby:\n' + '\n'.join(errors[:12])
        try:
            messagebox.showinfo('Nabídky – přetažení', text, parent=app)
        except Exception:
            pass
        return good

    def _install_unified_target(app):
        if os.name != 'nt':
            return False
        try:
            import pythoncom
            import win32clipboard
            import win32con
            import win32com.server.policy
            from win32comext.shell import shell, shellcon
        except Exception as exc:
            _log('Unified drop imports failed', exc)
            return False

        try:
            hwnd = int(app.winfo_id())
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

            def real_paths(data_object):
                if not qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return []
                try:
                    data = data_object.GetData(
                        (win32con.CF_HDROP, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)
                    )
                    handle = getattr(data, 'data_handle', None)
                    if not handle:
                        return []
                    count = shell.DragQueryFileW(handle, -1)
                    return [shell.DragQueryFileW(handle, index) for index in range(count)]
                except Exception as exc:
                    _log('CF_HDROP extraction failed', exc)
                    return []

            def virtual_outlook(data_object):
                if qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return False
                return (
                    qget(data_object, fmt_w, pythoncom.TYMED_HGLOBAL)
                    or qget(data_object, fmt_a, pythoncom.TYMED_HGLOBAL)
                )

            class UnifiedDropTarget(win32com.server.policy.DesignatedWrapPolicy):
                _public_methods_ = ['DragEnter', 'DragOver', 'DragLeave', 'Drop']
                _com_interfaces_ = [pythoncom.IID_IDropTarget]

                def __init__(self, owner):
                    self._wrap_(self)
                    self.owner = owner
                    self.kind = None

                def DragEnter(self, data_object, key_state, point, effect):
                    try:
                        if qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                            self.kind = 'files'
                        elif virtual_outlook(data_object):
                            self.kind = 'outlook'
                        else:
                            self.kind = None
                        return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('Unified DragEnter failed', exc)
                        self.kind = None
                        return shellcon.DROPEFFECT_NONE

                def DragOver(self, key_state, point, effect):
                    return shellcon.DROPEFFECT_COPY if self.kind else shellcon.DROPEFFECT_NONE

                def DragLeave(self):
                    self.kind = None

                def Drop(self, data_object, key_state, point, effect):
                    try:
                        kind = self.kind
                        self.kind = None
                        if kind == 'files' or qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                            paths = real_paths(data_object)
                            supported = [p for p in paths if Path(p).suffix.lower() in ('.pdf', '.msg')]
                            if not supported:
                                return shellcon.DROPEFFECT_NONE
                            _log('Explorer drop accepted: ' + ', '.join(supported))
                            self.owner.after(120, lambda ps=tuple(supported): _process_real_files(self.owner, ps))
                            return shellcon.DROPEFFECT_COPY

                        if kind == 'outlook' or virtual_outlook(data_object):
                            _log('Outlook virtual drop accepted')
                            # Let Windows finish the OLE transaction before Outlook COM is entered.
                            self.owner.after(650, self.owner.import_selected_outlook_offer)
                            return shellcon.DROPEFFECT_COPY
                        return shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('Unified Drop failed', exc)
                        return shellcon.DROPEFFECT_NONE

            pythoncom.OleInitialize()
            target = UnifiedDropTarget(app)
            wrapped = pythoncom.WrapObject(target, pythoncom.IID_IDropTarget, pythoncom.IID_IDropTarget)
            pythoncom.RegisterDragDrop(hwnd, wrapped)
            app._offer_drop_target = target
            app._offer_drop_target_wrapped = wrapped
            app._offer_drop_hwnd = hwnd
            _log('Unified file/outlook drop target registered')
            return True
        except Exception as exc:
            _log('Unified target registration failed', exc)
            return False

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after(1700, lambda: _enable_faulthandler(self))
        except Exception:
            pass
        try:
            self.after(1800, lambda: _install_tk_exception_guard(self))
        except Exception:
            pass
        try:
            self.after(3000, lambda: _install_unified_target(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init
