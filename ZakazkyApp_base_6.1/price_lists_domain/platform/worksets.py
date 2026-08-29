"""SQL-first refreshes for the fast-changing operational tables."""
from __future__ import annotations

from datetime import date, datetime


def _date_clause(field: str, mode: str, value: str):
    if not value:
        return "", []
    operator = {
        "Dříve než": "<", "Později než": ">", "Do data": "<=", "Od data": ">=", "Přesně": "=",
    }.get(mode, "=")
    return f" AND {field} {operator} ?", [value]


def _offer_values(M, tree, row):
    supplier = row["supplier"] or row["supplier_name"] or ""
    customer = row["customer"] or ""
    action = row["action_name"] or ""
    total = float(row["total_value"] or row["net_value"] or 0)
    value_map = {
        "Datum": M.fmt_date(row["offer_date"]), "Nabídka": M.fmt_date(row["offer_date"]),
        "Dodavatel": supplier, "Odběratel": customer, "Akce": action, "Příležitost": action,
        "Reference": row["reference"] or "", "Číslo nabídky": row["offer_number"] or "",
        "Číslo": row["offer_number"] or "", "Položek": row["item_count"],
        "Hodnota": f"{total:,.2f}".replace(",", " "), "Celkem": f"{total:,.2f}".replace(",", " "),
        "Měna": row["currency"] or "CZK", "Stav": "Archivováno" if row["archived"] else row["status"] or "",
        "Typ": "Ceník" if row["is_price_list"] else "Nabídka", "Soubor": row["source_pdf"] or "",
    }
    return tuple(value_map.get(str(col), "") for col in tree.cget("columns"))


def refresh_offers(M, app):
    tree = getattr(app, "offer_tree", None)
    if tree is None:
        return
    selected = set(tree.selection())
    for iid in tree.get_children(""):
        tree.delete(iid)
    show_archived = bool(app.offer_show_archived.get()) if hasattr(app, "offer_show_archived") else False
    supplier_filter = (getattr(app, "offer_supplier_filter", None).get() or "").strip() if hasattr(app, "offer_supplier_filter") else ""
    action_filter = (getattr(app, "offer_action_filter", None).get() or "").strip() if hasattr(app, "offer_action_filter") else ""
    query = (getattr(app, "offer_q", None).get() or "").strip() if hasattr(app, "offer_q") else ""
    type_filter = (getattr(app, "offer_type_filter", None).get() or "Vše") if hasattr(app, "offer_type_filter") else "Vše"
    where = ["(?=1 OR coalesce(o.archived,0)=0)"]
    params = [1 if show_archived else 0]
    supplier_expr = "coalesce(nullif(trim(s.official_name),''),nullif(trim(o.supplier_name),''),'')"
    action_expr = "CASE WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,ra.name,'') WHEN o.action_id IS NOT NULL THEN coalesce(op.name,oa.name,'') WHEN o.project_id IS NOT NULL THEN coalesce(pd.name,'') ELSE '' END"
    if supplier_filter:
        where.append(f"lower({supplier_expr}) LIKE ?")
        params.append("%" + supplier_filter.casefold() + "%")
    if action_filter:
        where.append(f"lower({action_expr}) LIKE ?")
        params.append("%" + action_filter.casefold() + "%")
    if query:
        where.append(
            f"lower({supplier_expr}||' '||coalesce(o.offer_number,'')||' '||coalesce(o.reference,'')||' '||"
            f"coalesce(o.note,'')||' '||{action_expr}) LIKE ?"
        )
        params.append("%" + query.casefold() + "%")
    if type_filter == "Ceníky":
        where.append("EXISTS(SELECT 1 FROM price_lists pl WHERE pl.source_offer_id=o.id)")
    elif type_filter == "Nabídky":
        where.append("NOT EXISTS(SELECT 1 FROM price_lists pl WHERE pl.source_offer_id=o.id)")
    with M.db() as con:
        rows = con.execute(
            f"""SELECT o.id,o.offer_date,o.supplier_name,o.offer_number,o.reference,o.total_value,
                       o.net_value,o.currency,o.status,o.source_pdf,o.archived,
                       {supplier_expr} supplier,c.official_name customer,{action_expr} action_name,
                       (SELECT COUNT(*) FROM supplier_offer_items i WHERE i.offer_id=o.id) item_count,
                       EXISTS(SELECT 1 FROM price_lists pl WHERE pl.source_offer_id=o.id) is_price_list
                FROM supplier_offers o
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN companies c ON c.id=o.customer_company_id
                LEFT JOIN projects pd ON pd.id=o.project_id
                LEFT JOIN requests rq ON rq.id=o.request_id
                LEFT JOIN actions ra ON ra.id=rq.action_id
                LEFT JOIN projects pr ON pr.id=ra.project_id
                LEFT JOIN actions oa ON oa.id=o.action_id
                LEFT JOIN projects op ON op.id=oa.project_id
                WHERE {' AND '.join(where)}
                ORDER BY CASE WHEN trim(coalesce(o.offer_date,''))='' THEN 1 ELSE 0 END,
                         o.offer_date DESC,o.id DESC LIMIT 3000""",
            params,
        ).fetchall()
    for row in rows:
        status = str(row["status"] or "").casefold()
        if row["archived"]:
            tag = "status_cancel"
        elif "hotov" in status or "přijat" in status:
            tag = "status_done"
        elif "zru" in status:
            tag = "status_cancel"
        else:
            tag = "status_offer"
        iid = f"o{row['id']}"
        tree.insert("", "end", iid=iid, values=_offer_values(M, tree, row), tags=(tag,))
        if iid in selected:
            tree.selection_add(iid)
    try:
        layout = getattr(M, "schedule_final_tree_layout", None)
        if callable(layout):layout(app)
    except Exception:pass


