"""Conditional bulk archive, reversible batches and per-page archive controls."""
from __future__ import annotations

from datetime import date, timedelta

from . import categories
from .database import maintain_database
from .fast_ocr import test_ocr


ARCHIVE_TYPES = (
    ("offers", "Přijaté cenové nabídky", "Nabídky s datem starším než mezní datum."),
    ("requests", "Uzavřené poptávky", "Obdržené nebo ukončené bez odezvy, starší než mezní datum."),
    ("actions", "Hotové / zrušené příležitosti", "Příležitosti ve stavu Hotovo nebo Zrušeno bez novější změny."),
    ("tasks", "Dokončené úkoly", "Dokončené úkoly starší než mezní datum."),
    ("pricelists", "Neaktuální ceníky", "Ceníky po platnosti nebo výslovně nahrazené novějším ceníkem."),
    ("projects", "Ukončené Akce", "Akce po termínu dokončení bez otevřené příležitosti."),
    ("documents", "Vydané dokumenty", "Budoucí vydané nabídky/objednávky v uzavřeném stavu."),
)


def _candidate_ids(M, kind: str, cutoff: str):
    with M.db() as con:
        if kind == "offers":
            rows = con.execute(
                """SELECT id FROM supplier_offers
                   WHERE coalesce(archived,0)=0 AND trim(coalesce(offer_date,''))<>'' AND offer_date<?""",
                (cutoff,),
            ).fetchall()
        elif kind == "requests":
            rows = con.execute(
                """SELECT id FROM requests
                   WHERE coalesce(archived,0)=0
                     AND (trim(coalesce(received_date,''))<>'' OR coalesce(no_response,0)=1)
                     AND coalesce(nullif(received_date,''),asked_date)<?""",
                (cutoff,),
            ).fetchall()
        elif kind == "actions":
            rows = con.execute(
                """SELECT id FROM actions
                   WHERE coalesce(archived,0)=0 AND status IN ('Hotovo','Zrušeno')
                     AND substr(coalesce(nullif(updated_at,''),nullif(created_date,''),'9999-12-31'),1,10)<?""",
                (cutoff,),
            ).fetchall()
        elif kind == "tasks":
            rows = con.execute(
                """SELECT id FROM tasks
                   WHERE coalesce(archived,0)=0 AND done=1
                     AND substr(coalesce(nullif(done_at,''),nullif(due_date,''),'9999-12-31'),1,10)<?""",
                (cutoff,),
            ).fetchall()
        elif kind == "pricelists":
            rows = con.execute(
                """SELECT p.id FROM price_lists p
                   WHERE coalesce(p.archived,0)=0 AND (
                     (trim(coalesce(p.valid_to,''))<>'' AND p.valid_to<?)
                     OR p.id IN (
                       SELECT newer.supersedes_id FROM price_lists newer
                       WHERE newer.supersedes_id IS NOT NULL
                         AND trim(coalesce(newer.valid_from,''))<>'' AND newer.valid_from<?
                     )
                   )""",
                (cutoff, cutoff),
            ).fetchall()
        elif kind == "projects":
            rows = con.execute(
                """SELECT p.id FROM projects p
                   WHERE p.active=1 AND trim(coalesce(p.end_date,''))<>'' AND p.end_date<?
                     AND NOT EXISTS (
                       SELECT 1 FROM actions a WHERE a.project_id=p.id
                         AND coalesce(a.archived,0)=0 AND a.status NOT IN ('Hotovo','Zrušeno')
                     )""",
                (cutoff,),
            ).fetchall()
        elif kind == "documents":
            rows = con.execute(
                """SELECT id FROM business_documents
                   WHERE coalesce(archived,0)=0
                     AND status IN ('Hotovo','Zrušeno','Odesláno','Uzavřeno')
                     AND trim(coalesce(issue_date,''))<>'' AND issue_date<?""",
                (cutoff,),
            ).fetchall()
        else:
            rows = []
    return [int(row[0]) for row in rows]


def _archive_rows(M, kind: str, ids: list[int], user: str, restore: bool = False) -> None:
    if not ids:
        return
    value = 0 if restore else 1
    with M.db() as con:
        if kind == "projects":
            con.executemany("UPDATE projects SET active=? WHERE id=?", [(1 if restore else 0, row_id) for row_id in ids])
            return
        table = {
            "offers": "supplier_offers", "requests": "requests", "actions": "actions",
            "tasks": "tasks", "pricelists": "price_lists", "documents": "business_documents",
        }[kind]
        columns = {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}
        if "archived_at" in columns and "archived_by" in columns:
            if restore:
                con.executemany(
                    f"UPDATE {table} SET archived=0,archived_at='',archived_by='' WHERE id=?",
                    [(row_id,) for row_id in ids],
                )
            else:
                con.executemany(
                    f"UPDATE {table} SET archived=1,archived_at=CURRENT_TIMESTAMP,archived_by=? WHERE id=?",
                    [(user, row_id) for row_id in ids],
                )
        else:
            con.executemany(f"UPDATE {table} SET archived=? WHERE id=?", [(value, row_id) for row_id in ids])


