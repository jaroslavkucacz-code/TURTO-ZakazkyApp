from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ZakazkyApp_base_6.1"


def replace(path, old, new, count=1):
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8")


catalog = SRC / "price_lists_domain/platform/product_catalog.py"
replace(
    catalog,
    "    return result\n\n\ndef _edit_product",
    '''    return result


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
    # The catalogue may be opened from a modal Ceník/Nabídka detail. Release its
    # grab first so the new window is always interactive.
    try:
        grabbed = app.grab_current()
        if grabbed is not None:
            grabbed.grab_release()
    except Exception:
        pass
    # Link only a small legacy batch synchronously; full migration has progress
    # and Storno so a large customer database never appears frozen.
    initial_sync = sync_all_unlinked(M, max_documents=25)
    win = M.tk.Toplevel(app)
''',
)
replace(
    catalog,
    '        bar.pack(fill="x")\n\n        def progress(done, total, text):',
    '''        bar.pack(fill="x")
        cancelled = {"value": False}
        M.ttk.Button(
            frame, text="Storno", command=lambda: cancelled.__setitem__("value", True)
        ).pack(anchor="e", pady=(10, 0))

        def progress(done, total, text):''',
)
replace(
    catalog,
    '''            progress_win.update_idletasks()

        try:''',
    '''            progress_win.update()
            if cancelled["value"]:
                raise RuntimeError("__TURTO_CATALOG_CANCELLED__")

        try:''',
)
replace(
    catalog,
    '''        except Exception as exc:
            progress_win.destroy()
            return M.messagebox.showerror("Katalog produktů", f"Synchronizaci se nepodařilo dokončit:\\n{exc}", parent=win)
        progress_win.destroy()
''',
    '''        except Exception as exc:
            progress_win.destroy()
            if str(exc) == "__TURTO_CATALOG_CANCELLED__":
                refresh_filters()
                refresh()
                return M.messagebox.showinfo(
                    "Katalog produktů", "Synchronizace byla stornována. Již propojené položky zůstaly bezpečně uložené.", parent=win
                )
            return M.messagebox.showerror(
                "Katalog produktů", "Synchronizaci se nepodařilo dokončit:" + chr(10) + str(exc), parent=win
            )
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

        # Open the actual catalogue against the isolated additive schema. This
        # catches modal-grab, SQL-column and Treeview integration regressions.
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
needle = '"def calculate_prices", "Interní kód", "Zdroje a ceny…",'
if needle not in text:
    raise SystemExit("Validation anchor not found")
validation.write_text(
    text.replace(needle, '"def calculate_prices", "Interní kód", "Zdroje a ceny…", "__TURTO_CATALOG_CANCELLED__",', 1),
    encoding="utf-8",
)

print("TURTO CRM 6.3.34 catalogue UI hardening complete")
