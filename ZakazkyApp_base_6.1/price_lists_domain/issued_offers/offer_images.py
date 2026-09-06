"""Issued-offer image references; shared PLEXUS assets are never duplicated."""
from __future__ import annotations
import hashlib
from pathlib import Path


def resolve(M, item, con=None):
    if item.get("_image_bytes"):
        return bytes(item["_image_bytes"])
    path = str(item.get("image_file_snapshot") or "")
    if path:
        p = Path(path)
        if p.is_file():
            return p.read_bytes()
    def read(db):
        key = str(item.get("image_asset_key_snapshot") or "")
        if key:
            try:
                r = db.execute("SELECT image_blob FROM offer_image_assets WHERE asset_key=?", (key,)).fetchone()
                if r and r[0]:
                    return bytes(r[0])
            except Exception:
                pass
        source = item.get("source_supplier_offer_item_id")
        if source:
            try:
                r = db.execute("SELECT i.*,o.supplier_name AS _supplier FROM supplier_offer_items i LEFT JOIN supplier_offers o ON o.id=i.offer_id WHERE i.id=?", (int(source),)).fetchone()
                if r:
                    row = dict(r)
                    resolver = getattr(M, "resolve_offer_item_image", None)
                    image = resolver(db, row, row.get("_supplier", "")) if callable(resolver) else row
                    if image and image.get("image_blob"):
                        return bytes(image["image_blob"])
            except Exception:
                pass
        return None
    if con is not None:
        return read(con)
    try:
        with M.db() as db:
            return read(db)
    except (AttributeError, OSError):
        return None


def capture(M, item, source=None):
    """Retain a durable source on first transfer/save, with content-addressed files
    for non-shared images. Existing commercial snapshots always win."""
    result = dict(item)
    if result.get("image_asset_key_snapshot") or result.get("image_file_snapshot"):
        return result
    if source is None and item.get("source_supplier_offer_item_id"):
        with M.db() as con:
            source = con.execute("SELECT * FROM supplier_offer_items WHERE id=?", (int(item["source_supplier_offer_item_id"]),)).fetchone()
    source = dict(source or {})
    key = str(source.get("image_asset_key") or "")
    if key:
        result["image_asset_key_snapshot"] = key
        return result
    blob = resolve(M, item)
    if blob:
        # This is an immutable copy of customer-facing artwork, not a catalogue write.
        from . import service
        root = service.template_assets_root(M) / "Obrazky polozek"
        root.mkdir(parents=True, exist_ok=True)
        target = root / (hashlib.sha256(blob).hexdigest() + ".img")
        if not target.exists():
            target.write_bytes(blob)
        result["image_file_snapshot"] = str(target)
    return result


def fingerprint(M, items):
    digest = hashlib.sha256()
    cache = {}
    try:
        with M.db() as con:
            for item in items:
                if item.get("row_type") in {"text", "heading"}:
                    continue
                key = (str(item.get("image_asset_key_snapshot") or ""),
                       str(item.get("image_file_snapshot") or ""),
                       str(item.get("source_supplier_offer_item_id") or ""))
                if key not in cache:
                    cache[key] = hashlib.sha256(resolve(M, item, con) or b"").digest()
                digest.update(cache[key])
    except (AttributeError, OSError):
        return ""
    return digest.hexdigest()
