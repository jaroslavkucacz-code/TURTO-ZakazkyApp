# TURTO CRM - canonical supplier-specific Excel export.
import io
import json
import math
import re


def apply(M):
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

    def _safe_filename_part(value, fallback='nabidka', maxlen=90):
        text = re.sub(
            r'[<>:"/\\|?*\x00-\x1f]+',
            '_',
            str(value or ''),
        )
        text = ' '.join(text.split()).strip(' ._')
        return (text or fallback)[:maxlen].rstrip(' .')

    def _export_filename_from_offer(offer):
        offer_no = _safe_filename_part(
            _v(offer, 'offer_number'),
            fallback='nabidka',
            maxlen=55,
        )
        supplier_reference = _safe_filename_part(
            _v(offer, 'reference'),
            fallback='',
            maxlen=95,
        )
        suffix = f'_{supplier_reference}' if supplier_reference else ''
        return f'Extrakce dat CN {offer_no}{suffix}.xlsx'

    def export_filename(offer_id):
        try:
            with M.db() as con:
                offer = con.execute(
                    'SELECT offer_number,reference FROM supplier_offers WHERE id=?',
                    (offer_id,),
                ).fetchone()
            if offer:
                return _export_filename_from_offer(offer)
        except Exception:
            pass
        return 'Extrakce dat CN nabidka.xlsx'

    M.offer_export_filename = export_filename

    def _save_path(parent, offer):
        from tkinter import filedialog
        return filedialog.asksaveasfilename(
            parent=parent,
            title='Extrakce dat nabídky',
            defaultextension='.xlsx',
            filetypes=[('Excel', '*.xlsx')],
            initialfile=_export_filename_from_offer(offer),
        ) or ''

    def _load(offer_id):
        ensure = getattr(M, 'ensure_offer_rich_details', None)
        if callable(ensure):
            try:
                ensure(offer_id)
            except Exception:
                pass
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

    def _item_image(offer, item):
        blob = _v(item, 'image_blob', default=None)
        ext = _v(item, 'image_ext', default='png') or 'png'
        if blob:
            return blob, ext
        try:
            with M.db() as con:
                row = con.execute(
                    'SELECT image_blob,image_ext FROM offer_product_images '
                    'WHERE supplier=? AND item_key=?',
                    (_v(offer, 'supplier'), _v(item, 'item_key', 'original_name')),
                ).fetchone()
            if row and row['image_blob']:
                return row['image_blob'], row['image_ext'] or 'png'
        except Exception:
            pass
        return None, 'png'

    def _base_formats(wb):
        return {
            'title': wb.add_format({
                'font_name': 'Calibri', 'bold': True, 'font_size': 16,
                'font_color': '#1F4E78',
            }),
            'label': wb.add_format({
                'font_name': 'Calibri', 'bold': True, 'bg_color': '#D9EAF7',
                'border': 1,
            }),
            'value': wb.add_format({'font_name': 'Calibri', 'border': 1}),
            'money': wb.add_format({
                'font_name': 'Calibri', 'border': 1,
                'num_format': '#,##0.00 "Kč"',
            }),
            'pct': wb.add_format({
                'font_name': 'Calibri', 'border': 1,
                'num_format': '0.##" %"',
            }),
            'head': wb.add_format({
                'font_name': 'Calibri', 'bold': True, 'font_color': 'white',
                'bg_color': '#1F4E78', 'border': 1, 'align': 'center',
                'valign': 'vcenter', 'text_wrap': True,
            }),
            'text_top': wb.add_format({
                'font_name': 'Calibri', 'border': 1, 'valign': 'top',
                'text_wrap': True,
            }),
            'text_center': wb.add_format({
                'font_name': 'Calibri', 'border': 1, 'valign': 'vcenter',
                'align': 'left', 'text_wrap': True,
            }),
            'int_top': wb.add_format({
                'font_name': 'Calibri', 'border': 1, 'num_format': '#,##0',
                'valign': 'top',
            }),
            'int_center': wb.add_format({
                'font_name': 'Calibri', 'border': 1, 'num_format': '#,##0',
                'valign': 'vcenter', 'align': 'center',
            }),
            'item_money_top': wb.add_format({
                'font_name': 'Calibri', 'border': 1,
                'num_format': '#,##0.00 "Kč"', 'valign': 'top',
            }),
            'item_money_center': wb.add_format({
                'font_name': 'Calibri', 'border': 1,
                'num_format': '#,##0.00 "Kč"', 'valign': 'vcenter',
                'align': 'center',
            }),
            'key_money': wb.add_format({
                'font_name': 'Calibri', 'border': 1,
                'num_format': '#,##0.00 "Kč"', 'valign': 'vcenter',
                'align': 'center', 'bold': True,
            }),
            'bold_inline': wb.add_format({'font_name': 'Calibri', 'bold': True}),
            'normal_inline': wb.add_format({'font_name': 'Calibri'}),
        }

    def _export_leviat(wb, ws, offer, items):
        f = _base_formats(wb)
        offer_no = _v(offer, 'offer_number')
        net = _num(_v(offer, 'net_value', 'total_value'))
        gross = _num(_v(offer, 'gross_value')) or sum(
            _num(_v(item, 'original_unit_price', 'unit_price'))
            * _num(_v(item, 'quantity'))
            for item in items
        )
        if not net:
            net = sum(_num(_v(item, 'total_price')) for item in items)
        disc_value = max(0, gross - net)
        disc_pct = _num(_v(offer, 'discount_pct'))
        if not disc_pct and gross:
            disc_pct = 100 * disc_value / gross
        vat = round(net * 0.21, 2)
        total = round(net + vat, 2)
        # Supplier document reference is deliberately independent from our CRM action.
        supplier_reference = str(_v(offer, 'reference') or '').strip() or '—'

        ws.write('A1', f'Cenová nabídka {offer_no}', f['title'])
        summary = [
            ('Číslo nabídky', offer_no, f['value']),
            ('Datum', M.fmt_date(_v(offer, 'offer_date')), f['value']),
            ('Reference zákazníka (Leviat)', supplier_reference, f['value']),
            ('Součet položek před slevou', gross, f['money']),
            ('Sleva %', disc_pct, f['pct']),
            ('Sleva Kč', disc_value, f['money']),
            ('Celkem bez DPH', net, f['money']),
            ('DPH', vat, f['money']),
            ('Celková částka s DPH', total, f['money']),
        ]
        for row, (name, value, fmt) in enumerate(summary, start=2):
            ws.write(row - 1, 0, name, f['label'])
            ws.write(row - 1, 1, value, fmt)

        start = 13
        ws.write(start - 1, 0, 'Pol.', f['head'])
        ws.write(start - 1, 1, 'Číslo výrobku', f['head'])
        ws.merge_range(start - 1, 2, start - 1, 7, 'Název položky', f['head'])
        ws.write(start - 1, 8, 'Množství [KS]', f['head'])
        ws.write(start - 1, 9, 'Cena za kus bez DPH', f['head'])
        ws.write(start - 1, 10, 'Cena položky bez DPH', f['head'])

        for row, item in enumerate(items, start=start):
            qty = _num(_v(item, 'quantity'))
            unit_price = _num(_v(item, 'unit_price'))
            total_price = _num(_v(item, 'total_price')) or qty * unit_price
            ws.write_number(row, 0, _num(_v(item, 'position')), f['int_top'])
            ws.write(row, 1, _v(item, 'product_code'), f['text_top'])
            ws.merge_range(
                row, 2, row, 7,
                _v(item, 'original_name', 'item_key'),
                f['text_top'],
            )
            ws.write_number(row, 8, qty, f['int_top'])
            ws.write_number(row, 9, unit_price, f['item_money_top'])
            ws.write_number(row, 10, total_price, f['item_money_top'])

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
        return min(220, max(54, 15 * lines + 12 * math.ceil(chars / 56)))

    def _rich_segments(item):
        raw = str(_v(item, 'details_rich_json') or '').strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
        result = []
        for segment in value if isinstance(value, list) else []:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get('text') or '')
            if not text:
                continue
            bold = bool(segment.get('bold'))
            if result and result[-1]['bold'] == bold:
                result[-1]['text'] += text
            else:
                result.append({'text': text, 'bold': bold})
        return result

    def _write_gerotop_description(ws, row, desc, details, segments, f):
        full = desc + (('\n' + details) if details else '')
        ws.merge_range(row, 1, row, 4, '', f['text_center'])
        if not desc:
            ws.write(row, 1, details, f['text_center'])
            return full
        args = [f['bold_inline'], desc]
        if details:
            args.extend([f['normal_inline'], '\n'])
            if segments:
                for segment in segments:
                    args.extend([
                        f['bold_inline'] if segment['bold'] else f['normal_inline'],
                        segment['text'],
                    ])
            else:
                args.extend([f['normal_inline'], details])
        try:
            # Cell format is the last argument; inline formats preserve PDF emphasis.
            ws.write_rich_string(row, 1, *args, f['text_center'])
        except Exception:
            ws.write(row, 1, full, f['text_center'])
        return full

    def _export_gerotop(wb, ws, offer, items):
        f = _base_formats(wb)
        offer_no = _v(offer, 'offer_number')
        internal_action = _v(offer, 'action_name') or 'Nepřiřazeno'

        product_net = 0.0
        for item in items:
            name = (
                str(_v(item, 'original_name')) + ' ' + str(_v(item, 'product_code'))
            ).casefold()
            if any(marker in name for marker in (
                'doprava', 'dopravné', 'balné', 'preprava', 'přeprava'
            )):
                continue
            product_net += _num(_v(item, 'total_price'))
        if not product_net:
            product_net = _num(_v(offer, 'net_value', 'total_value'))

        ws.write('A1', f'Cenová nabídka {offer_no}', f['title'])
        summary = [
            ('Dodavatel', _v(offer, 'supplier', default='GEROtop')),
            ('Číslo nabídky', offer_no),
            ('Datum', M.fmt_date(_v(offer, 'offer_date'))),
            ('Zakázka', internal_action),
            ('Celkem bez DPH – pouze výrobky', product_net),
        ]
        for row, (name, value) in enumerate(summary, start=2):
            ws.write(row - 1, 0, name, f['label'])
            if isinstance(value, (int, float)):
                ws.write_number(row - 1, 1, value, f['money'])
            else:
                ws.write(row - 1, 1, value, f['value'])

        start = 9
        ws.write(start - 1, 0, 'Kód', f['head'])
        ws.merge_range(start - 1, 1, start - 1, 4, 'Název / technický popis', f['head'])
        ws.merge_range(start - 1, 5, start - 1, 6, 'Obrázek', f['head'])
        ws.write(start - 1, 7, 'Počet [KS]', f['head'])
        ws.write(start - 1, 8, 'Cena/ks po slevě', f['head'])
        ws.write(start - 1, 9, 'Sleva', f['head'])
        ws.write(start - 1, 10, 'Původní cena/ks', f['head'])
        ws.write(start - 1, 11, 'Cena celkem', f['head'])

        for row, item in enumerate(items, start=start):
            code = _v(item, 'product_code')
            desc = str(_v(item, 'original_name', 'item_key') or '').strip()
            details = str(_v(item, 'details') or '').strip()
            segments = _rich_segments(item)
            qty = _num(_v(item, 'quantity'))
            unit_price = _num(_v(item, 'unit_price'))
            discount = _num(_v(item, 'discount_pct'))
            original = _num(_v(item, 'original_unit_price')) or unit_price
            total_price = _num(_v(item, 'total_price')) or qty * unit_price

            ws.write(row, 0, code, f['text_center'])
            full = _write_gerotop_description(
                ws, row, desc, details, segments, f
            )
            ws.merge_range(row, 5, row, 6, '', f['text_center'])
            ws.write_number(row, 7, qty, f['int_center'])
            ws.write_number(row, 8, unit_price, f['key_money'])
            ws.write_number(row, 9, discount, f['pct'])
            ws.write_number(row, 10, original, f['item_money_center'])
            ws.write_number(row, 11, total_price, f['item_money_center'])
            ws.set_row(row, _estimate_height(full))

            blob, ext = _item_image(offer, item)
            if blob:
                try:
                    bio = io.BytesIO(bytes(blob))
                    try:
                        ws.embed_image(row, 5, 'produkt.' + str(ext), {'image_data': bio})
                    except Exception:
                        ws.insert_image(
                            row, 5, 'produkt.' + str(ext),
                            {
                                'image_data': bio, 'object_position': 1,
                                'x_scale': 0.45, 'y_scale': 0.45,
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
                'Extrakce dat', f'Chybí XlsxWriter.\n\n{exc}', parent=parent or app
            )

        offer, items = _load(offer_id)
        if not offer:
            return
        path = _save_path(parent or app, offer)
        if not path:
            return

        wb = None
        try:
            wb = xlsxwriter.Workbook(path)
            ws = wb.add_worksheet('Nabídka')
            supplier = str(_v(offer, 'supplier')).casefold()
            if 'gerotop' in supplier:
                _export_gerotop(wb, ws, offer, items)
            else:
                _export_leviat(wb, ws, offer, items)
            wb.close()
            messagebox.showinfo(
                'Extrakce dat', f'Extrakce vytvořena:\n{path}', parent=parent or app
            )
        except Exception as exc:
            try:
                if wb:
                    wb.close()
            except Exception:
                pass
            messagebox.showerror('Extrakce dat', str(exc), parent=parent or app)

    M.export_offer_excel = export_legacy

    def selected(self):
        offer_id = self._selected_offer_id() if hasattr(self, '_selected_offer_id') else None
        if not offer_id:
            return M.messagebox.showinfo(
                'Extrakce dat', 'Vyberte nabídku.', parent=self
            )
        exporter = getattr(M, 'export_offer_excel', None)
        if callable(exporter):
            return exporter(self, offer_id, self)
        return export_legacy(self, offer_id, self)

    M.App.export_selected_offer_excel = selected

    # Rewire the historical detail button to the single canonical exporter.
    try:
        import crm_features as F
        dialog_cls = F.OfferDetailDialog
        old_build_detail = dialog_cls._build

        def build_detail(self):
            result = old_build_detail(self)
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
                                    command=lambda: getattr(
                                        M, 'export_offer_excel', export_legacy
                                    )(
                                        self.parent_app, self.oid, self
                                    ),
                                )
                        except Exception:
                            pass
                        walk(child)
                walk(self.f)
            except Exception:
                pass
            return result

        dialog_cls._build = build_detail
    except Exception:
        pass

    old_build_offers = M.App.build_offers

    def build_offers(self):
        result = old_build_offers(self)
        try:
            page = self.tabs['offers']
            def walk(widget):
                for child in widget.winfo_children():
                    try:
                        if (
                            child.winfo_class().endswith('Button')
                            and 'Export vybrané nabídky' in str(child.cget('text'))
                        ):
                            child.configure(text='Extrakce dat vybrané nabídky')
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
                            'GEROtop export zachovává technický popis včetně '
                            'tučných částí z původní nabídky, obrázky, množství '
                            'a ceny. Leviat export používá vlastní referenci '
                            'z dokumentu Leviat; interní název Akce v CRM je '
                            'veden samostatně a referenci dodavatele nepřepisuje.',
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