def open_bulk_archive_manager(M, app) -> None:
    dialog = M.tk.Toplevel(app)
    dialog.title("Správa archivu a výkonu")
    dialog.transient(app)
    dialog.grab_set()
    M.enable_dialog_maximize(dialog, 980, 680)
    outer = M.ttk.Frame(dialog, padding=16)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)
    outer.rowconfigure(4, weight=1)
    M.ttk.Label(outer, text="Hromadná archivace", font=("Calibri", 16, "bold")).grid(row=0, column=0, sticky="w")
    M.ttk.Label(
        outer,
        text="Archivace pouze skryje uzavřená data z každodenních přehledů. Nic se nemaže a poslední dávku lze obnovit.",
        style="PageSubtitle.TLabel",
    ).grid(row=1, column=0, sticky="w", pady=(2, 10))
    cutoff = M.tk.StringVar(value=(date.today() - timedelta(days=365)).isoformat())
    cutoff_frame = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
    cutoff_frame.grid(row=2, column=0, sticky="ew", pady=(0, 8))
    M.ttk.Label(cutoff_frame, text="Archivovat záznamy starší než:").pack(side="left")
    M.DatePicker(cutoff_frame, cutoff).pack(side="left", padx=8)
    M.ttk.Label(cutoff_frame, text="Nejdříve použijte Náhled.", style="PageSubtitle.TLabel").pack(side="left", padx=8)

    choices = {kind: M.tk.BooleanVar(value=(kind != "documents")) for kind, _, _ in ARCHIVE_TYPES}
    check_frame = M.ttk.Frame(outer, style="Panel.TFrame", padding=8)
    check_frame.grid(row=3, column=0, sticky="ew", pady=(0, 8))
    for index, (kind, label, description) in enumerate(ARCHIVE_TYPES):
        row = M.ttk.Frame(check_frame, style="Panel.TFrame")
        row.grid(row=index, column=0, sticky="ew", pady=2)
        M.ttk.Checkbutton(row, text=label, variable=choices[kind]).pack(side="left")
        M.ttk.Label(row, text=description, style="Panel.TLabel").pack(side="left", padx=(10, 0))

    tree = M.ttk.Treeview(outer, columns=("Typ", "Počet", "Podmínka"), show="headings")
    for col, width in (("Typ", 280), ("Počet", 90), ("Podmínka", 520)):
        tree.heading(col, text=col)
        tree.column(col, width=width, anchor="w")
    tree.grid(row=4, column=0, sticky="nsew")
    preview_data = {}

    def preview():
        value = M.parse_date(cutoff.get())
        if not value:
            return M.messagebox.showwarning("Archivace", "Vyplňte platné mezní datum.", parent=dialog)
        cutoff.set(value)
        preview_data.clear()
        for iid in tree.get_children(""):
            tree.delete(iid)
        for kind, label, description in ARCHIVE_TYPES:
            if not choices[kind].get():
                continue
            ids = _candidate_ids(M, kind, value)
            preview_data[kind] = ids
            tree.insert("", "end", iid=kind, values=(label, len(ids), description))

    def archive():
        if not preview_data:
            preview()
        selected = {kind: ids for kind, ids in preview_data.items() if choices[kind].get() and ids}
        total = sum(len(ids) for ids in selected.values())
        if not total:
            return M.messagebox.showinfo("Archivace", "Podle zadaných podmínek není co archivovat.", parent=dialog)
        if not M.messagebox.askyesno(
            "Potvrdit archivaci",
            f"Archivovat {total} záznamů?\n\nPřed změnou se vytvoří záloha databáze a poslední dávku lze obnovit.",
            parent=dialog,
        ):
            return
        backup = M.backup_now("before_bulk_archive")
        user = M.get_setting("active_user", "")
        with M.db() as con:
            batch_id = con.execute(
                """INSERT INTO archive_batches(created_by,cutoff_date,note,backup_path)
                   VALUES(?,?,?,?)""",
                (user, cutoff.get(), "Hromadná archivace", str(backup or "")),
            ).lastrowid
            for kind, ids in selected.items():
                old_state = "1" if kind == "projects" else "0"
                new_state = "0" if kind == "projects" else "1"
                con.executemany(
                    """INSERT INTO archive_batch_items(batch_id,table_name,row_id,old_state,new_state)
                       VALUES(?,?,?,?,?)""",
                    [(batch_id, kind, row_id, old_state, new_state) for row_id in ids],
                )
        for kind, ids in selected.items():
            _archive_rows(M, kind, ids, user, restore=False)
        dialog.destroy()
        app.refresh_all()
        M.messagebox.showinfo(
            "Archivace dokončena",
            f"Archivováno: {total} záznamů.\nBezpečnostní záloha:\n{backup}",
            parent=app,
        )

    def restore_last():
        with M.db() as con:
            batch = con.execute("SELECT * FROM archive_batches ORDER BY id DESC LIMIT 1").fetchone()
            rows = con.execute(
                "SELECT table_name,row_id FROM archive_batch_items WHERE batch_id=? ORDER BY id",
                (batch["id"],),
            ).fetchall() if batch else []
        if not batch or not rows:
            return M.messagebox.showinfo("Archivace", "Není k dispozici žádná archivní dávka.", parent=dialog)
        if not M.messagebox.askyesno(
            "Obnovit poslední dávku",
            f"Obnovit {len(rows)} záznamů z dávky {M.fmt_history_datetime(batch['created_at'])}?",
            parent=dialog,
        ):
            return
        grouped = {}
        for row in rows:
            grouped.setdefault(row["table_name"], []).append(int(row["row_id"]))
        user = M.get_setting("active_user", "")
        for kind, ids in grouped.items():
            _archive_rows(M, kind, ids, user, restore=True)
        with M.db() as con:
            con.execute("DELETE FROM archive_batches WHERE id=?", (batch["id"],))
        preview_data.clear()
        preview()
        app.refresh_all()
        M.messagebox.showinfo("Archivace", "Poslední archivní dávka byla obnovena.", parent=dialog)

    buttons = M.ttk.Frame(outer)
    buttons.grid(row=5, column=0, sticky="ew", pady=(10, 0))
    M.ttk.Button(buttons, text="Náhled", command=preview).pack(side="left")
    M.ttk.Button(buttons, text="Archivovat vybrané", style="Accent.TButton", command=archive).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Obnovit poslední dávku", command=restore_last).pack(side="left", padx=5)
    M.ttk.Button(buttons, text="Zavřít", command=dialog.destroy).pack(side="right")
    preview()


