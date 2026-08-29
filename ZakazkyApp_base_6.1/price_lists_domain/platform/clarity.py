"""MIVO ageing and price-list clarity refinements for TURTO CRM 6.3.32.

The module is intentionally additive.  It repairs the one-argument Evidence
refresh left by the lightweight compatibility layer, makes 7+ day MIVO waits
bold again, and adds lightweight status/validity context to Ceníky without
loading OCR payloads or images.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

MIVO_OVERDUE_DAYS = 7
PRICE_EXPIRING_DAYS = 30

_PRICE_TAGS = {
    "price_current": {"background": "#d2e8d7", "foreground": "#24502d"},
    "price_future": {"background": "#d8e8f5", "foreground": "#17324a"},
    "price_expiring": {"background": "#f5e6b5", "foreground": "#5b4308"},
    "price_review": {"background": "#f1d1aa", "foreground": "#65350a"},
    "price_expired": {"background": "#edc3c3", "foreground": "#6c2020"},
    "price_archived": {"background": "#d8dde1", "foreground": "#485159"},
}


def _exists(widget) -> bool:
    try:
        return widget is not None and bool(widget.winfo_exists())
    except Exception:
        return widget is not None


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _days_text(value: int) -> str:
    value = abs(int(value))
    if value == 1:
        return "1 den"
    if 2 <= value <= 4:
        return f"{value} dny"
    return f"{value} dní"


def _needs_review(value) -> bool:
    text = str(value or "").strip().casefold()
    return "ocr" in text or "kontrol" in text or text.startswith("bez")


def _validity_text(M, valid_from, valid_to, today=None) -> str:
    today = today or date.today()
    starts = _parse_iso(valid_from)
    ends = _parse_iso(valid_to)
    if starts and starts > today:
        delta = (starts - today).days
        return f"začíná za {_days_text(delta)} · {M.fmt_date(starts.isoformat())}"
    if ends:
        delta = (ends - today).days
        if delta < 0:
            return f"{_days_text(-delta)} po platnosti"
        if delta == 0:
            return "končí dnes"
        if delta <= PRICE_EXPIRING_DAYS:
            return f"končí za {_days_text(delta)}"
        return f"do {M.fmt_date(ends.isoformat())}"
    return "bez omezení"


def _price_status(row, today=None) -> str:
    today = today or date.today()
    if int(row["archived"] or 0):
        return "price_archived"
    if _needs_review(row["parse_status"]):
        return "price_review"
    starts = _parse_iso(row["valid_from"])
    ends = _parse_iso(row["valid_to"])
    if starts and starts > today:
        return "price_future"
    if ends and ends < today:
        return "price_expired"
    if ends and 0 <= (ends - today).days <= PRICE_EXPIRING_DAYS:
        return "price_expiring"
    return "price_current"


def _append_column(app, tree, name: str, width: int) -> None:
    if not _exists(tree):
        return
    columns = list(tree["columns"])
    if name in columns:
        return
    tree.configure(columns=tuple(columns + [name]))
    sorter = getattr(app, "sort_tree", None)
    if callable(sorter):
        tree.heading(name, text=name, command=lambda col=name, target=tree: sorter(target, col))
    else:
        tree.heading(name, text=name)
    tree.column(name, width=width, minwidth=90, anchor="w", stretch=False)


def _walk(widget):
    try:
        children = list(widget.winfo_children())
    except Exception:
        children = []
    for child in children:
        yield child
        yield from _walk(child)


def _extend_evidence_statuses(app) -> None:
    variable = getattr(app, "price_evidence_status", None)
    notebook = getattr(app, "price_notebook", None)
    if variable is None or not _exists(notebook):
        return
    wanted = (
        "Všechny", "Aktuální", "Končí do 30 dnů", "Budoucí",
        "Po platnosti", "Ke kontrole", "Archivované",
    )
    target_name = str(variable)
    for widget in _walk(notebook):
        try:
            if widget.winfo_class() == "TCombobox" and str(widget.cget("textvariable")) == target_name:
                widget.configure(values=wanted)
                app.price_evidence_status_box = widget
                return
        except Exception:
            continue


def _configure_price_tags(tree) -> None:
    if not _exists(tree):
        return
    for name, options in _PRICE_TAGS.items():
        try:
            tree.tag_configure(name, **options)
        except Exception:
            pass


def _quick_evidence(M, app, status: str) -> None:
    from . import price_page

    if not hasattr(app, "price_notebook"):
        return
    try:
        app.price_notebook.select(1)
        app.price_evidence_page = 0
        app.price_evidence_status.set(status)
        price_page.schedule_refresh(M, app, 0)
    except Exception:
        pass


def _install_price_overview(M, app) -> None:
    if getattr(app, "_price_clarity_ui_ready", False):
        return
    notebook = getattr(app, "price_notebook", None)
    page = getattr(app, "tabs", {}).get("pricelists")
    if not _exists(notebook) or not _exists(page):
        return

    _append_column(app, app.price_current_tree, "Platnost zdroje", 175)
    _append_column(app, app.price_list_evidence_tree, "Platnost", 165)
    _configure_price_tags(app.price_current_tree)
    _configure_price_tags(app.price_list_evidence_tree)
    _extend_evidence_statuses(app)

    panel = M.ttk.Frame(page, style="Panel.TFrame", padding=(10, 8))
    try:
        panel.pack(fill="x", pady=(0, 6), before=notebook)
    except Exception:
        panel.pack(fill="x", pady=(0, 6))
    app.price_clarity_panel = panel

    metrics = M.ttk.Frame(panel, style="Panel.TFrame")
    metrics.pack(fill="x")
    definitions = (
        ("Platných položek", "items"),
        ("Aktivní ceníky", "active"),
        ("Ke kontrole", "review"),
        ("Končí do 30 dnů", "expiring"),
        ("Po platnosti", "expired"),
    )
    app.price_clarity_metrics = {}
    for index, (label, key) in enumerate(definitions):
        card = M.ttk.Frame(metrics, style="Panel.TFrame", padding=(7, 0))
        card.grid(row=0, column=index, sticky="ew")
        metrics.columnconfigure(index, weight=1)
        variable = M.tk.StringVar(value="—")
        app.price_clarity_metrics[key] = variable
        M.ttk.Label(card, text=label, style="PageSubtitle.TLabel").pack(anchor="w")
        M.ttk.Label(
            card, textvariable=variable, style="Panel.TLabel", font=("Calibri", 14, "bold")
        ).pack(anchor="w")

    quick = M.ttk.Frame(panel, style="Panel.TFrame")
    quick.pack(fill="x", pady=(7, 0))
    M.ttk.Label(
        quick,
        text="Barvy: zelená aktuální · žlutá brzy končí · oranžová ke kontrole · červená po platnosti",
        style="PageSubtitle.TLabel",
    ).pack(side="left")
    for label, status in reversed((
        ("Aktuální", "Aktuální"),
        ("Končí do 30 dnů", "Končí do 30 dnů"),
        ("Ke kontrole", "Ke kontrole"),
        ("Po platnosti", "Po platnosti"),
    )):
        M.ttk.Button(
            quick, text=label, command=lambda value=status: _quick_evidence(M, app, value)
        ).pack(side="right", padx=(5, 0))

    app._price_clarity_ui_ready = True


def _summary_values(M):
    today = date.today().isoformat()
    soon = (date.today() + timedelta(days=PRICE_EXPIRING_DAYS)).isoformat()
    review = (
        "(lower(coalesce(parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(parse_status,'')) LIKE 'bez%')"
    )
    with M.db() as con:
        items = con.execute(
            """SELECT COUNT(*) FROM price_list_items i
               JOIN price_lists p ON p.id=i.price_list_id
               WHERE i.active=1 AND p.archived=0
                 AND trim(coalesce(p.valid_from,''))<>'' AND p.valid_from<=?
                 AND (trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)""",
            (today, today),
        ).fetchone()[0]
        active = con.execute(
            f"""SELECT COUNT(*) FROM price_lists
                WHERE archived=0 AND trim(coalesce(valid_from,''))<>'' AND valid_from<=?
                  AND (trim(coalesce(valid_to,''))='' OR valid_to>=?) AND NOT {review}""",
            (today, today),
        ).fetchone()[0]
        needs_review = con.execute(
            f"SELECT COUNT(*) FROM price_lists WHERE archived=0 AND {review}"
        ).fetchone()[0]
        expiring = con.execute(
            f"""SELECT COUNT(*) FROM price_lists
                WHERE archived=0 AND trim(coalesce(valid_from,''))<>'' AND valid_from<=?
                  AND trim(coalesce(valid_to,''))<>'' AND valid_to>=? AND valid_to<=?
                  AND NOT {review}""",
            (today, today, soon),
        ).fetchone()[0]
        expired = con.execute(
            """SELECT COUNT(*) FROM price_lists
               WHERE archived=0 AND trim(coalesce(valid_to,''))<>'' AND valid_to<?""",
            (today,),
        ).fetchone()[0]
    return {
        "items": int(items), "active": int(active), "review": int(needs_review),
        "expiring": int(expiring), "expired": int(expired),
    }


def _refresh_price_summary(M, app, force: bool = False) -> None:
    variables = getattr(app, "price_clarity_metrics", None)
    if not variables:
        return
    now = time.monotonic()
    cached = getattr(app, "_price_clarity_summary_cache", None)
    if not force and cached and now - cached[0] < 5:
        values = cached[1]
    else:
        values = _summary_values(M)
        app._price_clarity_summary_cache = (now, values)
    for key, variable in variables.items():
        try:
            variable.set(f"{int(values.get(key, 0)):,}".replace(",", " "))
        except Exception:
            variable.set("—")


def _refresh_evidence(M, app) -> None:
    """Lightweight evidence refresh with the correct public ``(M, app)`` signature."""
    from ..common import UPDATE_MODES
    from ..storage import _list_status
    from . import categories

    tree = app.price_list_evidence_tree
    for iid in tree.get_children(""):
        tree.delete(iid)
    supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
    category_expr = (
        "CASE WHEN cat.name IS NOT NULL THEN cat.name "
        "WHEN cats.category_count>1 THEN 'Více kategorií' "
        "WHEN cats.category_count=1 THEN cats.single_category ELSE 'Nezařazeno' END"
    )
    where = []
    params = []
    status = app.price_evidence_status.get()
    if status != "Archivované" and not app.price_list_show_archived.get():
        where.append("p.archived=0")
    query = app.price_evidence_q.get().strip().casefold()
    if query:
        where.append(
            f"lower({supplier_expr}||' '||coalesce(p.title,'')||' '||coalesce(p.product_group,'')||' '||"
            "coalesce(p.branch,'')||' '||coalesce(p.source_filename,'')) LIKE ?"
        )
        params.append("%" + query + "%")
    supplier = app.price_evidence_supplier.get().strip()
    if supplier:
        where.append(f"lower({supplier_expr}) LIKE ?")
        params.append("%" + supplier.casefold() + "%")
    category = app.price_evidence_category.get().strip()
    if category and category != "Všechny":
        category_id = categories.category_id_by_name(M, category) or -1
        where.append(
            "(p.category_id=? OR EXISTS(SELECT 1 FROM price_list_items ix "
            "WHERE ix.price_list_id=p.id AND ix.active=1 AND ix.category_id=?))"
        )
        params.extend((category_id, category_id))

    today_date = date.today()
    today = today_date.isoformat()
    soon = (today_date + timedelta(days=PRICE_EXPIRING_DAYS)).isoformat()
    review = (
        "(lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
        "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
    )
    if status == "Aktuální":
        where += [
            "p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from<=?",
            "(trim(coalesce(p.valid_to,''))='' OR p.valid_to>=?)", f"NOT {review}",
        ]
        params += [today, today]
    elif status == "Končí do 30 dnů":
        where += [
            "p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from<=?",
            "trim(coalesce(p.valid_to,''))<>''", "p.valid_to>=?", "p.valid_to<=?",
            f"NOT {review}",
        ]
        params += [today, today, soon]
    elif status == "Budoucí":
        where += ["p.archived=0", "trim(coalesce(p.valid_from,''))<>''", "p.valid_from>?"]
        params.append(today)
    elif status == "Po platnosti":
        where += ["p.archived=0", "trim(coalesce(p.valid_to,''))<>''", "p.valid_to<?"]
        params.append(today)
    elif status == "Ke kontrole":
        where.append(review)
    elif status == "Archivované":
        where.append("p.archived=1")
    where_sql = " AND ".join(where) if where else "1=1"
    offset = max(0, int(app.price_evidence_page or 0)) * app.price_evidence_page_size
    joins = """
        LEFT JOIN companies c ON c.id=p.supplier_company_id
        LEFT JOIN product_categories cat ON cat.id=p.category_id
        LEFT JOIN (
          SELECT i.price_list_id,COUNT(*) item_count,
                 COUNT(DISTINCT i.category_id) category_count,MIN(pc.name) single_category
          FROM price_list_items i LEFT JOIN product_categories pc ON pc.id=i.category_id
          WHERE i.active=1 GROUP BY i.price_list_id
        ) cats ON cats.price_list_id=p.id
    """
    with M.db() as con:
        total = con.execute(
            f"SELECT COUNT(*) FROM price_lists p {joins} WHERE {where_sql}", params
        ).fetchone()[0]
        rows = con.execute(
            f"""SELECT p.id,p.title,p.valid_from,p.valid_to,p.product_group,p.branch,
                       p.update_mode,p.archived,p.source_filename,p.imported_at,p.parse_status,
                       {supplier_expr} supplier,{category_expr} category,
                       coalesce(cats.item_count,0) item_count
                FROM price_lists p {joins}
                WHERE {where_sql}
                ORDER BY CASE WHEN trim(coalesce(p.valid_from,''))='' THEN 1 ELSE 0 END,
                         p.valid_from DESC,p.id DESC LIMIT ? OFFSET ?""",
            params + [app.price_evidence_page_size, offset],
        ).fetchall()
    if total and offset >= total and app.price_evidence_page:
        app.price_evidence_page = 0
        return _refresh_evidence(M, app)

    has_validity = "Platnost" in tuple(tree["columns"])
    for row in rows:
        values = (
            _list_status(row), M.fmt_date(row["valid_from"]), M.fmt_date(row["valid_to"]),
            row["supplier"], row["category"], row["title"], row["product_group"], row["branch"],
            UPDATE_MODES.get(row["update_mode"], row["update_mode"]), row["item_count"],
            row["source_filename"], M.fmt_history_datetime(row["imported_at"]),
        )
        if has_validity:
            values += (_validity_text(M, row["valid_from"], row["valid_to"], today_date),)
        tree.insert(
            "", "end", iid=f"pl{row['id']}", values=values,
            tags=(_price_status(row, today_date),),
        )
    start = offset + 1 if total else 0
    end = min(total, offset + len(rows))
    suffix = f" · filtr: {status}" if status and status != "Všechny" else ""
    app.price_evidence_status_text.set(f"Zobrazeno {start}–{end} z {total} ceníků{suffix}")
    app.price_evidence_prev.state(["!disabled"] if app.price_evidence_page > 0 else ["disabled"])
    app.price_evidence_next.state(["!disabled"] if end < total else ["disabled"])
    _refresh_price_summary(M, app)


def _decorate_current_prices(M, app) -> None:
    tree = getattr(app, "price_current_tree", None)
    rows = getattr(app, "price_current_rows", {})
    if not _exists(tree) or "Platnost zdroje" not in tuple(tree["columns"]) or not rows:
        return
    list_ids = sorted({int(info["price_list_id"]) for info in rows.values() if info.get("price_list_id")})
    if not list_ids:
        return
    marks = ",".join("?" for _ in list_ids)
    with M.db() as con:
        metadata = {
            int(row["id"]): row for row in con.execute(
                f"SELECT id,valid_from,valid_to,parse_status,archived FROM price_lists WHERE id IN ({marks})",
                tuple(list_ids),
            ).fetchall()
        }
    today = date.today()
    own_tags = set(_PRICE_TAGS)
    for iid, info in rows.items():
        if not tree.exists(iid):
            continue
        row = metadata.get(int(info["price_list_id"]))
        if row is None:
            continue
        tree.set(iid, "Platnost zdroje", _validity_text(M, row["valid_from"], row["valid_to"], today))
        tags = [tag for tag in tree.item(iid, "tags") if tag not in own_tags]
        status = _price_status(row, today)
        if status != "price_current":
            tags.append(status)
        tree.item(iid, tags=tuple(tags))


def _patch_prices(M) -> None:
    from . import price_page

    if getattr(M, "_turto_price_clarity_v6332", False):
        return
    original_build = price_page.build_price_lists
    original_current = price_page._refresh_current

    def build_price_lists(module, app):
        result = original_build(module, app)
        _install_price_overview(M, app)
        # The page can still be hidden while App.build() is running.  The normal
        # lazy navigation owner performs the first full refresh when it is shown.
        return result

    def refresh_current(module, app, allow_fts_retry=True):
        result = original_current(module, app, allow_fts_retry)
        _decorate_current_prices(M, app)
        _refresh_price_summary(M, app)
        return result

    price_page.build_price_lists = build_price_lists
    price_page._refresh_current = refresh_current
    price_page._refresh_evidence = _refresh_evidence
    M.App.build_price_lists = lambda self: price_page.build_price_lists(M, self)
    M._turto_price_clarity_v6332 = True


def _apply_mivo_ageing(M, app) -> None:
    tree = getattr(app, "mivo_tree", None)
    if not _exists(tree):
        return
    iids = [iid for iid in tree.get_children("") if str(iid).startswith("r")]
    if not iids:
        variable = getattr(app, "mivo_age_summary", None)
        if variable is not None:
            variable.set("Zobrazeno: 0")
        return
    ids = [int(str(iid)[1:]) for iid in iids]
    marks = ",".join("?" for _ in ids)
    with M.db() as con:
        data = {
            int(row["id"]): row for row in con.execute(
                f"SELECT id,asked_date,received_date,no_response,archived FROM requests WHERE id IN ({marks})",
                tuple(ids),
            ).fetchall()
        }
    today = date.today()
    waiting = 0
    overdue = 0
    for iid in iids:
        row = data.get(int(str(iid)[1:]))
        if row is None or not tree.exists(iid):
            continue
        is_waiting = (
            not int(row["archived"] or 0) and not int(row["no_response"] or 0)
            and not str(row["received_date"] or "").strip()
        )
        age = None
        asked = _parse_iso(row["asked_date"])
        if is_waiting:
            waiting += 1
            age = (today - asked).days if asked else None
        is_overdue = age is not None and age >= MIVO_OVERDUE_DAYS
        if is_overdue:
            overdue += 1
        tags = [tag for tag in tree.item(iid, "tags") if tag != "mivo_wait_7"]
        if is_overdue:
            tags.append("mivo_wait_7")
        tree.item(iid, tags=tuple(tags))
    variable = getattr(app, "mivo_age_summary", None)
    if variable is not None:
        variable.set(
            f"Zobrazeno: {len(iids)} · čeká na odpověď: {waiting} · "
            f"7+ dní: {overdue} (tučně)"
        )


def _patch_mivo(M) -> None:
    App = M.App
    if getattr(App, "_turto_mivo_ageing_v6332", False):
        return
    original_build = App.build_mivo
    original_refresh = App.refresh_mivo_requests

    def build_mivo(self, *args, **kwargs):
        result = original_build(self, *args, **kwargs)
        tree = getattr(self, "mivo_tree", None)
        if _exists(tree):
            tree.tag_configure("mivo_wait_7", font=("Calibri", 11, "bold"))
            if not hasattr(self, "mivo_age_summary"):
                self.mivo_age_summary = M.tk.StringVar(value="")
                label = M.ttk.Label(
                    self.tabs["mivo"], textvariable=self.mivo_age_summary,
                    style="PageSubtitle.TLabel",
                )
                try:
                    label.pack(fill="x", anchor="w", pady=(0, 4), before=tree.master)
                except Exception:
                    label.pack(fill="x", anchor="w", pady=(0, 4))
                self.mivo_age_summary_label = label
        return result

    def refresh_mivo_requests(self, *args, **kwargs):
        result = original_refresh(self, *args, **kwargs)
        try:
            self.after_idle(lambda: _apply_mivo_ageing(M, self))
        except Exception:
            _apply_mivo_ageing(M, self)
        return result

    App.build_mivo = build_mivo
    App.refresh_mivo_requests = refresh_mivo_requests
    App._turto_mivo_ageing_v6332 = True


def install(M) -> None:
    if getattr(M, "_turto_clarity_v6332", False):
        return
    _patch_prices(M)
    _patch_mivo(M)
    M._turto_clarity_v6332 = True


__all__ = [
    "install", "MIVO_OVERDUE_DAYS", "PRICE_EXPIRING_DAYS",
    "_days_text", "_needs_review", "_parse_iso",
]
