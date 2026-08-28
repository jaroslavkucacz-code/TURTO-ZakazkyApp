# TURTO CRM - canonical supplier-specific Excel export.
import io
import math


def apply(M):
    def _has(row, key):
        try:
            return key in row.keys()
        except Exception:
            return False

    def _v(row, *keys, default=''):
        for key in keys:
            try:
                if key in row.keys() and row[key] not in (None, ''):
                    return row[key]
            except Exception:
                pass
        return default

    def _num(value):
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _safe_no(value):
        text = str(value or 'nabidka').strip()
        return (
            ''.join(
                ch if ch.isalnum() or ch in '-_.' else '_'
                for ch in text
            ).strip('._')
            or 'nabidka'
        )

    def _save_path(parent, offer_no):
        from tkinter import filedialog

        return (
            filedialog.asksaveasfilename(
                parent=parent,
                title='Extrakce dat nabídky',
                defaultextension='.xlsx',
                filetypes=[('Excel', '*.xlsx')],
                initialfile=f'Extrakce dat CN {_safe_no(offer_no)}.xlsx',
            )
            or ''
        )

    def _load(offer_id):
        with M.db() as con:
            offer = con.execute(
                '''SELECT o.*,coalesce(s.official_name,o.supplier_name,'') supplier,
                          coalesce(cu.official_name,'') customer,
                          coalesce(a.name,'') action_name
                   FROM supplier_offers o
                   LEFT JOIN companies s ON s.id=o.supplier_company_id
                   LEFT JOIN companies cu ON cu.id=o.customer_company_id
                   LEFT JOIN actions a ON a.id=o.action_id
                   WHERE o.id=?''',
                (offer_id,),
            ).fetchone()
            items = con.execute(
                'SELECT * FROM supplier_offer_items '
                'WHERE offer_id=? ORDER BY position,id',
                (offer_id,),
            ).fetchall()
        return offer, items

    def _item_image(M, offer, item):
        blob = _v(item, 'image_blob', default=None)
        ext = _v(item, 'image_ext', default='png') or 'png'
        if blob:
            return blob, ext
        try:
            with M.db() as con:
                row = con.execute(
                    'SELECT image_blob,image_ext FROM offer_product_images '
                    'WHERE supplier=? AND item_key=?',
                    (
                        _v(offer, 'supplier'),
                        _v(item, 'item_key', 'original_name'),
                    ),
                ).fetchone()
            if row and row['image_blob']:
                return row['image_blob'], row['image_ext'] or 'png'
        except Exception:
            pass
        return None, 'png'

    def _export_leviat(wb, ws, offer, items):
        title = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'font_size': 16,
            'font_color': '#1F4E78',
        })
        label = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'bg_color': '#D9EAF7',
            'border': 1,
        })
        value = wb.add_format({'font_name': 'Calibri', 'border': 1})
        money = wb.add_format({
            'font_name': 'Calibri',
            'num_format': '#,##0.00 "Kč"',
            'border': 1,
        })
        pct = wb.add_format({
            'font_name': 'Calibri',
            'num_format': '0.00" %"',
            'border': 1,
        })
        head = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'font_color': 'white',
            'bg_color': '#1F4E78',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
        })
        text = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'valign': 'top',
            'text_wrap': True,
        })
        integer = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0',
            'valign': 'top',
        })
        item_money = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0.00 "Kč"',
            'valign': 'top',
        })

        offer_no = _v(offer, 'offer_number')
        net = _num(_v(offer, 'net_value', 'total_value'))
        gross = (
            _num(_v(offer, 'gross_value'))
            or sum(
                _num(_v(item, 'original_unit_price', 'unit_price'))
                * _num(_v(item, 'quantity'))
                for item in items
            )
        )
        if not net:
            net = sum(_num(_v(item, 'total_price')) for item in items)
        disc_value = max(0, gross - net)
        disc_pct = _num(_v(offer, 'discount_pct'))
        if not disc_pct and gross:
            disc_pct = 100 * disc_value / gross
        vat = round(net * 0.21, 2)
        total = round(net + vat, 2)
        reference = _v(offer, 'action_name', 'note') or 'Nepřiřazeno'

        ws.write('A1', f'Cenová nabídka {offer_no}', title)
        summary = [
            ('Číslo nabídky', offer_no, value),
            ('Datum', M.fmt_date(_v(offer, 'offer_date')), value),
            ('Reference / zakázka', reference, value),
            ('Součet položek před slevou', gross, money),
            ('Sleva %', disc_pct, pct),
            ('Sleva Kč', disc_value, money),
            ('Celkem bez DPH', net, money),
            ('DPH', vat, money),
            ('Celková částka s DPH', total, money),
        ]
        for row, (name, item_value, fmt) in enumerate(summary, start=2):
            ws.write(row - 1, 0, name, label)
            ws.write(row - 1, 1, item_value, fmt)

        start = 13
        ws.write(start - 1, 0, 'Pol.', head)
        ws.write(start - 1, 1, 'Číslo výrobku', head)
        ws.merge_range(start - 1, 2, start - 1, 7, 'Název položky', head)
        ws.write(start - 1, 8, 'Množství [KS]', head)
        ws.write(start - 1, 9, 'Cena za kus bez DPH', head)
        ws.write(start - 1, 10, 'Cena položky bez DPH', head)

        for row, item in enumerate(items, start=start):
            pos = _num(_v(item, 'position'))
            product = _v(item, 'product_code')
            desc = _v(item, 'original_name', 'item_key')
            qty = _num(_v(item, 'quantity'))
            unit_price = _num(_v(item, 'unit_price'))
            total_price = _num(_v(item, 'total_price')) or qty * unit_price
            ws.write_number(row, 0, pos, integer)
            ws.write(row, 1, product, text)
            ws.merge_range(row, 2, row, 7, desc, text)
            ws.write_number(row, 8, qty, integer)
            ws.write_number(row, 9, unit_price, item_money)
            ws.write_number(row, 10, total_price, item_money)

        last = start + len(items) - 1
        if items:
            ws.autofilter(start - 1, 0, last, 10)
        ws.freeze_panes(start, 0)
        ws.set_column('A:A', 9)
        ws.set_column('B:B', 17)
        ws.set_column('C:H', 10)
        ws.set_column('I:I', 15)
        ws.set_column('J:K', 22)
        ws.set_row(start - 1, 32)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)

    def _estimate_height(text):
        lines = max(1, len(str(text or '').splitlines()))
        chars = max(1, len(str(text or '')))
        return min(180, max(54, 15 * lines + 12 * math.ceil(chars / 56)))

    def _export_gerotop(wb, ws, offer, items):
        title = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'font_size': 16,
            'font_color': '#1F4E78',
        })
        label = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'bg_color': '#D9EAF7',
            'border': 1,
        })
        value = wb.add_format({'font_name': 'Calibri', 'border': 1})
        money = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0.00 "Kč"',
        })
        head = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
            'font_color': 'white',
            'bg_color': '#1F4E78',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
        })
        text = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'valign': 'vcenter',
            'align': 'left',
            'text_wrap': True,
        })
        bold_inline = wb.add_format({
            'font_name': 'Calibri',
            'bold': True,
        })
        normal_inline = wb.add_format({
            'font_name': 'Calibri',
        })
        integer = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0',
            'valign': 'vcenter',
            'align': 'center',
        })
        item_money = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0.00 "Kč"',
            'valign': 'vcenter',
            'align': 'center',
        })
        key_money = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '#,##0.00 "Kč"',
            'valign': 'vcenter',
            'align': 'center',
            'bold': True,
        })
        pct = wb.add_format({
            'font_name': 'Calibri',
            'border': 1,
            'num_format': '0.##" %"',
            'valign': 'vcenter',
            'align': 'center',
        })

        offer_no = _v(offer, 'offer_number')
        reference = _v(offer, 'action_name', 'note') or 'Nepřiřazeno'

        # Summary deliberately reports products only.
        product_net = 0.0
        for item in items:
            name = (
                str(_v(item, 'original_name'))
                + ' '
                + str(_v(item, 'product_code'))
            ).casefold()
            if any(
                marker in name
                for marker in (
                    'doprava',
                    'dopravné',
                    'balné',
                    'preprava',
                    'přeprava',
                )
            ):
                continue
            product_net += _num(_v(item, 'total_price'))
        if not product_net:
            product_net = _num(_v(offer, 'net_value', 'total_value'))

        ws.write('A1', f'Cenová nabídka {offer_no}', title)
        summary = [
            ('Dodavatel', _v(offer, 'supplier', default='GEROtop')),
            ('Číslo nabídky', offer_no),
            ('Datum', M.fmt_date(_v(offer, 'offer_date'))),
            ('Zakázka', reference),
            ('Celkem bez DPH – pouze výrobky', product_net),
        ]
        for row, (name, item_value) in enumerate(summary, start=2):
            ws.write(row - 1, 0, name, label)
            if isinstance(item_value, (int, float)):
                ws.write_number(row - 1, 1, item_value, money)
            else:
                ws.write(row - 1, 1, item_value, value)

        start = 9
        ws.write(start - 1, 0, 'Kód', head)
        ws.merge_range(
            start - 1,
            1,
            start - 1,
            4,
            'Název / technický popis',
            head,
        )
        ws.merge_range(start - 1, 5, start - 1, 6, 'Obrázek', head)
        ws.write(start - 1, 7, 'Počet [KS]', head)
        ws.write(start - 1, 8, 'Cena/ks po slevě', head)
        ws.write(start - 1, 9, 'Sleva', head)
        ws.write(start - 1, 10, 'Původní cena/ks', head)
        ws.write(start - 1, 11, 'Cena celkem', head)

        for row, item in enumerate(items, start=start):
            code = _v(item, 'product_code')
            desc = str(_v(item, 'original_name', 'item_key') or '').strip()
            details = str(_v(item, 'details') or '').strip()
            desc_full = desc + (('\n' + details) if details else '')
            qty = _num(_v(item, 'quantity'))
            unit_price = _num(_v(item, 'unit_price'))
            discount = _num(_v(item, 'discount_pct'))
            original = _num(_v(item, 'original_unit_price')) or unit_price
            total_price = _num(_v(item, 'total_price')) or qty * unit_price

            ws.write(row, 0, code, text)
            # Merge first, then put rich content into the top-left merged cell.
            ws.merge_range(row, 1, row, 4, '', text)
            if details and desc:
                try:
                    ws.write_rich_string(
                        row,
                        1,
                        bold_inline,
                        desc,
                        normal_inline,
                        '\n' + details,
                        text,
                    )
                except Exception:
                    ws.write(row, 1, desc_full, text)
            else:
                ws.write(row, 1, desc_full, text)

            ws.merge_range(row, 5, row, 6, '', text)
            ws.write_number(row, 7, qty, integer)
            ws.write_number(row, 8, unit_price, key_money)
            ws.write_number(row, 9, discount, pct)
            ws.write_number(row, 10, original, item_money)
            ws.write_number(row, 11, total_price, item_money)

            ws.set_row(row, _estimate_height(desc_full))

            blob, ext = _item_image(M, offer, item)
            if blob:
                try:
                    bio = io.BytesIO(bytes(blob))
                    try:
                        ws.embed_image(
                            row,
                            5,
                            'produkt.' + str(ext),
                            {'image_data': bio},
                        )
                    except Exception:
                        ws.insert_image(
                            row,
                            5,
                            'produkt.' + str(ext),
                            {
                                'image_data': bio,
                                'object_position': 1,
                                'x_scale': 0.45,
                                'y_scale': 0.45,
                            },
                        )
                except Exception:
                    pass

        ws.set_column('A:A', 16)
        ws.set_column('B:E', 11)
        ws.set_column('F:G', 18)
        ws.set_column('H:H', 12)
        ws.set_column('I:I', 20)
        ws.set_column('J:J', 11)
        ws.set_column('K:L', 19)
        ws.freeze_panes(start, 0)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)

    def export_legacy(app, offer_id, parent=None):
        from tkinter import messagebox

        try:
            import xlsxwriter
        except Exception as exc:
            return messagebox.showerror(
                'Extrakce dat',
                f'Chybí XlsxWriter.\n\n{exc}',
                parent=parent or app,
            )

        offer, items = _load(offer_id)
        if not offer:
            return
        path = _save_path(parent or app, _v(offer, 'offer_number'))
        if not path:
            return

        wb = None
        try:
            wb = xlsxwriter.Workbook(path)
            ws = wb.add_worksheet('Nabídka')
            supplier = str(_v(offer, 'supplier')).casefold()
            if 'gerotop' in supplier:
                _export_gerotop(wb, ws, offer, items)
            elif 'leviat' in supplier:
                _export_leviat(wb, ws, offer, items)
            else:
                _export_leviat(wb, ws, offer, items)
            wb.close()
            messagebox.showinfo(
                'Extrakce dat',
                f'Extrakce vytvořena:\n{path}',
                parent=parent or app,
            )
        except Exception as exc:
            try:
                if wb:
                    wb.close()
            except Exception:
                pass
            messagebox.showerror(
                'Extrakce dat',
                str(exc),
                parent=parent or app,
            )

    M.export_offer_excel = export_legacy

    def selected(self):
        offer_id = (
            self._selected_offer_id()
            if hasattr(self, '_selected_offer_id')
            else None
        )
        if not offer_id:
            return M.messagebox.showinfo(
                'Extrakce dat',
                'Vyberte nabídku.',
                parent=self,
            )
        return export_legacy(self, offer_id, self)

    M.App.export_selected_offer_excel = selected

    # v6.0.23 detail button captured the old exporter in a closure.
    try:
        import crm_features as F

        D = F.OfferDetailDialog
        old = D._build

        def build(self):
            result = old(self)
            try:
                def walk(widget):
                    for child in widget.winfo_children():
                        try:
                            if (
                                child.winfo_class().endswith('Button')
                                and str(child.cget('text')).strip()
                                == 'Exportovat do Excelu'
                            ):
                                child.configure(
                                    text='Extrakce dat do Excelu',
                                    command=lambda: export_legacy(
                                        self.parent_app,
                                        self.oid,
                                        self,
                                    ),
                                )
                        except Exception:
                            pass
                        walk(child)

                walk(self.f)
            except Exception:
                pass
            return result

        D._build = build
    except Exception:
        pass

    old_build = M.App.build_offers

    def build_offers(self):
        result = old_build(self)
        try:
            page = self.tabs['offers']

            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        if (
                            child.winfo_class().endswith('Button')
                            and 'Export vybrané nabídky'
                            in str(child.cget('text'))
                        ):
                            child.configure(
                                text='Extrakce dat vybrané nabídky'
                            )
                    except Exception:
                        pass
                    walk(child)

            walk(page)
        except Exception:
            pass
        return result

    M.App.build_offers = build_offers

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
                            '\n\nEXTRAKCE DAT NABÍDEK\n'
                            'Export jednotlivé nabídky používá dodavatelské '
                            'šablony. GEROtop export obsahuje název i technický '
                            'popis položky, obrázek, množství, cenu po slevě, '
                            'slevu, původní cenu a celkovou cenu. Leviat export '
                            'zachovává vlastní rekapitulaci a tabulku položek.',
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
