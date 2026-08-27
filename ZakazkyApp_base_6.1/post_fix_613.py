# TURTO CRM 6.1.15 - real CRM Excel export + DB-only offer deletion.
from pathlib import Path


def apply(M):
    # Restore the supplier-specific CRM exporter from v624. This is the proven
    # Leviat/GEROtop exporter used by the manual "Extrakce dat" action in CRM.
    try:
        import v624_legacy_exports
        v624_legacy_exports.apply(M)
    except Exception:
        pass

    manual_export = getattr(M, 'export_offer_excel', None)
    if callable(manual_export):
        def export_exactly_like_manual(app, offer_id, target_path):
            from tkinter import filedialog, messagebox
            target_path = Path(target_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            old_save = filedialog.asksaveasfilename
            old_info = messagebox.showinfo
            old_error = messagebox.showerror
            errors = []
            try:
                filedialog.asksaveasfilename = lambda *a, **k: str(target_path)
                messagebox.showinfo = lambda *a, **k: None
                messagebox.showerror = lambda title, msg, *a, **k: errors.append(str(msg))
                manual_export(app, offer_id, app)
            finally:
                filedialog.asksaveasfilename = old_save
                messagebox.showinfo = old_info
                messagebox.showerror = old_error
            if errors:
                raise RuntimeError(errors[-1])
            if not target_path.exists():
                raise RuntimeError('CRM export nevytvořil očekávaný soubor: ' + str(target_path))
            return target_path

        M.export_offer_excel = manual_export

        def selected(self):
            oid = self._selected_offer_id() if hasattr(self, '_selected_offer_id') else None
            if not oid:
                return M.messagebox.showinfo('Extrakce dat', 'Vyberte nabídku.', parent=self)
            return manual_export(self, oid, self)
        M.App.export_selected_offer_excel = selected

        old_pdf = getattr(M, 'process_offer_pdf', None)
        if callable(old_pdf):
            def process_pdf(app, path, *a, **k):
                result = old_pdf(app, path, *a, **k)
                try:
                    if isinstance(result, dict) and result.get('offer_id') and result.get('archive_folder'):
                        out = Path(result['archive_folder']) / 'Extrakce_nabidky.xlsx'
                        export_exactly_like_manual(app, result['offer_id'], out)
                        result['excel_files'] = [str(out)]
                except Exception as e:
                    if isinstance(result, dict):
                        result.setdefault('errors', []).append('Přesný CRM Excel export: ' + str(e))
                return result
            M.process_offer_pdf = process_pdf

        old_msg = getattr(M, 'process_offer_msg', None)
        if callable(old_msg):
            def process_msg(app, path, *a, **k):
                result = old_msg(app, path, *a, **k)
                try:
                    if not isinstance(result, dict) or not result.get('archive_folder'):
                        return result
                    offers = [x for x in (result.get('offers') or []) if isinstance(x, dict) and x.get('offer_id')]
                    if not offers:
                        return result
                    folder = Path(result['archive_folder'])
                    outs = []
                    for i, offer in enumerate(offers, 1):
                        out = folder / ('Extrakce_nabidky.xlsx' if len(offers) == 1 else f'Extrakce_nabidky_{i}.xlsx')
                        export_exactly_like_manual(app, offer['offer_id'], out)
                        outs.append(str(out))
                    result['excel_files'] = outs
                except Exception as e:
                    if isinstance(result, dict):
                        result.setdefault('errors', []).append('Přesný CRM Excel export: ' + str(e))
                return result
            M.process_offer_msg = process_msg

        M.export_offer_exactly_like_manual = export_exactly_like_manual

    # DB-only deletion. Physical archive files are intentionally completely
    # independent from CRM and are never deleted or modified here.
    def delete_offer(self):
        oid = self._selected_offer_id() if hasattr(self, '_selected_offer_id') else None
        if not oid:
            return
        if not M.messagebox.askyesno(
            'Nabídky',
            'Opravdu odstranit tento import nabídky z CRM?\n\nUložené PDF, MSG, přílohy a Excelové soubory na disku zůstanou beze změny.',
            parent=self
        ):
            return
        try:
            with M.db() as con:
                # v6.0.17 introduced offer_source_attachments.offer_id without
                # ON DELETE SET NULL. Detach the source record first; the source
                # message/attachment history remains available for reprocessing.
                try:
                    con.execute('UPDATE offer_source_attachments SET offer_id=NULL WHERE offer_id=?', (oid,))
                except Exception:
                    pass
                con.execute('DELETE FROM supplier_offers WHERE id=?', (oid,))
            self.refresh_offers()
        except Exception as e:
            M.messagebox.showerror('Nabídky', 'Import se nepodařilo odstranit z databáze.\n\n' + str(e), parent=self)

    M.App.delete_offer = delete_offer
