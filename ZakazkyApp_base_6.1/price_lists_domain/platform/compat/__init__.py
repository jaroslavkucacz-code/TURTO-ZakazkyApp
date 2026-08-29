"""Last-mile compatibility and lightweight-query guards.

This package intentionally shadows the sibling ``compat.py`` module.  It is loaded
by the workset wrapper and applied after the finalization layer.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import categories, finalize


def _install_classifier(M) -> None:
    def classify_text(module_or_value, value=None):
        actual = module_or_value if value is None else value
        hay = finalize._norm(actual)
        if not hay:
            return None
        rules, fallback = finalize._load_rules(M)
        for category_id, needles in rules:
            if any(needle in hay for needle in needles):
                return category_id
        return fallback

    categories.classify_text = classify_text


def _patch_light_evidence(M) -> None:
    from ...common import UPDATE_MODES
    from ...storage import _list_status
    from .. import price_page

    def refresh_evidence(app):
        tree = app.price_list_evidence_tree
        for iid in tree.get_children(""):
            tree.delete(iid)
        supplier_expr = "coalesce(nullif(trim(c.official_name),''),nullif(trim(p.supplier_name),''),'')"
        category_expr = "CASE WHEN cat.name IS NOT NULL THEN cat.name WHEN cats.category_count>1 THEN 'Více kategorií' WHEN cats.category_count=1 THEN cats.single_category ELSE 'Nezařazeno' END"
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
        today = date.today().isoformat()
        if status == "Aktuální":
            where += [
                "p.archived=0", "p.valid_from<=?", "(p.valid_to='' OR p.valid_to>=?)",
                "lower(coalesce(p.parse_status,'')) NOT LIKE '%ocr%'",
                "lower(coalesce(p.parse_status,'')) NOT LIKE '%kontrol%'",
                "lower(coalesce(p.parse_status,'')) NOT LIKE 'bez%'",
            ]
            params += [today, today]
        elif status == "Budoucí":
            where += ["p.archived=0", "p.valid_from>?"]
            params.append(today)
        elif status == "Po platnosti":
            where += ["p.archived=0", "trim(coalesce(p.valid_to,''))<>''", "p.valid_to<?"]
            params.append(today)
        elif status == "Ke kontrole":
            where.append(
                "(lower(coalesce(p.parse_status,'')) LIKE '%ocr%' OR "
                "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR "
                "lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
            )
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
            # Explicit columns are deliberate: ocr_text, ocr_layout_json, raw source
            # text and other potentially multi-megabyte payloads stay on disk.
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
            return refresh_evidence(app)
        for row in rows:
            tree.insert(
                "", "end", iid=f"pl{row['id']}",
                values=(
                    _list_status(row), M.fmt_date(row["valid_from"]), M.fmt_date(row["valid_to"]),
                    row["supplier"], row["category"], row["title"], row["product_group"], row["branch"],
                    UPDATE_MODES.get(row["update_mode"], row["update_mode"]), row["item_count"],
                    row["source_filename"], M.fmt_history_datetime(row["imported_at"]),
                ),
                tags=("status_cancel",) if int(row["archived"] or 0) else (),
            )
        start = offset + 1 if total else 0
        end = min(total, offset + len(rows))
        app.price_evidence_status_text.set(f"Zobrazeno {start}–{end} z {total} ceníků")
        app.price_evidence_prev.state(["!disabled"] if app.price_evidence_page > 0 else ["disabled"])
        app.price_evidence_next.state(["!disabled"] if end < total else ["disabled"])

    price_page._refresh_evidence = refresh_evidence


def _patch_notification_center(M) -> None:
    cls = getattr(M, "NotificationCenter", None)
    if cls is None:
        return

    def refresh(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        today = date.today()
        horizon = today.toordinal() + 3
        user = M.get_setting("active_user", "")
        with M.db() as con:
            tasks = con.execute(
                """SELECT t.id,t.due_date,t.text,a.name action_name FROM tasks t
                   JOIN actions a ON a.id=t.action_id
                   WHERE t.done=0 AND coalesce(t.archived,0)=0
                     AND (trim(coalesce(t.assigned_user,''))='' OR t.assigned_user=?)
                   ORDER BY t.due_date,t.id""",
                (user,),
            ).fetchall()
            actions = con.execute(
                """SELECT id,name,deadline FROM actions
                   WHERE coalesce(archived,0)=0 AND trim(coalesce(deadline,''))<>''
                     AND status NOT IN ('Hotovo','Zrušeno') ORDER BY deadline"""
            ).fetchall()
            requests = con.execute(
                """SELECT r.id,r.asked_date,r.item,a.name action_name,c.official_name company
                   FROM requests r LEFT JOIN actions a ON a.id=r.action_id
                   LEFT JOIN companies c ON c.id=r.company_id
                   WHERE coalesce(r.archived,0)=0 AND coalesce(r.no_response,0)=0
                     AND trim(coalesce(r.received_date,''))='' ORDER BY r.asked_date"""
            ).fetchall()
        for row in tasks:
            try:due = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
            except Exception:continue
            if due.toordinal() > horizon:
                continue
            tag = "over" if due < today else ("today" if due == today else "soon")
            when = "Po termínu" if due < today else ("Dnes" if due == today else M.fmt_date(row["due_date"]))
            self.tree.insert("", "end", iid=f"t{row['id']}", values=(when, "Úkol", row["action_name"], row["text"]), tags=(tag,))
        for row in actions:
            try:due = datetime.strptime(row["deadline"], "%Y-%m-%d").date()
            except Exception:continue
            if due.toordinal() > horizon:
                continue
            tag = "over" if due < today else ("today" if due == today else "soon")
            when = "Po termínu" if due < today else ("Dnes" if due == today else M.fmt_date(row["deadline"]))
            self.tree.insert("", "end", iid=f"a{row['id']}", values=(when, "Deadline Akce", row["name"], "Termín Akce"), tags=(tag,))
        for row in requests:
            try:asked = datetime.strptime(row["asked_date"], "%Y-%m-%d").date()
            except Exception:continue
            age = (today - asked).days
            if age < 3:
                continue
            self.tree.insert(
                "", "end", iid=f"r{row['id']}",
                values=(f"čeká {age} dní", "Poptávka", row["action_name"] or "—",
                        f"{row['company'] or '—'} · {row['item'] or '—'}"),
                tags=("wait",),
            )

    cls.refresh = refresh


def _patch_header_count(M) -> None:
    old_refresh = M.App.refresh_header

    def refresh_header(self, *args, **kwargs):
        result = old_refresh(self, *args, **kwargs)
        try:
            rows = self.action_rows()
            late = sum(self.late(row) for row in rows)
            with M.db() as con:
                waiting = con.execute(
                    """SELECT COUNT(*) FROM requests
                       WHERE coalesce(archived,0)=0 AND coalesce(no_response,0)=0
                         AND trim(coalesce(received_date,''))=''"""
                ).fetchone()[0]
                tasks_today = con.execute(
                    """SELECT COUNT(*) FROM tasks
                       WHERE done=0 AND coalesce(archived,0)=0 AND due_date<=?""",
                    (date.today().isoformat(),),
                ).fetchone()[0]
            self.today_summary.config(
                text=f"Dnes: {late} hořící termíny · {waiting} poptávek čeká na odpověď · {tasks_today} úkolů k řešení"
            )
        except Exception:
            pass
        return result

    M.App.refresh_header = refresh_header


def install(M) -> None:
    if getattr(M, "_turto_compat_v630", False):
        return
    _install_classifier(M)
    _patch_light_evidence(M)
    _patch_notification_center(M)
    _patch_header_count(M)
    M._turto_compat_v630 = True


__all__ = ["install"]
