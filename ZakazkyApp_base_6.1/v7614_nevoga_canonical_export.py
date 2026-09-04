"""TURTO CRM 7.6.14 - route automatic Nevoga archive Excel through the final exporter.

The archive layer is installed before the supplier-specific Nevoga layer. Older
releases therefore captured v624's generic exporter in a local closure and kept
using it for automatic PDF/MSG archive extraction even after the final Nevoga
exporter was installed. v624 treats every non-GEROtop supplier as Leviat, which
produced the observed six-column C:H description with no PLEXUS image and no
rich red fragments.

This compatibility layer runs after v769. It leaves import/database logic alone
and replaces only automatically generated Nevoga Excel files with the current
runtime M.export_offer_excel result. Manual and automatic export therefore use
one final supplier-aware implementation.
"""
from __future__ import annotations

from pathlib import Path


def _is_nevoga_name(value):
    folded = str(value or "").strip().casefold()
    return any(token in folded for token in ("nevoga", "nevegar", "reinforcement systems"))


def apply(M):
    if getattr(M, "_turto_v7614_nevoga_canonical_export", False):
        return
    M._turto_v7614_nevoga_canonical_export = True

    def supplier_for_offer(offer_id):
        try:
            with M.db() as con:
                row = con.execute(
                    """SELECT coalesce(nullif(trim(s.official_name),''),
                                      nullif(trim(s.short_name),''),
                                      nullif(trim(o.supplier_name),''),'') supplier
                       FROM supplier_offers o
                       LEFT JOIN companies s ON s.id=o.supplier_company_id
                       WHERE o.id=?""",
                    (int(offer_id),),
                ).fetchone()
            return str(row["supplier"] or "") if row else ""
        except Exception:
            return ""

    def exact_export_to_path(app, offer_id, target):
        """Run the *current* final exporter without presenting a save dialog."""
        exporter = getattr(M, "export_offer_excel", None)
        if not callable(exporter):
            raise RuntimeError("Finální Excel export nabídky není dostupný.")

        from tkinter import filedialog, messagebox

        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(target.stem + ".__nevoga_final__" + target.suffix)
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
            messagebox.showerror = lambda _title, text, *args, **kwargs: errors.append(str(text))
            exporter(app, int(offer_id), parent=app)
        finally:
            filedialog.asksaveasfilename = old_save
            messagebox.showinfo = old_info
            messagebox.showerror = old_error

        if errors:
            try:
                temp_target.unlink(missing_ok=True)
            except Exception:
                pass
            raise RuntimeError(errors[0])
        if not temp_target.exists() or temp_target.stat().st_size <= 0:
            raise RuntimeError("Finální Nevoga Excel nebyl vytvořen.")

        temp_target.replace(target)
        return str(target)

    M.export_nevoga_offer_to_path = exact_export_to_path

    def refresh_automatic_excel(app, result):
        if not isinstance(result, dict):
            return result

        offers = []
        for item in result.get("offers") or []:
            if isinstance(item, dict) and item.get("offer_id"):
                offers.append(int(item["offer_id"]))
        if not offers and result.get("offer_id"):
            offers = [int(result["offer_id"])]
        if not offers:
            return result

        outputs = list(result.get("excel_files") or [])
        archive_folder = str(result.get("archive_folder") or "").strip()

        for index, offer_id in enumerate(offers):
            if not _is_nevoga_name(supplier_for_offer(offer_id)):
                continue

            target = outputs[index] if index < len(outputs) else ""
            if not target and archive_folder:
                filename_fn = getattr(M, "offer_export_filename", None)
                filename = (
                    filename_fn(offer_id)
                    if callable(filename_fn)
                    else f"Extrakce dat CN Nevoga_{offer_id}.xlsx"
                )
                target = str(Path(archive_folder) / filename)

            if not target:
                result.setdefault("errors", []).append(
                    f"Nevoga nabídka {offer_id}: chybí cílová cesta Excel extrakce."
                )
                continue

            try:
                final_path = exact_export_to_path(app, offer_id, target)
                if index < len(outputs):
                    outputs[index] = final_path
                else:
                    while len(outputs) < index:
                        outputs.append("")
                    outputs.append(final_path)
            except Exception as exc:
                result.setdefault("errors", []).append(
                    f"Nevoga Excel {offer_id}: {exc}"
                )

        result["excel_files"] = outputs
        return result

    previous_process_msg = getattr(M, "process_offer_msg", None)
    if callable(previous_process_msg):
        def process_offer_msg(app, *args, **kwargs):
            result = previous_process_msg(app, *args, **kwargs)
            return refresh_automatic_excel(app, result)

        M.process_offer_msg = process_offer_msg

    previous_process_pdf = getattr(M, "process_offer_pdf", None)
    if callable(previous_process_pdf):
        def process_offer_pdf(app, *args, **kwargs):
            result = previous_process_pdf(app, *args, **kwargs)
            return refresh_automatic_excel(app, result)

        M.process_offer_pdf = process_offer_pdf

    M.V7614_NEVOGA_CANONICAL_EXPORT = {
        "automatic_msg_uses_final_exporter": True,
        "automatic_pdf_uses_final_exporter": True,
        "description_columns": "C:F",
        "image_columns": "G:H",
        "exact_supplier_red": True,
        "database_changes": False,
    }
