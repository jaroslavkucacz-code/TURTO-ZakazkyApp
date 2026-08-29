"""Final compatibility fixes and one-time data preparation for 6.3.30."""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from datetime import date

from . import categories

_CATEGORY_LOCK = threading.Lock()
_CATEGORY_CACHE = {"loaded": 0.0, "signature": None, "rules": [], "fallback": None}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _load_rules(M, force: bool = False):
    now = time.monotonic()
    if not force and _CATEGORY_CACHE["rules"] and now - float(_CATEGORY_CACHE["loaded"] or 0) < 10:
        return _CATEGORY_CACHE["rules"], _CATEGORY_CACHE["fallback"]
    with _CATEGORY_LOCK:
        now = time.monotonic()
        if not force and _CATEGORY_CACHE["rules"] and now - float(_CATEGORY_CACHE["loaded"] or 0) < 10:
            return _CATEGORY_CACHE["rules"], _CATEGORY_CACHE["fallback"]
        with M.db() as con:
            rows = con.execute(
                """SELECT id,name,keywords,sort_order,updated_at FROM product_categories
                   WHERE active=1 ORDER BY sort_order,name COLLATE CZECH"""
            ).fetchall()
        rules = []
        fallback = None
        signature = []
        for row in rows:
            cid = int(row["id"])
            name = str(row["name"] or "")
            signature.append((cid, name, str(row["keywords"] or ""), row["updated_at"]))
            if _norm(name) == "ostatni":
                fallback = cid
                continue
            needles = tuple(
                needle for needle in (_norm(part) for part in re.split(r"[|;\n]+", str(row["keywords"] or "")))
                if needle
            )
            if needles:
                rules.append((cid, needles))
        _CATEGORY_CACHE.update(loaded=now, signature=tuple(signature), rules=rules, fallback=fallback)
        return rules, fallback


def _install_fast_classifier(M) -> None:
    def classify_text(value: object):
        hay = _norm(value)
        if not hay:
            return None
        rules, fallback = _load_rules(M)
        for cid, needles in rules:
            if any(needle in hay for needle in needles):
                return cid
        return fallback

    categories.classify_text = classify_text
    M.invalidate_product_category_cache = lambda: _load_rules(M, True)


def _prepare_existing_data(M) -> None:
    """Classify existing lightweight rows once; no BLOB or OCR payload is read."""
    with M.db() as con:
        marker = con.execute("SELECT value FROM app_meta WHERE key='v630_catalog_migrated'").fetchone()
        if marker:
            return
        price_rows = con.execute(
            """SELECT id,price_list_id,product_code,supplier_item_code,item_key,name,description,
                      condition_text,dimensions
               FROM price_list_items WHERE category_id IS NULL ORDER BY id"""
        ).fetchall()
        offer_rows = con.execute(
            """SELECT id,product_code,item_key,original_name,details
               FROM supplier_offer_items WHERE category_id IS NULL ORDER BY id"""
        ).fetchall()

    price_updates = []
    for row in price_rows:
        value = " ".join(str(row[key] or "") for key in (
            "product_code", "supplier_item_code", "item_key", "name", "description", "condition_text", "dimensions"
        ))
        cid = categories.classify_text(value)
        if cid:
            price_updates.append((cid, int(row["id"])))
    offer_updates = []
    for row in offer_rows:
        value = " ".join(str(row[key] or "") for key in ("product_code", "item_key", "original_name", "details"))
        cid = categories.classify_text(value)
        if cid:
            offer_updates.append((cid, int(row["id"])))

    with M.db() as con:
        if price_updates:
            con.executemany("UPDATE price_list_items SET category_id=? WHERE id=?", price_updates)
        if offer_updates:
            con.executemany("UPDATE supplier_offer_items SET category_id=? WHERE id=?", offer_updates)
        # A list receives a header category only when all classified active rows agree.
        con.execute(
            """UPDATE price_lists SET category_id=(
                   SELECT MIN(i.category_id) FROM price_list_items i
                   WHERE i.price_list_id=price_lists.id AND i.active=1 AND i.category_id IS NOT NULL
               )
               WHERE category_id IS NULL
                 AND 1=(SELECT COUNT(DISTINCT i.category_id) FROM price_list_items i
                        WHERE i.price_list_id=price_lists.id AND i.active=1 AND i.category_id IS NOT NULL)"""
        )
        # Correct already imported PohlCon rules: the 50 % BV note belongs only to Kunex.
        con.execute(
            """UPDATE price_list_rules SET
                 scope_type='product_name_prefix',scope_value='Kunex',
                 rule_type='informational_surcharge_pct',
                 condition_text='Pouze výrobky Kunex v provedení BV (odolné bitumenům): příplatek 50 %, není-li u konkrétní položky uvedeno jinak.'
               WHERE abs(coalesce(percent_value,0)-50)<0.000001
                 AND lower(coalesce(condition_text,'')) LIKE '%bv%'
                 AND price_list_id IN (
                   SELECT p.id FROM price_lists p LEFT JOIN companies c ON c.id=p.supplier_company_id
                   WHERE lower(coalesce(c.official_name,p.supplier_name,'')) LIKE '%pohlcon%'
                 )"""
        )
        con.execute(
            "INSERT OR REPLACE INTO app_meta(key,value) VALUES('v630_catalog_migrated',CURRENT_TIMESTAMP)"
        )


