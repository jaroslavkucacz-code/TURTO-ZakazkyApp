# TURTO CRM - robust MSG import + inline product image panel.
import hashlib
import io
import re
import tempfile
from pathlib import Path


def apply(M):
    # ------------------------------------------------------------------
    # Robust Outlook .MSG import. Use extract_msg.openMsg and tolerate
    # attachment API differences across extract-msg versions.
    # ------------------------------------------------------------------
    def _bytes_from_attachment(att, tempdir):
        try:
            data = getattr(att, 'data', None)
            if callable(data):
                data = data()
            if isinstance(data, (bytes, bytearray, memoryview)):
                return bytes(data)
        except Exception:
            pass

        try:
            data = att.get_data()
            if isinstance(data, (bytes, bytearray, memoryview)):
                return bytes(data)
        except Exception:
            pass

        try:
            before = {p.name for p in Path(tempdir).iterdir()}
            result = att.save(customPath=str(tempdir))
            candidates = []
            if result:
                try:
                    candidates.append(Path(result))
                except Exception:
                    pass
            candidates += [
                p
                for p in Path(tempdir).iterdir()
                if p.name not in before and p.is_file()
            ]
            for path in candidates:
                if path.exists() and path.is_file():
                    return path.read_bytes()
        except Exception:
            pass
        return b''

    def _is_benign_non_offer(exc):
        # Technical sheets/drawings/certificates inside an e-mail are normal.
        if bool(getattr(exc, 'benign_offer_attachment', False)):
            return True
        # Compatibility while an in-place update replaces both modules.
        return (
            str(exc).strip()
            == 'PDF není rozpoznáno jako podporovaná cenová nabídka.'
        )

    def process_msg(app, path):
        path = Path(path)
        raw = path.read_bytes()
        message_hash = hashlib.sha256(raw).hexdigest()

        try:
            import extract_msg
        except Exception as exc:
            raise RuntimeError(
                'Knihovna extract-msg není dostupná. '
                'Aktualizujte/obnovte knihovny aplikace.'
            ) from exc

        try:
            msg = extract_msg.openMsg(str(path))
        except Exception as exc:
            raise RuntimeError(f'.MSG se nepodařilo otevřít: {exc}') from exc

        try:
            subject = str(getattr(msg, 'subject', '') or '')
            sender = str(
                getattr(msg, 'sender', '')
                or getattr(msg, 'senderEmail', '')
                or ''
            )
            sent = getattr(msg, 'date', '')
            try:
                sent = (
                    sent.strftime('%Y-%m-%d %H:%M:%S')
                    if hasattr(sent, 'strftime')
                    else str(sent or '')
                )
            except Exception:
                sent = str(sent or '')
            body = str(getattr(msg, 'body', '') or '')

            with M.db() as con:
                row = con.execute(
                    'SELECT id FROM offer_source_messages WHERE source_hash=?',
                    (message_hash,),
                ).fetchone()
                if row:
                    message_id = row['id']
                else:
                    message_id = con.execute(
                        '''INSERT INTO offer_source_messages(
                            source_path,source_hash,subject,sender,sent_at,body,
                            imported_by,status
                        ) VALUES(?,?,?,?,?,?,?,?)''',
                        (
                            str(path),
                            message_hash,
                            subject,
                            sender,
                            sent,
                            body,
                            M.get_setting('active_user', ''),
                            'ZPRACOVÁVÁ SE',
                        ),
                    ).lastrowid

            results = []
            attachments = 0
            unsupported = []
            errors = []

            with tempfile.TemporaryDirectory(prefix='turto_msg_') as td:
                tempdir = Path(td)
                for index, attachment in enumerate(
                    getattr(msg, 'attachments', []) or [],
                    1,
                ):
                    name = str(
                        getattr(attachment, 'longFilename', None)
                        or getattr(attachment, 'shortFilename', None)
                        or getattr(attachment, 'name', None)
                        or f'priloha_{index}'
                    )
                    data = _bytes_from_attachment(attachment, tempdir)
                    if not data:
                        errors.append(f'{name}: přílohu se nepodařilo načíst')
                        continue

                    attachments += 1
                    ext = Path(name).suffix.lower()
                    content_hash = hashlib.sha256(data).hexdigest()

                    with M.db() as con:
                        con.execute(
                            '''INSERT OR IGNORE INTO offer_source_attachments(
                                message_id,filename,extension,content_hash,content_blob
                            ) VALUES(?,?,?,?,?)''',
                            (
                                message_id,
                                name,
                                ext,
                                content_hash,
                                M.sqlite3.Binary(data),
                            ),
                        )

                    safe = (
                        re.sub(r'[^\w.()\- ]+', '_', Path(name).name)
                        or f'priloha_{index}'
                    )
                    temp_path = tempdir / (f'{index:03d}_' + safe)
                    temp_path.write_bytes(data)

                    if ext == '.pdf':
                        try:
                            result = M.process_offer_pdf(
                                app,
                                temp_path,
                                message_id,
                                name,
                                data,
                            )
                            results.append(result)
                        except Exception as exc:
                            if _is_benign_non_offer(exc):
                                unsupported.append(name)
                            else:
                                errors.append(f'{name}: {exc}')
                    else:
                        unsupported.append(name)

            good = [
                result
                for result in results
                if result and not result.get('error')
            ]
            note = (
                f'Příloh: {attachments}; '
                f'rozpoznaných nabídek: {len(good)}; '
                f'ostatní: {len(unsupported)}; '
                f'chyb: {len(errors)}'
            )

            with M.db() as con:
                con.execute(
                    'UPDATE offer_source_messages SET status=?,note=? WHERE id=?',
                    (
                        'HOTOVO'
                        if good
                        else (
                            'NAČTENO – BEZ ROZPOZNANÉ PDF NABÍDKY'
                            if attachments
                            else 'BEZ PŘÍLOH'
                        ),
                        note,
                        message_id,
                    ),
                )

            return {
                'message_id': message_id,
                'attachments': attachments,
                'offers': good,
                'results': results,
                'unsupported': unsupported,
                'errors': errors,
                'subject': subject,
            }
        finally:
            try:
                msg.close()
            except Exception:
                pass

    M.process_offer_msg = process_msg

    # Detailed real parser/attachment errors remain visible. Ordinary non-offer
    # PDFs inside MSG are intentionally treated as "other attachments".
    def import_offer_sources(app):
        from tkinter import filedialog, messagebox

        paths = filedialog.askopenfilenames(
            parent=app,
            title='Importovat cenové nabídky',
            filetypes=[
                ('Nabídky / e-maily', '*.pdf *.msg'),
                ('PDF', '*.pdf'),
                ('Outlook zprávy', '*.msg'),
                ('Všechny soubory', '*.*'),
            ],
        )
        if not paths:
            return

        ok = []
        errors = []
        msg_count = 0
        att_count = 0

        for path in paths:
            try:
                if str(path).lower().endswith('.msg'):
                    result = process_msg(app, path)
                    msg_count += 1
                    att_count += result['attachments']
                    ok.extend(result['offers'])
                    errors.extend(result.get('errors') or [])
                elif str(path).lower().endswith('.pdf'):
                    # A directly selected PDF is expected to be an offer.
                    ok.append(M.process_offer_pdf(app, path))
                else:
                    errors.append(
                        f'{Path(path).name}: nepodporovaný vstupní formát'
                    )
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')

        try:
            app.refresh_offers()
        except Exception:
            pass

        text = (
            'Import dokončen.\n\n'
            f'Nabídky: {len(ok)}\n'
            f'MSG: {msg_count}\n'
            f'Přílohy v MSG: {att_count}'
        )
        if errors:
            text += '\n\nChyby:\n' + '\n'.join(errors[:15])
        messagebox.showinfo(
            'Zpracování cenových nabídek',
            text,
            parent=app,
        )

    M.App.import_offer_sources = import_offer_sources

    # ------------------------------------------------------------------
    # GEROtop/product images directly inside the Offer detail window.
    # ------------------------------------------------------------------
    try:
        import crm_features as F

        D = F.OfferDetailDialog
        old_build = D._build

        def _load_image_for(self, item):
            if not item:
                return None
            supplier = (
                self.offer_row['supplier']
                or self.offer_row['supplier_name']
                or ''
            )
            with M.db() as con:
                image = con.execute(
                    '''SELECT image_blob,image_ext,source_offer_no,source_offer_date
                       FROM offer_product_images
                       WHERE supplier=? AND item_key=?''',
                    (supplier, item['item_key']),
                ).fetchone()
                if not image or not image['image_blob']:
                    image2 = con.execute(
                        'SELECT image_blob,image_ext '
                        'FROM supplier_offer_items WHERE id=?',
                        (item['id'],),
                    ).fetchone()
                    if image2 and image2['image_blob']:
                        return {
                            'image_blob': image2['image_blob'],
                            'image_ext': image2['image_ext'],
                            'source_offer_no': self.offer_row['offer_number'],
                            'source_offer_date': self.offer_row['offer_date'],
                        }
            return dict(image) if image and image['image_blob'] else None

        def refresh_preview(self, *_):
            try:
                item = self._selected_item()
                if not item:
                    return
                self.preview_title.configure(
                    text=(
                        item.get('original_name')
                        or item.get('item_key')
                        or 'Položka'
                    )
                )
                self.preview_meta.configure(
                    text=(
                        f"Kód: {item.get('product_code') or '—'}   •   "
                        f"Množství: {item.get('quantity') or 0} "
                        f"{item.get('unit') or ''}   •   "
                        f"Cena/ks: {float(item.get('unit_price') or 0):,.2f}"
                    )
                )
                image = _load_image_for(self, item)
                if not image:
                    self.preview_image.configure(
                        image='',
                        text='K této položce není uložen obrázek.',
                    )
                    self.preview_image.image = None
                    self.preview_source.configure(text='')
                    return

                from PIL import Image, ImageTk

                img = Image.open(io.BytesIO(bytes(image['image_blob'])))
                img.thumbnail((320, 220))
                photo = ImageTk.PhotoImage(img)
                self.preview_image.configure(image=photo, text='')
                self.preview_image.image = photo
                self.preview_source.configure(
                    text=(
                        'Zdroj obrázku: nabídka '
                        f"{image.get('source_offer_no') or '—'} z "
                        f"{M.fmt_date(image.get('source_offer_date'))}"
                    )
                )
            except Exception as exc:
                try:
                    self.preview_image.configure(
                        image='',
                        text=f'Obrázek nelze zobrazit: {exc}',
                    )
                except Exception:
                    pass

        def build(self):
            old_build(self)
            try:
                panel = M.ttk.Frame(
                    self.f,
                    style='Card.TFrame',
                    padding=12,
                )
                panel.pack(fill='x', pady=(8, 0))
                self.preview_title = M.ttk.Label(
                    panel,
                    text='Vyberte položku',
                    style='Section.TLabel',
                )
                self.preview_title.grid(row=0, column=0, sticky='w')
                self.preview_meta = M.ttk.Label(
                    panel,
                    text='',
                    style='PageSubtitle.TLabel',
                )
                self.preview_meta.grid(
                    row=1,
                    column=0,
                    sticky='w',
                    pady=(2, 8),
                )
                self.preview_image = M.ttk.Label(
                    panel,
                    text='Vyberte položku nabídky.',
                )
                self.preview_image.grid(
                    row=0,
                    column=1,
                    rowspan=3,
                    sticky='e',
                    padx=(18, 0),
                )
                self.preview_source = M.ttk.Label(
                    panel,
                    text='',
                    style='PageSubtitle.TLabel',
                )
                self.preview_source.grid(
                    row=2,
                    column=0,
                    sticky='w',
                )
                panel.columnconfigure(0, weight=1)
                self.tree.bind(
                    '<<TreeviewSelect>>',
                    lambda _event: refresh_preview(self),
                    add='+',
                )
                if self.tree.get_children():
                    first = self.tree.get_children()[0]
                    self.tree.selection_set(first)
                    self.tree.focus(first)
                    refresh_preview(self)
            except Exception:
                pass

        def open_image_inline(self):
            refresh_preview(self)
            try:
                self.preview_image.focus_set()
            except Exception:
                pass

        D._build = build
        D.open_image = open_image_inline
        D.refresh_preview = refresh_preview
    except Exception:
        pass

    # Help note.
    try:
        old_help = M.App.build_help

        def help_page(self):
            result = old_help(self)
            try:
                import tkinter as tk

                page = self.tabs['help']

                def walk(widget):
                    if isinstance(widget, tk.Text):
                        widget.configure(state='normal')
                        widget.insert(
                            'end',
                            '\n\nNABÍDKY – IMPORT PDF / MSG\n'
                            'Import Outlook .MSG bezpečně uchovává přílohy. '
                            'PDF, které není cenovou nabídkou (např. technický '
                            'list), se eviduje jako ostatní příloha a nepovažuje '
                            'se za chybu. Skutečné chyby rozpoznané nabídky se '
                            'nadále zobrazí. Obrázky položek GEROtop se zobrazují '
                            'přímo v detailu nabídky.',
                        )
                        widget.configure(state='disabled')
                    for child in widget.winfo_children():
                        walk(child)

                walk(page)
            except Exception:
                pass
            return result

        M.App.build_help = help_page
    except Exception:
        pass
