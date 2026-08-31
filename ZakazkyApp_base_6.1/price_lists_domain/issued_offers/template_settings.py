"""Manage uploaded header/footer assets and PDF page geometry."""
from __future__ import annotations

from . import service


def manage_templates(M, app):
    win = M.tk.Toplevel(app)
    win.title("Šablony vydaných nabídek")
    win.transient(app)
    win.grab_set()
    M.enable_dialog_maximize(win, 1180, 740)
    outer = M.ttk.Frame(win, padding=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(1, weight=1)
    M.ttk.Label(outer, text="PDF šablony vydaných nabídek", font=("Calibri", 16, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
    )

    left = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
    left.grid(row=1, column=0, sticky="nsw", padx=(0, 8))
    right = M.ttk.Frame(outer, style="Card.TFrame", padding=10)
    right.grid(row=1, column=1, sticky="nsew")
    right.columnconfigure(1, weight=1)

    tree = M.ttk.Treeview(left, columns=("Stav", "Výchozí"), show="tree headings", height=22, selectmode="browse")
    tree.heading("#0", text="Šablona")
    tree.column("#0", width=260, anchor="w")
    tree.heading("Stav", text="Stav")
    tree.column("Stav", width=85, anchor="w")
    tree.heading("Výchozí", text="Výchozí")
    tree.column("Výchozí", width=80, anchor="w")
    tree.pack(fill="both", expand=True)

    selected_id = {"value": None}
    vars_ = {
        "name": M.tk.StringVar(),
        "header_path": M.tk.StringVar(),
        "footer_path": M.tk.StringVar(),
        "header_height_mm": M.tk.StringVar(value="25"),
        "footer_height_mm": M.tk.StringVar(value="14"),
        "margin_left_mm": M.tk.StringVar(value="14"),
        "margin_right_mm": M.tk.StringVar(value="14"),
        "body_top_gap_mm": M.tk.StringVar(value="5"),
        "body_bottom_gap_mm": M.tk.StringVar(value="5"),
        "active": M.tk.BooleanVar(value=True),
        "is_default": M.tk.BooleanVar(value=False),
        "header_every_page": M.tk.BooleanVar(value=True),
        "footer_every_page": M.tk.BooleanVar(value=True),
    }

    row = 0
    M.ttk.Label(right, text="Název šablony").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
    M.ttk.Entry(right, textvariable=vars_["name"]).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
    row += 1

    def file_row(label, key):
        nonlocal row
        M.ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        M.ttk.Entry(right, textvariable=vars_[key]).grid(row=row, column=1, sticky="ew", pady=4)

        def choose():
            path = M.filedialog.askopenfilename(
                parent=win,
                filetypes=[("PNG, JPG nebo PDF", "*.png *.jpg *.jpeg *.pdf"), ("Všechny soubory", "*.*")],
            )
            if path:
                try:
                    target = service.copy_template_asset(M, path, key)
                    vars_[key].set(str(target))
                except Exception as exc:
                    M.messagebox.showerror("PDF šablony", str(exc), parent=win)

        M.ttk.Button(right, text="Nahrát…", command=choose).grid(row=row, column=2, sticky="w", padx=(6, 0))
        row += 1

    file_row("Záhlaví", "header_path")
    file_row("Zápatí", "footer_path")

    numeric = (
        ("Výška záhlaví [mm]", "header_height_mm"),
        ("Výška zápatí [mm]", "footer_height_mm"),
        ("Levý okraj [mm]", "margin_left_mm"),
        ("Pravý okraj [mm]", "margin_right_mm"),
        ("Odstup pod záhlavím [mm]", "body_top_gap_mm"),
        ("Odstup nad zápatím [mm]", "body_bottom_gap_mm"),
    )
    for label, key in numeric:
        M.ttk.Label(right, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        M.ttk.Entry(right, textvariable=vars_[key], width=16).grid(row=row, column=1, sticky="w", pady=4)
        row += 1

    for text, key in (
        ("Aktivní šablona", "active"),
        ("Použít jako výchozí", "is_default"),
        ("Záhlaví na každé stránce", "header_every_page"),
        ("Zápatí na každé stránce", "footer_every_page"),
    ):
        M.ttk.Checkbutton(right, text=text, variable=vars_[key]).grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
        row += 1

    M.ttk.Label(
        right,
        text="Soubory se kopírují do Dokumenty\\TURTO Zakazky\\Sablony\\Vydane nabidky. Změna šablony nemění již vytvořené PDF revize.",
        style="PageSubtitle.TLabel", wraplength=760,
    ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 4))
    row += 1
    buttons = M.ttk.Frame(right)
    buttons.grid(row=row, column=0, columnspan=3, sticky="e", pady=(10, 0))

    def clear():
        selected_id["value"] = None
        vars_["name"].set("Nová šablona")
        vars_["header_path"].set("")
        vars_["footer_path"].set("")
        for key, value in (("header_height_mm", "25"), ("footer_height_mm", "14"), ("margin_left_mm", "14"), ("margin_right_mm", "14"), ("body_top_gap_mm", "5"), ("body_bottom_gap_mm", "5")):
            vars_[key].set(value)
        vars_["active"].set(True)
        vars_["is_default"].set(False)
        vars_["header_every_page"].set(True)
        vars_["footer_every_page"].set(True)

    def refresh(select_id=None):
        for iid in tree.get_children(""):
            tree.delete(iid)
        rows = service.list_templates(M, include_inactive=True)
        for item in rows:
            iid = f"t{item['id']}"
            tree.insert(
                "", "end", iid=iid, text=item["name"],
                values=("Aktivní" if item["active"] else "Neaktivní", "Ano" if item["is_default"] else ""),
                tags=("status_cancel",) if not item["active"] else (),
            )
        if select_id and tree.exists(f"t{select_id}"):
            tree.selection_set(f"t{select_id}")
            tree.see(f"t{select_id}")

    def load_selected(*_):
        selection = tree.selection()
        if not selection:
            return
        template_id = int(str(selection[0])[1:])
        data = service.load_template(M, template_id)
        selected_id["value"] = template_id
        for key in ("name", "header_path", "footer_path", "header_height_mm", "footer_height_mm", "margin_left_mm", "margin_right_mm", "body_top_gap_mm", "body_bottom_gap_mm"):
            vars_[key].set(str(data.get(key) or ""))
        for key in ("active", "is_default", "header_every_page", "footer_every_page"):
            vars_[key].set(bool(data.get(key)))

    def save():
        try:
            values = {key: variable.get() for key, variable in vars_.items()}
            template_id = service.save_template(M, values, selected_id["value"])
            selected_id["value"] = template_id
            refresh(template_id)
            try:
                app.refresh_issued_offers()
            except Exception:
                pass
        except Exception as exc:
            M.messagebox.showwarning("PDF šablony", str(exc), parent=win)

    def remove():
        if not selected_id["value"]:
            return
        if M.messagebox.askyesno("PDF šablony", "Odebrat vybranou šablonu? Použitá šablona bude pouze deaktivována.", parent=win):
            service.deactivate_template(M, selected_id["value"])
            clear()
            refresh()

    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right")
    M.ttk.Button(buttons, text="Nová", command=clear).pack(side="right", padx=5)
    M.ttk.Button(buttons, text="Odebrat", command=remove).pack(side="right", padx=5)
    M.ttk.Button(buttons, text="Zavřít", command=win.destroy).pack(side="right", padx=5)
    tree.bind("<<TreeviewSelect>>", load_selected, add="+")
    refresh()
    rows = service.list_templates(M)
    if rows:
        tree.selection_set(f"t{rows[0]['id']}")
        load_selected()
    else:
        clear()


def install(M):
    M.App.manage_issued_offer_templates = lambda self: manage_templates(M, self)


__all__ = ["manage_templates", "install"]