def _request_status(row):
    if int(row["archived"] or 0):
        return "Archivováno"
    if int(row["no_response"] or 0):
        return "Bez odezvy"
    return "Obdrženo" if row["received_date"] else "Čekám"


def _request_tag(row):
    if int(row["archived"] or 0):
        return "status_cancel"
    if row["received_date"] or int(row["no_response"] or 0):
        return "req_received"
    return "req_fresh"


def _request_where(M, app, mivo: bool):
    if mivo:
        status = app.mivo_status_filter.get().casefold().strip()
        user = app.mivo_user_filter.get().casefold().strip()
        action_filter = app.mivo_action_filter.get().casefold().strip()
        mode = app.mivo_date_mode.get()
        date_filter = M.parse_date(app.mivo_date_filter.get().strip()) if app.mivo_date_filter.get().strip() else ""
        show_archived = bool(app.mivo_show_archived.get())
        supplier_filter = ""
    else:
        status = app.req_status_filter.get().casefold().strip()
        user = app.req_user_filter.get().casefold().strip()
        action_filter = app.req_action_filter.get().casefold().strip()
        supplier_filter = app.req_at_filter.get().casefold().strip()
        mode = app.req_date_mode.get()
        date_filter = M.parse_date(app.req_date_filter.get().strip()) if app.req_date_filter.get().strip() else ""
        show_archived = bool(app.req_show_archived.get())
    mivo_sql = "(lower(trim(coalesce(c.short_name,'')))='mivo' OR lower(trim(coalesce(c.official_name,'')))='mivo' OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo %' OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo,%' OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo.%')"
    where = [mivo_sql if mivo else f"NOT {mivo_sql}"]
    params = []
    if not show_archived:
        where.append("coalesce(r.archived,0)=0")
    if status:
        if "archiv" in status:where.append("coalesce(r.archived,0)=1")
        elif "bez odezvy" in status:where.append("coalesce(r.archived,0)=0 AND coalesce(r.no_response,0)=1")
        elif "obdrž" in status or "obdrz" in status:where.append("coalesce(r.archived,0)=0 AND trim(coalesce(r.received_date,''))<>''")
        elif "ček" in status or "cek" in status:where.append("coalesce(r.archived,0)=0 AND coalesce(r.no_response,0)=0 AND trim(coalesce(r.received_date,''))=''")
    if user:
        where.append("lower(coalesce(r.assigned_user,'')) LIKE ?")
        params.append("%" + user + "%")
    if action_filter:
        where.append("lower(coalesce(a.name,'')) LIKE ?")
        params.append("%" + action_filter + "%")
    if supplier_filter:
        where.append("lower(coalesce(c.official_name,'')) LIKE ?")
        params.append("%" + supplier_filter + "%")
    clause, date_params = _date_clause("r.asked_date", mode, date_filter)
    if clause:
        where.append(clause.replace(" AND ", "", 1))
        params.extend(date_params)
    return where, params


