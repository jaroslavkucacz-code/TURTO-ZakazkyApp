"""TURTO CRM 7.7.0 final runtime policy.

This module is deliberately applied last.  It does not reimplement the whole CRM;
it gives one explicit final owner to the behaviours that historically accumulated
multiple wrappers: application identity, dialog placement, deadline emphasis,
Action-table sizing, PLEXUS image resolution and rollback entry points.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from typing import Any

POLICY_OWNER = "v770_runtime_policy"
ATTENTION_TAG = "v770_deadline_attention"
REQUEST_ATTENTION_TAG = "v770_request_attention"
_PLEXUS_RE = re.compile(r"(?:^|[|,;\s])(?:typ|type)\s*[:=\-]?\s*([A-Z]{1,3})(?=\s|[|,;]|$)", re.I)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except Exception:
        try:
            return getattr(row, key)
        except Exception:
            return default


def _is_nevoga(value: Any) -> bool:
    folded = _text(value).casefold()
    return any(token in folded for token in ("nevoga", "nevegar", "reinforcement systems", "reinforcementsystems"))


def _plexus_type(*values: Any) -> str:
    for value in values:
        match = _PLEXUS_RE.search(_text(value).upper())
        if match:
            return match.group(1).upper()
    return ""


def _asset_key(code: Any) -> str:
    code = _text(code).upper()
    return f"nevoga:plexus:{code}" if code else ""


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_plexus_schema(M: Any) -> None:
    with M.db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS offer_image_assets(
                 asset_key TEXT PRIMARY KEY,
                 supplier TEXT NOT NULL,
                 family TEXT NOT NULL DEFAULT '',
                 type_code TEXT NOT NULL DEFAULT '',
                 image_blob BLOB NOT NULL,
                 image_ext TEXT DEFAULT '',
                 image_hash TEXT DEFAULT '',
                 source_offer_no TEXT DEFAULT '',
                 source_offer_date TEXT DEFAULT '',
                 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        con.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_offer_image_assets_supplier_type
               ON offer_image_assets(supplier,family,type_code)"""
        )
        item_cols = _columns(con, "supplier_offer_items")
        if "image_asset_key" not in item_cols:
            con.execute("ALTER TABLE supplier_offer_items ADD COLUMN image_asset_key TEXT DEFAULT ''")
        if "plexus_type" not in item_cols:
            con.execute("ALTER TABLE supplier_offer_items ADD COLUMN plexus_type TEXT DEFAULT ''")


def _upsert_plexus_asset(
    con: sqlite3.Connection,
    code: str,
    image_bytes: Any,
    image_ext: str = "png",
    offer_no: str = "",
    offer_date: str = "",
) -> str:
    code = _text(code).upper()
    key = _asset_key(code)
    if not key or not image_bytes:
        return ""
    blob = bytes(image_bytes)
    if not blob:
        return ""
    digest = hashlib.sha256(blob).hexdigest()
    con.execute(
        """INSERT INTO offer_image_assets(
               asset_key,supplier,family,type_code,image_blob,image_ext,image_hash,
               source_offer_no,source_offer_date,updated_at
           ) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(asset_key) DO UPDATE SET
               image_blob=CASE
                   WHEN excluded.image_hash<>offer_image_assets.image_hash
                   THEN excluded.image_blob ELSE offer_image_assets.image_blob END,
               image_ext=CASE
                   WHEN excluded.image_hash<>offer_image_assets.image_hash
                   THEN excluded.image_ext ELSE offer_image_assets.image_ext END,
               image_hash=CASE
                   WHEN excluded.image_hash<>offer_image_assets.image_hash
                   THEN excluded.image_hash ELSE offer_image_assets.image_hash END,
               source_offer_no=CASE WHEN trim(excluded.source_offer_no)<>''
                   THEN excluded.source_offer_no ELSE offer_image_assets.source_offer_no END,
               source_offer_date=CASE WHEN trim(excluded.source_offer_date)<>''
                   THEN excluded.source_offer_date ELSE offer_image_assets.source_offer_date END,
               updated_at=CURRENT_TIMESTAMP""",
        (
            key, "Nevoga", "PLEXUS", code, sqlite3.Binary(blob),
            _text(image_ext) or "png", digest, _text(offer_no), _text(offer_date),
        ),
    )
    return key


def _canonical_image(con: sqlite3.Connection, item_key: str) -> dict[str, Any] | None:
    if not item_key or not _table_exists(con, "offer_product_images"):
        return None
    try:
        rows = con.execute(
            """SELECT supplier,item_key,image_blob,image_ext,source_offer_no,source_offer_date
               FROM offer_product_images WHERE item_key=?
               ORDER BY source_offer_date DESC""",
            (item_key,),
        ).fetchall()
    except Exception:
        return None
    for row in rows:
        if _is_nevoga(row["supplier"]) and row["image_blob"]:
            return dict(row)
    return None


def _resolve_plexus_image(con: sqlite3.Connection, item: Any, supplier: str = "") -> dict[str, Any] | None:
    code = _text(_row_get(item, "plexus_type")).upper() or _plexus_type(
        _row_get(item, "original_name"), _row_get(item, "item_key"), _row_get(item, "details")
    )
    key = _text(_row_get(item, "image_asset_key")) or (_asset_key(code) if _is_nevoga(supplier) else "")
    if key and _table_exists(con, "offer_image_assets"):
        row = con.execute(
            """SELECT image_blob,image_ext,source_offer_no,source_offer_date,asset_key,type_code
               FROM offer_image_assets WHERE asset_key=?""",
            (key,),
        ).fetchone()
        if row and row["image_blob"]:
            return dict(row)

    blob = _row_get(item, "image_blob")
    if blob:
        return {
            "image_blob": blob,
            "image_ext": _row_get(item, "image_ext", "") or "png",
            "source_offer_no": "",
            "source_offer_date": _row_get(item, "image_source_offer_date", "") or "",
            "asset_key": key,
            "type_code": code,
        }

    canonical = _canonical_image(con, _text(_row_get(item, "item_key")))
    if canonical:
        canonical.setdefault("asset_key", key)
        canonical.setdefault("type_code", code)
        return canonical
    return None


