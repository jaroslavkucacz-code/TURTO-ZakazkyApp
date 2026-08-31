"""CRM list page for issued offers."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from . import service


_STATUS_TAGS = {
    "Rozpracováno": "status_active",
    "Připraveno": "status_wait",
    "Odesláno": "status_offer",
    "Přijato": "status_done",
    "Zamítnuto": "status_cancel",
    "Zrušeno": "status_cancel",
    "Archivováno": "status_cancel",
}


def _exists(widget):
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return False


def _combobox(M, parent, variable, values, width=None):
    kwargs = {"textvariable": variable, "values": values, "state": "readonly"}
    if width:
        kwargs["width"] = width
    return M.safe_combobox(parent, **kwargs)


def build_issued_offers(M, app):
    page = app.tabs["issued_offers"]
    for child in page.winfo_children():
        child.destroy()
    app.title_label(page, "Vydané nabídky")
    M.ttk.Label(
        page,
        text="Cenové nabídky vystavené zákazníkům · položky z Katalogu · PDF revize · Outlook koncept",
        style="PageSubtitle.TLabel",
    ).pack(anchor="w", pady=(0, 8))

    toolbar = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    toolbar.pack(fill="x", pady=(0, 7))
    M.ttk.Button(toolbar, text="+ Nová nabídka", style="Accent.TButton", command=lambda: app.open_issued_offer_editor()).pack(side="left")
    M.ttk.Button(toolbar, text="Upravit / otevřít", command=lambda: _open_selected(M, app)).pack(side="left", padx=4)
    M.ttk.Button(toolbar, text="Duplikovat", command=lambda: _duplicate_selected(M, app)).pack(side="left", padx=4)
    M.ttk.Button(toolbar, text="Vytvořit PDF", command=lambda: _render_selected(M, app, True)).pack(side="left", padx=(14, 4))
    M.ttk.Button(toolbar, text="Outlook koncept", command=lambda: _draft_selected(M, app)).pack(side="left", padx=4)
    M.ttk.Button(toolbar, text="Šablony PDF…", command=lambda: app.manage_issued_offer_templates()).pack(side="right")
    M.ttk.Button(toolbar, text="Nastavení…", command=lambda: app.open_issued_offer_settings()).pack(side="right", padx=4)

    metrics = M.ttk.Frame(page, style="App.TFrame")
    metrics.pack(fill="x", pady=(0, 7))
    app.issued_offer_metric_vars = {}
    metric_defs = (
        ("Rozpracované", "draft", "Rozpracováno"),
        ("K odeslání", "ready", "Připraveno"),
        ("Odeslané", "sent", "Odesláno"),
        ("Končí do 7 dnů", "expiring", "Končí"),
        ("Přijaté", "accepted", "Přijato"),
        ("Archivované", "archived", "Archivováno"),
    )
    for index, (label, key, quick) in enumerate(metric_defs):
        card = M.ttk.Frame(metrics, style="Card.TFrame", padding=(11, 8))
        card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 4, 0))
        metrics.columnconfigure(index, weight=1)
        M.ttk.Label(card, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        variable = M.tk.StringVar(value="—")
        app.issued_offer_metric_vars[key] = variable
        value_label = M.ttk.Label(card, textvariable=variable, font=("Calibri", 15, "bold"))
        value_label.pack(anchor="w")
        for widget in (card, value_label):
            try:
                widget.configure(cursor="hand2")
                widget.bind("<Button-1>", lambda _event, target=quick: _quick_view(M, app, target), add="+")
            except Exception:
                pass

    filters = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 7))
    filters.pack(fill="x", pady=(0, 7))
    app.issued_offer_q = M.tk.StringVar()
    app.issued_offer_company = M.tk.StringVar()
    app.issued_offer_project = M.tk.StringVar()
    app.issued_offer_status = M.tk.StringVar(value="Aktivní")
    app.issued_offer_page_size = M.tk.StringVar(value="250")
    app.issued_offer_page = 0
    labels = ("Hledat", "Odběratel", "Akce / Příležitost", "Pohled", "Řádků")
    for index, label in enumerate(labels):
        M.ttk.Label(filters, text=label, style="FilterLabel.TLabel").grid(row=0, column=index, sticky="w")
        filters.columnconfigure(index, weight=3 if index == 0 else 1)
    M.ttk.Entry(filters, textvariable=app.issued_offer_q).grid(row=1, column=0, sticky="ew", padx=(0, 5))
    companies = [name for _cid, name in service.list_companies(M)]
    app.issued_offer_company_box = M.AutocompleteEntry(filters, textvariable=app.issued_offer_company, values=companies)
    app.issued_offer_company_box.grid(row=1, column=1, sticky="ew", padx=(0, 5))
    projects = [name for _pid, name in service.list_projects(M)] + [name for _aid, name, _pid in service.list_actions(M)]
    app.issued_offer_project_box = M.AutocompleteEntry(filters, textvariable=app.issued_offer_project, values=projects)
    app.issued_offer_project_box.grid(row=1, column=2, sticky="ew", padx=(0, 5))
    _combobox(
        M, filters, app.issued_offer_status,
        ["Aktivní", "Všechny", *service.STATUSES, "Končí", "Po platnosti", "Archivováno"],
    ).grid(row=1, column=3, sticky="ew", padx=(0, 5))
    _combobox(M, filters, app.issued_offer_page_size, ["100", "250", "500", "1000"], 8).grid(row=1, column=4, sticky="ew")

    body = M.ttk.Panedwindow(page, orient="horizontal")
    body.pack(fill="both", expand=True)
    left = M.ttk.Frame(body)
    right = M.ttk.Frame(body, style="Panel.TFrame", padding=12)
    body.add(left, weight=4)
    body.add(right, weight=1)
    left.columnconfigure(0, weight=1)
    left.rowconfigure(0, weight=1)
    right.columnconfigure(0, weight=1)

    columns = ("Číslo", "Datum", "Platnost", "Odběratel", "Akce", "Předmět", "Stav", "Bez DPH", "S DPH", "Měna", "Revize", "Obchodník")
    widths = (135, 95, 105, 220, 230, 260, 110, 115, 115, 65, 65, 150)
    wrap = M.ttk.Frame(left)
    wrap.grid(row=0, column=0, sticky="nsew")
    wrap.columnconfigure(0, weight=1)
    wrap.rowconfigure(0, weight=1)
    app.issued_offer_tree = M.ttk.Treeview(wrap, columns=columns, show="headings", selectmode="extended")
    for column, width in zip(columns, widths):
        sorter = getattr(app, "sort_tree", None)
        if callable(sorter):
            app.issued_offer_tree.heading(column, text=column, command=lambda col=column: sorter(app.issued_offer_tree, col))
        else:
            app.issued_offer_tree.heading(column, text=column)
        app.issued_offer_tree.column(column, width=width, anchor="w", stretch=False)
    app.issued_offer_tree.grid(row=0, column=0, sticky="nsew")
    ys = M.ttk.Scrollbar(wrap, orient="vertical", command=app.issued_offer_tree.yview)
    xs = M.ttk.Scrollbar(wrap, orient="horizontal", command=app.issued_offer_tree.xview)
    ys.grid(row=0, column=1, sticky="ns")
    xs.grid(row=1, column=0, sticky="ew")
    app.issued_offer_tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
    app.issued_offer_rows = {}
    M.bind_row_double_click(app.issued_offer_tree, lambda _event: _open_selected(M, app))
    app.issued_offer_tree.bind("<<TreeviewSelect>>", lambda _event: _refresh_detail(M, app), add="+")

    nav = M.ttk.Frame(left, style="Panel.TFrame", padding=(8, 6))
    nav.grid(row=1, column=0, sticky="ew", pady=(6, 0))
    app.issued_offer_status_text = M.tk.StringVar(value="")
    M.ttk.Label(nav, textvariable=app.issued_offer_status_text, style="PageSubtitle.TLabel").pack(side="left")
    M.ttk.Button(nav, text="Zrušit filtry", command=lambda: _clear_filters(M, app)).pack(side="left", padx=(12, 0))
    app.issued_offer_prev = M.ttk.Button(nav, text="← Předchozí", command=lambda: _change_page(M, app, -1))
    app.issued_offer_prev.pack(side="right", padx=3)
    app.issued_offer_next = M.ttk.Button(nav, text="Další →", command=lambda: _change_page(M, app, 1))
    app.issued_offer_next.pack(side="right", padx=3)

    M.ttk.Label(right, text="Detail vydané nabídky", font=("Calibri", 14, "bold")).grid(row=0, column=0, sticky="w")
    app.issued_offer_detail_title = M.tk.StringVar(value="Nevybrána žádná nabídka")
    M.ttk.Label(right, textvariable=app.issued_offer_detail_title, font=("Calibri", 12, "bold"), wraplength=340).grid(row=1, column=0, sticky="w", pady=(8, 3))
    app.issued_offer_detail_text = M.tk.StringVar(value="Vyberte nabídku v tabulce.")
    M.ttk.Label(right, textvariable=app.issued_offer_detail_text, justify="left", wraplength=350).grid(row=2, column=0, sticky="nw")
    actions = M.ttk.Frame(right, style="Panel.TFrame")
    actions.grid(row=3, column=0, sticky="ew", pady=(14, 0))
    M.ttk.Button(actions, text="Otevřít nabídku", style="Accent.TButton", command=lambda: _open_selected(M, app)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Vytvořit a otevřít PDF", command=lambda: _render_selected(M, app, True)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Otevřít poslední PDF", command=lambda: _open_pdf(M, app)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Outlook koncept", command=lambda: _draft_selected(M, app)).pack(fill="x", pady=2)
    M.ttk.Separator(actions).pack(fill="x", pady=7)
    M.ttk.Button(actions, text="Duplikovat nabídku", command=lambda: _duplicate_selected(M, app)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Změnit stav…", command=lambda: _change_status(M, app)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Archivovat / obnovit", command=lambda: _toggle_archive(M, app)).pack(fill="x", pady=2)
    M.ttk.Button(actions, text="Odstranit koncept", command=lambda: _delete_selected(M, app)).pack(fill="x", pady=2)

    context = M.tk.Menu(app.issued_offer_tree, tearoff=False)
    context.add_command(label="Otevřít nabídku", command=lambda: _open_selected(M, app))
    context.add_command(label="Vytvořit PDF", command=lambda: _render_selected(M, app, True))
    context.add_command(label="Outlook koncept", command=lambda: _draft_selected(M, app))
    context.add_separator()
    context.add_command(label="Duplikovat", command=lambda: _duplicate_selected(M, app))
    context.add_command(label="Změnit stav…", command=lambda: _change_status(M, app))
    context.add_command(label="Archivovat / obnovit", command=lambda: _toggle_archive(M, app))

    def popup(event):
        iid = app.issued_offer_tree.identify_row(event.y)
        if iid and iid not in app.issued_offer_tree.selection():
            app.issued_offer_tree.selection_set(iid)
        try:
            context.tk_popup(event.x_root, event.y_root)
        finally:
            context.grab_release()

    app.issued_offer_tree.bind("<Button-3>", popup, add="+")
    for variable in (app.issued_offer_q, app.issued_offer_company, app.issued_offer_project, app.issued_offer_status, app.issued_offer_page_size):
        variable.trace_add("write", lambda *_: _schedule_refresh(M, app))
    refresh_issued_offers(M, app)


def _summary(M):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=7)).isoformat()
    with M.db() as con:
        row = con.execute(
            """SELECT
              SUM(CASE WHEN archived=0 AND status='Rozpracováno' THEN 1 ELSE 0 END) draft,
              SUM(CASE WHEN archived=0 AND status='Připraveno' THEN 1 ELSE 0 END) ready,
              SUM(CASE WHEN archived=0 AND status='Odesláno' THEN 1 ELSE 0 END) sent,
              SUM(CASE WHEN archived=0 AND status NOT IN ('Přijato','Zamítnuto','Zrušeno')
                       AND trim(coalesce(valid_to,''))<>'' AND valid_to>=? AND valid_to<=? THEN 1 ELSE 0 END) expiring,
              SUM(CASE WHEN archived=0 AND status='Přijato' THEN 1 ELSE 0 END) accepted,
              SUM(CASE WHEN archived=1 THEN 1 ELSE 0 END) archived
              FROM business_documents WHERE document_type=? AND direction=?""",
            (today, soon, service.DOCUMENT_TYPE, service.DOCUMENT_DIRECTION),
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _refresh_metrics(M, app):
    values = _summary(M)
    for key, variable in getattr(app, "issued_offer_metric_vars", {}).items():
        variable.set(f"{values.get(key, 0):,}".replace(",", " "))


def refresh_issued_offers(M, app):
    tree = getattr(app, "issued_offer_tree", None)
    if not _exists(tree):
        return
    selected = set(tree.selection())
    for iid in tree.get_children(""):
        tree.delete(iid)
    app.issued_offer_rows = {}
    where = ["d.document_type=?", "d.direction=?"]
    params = [service.DOCUMENT_TYPE, service.DOCUMENT_DIRECTION]
    query = app.issued_offer_q.get().strip().casefold()
    if query:
        where.append(
            "lower(coalesce(d.document_number,'')||' '||coalesce(d.customer_name_snapshot,'')||' '||"
            "coalesce(d.offer_subject,'')||' '||coalesce(d.customer_reference,'')||' '||"
            "coalesce(p.name,'')||' '||coalesce(a.name,'')||' '||coalesce(d.salesperson_snapshot,'')) LIKE ?"
        )
        params.append("%" + query + "%")
    company = app.issued_offer_company.get().strip().casefold()
    if company:
        where.append("lower(coalesce(d.customer_name_snapshot,c.official_name,c.short_name,'')) LIKE ?")
        params.append("%" + company + "%")
    project = app.issued_offer_project.get().strip().casefold()
    if project:
        where.append("lower(coalesce(p.name,'')||' '||coalesce(a.name,'')) LIKE ?")
        params.append("%" + project + "%")
    status = app.issued_offer_status.get()
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=7)).isoformat()
    if status == "Aktivní":
        where.append("d.archived=0")
    elif status == "Archivováno":
        where.append("d.archived=1")
    elif status == "Končí":
        where += ["d.archived=0", "d.status NOT IN ('Přijato','Zamítnuto','Zrušeno')", "d.valid_to>=?", "d.valid_to<=?"]
        params += [today, soon]
    elif status == "Po platnosti":
        where += ["d.archived=0", "trim(coalesce(d.valid_to,''))<>''", "d.valid_to<?", "d.status NOT IN ('Přijato','Zamítnuto','Zrušeno')"]
        params.append(today)
    elif status != "Všechny":
        where.append("d.archived=0 AND d.status=?")
        params.append(status)
    try:
        page_size = max(50, min(1000, int(app.issued_offer_page_size.get() or 250)))
    except Exception:
        page_size = 250
    offset = max(0, int(app.issued_offer_page or 0)) * page_size
    with M.db() as con:
        total = int(con.execute(
            f"""SELECT COUNT(*) FROM business_documents d
                 LEFT JOIN companies c ON c.id=d.company_id
                 LEFT JOIN projects p ON p.id=d.project_id
                 LEFT JOIN actions a ON a.id=d.action_id
                 WHERE {' AND '.join(where)}""",
            params,
        ).fetchone()[0] or 0)
        rows = con.execute(
            f"""SELECT d.*,coalesce(nullif(trim(d.customer_name_snapshot),''),c.official_name,c.short_name,'') customer,
                       p.name project_name,a.name action_name
                FROM business_documents d
                LEFT JOIN companies c ON c.id=d.company_id
                LEFT JOIN projects p ON p.id=d.project_id
                LEFT JOIN actions a ON a.id=d.action_id
                WHERE {' AND '.join(where)}
                ORDER BY d.archived,d.issue_date DESC,d.id DESC LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()
    if total and offset >= total and app.issued_offer_page:
        app.issued_offer_page = 0
        return refresh_issued_offers(M, app)
    for row in rows:
        item = dict(row)
        iid = f"bo{row['id']}"
        app.issued_offer_rows[iid] = item
        state = "Archivováno" if row["archived"] else row["status"]
        action = row["project_name"] or row["action_name"] or ""
        tree.insert(
            "", "end", iid=iid,
            values=(
                row["document_number"], M.fmt_date(row["issue_date"]), M.fmt_date(row["valid_to"]),
                row["customer"], action, row["offer_subject"], state,
                f"{service.number(row['subtotal_net']):,.2f}".replace(",", " "),
                f"{service.number(row['total_gross']):,.2f}".replace(",", " "),
                row["currency"], f"R{int(row['revision_no'] or 0):02d}" if row["last_pdf_path"] else "—",
                row["salesperson_snapshot"],
            ),
            tags=(_STATUS_TAGS.get(state, "status_active"),),
        )
        if iid in selected:
            tree.selection_add(iid)
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    app.issued_offer_status_text.set(f"Zobrazeno {start}–{end} z {total} vydaných nabídek")
    app.issued_offer_prev.state(["!disabled"] if app.issued_offer_page > 0 else ["disabled"])
    app.issued_offer_next.state(["!disabled"] if end < total else ["disabled"])
    _refresh_metrics(M, app)
    _refresh_detail(M, app)


