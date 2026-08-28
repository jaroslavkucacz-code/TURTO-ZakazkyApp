"""Value normalization shared by Ceníky."""
from __future__ import annotations
import hashlib,re,unicodedata
from datetime import date,datetime
from pathlib import Path
from . import context as ctx

PRICE_LIST_EXTS={".pdf",".xlsx",".xlsm",".csv"}
UPDATE_MODES={
 "partial":"Dílčí dodatek – aktualizuje pouze uvedené položky",
 "replace_group":"Nahrazuje celý předchozí ceník stejné skupiny",
 "replace_all":"Nahrazuje celý předchozí ceník dodavatele",
}

class PriceListImportCancelled(RuntimeError):
    pass


def _safe(value: object, maxlen: int = 120) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(value or "")).strip(" ._")
    return (text or "Bez_nazvu")[:maxlen]


def _norm(value: object) -> str:
    try:
        fn = getattr(ctx.M, "norm_name", None)
        if callable(fn):
            return str(fn(str(value or "")) or "")
    except Exception:
        pass
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r"\b(s\.?\s*r\.?\s*o\.?|a\.?\s*s\.?|spol\.?\s*s\.?\s*r\.?\s*o\.?)\b", "", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _number(value, default=0.0):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text or text in {"-", "—"}:
        return default
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9+\-.]", "", text)
    try:
        return float(text)
    except Exception:
        return default


def _iso_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            pass
    return text


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
