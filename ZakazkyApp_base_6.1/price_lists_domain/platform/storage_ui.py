"""Preview-first storage maintenance. Workers never call Tk from a background thread."""
from pathlib import Path
import queue
import threading

import storage_maintenance as storage


def size_text(value):
    return f"{value / (1024 ** 3):.2f} GiB" if value >= 1024 ** 3 else f"{value / (1024 ** 2):.1f} MiB"


def open_storage(M, app):
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    if getattr(M, "TEST_MODE", False):
        messagebox.showwarning("Úložiště", "Úklid ani změna pravidel nejsou v režimu TEST dostupné.", parent=app)
        return None
    previous = getattr(app, "_storage_window", None)
    if previous is not None and previous.winfo_exists():
        previous.lift()
        return previous
    root, database = Path(M.DATA_ROOT), Path(M.DB)
    win = tk.Toplevel(app)
    app._storage_window = win
    win.title("Zálohy a úklid úložiště")
    win.geometry("1160x700")
    win.minsize(800, 500)
    frame = ttk.Frame(win, padding=14); frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=storage.RULES, wraplength=1040).pack(anchor="w")
    ttk.Label(frame, text="Ruční/importní zálohy, živá databáze, přílohy a nerozpoznané soubory se nemažou.\n"
              "U aktualizací zůstávají dva nejnovější balíčky v každé složce a soubory potřebné pro návrat verze.",
              wraplength=1040).pack(anchor="w", pady=(5, 10))
    legacy = tk.BooleanVar(value=False)
    legacy_check = ttk.Checkbutton(frame, text="Zahrnout staré zálohy s doprovodnými soubory (pouze tento ruční úklid)",
                                   variable=legacy, command=lambda: refresh())
    legacy_check.pack(anchor="w")
    status = tk.StringVar(value="Načítám náhled…")
    ttk.Label(frame, textvariable=status, wraplength=1040).pack(anchor="w", pady=6)
    table_frame = ttk.Frame(frame); table_frame.pack(fill="both", expand=True)
    columns = ("file", "size", "decision")
    tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended", name="layout__storage_ui__open_storage__tree")
    for col, text, width in (("file", "Soubor", 550), ("size", "Velikost", 95), ("decision", "Rozhodnutí / ochrana", 350)):
        tree.heading(col, text=text); tree.column(col, width=width, minwidth=75, stretch=True)
    tree.tag_configure("keep", foreground="#64748b")
    scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
    ttk.Label(frame, text="Vyberte řádky k úklidu (Ctrl / Shift). Chráněné řádky nelze odstranit.").pack(anchor="w", pady=6)
    controls = ttk.Frame(frame); controls.pack(fill="x")
    messages = queue.Queue()
    state = {"busy": False, "entries": {}, "legacy": False}
    buttons = [legacy_check]

    def context_valid():
        if getattr(M, "TEST_MODE", False) or Path(M.DB).resolve() != database.resolve():
            raise ValueError("Změnila se aktivní databáze. Zavřete dialog a otevřete jej znovu.")

    def selected():
        return [state["entries"][i] for i in tree.selection() if state["entries"][i]["eligible"]]

    def selection_changed(_event=None):
        if state["busy"]:
            return
        entries = list(state["entries"].values())
        chosen = selected()
        eligible = [e for e in entries if e["eligible"]]
        status.set(f"K úklidu: {len(eligible)} položek / {size_text(sum(e['size'] for e in eligible))}. "
                   f"Vybráno: {len(chosen)} / {size_text(sum(e['size'] for e in chosen))}. "
                   f"Ponechat: {len(entries) - len(eligible)} položek / "
                   f"{size_text(sum(e['size'] for e in entries if not e['eligible']))}.")
    tree.bind("<<TreeviewSelect>>", selection_changed)

    def start(kind, callback):
        if state["busy"]:
            return
        state["busy"] = True
        for b in buttons:
            b.configure(state="disabled")
        status.set("Pracuji… U velkých souborů může kontrola chvíli trvat.")
        def worker():
            try:
                context_valid()
                result = callback()
                messages.put((kind, result, None))
            except Exception as exc:
                messages.put((kind, None, str(exc)))
        threading.Thread(target=worker, name="TURTO-Storage", daemon=False).start()
        win.after(100, poll)

    def refresh():
        include_legacy = legacy.get()
        state["legacy"] = include_legacy
        start("scan", lambda: storage.build_plan(root, database, include_legacy=include_legacy))

    def poll():
        try:
            kind, result, error = messages.get_nowait()
        except queue.Empty:
            win.after(100, poll)
            return
        if kind == "progress":
            status.set(result)
            win.after(100, poll)
            return
        state["busy"] = False
        for b in buttons:
            b.configure(state="normal")
        if error:
            status.set("Operace nebyla dokončena. Soubory nejsou automaticky zkoušeny znovu.")
            messagebox.showerror("Úložiště", error, parent=win)
        elif kind == "scan":
            tree.delete(*tree.get_children())
            state["entries"] = {}
            for index, e in enumerate(sorted(result, key=lambda e: (not e["eligible"], e["relative"]))):
                key = str(index); state["entries"][key] = e
                label = e["relative"]
                if e.get("members"):
                    label += f" (+{len(e['members']) - 1} doprovodné soubory)"
                tree.insert("", "end", iid=key, values=(label, size_text(e["size"]),
                            ("K úklidu: " if e["eligible"] else "Ponechat: ") + e["reason"]),
                            tags=() if e["eligible"] else ("keep",))
            selection_changed()
        elif kind == "cleanup":
            text = f"Zpracováno {len(result['completed'])} souborů / {size_text(result['bytes'])}.\n"
            text += f"Bezpečnostní záloha: {result['backup']}\nProtokol: {result['log']}"
            if result["archive"]:
                text += f"\nArchiv: {result['archive']}\nNa stejném disku přesun volné místo nezvětší."
            else:
                text += "\nSmazané soubory nejsou v koši; zachované zálohy zůstávají v původní složce."
            if result["error"]:
                messagebox.showwarning("Úklid zastaven", text + "\n\n" + result["error"], parent=win)
            else:
                messagebox.showinfo("Úklid dokončen", text, parent=win)
            refresh()
        elif kind == "policy":
            status.set("Pravidla uložena. Denní záloha proběhne při běhu CRM; staré soubory před zapnutím zůstávají pro ruční úklid.")

    def cleanup(archive_mode):
        chosen = selected()
        if not chosen:
            messagebox.showinfo("Úložiště", "Vyberte soubory označené K úklidu.", parent=win)
            return
        archive = None
        if archive_mode:
            value = filedialog.askdirectory(parent=win, title="Archiv mimo složku CRM – ideálně jiný disk")
            if not value:
                return
            archive = Path(value)
        action = "Přesunout po ověření kopií do archivu" if archive else "TRVALE SMAZAT (bez koše)"
        groups = sum(bool(e.get("members")) for e in chosen)
        count = sum(len(e.get("members", [e])) for e in chosen)
        group_note = (f"\nObsahuje {groups} starých záloh včetně všech doprovodných souborů.\n"
                      "Před jejich úklidem se ověří, že nejsou používány.\n") if groups else ""
        if not messagebox.askyesno("Potvrdit úklid", f"{action}:\n{len(chosen)} vybraných položek / "
                                  f"{size_text(sum(e['size'] for e in chosen))}?\n\n"
                                  f"Celkem {count} souborů.{group_note}\n"
                                  "Nejprve se vytvoří a ověří bezpečnostní záloha živé databáze.\n"
                                  "Je pro ni potřeba další volné místo přibližně o velikosti databáze.",
                                  parent=win, default="no"):
            return
        include_legacy = state["legacy"]
        start("cleanup", lambda: storage.execute(root, database, chosen, archive=archive, include_legacy=include_legacy,
              progress=lambda text: messages.put(("progress", text, None))))

    def button(text, command):
        b = ttk.Button(controls, text=text, command=command); b.pack(side="left", padx=(0, 8)); buttons.append(b)
        return b
    refresh_button = button("Obnovit náhled", refresh)
    select_button = button("Vybrat vše k úklidu", lambda: tree.selection_set([i for i, e in state["entries"].items() if e["eligible"]]))
    archive_button = button("Přesunout do archivu…", lambda: cleanup(True))
    delete_button = button("Smazat vybrané…", lambda: cleanup(False))
    auto = tk.BooleanVar(value=False)
    try:
        saved = storage.policy(root)
        auto.set(saved.get("enabled") is True and saved.get("database") == str(database.resolve()))
    except Exception as exc:
        messagebox.showwarning("Pravidla úložiště", str(exc), parent=win)
    check = ttk.Checkbutton(frame, text="Denní záloha a automatické promazávání nových automatických souborů při běhu CRM", variable=auto)
    check.pack(anchor="w", pady=(15, 4)); buttons.append(check)
    ttk.Label(frame, text="Výchozí stav: vypnuto. Po zapnutí se trvale mažou jen soubory vzniklé až po zapnutí a nad rámec pravidel.\n"
              "Starší soubory vyžadují ruční úklid výše. Ruční zálohy se nepromazávají. Archiv mimo tento disk si ponechte zvlášť.",
              wraplength=1040).pack(anchor="w")

    def save():
        enabled = auto.get()
        if enabled and not messagebox.askyesno("Automatická údržba", "Zapnout denní zálohu a trvalé promazávání "
                "nových automatických záloh a balíčků podle uvedených pravidel?\n\n"
                "Dosavadní soubory se tímto souhlasem nemažou.", parent=win, default="no"):
            return
        start("policy", lambda: storage.save_policy(root, database, enabled))
    save_button = ttk.Button(frame, text="Uložit pravidla", command=save); save_button.pack(anchor="w", pady=6); buttons.append(save_button)

    def close():
        if state["busy"]:
            messagebox.showinfo("Úložiště", "Počkejte na dokončení právě probíhající operace.", parent=win)
        else:
            win.destroy()
    win.protocol("WM_DELETE_WINDOW", close)
    # Test hooks contain widgets/state only; no alternate data or cleanup paths.
    win._storage = dict(tree=tree, state=state, refresh=refresh_button, select=select_button,
                        archive=archive_button, delete=delete_button, auto=auto, save=save_button, status=status,
                        legacy=legacy, legacy_check=legacy_check)
    refresh()
    return win


def install(M):
    App = M.App
    if getattr(App, "_storage_830", False):
        return
    original_init = App.__init__

    def init(self, *args, **kwargs):
        result = original_init(self, *args, **kwargs)
        self._storage_daily_busy = False
        def tick():
            if not self._storage_daily_busy and not getattr(M, "TEST_MODE", False):
                # Capture the live path before any possible switch to TEST.
                root, database = Path(M.DATA_ROOT), Path(M.DB)
                def worker():
                    try:
                        if storage.policy(root).get("enabled") is True:
                            storage.run_daily(root, database)
                    except Exception as exc:
                        try:
                            from datetime import datetime
                            from updater_safety import write_json
                            write_json(root / "logs" / "storage_daily_error.json", {"at": datetime.now().isoformat(), "error": str(exc)})
                        except Exception:
                            pass
                    finally:
                        self._storage_daily_busy = False
                self._storage_daily_busy = True
                threading.Thread(target=worker, name="TURTO-DailyBackup", daemon=False).start()
            self.after(60 * 60 * 1000, tick)
        self.after(15000, tick)
        return result
    App.__init__ = init
    App._storage_830 = True
