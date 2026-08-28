"""Ceník file/archive and DB-only lifecycle operations."""
from __future__ import annotations
import os
from pathlib import Path
from . import context as ctx
from .archive import price_list_archive_root

def _selected_price_list_id(app):
    tree = getattr(app, "price_list_evidence_tree", None)
    selection = tree.selection() if tree is not None else ()
    if not selection:
        return None
    text = str(selection[0])
    return int(text[2:]) if text.startswith("pl") else None


def open_price_list_file(app):
    price_list_id = _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    with ctx.M.db() as con:
        row = con.execute("SELECT archive_path FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
    path = Path(str(row["archive_path"] or "")) if row else None
    if not path or not path.is_file():
        return ctx.M.messagebox.showwarning("Ceníky", "Archivovaný soubor nebyl nalezen.", parent=app)
    try:
        os.startfile(str(path))
    except Exception as exc:
        ctx.M.messagebox.showerror("Ceníky", str(exc), parent=app)


def open_price_list_folder(app):
    price_list_id = _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    with ctx.M.db() as con:
        row = con.execute("SELECT archive_path FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
    path = Path(str(row["archive_path"] or "")) if row else None
    folder = path.parent if path else price_list_archive_root()
    try:
        os.startfile(str(folder))
    except Exception as exc:
        ctx.M.messagebox.showerror("Ceníky", str(exc), parent=app)


def archive_price_list(app, restore=False):
    price_list_id = _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    with ctx.M.db() as con:
        con.execute("UPDATE price_lists SET archived=? WHERE id=?", (0 if restore else 1, price_list_id))
    app.refresh_price_lists()


def delete_price_list_db(app):
    price_list_id = _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    if not ctx.M.messagebox.askyesno(
        "Smazat Ceník z databáze",
        "Opravdu odstranit Ceník a jeho vytěžené položky z databáze CRM?\n\nArchivovaný původní soubor na disku zůstane zachovaný.",
        parent=app,
    ):
        return
    with ctx.M.db() as con:
        con.execute("DELETE FROM price_lists WHERE id=?", (price_list_id,))
    app.refresh_price_lists(); app.refresh_offers()


def _open_archived_path(app, price_list_id: int, folder: bool = False):
    with ctx.M.db() as con:
        row = con.execute("SELECT archive_path FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
    path = Path(str(row["archive_path"] or "")) if row else None
    target = path.parent if folder and path else path
    if not target or not target.exists():
        return ctx.M.messagebox.showwarning("Ceníky", "Archivovaný soubor nebo složka nebyly nalezeny.", parent=app)
    try:
        os.startfile(str(target))
    except Exception as exc:
        ctx.M.messagebox.showerror("Ceníky", str(exc), parent=app)