def _stored_pdf_bytes(con: sqlite3.Connection, offer_id: int) -> tuple[str, bytes] | None:
    """Return a PDF stored in any supported attachment/blob table."""
    if _table_exists(con, "offer_source_attachments"):
        cols = _columns(con, "offer_source_attachments")
        blob_col = next((c for c in ("content_blob", "source_blob", "data_blob", "file_blob", "blob") if c in cols), "")
        offer_col = next((c for c in ("offer_id", "supplier_offer_id") if c in cols), "")
        name_col = next((c for c in ("filename", "file_name", "name") if c in cols), "")
        ext_col = next((c for c in ("extension", "file_ext", "ext") if c in cols), "")
        if blob_col and offer_col:
            select = [blob_col]
            if name_col:
                select.append(name_col)
            if ext_col:
                select.append(ext_col)
            try:
                rows = con.execute(
                    f"SELECT {','.join(select)} FROM offer_source_attachments WHERE {offer_col}=? ORDER BY rowid",
                    (int(offer_id),),
                ).fetchall()
            except Exception:
                rows = []
            for row in rows:
                blob = row[blob_col]
                name = _text(row[name_col]) if name_col else "nabidka.pdf"
                ext = _text(row[ext_col]).lower() if ext_col else Path(name).suffix.lower()
                if blob and (ext == ".pdf" or name.lower().endswith(".pdf")):
                    return (Path(name).name or "nabidka.pdf", bytes(blob))

    if _table_exists(con, "supplier_offers"):
        cols = _columns(con, "supplier_offers")
        for blob_col in ("source_pdf_blob", "pdf_blob", "source_blob"):
            if blob_col not in cols:
                continue
            try:
                row = con.execute(
                    f"SELECT {blob_col} FROM supplier_offers WHERE id=?", (int(offer_id),)
                ).fetchone()
            except Exception:
                row = None
            if row and row[blob_col]:
                return ("nabidka.pdf", bytes(row[blob_col]))
    return None


def _parsed_assets(M: Any, offer_id: int) -> dict[str, dict[str, Any]]:
    with M.db() as con:
        offer = con.execute(
            "SELECT source_pdf,offer_number,offer_date,supplier_name FROM supplier_offers WHERE id=?",
            (int(offer_id),),
        ).fetchone()
        if not offer or not _is_nevoga(offer["supplier_name"]):
            return {}
        source_path = Path(_text(offer["source_pdf"])) if _text(offer["source_pdf"]) else None
        stored = None if source_path and source_path.is_file() else _stored_pdf_bytes(con, int(offer_id))

    def parse(path: Path) -> dict[str, dict[str, Any]]:
        parsed, _raw = M.extract_offer_pdf(path)
        result: dict[str, dict[str, Any]] = {}
        for item in list((parsed or {}).get("items") or []):
            code = _text(item.get("plexus_type")).upper() or _plexus_type(
                item.get("description"), item.get("item_key"), item.get("details")
            )
            image = item.get("image_bytes")
            if code and image:
                result[code] = {
                    "image_bytes": bytes(image),
                    "image_ext": _text(item.get("image_ext")) or "png",
                    "position": int(item.get("position") or 0),
                }
        return result

    try:
        if source_path and source_path.is_file():
            return parse(source_path)
        if stored:
            name, data = stored
            with tempfile.TemporaryDirectory(prefix="turto_plexus_") as td:
                path = Path(td) / (Path(name).name or "nabidka.pdf")
                if path.suffix.lower() != ".pdf":
                    path = path.with_suffix(".pdf")
                path.write_bytes(data)
                return parse(path)
    except Exception:
        return {}
    return {}


def _centralize_parsed(M: Any, offer_id: int, parsed: Any) -> int:
    if not _is_nevoga((parsed or {}).get("supplier")):
        return 0
    _ensure_plexus_schema(M)
    parsed_items = list((parsed or {}).get("items") or [])
    if not parsed_items:
        return 0
    with M.db() as con:
        offer = con.execute(
            "SELECT offer_number,offer_date FROM supplier_offers WHERE id=?", (int(offer_id),)
        ).fetchone()
        stored = con.execute(
            "SELECT id,position,item_key,original_name,details FROM supplier_offer_items "
            "WHERE offer_id=? ORDER BY position,id", (int(offer_id),)
        ).fetchall()
        by_position: dict[int, list[Any]] = {}
        for row in stored:
            by_position.setdefault(int(row["position"] or 0), []).append(row)
        linked = 0
        for item in parsed_items:
            code = _text(item.get("plexus_type")).upper() or _plexus_type(
                item.get("description"), item.get("item_key"), item.get("details")
            )
            image = item.get("image_bytes")
            if not code or not image:
                continue
            key = _upsert_plexus_asset(
                con, code, image, _text(item.get("image_ext")) or "png",
                _text(offer["offer_number"] if offer else ""),
                _text(offer["offer_date"] if offer else ""),
            )
            if not key:
                continue
            candidates = by_position.get(int(item.get("position") or 0), [])
            row = candidates.pop(0) if candidates else None
            if row:
                con.execute(
                    "UPDATE supplier_offer_items SET image_asset_key=?,plexus_type=? WHERE id=?",
                    (key, code, int(row["id"])),
                )
                linked += 1
        return linked