def _selected_rows(app):
    return [app.issued_offer_rows[iid] for iid in app.issued_offer_tree.selection() if iid in app.issued_offer_rows]


def _selected_one(M, app):
    rows = _selected_rows(app)
    if len(rows) != 1:
        M.messagebox.showinfo("Vydané nabídky", "Vyberte právě jednu nabídku.", parent=app)
        return None
    return rows[0]


def _refresh_detail(M, app):
    rows = _selected_rows(app)
    if not rows:
        app.issued_offer_detail_title.set("Nevybrána žádná nabídka")
        app.issued_offer_detail_text.set("Vyberte nabídku v tabulce.")
        return
    if len(rows) > 1:
        total = sum(service.number(row.get("subtotal_net")) for row in rows)
        app.issued_offer_detail_title.set(f"Vybráno {len(rows)} nabídek")
        app.issued_offer_detail_text.set(f"Společná hodnota bez DPH: {total:,.2f}".replace(",", " "))
        return
    row = rows[0]
    app.issued_offer_detail_title.set(f"{row.get('document_number') or ''} · {row.get('customer') or ''}")
    lines = [
        f"Stav: {'Archivováno' if row.get('archived') else row.get('status') or '—'}",
        f"Datum: {M.fmt_date(row.get('issue_date'))}",
        f"Platnost: {M.fmt_date(row.get('valid_to')) or 'bez omezení'}",
        f"Akce: {row.get('project_name') or row.get('action_name') or '—'}",
        f"Předmět: {row.get('offer_subject') or '—'}",
        f"Reference: {row.get('customer_reference') or '—'}",
        f"Celkem bez DPH: {service.number(row.get('subtotal_net')):,.2f} {row.get('currency') or 'CZK'}".replace(",", " "),
        f"Celkem s DPH: {service.number(row.get('total_gross')):,.2f} {row.get('currency') or 'CZK'}".replace(",", " "),
        f"Obchodník: {row.get('salesperson_snapshot') or '—'}",
        f"Poslední PDF: {Path(str(row.get('last_pdf_path') or '')).name or 'nevytvořeno'}",
    ]
    app.issued_offer_detail_text.set("\n".join(lines))


