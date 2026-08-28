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
                normalize(self)
                try:
                    self.after_idle(lambda: recolor_dashboard(self))
                except Exception:
                    recolor_dashboard(self)
                return result

            return wrapped

        setattr(M.App, name, make(old))

    old_show = getattr(M.App, 'show_page', None)
    if callable(old_show):
        def show_page(self, *args, **kwargs):
            result = old_show(self, *args, **kwargs)
            normalize(self)
            recolor_dashboard(self)
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

    def folder_for(app, offer_id, path=None, subject=''):
        with M.db() as con:
            offer = con.execute(
                "SELECT offer_date,offer_number,coalesce(supplier_name,'') supplier "
                'FROM supplier_offers WHERE id=?',
                (offer_id,),
            ).fetchone()
        digest = ''
        try:
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8]
        except Exception:
            pass
        source_name = Path(path).stem if path else 'nabidka'
        parts = (
            ((offer['offer_date'] or '')[:10] if offer else '') or 'bez-data',
            safe(offer['supplier'] if offer else '', 35),
            safe(
                (offer['offer_number'] if offer else '')
                or subject
                or source_name,
                55,
            ),
            digest,
        )
        folder = archive_root(app) / '_'.join(part for part in parts if part)
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
                output = folder / 'Extrakce_nabidky.xlsx'
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
            for index, offer in enumerate(offers, 1):
                output = folder / (
                    'Extrakce_nabidky.xlsx'
                    if len(offers) == 1
                    else f'Extrakce_nabidky_{index}.xlsx'
                )
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
    def delete_offer(self):
        offer_id = (
            self._selected_offer_id()
            if hasattr(self, '_selected_offer_id')
            else None
        )
        if not offer_id:
            return
        if not M.messagebox.askyesno(
            'Nabídky',
            'Opravdu odstranit tento import nabídky z CRM?\n\n'
            'Soubory na disku zůstanou beze změny.',
            parent=self,
        ):
            return
        try:
            with M.db() as con:
                try:
                    con.execute(
                        'UPDATE offer_source_attachments '
                        'SET offer_id=NULL WHERE offer_id=?',
                        (offer_id,),
                    )
                except Exception:
                    pass
                con.execute(
                    'DELETE FROM supplier_offers WHERE id=?',
                    (offer_id,),
                )
            self.refresh_offers()
        except Exception as exc:
            M.messagebox.showerror(
                'Nabídky',
                str(exc),
                parent=self,
            )

    M.App.delete_offer = delete_offer

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
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
        return result

    M.App.__init__ = init
