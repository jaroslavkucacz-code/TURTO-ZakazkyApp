# TURTO CRM - consolidated safe Explorer/Outlook drop runtime
#
# One module owns native drag-and-drop. Whole Outlook messages are deliberately
# kept out of FileGroupDescriptor/GetData handling: the OLE Drop callback only
# queues a lightweight request and returns. The actual messages are then saved
# from Outlook Selection through the normal Tk event loop. PDF attachments still
# use FileContents because their bytes exist only during the native Drop callback.
import gc
import os
import re
import struct
import tempfile
import traceback
from collections import deque
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
                handle.write(
                    '\n[' + datetime.now().isoformat(timespec='seconds') + '] '
                    + str(stage) + '\n'
                )
                if exc is not None:
                    handle.write(repr(exc) + '\n')
                    handle.write(traceback.format_exc() + '\n')
        except Exception:
            pass

    def _safe_filename(value, fallback='outlook'):
        text = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+',
            '_',
            str(value or ''),
        ).strip(' ._')
        return (text or fallback)[:140]

    def _enable_faulthandler(app):
        try:
            import faulthandler
            handle = _log_path().open('a', encoding='utf-8')
            faulthandler.enable(file=handle, all_threads=True)
            app._offer_fault_log_handle = handle
            _log('faulthandler enabled')
        except Exception as exc:
            _log('faulthandler init failed', exc)

    def _install_tk_exception_guard(app):
        try:
            old_report = getattr(app, 'report_callback_exception', None)

            def report(exc_type, exc_value, exc_tb):
                try:
                    with _log_path().open('a', encoding='utf-8') as handle:
                        handle.write('\nTk callback exception:\n')
                        traceback.print_exception(
                            exc_type, exc_value, exc_tb, file=handle
                        )
                except Exception:
                    pass
                try:
                    M.messagebox.showerror(
                        'Chyba aplikace',
                        'Při zpracování vstupu nastala chyba, ale CRM zůstává '
                        'spuštěné.\nPodrobnosti jsou v offer_drop_crash.log.',
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
        """Fallback only; normal releases use post_baseline._start_offer_batch."""
        from tkinter import messagebox

        good = []
        errors = []
        messages = 0
        attachments = 0
        for raw in paths:
            path = Path(str(raw))
            try:
                if not path.exists():
                    errors.append(f'{path}: soubor nebyl nalezen')
                    continue
                ext = path.suffix.lower()
                if ext == '.msg':
                    _log(f'{source_label} MSG processing begin: {path.name}')
                    result = M.process_offer_msg(app, path)
                    _log(f'{source_label} MSG processing end: {path.name}')
                    messages += 1
                    attachments += int((result or {}).get('attachments') or 0)
                    good.extend((result or {}).get('offers') or [])
                    errors.extend((result or {}).get('errors') or [])
                elif ext == '.pdf':
                    _log(f'{source_label} PDF processing begin: {path.name}')
                    result = M.process_offer_pdf(app, path)
                    _log(f'{source_label} PDF processing end: {path.name}')
                    good.append(result)
                else:
                    errors.append(f'{path.name}: nepodporovaný formát')
            except Exception as exc:
                _log(source_label + ' processing failed: ' + str(raw), exc)
                errors.append(f'{path.name}: {exc}')

        try:
            app.refresh_offers()
        except Exception:
            pass

        text = f'Zpracováno. Nabídky: {len(good)}'
        if messages:
            text += f'   •   MSG: {messages}   •   přílohy: {attachments}'
        if errors:
            text += '\n\nChyby / upozornění:\n' + '\n'.join(errors[:12])
        try:
            messagebox.showinfo(
                'Nabídky – ' + source_label.lower(), text, parent=app
            )
        except Exception:
            pass
        return good

    def _find_batch_dialog(app, before=None):
        before = set(before or ())
        try:
            candidates = list(app.winfo_children())
        except Exception:
            return None
        for only_new in (True, False):
            for widget in reversed(candidates):
                try:
                    if only_new and str(widget) in before:
                        continue
                    if widget.winfo_class() != 'Toplevel':
                        continue
                    if widget.title() == 'Zpracování cenových nabídek':
                        return widget
                except Exception:
                    pass
        return None

    def _foreground_batch_dialog(app, dialog):
        if dialog is None:
            return
        try:
            dialog.deiconify()
            dialog.lift()
            dialog.attributes('-topmost', True)
            dialog.focus_force()
            dialog.after(
                650,
                lambda d=dialog: d.attributes('-topmost', False)
                if d.winfo_exists() else None,
            )
        except Exception:
            pass

    def _retain_temp_for_batch(app, temp_dir, dialog):
        if temp_dir is None:
            return
        holders = getattr(app, '_offer_batch_temp_dirs', None)
        if not isinstance(holders, list):
            holders = []
            app._offer_batch_temp_dirs = holders
        holders.append(temp_dir)
        released = {'done': False}

        def release(event=None):
            if event is not None and dialog is not None:
                try:
                    if event.widget is not dialog:
                        return
                except Exception:
                    return
            if released['done']:
                return
            released['done'] = True
            try:
                temp_dir.cleanup()
            except Exception:
                pass
            try:
                if temp_dir in holders:
                    holders.remove(temp_dir)
            except Exception:
                pass

        if dialog is not None:
            try:
                dialog.bind('<Destroy>', release, add='+')
            except Exception:
                pass
        try:
            app.bind(
                '<Destroy>',
                lambda e: release()
                if getattr(e, 'widget', None) is app else None,
                add='+',
            )
        except Exception:
            pass

    def _start_visible_batch(app, paths, temp_dir=None, source_label='Přetažení'):
        batch = getattr(app, '_start_offer_batch', None)
        if callable(batch):
            try:
                before = {str(widget) for widget in app.winfo_children()}
            except Exception:
                before = set()
            try:
                batch(tuple(paths))
            except Exception as exc:
                _log('Batch runner failed; using direct fallback', exc)
            else:
                dialog = _find_batch_dialog(app, before)
                _foreground_batch_dialog(app, dialog)
                _retain_temp_for_batch(app, temp_dir, dialog)
                return []

        try:
            return _process_direct_files(app, paths, source_label)
        finally:
            if temp_dir is not None:
                try:
                    temp_dir.cleanup()
                except Exception:
                    pass

    def import_selected_outlook_offer(self):
        """Save the current Outlook selection incrementally, with progress and cancel."""
        from tkinter import messagebox, ttk

        if os.name != 'nt':
            return messagebox.showerror(
                'Přenos z Outlooku',
                'Přímý import z Outlooku je dostupný pouze ve Windows.',
                parent=self,
            )

        pythoncom = None
        com_initialized = False
        refs = {'outlook': None, 'explorer': None, 'selection': None}
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            com_initialized = True
            _log('Outlook selected-message preparation start')
            try:
                refs['outlook'] = win32com.client.GetActiveObject(
                    'Outlook.Application'
                )
            except Exception:
                refs['outlook'] = win32com.client.Dispatch('Outlook.Application')

            refs['explorer'] = refs['outlook'].ActiveExplorer()
            refs['selection'] = (
                refs['explorer'].Selection
                if refs['explorer'] is not None else None
            )
            count = int(refs['selection'].Count) if refs['selection'] is not None else 0
            if count < 1:
                raise RuntimeError('V Outlooku není vybraný žádný e-mail.')
        except Exception as exc:
            _log('Outlook selected-message preparation init failed', exc)
            refs.update(outlook=None, explorer=None, selection=None)
            gc.collect()
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            return messagebox.showerror(
                'Přenos z Outlooku',
                'E-mail se nepodařilo bezpečně převzít z Outlooku.\n\n'
                + str(exc)
                + '\n\nPodrobnosti jsou v offer_drop_crash.log.',
                parent=self,
            )

        temp_dir = tempfile.TemporaryDirectory(prefix='turto_outlook_msg_')
        state = {
            'index': 1,
            'saved': [],
            'errors': [],
            'cancel': False,
            'closed': False,
        }

        dialog = M.tk.Toplevel(self)
        dialog.title('Přebírání e-mailů z Outlooku')
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.geometry('610x235')

        box = ttk.Frame(dialog, padding=18)
        box.pack(fill='both', expand=True)
        title = ttk.Label(
            box,
            text=f'Přebírám e-maily z Outlooku 0 z {count}',
            style='Section.TLabel',
        )
        title.pack(anchor='w')
        current = ttk.Label(
            box,
            text='Připravuji první zprávu…',
            style='PageSubtitle.TLabel',
        )
        current.pack(anchor='w', pady=(6, 6))
        info = ttk.Label(
            box,
            text=(
                'Zprávy se nejprve bezpečně ukládají do dočasných .MSG souborů. '
                'Potom automaticky začne vlastní zpracování nabídek.'
            ),
            style='PageSubtitle.TLabel',
            wraplength=565,
        )
        info.pack(anchor='w', pady=(0, 10))
        bar = ttk.Progressbar(box, maximum=max(1, count), value=0, length=565)
        bar.pack(fill='x', pady=(0, 14))
        buttons = ttk.Frame(box)
        buttons.pack(fill='x')

        def release_com():
            if state['closed']:
                return
            state['closed'] = True
            refs['selection'] = None
            refs['explorer'] = None
            refs['outlook'] = None
            gc.collect()
            try:
                pythoncom.PumpWaitingMessages()
            except Exception:
                pass
            if com_initialized:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            _log('Outlook selected-message preparation end')

        def cleanup_temp():
            try:
                temp_dir.cleanup()
            except Exception:
                pass

        def close_dialog():
            try:
                if dialog.winfo_exists():
                    dialog.destroy()
            except Exception:
                pass

        def cancel():
            if state['cancel']:
                return
            state['cancel'] = True
            try:
                current.configure(
                    text='Storno požadováno – dokončím právě převáděný e-mail a zastavím.'
                )
            except Exception:
                pass

        ttk.Button(buttons, text='Storno', command=cancel).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW', cancel)
        _foreground_batch_dialog(self, dialog)

        def abort_preparation(message=None):
            saved_count = len(state['saved'])
            close_dialog()
            release_com()
            cleanup_temp()
            text = (
                'Přebírání e-mailů bylo zastaveno.\n\n'
                f'Převzato dočasně: {saved_count} z {count}.\n'
                'Žádná z této nedokončené dávky nebyla předána ke zpracování.'
            )
            if message:
                text += '\n\n' + str(message)
            messagebox.showinfo('Přenos z Outlooku', text, parent=self)

        def start_processing():
            paths = tuple(state['saved'])
            close_dialog()
            release_com()
            if not paths:
                cleanup_temp()
                detail = '\n'.join(state['errors'][:10])
                return messagebox.showerror(
                    'Přenos z Outlooku',
                    'Nepodařilo se převzít žádný z vybraných e-mailů.'
                    + (('\n\n' + detail) if detail else ''),
                    parent=self,
                )
            if state['errors']:
                _log(
                    f'Outlook preparation completed with {len(state["errors"])} errors; '
                    f'continuing with {len(paths)} messages'
                )
            _start_visible_batch(
                self,
                paths,
                temp_dir=temp_dir,
                source_label='Outlook',
            )

        def save_next():
            if state['cancel']:
                abort_preparation()
                return
            index = state['index']
            if index > count:
                start_processing()
                return

            title.configure(text=f'Přebírám e-maily z Outlooku {index} z {count}')
            bar['value'] = index - 1
            item = None
            try:
                selection = refs.get('selection')
                if selection is None:
                    raise RuntimeError('Outlook Selection již není dostupný.')
                item = selection.Item(index)
                try:
                    is_mail = int(getattr(item, 'Class', 0)) == 43
                except Exception:
                    is_mail = True

                if not is_mail:
                    current.configure(
                        text=f'{index}/{count}: přeskočena nepodporovaná položka'
                    )
                else:
                    subject = str(
                        getattr(item, 'Subject', '') or f'outlook_{index}'
                    )
                    current.configure(text=f'{index}/{count}: {subject[:95]}')
                    try:
                        self.update_idletasks()
                    except Exception:
                        pass
                    path = Path(temp_dir.name) / (
                        _safe_filename(subject, f'outlook_{index}')
                        + f'_{index}.msg'
                    )
                    _log(f'Outlook SaveAs begin: {path.name}')
                    try:
                        item.SaveAs(str(path), 9)
                    except Exception as first_exc:
                        low = str(first_exc).casefold()
                        if (
                            'omezil počet položek' in low
                            or 'server administrator' in low
                            or '-2147220731' in repr(first_exc)
                        ):
                            raise
                        item.SaveAs(str(path), 3)
                    if path.exists() and path.stat().st_size > 0:
                        state['saved'].append(path)
                        _log(
                            f'Outlook SaveAs complete: {path.name} '
                            f'({path.stat().st_size} bytes)'
                        )
                    else:
                        state['errors'].append(
                            f'{index}/{count} {subject}: Outlook nevytvořil platný .MSG soubor.'
                        )
            except Exception as exc:
                _log(f'Outlook SaveAs failed for selection index {index}', exc)
                state['errors'].append(f'{index}/{count}: {exc}')
            finally:
                item = None
                if index % 20 == 0:
                    gc.collect()
                    try:
                        pythoncom.PumpWaitingMessages()
                    except Exception:
                        pass

            state['index'] += 1
            bar['value'] = min(index, count)
            if state['cancel']:
                self.after(10, abort_preparation)
            else:
                self.after(20, save_next)

        self.after(10, save_next)
        return []

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
                if not qget(
                    data_object,
                    win32con.CF_HDROP,
                    pythoncom.TYMED_HGLOBAL,
                ):
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
                    return [
                        shell.DragQueryFileW(handle, index)
                        for index in range(count)
                    ]
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
                """Read descriptors only for attachment drops, never normal MSG drops."""
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
                            name = raw_name.decode(
                                'utf-16le', errors='ignore'
                            ).split('\x00', 1)[0]
                        else:
                            name = raw_name.split(b'\x00', 1)[0].decode(
                                'mbcs', errors='replace'
                            )
                        result.append((index, name or f'outlook_{index + 1}'))
                    return result
                except Exception as exc:
                    _log('Outlook descriptor extraction failed', exc)
                    return []

            def virtual_outlook(data_object):
                if qget(data_object, win32con.CF_HDROP, pythoncom.TYMED_HGLOBAL):
                    return False
                return descriptor_format(data_object)[0] is not None

            def virtual_has_filecontents(data_object, index=0):
                return (
                    qget(data_object, fmt_contents, pythoncom.TYMED_ISTREAM, index)
                    or qget(data_object, fmt_contents, pythoncom.TYMED_HGLOBAL, index)
                )

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

            def virtual_pdf_content(data_object, index):
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
                    'Outlook neposkytl obsah přetaženého PDF.'
                    + ((' ' + '; '.join(errors)) if errors else '')
                )

            def materialize_pdf_attachments(data_object, descriptors):
                supported = [
                    (index, name)
                    for index, name in descriptors
                    if Path(name).suffix.lower() == '.pdf'
                ]
                if not supported:
                    return None, [], []

                temp_dir = tempfile.TemporaryDirectory(prefix='turto_outlook_pdf_')
                paths = []
                errors = []
                used_names = set()
                for index, name in supported:
                    try:
                        _log(
                            f'Outlook PDF FileContents begin: index={index}, name={name}'
                        )
                        data = virtual_pdf_content(data_object, index)
                        base = _safe_filename(
                            Path(name).name, f'outlook_{index + 1}'
                        )
                        if not base.lower().endswith('.pdf'):
                            base += '.pdf'
                        candidate = base
                        serial = 2
                        while candidate.casefold() in used_names:
                            candidate = f'{Path(base).stem}_{serial}.pdf'
                            serial += 1
                        used_names.add(candidate.casefold())
                        target = Path(temp_dir.name) / candidate
                        target.write_bytes(data)
                        paths.append(target)
                        _log(
                            f'Outlook PDF FileContents complete: '
                            f'{target.name} ({len(data)} bytes)'
                        )
                    except Exception as exc:
                        _log(f'Outlook PDF FileContents failed: {name}', exc)
                        errors.append(f'{name}: {exc}')
                return temp_dir, paths, errors

            pending = deque()
            drain_state = {'closed': False}

            def show_virtual_error(errors):
                try:
                    M.messagebox.showerror(
                        'Přenos z Outlooku',
                        'Přetaženou PDF přílohu se nepodařilo převzít.\n\n'
                        + '\n'.join(errors[:8])
                        + '\n\nPodrobnosti jsou v offer_drop_crash.log.',
                        parent=app,
                    )
                except Exception:
                    pass

            def drain_pending():
                if drain_state['closed']:
                    return
                try:
                    while pending:
                        kind, payload = pending.popleft()
                        if kind == 'real_files':
                            _start_visible_batch(
                                app, payload, source_label='Přetažení'
                            )
                        elif kind == 'outlook_messages':
                            app.import_selected_outlook_offer()
                        elif kind == 'virtual_pdfs':
                            temp_dir, paths = payload
                            _start_visible_batch(
                                app,
                                paths,
                                temp_dir=temp_dir,
                                source_label='Outlook',
                            )
                        elif kind == 'virtual_error':
                            show_virtual_error(payload)
                except Exception as exc:
                    _log('Deferred drop queue failed', exc)
                try:
                    if app.winfo_exists() and not drain_state['closed']:
                        app.after(120, drain_pending)
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
                        if qget(
                            data_object,
                            win32con.CF_HDROP,
                            pythoncom.TYMED_HGLOBAL,
                        ):
                            self.kind = 'files'
                        elif virtual_outlook(data_object):
                            self.kind = 'outlook'
                        else:
                            self.kind = None
                        return (
                            shellcon.DROPEFFECT_COPY
                            if self.kind else shellcon.DROPEFFECT_NONE
                        )
                    except Exception as exc:
                        _log('Unified DragEnter failed', exc)
                        self.kind = None
                        return shellcon.DROPEFFECT_NONE

                def DragOver(self, key_state, point, effect):
                    return (
                        shellcon.DROPEFFECT_COPY
                        if self.kind else shellcon.DROPEFFECT_NONE
                    )

                def DragLeave(self):
                    self.kind = None

                def Drop(self, data_object, key_state, point, effect):
                    """Keep whole-message Drop callback minimal and COM-object free."""
                    try:
                        kind = self.kind
                        self.kind = None

                        if kind == 'files' or qget(
                            data_object,
                            win32con.CF_HDROP,
                            pythoncom.TYMED_HGLOBAL,
                        ):
                            paths = real_paths(data_object)
                            supported = tuple(
                                path for path in paths
                                if Path(path).suffix.lower() in ('.pdf', '.msg')
                            )
                            if not supported:
                                return shellcon.DROPEFFECT_NONE
                            _log(
                                f'Explorer drop accepted: {len(supported)} souborů'
                            )
                            pending.append(('real_files', supported))
                            return shellcon.DROPEFFECT_COPY

                        if kind == 'outlook' or virtual_outlook(data_object):
                            if not virtual_has_filecontents(data_object, 0):
                                _log(
                                    'Outlook whole-message drop accepted; '
                                    'FileContents bypassed; scheduling SaveAs(.msg); '
                                    'descriptor GetData bypassed'
                                )
                                pending.append(('outlook_messages', None))
                                return shellcon.DROPEFFECT_COPY

                            descriptors = virtual_descriptors(data_object)
                            names = [name for _index, name in descriptors]
                            _log(
                                f'Outlook attachment drop descriptors: {len(names)} položek'
                            )
                            temp_dir, paths, errors = materialize_pdf_attachments(
                                data_object, descriptors
                            )
                            if paths:
                                pending.append(
                                    ('virtual_pdfs', (temp_dir, tuple(paths)))
                                )
                                return shellcon.DROPEFFECT_COPY
                            if temp_dir is not None:
                                try:
                                    temp_dir.cleanup()
                                except Exception:
                                    pass
                            if errors:
                                pending.append(('virtual_error', tuple(errors)))
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
            app._offer_drop_pending = pending

            app.after(120, drain_pending)

            cleanup_state = {'done': False}

            def cleanup_drop(event=None):
                if event is not None and getattr(event, 'widget', None) is not app:
                    return
                if cleanup_state['done']:
                    return
                cleanup_state['done'] = True
                drain_state['closed'] = True
                try:
                    pythoncom.RevokeDragDrop(hwnd)
                except Exception:
                    pass
                try:
                    app._offer_drop_target_wrapped = None
                    app._offer_drop_target = None
                except Exception:
                    pass
                gc.collect()
                try:
                    pythoncom.OleUninitialize()
                except Exception:
                    pass

            try:
                app.bind('<Destroy>', cleanup_drop, add='+')
            except Exception:
                pass

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