def _ensure_offer_plexus_images(M: Any, offer_id: int) -> int:
    """Resolve old and new Nevoga offers, then reparse a stored source if needed."""
    _ensure_plexus_schema(M)
    offer_id = int(offer_id)
    linked = 0
    with M.db() as con:
        offer = con.execute(
            "SELECT supplier_name,offer_number,offer_date FROM supplier_offers WHERE id=?",
            (offer_id,),
        ).fetchone()
        if not offer or not _is_nevoga(offer["supplier_name"]):
            return 0
        rows = con.execute(
            "SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id",
            (offer_id,),
        ).fetchall()
        missing_codes: set[str] = set()
        for row in rows:
            code = _text(_row_get(row, "plexus_type")).upper() or _plexus_type(
                row["original_name"], row["item_key"], row["details"]
            )
            if not code:
                continue
            key = _asset_key(code)
            image = _resolve_plexus_image(con, row, offer["supplier_name"])
            if image and image.get("image_blob"):
                if not _text(_row_get(row, "image_asset_key")):
                    key = _upsert_plexus_asset(
                        con, code, image["image_blob"], image.get("image_ext") or "png",
                        offer["offer_number"] or "", offer["offer_date"] or "",
                    ) or key
                con.execute(
                    "UPDATE supplier_offer_items SET image_asset_key=?,plexus_type=? WHERE id=?",
                    (key, code, int(row["id"])),
                )
                linked += 1
            else:
                missing_codes.add(code)

    if missing_codes:
        parsed = _parsed_assets(M, offer_id)
        if parsed:
            with M.db() as con:
                offer = con.execute(
                    "SELECT offer_number,offer_date FROM supplier_offers WHERE id=?", (offer_id,)
                ).fetchone()
                rows = con.execute(
                    "SELECT id,position,original_name,item_key,details FROM supplier_offer_items "
                    "WHERE offer_id=? ORDER BY position,id", (offer_id,)
                ).fetchall()
                for code, data in parsed.items():
                    key = _upsert_plexus_asset(
                        con, code, data["image_bytes"], data.get("image_ext") or "png",
                        offer["offer_number"] or "", offer["offer_date"] or "",
                    )
                    if not key:
                        continue
                    for row in rows:
                        row_code = _plexus_type(row["original_name"], row["item_key"], row["details"])
                        if row_code == code:
                            con.execute(
                                "UPDATE supplier_offer_items SET image_asset_key=?,plexus_type=? WHERE id=?",
                                (key, code, int(row["id"])),
                            )
                            linked += 1
    return linked


def _clean_date(value: Any) -> str:
    text = _text(value)
    for marker in ("⚠️ ", "⚠ ", "⚠️", "⚠", "● ", "●", "▲ ", "△ "):
        text = text.replace(marker, "")
    return text.strip()


def _parse_date(value: Any) -> date | None:
    text = _clean_date(value)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d. %m. %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass
    return None


def _attention_callback(self: Any, rows: Any) -> None:
    tree = getattr(self, "action_tree", None)
    if tree is None:
        return
    try:
        tree.tag_configure(ATTENTION_TAG, font=("Calibri", 10, "bold"))
    except Exception:
        pass
    for item in rows or ():
        iid = item[0] if item else None
        late = bool(item[1]) if len(item) > 1 else False
        soon = bool(item[2]) if len(item) > 2 else False
        if not iid:
            continue
        try:
            if not tree.exists(iid):
                continue
            raw = tree.set(iid, "Deadline")
            clean = _clean_date(raw)
            if clean != raw:
                tree.set(iid, "Deadline", clean)
            tags = [tag for tag in (tree.item(iid, "tags") or ()) if tag != ATTENTION_TAG]
            if late or soon:
                tags.append(ATTENTION_TAG)
            tree.item(iid, tags=tuple(tags))
        except Exception:
            pass


def _request_attention_callback(self: Any, tree: Any, rows: Any) -> None:
    if tree is None:
        return
    try:
        tree.tag_configure(REQUEST_ATTENTION_TAG, font=("Calibri", 10, "bold"))
    except Exception:
        pass
    for item in rows or ():
        iid = item[0] if item else None
        overdue = bool(item[1]) if len(item) > 1 else False
        if not iid:
            continue
        try:
            if not tree.exists(iid):
                continue
            raw = tree.set(iid, "Poptáno")
            clean = _clean_date(raw)
            if clean != raw:
                tree.set(iid, "Poptáno", clean)
            tags = [tag for tag in (tree.item(iid, "tags") or ()) if tag != REQUEST_ATTENTION_TAG]
            if overdue:
                tags.append(REQUEST_ATTENTION_TAG)
            tree.item(iid, tags=tuple(tags))
        except Exception:
            pass


def _display_columns(tree: Any) -> list[str]:
    try:
        all_columns = list(tree.cget("columns") or ())
        displayed = list(tree.cget("displaycolumns") or ())
        if not displayed or displayed == ["#all"]:
            return all_columns
        result = []
        for value in displayed:
            if str(value).isdigit():
                index = int(value)
                if 0 <= index < len(all_columns):
                    result.append(all_columns[index])
            elif value in all_columns:
                result.append(value)
        return result or all_columns
    except Exception:
        return []


