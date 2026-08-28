"""User-facing Ceník import with progress, Storno and safe fallback archive."""
from __future__ import annotations
from pathlib import Path
from . import context as ctx
from .archive import price_list_archive_root
from .common import PRICE_LIST_EXTS,PriceListImportCancelled
from .metadata import _metadata_dialog
from .parser import parse_price_list_file
from .storage import _save_price_list

def import_price_list(app):
    path_value = ctx.M.filedialog.askopenfilename(
        parent=app, title="Importovat Ceník",
        filetypes=[("Ceníky", "*.pdf *.xlsx *.xlsm *.csv"), ("PDF", "*.pdf"),
                   ("Excel", "*.xlsx *.xlsm"), ("CSV", "*.csv"), ("Všechny soubory", "*.*")],
    )
    if not path_value:
        return
    path = Path(path_value)
    if path.suffix.lower() not in PRICE_LIST_EXTS:
        return ctx.M.messagebox.showwarning("Ceníky", "Tento formát zatím není podporovaný.", parent=app)

    state={"cancel":False}
    progress = ctx.M.tk.Toplevel(app)
    progress.title("Načítání Ceníku")
    progress.transient(app)
    progress.geometry("580x205")
    progress.resizable(False,False)
    frame = ctx.M.ttk.Frame(progress, padding=18); frame.pack(fill="both", expand=True)
    label = ctx.M.ttk.Label(frame, text="Analyzuji soubor…", style="Section.TLabel"); label.pack(anchor="w")
    detail = ctx.M.ttk.Label(frame, text=path.name, style="PageSubtitle.TLabel"); detail.pack(anchor="w", pady=(6, 10))
    bar = ctx.M.ttk.Progressbar(frame, mode="indeterminate", length=520); bar.pack(fill="x"); bar.start(10)
    buttons=ctx.M.ttk.Frame(frame);buttons.pack(fill="x",pady=(12,0))

    def cancel():
        state["cancel"]=True
        detail.configure(text="Storno – dokončuji právě probíhající krok…")
    ctx.M.ttk.Button(buttons,text="Storno",command=cancel).pack(side="right")
    progress.protocol("WM_DELETE_WINDOW",cancel)
    try:
        progress.lift();progress.focus_force()
        app.update_idletasks()
    except Exception:
        pass

    def update(index, total, text):
        if state["cancel"]:
            raise PriceListImportCancelled("Import Ceníku byl zrušen.")
        detail.configure(text=text)
        try:
            if total and total>0:
                bar.stop();bar.configure(mode="determinate",maximum=max(1,total),value=min(index,total))
            app.update()
        except Exception:
            pass

    parsed=None
    parse_error=None
    try:
        parsed = parse_price_list_file(path, update)
        if state["cancel"]:
            raise PriceListImportCancelled("Import Ceníku byl zrušen.")
    except PriceListImportCancelled:
        try:progress.destroy()
        except Exception:pass
        return
    except Exception as exc:
        parse_error=exc
    try:progress.destroy()
    except Exception:pass

    if parse_error is not None:
        keep=ctx.M.messagebox.askyesno(
            "Import Ceníku",
            "Automatické načtení položek se nepodařilo.\n\n"
            f"{parse_error}\n\n"
            "Chcete původní soubor přesto trvale archivovat a evidovat bez rozpoznaných položek?",
            parent=app,
        )
        if not keep:
            return
        parsed={
            "supplier":"", "title":path.stem, "valid_from":"", "valid_to":"",
            "product_group":"", "branch":"", "currency":"CZK", "items":[],
            "terms_text":"", "raw_text":"", "ocr_text":"", "ocr_layout_json":"", "ocr_engine":"",
            "parse_status":"Bez rozpoznaných položek – " + str(parse_error)[:500],
            "source_type":path.suffix.lstrip(".").upper(), "suggested_update_mode":"partial",
        }

    metadata = _metadata_dialog(app, parsed, path)
    if not metadata:
        return
    try:
        price_list_id, created = _save_price_list(path, parsed, metadata)
    except Exception as exc:
        return ctx.M.messagebox.showerror("Import Ceníku", str(exc), parent=app)
    try:
        app.refresh_price_lists()
        app.refresh_offers()
    except Exception:
        pass
    if created:
        ctx.M.messagebox.showinfo(
            "Ceníky",
            f"Ceník byl archivován a uložen.\n\nPoložek: {len(parsed.get('items') or [])}\nArchiv:\n{price_list_archive_root()}",
            parent=app,
        )
    else:
        ctx.M.messagebox.showinfo("Ceníky", "Tento zdrojový soubor už je v evidenci uložený.", parent=app)
