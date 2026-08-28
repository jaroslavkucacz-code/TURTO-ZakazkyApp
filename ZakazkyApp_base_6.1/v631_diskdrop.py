# TURTO CRM - consolidated safe Explorer/Outlook drop runtime
#
# This module is the single owner of native file/Outlook drag-and-drop,
# Outlook OLE payload extraction, COM lifetime protection, callback diagnostics
# and fatal-error logging.
import os
import re
import struct
import tempfile
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

    def _safe_filename(value, fallback='outlook'):
        text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', str(value or '')).strip(' ._')
        return (text or fallback)[:140]

    # Keep a Python-level diagnostic stream open for native failures.
    def _enable_faulthandler(app):
        try:
            import faulthandler
            handle = _log_path().open('a', encoding='utf-8')
            faulthandler.enable(file=handle, all_threads=True)
            app._offer_fault_log_handle = handle
        except Exception as exc:
            _log('faulthandler init failed', exc)

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

    def _process_direct_files(app, paths, source_label='Přetažení'):
        from tkinter import messagebox

        good = []
        errors = []
        messages = 0
        attachments = 0
        excel_files = 0
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
                    excel_files += len((result or {}).get('excel_files') or [])
                    good.extend((result or {}).get('offers') or [])
                    errors.extend((result or {}).get('errors') or [])
                    for item in (result or {}).get('results') or []:
                        if isinstance(item, dict) and item.get('error'):
                            errors.append(str(item['error']))
                elif ext == '.pdf':
                    result = M.process_offer_pdf(app, path)
                    if isinstance(result, dict):
                        excel_files += len(result.get('excel_files') or [])
                    good.append(result)
                else:
                    errors.append(f'{path.name}: nepodporovaný formát')
            except Exception as exc:
                _log(source_label + ' processing failed: ' + str(raw), exc)
                errors.append(f'{Path(str(raw)).name}: {exc}')

        try:
            app.refresh_offers()
        except Exception:
            pass
        text = f'Zpracováno. Nabídky: {len(good)}'
        if messages:
            text += f'   •   MSG: {messages}   •   přílohy: {attachments}'
        if excel_files:
            text += f'   •   Excel: {excel_files}'
        if errors:
            text += '\n\nChyby / upozornění:\n' + '\n'.join(errors[:12])
        try:
            messagebox.showinfo('Nabídky – ' + source_label.lower(), text, parent=app)
        except Exception:
            pass
        return good

    def _process_real_files(app, paths):
        # Disk files can use the shared UI batch runner because their lifetime is
        # independent from the drag transaction.
        batch = getattr(app, '_start_offer_batch', None)
        if callable(batch):
            try:
                batch(tuple(paths))
                return []
            except Exception as exc:
                _log('Batch runner failed; using direct fallback', exc)
        return _process_direct_files(app, paths, 'přetažení')

    def _process_virtual_files(app, temp_dir, paths):
        # Outlook FileContents exists only while the OLE data object is alive.
        # The bytes are therefore materialized during Drop and processed here.
        try:
            return _process_direct_files(app, paths, 'Outlook')
        finally:
            try:
                temp_dir.cleanup()
            except Exception:
                pass

    def import_selected_outlook_offer(self):
        """Manual/whole-message Outlook import through one canonical MSG path."""
        from tkinter import messagebox

        if os.name != 'nt':
            return messagebox.showerror(
                'Přenos z Outlooku',
                'Přímý import z Outlooku je dostupný pouze ve Windows.',
                parent=self,
            )

        pythoncom = None
        temp_dir = None
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            _log('Outlook selected-message import start')
            try:
                outlook = win32com.client.GetActiveObject('Outlook.Application')
            except Exception:
                outlook = win32com.client.Dispatch('Outlook.Application')

            explorer = outlook.ActiveExplorer()
            selection = explorer.Selection if explorer is not None else None
            count = int(selection.Count) if selection is not None else 0
            if count < 1:
                raise RuntimeError('V Outlooku není vybraný žádný e-mail.')

            temp_dir = tempfile.TemporaryDirectory(prefix='turto_outlook_msg_')
            paths = []
            for index in range(1, count + 1):
                item = selection.Item(index)
                try:
                    if int(getattr(item, 'Class', 0)) != 43:  # olMail
                        continue
                except Exception:
                    pass
                subject = str(getattr(item, 'Subject', '') or f'outlook_{index}')
                path = Path(temp_dir.name) / (
                    _safe_filename(subject, f'outlook_{index}') + f'_{index}.msg'
                )
                try:
                    item.SaveAs(str(path), 9)  # olMSGUnicode
                except Exception:
                    item.SaveAs(str(path), 3)  # olMSG
                if path.exists() and path.stat().st_size > 0:
                    paths.append(path)

            if not paths:
                raise RuntimeError('Výběr Outlooku neobsahuje zpracovatelný e-mail.')

            result = _process_direct_files(self, paths, 'Outlook')
            return result
        except Exception as exc:
            _log('Outlook selected-message import failed', exc)
            messagebox.showerror(
                'Přenos z Outlooku',
                'E-mail se nepodařilo bezpečně převzít z Outlooku.\n\n'
                + str(exc)
                + '\n\nPodrobnosti jsou v offer_drop_crash.log.',
                parent=self,
            )
            return []
        finally:
            try:
                if temp_dir is not None:
                    temp_dir.cleanup()
            except Exception:
                pass
            try:
                if pythoncom is not None:
                    pythoncom.CoUninitialize()
            except Exception:
                pass
            _log('Outlook selected-message import end')

    M.App.import_selected_outlook_offer = import_selected_outlook_offer

    def _install_unified_target(app):
        if os.name != 'nt':
            return False
        try:
            import ctypes
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
            fmt_contents = win32clipboard.RegisterClipboardFormat('FileContents')

            def qget(data_object, fmt, tymed, index=-1):
                try:
                    data_object.QueryGetData(
                        (fmt, None, pythoncom.DVASPECT_CONTENT, index, tymed)
                    )
                    return True
                except Exception:
                    return False

            def medium_bytes(medium):
                data = getattr(medium, 'data', None)
                if isinstance(data, (bytes, bytearray, memoryview)):
                    return bytes(data)
                handle = getattr(medium, 'data_handle', None)
                if not handle:
                    return b''
                kernel32 = ctypes.windll.kernel32
                kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
                kernel32.GlobalSize.restype = ctypes.c_size_t
                kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
                size = int(kernel32.GlobalSize(handle) or 0)
                pointer = kernel32.GlobalLock(handle)
                if not pointer or size <= 0:
                    return b''
                try:
                    return ctypes.string_at(pointer, size)
                finally:
                    kernel32.GlobalUnlock(handle)

            def real_paths(data_object):
                if not qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return []
                try:
                    data = data_object.GetData(
                        (
                            win32con.CF_HDROP,
                            None,
                            pythoncom.DVASPECT_CONTENT,
                            -1,
                            pythoncom.TYMED_HGLOBAL,
                        )
                    )
                    handle = getattr(data, 'data_handle', None)
                    if not handle:
                        return []
                    count = shell.DragQueryFileW(handle, -1)
                    return [shell.DragQueryFileW(handle, index) for index in range(count)]
                except Exception as exc:
                    _log('CF_HDROP extraction failed', exc)
                    return []

            def descriptor_format(data_object):
                if qget(data_object, fmt_w, pythoncom.TYMED_HGLOBAL):
                    return fmt_w, True
                if qget(data_object, fmt_a, pythoncom.TYMED_HGLOBAL):
                    return fmt_a, False
                return None, False

            def virtual_descriptors(data_object):
                fmt, wide = descriptor_format(data_object)
                if fmt is None:
                    return []
                try:
                    medium = data_object.GetData(
                        (fmt, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)
                    )
                    blob = medium_bytes(medium)
                    if len(blob) < 4:
                        return []
                    count = struct.unpack_from('<I', blob, 0)[0]
                    descriptor_size = 592 if wide else 332
                    name_size = 520 if wide else 260
                    maximum = max(0, (len(blob) - 4) // descriptor_size)
                    count = min(count, maximum, 512)
                    result = []
                    for index in range(count):
                        start = 4 + index * descriptor_size
                        chunk = blob[start:start + descriptor_size]
                        raw_name = chunk[-name_size:]
                        if wide:
                            name = raw_name.decode('utf-16le', errors='ignore').split('\x00', 1)[0]
                        else:
                            name = raw_name.split(b'\x00', 1)[0].decode('mbcs', errors='replace')
                        result.append((index, name or f'outlook_{index + 1}'))
                    return result
                except Exception as exc:
                    _log('Outlook descriptor extraction failed', exc)
                    return []

            def virtual_outlook(data_object):
                if qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return False
                return descriptor_format(data_object)[0] is not None

            def stream_bytes(stream):
                chunks = []
                while True:
                    chunk = stream.Read(1024 * 1024)
                    if not chunk:
                        break
                    if isinstance(chunk, tuple):
                        chunk = chunk[0]
                    if not chunk:
                        break
                    chunks.append(bytes(chunk))
                    if len(chunk) < 1024 * 1024:
                        break
                return b''.join(chunks)

            def virtual_content(data_object, index):
                # Outlook attachments normally expose FileContents as IStream.
                # HGLOBAL is accepted as a conservative fallback.
                errors = []
                for tymed in (pythoncom.TYMED_ISTREAM, pythoncom.TYMED_HGLOBAL):
                    if not qget(data_object, fmt_contents, tymed, index):
                        continue
                    try:
                        medium = data_object.GetData(
                            (fmt_contents, None, pythoncom.DVASPECT_CONTENT, index, tymed)
                        )
                        if tymed == pythoncom.TYMED_ISTREAM:
                            stream = getattr(medium, 'data', None)
                            if stream is None:
                                raise RuntimeError('FileContents neobsahuje IStream.')
                            data = stream_bytes(stream)
                        else:
                            data = medium_bytes(medium)
                        if data:
                            return data
                    except Exception as exc:
                        errors.append(str(exc))
                raise RuntimeError(
                    'Outlook neposkytl obsah přetaženého souboru.'
                    + ((' ' + '; '.join(errors)) if errors else '')
                )

            def materialize_virtual(data_object):
                descriptors = virtual_descriptors(data_object)
                supported = [
                    (index, name)
                    for index, name in descriptors
                    if Path(name).suffix.lower() in ('.pdf', '.msg')
                ]
                if not supported:
                    return None, [], descriptors, []

                temp_dir = tempfile.TemporaryDirectory(prefix='turto_outlook_drop_')
                paths = []
                errors = []
                used_names = set()
                for index, name in supported:
                    try:
                        data = virtual_content(data_object, index)
                        base = _safe_filename(Path(name).name, f'outlook_{index + 1}')
                        ext = Path(name).suffix.lower()
                        if not base.lower().endswith(ext):
                            base += ext
                        candidate = base
                        serial = 2
                        while candidate.casefold() in used_names:
                            stem = Path(base).stem
                            candidate = f'{stem}_{serial}{ext}'
                            serial += 1
                        used_names.add(candidate.casefold())
                        target = Path(temp_dir.name) / candidate
                        target.write_bytes(data)
                        paths.append(target)
                    except Exception as exc:
                        errors.append(f'{name}: {exc}')
                return temp_dir, paths, descriptors, errors

            def show_virtual_error(errors):
                try:
                    M.messagebox.showerror(
                        'Přenos z Outlooku',
                        'Přetaženou PDF přílohu se nepodařilo převzít. '
                        'CRM z bezpečnostních důvodů nezpracovalo jiný vybraný e-mail.\n\n'
                        + '\n'.join(errors[:8])
                        + '\n\nPodrobnosti jsou v offer_drop_crash.log.',
                        parent=app,
                    )
                except Exception:
                    pass

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
                        if kind == 'files' or qget(
                            data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL
                        ):
                            paths = real_paths(data_object)
                            supported = [
                                path
                                for path in paths
                                if Path(path).suffix.lower() in ('.pdf', '.msg')
                            ]
                            if not supported:
                                return shellcon.DROPEFFECT_NONE
                            _log('Explorer drop accepted: ' + ', '.join(supported))
                            self.owner.after(
                                120,
                                lambda ps=tuple(supported): _process_real_files(self.owner, ps),
                            )
                            return shellcon.DROPEFFECT_COPY

                        if kind == 'outlook' or virtual_outlook(data_object):
                            temp_dir, paths, descriptors, errors = materialize_virtual(data_object)
                            names = [name for _, name in descriptors]
                            _log('Outlook virtual drop: ' + ', '.join(names or ['bez názvu']))
                            if paths:
                                self.owner.after(
                                    120,
                                    lambda td=temp_dir, ps=tuple(paths): _process_virtual_files(
                                        self.owner, td, ps
                                    ),
                                )
                                return shellcon.DROPEFFECT_COPY

                            if temp_dir is not None:
                                try:
                                    temp_dir.cleanup()
                                except Exception:
                                    pass

                            # A whole Outlook MailItem is typically advertised as
                            # a virtual .msg. If Outlook refuses direct FileContents,
                            # keep the proven Selection.SaveAs(.msg) fallback.
                            has_msg = any(Path(name).suffix.lower() == '.msg' for name in names)
                            has_pdf = any(Path(name).suffix.lower() == '.pdf' for name in names)
                            if has_msg and not has_pdf:
                                _log('Outlook MSG FileContents unavailable; using selected-message fallback')
                                self.owner.after(650, self.owner.import_selected_outlook_offer)
                                return shellcon.DROPEFFECT_COPY

                            if errors:
                                _log('Outlook attachment extraction failed: ' + ' | '.join(errors))
                                self.owner.after(0, lambda es=tuple(errors): show_virtual_error(es))
                                return shellcon.DROPEFFECT_COPY
                            return shellcon.DROPEFFECT_NONE
                        return shellcon.DROPEFFECT_NONE
                    except Exception as exc:
                        _log('Unified Drop failed', exc)
                        return shellcon.DROPEFFECT_NONE

            pythoncom.OleInitialize()
            target = UnifiedDropTarget(app)
            wrapped = pythoncom.WrapObject(
                target,
                pythoncom.IID_IDropTarget,
                pythoncom.IID_IDropTarget,
            )
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