def _open_selected(M, app):
    row = _selected_one(M, app)
    if row:
        app.open_issued_offer_editor(int(row["id"]))


def _duplicate_selected(M, app):
    row = _selected_one(M, app)
    if not row:
        return
    try:
        new_id = service.duplicate_document(M, int(row["id"]))
        refresh_issued_offers(M, app)
        app.open_issued_offer_editor(new_id)
    except Exception as exc:
        M.messagebox.showerror("Vydané nabídky", str(exc), parent=app)


def _render_selected(M, app, open_after=False):
    row = _selected_one(M, app)
    if not row:
        return
    try:
        M.render_issued_offer_pdf(int(row["id"]), open_after=open_after)
        refresh_issued_offers(M, app)
    except Exception as exc:
        M.messagebox.showerror("Vydané nabídky", str(exc), parent=app)


def _open_pdf(M, app):
    row = _selected_one(M, app)
    if not row:
        return
    path = service.latest_pdf_path(M, int(row["id"]))
    if not path:
        return M.messagebox.showinfo("Vydané nabídky", "K nabídce zatím nebylo vytvořeno PDF.", parent=app)
    service.open_path(path)


def _draft_selected(M, app):
    row = _selected_one(M, app)
    if row:
        M.create_issued_offer_outlook_draft(app, int(row["id"]))


