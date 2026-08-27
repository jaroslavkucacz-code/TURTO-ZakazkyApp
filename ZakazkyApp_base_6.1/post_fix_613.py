# TURTO CRM 6.1.13 - automatic extraction must use the exact same export code as manual CRM export.
from pathlib import Path


def apply(M):
    manual_export = getattr(M, 'export_offer_excel', None)
    if not callable(manual_export):
        return

    def export_exactly_like_manual(app, offer_id, target_path):
        """Run the existing manual CRM export function unchanged, only inject its save path.
        This guarantees identical workbook structure/formatting to a manual export of the same offer_id.
        """
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

    # Re-export PDF imports after the 6.1.12 archive workflow, overwriting the
    # automatically generated workbook with the output of the exact manual path.
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

    # Same for MSG. The database import and file archiving finish first; only then
    # are the recognized offer IDs exported through the real manual CRM function.
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
