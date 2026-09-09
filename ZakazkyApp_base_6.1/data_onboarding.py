"""First-run data wizard for TURTO CRM 8.0+.

It runs before the main application imports its database globals.  Existing data
are never deleted; importing an existing database uses SQLite's backup API.
"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import data_location


def _database_ready() -> bool:
    path = data_location.database_path()
    return bool(path.is_file() and data_location.validate_database(path)["ok"])


def _choose_existing(parent: tk.Misc) -> bool:
    source = filedialog.askopenfilename(
        parent=parent,
        title="Vyberte databázi TURTO CRM",
        filetypes=[("Databáze SQLite", "*.db *.sqlite *.sqlite3"), ("Všechny soubory", "*.*")],
    )
    if not source:
        return False
    validation = data_location.validate_database(source)
    if not validation["ok"]:
        messagebox.showerror("Databáze", validation["message"], parent=parent)
        return False

    answer = messagebox.askyesnocancel(
        "Připojit databázi",
        "Databáze je v pořádku.\n\n"
        "ANO = doporučeně ji bezpečně zkopírovat do standardní složky TURTO.\n"
        "NE = používat vybraný soubor přímo v jeho současném umístění.\n\n"
        "Přímé používání databáze ze síťové nebo cloudově synchronizované složky "
        "není vhodné pro současný provoz více počítačů.",
        parent=parent,
    )
    if answer is None:
        return False
    try:
        if answer:
            target = data_location.copy_database_to_standard(source)
            detail = f"Databáze byla přenesena do:\n{target}"
        else:
            data_location.attach_database(source)
            detail = f"CRM bude používat databázi:\n{Path(source).resolve()}"
        messagebox.showinfo("Databáze připojena", detail, parent=parent)
        return True
    except FileExistsError:
        messagebox.showerror(
            "Databáze",
            "Ve standardní složce už databáze existuje. Nebyla přepsána.",
            parent=parent,
        )
    except Exception as exc:
        messagebox.showerror("Databáze", f"Databázi se nepodařilo připojit:\n\n{exc}", parent=parent)
    return False


def configure_data_location(*, force: bool = False) -> bool:
    if not force and _database_ready():
        return True

    root = tk.Tk()
    root.title("TURTO CRM – první spuštění")
    root.geometry("700x430")
    root.minsize(640, 400)
    root.option_add("*Font", "Calibri 10")
    result = {"ok": False}

    shell = ttk.Frame(root, padding=24)
    shell.pack(fill="both", expand=True)
    ttk.Label(shell, text="TURTO CRM", font=("Calibri", 20, "bold")).pack(anchor="w")
    ttk.Label(
        shell,
        text="Nastavení dat pro tento počítač",
        font=("Calibri", 12, "bold"),
    ).pack(anchor="w", pady=(4, 18))
    ttk.Label(
        shell,
        text=(
            "Program je nainstalovaný odděleně od firemních dat. Na tomto počítači "
            "můžete začít s novou databází, nebo připojit existující databázi TURTO CRM."
        ),
        wraplength=620,
        justify="left",
    ).pack(anchor="w", pady=(0, 22))

    card = ttk.Frame(shell, padding=18)
    card.pack(fill="x")
    ttk.Label(card, text="Standardní umístění dat", font=("Calibri", 10, "bold")).pack(anchor="w")
    ttk.Label(card, text=str(data_location.default_data_root()), wraplength=600).pack(anchor="w", pady=(3, 12))

    def use_new() -> None:
        try:
            data_location.use_default_location()
            result["ok"] = True
            root.destroy()
        except Exception as exc:
            messagebox.showerror("Data", f"Umístění dat se nepodařilo připravit:\n\n{exc}", parent=root)

    def attach() -> None:
        if _choose_existing(root):
            result["ok"] = True
            root.destroy()

    buttons = ttk.Frame(shell)
    buttons.pack(fill="x", pady=(24, 0))
    ttk.Button(buttons, text="Začít s novými daty", command=use_new).pack(side="left")
    ttk.Button(buttons, text="Připojit existující databázi…", command=attach).pack(side="left", padx=10)
    ttk.Button(buttons, text="Zrušit", command=root.destroy).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return bool(result["ok"])


def ensure_data_location() -> bool:
    """Return True when main CRM startup may continue."""
    return configure_data_location(force=False)


__all__ = ["configure_data_location", "ensure_data_location"]