def _fit_action_tree(tree: Any) -> None:
    try:
        if tree is None or not tree.winfo_exists():
            return
        columns = _display_columns(tree)
        if not columns:
            return
        available = max(100, int(tree.winfo_width()) - 4)
        if available <= 120:
            return
        if not hasattr(tree, "_v770_action_design"):
            tree._v770_action_design = {
                column: max(60, int(tree.column(column, "width") or 80))
                for column in columns
            }
        design = tree._v770_action_design
        compact = {"Stav", "Přijato", "Deadline"}
        minimum = {
            column: (86 if column in ("Přijato", "Deadline") else 100 if column == "Stav" else 110)
            for column in columns
        }
        base = {column: max(minimum[column], int(design.get(column, minimum[column]))) for column in columns}
        total = sum(base.values())
        widths = dict(base)
        flex = [column for column in columns if column not in compact] or [columns[-1]]
        if total < available:
            extra = available - total
            weights = [max(1, base[column]) for column in flex]
            weight_total = sum(weights)
            allocated = 0
            for index, column in enumerate(flex):
                add = extra - allocated if index == len(flex) - 1 else int(extra * weights[index] / weight_total)
                widths[column] += add
                allocated += add
        elif total > available:
            shortage = total - available
            capacity = sum(max(0, widths[column] - minimum[column]) for column in flex)
            if capacity:
                removed = 0
                for index, column in enumerate(flex):
                    room = max(0, widths[column] - minimum[column])
                    cut = min(room, shortage - removed if index == len(flex) - 1 else int(shortage * room / capacity))
                    widths[column] -= cut
                    removed += cut
        for column in columns:
            tree.column(
                column,
                width=max(minimum[column], int(widths[column])),
                minwidth=minimum[column],
                stretch=False,
            )
        sync = getattr(tree, "_sync_filter_bar", None)
        if callable(sync):
            tree.after_idle(sync)
    except Exception:
        pass


def _install_action_layout(app: Any) -> None:
    tree = getattr(app, "action_tree", None)
    if tree is None:
        return
    if not getattr(tree, "_v770_full_width_bound", False):
        tree._v770_full_width_bound = True
        tree.bind("<Configure>", lambda _event, current=tree: current.after(80, lambda: _fit_action_tree(current)), add="+")
        tree.bind("<Map>", lambda _event, current=tree: current.after_idle(lambda: _fit_action_tree(current)), add="+")
    _fit_action_tree(tree)


def _workarea_for_window(win: Any) -> tuple[int, int, int, int]:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

            hwnd = int(win.winfo_id())
            monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
        except Exception:
            pass
    return 0, 0, int(win.winfo_screenwidth()), int(win.winfo_screenheight())


def _workarea_for_point(win: Any, x: int, y: int) -> tuple[int, int, int, int]:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

            monitor = ctypes.windll.user32.MonitorFromPoint(POINT(int(x), int(y)), 2)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom
        except Exception:
            pass
    return _workarea_for_window(win)