def _change_status(M, app):
    row = _selected_one(M, app)
    if not row:
        return
    dialog = M.tk.Toplevel(app)
    dialog.title("Změnit stav vydané nabídky")
    dialog.transient(app)
    dialog.grab_set()
    frame = M.ttk.Frame(dialog, padding=16)
    frame.pack(fill="both", expand=True)
    value = M.tk.StringVar(value=str(row.get("status") or "Rozpracováno"))
    M.ttk.Label(frame, text="Nový stav").pack(anchor="w")
    _combobox(M, frame, value, list(service.STATUSES)).pack(fill="x", pady=(5, 12))

    def save():
        service.set_status(M, int(row["id"]), value.get())
        dialog.destroy()
        refresh_issued_offers(M, app)

    buttons = M.ttk.Frame(frame)
    buttons.pack(fill="x")
    M.ttk.Button(buttons, text="Zrušit", command=dialog.destroy).pack(side="right")
    M.ttk.Button(buttons, text="Uložit", style="Accent.TButton", command=save).pack(side="right", padx=(0, 5))
    try:
        M.center_dialog(dialog, app)
    except Exception:
        pass


def _toggle_archive(M, app):
    rows = _selected_rows(app)
    if not rows:
        return M.messagebox.showinfo("Vydané nabídky", "Vyberte jednu nebo více nabídek.", parent=app)
    archive = not all(bool(row.get("archived")) for row in rows)
    for row in rows:
        service.set_archived(M, int(row["id"]), archive)
    refresh_issued_offers(M, app)