def _selected_ids(tree, prefix: str):
    result = []
    for iid in tree.selection():
        text = str(iid)
        if text.startswith(prefix):
            try:result.append(int(text[len(prefix):]))
            except Exception:pass
    return result


def _toggle_selected(M, app, tree, kind: str, prefix: str, restore: bool):
    ids = _selected_ids(tree, prefix)
    if not ids:
        return M.messagebox.showinfo("Archiv", "Vyberte jeden nebo více záznamů.", parent=app)
    _archive_rows(M, kind, ids, M.get_setting("active_user", ""), restore=restore)
    app.refresh_all()


def _add_page_archive_controls(M, App) -> None:
    old_build_offers = App.build_offers
    old_build_actions = App.build_actions
    old_build_tasks = App.build_tasks

    def build_offers(self, *args, **kwargs):
        result = old_build_offers(self, *args, **kwargs)
        try:
            page = self.tabs["offers"]
            bar = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 5))
            first = page.winfo_children()[0] if page.winfo_children() else None
            bar.pack(fill="x", before=first) if first else bar.pack(fill="x")
            self.offer_show_archived = M.tk.BooleanVar(value=False)
            M.ttk.Checkbutton(bar, text="Zobrazit archivované", variable=self.offer_show_archived, command=self.refresh_offers).pack(side="left")
            M.ttk.Button(bar, text="Archivovat vybrané", command=lambda: _toggle_selected(M, self, self.offer_tree, "offers", "o", False)).pack(side="right", padx=3)
            M.ttk.Button(bar, text="Obnovit vybrané", command=lambda: _toggle_selected(M, self, self.offer_tree, "offers", "o", True)).pack(side="right", padx=3)
        except Exception:
            pass
        return result

    def build_actions(self, *args, **kwargs):
        result = old_build_actions(self, *args, **kwargs)
        try:
            page = self.tabs["actions"]
            bar = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 5))
            first = page.winfo_children()[0] if page.winfo_children() else None
            bar.pack(fill="x", before=first) if first else bar.pack(fill="x")
            self.action_show_archived = M.tk.BooleanVar(value=False)
            M.ttk.Checkbutton(bar, text="Zobrazit archivované", variable=self.action_show_archived, command=self.refresh_actions).pack(side="left")
            M.ttk.Button(bar, text="Archivovat vybrané", command=lambda: _toggle_selected(M, self, self.action_tree, "actions", "a", False)).pack(side="right", padx=3)
            M.ttk.Button(bar, text="Obnovit vybrané", command=lambda: _toggle_selected(M, self, self.action_tree, "actions", "a", True)).pack(side="right", padx=3)
        except Exception:
            pass
        return result

    def build_tasks(self, *args, **kwargs):
        result = old_build_tasks(self, *args, **kwargs)
        try:
            page = self.tabs["tasks"]
            bar = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 5))
            first = page.winfo_children()[0] if page.winfo_children() else None
            bar.pack(fill="x", before=first) if first else bar.pack(fill="x")
            self.task_show_archived = M.tk.BooleanVar(value=False)

            def changed():
                if self.task_show_archived.get() and hasattr(self, "task_show_done"):
                    self.task_show_done.set(True)
                self.refresh_tasks()

            M.ttk.Checkbutton(bar, text="Zobrazit archivované", variable=self.task_show_archived, command=changed).pack(side="left")
            M.ttk.Button(bar, text="Archivovat vybrané", command=lambda: _toggle_selected(M, self, self.task_tree, "tasks", "t", False)).pack(side="right", padx=3)
            M.ttk.Button(bar, text="Obnovit vybrané", command=lambda: _toggle_selected(M, self, self.task_tree, "tasks", "t", True)).pack(side="right", padx=3)
        except Exception:
            pass
        return result

    App.build_offers = build_offers
    App.build_actions = build_actions
    App.build_tasks = build_tasks


