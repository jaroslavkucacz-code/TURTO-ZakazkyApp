# TURTO CRM 6.3 active extension layer
# One active layer owns table geometry, dashboard status tagging, offer archive,
# exact supplier Excel export, Outlook import and DB-only offer deletion.


def apply(M):
    import hashlib
    import json
    import re
    import shutil
    import tempfile
    from pathlib import Path

    # ------------------------------------------------------------------
    # Unified Treeview geometry and auxiliary redraws.
    # ------------------------------------------------------------------
    COMPACT = {
        'Stav', 'Přijato', 'Deadline', 'Poptáno', 'Obdrženo', 'Datum',
        'Zahájení', 'Dokončení', 'ID', 'Počet', 'Nabídky', 'Měna',
        'Ks', 'MJ', 'Příležitostí', 'Cena', 'Celkem',
    }

    def display_columns(tree):
        try:
            all_cols = list(tree.cget('columns'))
            raw = list(tree.cget('displaycolumns'))
            if not raw or raw == ['#all']:
                return all_cols
            out = []
            for col in raw:
                if str(col).isdigit():
                    idx = int(col)
                    if 0 <= idx < len(all_cols):
                        out.append(all_cols[idx])
                elif col in all_cols:
                    out.append(col)
            return out or all_cols
        except Exception:
            return []

    def fit_tree(tree, available=None):
        try:
            cols = display_columns(tree)
            if not cols:
                return
            if not hasattr(tree, '_turto_design_widths'):
                tree._turto_design_widths = {
                    col: max(50, min(int(tree.column(col, 'width')), 500))
                    for col in cols
                }
            design = tree._turto_design_widths
            for col in cols:
                if col not in design:
                    design[col] = max(50, min(int(tree.column(col, 'width')), 500))
            width = int(available if available is not None else tree.winfo_width())
            if width <= 10:
                return
            flex = [col for col in cols if str(col) not in COMPACT] or [cols[-1]]
            preferred = sum(design[col] for col in cols)
            share, rest = divmod(max(0, width - 4 - preferred), len(flex))
            for col in cols:
                col_width = design[col]
                if col in flex:
                    idx = flex.index(col)
                    col_width += share + (1 if idx < rest else 0)
                tree.column(
                    col,
                    width=col_width,
                    minwidth=max(50, min(design[col], 120)),
                    stretch=False,
                )
        except Exception:
            pass

    def schedule_auxiliary_redraw(tree):
        try:
            previous = getattr(tree, '_turto_aux_after', None)
            if previous is not None:
                try:
                    tree.after_cancel(previous)
                except Exception:
                    pass

            def finish():
                tree._turto_aux_after = None
                try:
                    fn = getattr(tree, '_sync_filter_bar', None)
                    if callable(fn):
                        fn()
                except Exception:
                    pass
                try:
                    fn = getattr(tree, '_date_cell_redraw', None)
                    if callable(fn):
                        fn()
                except Exception:
                    pass

            tree._turto_aux_after = tree.after(110, finish)
        except Exception:
            pass

    def install_tree(tree):
        try:
            if tree is None or not tree.winfo_exists():
                return
            if not getattr(tree, '_turto_layout_bound', False):
                tree._turto_layout_bound = True

                def on_configure(event, current=tree):
                    fit_tree(current, getattr(event, 'width', None))
                    schedule_auxiliary_redraw(current)

                tree.bind('<Configure>', on_configure, add='+')
            if not getattr(tree, '_turto_map_bound', False):
                tree._turto_map_bound = True
                tree.bind(
                    '<Map>',
                    lambda _event, current=tree: (
                        fit_tree(current),
                        schedule_auxiliary_redraw(current),
                    ),
                    add='+',
                )
            fit_tree(tree)
        except Exception:
            pass

    def walk(widget, callback):
        try:
            for child in widget.winfo_children():
                try:
                    callback(child)
                except Exception:
                    pass
                walk(child, callback)
        except Exception:
            pass

    def normalize(app):
        walk(
            app,
            lambda widget: install_tree(widget)
            if widget.winfo_class() == 'Treeview'
            else None,
        )

    def reclaim_tree_layout(app):
        """Remove legacy Configure handlers, then install one final fitter."""
        def reclaim(widget):
            try:
                if widget.winfo_class() != 'Treeview':
                    return
                try:
                    widget.unbind('<Configure>')
                except Exception:
                    pass
                widget._turto_layout_bound = False
                install_tree(widget)
                schedule_auxiliary_redraw(widget)
            except Exception:
                pass

        walk(app, reclaim)

    # ------------------------------------------------------------------
    # Exact dashboard status tagging.
    # ------------------------------------------------------------------
    STATUS_TAGS = {
        'rozpracováno': 'status_active',
        'rozpracovano': 'status_active',
        'připraveno': 'status_offer',
        'pripraveno': 'status_offer',
        'hotovo': 'status_done',
        'zrušeno': 'status_cancel',
        'zruseno': 'status_cancel',
    }

    def recolor_dashboard(app):
        try:
            page = getattr(app, 'tabs', {}).get('dash')
        except Exception:
            page = None
        if page is None:
            return

        def recolor(widget):
            try:
                if widget.winfo_class() != 'Treeview':
                    return
                cols = list(widget.cget('columns') or ())
                status_col = None
                for col in cols:
                    try:
                        heading = str(widget.heading(col, 'text') or '').strip().casefold()
                    except Exception:
                        heading = str(col).strip().casefold()
                    if heading == 'stav' or 'stav' in heading:
                        status_col = col
                        break
                if status_col is None:
                    return
                for iid in widget.get_children(''):
                    status = str(widget.set(iid, status_col) or '').strip().casefold()
                    tag = STATUS_TAGS.get(status)
                    if tag:
                        widget.item(iid, tags=(tag,))
            except Exception:
                pass

        recolor(page)
        walk(page, recolor)

    old_tree = getattr(M.App, 'tree', None)
    if callable(old_tree):
        def tree(self, *args, **kwargs):
            widget = old_tree(self, *args, **kwargs)
            install_tree(widget)
            return widget

        M.App.tree = tree

    def schedule_final_layout(app):
        """Run geometry after older refresh layers finish their idle callbacks."""
        try:
            previous = getattr(app, '_turto_final_layout_after', None)
            if previous is not None:
                try:
                    app.after_cancel(previous)
                except Exception:
                    pass

            def finish():
                try:
                    app._turto_final_layout_after = None
                except Exception:
                    pass
                normalize(app)
                recolor_dashboard(app)

            app._turto_final_layout_after = app.after_idle(finish)
        except Exception:
            normalize(app)
            recolor_dashboard(app)

    M.schedule_final_tree_layout = schedule_final_layout

    for name in (
        'refresh_dash', 'refresh_dashboard', 'refresh_actions', 'refresh_requests',
        'refresh_mivo_requests', 'refresh_mivo', 'refresh_projects',
        'refresh_offers', 'refresh_tasks', 'refresh_companies',
        'refresh_people', 'refresh_all',
    ):
        old = getattr(M.App, name, None)
        if not callable(old):
            continue

        def make(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                schedule_final_layout(self)
                return result

            return wrapped

        setattr(M.App, name, make(old))

    old_show = getattr(M.App, 'show_page', None)
    if callable(old_show):
        def show_page(self, *args, **kwargs):
            result = old_show(self, *args, **kwargs)
            schedule_final_layout(self)
            return result

        M.App.show_page = show_page

    # ------------------------------------------------------------------
    # Per-PC / per-user archive folder setting.
    # ------------------------------------------------------------------
    LOCAL_CFG = (
        Path(getattr(M, 'DATA_ROOT', Path.home() / 'Documents' / 'TURTO Zakazky'))
        / 'local_settings.json'
    )
    DEFAULT_ARCHIVE = (
        Path(getattr(M, 'DATA_ROOT', Path.home() / 'Documents' / 'TURTO Zakazky'))
        / 'Nabidky'
    )

    # Only real business/document attachments are copied next to the MSG.
    # Inline images, signature graphics and decorative mail resources are never
    # materialized into the physical offer archive.
    MAIN_ATTACHMENT_EXTS = {
        '.pdf',
        '.xls', '.xlsx', '.xlsm', '.xlsb', '.csv', '.ods',
        '.doc', '.docx', '.odt', '.rtf', '.txt',
        '.ppt', '.pptx',
        '.zip', '.rar', '.7z',
        '.xml',
        '.ifc', '.dwg', '.dxf', '.rvt',
        '.step', '.stp', '.iges', '.igs',
    }
    IMAGE_EXTS = {
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff',
        '.webp', '.svg', '.ico', '.emf', '.wmf', '.heic', '.avif',
    }

    def active_user(app=None):
        try:
            return (app.active_user.get() or '').strip() or 'Výchozí'
        except Exception:
            try:
                return (M.get_setting('active_user', '') or '').strip() or 'Výchozí'
            except Exception:
                return 'Výchozí'

    def load_cfg():
        try:
            return json.loads(LOCAL_CFG.read_text(encoding='utf-8')) if LOCAL_CFG.exists() else {}
        except Exception:
            return {}

    def save_cfg(data):
        try:
            LOCAL_CFG.parent.mkdir(parents=True, exist_ok=True)
            temp = LOCAL_CFG.with_suffix('.tmp')
            temp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
            temp.replace(LOCAL_CFG)
        except Exception:
            pass

    def archive_root(app=None):
        path = (
            (load_cfg().get('offer_archive_dir_by_user') or {})
            .get(active_user(app), '')
            .strip()
        )
        return Path(path) if path else DEFAULT_ARCHIVE

    def set_archive_root(app, path):
        data = load_cfg()
        data.setdefault('offer_archive_dir_by_user', {})[active_user(app)] = str(Path(path))
        save_cfg(data)

    def cleanup_legacy_offer_staging(app=None):
        """Delete only legacy staging files whose full bytes are already stored in DB.

        Current MSG/PDF import uses TemporaryDirectory and cleans itself. Older
        versions could leave mail material under DATA_ROOT\Dokumenty/Documents.
        Never remove an unknown file and never touch the configured offer archive.
        """
        try:
            import os

            data_root = Path(getattr(M, 'DATA_ROOT', ''))
            if not data_root.is_dir():
                return 0

            roots = []
            try:
                for child in data_root.iterdir():
                    if child.is_dir() and child.name.casefold() in {'dokumenty', 'documents'}:
                        roots.append(child)
            except Exception:
                return 0
            if not roots:
                return 0

            # A file is disposable only when the database already contains its
            # complete original bytes, not merely metadata or a path.
            known_hashes = set()
            try:
                with M.db() as con:
                    tables = {
                        str(row[0])
                        for row in con.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    if 'offer_source_messages' in tables:
                        cols = {
                            str(row[1])
                            for row in con.execute(
                                'PRAGMA table_info(offer_source_messages)'
                            ).fetchall()
                        }
                        if 'source_blob' in cols:
                            known_hashes.update(
                                str(row[0])
                                for row in con.execute(
                                    "SELECT source_hash FROM offer_source_messages "
                                    "WHERE source_blob IS NOT NULL AND length(source_blob)>0 "
                                    "AND trim(coalesce(source_hash,''))<>''"
                                ).fetchall()
                            )
                    if 'offer_source_attachments' in tables:
                        known_hashes.update(
                            str(row[0])
                            for row in con.execute(
                                "SELECT content_hash FROM offer_source_attachments "
                                "WHERE content_blob IS NOT NULL AND length(content_blob)>0 "
                                "AND trim(coalesce(content_hash,''))<>''"
                            ).fetchall()
                        )
            except Exception:
                return 0
            if not known_hashes:
                return 0

            try:
                archive = archive_root(app).resolve()
            except Exception:
                archive = None

            def digest(path):
                h = hashlib.sha256()
                with path.open('rb') as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
                return h.hexdigest()

            deleted = 0
            for root in roots:
                try:
                    resolved_root = root.resolve()
                    if archive is not None and (
                        resolved_root == archive
                        or resolved_root in archive.parents
                        or archive in resolved_root.parents
                    ):
                        # Never clean a path that is or contains the real archive.
                        continue
                except Exception:
                    continue

                files = []
                try:
                    files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink()]
                except Exception:
                    pass
                for file_path in files:
                    try:
                        if digest(file_path) in known_hashes:
                            file_path.unlink()
                            deleted += 1
                    except Exception:
                        pass

                # Remove only directories that became genuinely empty. Unknown
                # content keeps both its file and its parent folder untouched.
                try:
                    dirs = [p for p in root.rglob('*') if p.is_dir()]
                    dirs.sort(key=lambda p: len(p.parts), reverse=True)
                    for directory in dirs:
                        try:
                            if not any(directory.iterdir()):
                                directory.rmdir()
                        except Exception:
                            pass
                    if root.exists() and not any(root.iterdir()):
                        root.rmdir()
                except Exception:
                    pass
            return deleted
        except Exception:
            return 0

    M.cleanup_legacy_offer_staging = cleanup_legacy_offer_staging

    def show_offer_archive_folder(app, folders):
        """Open the resulting offer folder, or foreground its existing Explorer window."""
        try:
            import os
            import subprocess
            import sys

            if not sys.platform.startswith('win'):
                return False

            if isinstance(folders, (str, Path)):
                folders = [folders]
            unique = []
            seen = set()
            for raw in folders or []:
                try:
                    path = Path(str(raw))
                    if not path.is_dir():
                        continue
                    key = os.path.normcase(os.path.normpath(os.path.abspath(str(path))))
                    if key in seen:
                        continue
                    seen.add(key)
                    unique.append(path)
                except Exception:
                    pass
            if not unique:
                return False

            # One imported offer -> show its exact folder. A multi-offer batch can
            # create several sibling folders, so show their configured archive root.
            target = unique[0] if len(unique) == 1 else archive_root(app)
            target = Path(target)
            if not target.is_dir():
                return False
            target_key = os.path.normcase(
                os.path.normpath(os.path.abspath(str(target)))
            )

            def foreground_existing():
                pythoncom = None
                try:
                    import pythoncom
                    import win32com.client
                    import win32con
                    import win32gui

                    pythoncom.CoInitialize()
                    shell = win32com.client.Dispatch('Shell.Application')
                    for window in shell.Windows():
                        try:
                            current = str(window.Document.Folder.Self.Path or '')
                            current_key = os.path.normcase(
                                os.path.normpath(os.path.abspath(current))
                            )
                            if current_key != target_key:
                                continue
                            hwnd = int(getattr(window, 'HWND', 0) or 0)
                            if not hwnd:
                                continue
                            try:
                                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                            except Exception:
                                pass
                            try:
                                win32gui.SetWindowPos(
                                    hwnd,
                                    win32con.HWND_TOP,
                                    0, 0, 0, 0,
                                    win32con.SWP_NOMOVE
                                    | win32con.SWP_NOSIZE
                                    | win32con.SWP_SHOWWINDOW,
                                )
                            except Exception:
                                pass
                            try:
                                win32gui.SetForegroundWindow(hwnd)
                            except Exception:
                                try:
                                    win32gui.BringWindowToTop(hwnd)
                                except Exception:
                                    pass
                            return True
                        except Exception:
                            continue
                except Exception:
                    return False
                finally:
                    try:
                        if pythoncom is not None:
                            pythoncom.CoUninitialize()
                    except Exception:
                        pass
                return False

            if foreground_existing():
                return True

            try:
                os.startfile(str(target))
            except Exception:
                try:
                    subprocess.Popen(['explorer.exe', str(target)])
                except Exception:
                    return False

            # Explorer may need a moment to materialize the new window. Refocus it
            # after launch so CRM never leaves the newly opened folder behind itself.
            try:
                app.after(350, foreground_existing)
                app.after(900, foreground_existing)
            except Exception:
                pass
            return True
        except Exception:
            return False

    M.show_offer_archive_folder = show_offer_archive_folder

    old_settings = getattr(M.App, 'build_settings', None)
    if callable(old_settings):
        def build_settings(self):
            result = old_settings(self)
            try:
                from tkinter import filedialog, ttk

                page = self.tabs['settings']
                card = ttk.Frame(page, style='Panel.TFrame', padding=18)
                card.pack(fill='x', pady=(10, 0))
                ttk.Label(
                    card,
                    text='Ukládání zpracovaných nabídek',
                    style='Panel.TLabel',
                    font=('Calibri', 12, 'bold'),
                ).grid(row=0, column=0, columnspan=3, sticky='w')
                var = M.tk.StringVar(value=str(archive_root(self)))
                self._offer_archive_dir_var = var
                entry = ttk.Entry(card, textvariable=var)
                entry.grid(row=1, column=0, sticky='ew', padx=(0, 8))
                card.columnconfigure(0, weight=1)

                def choose():
                    value = filedialog.askdirectory(
                        parent=self,
                        initialdir=var.get() or str(DEFAULT_ARCHIVE),
                    )
                    if value:
                        var.set(value)
                        set_archive_root(self, value)

                entry.bind(
                    '<FocusOut>',
                    lambda _event: set_archive_root(self, var.get())
                    if var.get().strip()
                    else None,
                )
                ttk.Button(card, text='Vybrat…', command=choose).grid(row=1, column=1)
            except Exception:
                pass
            return result

        M.App.build_settings = build_settings

    # ------------------------------------------------------------------
    # Rich GEROtop description persistence. The parser already knows which PDF
    # spans are bold; this stores that metadata without altering existing text.
    # ------------------------------------------------------------------
    try:
        with M.db() as con:
            cols = {
                row[1]
                for row in con.execute('PRAGMA table_info(supplier_offer_items)')
            }
            if 'details_rich_json' not in cols:
                con.execute(
                    "ALTER TABLE supplier_offer_items "
                    "ADD COLUMN details_rich_json TEXT DEFAULT ''"
                )
    except Exception:
        pass

    def store_rich_from_parsed(offer_id, parsed):
        if 'gerotop' not in str((parsed or {}).get('supplier') or '').casefold():
            return False
        parsed_items = list((parsed or {}).get('items') or [])
        if not parsed_items:
            return False
        changed = False
        with M.db() as con:
            rows = con.execute(
                'SELECT id,position FROM supplier_offer_items '
                'WHERE offer_id=? ORDER BY position,id',
                (offer_id,),
            ).fetchall()
            by_position = {int(row['position'] or 0): row['id'] for row in rows}
            for item in parsed_items:
                segments = item.get('rich_segments') or []
                if not segments:
                    continue
                item_id = by_position.get(int(item.get('position') or 0))
                if not item_id:
                    continue
                con.execute(
                    'UPDATE supplier_offer_items SET details_rich_json=? WHERE id=?',
                    (
                        json.dumps(
                            segments,
                            ensure_ascii=False,
                            separators=(',', ':'),
                        ),
                        item_id,
                    ),
                )
                changed = True
        return changed

    def parse_rich_source(path):
        fn = getattr(M, 'extract_offer_pdf', None)
        if not callable(fn):
            return None
        parsed, _raw = fn(path)
        return parsed

    def ensure_offer_rich_details(offer_id):
        try:
            with M.db() as con:
                offer = con.execute(
                    "SELECT coalesce(supplier_name,'') supplier,source_pdf "
                    'FROM supplier_offers WHERE id=?',
                    (offer_id,),
                ).fetchone()
                if not offer or 'gerotop' not in str(offer['supplier']).casefold():
                    return False
                existing = con.execute(
                    "SELECT 1 FROM supplier_offer_items WHERE offer_id=? "
                    "AND coalesce(details_rich_json,'')<>'' LIMIT 1",
                    (offer_id,),
                ).fetchone()
                if existing:
                    return True
                source_pdf = str(offer['source_pdf'] or '').strip()

            if source_pdf and Path(source_pdf).is_file():
                parsed = parse_rich_source(source_pdf)
                if parsed and store_rich_from_parsed(offer_id, parsed):
                    return True

            try:
                with M.db() as con:
                    attachment = con.execute(
                        "SELECT filename,content_blob FROM offer_source_attachments "
                        "WHERE offer_id=? AND lower(extension)='.pdf' "
                        'AND content_blob IS NOT NULL ORDER BY id LIMIT 1',
                        (offer_id,),
                    ).fetchone()
            except Exception:
                attachment = None

            if attachment and attachment['content_blob']:
                with tempfile.TemporaryDirectory(prefix='turto_rich_offer_') as td:
                    name = Path(
                        str(attachment['filename'] or 'nabidka.pdf')
                    ).name
                    if not name.lower().endswith('.pdf'):
                        name += '.pdf'
                    source = Path(td) / name
                    source.write_bytes(bytes(attachment['content_blob']))
                    parsed = parse_rich_source(source)
                    return bool(
                        parsed and store_rich_from_parsed(offer_id, parsed)
                    )
        except Exception:
            return False
        return False

    M.ensure_offer_rich_details = ensure_offer_rich_details

    # ------------------------------------------------------------------
    # Exact proven supplier exporter. v624 remains canonical.
    # ------------------------------------------------------------------
    try:
        import v624_legacy_exports

        v624_legacy_exports.apply(M)
    except Exception:
        pass

    manual_export = getattr(M, 'export_offer_excel', None)

    def export_to_path(app, offer_id, target):
        """Run the exact manual exporter into a temporary file, then replace."""
        if not callable(manual_export):
            raise RuntimeError('CRM Excel export není dostupný.')

        from tkinter import filedialog, messagebox

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(target.stem + '.__tmp__' + target.suffix)
        try:
            temp_target.unlink(missing_ok=True)
        except Exception:
            pass

        old_save = filedialog.asksaveasfilename
        old_info = messagebox.showinfo
        old_error = messagebox.showerror
        errors = []
        try:
            filedialog.asksaveasfilename = lambda *args, **kwargs: str(temp_target)
            messagebox.showinfo = lambda *args, **kwargs: None
            messagebox.showerror = (
                lambda _title, msg, *args, **kwargs: errors.append(str(msg))
            )
            manual_export(app, offer_id, app)
        finally:
            filedialog.asksaveasfilename = old_save
            messagebox.showinfo = old_info
            messagebox.showerror = old_error

        if errors:
            try:
                temp_target.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(errors[-1])
        if not temp_target.exists():
            raise RuntimeError(
                'CRM export nevytvořil očekávaný soubor: ' + str(temp_target)
            )
        try:
            temp_target.replace(target)
        except Exception as exc:
            raise RuntimeError(
                'Extrakci se nepodařilo uložit. Není soubor otevřený v Excelu? '
                + str(exc)
            ) from exc
        return target

    M.export_offer_exactly_like_manual = export_to_path

    def excel_name_for_offer(offer_id):
        generator = getattr(M, 'offer_export_filename', None)
        if callable(generator):
            try:
                name = str(generator(offer_id) or '').strip()
                if name.lower().endswith('.xlsx'):
                    return name
            except Exception:
                pass
        return 'Extrakce dat CN nabidka.xlsx'

    # ------------------------------------------------------------------
    # DB-first archive pipeline.
    # ------------------------------------------------------------------
    def safe(value, maxlen=100):
        text = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+',
            '_',
            str(value or ''),
        ).strip(' ._')
        return (text or 'Bez_nazvu')[:maxlen]

    def archive_date_token(value):
        text = str(value or '').strip()
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', text)
        if m:
            return f'{m.group(1)[2:]}-{m.group(2)}-{m.group(3)}'
        m = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        if m:
            return f'{m.group(3)[2:]}-{int(m.group(2)):02d}-{int(m.group(1)):02d}'
        return 'bez-data'

    def folder_for(app, offer_id, path=None, subject=''):
        with M.db() as con:
            offer = con.execute(
                '''SELECT o.offer_date,o.offer_number,
                          coalesce(o.supplier_name,'') supplier,
                          coalesce(a.name,'') action_name
                   FROM supplier_offers o
                   LEFT JOIN actions a ON a.id=o.action_id
                   WHERE o.id=?''',
                (offer_id,),
            ).fetchone()
        source_name = Path(path).stem if path else 'nabidka'
        supplier = safe(offer['supplier'] if offer else 'dodavatel', 40)
        date_token = archive_date_token(offer['offer_date'] if offer else '')
        action_name = str(offer['action_name'] or '').strip() if offer else ''
        offer_no = str(offer['offer_number'] or '').strip() if offer else ''
        label = action_name or offer_no or subject or source_name
        folder_name = safe(
            f'nabídka {supplier}_{date_token}_{label}',
            180,
        )
        folder = archive_root(app) / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def attachment_name(attachment, index):
        for attr in ('longFilename', 'shortFilename', 'name', 'filename'):
            try:
                value = getattr(attachment, attr, None)
                value = value() if callable(value) else value
                if value:
                    return str(value)
            except Exception:
                pass
        return f'priloha_{index}'

    def truthy_attachment_flag(attachment, names):
        for name in names:
            try:
                value = getattr(attachment, name, None)
                value = value() if callable(value) else value
            except Exception:
                continue
            if isinstance(value, str):
                if value.strip().casefold() in {'1', 'true', 'ano', 'yes', 'inline', 'hidden'}:
                    return True
            elif bool(value):
                return True
        return False

    def attachment_mime(attachment):
        for name in ('mimetype', 'mimeType', 'contentType', 'content_type'):
            try:
                value = getattr(attachment, name, None)
                value = value() if callable(value) else value
                if value:
                    return str(value).strip().casefold()
            except Exception:
                pass
        return ''

    def is_main_attachment(attachment, name):
        ext = Path(str(name)).suffix.lower()
        if ext in IMAGE_EXTS or ext not in MAIN_ATTACHMENT_EXTS:
            return False
        if attachment_mime(attachment).startswith('image/'):
            return False
        if truthy_attachment_flag(
            attachment,
            ('hidden', 'isHidden', 'inline', 'isInline', 'is_inline'),
        ):
            return False
        return True

    def attachment_bytes(attachment):
        data = None
        try:
            data = getattr(attachment, 'data', None)
            data = data() if callable(data) else data
        except Exception:
            data = None
        if data is None:
            try:
                getter = getattr(attachment, 'get_data', None)
                data = getter() if callable(getter) else None
            except Exception:
                data = None
        if isinstance(data, str):
            return data.encode('utf-8', errors='replace')
        if data is None:
            return b''
        try:
            return bytes(data)
        except Exception:
            return b''

    def write_unique(folder, name, data):
        base = folder / safe(Path(name).name, 130)
        if base.exists():
            try:
                if base.read_bytes() == data:
                    return base
            except Exception:
                pass
            digest = hashlib.sha256(data).hexdigest()[:8]
            base = base.with_name(base.stem + '_' + digest + base.suffix)
        base.write_bytes(data)
        return base

    base_pdf = getattr(M, 'process_offer_pdf', None)
    base_msg = getattr(M, 'process_offer_msg', None)

    if callable(base_pdf):
        def process_pdf(app, path, *args, **kwargs):
            result = base_pdf(app, path, *args, **kwargs)
            if isinstance(result, dict) and result.get('offer_id'):
                try:
                    ensure_offer_rich_details(result['offer_id'])
                except Exception:
                    pass
            if getattr(app, '_turto_inside_msg', False):
                return result
            if not isinstance(result, dict):
                return result
            offer_id = result.get('offer_id')
            if not offer_id:
                return result
            try:
                folder = folder_for(app, offer_id, path)
                source = Path(path)
                archived = folder / safe(source.name, 130)
                if not archived.exists() or archived.stat().st_size != source.stat().st_size:
                    shutil.copy2(source, archived)
                output = folder / excel_name_for_offer(offer_id)
                export_to_path(app, offer_id, output)
                result.update(
                    archive_folder=str(folder),
                    archive_file=str(archived),
                    archive_attachments=[],
                    excel_files=[str(output)],
                )
            except Exception as exc:
                result.setdefault('errors', []).append(
                    'Archiv / Excel: ' + str(exc)
                )
            return result

        M.process_offer_pdf = process_pdf

    if callable(base_msg):
        def process_msg(app, path, *args, **kwargs):
            # 1) Parse and write DB records first.
            app._turto_inside_msg = True
            try:
                result = base_msg(app, path, *args, **kwargs)
            finally:
                app._turto_inside_msg = False

            if not isinstance(result, dict):
                return result
            offers = [
                item
                for item in (result.get('offers') or [])
                if isinstance(item, dict) and item.get('offer_id')
            ]
            if not offers:
                return result

            for offer in offers:
                try:
                    ensure_offer_rich_details(offer['offer_id'])
                except Exception:
                    pass

            source = Path(path)
            message = None
            subject = ''
            local_errors = []
            saved_attachments = []
            outputs = []

            # 2) Read only metadata needed for the physical archive. Failure to
            # inspect one attachment must never stop the Excel extraction.
            try:
                import extract_msg

                message = extract_msg.Message(str(source))
                subject = str(getattr(message, 'subject', '') or '')
            except Exception as exc:
                local_errors.append('MSG přílohy: ' + str(exc))

            try:
                folder = folder_for(
                    app,
                    offers[0]['offer_id'],
                    source,
                    subject,
                )
                archived_msg = folder / safe(source.name, 130)
                if (
                    not archived_msg.exists()
                    or archived_msg.stat().st_size != source.stat().st_size
                ):
                    shutil.copy2(source, archived_msg)
            except Exception as exc:
                result.setdefault('errors', []).append(
                    'Archiv MSG: ' + str(exc)
                )
                try:
                    if message is not None:
                        message.close()
                except Exception:
                    pass
                return result

            # 3) Copy only explicit document/business attachments. Inline images
            # and signature resources are skipped before their data is accessed.
            if message is not None:
                for index, attachment in enumerate(
                    getattr(message, 'attachments', []) or [],
                    1,
                ):
                    name = attachment_name(attachment, index)
                    if not is_main_attachment(attachment, name):
                        continue
                    try:
                        data = attachment_bytes(attachment)
                        if not data:
                            local_errors.append(
                                f'Příloha {name}: nebyla dostupná žádná data.'
                            )
                            continue
                        saved_attachments.append(
                            str(write_unique(folder, name, data))
                        )
                    except Exception as exc:
                        local_errors.append(f'Příloha {name}: {exc}')
                try:
                    message.close()
                except Exception:
                    pass

            # 4) Always generate the Excel from committed DB data, regardless of
            # any attachment-specific problem above.
            used_output_names = set()
            for index, offer in enumerate(offers, 1):
                filename = excel_name_for_offer(offer['offer_id'])
                key = filename.casefold()
                if key in used_output_names:
                    candidate = Path(filename)
                    filename = f'{candidate.stem}_{index}{candidate.suffix}'
                    key = filename.casefold()
                used_output_names.add(key)
                output = folder / filename
                try:
                    export_to_path(app, offer['offer_id'], output)
                    outputs.append(str(output))
                except Exception as exc:
                    local_errors.append(
                        f'Extrakce nabídky {offer["offer_id"]}: {exc}'
                    )

            result.update(
                archive_folder=str(folder),
                archive_msg=str(archived_msg),
                archive_attachments=saved_attachments,
                excel_files=outputs,
            )
            if local_errors:
                result.setdefault('errors', []).extend(local_errors)
            return result

        M.process_offer_msg = process_msg

    # ------------------------------------------------------------------
    # Shared batch runner for file picker and Explorer drops.
    # ------------------------------------------------------------------
    def start_offer_batch(self, paths):
        from tkinter import messagebox, ttk

        paths = [
            Path(path)
            for path in paths
            if str(path).lower().endswith(('.pdf', '.msg'))
        ]
        if not paths:
            return

        total = len(paths)
        state = {
            'index': 0,
            'cancel': False,
            'offers': 0,
            'messages': 0,
            'errors': [],
            'archives': [],
        }

        dialog = M.tk.Toplevel(self)
        dialog.title('Zpracování cenových nabídek')
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.geometry('560x210')

        box = ttk.Frame(dialog, padding=18)
        box.pack(fill='both', expand=True)
        title = ttk.Label(
            box,
            text=f'Zpracování 0 z {total}',
            style='Section.TLabel',
        )
        title.pack(anchor='w')
        current = ttk.Label(
            box,
            text='Připravuji…',
            style='PageSubtitle.TLabel',
        )
        current.pack(anchor='w', pady=(6, 10))
        bar = ttk.Progressbar(box, maximum=max(1, total), value=0, length=520)
        bar.pack(fill='x', pady=(0, 14))
        buttons = ttk.Frame(box)
        buttons.pack(fill='x')

        def cancel():
            state['cancel'] = True
            current.configure(
                text='Po dokončení aktuálního souboru bude dávka zastavena…'
            )

        def background():
            dialog.withdraw()

        ttk.Button(buttons, text='Storno', command=cancel).pack(side='right')
        ttk.Button(
            buttons,
            text='Pokračovat na pozadí',
            command=background,
        ).pack(side='right', padx=(0, 8))
        dialog.protocol('WM_DELETE_WINDOW', background)

        def finish():
            try:
                self.refresh_offers()
            except Exception:
                pass
            try:
                dialog.destroy()
            except Exception:
                pass
            text = (
                ('Zpracování zastaveno.' if state['cancel'] else 'Zpracování dokončeno.')
                + f'\n\nNabídky: {state["offers"]}'
                + f'\nMSG: {state["messages"]}'
            )
            if state['archives']:
                text += '\nArchiv: ' + str(archive_root(self))
            if state['errors']:
                text += (
                    f'\n\nChyby / upozornění: {len(state["errors"])}\n'
                    + '\n'.join(state['errors'][:12])
                )
            messagebox.showinfo(
                'Zpracování cenových nabídek',
                text,
                parent=self,
            )
            try:
                cleanup_legacy_offer_staging(self)
            except Exception:
                pass
            if state['archives'] and not state['cancel']:
                show_offer_archive_folder(self, state['archives'])

        def step():
            if state['cancel'] or state['index'] >= total:
                finish()
                return

            path = paths[state['index']]
            title.configure(
                text=f'Zpracování {state["index"] + 1} z {total}'
            )
            current.configure(text=path.name)
            bar['value'] = state['index']
            try:
                self.update_idletasks()
            except Exception:
                pass

            try:
                if path.suffix.lower() == '.msg':
                    result = M.process_offer_msg(self, path)
                    state['messages'] += 1
                    state['offers'] += len((result or {}).get('offers') or [])
                else:
                    result = M.process_offer_pdf(self, path)
                    if isinstance(result, dict) and result.get('offer_id'):
                        state['offers'] += 1
                if isinstance(result, dict):
                    if result.get('archive_folder'):
                        state['archives'].append(result['archive_folder'])
                    state['errors'].extend(result.get('errors') or [])
                    for item in result.get('results') or []:
                        if isinstance(item, dict) and item.get('error'):
                            state['errors'].append(str(item['error']))
            except Exception as exc:
                state['errors'].append(f'{path.name}: {exc}')

            state['index'] += 1
            bar['value'] = state['index']
            self.after(30, step)

        self.after(10, step)

    M.App._start_offer_batch = start_offer_batch

    def import_offer_sources(self):
        from tkinter import filedialog

        paths = filedialog.askopenfilenames(
            parent=self,
            title='Importovat cenové nabídky',
            filetypes=[
                ('Nabídky / e-maily', '*.pdf *.msg'),
                ('PDF', '*.pdf'),
                ('Outlook zprávy', '*.msg'),
                ('Všechny soubory', '*.*'),
            ],
        )
        if paths:
            self._start_offer_batch(paths)

    M.App.import_offer_sources = import_offer_sources

    # ------------------------------------------------------------------
    # Canonical Outlook-selection importer. v631 wraps this with COM lifetime
    # protection and diagnostics after this layer is applied.
    # ------------------------------------------------------------------
    def import_selected_outlook_offer(self):
        from tkinter import messagebox
        import os

        if os.name != 'nt':
            return messagebox.showerror(
                'Přenos z Outlooku',
                'Přímý import z Outlooku je dostupný pouze ve Windows.',
                parent=self,
            )

        try:
            import win32com.client
        except Exception as exc:
            return messagebox.showerror(
                'Přenos z Outlooku',
                'Chybí pywin32. Restartujte aplikaci po aktualizaci.\n\n'
                + str(exc),
                parent=self,
            )

        temp_dir = None
        good = []
        errors = []
        excel_count = 0
        try:
            try:
                outlook = win32com.client.GetActiveObject('Outlook.Application')
            except Exception:
                outlook = win32com.client.Dispatch('Outlook.Application')

            explorer = outlook.ActiveExplorer()
            selection = explorer.Selection if explorer is not None else None
            count = int(selection.Count) if selection is not None else 0
            if count < 1:
                raise RuntimeError('V Outlooku není vybraný žádný e-mail.')

            temp_dir = tempfile.TemporaryDirectory(prefix='turto_outlook_')
            paths = []
            for index in range(1, count + 1):
                item = selection.Item(index)
                try:
                    if int(getattr(item, 'Class', 0)) != 43:
                        continue
                except Exception:
                    pass
                subject = str(getattr(item, 'Subject', '') or f'outlook_{index}')
                filename = safe(subject, 120) or f'outlook_{index}'
                path = Path(temp_dir.name) / (filename + f'_{index}.msg')
                try:
                    item.SaveAs(str(path), 9)
                except Exception:
                    item.SaveAs(str(path), 3)
                if path.exists() and path.stat().st_size > 0:
                    paths.append(path)

            if not paths:
                raise RuntimeError(
                    'Výběr Outlooku neobsahuje zpracovatelný e-mail.'
                )

            for path in paths:
                try:
                    result = M.process_offer_msg(self, path)
                    good.extend((result or {}).get('offers') or [])
                    excel_count += len((result or {}).get('excel_files') or [])
                    errors.extend((result or {}).get('errors') or [])
                    for item in (result or {}).get('results') or []:
                        if isinstance(item, dict) and item.get('error'):
                            errors.append(str(item['error']))
                except Exception as exc:
                    errors.append(f'{path.name}: {exc}')

            try:
                self.refresh_offers()
            except Exception:
                pass

            if errors:
                title = (
                    'Import se nezdařil'
                    if not good
                    else 'Import dokončen s upozorněními'
                )
                return messagebox.showwarning(
                    title,
                    f'Nabídky: {len(good)}\n'
                    f'Excelové extrakce: {excel_count}\n\n'
                    + '\n'.join(errors[:12]),
                    parent=self,
                )
            messagebox.showinfo(
                'Přenos z Outlooku',
                f'Import dokončen.\n\nNabídky: {len(good)}\n'
                f'Excelové extrakce: {excel_count}',
                parent=self,
            )
            return good
        except Exception as exc:
            messagebox.showerror(
                'Přenos z Outlooku',
                str(exc),
                parent=self,
            )
            return []
        finally:
            try:
                if temp_dir:
                    temp_dir.cleanup()
            except Exception:
                pass

    M.App.import_selected_outlook_offer = import_selected_outlook_offer

    # ------------------------------------------------------------------
    # DB-only deletion; the physical archive remains independent.
    # ------------------------------------------------------------------
    def selected_offer_ids(self):
        tree = getattr(self, 'offer_tree', None)
        if tree is None:
            return []
        result = []
        try:
            for iid in tree.selection():
                text = str(iid)
                if not text.startswith('o'):
                    continue
                try:
                    offer_id = int(text[1:])
                except Exception:
                    continue
                if offer_id not in result:
                    result.append(offer_id)
        except Exception:
            pass
        return result

    M.App._selected_offer_ids = selected_offer_ids

    def delete_offer(self):
        offer_ids = self._selected_offer_ids()
        if not offer_ids:
            return M.messagebox.showinfo(
                'Nabídky',
                'Vyberte jednu nebo více nabídek.',
                parent=self,
            )

        count = len(offer_ids)
        if count == 1:
            question = 'Opravdu odstranit vybranou nabídku z databáze CRM?'
        else:
            question = f'Opravdu odstranit {count} vybraných nabídek z databáze CRM?'
        question += '\n\nSoubory na disku zůstanou beze změny.'
        if not M.messagebox.askyesno('Odstranit nabídky', question, parent=self):
            return

        placeholders = ','.join('?' for _ in offer_ids)
        params = tuple(offer_ids)
        try:
            with M.db() as con:
                try:
                    con.execute(
                        f'UPDATE offer_source_attachments SET offer_id=NULL '
                        f'WHERE offer_id IN ({placeholders})',
                        params,
                    )
                except Exception:
                    pass
                con.execute(
                    f'DELETE FROM supplier_offers WHERE id IN ({placeholders})',
                    params,
                )
            self.refresh_offers()
        except Exception as exc:
            M.messagebox.showerror('Nabídky', str(exc), parent=self)

    M.App.delete_offer = delete_offer

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            tree = getattr(self, 'offer_tree', None)
            if tree is not None:
                tree.configure(selectmode='extended')
        except Exception:
            pass
        try:
            self.update_idletasks()
            normalize(self)
            recolor_dashboard(self)
        except Exception:
            pass
        try:
            self.after(1200, lambda: reclaim_tree_layout(self))
        except Exception:
            pass
        try:
            # One safe pass also removes verified leftovers from older releases.
            self.after(1800, lambda: cleanup_legacy_offer_staging(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init
