# TURTO CRM - source MSG preservation and Offers drop-zone UI.
# Native drag-and-drop itself is owned exclusively by v631_diskdrop.
import hashlib
from pathlib import Path


def apply(M):
    # Preserve the original MSG bytes in the source-message record for audit /
    # future reprocessing. This is independent from the physical archive.
    try:
        with M.db() as con:
            if not M.has_column(con, 'offer_source_messages', 'source_blob'):
                con.execute(
                    'ALTER TABLE offer_source_messages ADD COLUMN source_blob BLOB'
                )
    except Exception:
        pass

    def store_source_blob(path, message_id=None):
        try:
            source = Path(path)
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            with M.db() as con:
                if message_id:
                    con.execute(
                        'UPDATE offer_source_messages SET source_blob=? WHERE id=?',
                        (M.sqlite3.Binary(raw), message_id),
                    )
                else:
                    con.execute(
                        'UPDATE offer_source_messages SET source_blob=? '
                        'WHERE source_hash=?',
                        (M.sqlite3.Binary(raw), digest),
                    )
        except Exception:
            pass

    old_process_msg = getattr(M, 'process_offer_msg', None)
    if callable(old_process_msg):
        def process_msg(app, path, *args, **kwargs):
            result = old_process_msg(app, path, *args, **kwargs)
            if isinstance(result, dict):
                store_source_blob(path, result.get('message_id'))
            else:
                store_source_blob(path)
            return result

        M.process_offer_msg = process_msg

    # Visual entry point only. Do not register TkDND here: the old widget-level
    # target could fire together with the native root OLE target and process one
    # Outlook drop twice.
    def setup_drop_area(app):
        try:
            page = app.tabs.get('offers')
            if page is None or getattr(app, '_offer_drop_area_ready', False):
                return
            app._offer_drop_area_ready = True
            children = page.winfo_children()
            box = M.ttk.Frame(
                page,
                style='Card.TFrame',
                padding=(16, 12),
            )
            box.pack(
                fill='x',
                before=children[0] if children else None,
                pady=(0, 8),
            )
            left = M.ttk.Frame(box, style='Card.TFrame')
            left.pack(side='left', fill='x', expand=True)
            M.ttk.Label(
                left,
                text='⇩  Přetáhněte PDF nebo MSG do okna programu',
                style='Section.TLabel',
            ).pack(anchor='w')
            M.ttk.Label(
                left,
                text=(
                    'Průzkumník i Outlook používají jeden bezpečný importní '
                    'mechanismus; obrázky z podpisů se nearchivují.'
                ),
                style='PageSubtitle.TLabel',
            ).pack(anchor='w', pady=(3, 0))
            M.ttk.Button(
                box,
                text='Načíst vybraný e-mail z Outlooku',
                style='Toolbar.TButton',
                command=lambda: app.import_selected_outlook_offer(),
            ).pack(side='right', padx=(12, 0))
        except Exception:
            pass

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after_idle(lambda: setup_drop_area(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init