def _delete_selected(M, app):
    row = _selected_one(M, app)
    if not row:
        return
    if not M.messagebox.askyesno(
        "Vydané nabídky",
        "Odstranit rozpracovaný koncept z databáze? Tuto operaci nelze použít na nabídku s vytvořeným PDF.",
        parent=app,
    ):
        return
    try:
        service.delete_draft(M, int(row["id"]))
        refresh_issued_offers(M, app)
    except Exception as exc:
        M.messagebox.showwarning("Vydané nabídky", str(exc), parent=app)


def _quick_view(M, app, target):
    app.issued_offer_status.set(target)
    app.issued_offer_page = 0
    _schedule_refresh(M, app, 0)


def _clear_filters(M, app):
    app.issued_offer_q.set("")
    app.issued_offer_company.set("")
    app.issued_offer_project.set("")
    app.issued_offer_status.set("Aktivní")
    app.issued_offer_page = 0
    _schedule_refresh(M, app, 0)


def _change_page(M, app, delta):
    app.issued_offer_page = max(0, int(app.issued_offer_page or 0) + int(delta))
    refresh_issued_offers(M, app)


def _schedule_refresh(M, app, delay=160):
    previous = getattr(app, "_issued_offer_refresh_after", None)
    if previous:
        try:
            app.after_cancel(previous)
        except Exception:
            pass
    app.issued_offer_page = 0
    app._issued_offer_refresh_after = app.after(delay, lambda: refresh_issued_offers(M, app))


def install(M):
    M.App.build_issued_offers = lambda self: build_issued_offers(M, self)
    M.App.refresh_issued_offers = lambda self: refresh_issued_offers(M, self)


__all__ = ["build_issued_offers", "refresh_issued_offers", "install"]
