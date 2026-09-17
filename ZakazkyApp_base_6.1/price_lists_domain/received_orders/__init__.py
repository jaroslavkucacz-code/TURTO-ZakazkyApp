"""Received orders page and issued-offer conversion command."""
from . import service
from .editor import ReceivedOrderEditor
from ..platform import universal_search as search


def install(M):
    if getattr(M.App, "_received_orders_828", False):
        return
    from ..platform import lazy_refresh
    lazy_refresh.PAGE_REFRESH["received_orders"] = "refresh_received_orders"
    lazy_refresh.PAGE_TREES["received_orders"] = ("received_order_tree",)

    def open_editor(app, document_id=None, source_offer_id=None):
        try:
            editor = ReceivedOrderEditor(M, app, document_id, source_offer_id)
            app._received_order_editor = editor
            return editor
        except Exception as exc:
            M.messagebox.showwarning("Přijatá objednávka", str(exc), parent=app)

    def convert(app):
        from ..issued_offers.page import _selected_one
        row = _selected_one(M, app)
        if row:
            return open_editor(app, source_offer_id=int(row["id"]))

    def selected(app):
        values = app.received_order_tree.selection()
        if len(values) != 1:
            return M.messagebox.showinfo("Přijaté objednávky", "Vyberte právě jednu objednávku.", parent=app)
        return open_editor(app, int(values[0][2:]))

    def build_page(app):
        page = app.tabs["received_orders"]
        app.title_label(page, "Přijaté objednávky", "+ Nová objednávka", lambda: open_editor(app))
        toolbar = M.ttk.Frame(page, style="Panel.TFrame", padding=8)
        toolbar.pack(fill="x", pady=(0, 6))
        M.ttk.Button(toolbar, text="Otevřít objednávku", command=lambda: selected(app)).pack(side="left")
        M.ttk.Button(toolbar, text="Přejít na vydané nabídky", command=lambda: app.show_page("issued_offers")).pack(side="left", padx=8)
        filters = M.ttk.Frame(page, style="Panel.TFrame")
        filters.pack(fill="x", pady=(0, 4))
        columns = ("Číslo", "Přijato", "Termín", "Odběratel", "Číslo u odběratele", "Z nabídky", "Předmět", "Stav", "Bez DPH", "S DPH", "Měna")
        app.received_order_tree = app.tree(page, columns, (145, 100, 100, 240, 170, 140, 240, 120, 110, 110, 65))
        search.install_main_search(app, app.received_order_tree, filters, "received_orders", "refresh_received_orders")
        M.bind_row_double_click(app.received_order_tree, lambda event: selected(app))
        app.received_order_tree.bind("<Return>", lambda event: (selected(app), "break")[1])
        refresh(app)

    def refresh(app):
        tree = getattr(app, "received_order_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        chosen = set(tree.selection())
        for iid in tree.get_children():
            tree.delete(iid)
        for row in service.list_documents(M):
            iid = f"ro{row['id']}"
            search.insert_matching(tree, "", "end", iid=iid, values=(row["document_number"], M.fmt_date(row["issue_date"]), M.fmt_date(row["due_date"]),
                row["customer_name_snapshot"], row["customer_reference"], row["source_offer_number"], row["offer_subject"], row["status"],
                f"{row['subtotal_net']:,.2f}".replace(",", " "), f"{row['total_gross']:,.2f}".replace(",", " "), row["currency"]))
            if iid in chosen and tree.exists(iid):
                tree.selection_add(iid)

    M.App.open_received_order_editor = open_editor
    M.App.create_received_order_from_offer = convert
    M.App.refresh_received_orders = refresh
    previous_build = M.App.build

    def build(app, *args, **kwargs):
        result = previous_build(app, *args, **kwargs)
        page = M.ttk.Frame(app.pages, style="App.TFrame")
        page.grid(row=0, column=0, sticky="nsew")
        app.tabs["received_orders"] = page
        from ..platform.grouped_navigation import register_page
        register_page(app, "received_orders", "Přijaté objednávky")
        build_page(app)
        page.grid_remove()
        return result

    M.App.build = build
    M.App._received_orders_828 = True