def _place_dialog(win: Any, parent: Any = None, preferred: tuple[int, int] | None = None) -> None:
    try:
        if bool(win.overrideredirect()):
            return
    except Exception:
        pass
    try:
        parent = parent or getattr(win, "master", None)
        if parent is None or not parent.winfo_exists():
            parent = win
        win.update_idletasks()
        parent.update_idletasks()
        left, top, right, bottom = _workarea_for_window(parent)
        area_w, area_h = max(420, right - left), max(320, bottom - top)
        pref = preferred or getattr(win, "_v770_preferred_size", None) or getattr(win, "_preferred_dialog_size", None) or (0, 0)
        req_w = max(int(win.winfo_reqwidth() or 0), int(win.winfo_width() or 0), int(pref[0] or 0), 360)
        req_h = max(int(win.winfo_reqheight() or 0), int(win.winfo_height() or 0), int(pref[1] or 0), 220)
        width = min(req_w, max(360, area_w - 30))
        height = min(req_h, max(220, area_h - 30))
        px = int(parent.winfo_rootx() + max(0, parent.winfo_width()) / 2)
        py = int(parent.winfo_rooty() + max(0, parent.winfo_height()) / 2)
        x = min(max(left + 10, px - width // 2), right - width - 10)
        y = min(max(top + 10, py - height // 2), bottom - height - 10)
        win.geometry(f"{width}x{height}+{int(x)}+{int(y)}")
        win.maxsize(max(360, area_w - 10), max(220, area_h - 10))
    except Exception:
        pass


def _install_dialog_policy(M: Any) -> None:
    def center_dialog(win: Any, parent: Any = None):
        for delay in (0, 60, 180):
            try:
                win.after(delay, lambda current=win, owner=parent: _place_dialog(current, owner))
            except Exception:
                pass

    def enable_dialog_maximize(win: Any, min_width: int = 620, min_height: int = 420):
        try:
            win.resizable(True, True)
            win._v770_preferred_size = (max(420, int(min_width)), max(280, int(min_height)))
            win.minsize(min(520, max(420, int(min_width))), min(360, max(280, int(min_height))))
        except Exception:
            pass
        center_dialog(win, getattr(win, "master", None))

    M.center_dialog = center_dialog
    M.enable_dialog_maximize = enable_dialog_maximize

    Toplevel = M.tk.Toplevel
    if not getattr(Toplevel, "_turto_v770_monitor_policy", False):
        previous_init = Toplevel.__init__

        def init(self, *args, **kwargs):
            previous_init(self, *args, **kwargs)
            for delay in (20, 140, 260):
                try:
                    self.after(delay, lambda current=self: _place_dialog(current, getattr(current, "master", None)))
                except Exception:
                    pass

        Toplevel.__init__ = init
        Toplevel._turto_v770_monitor_policy = True

    Autocomplete = getattr(M, "AutocompleteEntry", None)
    if Autocomplete is not None and not getattr(Autocomplete, "_turto_v770_popup_policy", False):
        previous_reposition = Autocomplete._reposition_popup

        def reposition(self):
            previous_reposition(self)
            try:
                popup = self.popup
                if not popup or not popup.winfo_exists() or not popup.winfo_viewable():
                    return
                popup.update_idletasks()
                entry_x = int(self.winfo_rootx())
                entry_y = int(self.winfo_rooty())
                entry_w = max(120, int(self.winfo_width()))
                entry_h = max(20, int(self.winfo_height()))
                left, top, right, bottom = _workarea_for_point(self, entry_x + entry_w // 2, entry_y + entry_h // 2)
                width = min(max(entry_w, int(popup.winfo_width()), 300), max(180, right - left - 20))
                height = min(max(30, int(popup.winfo_height())), max(30, bottom - top - 20))
                x = min(max(left + 5, entry_x), right - width - 5)
                below = entry_y + entry_h
                y = below if below + height <= bottom - 5 else entry_y - height
                y = min(max(top + 5, y), bottom - height - 5)
                popup.geometry(f"{width}x{height}+{x}+{y}")
            except Exception:
                try:
                    self.hide()
                except Exception:
                    pass

        Autocomplete._reposition_popup = reposition
        Autocomplete._turto_v770_popup_policy = True


def _ensure_icon_assets(M: Any) -> None:
    """Create the transparent TURTO CRM icon locally when the release has none."""
    root = Path(getattr(M, "ROOT", Path.cwd()))
    png = root / "turto_crm.png"
    ico = root / "turto_crm.ico"
    if png.is_file() and ico.is_file():
        return
    try:
        from PIL import Image, ImageDraw, ImageFont

        size = 256
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        silver = (210, 216, 222, 255)
        dark = (40, 48, 56, 255)
        gold = (214, 169, 0, 255)
        shadow = (0, 0, 0, 95)

        # Compact building mark: three structural bars plus a gold sweep.
        bars = ((55, 62, 86, 150), (94, 34, 129, 150), (139, 76, 169, 150))
        for left, top, right, bottom in bars:
            draw.rounded_rectangle((left + 4, top + 5, right + 4, bottom + 5), radius=4, fill=shadow)
            draw.rounded_rectangle((left, top, right, bottom), radius=4, fill=dark, outline=silver, width=4)
            inner = max(5, (right - left) // 4)
            draw.rounded_rectangle((left + inner, top + 14, right - inner, bottom - 8), radius=2, fill=(0, 0, 0, 0), outline=silver, width=3)
        draw.arc((31, 91, 193, 181), 8, 174, fill=shadow, width=14)
        draw.arc((27, 87, 189, 177), 8, 174, fill=silver, width=10)
        draw.arc((31, 91, 193, 181), 8, 174, fill=gold, width=4)

        def font(size_px: int):
            candidates = (
                Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "calibrib.ttf",
                Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
            )
            for candidate in candidates:
                try:
                    if candidate.is_file():
                        return ImageFont.truetype(str(candidate), size_px)
                except Exception:
                    pass
            return ImageFont.load_default()

        turto_font = font(48)
        crm_font = font(30)
        turto = "TURTO"
        crm = "CRM"
        tb = draw.textbbox((0, 0), turto, font=turto_font, stroke_width=1)
        cb = draw.textbbox((0, 0), crm, font=crm_font, stroke_width=1)
        tx = (size - (tb[2] - tb[0])) // 2
        cx = (size - (cb[2] - cb[0])) // 2
        draw.text((tx + 2, 166 + 2), turto, font=turto_font, fill=shadow, stroke_width=1, stroke_fill=shadow)
        draw.text((tx, 166), turto, font=turto_font, fill=silver, stroke_width=1, stroke_fill=dark)
        draw.line((35, 226, cx - 8, 226), fill=gold, width=3)
        draw.line((cx + (cb[2] - cb[0]) + 8, 226, 221, 226), fill=gold, width=3)
        draw.text((cx + 1, 207 + 1), crm, font=crm_font, fill=shadow, stroke_width=1, stroke_fill=shadow)
        draw.text((cx, 207), crm, font=crm_font, fill=gold, stroke_width=1, stroke_fill=dark)

        image.save(png, optimize=True)
        image.save(
            ico,
            format="ICO",
            sizes=((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)),
        )
    except Exception:
        pass


def _configure_identity(M: Any, win: Any) -> None:
    _ensure_icon_assets(M)
    root = Path(getattr(M, "ROOT", Path.cwd()))
    ico = root / "turto_crm.ico"
    png = root / "turto_crm.png"
    try:
        if ico.is_file():
            win.iconbitmap(default=str(ico))
    except Exception:
        pass
    try:
        if png.is_file():
            image = M.tk.PhotoImage(file=str(png))
            win.iconphoto(True, image)
            win._turto_crm_icon_photo = image
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TURTO.CRM")
        except Exception:
            pass


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _apply_branding(M: Any, app: Any) -> None:
    try:
        app.title("TURTO CRM")
    except Exception:
        pass
    try:
        style = M.ttk.Style(app)
        style.configure("BrandCRM.TLabel", background="#17212a", foreground="#d6a900", font=("Calibri", 13, "bold"))
    except Exception:
        pass
    for widget in _walk(app):
        try:
            if not widget.winfo_class().endswith("Label"):
                continue
            value = _text(widget.cget("text"))
            if "Zakázky CRM" in value or "Zakazky CRM" in value:
                widget.configure(text="  CRM", style="BrandCRM.TLabel")
        except Exception:
            pass


def _version_from_package_manifest(path: Path) -> tuple[str, Path, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        package = path.parent / Path(_text(data.get("file"))).name
        version = _text(data.get("version"))
        digest = _text(data.get("sha256"))
        if package.is_file() and version:
            return version, package, digest
    except Exception:
        pass
    return None


def _rollback_candidate(M: Any) -> tuple[str, Path, str] | None:
    data_root = Path(getattr(M, "DATA_ROOT", Path.home() / "Documents" / "TURTO Zakazky"))
    external = data_root / "updates" / "rollback" / "latest.json"
    try:
        data = json.loads(external.read_text(encoding="utf-8"))
        package = Path(_text(data.get("package")))
        version = _text(data.get("version"))
        digest = _text(data.get("sha256"))
        if package.is_file() and version:
            return version, package, digest
    except Exception:
        pass
    bundled = Path(getattr(M, "ROOT", Path.cwd())) / "_rollback" / "rollback_manifest.json"
    return _version_from_package_manifest(bundled) if bundled.is_file() else None


def _verify_package(path: Path, expected: str) -> bool:
    if not expected:
        return True
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest.casefold() == expected.casefold()


def _launch_rollback(M: Any, app: Any) -> None:
    candidate = _rollback_candidate(M)
    if not candidate:
        return M.messagebox.showinfo(
            "Návrat verze",
            "V této instalaci není uložená předchozí verze programu.",
            parent=app,
        )
    version, package, digest = candidate
    if not _verify_package(package, digest):
        return M.messagebox.showerror(
            "Návrat verze",
            "Balíček předchozí verze neprošel kontrolou SHA-256. Návrat nebyl spuštěn.",
            parent=app,
        )
    if not M.messagebox.askyesno(
        "Vrátit předchozí verzi",
        f"Vrátit program na TURTO CRM {version}?\n\n"
        "Pracovní databáze se nemaže. Před výměnou programu se automaticky vytvoří "
        "samostatná záloha databáze i současné verze programu.",
        parent=app,
    ):
        return
    root = Path(getattr(M, "ROOT", Path.cwd()))
    updater = root / "crm_updater.pyw"
    if not updater.is_file():
        return M.messagebox.showerror("Návrat verze", "Chybí crm_updater.pyw.", parent=app)
    if sys.platform.startswith("win"):
        launcher = shutil.which("pyw") or shutil.which("pythonw") or sys.executable
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        launcher = sys.executable
        flags = 0
    try:
        subprocess.Popen(
            [str(launcher), str(updater), "--install", str(package), str(root), str(os.getpid()), "rollback"],
            cwd=str(root),
            creationflags=flags,
        )
        app.after(180, app.destroy)
    except Exception as exc:
        M.messagebox.showerror("Návrat verze", f"Návrat se nepodařilo spustit:\n{exc}", parent=app)


def _install_rollback_ui(M: Any) -> None:
    previous = getattr(M.App, "build_settings", None)
    if not callable(previous) or getattr(previous, "_turto_v770_rollback_ui", False):
        return

    def build_settings(self, *args, **kwargs):
        result = previous(self, *args, **kwargs)
        try:
            page = self.tabs["settings"]
            card = M.ttk.Frame(page, style="Panel.TFrame", padding=18)
            card.pack(fill="x", pady=(10, 0))
            M.ttk.Label(card, text="Obnovení předchozí verze", font=("Calibri", 12, "bold")).pack(anchor="w")
            candidate = _rollback_candidate(M)
            if candidate:
                version = candidate[0]
                description = (
                    f"K dispozici je TURTO CRM {version}. Databáze zůstane na místě a před návratem "
                    "se vytvoří její časově označená záloha."
                )
                button_text = f"Vrátit TURTO CRM {version}…"
                state = "normal"
            else:
                description = "Předchozí instalační balíček zatím není v této instalaci dostupný."
                button_text = "Předchozí verze není dostupná"
                state = "disabled"
            M.ttk.Label(card, text=description, style="PageSubtitle.TLabel", wraplength=900).pack(anchor="w", pady=(3, 9))
            M.ttk.Button(
                card, text=button_text, state=state,
                command=lambda current=self: _launch_rollback(M, current),
            ).pack(anchor="w")
        except Exception:
            pass
        return result

    build_settings._turto_v770_rollback_ui = True
    M.App.build_settings = build_settings


def _install_shortcut_owner(M: Any) -> None:
    def create_desktop_shortcut(self):
        if not sys.platform.startswith("win"):
            return M.messagebox.showinfo("Zástupce", "Tato funkce je určena pro Windows.", parent=self)
        try:
            root = Path(getattr(M, "ROOT", Path.cwd()))
            desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
            desktop.mkdir(parents=True, exist_ok=True)
            link = desktop / "TURTO CRM.lnk"
            target = str(Path(sys.executable).resolve()) if getattr(sys, "frozen", False) else str((root / "Spustit_Zakazky.bat").resolve())
            env = os.environ.copy()
            env.update({"TURTO_LINK": str(link), "TURTO_TARGET": target, "TURTO_ROOT": str(root)})
            script = r'''
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($env:TURTO_LINK)
$s.TargetPath=$env:TURTO_TARGET
$s.WorkingDirectory=$env:TURTO_ROOT
$s.Description='TURTO CRM'
$icon=Join-Path $env:TURTO_ROOT 'turto_crm.ico'
if (Test-Path $icon) { $s.IconLocation=$icon }
$s.Save()
'''
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                env=env, capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode:
                raise RuntimeError((completed.stderr or completed.stdout).strip())
            M.messagebox.showinfo("Zástupce", f"Zástupce byl vytvořen:\n{link}", parent=self)
        except Exception as exc:
            M.messagebox.showerror("Zástupce", f"Zástupce se nepodařilo vytvořit:\n{exc}", parent=self)

    M.App.create_desktop_shortcut = create_desktop_shortcut


def _install_plexus_ui(M: Any) -> None:
    try:
        import crm_features
    except Exception:
        crm_features = None
    classes = []
    for cls in (
        getattr(crm_features, "OfferDetailDialog", None) if crm_features else None,
        getattr(M, "OfferDetailDialog", None),
    ):
        if cls is not None and cls not in classes:
            classes.append(cls)

    for cls in classes:
        if getattr(cls, "_turto_v770_plexus_preview", False):
            continue
        previous_build = cls._build

        def build(self, *args, __previous=previous_build, **kwargs):
            result = __previous(self, *args, **kwargs)
            try:
                offer = getattr(self, "offer_row", None)
                supplier = (_row_get(offer, "supplier", "") or _row_get(offer, "supplier_name", "")) if offer else ""
                if not _is_nevoga(supplier):
                    return result
                _ensure_offer_plexus_images(M, int(self.oid))
                panel = M.ttk.Frame(self.f, style="Card.TFrame", padding=8)
                title = M.tk.StringVar(value="Obrázek PLEXUS")
                M.ttk.Label(panel, textvariable=title, style="PageSubtitle.TLabel").pack(anchor="w")
                preview = M.ttk.Label(panel, text="Vyberte položku nabídky.", anchor="center")
                preview.pack(fill="x", expand=True, pady=(5, 0))
                panel.pack(fill="x", pady=(6, 0))

                def render(_event=None):
                    item = self._selected_item()
                    if not item:
                        preview.configure(image="", text="Vyberte položku nabídky.")
                        return
                    with M.db() as con:
                        image = _resolve_plexus_image(con, item, supplier)
                    if not image:
                        _ensure_offer_plexus_images(M, int(self.oid))
                        with M.db() as con:
                            refreshed = con.execute("SELECT * FROM supplier_offer_items WHERE id=?", (int(item["id"]),)).fetchone()
                            image = _resolve_plexus_image(con, refreshed or item, supplier)
                    code = _text(_row_get(item, "plexus_type")) or _plexus_type(
                        _row_get(item, "original_name"), _row_get(item, "item_key")
                    )
                    title.set(f"Obrázek PLEXUS – typ {code}" if code else "Obrázek PLEXUS")
                    if not image or not image.get("image_blob"):
                        preview.configure(image="", text="K této položce zatím není uložen obrázek PLEXUS.")
                        preview.image = None
                        return
                    from PIL import Image, ImageTk
                    pil = Image.open(io.BytesIO(bytes(image["image_blob"]))).convert("RGBA")
                    pil.thumbnail((640, 210))
                    photo = ImageTk.PhotoImage(pil)
                    preview.configure(image=photo, text="")
                    preview.image = photo

                tree = getattr(self, "tree", None)
                if tree is not None:
                    tree.bind("<<TreeviewSelect>>", render, add="+")
                render()
            except Exception:
                pass
            return result

        def open_image(self):
            item = self._selected_item()
            if not item:
                return M.messagebox.showinfo("Nabídky", "Vyberte položku nabídky.", parent=self)
            offer = getattr(self, "offer_row", None)
            supplier = (_row_get(offer, "supplier", "") or _row_get(offer, "supplier_name", "")) if offer else ""
            _ensure_offer_plexus_images(M, int(self.oid))
            with M.db() as con:
                refreshed = con.execute("SELECT * FROM supplier_offer_items WHERE id=?", (int(item["id"]),)).fetchone()
                image = _resolve_plexus_image(con, refreshed or item, supplier)
            if not image or not image.get("image_blob"):
                return M.messagebox.showinfo("Nabídky", "K této položce není uložen obrázek.", parent=self)
            try:
                from PIL import Image, ImageTk
                pil = Image.open(io.BytesIO(bytes(image["image_blob"]))).convert("RGBA")
                pil.thumbnail((1000, 680))
                dialog = M.tk.Toplevel(self)
                dialog.title("Obrázek PLEXUS")
                dialog.transient(self)
                dialog.grab_set()
                M.enable_dialog_maximize(dialog, 720, 500)
                photo = ImageTk.PhotoImage(pil)
                label = M.ttk.Label(dialog, image=photo)
                label.image = photo
                label.pack(fill="both", expand=True, padx=14, pady=14)
                M.ttk.Button(dialog, text="Zavřít", command=dialog.destroy).pack(pady=(0, 14))
            except Exception as exc:
                M.messagebox.showerror("Nabídky", f"Obrázek se nepodařilo otevřít:\n{exc}", parent=self)

        cls._build = build
        cls.open_image = open_image
        cls._turto_v770_plexus_preview = True

    previous_export = getattr(M, "export_offer_excel", None)
    if callable(previous_export) and not getattr(previous_export, "_turto_v770_plexus_guard", False):
        def export_offer_excel(app, offer_id, parent=None):
            try:
                _ensure_offer_plexus_images(M, int(offer_id))
            except Exception:
                pass
            return previous_export(app, offer_id, parent=parent)

        export_offer_excel._turto_v770_plexus_guard = True
        M.export_offer_excel = export_offer_excel


def _schedule_plexus_backfill(M: Any, app: Any) -> None:
    try:
        with M.db() as con:
            rows = con.execute(
                """SELECT DISTINCT o.id FROM supplier_offers o
                   JOIN supplier_offer_items i ON i.offer_id=o.id
                   WHERE (lower(coalesce(o.supplier_name,'')) LIKE '%nevoga%'
                       OR lower(coalesce(o.supplier_name,'')) LIKE '%reinforcement%')
                     AND lower(coalesce(i.original_name,'')||' '||coalesce(i.item_key,'')) LIKE '%plexus%'
                   ORDER BY o.id DESC LIMIT 25"""
            ).fetchall()
        ids = [int(row[0]) for row in rows]
    except Exception:
        ids = []

    def step(index: int = 0):
        if index >= len(ids):
            return
        try:
            _ensure_offer_plexus_images(M, ids[index])
        except Exception:
            pass
        try:
            app.after(70, lambda: step(index + 1))
        except Exception:
            pass

    if ids:
        app.after(800, step)


def apply(M: Any) -> None:
    if getattr(M, "_turto_v770_runtime_policy", False):
        return
    M._turto_v770_runtime_policy = True
    M.APP_NAME = "TURTO CRM"

    previous_ensure_schema = getattr(M, "ensure_schema", None)
    if callable(previous_ensure_schema):
        def ensure_schema():
            result = previous_ensure_schema()
            _ensure_plexus_schema(M)
            return result
        M.ensure_schema = ensure_schema

    previous_save = getattr(M, "save_offer_import", None)
    if callable(previous_save):
        def save_offer_import(*args, **kwargs):
            result = previous_save(*args, **kwargs)
            try:
                offer_id = int(result[0])
                parsed = result[3] if len(result) > 3 else {}
                _centralize_parsed(M, offer_id, parsed)
            except Exception:
                pass
            return result
        M.save_offer_import = save_offer_import

    M.ensure_plexus_images = lambda offer_id: _ensure_offer_plexus_images(M, int(offer_id))
    M.resolve_offer_item_image = _resolve_plexus_image
    M.plexus_image_asset_key = _asset_key

    _install_dialog_policy(M)
    _install_rollback_ui(M)
    _install_shortcut_owner(M)

    M.App._refresh_action_deadline_highlights = _attention_callback
    M.App._refresh_request_date_highlights = _request_attention_callback

    previous_refresh_tasks = getattr(M.App, "refresh_tasks", None)
    if callable(previous_refresh_tasks) and not getattr(previous_refresh_tasks, "_turto_v770_deadline_bold", False):
        def refresh_tasks(self, *args, **kwargs):
            result = previous_refresh_tasks(self, *args, **kwargs)
            tree = getattr(self, "task_tree", None)
            if tree is not None:
                try:
                    tree.tag_configure(ATTENTION_TAG, font=("Calibri", 10, "bold"))
                    columns = list(tree.cget("columns") or ())
                    date_col = next((c for c in columns if _text(c).casefold() in {"termín", "termin", "deadline", "do"}), None)
                    status_col = next((c for c in columns if _text(c).casefold() == "stav"), None)
                    today = date.today()
                    if date_col:
                        for iid in tree.get_children(""):
                            due = _parse_date(tree.set(iid, date_col))
                            status = _text(tree.set(iid, status_col)).casefold() if status_col else ""
                            attention = bool(due and due <= today + timedelta(days=3) and not any(x in status for x in ("hotov", "splně", "dokonc")))
                            tags = [tag for tag in (tree.item(iid, "tags") or ()) if tag != ATTENTION_TAG]
                            if attention:
                                tags.append(ATTENTION_TAG)
                            tree.item(iid, tags=tuple(tags))
                except Exception:
                    pass
            return result
        refresh_tasks._turto_v770_deadline_bold = True
        M.App.refresh_tasks = refresh_tasks

    previous_identity = getattr(M, "configure_windows_app_identity", None)
    def configure_windows_app_identity(win):
        if callable(previous_identity):
            try:
                previous_identity(win)
            except Exception:
                pass
        _configure_identity(M, win)
    M.configure_windows_app_identity = configure_windows_app_identity

    previous_init = M.App.__init__
    def app_init(self, *args, **kwargs):
        result = previous_init(self, *args, **kwargs)
        _configure_identity(M, self)
        try:
            self.title("TURTO CRM")
        except Exception:
            pass
        self.after_idle(lambda current=self: _apply_branding(M, current))
        self.after_idle(lambda current=self: _install_action_layout(current))
        self.after(250, lambda current=self: _install_action_layout(current))
        _schedule_plexus_backfill(M, self)
        return result
    M.App.__init__ = app_init

    _install_plexus_ui(M)

    M.V770_RUNTIME_POLICY = {
        "owner": POLICY_OWNER,
        "application_name": "TURTO CRM",
        "dialog_monitor_owner": POLICY_OWNER,
        "deadline_emphasis_owner": POLICY_OWNER,
        "action_width_owner": POLICY_OWNER,
        "plexus_image_owner": POLICY_OWNER,
        "rollback_supported": True,
        "rollback_preserves_database": True,
    }
