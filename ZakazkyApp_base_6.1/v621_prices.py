# TURTO CRM 6.0.21 - product price browser, request linking, safer delete


def apply(M):
    # --- additive compatibility schema ---
    try:
        with M.db() as con:
            if not M.has_column(con, 'supplier_offers', 'request_id'):
                con.execute('ALTER TABLE supplier_offers ADD COLUMN request_id INTEGER')
            if not M.has_column(con, 'offer_source_messages', 'archive_path'):
                con.execute(
                    'ALTER TABLE offer_source_messages '
                    'ADD COLUMN archive_path TEXT DEFAULT ""'
                )
            if not M.has_column(con, 'offer_source_attachments', 'archive_path'):
                con.execute(
                    'ALTER TABLE offer_source_attachments '
                    'ADD COLUMN archive_path TEXT DEFAULT ""'
                )
            con.execute(
                'CREATE INDEX IF NOT EXISTS idx_offer_items_price_browser '
                'ON supplier_offer_items(item_key,offer_id)'
            )
            con.execute(
                'CREATE INDEX IF NOT EXISTS idx_supplier_offers_request '
                'ON supplier_offers(request_id)'
            )
    except Exception:
        pass

    # Physical archive ownership moved to the canonical post_baseline pipeline in
    # TURTO CRM 6.3. This module must NOT create TURTO Zakazky\Dokumenty\Nabidky,
    # copy MSG/PDF/attachments there, or clear source BLOBs after import. Keeping
    # archive ownership in one place prevents mail fragments/signature resources
    # from being materialized by an obsolete secondary pipeline.

    # --- Product / price browser ---
    class ProductPriceBrowser(M.tk.Toplevel):
        def __init__(self, parent):
            super().__init__(parent)
            self.title('Produkty / ceny')
            M.enable_dialog_maximize(self, 1320, 820)
            self.transient(parent)
            frame = M.ttk.Frame(self, padding=14)
            frame.pack(fill='both', expand=True)
            top = M.ttk.Frame(frame)
            top.pack(fill='x', pady=(0, 8))
            M.ttk.Label(top, text='Produkty / ceny', style='PageTitle.TLabel').pack(
                side='left'
            )
            self.q = M.tk.StringVar()
            entry = M.ttk.Entry(top, textvariable=self.q, width=38)
            entry.pack(side='right')
            M.ttk.Label(top, text='Hledat:').pack(side='right', padx=(0, 6))
            entry.bind('<KeyRelease>', lambda _event: self.load())

            columns = (
                'Dodavatel', 'Kód', 'Produkt', 'Poslední cena', 'Sleva',
                'Datum', 'Předchozí cena', 'Změna %', 'Akce', 'Poptávka',
            )
            self.t = M.ttk.Treeview(frame, columns=columns, show='headings')
            for column, width in zip(
                columns, (150, 110, 330, 110, 75, 95, 115, 80, 210, 210)
            ):
                self.t.heading(column, text=column)
                self.t.column(column, width=width, anchor='w')
            self.t.pack(fill='both', expand=True)
            M.bind_row_double_click(self.t, lambda _event: self.history())

            buttons = M.ttk.Frame(frame)
            buttons.pack(fill='x', pady=(8, 0))
            M.ttk.Button(
                buttons,
                text='Historie ceny',
                style='Accent.TButton',
                command=self.history,
            ).pack(side='right')
            M.ttk.Button(
                buttons, text='Zavřít', command=self.destroy
            ).pack(side='right', padx=6)
            self.rows = {}
            self.load()

        def load(self):
            for item in self.t.get_children():
                self.t.delete(item)
            self.rows = {}
            query = (self.q.get() or '').strip().casefold()
            with M.db() as con:
                has_request = M.has_column(con, 'supplier_offers', 'request_id')
                request_join = 'LEFT JOIN requests r ON r.id=o.request_id' if has_request else ''
                request_select = ',r.item request_item' if has_request else ",'' request_item"
                rows = con.execute(
                    f'''SELECT i.id,i.item_key,i.product_code,i.original_name,
                               i.unit_price,i.discount_pct,o.offer_date,
                               coalesce(s.official_name,o.supplier_name,'') supplier,
                               a.name action_name {request_select}
                        FROM supplier_offer_items i
                        JOIN supplier_offers o ON o.id=i.offer_id
                        LEFT JOIN companies s ON s.id=o.supplier_company_id
                        LEFT JOIN actions a ON a.id=o.action_id
                        {request_join}
                        ORDER BY supplier COLLATE CZECH,
                                 i.item_key COLLATE CZECH,
                                 o.offer_date DESC,o.id DESC,i.id DESC'''
                ).fetchall()

            groups = {}
            for row in rows:
                key = (
                    (row['supplier'] or '').casefold(),
                    row['item_key'] or row['original_name'] or '',
                )
                groups.setdefault(key, []).append(row)

            number = 0
            for _key, history in groups.items():
                row = history[0]
                previous = history[1] if len(history) > 1 else None
                haystack = ' '.join(
                    str(row[key] or '')
                    for key in ('supplier', 'product_code', 'original_name', 'item_key')
                ).casefold()
                if query and query not in haystack:
                    continue
                last = float(row['unit_price'] or 0)
                previous_value = float(previous['unit_price'] or 0) if previous else 0
                change = (
                    (last / previous_value - 1) * 100
                    if last and previous_value else None
                )
                iid = f'p{number}'
                number += 1
                self.rows[iid] = dict(row)
                self.t.insert(
                    '', 'end', iid=iid,
                    values=(
                        row['supplier'],
                        row['product_code'] or '',
                        row['original_name'] or row['item_key'],
                        f'{last:,.2f}',
                        f"{float(row['discount_pct'] or 0):.2f} %",
                        M.fmt_date(row['offer_date']),
                        f'{previous_value:,.2f}' if previous_value else '',
                        f'{change:+.1f} %' if change is not None else '',
                        row['action_name'] or '',
                        row['request_item'] or '',
                    ),
                )

        def history(self):
            selection = self.t.selection()
            if not selection:
                return
            row = self.rows[selection[0]]
            try:
                import crm_features as F
                dialog = F.OfferPriceHistoryDialog(
                    self,
                    row['supplier'],
                    row['item_key'] or row['original_name'],
                    row['original_name'] or row['item_key'],
                )
                self.wait_window(dialog)
            except Exception as exc:
                M.messagebox.showerror('Produkty / ceny', str(exc), parent=self)

    M.ProductPriceBrowser = ProductPriceBrowser
    M.App.open_product_prices = lambda self: ProductPriceBrowser(self)

    # --- Optional request link for an offer ---
    def assign_offer_to_request(app, offer_id, parent=None):
        with M.db() as con:
            columns = [row[1] for row in con.execute('PRAGMA table_info(requests)')]
            if 'id' not in columns:
                return
            select = ['id'] + [
                column for column in
                ('item', 'asked_date', 'action_id', 'company_id', 'archived')
                if column in columns
            ]
            sql = 'SELECT ' + ','.join(select) + ' FROM requests'
            where = []
            if 'archived' in columns:
                where.append('coalesce(archived,0)=0')
            if where:
                sql += ' WHERE ' + ' AND '.join(where)
            sql += ' ORDER BY id DESC LIMIT 500'
            rows = con.execute(sql).fetchall()
        if not rows:
            return

        dialog = M.tk.Toplevel(parent or app)
        dialog.title('Přiřadit nabídku k Poptávce')
        M.enable_dialog_maximize(dialog, 980, 650)
        dialog.transient(parent or app)
        dialog.grab_set()
        frame = M.ttk.Frame(dialog, padding=14)
        frame.pack(fill='both', expand=True)
        M.ttk.Label(
            frame,
            text='Přiřadit k Poptávce (nepovinné)',
            style='Section.TLabel',
        ).pack(anchor='w')
        tree = M.ttk.Treeview(
            frame,
            columns=('ID', 'Poptáváno', 'Datum', 'Akce'),
            show='headings',
        )
        for column in ('ID', 'Poptáváno', 'Datum', 'Akce'):
            tree.heading(column, text=column)
        tree.pack(fill='both', expand=True, pady=8)

        with M.db() as con:
            for row in rows:
                action_name = ''
                if 'action_id' in row.keys() and row['action_id']:
                    action = con.execute(
                        'SELECT name FROM actions WHERE id=?', (row['action_id'],)
                    ).fetchone()
                    action_name = action['name'] if action else ''
                tree.insert(
                    '', 'end', iid=str(row['id']),
                    values=(
                        row['id'],
                        row['item'] if 'item' in row.keys() else '',
                        M.fmt_date(row['asked_date']) if 'asked_date' in row.keys() else '',
                        action_name,
                    ),
                )

        def save():
            selection = tree.selection()
            if not selection:
                return
            request_id = int(selection[0])
            with M.db() as con:
                request = con.execute(
                    'SELECT * FROM requests WHERE id=?', (request_id,)
                ).fetchone()
                action_id = (
                    request['action_id']
                    if request and 'action_id' in request.keys() else None
                )
                con.execute(
                    'UPDATE supplier_offers '
                    'SET request_id=?,action_id=coalesce(?,action_id) WHERE id=?',
                    (request_id, action_id, offer_id),
                )
            dialog.destroy()
            try:
                app.refresh_offers()
            except Exception:
                pass

        buttons = M.ttk.Frame(frame)
        buttons.pack(fill='x')
        M.ttk.Button(
            buttons, text='Bez přiřazení', command=dialog.destroy
        ).pack(side='right')
        M.ttk.Button(
            buttons, text='Přiřadit', style='Accent.TButton', command=save
        ).pack(side='right', padx=6)
        tree.bind('<Double-1>', lambda _event: save())
        dialog.wait_window()

    M.assign_offer_to_request = assign_offer_to_request

    # Historical Offer UI hooks remain for compatibility. The final Offers page
    # composition is reasserted later by crm_features.install_offer_ui().
    old_build = M.App.build_offers

    def build_offers(self):
        old_build(self)
        try:
            page = self.tabs['offers']
            bar = M.ttk.Frame(page, style='Panel.TFrame', padding=(10, 7))
            bar.pack(
                fill='x',
                before=page.winfo_children()[0] if page.winfo_children() else None,
                pady=(0, 5),
            )
            M.ttk.Button(
                bar,
                text='💰 Produkty / ceny',
                style='Accent.TButton',
                command=self.open_product_prices,
            ).pack(side='left')
            M.ttk.Label(
                bar,
                text='Přehled posledních a předchozích cen bez rozklikávání jednotlivých nabídek.',
                style='PageSubtitle.TLabel',
            ).pack(side='left', padx=10)

            def walk(widget):
                for child in list(widget.winfo_children()):
                    try:
                        if (
                            child.winfo_class().endswith('Button')
                            and 'PDF' in str(child.cget('text')).upper()
                        ):
                            child.destroy()
                            continue
                    except Exception:
                        pass
                    walk(child)

            walk(page)
        except Exception:
            pass

    M.App.build_offers = build_offers

    # Offer detail: replace action-only linking with request-aware linking and
    # suppress original PDF button.
    try:
        import crm_features as F
        Detail = F.OfferDetailDialog
        old_detail_build = Detail._build

        def detail_build(self):
            old_detail_build(self)
            try:
                for widget in self.f.winfo_children():
                    for child in list(widget.winfo_children()):
                        try:
                            if (
                                child.winfo_class().endswith('Button')
                                and 'PDF' in str(child.cget('text')).upper()
                            ):
                                child.destroy()
                        except Exception:
                            pass
                tools = M.ttk.Frame(self.f, style='Panel.TFrame')
                tools.pack(fill='x', pady=(6, 0))
                M.ttk.Button(
                    tools,
                    text='Přiřadit k Poptávce…',
                    style='Toolbar.TButton',
                    command=lambda: assign_offer_to_request(
                        self.parent_app, self.oid, self
                    ),
                ).pack(side='left')
            except Exception:
                pass

        Detail._build = detail_build
    except Exception:
        pass

    # Safer delete of wrongly-created opportunities: never hang on FK/linked records.
    def delete_action(self):
        selection = self.action_tree.selection()
        if not selection:
            return
        action_id = int(str(selection[0]).lstrip('aA'))
        with M.db() as con:
            row = con.execute(
                'SELECT name FROM actions WHERE id=?', (action_id,)
            ).fetchone()
            if not row:
                return
            dependencies = []
            for table, label in (
                ('requests', 'Poptávky'),
                ('tasks', 'Úkoly'),
                ('supplier_offers', 'Nabídky'),
            ):
                try:
                    columns = [
                        item[1] for item in con.execute(f'PRAGMA table_info({table})')
                    ]
                    if 'action_id' in columns:
                        count = con.execute(
                            f'SELECT count(*) n FROM {table} WHERE action_id=?',
                            (action_id,),
                        ).fetchone()['n']
                        if count:
                            dependencies.append(f'{label}: {count}')
                except Exception:
                    pass
        if dependencies:
            return M.messagebox.showwarning(
                'Smazat Příležitost',
                'Příležitost nelze smazat, protože má vazby:\n'
                + '\n'.join(dependencies)
                + '\n\nNejprve vazby odpojte nebo záznam zrušte.',
                parent=self,
            )
        if not M.messagebox.askyesno(
            'Smazat Příležitost',
            f"Opravdu smazat „{row['name']}“?",
            parent=self,
        ):
            return
        try:
            with M.db() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('DELETE FROM actions WHERE id=?', (action_id,))
                con.commit()
            try:
                self.refresh_actions()
                self.refresh_dash()
            except Exception:
                pass
        except Exception as exc:
            M.messagebox.showerror(
                'Smazat Příležitost',
                f'Smazání se nepodařilo:\n{exc}',
                parent=self,
            )

    M.App.delete_action = delete_action

    # Help note.
    try:
        old_help = M.App.build_help

        def help_page(self):
            result = old_help(self)
            try:
                import tkinter as tk

                def walk(widget):
                    if isinstance(widget, tk.Text):
                        widget.configure(state='normal')
                        widget.insert(
                            'end',
                            '\n\nNABÍDKY – PRODUKTY / CENY\n'
                            'Přehled Produkty / ceny zobrazuje poslední a předchozí '
                            'cenu, změnu, dodavatele, Akci a Poptávku. Fyzický archiv '
                            'Nabídek spravuje výhradně aktuální archivní pipeline; tento '
                            'modul již nevytváří pomocnou složku Dokumenty/Nabidky ani '
                            'do ní nekopíruje části e-mailů.',
                        )
                        widget.configure(state='disabled')
                    for child in widget.winfo_children():
                        walk(child)

                walk(self.tabs['help'])
            except Exception:
                pass
            return result

        M.App.build_help = help_page
    except Exception:
        pass