def refresh_requests(M, app, mivo: bool = False):
    tree = app.mivo_tree if mivo else app.request_tree
    selected = set(tree.selection())
    for iid in tree.get_children(""):
        tree.delete(iid)
    where, params = _request_where(M, app, mivo)
    with M.db() as con:
        rows = con.execute(
            f"""SELECT r.id,r.asked_date,r.received_date,r.item,r.recipients_snapshot,r.assigned_user,
                       r.archived,r.no_response,c.official_name company,c.short_name company_short,
                       cf.official_name requested_for,a.name action_name
                FROM requests r
                LEFT JOIN companies c ON c.id=r.company_id
                LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                LEFT JOIN actions a ON a.id=r.action_id
                WHERE {' AND '.join(where)}
                ORDER BY CASE WHEN trim(coalesce(r.asked_date,''))='' THEN 1 ELSE 0 END,
                         r.asked_date DESC,r.id DESC LIMIT 5000""",
            params,
        ).fetchall()
    overdue = []
    for row in rows:
        state = _request_status(row)
        if mivo:
            # MIVO uses bold ageing only. Keep the stored date visually clean;
            # warning symbols belong to the regular Poptávky table, not here.
            values = (
                state,row["assigned_user"] or "",M.fmt_date(row["asked_date"]),
                M.fmt_date(row["received_date"]),row["requested_for"] or "",row["action_name"] or "",
                row["item"] or "",row["recipients_snapshot"] or "",
            )
        else:
            values = (
                state,row["assigned_user"] or "",M.request_wait_date(row["asked_date"],row["received_date"]),
                M.fmt_date(row["received_date"]),row["requested_for"] or "",row["company"] or "",
                row["action_name"] or "",row["item"] or "",row["recipients_snapshot"] or "",
            )
        iid = f"r{row['id']}"
        tree.insert("", "end", iid=iid, values=values, tags=(_request_tag(row),))
        if iid in selected:tree.selection_add(iid)
        overdue.append((iid, M.request_is_overdue(row["asked_date"], row["received_date"]) and not int(row["no_response"] or 0)))
    if not mivo:
        app.after_idle(lambda rows=overdue, target=tree: app._refresh_request_date_highlights(target, rows))
    try:app.reapply_tree_sort(tree)
    except Exception:pass


def refresh_tasks(M, app):
    tree = getattr(app, "task_tree", None)
    if tree is None:return
    selected = set(tree.selection())
    for iid in tree.get_children(""):tree.delete(iid)
    show_done = bool(app.task_show_done.get()) if hasattr(app, "task_show_done") else False
    show_archived = bool(app.task_show_archived.get()) if hasattr(app, "task_show_archived") else False
    query = app.task_q.get().casefold().strip() if hasattr(app, "task_q") else ""
    user = app.task_user_filter.get() if hasattr(app, "task_user_filter") else "Všichni"
    where = ["(?=1 OR t.done=0)", "(?=1 OR coalesce(t.archived,0)=0)"]
    params = [1 if show_done else 0, 1 if show_archived else 0]
    if query:
        where.append("lower(coalesce(a.name,'')||' '||coalesce(t.text,'')||' '||coalesce(t.note,'')||' '||coalesce(t.assigned_user,'')) LIKE ?")
        params.append("%" + query + "%")
    if user and user != "Všichni":
        where.append("lower(coalesce(t.assigned_user,'')) LIKE ?")
        params.append("%" + user.casefold() + "%")
    with M.db() as con:
        rows = con.execute(
            f"""SELECT t.id,t.due_date,t.text,t.created_by,t.done_by,t.assigned_user,t.done,t.archived,a.name action_name
                FROM tasks t JOIN actions a ON a.id=t.action_id
                WHERE {' AND '.join(where)} ORDER BY t.archived,t.done,t.due_date,t.id LIMIT 5000""",
            params,
        ).fetchall()
    today = date.today()
    for row in rows:
        if row["archived"]:
            state, tag = "Archivováno", "status_cancel"
        elif row["done"]:
            state, tag = "Hotovo", "status_done"
        else:
            try:due = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
            except Exception:due = today
            diff = (due - today).days
            if diff < 0:state, tag = "Po termínu", "status_late"
            elif diff == 0:state, tag = "Dnes", "status_soon"
            elif diff <= 3:state, tag = "Brzy", "status_wait"
            else:state, tag = "Čeká", "status_active"
        iid = f"t{row['id']}"
        tree.insert("", "end", iid=iid, values=(
            state,row["assigned_user"] or "",M.fmt_date(row["due_date"]),row["action_name"] or "",
            row["text"] or "",row["created_by"] or "",row["done_by"] or "",
        ), tags=(tag,))
        if iid in selected:tree.selection_add(iid)


def install(M) -> None:
    App = M.App
    if getattr(App, "_turto_worksets_v630", False):return
    App.refresh_offers = lambda self: refresh_offers(M, self)
    App.refresh_requests = lambda self: refresh_requests(M, self, False)
    App.refresh_mivo_requests = lambda self: refresh_requests(M, self, True)
    App.refresh_tasks = lambda self: refresh_tasks(M, self)
    App._turto_worksets_v630 = True