def _patch_refreshes(M, App) -> None:
    old_offer_refresh = App.refresh_offers
    old_task_refresh = App.refresh_tasks
    old_tag = App.tag

    def refresh_offers(self, *args, **kwargs):
        result = old_offer_refresh(self, *args, **kwargs)
        tree = getattr(self, "offer_tree", None)
        if tree is None:
            return result
        ids = _selected_ids_from_children(tree, "o")
        archived = set()
        if ids:
            marks = ",".join("?" for _ in ids)
            with M.db() as con:
                archived = {int(row[0]) for row in con.execute(
                    f"SELECT id FROM supplier_offers WHERE archived=1 AND id IN ({marks})", tuple(ids)
                ).fetchall()}
        show = bool(getattr(self, "offer_show_archived", M.tk.BooleanVar(value=False)).get()) if hasattr(self, "offer_show_archived") else False
        for iid in list(tree.get_children("")):
            offer_id = int(str(iid)[1:]) if str(iid).startswith("o") else None
            if offer_id in archived:
                if not show:
                    tree.delete(iid)
                else:
                    tree.item(iid, tags=("status_cancel",))
        return result

    def refresh_tasks(self, *args, **kwargs):
        result = old_task_refresh(self, *args, **kwargs)
        tree = getattr(self, "task_tree", None)
        if tree is None:
            return result
        ids = _selected_ids_from_children(tree, "t")
        archived = set()
        if ids:
            marks = ",".join("?" for _ in ids)
            with M.db() as con:
                archived = {int(row[0]) for row in con.execute(
                    f"SELECT id FROM tasks WHERE archived=1 AND id IN ({marks})", tuple(ids)
                ).fetchall()}
        show = bool(self.task_show_archived.get()) if hasattr(self, "task_show_archived") else False
        for iid in list(tree.get_children("")):
            task_id = int(str(iid)[1:]) if str(iid).startswith("t") else None
            if task_id in archived:
                if not show:
                    tree.delete(iid)
                else:
                    tree.item(iid, tags=("status_cancel",))
        return result

    def tag(self, row):
        try:
            if "archived" in row.keys() and int(row["archived"] or 0):
                return "status_cancel"
        except Exception:
            pass
        return old_tag(self, row)

    App.refresh_offers = refresh_offers
    App.refresh_tasks = refresh_tasks
    App.tag = tag


def _selected_ids_from_children(tree, prefix: str):
    result = []
    for iid in tree.get_children(""):
        text = str(iid)
        if text.startswith(prefix):
            try:result.append(int(text[len(prefix):]))
            except Exception:pass
    return result