def _patch_schema_migration(M) -> None:
    old_ensure = M.ensure_schema

    def ensure_schema():
        old_ensure()
        _prepare_existing_data(M)

    M.ensure_schema = ensure_schema


def _patch_evidence(M) -> None:
    from ..common import UPDATE_MODES
    from ..storage import _list_status
    from . import price_page

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
            cid = categories.category_id_by_name(M, category) or -1
            where.append(
                "(p.category_id=? OR EXISTS(SELECT 1 FROM price_list_items ix WHERE ix.price_list_id=p.id AND ix.active=1 AND ix.category_id=?))"
            )
            params.extend((cid, cid))
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
                "lower(coalesce(p.parse_status,'')) LIKE '%kontrol%' OR lower(coalesce(p.parse_status,'')) LIKE 'bez%')"
            )
        elif status == "Archivované":
            where.append("p.archived=1")
        where_sql = " AND ".join(where) if where else "1=1"
        offset = max(0, int(app.price_evidence_page or 0)) * app.price_evidence_page_size
        joins = f"""
            LEFT JOIN companies c ON c.id=p.supplier_company_id
            LEFT JOIN product_categories cat ON cat.id=p.category_id
            LEFT JOIN (
              SELECT i.price_list_id,COUNT(*) item_count,COUNT(DISTINCT i.category_id) category_count,
                     MIN(pc.name) single_category
              FROM price_list_items i LEFT JOIN product_categories pc ON pc.id=i.category_id
              WHERE i.active=1 GROUP BY i.price_list_id
            ) cats ON cats.price_list_id=p.id
        """
        with M.db() as con:
            total = con.execute(f"SELECT COUNT(*) FROM price_lists p {joins} WHERE {where_sql}", params).fetchone()[0]
            rows = con.execute(
                f"""SELECT p.*,{supplier_expr} supplier,{category_expr} category,
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
                    _list_status(row), M.fmt_date(row["valid_from"]), M.fmt_date(row["valid_to"]), row["supplier"],
                    row["category"], row["title"], row["product_group"], row["branch"],
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


def _patch_page_mapping(M) -> None:
    old_show = M.App.show_page

    def show_page(self, key, *args, **kwargs):
        if key == "pricelists":
            try:self.tabs[key].grid(row=0, column=0, sticky="nsew")
            except Exception:pass
        return old_show(self, key, *args, **kwargs)

    M.App.show_page = show_page


def _patch_safe_manual_archive(M) -> None:
    from . import archive
    old_archive_rows = archive._archive_rows

    def archive_rows(module, kind, ids, user, restore=False):
        safe_ids = list(ids)
        if not restore and safe_ids and kind in {"actions", "tasks"}:
            marks = ",".join("?" for _ in safe_ids)
            with M.db() as con:
                if kind == "actions":
                    safe_ids = [
                        int(row[0]) for row in con.execute(
                            f"SELECT id FROM actions WHERE id IN ({marks}) AND status IN ('Hotovo','Zrušeno')",
                            tuple(safe_ids),
                        ).fetchall()
                    ]
                else:
                    safe_ids = [
                        int(row[0]) for row in con.execute(
                            f"SELECT id FROM tasks WHERE id IN ({marks}) AND done=1", tuple(safe_ids)
                        ).fetchall()
                    ]
            if not safe_ids:
                return M.messagebox.showinfo(
                    "Archiv", "Aktivní příležitosti ani nedokončené úkoly nelze archivovat.", parent=None
                )
        return old_archive_rows(module, kind, safe_ids, user, restore)

    archive._archive_rows = archive_rows


def _patch_notifications(M) -> None:
    cls = getattr(M, "NotificationCenter", None)
    if cls is None or getattr(cls, "_turto_archive_filter_v630", False):
        return
    old_refresh = cls.refresh

    def refresh(self, *args, **kwargs):
        result = old_refresh(self, *args, **kwargs)
        request_ids = [int(str(iid)[1:]) for iid in self.tree.get_children("") if str(iid).startswith("r")]
        hidden = set()
        if request_ids:
            marks = ",".join("?" for _ in request_ids)
            with M.db() as con:
                hidden = {
                    int(row[0]) for row in con.execute(
                        f"SELECT id FROM requests WHERE id IN ({marks}) AND (coalesce(archived,0)=1 OR coalesce(no_response,0)=1)",
                        tuple(request_ids),
                    ).fetchall()
                }
        for iid in list(self.tree.get_children("")):
            if str(iid).startswith("r") and int(str(iid)[1:]) in hidden:
                self.tree.delete(iid)
        return result

    cls.refresh = refresh
    cls._turto_archive_filter_v630 = True


def install(M) -> None:
    if getattr(M, "_turto_finalize_v630", False):
        return
    _install_fast_classifier(M)
    _patch_schema_migration(M)
    _patch_evidence(M)
    _patch_page_mapping(M)
    _patch_safe_manual_archive(M)
    _patch_notifications(M)
    M._turto_finalize_v630 = True
