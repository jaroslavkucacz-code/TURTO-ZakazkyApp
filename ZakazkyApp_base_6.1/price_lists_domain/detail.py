"""Detailed Ceník and item-attribute view."""
from __future__ import annotations
from . import context as ctx
from .common import UPDATE_MODES,_number
from .operations import _open_archived_path,_selected_price_list_id
from .storage import _format_price

def open_price_list_detail(app, price_list_id=None):
    price_list_id = price_list_id or _selected_price_list_id(app)
    if not price_list_id:
        return ctx.M.messagebox.showinfo("Ceníky", "Vyberte ceník.", parent=app)
    with ctx.M.db() as con:
        header = con.execute(
            """SELECT p.*,coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'') supplier,
                      old.title previous_title
               FROM price_lists p
               LEFT JOIN companies c ON c.id=p.supplier_company_id
               LEFT JOIN price_lists old ON old.id=p.supersedes_id
               WHERE p.id=?""", (price_list_id,)
        ).fetchone()
        items = con.execute(
            "SELECT * FROM price_list_items WHERE price_list_id=? ORDER BY row_no,id", (price_list_id,)
        ).fetchall()
        attrs = con.execute(
            """SELECT a.* FROM price_list_item_attributes a
               JOIN price_list_items i ON i.id=a.item_id WHERE i.price_list_id=? ORDER BY a.item_id,a.id""",
            (price_list_id,),
        ).fetchall()
        rules = con.execute(
            "SELECT * FROM price_list_rules WHERE price_list_id=? AND active=1 ORDER BY priority,id", (price_list_id,)
        ).fetchall()
    if not header:
        return
    dialog = ctx.M.tk.Toplevel(app); dialog.title("Detail Ceníku"); dialog.transient(app); dialog.grab_set()
    ctx.M.enable_dialog_maximize(dialog, 1350, 820)
    outer = ctx.M.ttk.Frame(dialog, padding=14); outer.pack(fill="both", expand=True)
    ctx.M.ttk.Label(outer, text=f"{header['supplier'] or 'Neurčený dodavatel'} · {header['title']}",
                font=("Calibri", 16, "bold")).pack(anchor="w")
    subtitle = (
        f"Platnost: {ctx.M.fmt_date(header['valid_from']) or '—'} až {ctx.M.fmt_date(header['valid_to']) or 'bez konce'}"
        f"   ·   Skupina: {header['product_group'] or '—'}"
        f"   ·   Větev: {header['branch'] or '—'}"
        f"   ·   Režim: {UPDATE_MODES.get(header['update_mode'], header['update_mode'])}"
    )
    ctx.M.ttk.Label(outer, text=subtitle, style="PageSubtitle.TLabel").pack(anchor="w", pady=(2, 8))
    if header["previous_title"]:
        ctx.M.ttk.Label(outer, text=f"Aktualizuje: {header['previous_title']}", style="PageSubtitle.TLabel").pack(anchor="w", pady=(0, 8))
    paned = ctx.M.ttk.Panedwindow(outer, orient="vertical"); paned.pack(fill="both", expand=True)
    item_frame = ctx.M.ttk.Frame(paned); info_frame = ctx.M.ttk.Frame(paned)
    paned.add(item_frame, weight=4); paned.add(info_frame, weight=1)
    cols = ("Ř.", "Kód", "Produkt", "Zdrojová cena", "Cena/MJ", "Cena za", "MJ", "Přirážka", "Sleva",
            "Min. odběr", "Balení", "Paleta", "Hmotnost/MJ", "Hmotnost balení", "Hmotnost palety", "Podmínka")
    widths = (55, 120, 330, 110, 110, 70, 60, 80, 70, 90, 100, 80, 100, 115, 110, 240)
    tree = ctx.M.ttk.Treeview(item_frame, columns=cols, show="headings")
    for col, width in zip(cols, widths):tree.heading(col, text=col); tree.column(col, width=width, anchor="w")
    ys = ctx.M.ttk.Scrollbar(item_frame, orient="vertical", command=tree.yview)
    xs = ctx.M.ttk.Scrollbar(item_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    tree.grid(row=0, column=0, sticky="nsew"); ys.grid(row=0, column=1, sticky="ns"); xs.grid(row=1, column=0, sticky="ew")
    item_frame.rowconfigure(0, weight=1); item_frame.columnconfigure(0, weight=1)
    attrs_by_item = {}
    for attr in attrs:attrs_by_item.setdefault(int(attr["item_id"]), []).append(attr)
    for row in items:
        adjustment = _number(row["surcharge_pct"]) - _number(row["discount_pct"])
        tree.insert("", "end", iid=f"pli{row['id']}", values=(
            row["row_no"], row["product_code"] or row["item_key"] or "", row["name"] or row["description"] or "",
            _format_price(row["source_price"], row["currency"]), _format_price(row["normalized_unit_price"], row["currency"]),
            f"{_number(row['price_basis_qty']):g}", row["unit"] or "",
            f"+{_number(row['surcharge_pct']):g} %" if _number(row["surcharge_pct"]) else "",
            f"-{_number(row['discount_pct']):g} %" if _number(row["discount_pct"]) else "",
            f"{_number(row['minimum_qty']):g}" if _number(row["minimum_qty"]) else "",
            f"{_number(row['package_qty']):g} {row['package_unit'] or ''}".strip() if _number(row["package_qty"]) else "",
            f"{_number(row['pallet_qty']):g}" if _number(row["pallet_qty"]) else "",
            f"{_number(row['weight_unit']):g} kg" if _number(row["weight_unit"]) else "",
            f"{_number(row['weight_package']):g} kg" if _number(row["weight_package"]) else "",
            f"{_number(row['weight_pallet']):g} kg" if _number(row["weight_pallet"]) else "",
            row["condition_text"] or "",
        ))
    info_frame.columnconfigure(0, weight=1); info_frame.columnconfigure(1, weight=1); info_frame.rowconfigure(1, weight=1)
    ctx.M.ttk.Label(info_frame, text="Další údaje vybrané položky", style="Section.TLabel").grid(row=0, column=0, sticky="w")
    ctx.M.ttk.Label(info_frame, text="Podmínky a poznámky dokumentu", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=(10, 0))
    attr_text = ctx.M.tk.Text(info_frame, height=8, wrap="word"); attr_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
    terms_text = ctx.M.tk.Text(info_frame, height=8, wrap="word"); terms_text.grid(row=1, column=1, sticky="nsew", padx=(10, 0), pady=(4, 0))
    terms = str(header["terms_text"] or "")
    if rules:
        terms += "\n\nPravidla:\n" + "\n".join(
            f"• {r['condition_text'] or r['scope_value'] or r['rule_type']}: "
            f"{_number(r['percent_value']):g} %" if _number(r['percent_value']) else
            f"• {r['condition_text'] or r['scope_value'] or r['rule_type']}"
            for r in rules
        )
    terms_text.insert("1.0", terms.strip() or "Bez dalších podmínek."); terms_text.configure(state="disabled")
    def show_attrs(_event=None):
        attr_text.configure(state="normal"); attr_text.delete("1.0", "end")
        selection = tree.selection()
        if selection:
            item_id = int(str(selection[0])[3:])
            lines = []
            row = next((r for r in items if int(r["id"]) == item_id), None)
            if row:
                for label, value in (("GTIN", row["gtin"]), ("Celní kód", row["customs_code"]), ("Rozměry", row["dimensions"]),
                                     ("Popis", row["description"]), ("Původní řádek", row["source_row_json"])):
                    if str(value or "").strip():lines.append(f"{label}: {value}")
            for attr in attrs_by_item.get(item_id, []):
                lines.append(f"{attr['attribute_key']}: {attr['attribute_value']} {attr['attribute_unit'] or ''}".strip())
            attr_text.insert("1.0", "\n".join(lines) or "Bez dalších údajů.")
        attr_text.configure(state="disabled")
    tree.bind("<<TreeviewSelect>>", show_attrs, add="+")
    buttons = ctx.M.ttk.Frame(outer); buttons.pack(fill="x", pady=(8, 0))
    ctx.M.ttk.Button(buttons, text="Otevřít původní soubor", command=lambda:_open_archived_path(app, price_list_id, False)).pack(side="left")
    ctx.M.ttk.Button(buttons, text="Otevřít složku", command=lambda:_open_archived_path(app, price_list_id, True)).pack(side="left", padx=5)
    ctx.M.ttk.Button(buttons, text="Zavřít", style="Accent.TButton", command=dialog.destroy).pack(side="right")