def _patch_action_rows(M, App) -> None:
    def action_rows(self):
        show_archived = bool(self.action_show_archived.get()) if hasattr(self, "action_show_archived") else False
        with M.db() as con:
            return con.execute(
                """SELECT a.*,c.official_name company,s.name salesperson,
                    (SELECT COUNT(*) FROM requests r
                     LEFT JOIN companies rc ON rc.id=r.company_id
                     WHERE r.action_id=a.id
                       AND trim(coalesce(r.received_date,''))=''
                       AND coalesce(r.no_response,0)=0 AND coalesce(r.archived,0)=0
                       AND NOT (
                         lower(trim(coalesce(rc.short_name,'')))='mivo'
                         OR lower(trim(coalesce(rc.official_name,'')))='mivo'
                         OR lower(trim(coalesce(rc.official_name,''))) LIKE 'mivo %'
                       )) waiting
                    FROM actions a
                    LEFT JOIN companies c ON c.id=a.company_id
                    LEFT JOIN salespeople s ON s.id=a.salesperson_id
                    WHERE (?=1 OR coalesce(a.archived,0)=0)
                    ORDER BY CASE WHEN trim(coalesce(a.created_date,''))='' THEN 1 ELSE 0 END,
                             a.created_date DESC,a.id DESC""",
                (1 if show_archived else 0,),
            ).fetchall()

    App.action_rows = action_rows


def _patch_notifications(M, App) -> None:
    def notification_count(self):
        today = date.today()
        horizon = today.toordinal() + 3
        count = 0
        with M.db() as con:
            for row in con.execute("SELECT due_date FROM tasks WHERE done=0 AND coalesce(archived,0)=0"):
                try:due = M.datetime.strptime(row["due_date"], "%Y-%m-%d").date()
                except Exception:continue
                if due.toordinal() <= horizon:
                    count += 1
            for row in con.execute(
                """SELECT deadline FROM actions WHERE coalesce(archived,0)=0
                   AND trim(coalesce(deadline,''))<>'' AND status NOT IN ('Hotovo','Zrušeno')"""
            ):
                try:due = M.datetime.strptime(row["deadline"], "%Y-%m-%d").date()
                except Exception:continue
                if due.toordinal() <= horizon:
                    count += 1
            count += con.execute(
                """SELECT COUNT(*) FROM requests WHERE coalesce(archived,0)=0 AND coalesce(no_response,0)=0
                   AND trim(coalesce(received_date,''))='' AND asked_date<>''
                   AND julianday(?) - julianday(asked_date) >= 3""",
                (today.isoformat(),),
            ).fetchone()[0]
        return count

    App.notification_count = notification_count


def _patch_settings(M, App) -> None:
    old_settings = App.build_settings

    def build_settings(self, *args, **kwargs):
        result = old_settings(self, *args, **kwargs)
        try:
            page = self.tabs["settings"]
            card = M.ttk.Frame(page, style="Panel.TFrame", padding=18)
            card.pack(fill="x", pady=(10, 0))
            M.ttk.Label(card, text="Výkon, archiv a katalog", style="Panel.TLabel", font=("Calibri", 12, "bold")).grid(
                row=0, column=0, columnspan=4, sticky="w"
            )
            M.ttk.Button(card, text="Správa archivu a výkonu…", style="Accent.TButton", command=lambda: open_bulk_archive_manager(M, self)).grid(
                row=1, column=0, sticky="w", pady=6
            )
            M.ttk.Button(card, text="Kategorie produktů…", command=lambda: categories.manage_categories(M, self)).grid(
                row=1, column=1, sticky="w", padx=8, pady=6
            )
            M.ttk.Button(card, text="Otestovat OCR na PDF…", command=lambda: test_ocr(M, self)).grid(
                row=1, column=2, sticky="w", padx=8, pady=6
            )
            M.ttk.Button(card, text="Optimalizovat databázi", command=lambda: maintain_database(M, self)).grid(
                row=1, column=3, sticky="w", padx=8, pady=6
            )
            M.ttk.Label(
                card,
                text="Připraven je také indexovaný datový základ pro budoucí vydané nabídky a vydané objednávky.",
                style="Panel.TLabel",
            ).grid(row=2, column=0, columnspan=4, sticky="w")
        except Exception:
            pass
        return result

    App.build_settings = build_settings


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_archive_v630", False):
        return
    M.open_bulk_archive_manager = lambda app: open_bulk_archive_manager(M, app)
    _add_page_archive_controls(M, App)
    _patch_refreshes(M, App)
    _patch_action_rows(M, App)
    _patch_notifications(M, App)
    _patch_settings(M, App)
    App._turto_archive_v630 = True
