from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ZakazkyApp_base_6.1"


def replace(path, old, new, count=1):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:140]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


catalog = SRC / "price_lists_domain/platform/product_catalog.py"
replace(
    catalog,
    '''def _selected_product_ids(tree) -> list[int]:
    result = []
    for iid in tree.selection():
        text = str(iid)
        if text.startswith("cp"):
            try:
                result.append(int(text[2:]))
            except Exception:
                pass
    return result


def _edit_product''',
    '''def _selected_product_ids(tree) -> list[int]:
    result = []
    for iid in tree.selection():
        text = str(iid)
        if text.startswith("cp"):
            try:
                result.append(int(text[2:]))
            except Exception:
                pass
    return result


def _root_app(widget):
    current = widget
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        master = getattr(current, "master", None)
        if master is None:
            break
        current = master
    return current or widget


def _edit_product''',
)
replace(
    catalog,
    '''def open_product_catalog(M, app, category_id=None, subgroup_id=None) -> None:
    # Link a bounded initial batch so the window opens quickly even on a large legacy database.
    initial_sync = sync_all_unlinked(M, max_documents=100)
    win = M.tk.Toplevel(app)
''',
    '''def open_product_catalog(M, app, category_id=None, subgroup_id=None) -> None:
    app = _root_app(app)
    # A catalogue can be opened from modal Ceník/Nabídka dialogs. Release the
    # previous grab so the new window is always usable; no data are committed by
    # merely opening the catalogue.
    try:
        grabbed = app.grab_current()
        if grabbed is not None:
            grabbed.grab_release()
    except Exception:
        pass
    # Only a small deterministic legacy batch is linked synchronously. A complete
    # migration has its own progress dialog and Storno button.
    initial_sync = sync_all_unlinked(M, max_documents=25)
    win = M.tk.Toplevel(app)
''',
)
replace(
    catalog,
    '''        bar = M.ttk.Progressbar(frame, mode="determinate", length=520)
        bar.pack(fill="x")

        def progress(done, total, text):
            bar.configure(maximum=max(1, total), value=done)
            label.set(f"{done}/{total} · {text}")
            progress_win.update_idletasks()

        try:
            result = sync_all_unlinked(M, max_documents=None, progress=progress)
        except Exception as exc:
            progress_win.destroy()
            return M.messagebox.showerror("Katalog produktů", f"Synchronizaci se nepodařilo dokončit:\n{exc}", parent=win)
        progress_win.destroy()
''',
    '''        bar = M.ttk.Progressbar(frame, mode="determinate", length=520)
        bar.pack(fill="x")
        cancelled = {"value": False}
        M.ttk.Button(
            frame, text="Storno", command=lambda: cancelled.__setitem__("value", True)
        ).pack(anchor="e", pady=(10, 0))

        def progress(done, total, text):
            bar.configure(maximum=max(1, total), value=done)
            label.set(f"{done}/{total} · {text}")
            progress_win.update()
            if cancelled["value"]:
                raise RuntimeError("__TURTO_CATALOG_CANCELLED__")

        try:
            result = sync_all_unlinked(M, max_documents=None, progress=progress)
        except Exception as exc:
            progress_win.destroy()
            if str(exc) == "__TURTO_CATALOG_CANCELLED__":
                refresh_filters()
                refresh()
                return M.messagebox.showinfo(
                    "Katalog produktů", "Synchronizace byla stornována. Již propojené položky zůstaly bezpečně uložené.", parent=win
                )
            return M.messagebox.showerror("Katalog produktů", f"Synchronizaci se nepodařilo dokončit:\n{exc}", parent=win)
        progress_win.destroy()
''',
)

categories = SRC / "price_lists_domain/platform/categories.py"
replace(categories, "product_catalog.sync_all_unlinked(M, max_documents=100)", "product_catalog.sync_all_unlinked(M, max_documents=25)")

real_ui = ROOT / "scripts/validate-real-ui.py"
replace(
    real_ui,
    '''        assert root._current_page == "dash"
        assert not callback_errors, "\\n".join(callback_errors)

        # Reproduce the attached-log failure path:''',
    '''        assert root._current_page == "dash"
        assert not callback_errors, "\\n".join(callback_errors)

        # Open the real product catalogue against the isolated additive schema.
        # This catches modal-grab, SQL-column and Treeview integration regressions.
        root.open_product_catalog()
        root.update()
        catalogue_windows = [
            child for child in root.winfo_children()
            if isinstance(child, app.tk.Toplevel) and child.winfo_exists() and child.title() == "Katalog produktů"
        ]
        assert len(catalogue_windows) == 1, catalogue_windows
        catalogue = catalogue_windows[0]

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        catalogue_trees = [widget for widget in walk(catalogue) if isinstance(widget, app.ttk.Treeview)]
        assert catalogue_trees, "Katalog produktů neobsahuje tabulku"
        columns = set(catalogue_trees[0]["columns"])
        for required in ("Výrobce", "Interní kód", "Interní označení", "Produktová skupina", "Podskupina", "Marže", "Sleva"):
            assert required in columns, required
        catalogue.destroy()
        root.update()
        assert not callback_errors, "\\n".join(callback_errors)

        # Reproduce the attached-log failure path:''',
)

validation = ROOT / "scripts/validate-6334-product-catalog.py"
text = validation.read_text(encoding="utf-8")
text = text.replace(
    '"def calculate_prices", "Interní kód", "Zdroje a ceny…",',
    '"def calculate_prices", "Interní kód", "Zdroje a ceny…", "__TURTO_CATALOG_CANCELLED__",',
)
validation.write_text(text, encoding="utf-8")

print("TURTO CRM 6.3.34 catalogue UI hardening complete")
