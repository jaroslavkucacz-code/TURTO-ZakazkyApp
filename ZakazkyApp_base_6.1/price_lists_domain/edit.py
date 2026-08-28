"""Editing of non-destructive Ceník metadata."""
from __future__ import annotations
from datetime import datetime,timedelta
from . import context as ctx
from .common import UPDATE_MODES,_iso_date
from .operations import _selected_price_list_id

def edit_price_list_metadata(app):
    price_list_id = _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    with ctx.M.db() as con:
        row = con.execute("SELECT * FROM price_lists WHERE id=?", (price_list_id,)).fetchone()
        prior = con.execute(
            """SELECT id,title,valid_from,supplier_name FROM price_lists
               WHERE id<>? AND archived=0 ORDER BY valid_from DESC,id DESC LIMIT 500""", (price_list_id,)
        ).fetchall()
    if not row:return
    dialog = ctx.M.tk.Toplevel(app); dialog.title("Upravit údaje Ceníku"); dialog.transient(app); dialog.grab_set()
    ctx.M.enable_dialog_maximize(dialog, 820, 620)
    outer = ctx.M.scrollable_dialog_frame(dialog, 14)
    variables = {
        "title": ctx.M.tk.StringVar(value=row["title"] or ""),
        "valid_from": ctx.M.tk.StringVar(value=row["valid_from"] or ""),
        "valid_to": ctx.M.tk.StringVar(value=row["valid_to"] or ""),
        "product_group": ctx.M.tk.StringVar(value=row["product_group"] or ""),
        "branch": ctx.M.tk.StringVar(value=row["branch"] or ""),
        "update_mode": ctx.M.tk.StringVar(value=UPDATE_MODES.get(row["update_mode"] or "partial", UPDATE_MODES["partial"])),
        "previous": ctx.M.tk.StringVar(value=""),
    }
    labels = (("Název", "title"), ("Produktová skupina", "product_group"), ("Větev / podmínka", "branch"))
    for idx, (label, key) in enumerate(labels):
        ctx.M.ttk.Label(outer, text=label).grid(row=idx, column=0, sticky="w", pady=5)
        ctx.M.ttk.Entry(outer, textvariable=variables[key]).grid(row=idx, column=1, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Platí od").grid(row=3, column=0, sticky="w", pady=5); ctx.M.DatePicker(outer, variables["valid_from"]).grid(row=3, column=1, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Platí do").grid(row=4, column=0, sticky="w", pady=5); ctx.M.DatePicker(outer, variables["valid_to"]).grid(row=4, column=1, sticky="ew", pady=5)
    ctx.M.ttk.Label(outer, text="Způsob aktualizace").grid(row=5, column=0, sticky="w", pady=5)
    ctx.M.safe_combobox(outer, textvariable=variables["update_mode"], values=list(UPDATE_MODES.values()), state="readonly").grid(row=5, column=1, sticky="ew", pady=5)
    prior_values = [(f"{r['supplier_name']} · {r['title']} · {ctx.M.fmt_date(r['valid_from'])}", r["id"]) for r in prior]
    current_label = next((label for label, pid in prior_values if pid == row["supersedes_id"]), "")
    variables["previous"].set(current_label)
    ctx.M.ttk.Label(outer, text="Aktualizuje předchozí ceník").grid(row=6, column=0, sticky="w", pady=5)
    previous_box = ctx.M.AutocompleteEntry(outer, textvariable=variables["previous"], values=prior_values)
    previous_box.grid(row=6, column=1, sticky="ew", pady=5)
    note = ctx.M.tk.Text(outer, height=4, wrap="word"); note.insert("1.0", row["note"] or "")
    ctx.M.ttk.Label(outer, text="Poznámka").grid(row=7, column=0, sticky="nw", pady=5); note.grid(row=7, column=1, sticky="ew", pady=5)
    buttons = ctx.M.ttk.Frame(outer); buttons.grid(row=8, column=0, columnspan=2, sticky="e", pady=8)
    def save():
        previous_id = getattr(previous_box, "selected_payload", None)
        if not previous_id and variables["previous"].get().strip():
            previous_id = next((pid for label, pid in prior_values if label.casefold() == variables["previous"].get().strip().casefold()), None)
        valid_from = _iso_date(variables["valid_from"].get())
        mode = next((key for key,label in UPDATE_MODES.items() if label==variables["update_mode"].get()), "partial")
        with ctx.M.db() as con:
            con.execute(
                """UPDATE price_lists SET title=?,valid_from=?,valid_to=?,product_group=?,branch=?,update_mode=?,supersedes_id=?,note=? WHERE id=?""",
                (variables["title"].get().strip(), valid_from, _iso_date(variables["valid_to"].get()),
                 variables["product_group"].get().strip(), variables["branch"].get().strip(), mode,
                 previous_id, note.get("1.0", "end").strip(), price_list_id),
            )
            if previous_id and mode in {"replace_group", "replace_all"} and valid_from:
                previous_day = (datetime.strptime(valid_from, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
                con.execute("UPDATE price_lists SET valid_to=? WHERE id=? AND (valid_to='' OR valid_to>?)",
                            (previous_day, previous_id, previous_day))
        dialog.destroy(); app.refresh_price_lists(); app.refresh_offers()
    ctx.M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right", padx=4)
    ctx.M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right")
    outer.columnconfigure(1, weight=1)
