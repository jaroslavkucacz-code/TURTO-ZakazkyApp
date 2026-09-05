"""TURTO CRM 7.8 – professional issued-offer workflow and help centre.

This additive layer keeps the canonical PDF renderer and the existing business
document tables.  It adds a controlled preflight/release workflow, stale-PDF
detection, explicit sent confirmation and a searchable in-application handbook.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Iterable


def _text(value: Any, fallback: str = "") -> str:
    result = str(value or "").strip()
    return result or fallback


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace("\u00a0", " ").replace(" ", "").replace(",", ".")
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "ne", "no"}
    return bool(value)


def _widget_exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def _walk(widget: Any):
    yield widget
    try:
        for child in widget.winfo_children():
            yield from _walk(child)
    except Exception:
        return


def _parse_date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            pass
    return None


def _money(value: Any, currency: str = "CZK") -> str:
    return (
        f"{_number(value):,.2f}".replace(",", " ").replace(".", ",")
        + " "
        + (_text(currency, "CZK"))
    )


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", _text(value).casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


@dataclass(frozen=True)
class OfferCheck:
    code: str
    label: str
    level: str
    message: str
    section: str

    @property
    def blocking(self) -> bool:
        return self.level == "error"


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[OfferCheck, ...]

    @property
    def errors(self) -> tuple[OfferCheck, ...]:
        return tuple(check for check in self.checks if check.level == "error")

    @property
    def warnings(self) -> tuple[OfferCheck, ...]:
        return tuple(check for check in self.checks if check.level == "warning")

    @property
    def passed(self) -> tuple[OfferCheck, ...]:
        return tuple(check for check in self.checks if check.level == "ok")

    @property
    def ready(self) -> bool:
        return not self.errors

    @property
    def headline(self) -> str:
        if self.errors:
            return (
                f"Vydání blokuje {len(self.errors)} "
                f"{'chyba' if len(self.errors) == 1 else 'chyb'}."
            )
        if self.warnings:
            return (
                f"Nabídku lze vydat; zbývá {len(self.warnings)} "
                f"{'doporučení' if len(self.warnings) == 1 else 'doporučení'}."
            )
        return "Nabídka je připravena k vydání."


@dataclass(frozen=True)
class PdfState:
    status: str
    path: Path | None
    revision_no: int | None
    created_at: str
    current_fingerprint: str
    revision_fingerprint: str

    @property
    def label(self) -> str:
        revision = (
            f"R{int(self.revision_no):02d}"
            if self.revision_no is not None
            else "bez revize"
        )
        if self.status == "current":
            return f"Aktuální PDF · {revision}"
        if self.status == "stale":
            return f"PDF neodpovídá změnám · poslední {revision}"
        if self.status == "missing":
            return f"Soubor poslední revize chybí · {revision}"
        return "PDF zatím nebylo vydáno"


DOCUMENT_FINGERPRINT_FIELDS = (
    "document_number",
    "company_id",
    "customer_contact_id",
    "project_id",
    "project_name",
    "action_id",
    "action_name",
    "issue_date",
    "valid_to",
    "currency",
    "vat_mode",
    "global_discount_pct",
    "offer_subject",
    "customer_reference",
    "delivery_address",
    "customer_name_snapshot",
    "customer_address_snapshot",
    "customer_ico_snapshot",
    "customer_dic_snapshot",
    "customer_contact_snapshot",
    "customer_email_snapshot",
    "customer_phone_snapshot",
    "issuer_name_snapshot",
    "issuer_address_snapshot",
    "issuer_ico_snapshot",
    "issuer_dic_snapshot",
    "issuer_contact_snapshot",
    "issuer_email_snapshot",
    "issuer_phone_snapshot",
    "issuer_bank_snapshot",
    "salesperson_snapshot",
    "payment_terms",
    "delivery_terms",
    "delivery_time",
    "customer_note",
    "template_id",
)

ITEM_FINGERPRINT_FIELDS = (
    "row_type",
    "product_code",
    "name",
    "description",
    "quantity",
    "unit",
    "recommended_unit_price",
    "unit_price",
    "total_price",
    "vat_rate",
    "show_recommended_price",
    "category_id",
    "subgroup_id",
    "category_name_snapshot",
    "subgroup_name_snapshot",
    "internal_code_snapshot",
    "internal_name_snapshot",
    "supplier_presentation_snapshot",
    "supplier_name_snapshot",
    "name_note_snapshot",
    "line_note",
)


def _canonical(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def commercial_fingerprint(
    document: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> str:
    """Hash only customer-visible and price-defining offer content."""
    doc = {
        field: _canonical((document or {}).get(field))
        for field in DOCUMENT_FINGERPRINT_FIELDS
    }
    rows = []
    for position, raw in enumerate(list(items or []), 1):
        item = dict(raw or {})
        row = {"position": position}
        row.update(
            {
                field: _canonical(item.get(field))
                for field in ITEM_FINGERPRINT_FIELDS
            }
        )
        rows.append(row)
    payload = json.dumps(
        {"document": doc, "items": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_ASSET_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}


def _asset_digest(value: Any) -> str:
    path = Path(_text(value)) if _text(value) else None
    if path is None or not path.is_file():
        return ""
    try:
        stat = path.stat()
        key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
        cached = _ASSET_DIGEST_CACHE.get(key)
        if cached:
            return cached
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if len(_ASSET_DIGEST_CACHE) > 64:
            _ASSET_DIGEST_CACHE.clear()
        _ASSET_DIGEST_CACHE[key] = digest
        return digest
    except Exception:
        return ""


def template_fingerprint(M: Any, template_id: Any) -> str:
    """Fingerprint the actual page layout and header/footer assets."""
    try:
        from price_lists_domain.issued_offers import service

        template = service.load_template(
            M, int(template_id) if template_id else None
        )
    except Exception:
        template = {}
    fields = (
        "id",
        "name",
        "header_height_mm",
        "footer_height_mm",
        "margin_left_mm",
        "margin_right_mm",
        "body_top_gap_mm",
        "body_bottom_gap_mm",
        "header_every_page",
        "footer_every_page",
    )
    payload = {field: _canonical(template.get(field)) for field in fields}
    payload["header_asset"] = _asset_digest(template.get("header_path"))
    payload["footer_asset"] = _asset_digest(template.get("footer_path"))
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def release_fingerprint(
    M: Any,
    document: dict[str, Any],
    items: Iterable[dict[str, Any]],
) -> str:
    commercial = commercial_fingerprint(document, items)
    template = template_fingerprint(M, (document or {}).get("template_id"))
    return hashlib.sha256(
        (commercial + "|" + template).encode("utf-8")
    ).hexdigest()


def offer_preflight(
    document: dict[str, Any],
    items: Iterable[dict[str, Any]],
    *,
    for_email: bool = False,
) -> PreflightReport:
    """Return a deterministic commercial readiness report."""
    document = dict(document or {})
    items = [dict(item or {}) for item in list(items or [])]
    checks: list[OfferCheck] = []

    def add(
        condition: bool,
        code: str,
        label: str,
        ok_message: str,
        fail_message: str,
        section: str,
        fail_level: str = "error",
    ) -> None:
        checks.append(
            OfferCheck(
                code=code,
                label=label,
                level="ok" if condition else fail_level,
                message=ok_message if condition else fail_message,
                section=section,
            )
        )

    customer = _text(document.get("customer_name_snapshot"))
    add(
        bool(customer),
        "customer",
        "Odběratel",
        customer or "Odběratel je vyplněn.",
        "Vyberte nebo vyplňte odběratele.",
        "Odběratel",
    )
    address = _text(document.get("customer_address_snapshot"))
    add(
        bool(address),
        "customer_address",
        "Adresa odběratele",
        address or "Adresa je vyplněna.",
        "Doplňte adresu odběratele, aby byla nabídka obchodně úplná.",
        "Odběratel",
        "warning",
    )
    contact = _text(document.get("customer_contact_snapshot"))
    add(
        bool(contact),
        "contact",
        "Kontaktní osoba",
        contact or "Kontaktní osoba je vyplněna.",
        "Doporučujeme vybrat konkrétní kontaktní osobu.",
        "Odběratel",
        "warning",
    )
    email = _text(document.get("customer_email_snapshot"))
    add(
        bool(email) and "@" in email,
        "email",
        "E-mail zákazníka",
        email or "E-mail je vyplněn.",
        (
            "Pro přípravu e-mailu doplňte platnou adresu zákazníka."
            if for_email
            else "Doporučujeme doplnit e-mail zákazníka."
        ),
        "Odběratel",
        "error" if for_email else "warning",
    )

    subject = _text(document.get("offer_subject"))
    linked = bool(
        document.get("project_id")
        or document.get("action_id")
        or _text(document.get("project_name"))
        or _text(document.get("action_name"))
    )
    add(
        bool(subject or linked),
        "subject",
        "Předmět / akce",
        subject or _text(document.get("project_name") or document.get("action_name")),
        "Doplňte předmět nabídky nebo ji propojte s Akcí či Příležitostí.",
        "Dokument",
    )

    issue = _parse_date(document.get("issue_date"))
    add(
        issue is not None,
        "issue_date",
        "Datum vystavení",
        issue.strftime("%d.%m.%Y") if issue else "",
        "Datum vystavení není platné.",
        "Dokument",
    )
    valid_text = _text(document.get("valid_to"))
    valid = _parse_date(valid_text)
    valid_ok = bool(valid and issue and valid >= issue)
    if not valid_text:
        checks.append(
            OfferCheck(
                "validity",
                "Platnost nabídky",
                "warning",
                "Doporučujeme určit datum platnosti nabídky.",
                "Dokument",
            )
        )
    else:
        add(
            valid_ok,
            "validity",
            "Platnost nabídky",
            valid.strftime("%d.%m.%Y") if valid else "",
            (
                "Datum platnosti není platné nebo předchází datu vystavení."
            ),
            "Dokument",
        )

    currency = _text(document.get("currency"))
    add(
        currency in {"CZK", "EUR", "PLN"},
        "currency",
        "Měna",
        currency or "Měna je vyplněna.",
        "Vyberte podporovanou měnu CZK, EUR nebo PLN.",
        "Dokument",
    )
    issuer = _text(document.get("issuer_name_snapshot"))
    add(
        bool(issuer),
        "issuer",
        "Vystavitel",
        issuer or "Vystavitel je vyplněn.",
        "V nastavení vydaných nabídek doplňte údaje vystavitele.",
        "Dokument",
    )
    salesperson = _text(
        document.get("salesperson_snapshot")
        or document.get("issuer_contact_snapshot")
    )
    add(
        bool(salesperson),
        "salesperson",
        "Odpovědný obchodník",
        salesperson or "Obchodník je vyplněn.",
        "Doplňte obchodníka nebo kontaktní osobu vystavitele.",
        "Dokument",
        "warning",
    )
    add(
        bool(document.get("template_id")),
        "template",
        "PDF šablona",
        _text(document.get("template_name"), "Šablona je vybrána."),
        "Vyberte aktivní PDF šablonu.",
        "Dokument",
    )

    add(
        bool(items),
        "items",
        "Položky nabídky",
        f"Nabídka obsahuje {len(items)} řádků.",
        "Přidejte alespoň jednu položku.",
        "Položky",
    )
    priced_rows = [
        item
        for item in items
        if _text(item.get("row_type"), "product").casefold()
        not in {"heading", "text"}
    ]
    add(
        bool(priced_rows),
        "priced_items",
        "Oceněné položky",
        f"Oceněných řádků: {len(priced_rows)}.",
        "Nabídka musí obsahovat alespoň jednu oceněnou položku.",
        "Položky",
    )

    blank_headings: list[int] = []
    blank_texts: list[int] = []
    missing_names: list[int] = []
    invalid_quantities: list[int] = []
    missing_units: list[int] = []
    missing_identities: list[int] = []
    negative_prices: list[int] = []
    zero_prices: list[int] = []
    invalid_discounts: list[int] = []
    invalid_vat: list[int] = []

    for position, item in enumerate(items, 1):
        row_type = _text(item.get("row_type"), "product").casefold()
        if row_type == "heading":
            if not _text(item.get("name") or item.get("description")):
                blank_headings.append(position)
            continue
        if row_type == "text":
            if not _text(item.get("description") or item.get("name")):
                blank_texts.append(position)
            continue

        name = _text(
            item.get("name")
            or item.get("internal_name_snapshot")
            or item.get("description")
        )
        if not name:
            missing_names.append(position)
        if _number(item.get("quantity")) <= 0:
            invalid_quantities.append(position)
        if not _text(item.get("unit")):
            missing_units.append(position)
        supplier_presentation = _truthy(
            item.get("supplier_presentation_snapshot")
        )
        if row_type == "product" and not supplier_presentation:
            if not (
                _text(item.get("internal_code_snapshot"))
                and _text(item.get("internal_name_snapshot"))
            ):
                missing_identities.append(position)
        price = _number(item.get("unit_price"))
        if price < 0:
            negative_prices.append(position)
        elif price == 0:
            zero_prices.append(position)
        discount = _number(item.get("discount_pct"))
        if not 0 <= discount <= 100:
            invalid_discounts.append(position)
        vat = _number(item.get("vat_rate"), 21)
        if not 0 <= vat <= 100:
            invalid_vat.append(position)

    def positions(values: list[int]) -> str:
        shown = ", ".join(str(value) for value in values[:14])
        if len(values) > 14:
            shown += f" a dalších {len(values) - 14}"
        return shown

    def aggregate(
        code: str,
        label: str,
        section: str,
        problems: list[int],
        ok_message: str,
        fail_prefix: str,
        level: str = "error",
    ) -> None:
        checks.append(
            OfferCheck(
                code,
                label,
                level if problems else "ok",
                (
                    f"{fail_prefix} Řádky: {positions(problems)}."
                    if problems
                    else ok_message
                ),
                section,
            )
        )

    aggregate(
        "headings",
        "Nadpisy oddílů",
        "Položky",
        blank_headings,
        "Všechny vložené nadpisy mají text.",
        "Prázdné nadpisy odstraňte nebo doplňte.",
    )
    aggregate(
        "text_rows",
        "Textové řádky",
        "Položky",
        blank_texts,
        "Všechny textové řádky mají obsah.",
        "Prázdné textové řádky odstraňte nebo doplňte.",
    )
    aggregate(
        "item_names",
        "Zákaznická označení",
        "Položky",
        missing_names,
        "Všechny oceněné položky mají zákaznické označení.",
        "Chybí zákaznické označení.",
    )
    aggregate(
        "quantities",
        "Množství",
        "Položky",
        invalid_quantities,
        "Všechna množství jsou větší než nula.",
        "Množství musí být větší než nula.",
    )
    aggregate(
        "units",
        "Měrné jednotky",
        "Položky",
        missing_units,
        "Všechny oceněné položky mají měrnou jednotku.",
        "Doporučujeme doplnit měrnou jednotku.",
        "warning",
    )
    aggregate(
        "identities",
        "Interní identita TURTO",
        "Položky",
        missing_identities,
        "Všechny běžné produkty mají interní kód a název TURTO.",
        "Produkt nemá interní kód nebo interní název TURTO.",
    )
    aggregate(
        "negative_prices",
        "Záporné ceny",
        "Ceny",
        negative_prices,
        "Žádná prodejní cena není záporná.",
        "Prodejní cena nesmí být záporná.",
    )
    aggregate(
        "zero_prices",
        "Nulové ceny",
        "Ceny",
        zero_prices,
        "Všechny oceněné položky mají nenulovou prodejní cenu.",
        "Ověřte, zda je nulová prodejní cena záměr.",
        "warning",
    )
    aggregate(
        "discounts",
        "Slevy položek",
        "Ceny",
        invalid_discounts,
        "Všechny slevy jsou v rozsahu 0 až 100 %.",
        "Sleva musí být v rozsahu 0 až 100 %.",
    )
    aggregate(
        "vat",
        "Sazby DPH",
        "Ceny",
        invalid_vat,
        "Všechny sazby DPH jsou v platném rozsahu.",
        "Sazba DPH musí být v rozsahu 0 až 100 %.",
    )
    global_discount = _number(document.get("global_discount_pct"))
    add(
        0 <= global_discount <= 100,
        "global_discount",
        "Celková sleva",
        f"{global_discount:g} %",
        "Celková sleva musí být v rozsahu 0 až 100 %.",
        "Ceny",
    )
    add(
        bool(_text(document.get("payment_terms"))),
        "payment_terms",
        "Platební podmínky",
        _text(document.get("payment_terms")),
        "Doporučujeme doplnit platební podmínky.",
        "Podmínky",
        "warning",
    )
    add(
        bool(
            _text(document.get("delivery_terms"))
            or _text(document.get("delivery_time"))
        ),
        "delivery_terms",
        "Dodání",
        "Dodací podmínky nebo termín jsou vyplněny.",
        "Doporučujeme doplnit podmínky nebo termín dodání.",
        "Podmínky",
        "warning",
    )
    return PreflightReport(tuple(checks))


def _record_history(M: Any, document_id: int, event_type: str, note: str) -> None:
    try:
        from price_lists_domain.issued_offers import service

        user = service.active_user(M)
        with M.db() as con:
            con.execute(
                """INSERT INTO business_document_history(
                       document_id,event_type,note,user_name
                   ) VALUES(?,?,?,?)""",
                (int(document_id), _text(event_type), _text(note), user),
            )
    except Exception:
        pass


def pdf_state(M: Any, document_id: int) -> PdfState:
    from price_lists_domain.issued_offers import service

    document, items = service.load_document(M, int(document_id))
    current_commercial = commercial_fingerprint(document, items)
    current = release_fingerprint(M, document, items)
    try:
        with M.db() as con:
            row = con.execute(
                """SELECT revision_no,pdf_path,data_json,created_at
                     FROM business_document_revisions
                    WHERE document_id=?
                    ORDER BY revision_no DESC,id DESC LIMIT 1""",
                (int(document_id),),
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return PdfState("none", None, None, "", current, "")

    path = Path(_text(row["pdf_path"])) if _text(row["pdf_path"]) else None
    snapshot: dict[str, Any] = {}
    try:
        snapshot = json.loads(_text(row["data_json"], "{}"))
        if not isinstance(snapshot, dict):
            snapshot = {}
    except Exception:
        snapshot = {}
    revision_fingerprint = _text(snapshot.get("_release_fingerprint"))
    if revision_fingerprint:
        matching = revision_fingerprint == current
    else:
        # Revisions created before 7.8 did not store the template fingerprint.
        # Compare their commercial payload so they remain usable and immutable.
        revision_fingerprint = _text(snapshot.get("_commercial_fingerprint"))
        if not revision_fingerprint:
            revision_fingerprint = commercial_fingerprint(
                snapshot, list(snapshot.get("items") or [])
            )
        matching = revision_fingerprint == current_commercial
    if path is None or not path.is_file():
        status = "missing"
    elif bool(document.get("locked")):
        # A terminal document is immutable; its archived PDF remains the
        # authoritative historical output even if the global template changes.
        status = "current"
    elif matching:
        status = "current"
    else:
        status = "stale"
    return PdfState(
        status,
        path,
        int(row["revision_no"]) if row["revision_no"] is not None else None,
        _text(row["created_at"]),
        current,
        revision_fingerprint,
    )


def ensure_current_pdf(
    M: Any,
    document_id: int,
    *,
    force_revision: bool = False,
    open_after: bool = False,
) -> Path:
    """Reuse a matching immutable revision; otherwise call the canonical renderer."""
    from price_lists_domain.issued_offers import service

    state = pdf_state(M, int(document_id))
    document, _items = service.load_document(M, int(document_id))
    locked = bool(document.get("locked"))
    if (
        not force_revision
        and state.status == "current"
        and state.path is not None
        and state.path.is_file()
    ):
        if open_after:
            service.open_path(state.path)
        return state.path
    if locked and state.path is not None and state.path.is_file():
        # Historical terminal documents are immutable. Their archived PDF is the
        # authoritative output even if an older revision predates fingerprints.
        if open_after:
            service.open_path(state.path)
        return state.path
    return Path(
        M.render_issued_offer_pdf(
            int(document_id), output_path=None, open_after=open_after
        )
    )


HELP_TOPICS: dict[str, dict[str, Any]] = {
    "help_start": {
        "category": "Začínáme",
        "title": "Rychlý start a logika TURTO CRM",
        "summary": "Jak spolu souvisejí společnosti, osoby, Akce, Příležitosti, Poptávky, přijaté a vydané nabídky.",
        "keywords": "začátek přehled tok workflow první kroky",
        "body": """## Základní obchodní tok

Společnost → Osoba → Akce → Příležitost → Poptávka → Přijatá nabídka → Vydaná nabídka → Úkol

TURTO CRM odděluje kontaktní data, obchodní případ a obchodní dokumenty. Společnost a Osoba tvoří adresář. Akce představuje stavbu nebo projekt. Příležitost popisuje konkrétní obchodní možnost u dané společnosti. Poptávka zaznamenává, co bylo odesláno dodavateli. Přijatá nabídka uchovává původní dodavatelské podklady. Vydaná nabídka je samostatný zákaznický dokument se svou cenou, revizemi a historií.

## Doporučený první postup

1. Zkontrolujte nebo založte Společnost a kontaktní Osobu.
2. Založte Akci a Příležitost, aby byla pozdější komunikace dohledatelná.
3. Z Příležitosti vytvořte Poptávku a vyberte dodavatele.
4. Po doručení nabídku přetáhněte z Outlooku nebo načtěte jako PDF.
5. Z přijaté nabídky připravte Vydanou nabídku, upravte ceny a proveďte kontrolu před vydáním.
6. Po skutečném odeslání potvrďte stav Odesláno.

TIP: Dvojklik na datový řádek obvykle otevře detail. Pravé tlačítko nabízí kontextové akce. Záhlaví sloupců slouží k řazení a nastavení zobrazení.""",
    },
    "help_navigation": {
        "category": "Začínáme",
        "title": "Orientace, tabulky a filtry",
        "summary": "Vyhledávání, řazení, vlastní sloupce a práce s rozsáhlými tabulkami.",
        "keywords": "tabulka filtr sloupec řazení pravé tlačítko zobrazení",
        "body": """## Práce s tabulkami

Filtrační pole jsou umístěna nad odpovídajícími sloupci. Zadaný text se u většiny přehledů uplatní průběžně. Tlačítko Zrušit filtry vrátí základní pohled. Kliknutí na název sloupce mění směr řazení.

Pravým tlačítkem na záhlaví lze u podporovaných tabulek otevřít správu sloupců. Program si šířku, pořadí a viditelnost pamatuje. Obnovení výchozích sloupců vrátí bezpečné základní rozložení.

## Výběr řádků

Jeden řádek vyberete kliknutím. Více řádků vyberete pomocí Ctrl nebo Shift. Dvojklik otevírá detail pouze tehdy, když je ukazatel skutečně nad datovým řádkem; dvojklik na záhlaví nic neotevře.

## Našeptávací pole

Do pole lze psát i vybírat myší. Psaní seznam zužuje. Hodnota musí odpovídat existující položce tam, kde je vyžadována vazba na databázi. U volných textů lze ponechat vlastní zápis.

TIP: Pokud se po aktualizaci zdá tabulka příliš široká, použijte pravé tlačítko na záhlaví a Obnovit výchozí sloupce.""",
    },
    "help_actions": {
        "category": "Obchod",
        "title": "Příležitosti a obchodní případ",
        "summary": "Založení obchodní příležitosti, odpovědnost, termíny, historie a návazné dokumenty.",
        "keywords": "příležitost obchodník co se řeší termín historie sloučit",
        "body": """## Kdy založit Příležitost

Příležitost založte pro konkrétní obchodní možnost u konkrétní společnosti. Vyplňte název, co se řeší, odpovědného obchodníka, stav a nejbližší termín. Jedna Akce může mít více Příležitostí u různých firem.

## Návaznosti

Z detailu Příležitosti lze založit Poptávku. Vazba se uloží, takže je později zřejmé, proč poptávka vznikla a kdo ji řešil. Přijaté i vydané nabídky je vhodné spojit se stejnou Akcí nebo Příležitostí.

## Stavy a termíny

Rozpracovaná Příležitost zůstává v aktivních pohledech. Hotovo a Zrušeno ji vyřadí z běžného pracovního seznamu, historie se však nemaže. Termíny blížící se do několika dnů jsou zvýrazněné.

## Sloučení

Sloučení převede vazby na cílovou Akci nebo Příležitost podle konkrétního dialogu. Historické snapshoty již vydaných dokumentů se zpětně nepřepisují.

POZOR: Přejmenování Akce mění aktuální databázový název, nikoli text dříve vytvořeného PDF. Vydané PDF je neměnná revize.""",
    },
    "help_requests": {
        "category": "Obchod",
        "title": "Poptávky dodavatelům",
        "summary": "Příjemci, předmět, Outlook koncept, čekající odpověď a zvláštní režim MIVO.",
        "keywords": "poptávka dodavatel odběratel outlook příjemce MIVO bez odezvy",
        "body": """## Založení Poptávky

Vyberte Dodavatele. Odběratel, Akce a Příležitost doplňte vždy, když jsou známé; výrazně to usnadní pozdější dohledání nabídky. Kontaktní osoby se nabízejí podle vybrané společnosti.

Poptávku lze uložit bez příjemce a adresu doplnit až v Outlooku. Tlačítko Přidat osobu založí nový kontakt u právě vybrané společnosti.

## E-mail

Vytvořit e-mail připraví koncept. Program doplní předmět, základní text a trvalou kopii na firemní adresu. Koncept zkontrolujte a odešlete v Outlooku. Uložený koncept není sám o sobě odeslaná zpráva.

## Odpověď dodavatele

Datum Obdrženo znamená, že přišla odpověď. Do té doby je Poptávka čekající. Stav Bez odezvy použijte u starší komunikace, kterou již nechcete dále urgovat.

## MIVO

Poptávky směrované na MIVO jsou oddělené do vlastní sekce. Mají zjednodušený přehled a volnější předmět, ale stále mohou být spojené s Akcí, Příležitostí a termínem.""",
    },
    "help_received_offers": {
        "category": "Nabídky",
        "title": "Přijaté nabídky a původní dodavatelská data",
        "summary": "Import PDF nebo MSG, zachování zdroje, obrázky, přepočet a vytvoření zákaznické nabídky.",
        "keywords": "přijatá nabídka PDF MSG drag drop parser dodavatel obrázek PLEXUS",
        "body": """## Import

Přijatou nabídku lze načíst z podporovaného PDF nebo přetáhnout z Outlooku jako zprávu MSG. Program nejprve archivuje zdroj a poté zpracuje položky. Původní soubor zůstává oddělený od zákaznické nabídky.

## Kontrola po importu

Ověřte číslo nabídky, dodavatele, měnu, množství, jednotky, jednotkové ceny a technické popisy. U výrobků PLEXUS zkontrolujte také přiřazený typ a obrázek. Červené zvýraznění se přenáší pouze z míst, která jsou červená v originálu.

## Vytvoření vydané nabídky

Položky lze převzít do Vydané nabídky bez automatického založení katalogových karet. Dodavatelský název zůstává zachovaný. Vlastní doplnění se připojuje jako dodatek, nepřepisuje původní označení.

POZOR: Přijatá nabídka je nákupní podklad. Zákaznická cena, marže, sleva a text pro zákazníka se řeší až ve Vydané nabídce.""",
    },
    "help_catalog_pricing": {
        "category": "Nabídky",
        "title": "Katalog produktů, skupiny a cenová pravidla",
        "summary": "Interní označení TURTO, nákupní ceny, skupiny, podskupiny, marže a slevy.",
        "keywords": "katalog produkt cena marže sleva skupina podskupina ceník",
        "body": """## Úloha katalogu

Katalog obsahuje interní kód a interní název TURTO. Dodavatelské kódy a názvy jsou vedené jako zdroje. Díky tomu může jedna zákaznická položka čerpat ceny z více ceníků, aniž by se měnila její identita.

## Cenová hierarchie

Výchozí marže a sleva mohou pocházet ze skupiny, podskupiny nebo přímo z produktu. Ve Vydané nabídce se ukládá snapshot použitého základu. Pozdější změna pravidla proto nepřepíše již uloženou nabídku.

## Aktuální nákupní cena

Program upřednostňuje platný strukturovaný ceník. OCR nebo kontrolní zdroje nejsou automaticky považované za autoritativní. U každé ceny sledujte uvedený zdroj a datum platnosti.

## Nezařazené produkty

Produkt bez interního kódu nebo názvu nelze vydat jako běžnou katalogovou položku. Doplňte identitu v Katalogu. Výjimkou je řádek převzatý z Přijaté nabídky v režimu zachování dodavatelského označení.""",
    },
    "help_issued_offers": {
        "category": "Vydané nabídky",
        "title": "Vydaná nabídka – profesionální pracovní postup",
        "summary": "Od konceptu přes kontrolu cen a živý náhled až k vydání zákaznického PDF.",
        "keywords": "vydaná nabídka koncept zákazník položky cena náhled vydat",
        "body": """## 1. Odběratel a vazby

Vyberte odběratele, kontaktní osobu, Akci nebo Příležitost a doplňte předmět. Datum vystavení a platnost jsou součástí obchodního dokumentu. Obchodník a PDF šablona určují kontaktní údaje a vzhled výstupu.

## 2. Položky a ceny

Položky přidejte z Katalogu, ručně nebo převzetím z Přijaté nabídky. U každé oceněné položky zkontrolujte množství, MJ, nákupní cenu, marži, doporučenou cenu, slevu, prodejní cenu a DPH. Nadpisy a textové řádky umožňují nabídku přehledně členit.

## 3. Zákaznický text

Označení a Popis pro zákazníka se zobrazují v PDF. Interní poznámka se zákazníkovi nezobrazuje. Platební, dodací a termínové podmínky patří do samostatných polí, aby byly v dokumentu konzistentní.

## 4. Živý náhled

Vizuální náhled používá stejný renderer jako finální PDF. Dvojklikem lze upravit řádek přímo v náhledu. Datová tabulka zobrazuje podrobné interní cenové údaje.

## 5. Kontrola a vydání

Tlačítko Zkontrolovat a vydat otevře předletovou kontrolu. Chyby musí být opravené. Doporučení lze vědomě ponechat. Teprve poté vznikne číslovaná a archivovaná PDF revize.

KLÁVESY: Ctrl+S uloží koncept, Ctrl+Enter otevře kontrolu před vydáním, F1 otevře tuto nápovědu.""",
    },
    "help_offer_release": {
        "category": "Vydané nabídky",
        "title": "Kontrola a řízené vydání nabídky",
        "summary": "Co kontroluje preflight, co blokuje vydání a jak vzniká revize.",
        "keywords": "preflight kontrola vydání chyba doporučení revize připraveno",
        "body": """## Předletová kontrola

Kontrola před vydáním ověřuje odběratele, datum, platnost, měnu, předmět nebo vazbu na Akci, PDF šablonu, oceněné položky, množství, zákaznické názvy, interní identitu TURTO, ceny, slevy, DPH a obchodní podmínky.

Červená chyba vydání blokuje. Oranžové doporučení upozorňuje na neúplnost, ale dokument lze vydat. Zelená kontrola je splněná.

## Vydání PDF

Po vydání se stav rozpracovaného dokumentu změní na Připraveno. Finální PDF vytvoří kanonický A4 renderer a uloží jej do archivu nabídky. Současně vznikne revize se snapshotem dat a SHA-256 souboru.

Pokud se od poslední revize nic obchodně významného nezměnilo, program použije stejné aktuální PDF. Pokud se změnil odběratel, položka, cena, text, podmínky nebo šablona, vytvoří novou revizi.

## Nová revize bez změny

Volbu Vytvořit novou revizi i bez změny použijte pouze tehdy, když potřebujete nový časově evidovaný výstup. Běžné opakované otevření nemá vytvářet zbytečné revize.

POZOR: Odeslaný nebo jinak uzamčený dokument se neupravuje. Pro změnu zákaznického obsahu vytvořte duplikát a vydejte nový dokument.""",
    },
    "help_prices_vat": {
        "category": "Vydané nabídky",
        "title": "Ceny, marže, slevy a DPH",
        "summary": "Výpočet jednotkové a celkové ceny, globální sleva a význam interních cenových polí.",
        "keywords": "cena nákupní marže doporučená sleva prodejní DPH globální",
        "body": """## Výpočet položky

Doporučená cena = nákupní cena × (1 + marže / 100)

Prodejní cena = doporučená cena × (1 − sleva / 100)

Celkem za položku = množství × prodejní cena

Nákupní cena, marže a zdroj cenového pravidla jsou interní údaje. Zákaznický PDF výstup používá prodejní cenu a celkovou cenu podle nastavení produktové skupiny.

## Celková sleva

Celková sleva se uplatní na součet oceněných položek. DPH se následně počítá z částek po této slevě podle sazby jednotlivých řádků.

## Kontrolní zásady

Nulová cena je povolená, ale kontrola ji označí jako doporučení k ověření. Záporná cena, sleva mimo 0–100 % nebo neplatná DPH vydání blokují.

TIP: Ruční přepsání Prodejní ceny je možné. Tlačítko Přepočítat znovu odvodí doporučenou a prodejní cenu z nákupní ceny, marže a slevy.""",
    },
    "help_pdf_revisions": {
        "category": "Vydané nabídky",
        "title": "PDF, revize, archiv a neměnnost",
        "summary": "Kde jsou soubory, jak se číslují revize a proč se staré PDF nepřepisuje.",
        "keywords": "PDF revize archiv R00 SHA hash složka soubor",
        "body": """## Číslování

Číslo nabídky má formát CNrr-00000. Přidělí se při prvním uložení dokumentu. PDF revize mají označení R00, R01 a dále.

## Archiv

Každá nabídka má vlastní složku v archivu vydaných nabídek. Program ukládá cestu, velikost a SHA-256 každé revize spolu se snapshotem obchodních dat.

## Aktuálnost PDF

Program porovnává zákaznický obsah a ceny s poslední revizí. Stav Aktuální PDF znamená, že poslední soubor odpovídá datům. Stav PDF neodpovídá změnám znamená, že je nutné dokument znovu vydat.

## Neměnnost

Staré PDF se nepřepisuje. Nová změna vytváří novou revizi. Historie tak umožňuje zpětně prokázat, co bylo v určitém okamžiku vydáno.

POZOR: Ruční přesunutí nebo smazání archivního PDF způsobí stav Soubor chybí. Databázová historie zůstane, ale soubor bude nutné obnovit ze zálohy nebo vytvořit novou revizi u neuzamčeného dokumentu.""",
    },
    "help_outlook": {
        "category": "Vydané nabídky",
        "title": "Příprava nabídky v Outlooku a potvrzení odeslání",
        "summary": "Bezpečný rozdíl mezi vytvořeným konceptem a skutečně odeslanou nabídkou.",
        "keywords": "Outlook koncept odesláno potvrdit příloha e-mail podpis",
        "body": """## Připravit e-mail

Program nejprve ověří e-mail zákazníka a aktuálnost PDF. Poté otevře Outlook koncept, doplní adresáta, trvalou kopii, předmět, průvodní text a připojí aktuální PDF revizi. Existující Outlook podpis zůstává zachovaný.

## Koncept není odeslaný e-mail

Otevření konceptu nemění stav nabídky na Odesláno. Dokument zůstane Připraveno. Zprávu lze v Outlooku upravit, uložit, zavřít nebo odeslat.

## Potvrdit odeslání

Po skutečném odeslání v Outlooku použijte Potvrdit odeslání. Program zobrazí výslovné potvrzení a teprve potom nastaví stav Odesláno, uloží čas a dokument uzamkne.

POZOR: Potvrzení používejte jen po ověření, že zpráva je ve složce Odeslaná pošta. CRM nečte stav odeslání přímo z Outlook serveru.

## Opakované zaslání

U již odeslané nabídky lze znovu otevřít koncept s archivovaným PDF. Obsah uzamčeného dokumentu se přitom nemění. Pro cenovou nebo textovou změnu vytvořte duplikát.""",
    },
    "help_statuses": {
        "category": "Vydané nabídky",
        "title": "Stavy vydané nabídky",
        "summary": "Význam stavů Rozpracováno, Připraveno, Odesláno, Přijato, Zamítnuto a Zrušeno.",
        "keywords": "stav rozpracováno připraveno odesláno přijato zamítnuto zrušeno",
        "body": """## Rozpracováno

Koncept lze libovolně měnit a ukládat. Číslo nabídky se přidělí při prvním uložení.

## Připraveno

Nabídka prošla kontrolou a má aktuální PDF nebo je připravená k jeho vytvoření. Stále ji lze upravit; změna však zneplatní aktuálnost posledního PDF a vyžádá novou revizi.

## Odesláno

Uživatel potvrdil skutečné odeslání. Uloží se čas a dokument se uzamkne.

## Přijato

Zákazník nabídku přijal. Jde o terminální a uzamčený stav.

## Zamítnuto a Zrušeno

Zamítnuto vyjadřuje rozhodnutí zákazníka. Zrušeno používá vystavitel pro dokument, který již nemá pokračovat. Oba stavy jsou uzamčené.

TIP: Archivace není obchodní stav. Pouze přesune dokument mimo základní aktivní pohled, aniž by měnila jeho historii.""",
    },
    "help_projects_tasks": {
        "category": "Organizace",
        "title": "Akce, úkoly a připomínky",
        "summary": "Projektová vazba, odpovědnost a práce s termíny.",
        "keywords": "akce projekt úkol připomínka deadline termín mapa",
        "body": """## Akce

Akce seskupuje Příležitosti, Poptávky a Nabídky patřící k jedné stavbě nebo projektu. Lze evidovat adresu, GPS, investora, generálního dodavatele a časový rámec.

## Úkol

Úkol má text, termín, odpovědného uživatele a volitelnou vazbu na Příležitost. Dokončený úkol zůstává v historii.

## Připomínky

K jedné Příležitosti lze přidat více připomínek s různým termínem a popisem. Přehled zvýrazňuje položky po termínu a nejbližší kroky.

TIP: U vydané nabídky si po odeslání vytvořte úkol na kontrolu reakce zákazníka před koncem platnosti.""",
    },
    "help_directory": {
        "category": "Organizace",
        "title": "Společnosti, osoby a ARES",
        "summary": "Oficiální názvy, IČO, sídlo, kontakty a bezpečné sloučení duplicit.",
        "keywords": "společnost osoba kontakt ARES IČO DIČ sloučit duplicita",
        "body": """## Společnosti

Používejte oficiální název, IČO, DIČ a sídlo. Ověření přes ARES doplní veřejné údaje, ručně zadané obchodní informace však kontrolujte samostatně.

## Osoby

Osoba je propojena se společností interním ID. Tato vazba řídí nabídku příjemců v Poptávkách i Vydaných nabídkách.

## Sloučení duplicit

Sloučení převede aktuální vazby na jednu cílovou společnost. Historické snapshoty v již vydaných dokumentech a PDF zůstávají neměnné, aby se nezměnil původní obchodní doklad.

POZOR: Před vydáním nabídky zkontrolujte, že vybraná kontaktní osoba má aktuální e-mail. Příprava Outlook konceptu bez platné adresy je blokována.""",
    },
    "help_data_updates": {
        "category": "Správa a bezpečnost",
        "title": "Data, zálohy, aktualizace a návrat verze",
        "summary": "Kde jsou pracovní data a jak program chrání databázi při aktualizaci.",
        "keywords": "databáze záloha aktualizace rollback návrat verze data",
        "body": """## Oddělení programu a dat

Pracovní databáze je uložena mimo instalační složku programu v Dokumentech uživatele. Aktualizace proto vyměňuje programové soubory, nikoli pracovní data.

## Automatická aktualizace

CRM pravidelně kontroluje oficiální kanál, ověří balíček pomocí SHA-256 a spustí interní aktualizátor. Před instalací se vytvoří konzistentní SQLite záloha databáze a ZIP snapshot současné verze programu.

## Návrat předchozí verze

V Nastavení lze použít uložený rollback balíček. Návrat mění programové soubory, ale ponechává pracovní databázi. I před návratem vznikne nová záloha.

## Vlastní záloha

Před hromadným importem nebo větším čištěním doporučujeme vytvořit také ruční export. Zkontrolovat data provádí kontrolu integrity a vazeb; samo záznamy nemaže.

POZOR: Instalační ZIP není záloha databáze. Obchodní data jsou v uživatelské datové složce.""",
    },
    "help_shortcuts": {
        "category": "Správa a bezpečnost",
        "title": "Klávesové zkratky a rychlé ovládání",
        "summary": "Nejdůležitější klávesy v CRM a editoru nabídky.",
        "keywords": "klávesy zkratky Ctrl Enter Escape F1 F5",
        "body": """## Obecně

Enter potvrzuje běžný dialog, pokud kurzor není ve víceřádkovém textu. Escape dialog zavře nebo zruší. Dvojklik otevírá vybraný řádek.

## Editor vydané nabídky

Ctrl+S — uložit koncept
Ctrl+Enter — otevřít kontrolu a vydání
F1 — otevřít nápovědu k vydaným nabídkám
F5 — obnovit živý náhled PDF
Ctrl+kolečko — přiblížit nebo oddálit PDF náhled
Ctrl+0 — náhled 100 %

## Tabulky

Kliknutí na záhlaví — řazení
Ctrl+klik — nesouvislý vícenásobný výběr
Shift+klik — souvislý výběr
Pravé tlačítko na záhlaví — sloupce
Pravé tlačítko na řádku — kontextové akce""",
    },
    "help_troubleshooting": {
        "category": "Správa a bezpečnost",
        "title": "Řešení nejčastějších potíží",
        "summary": "Náhled PDF, Outlook, chybějící cena, aktualizace a diagnostika.",
        "keywords": "chyba problém nefunguje náhled Outlook PDF cena aktualizace",
        "body": """## Náhled PDF se neobnovil

Přepněte na Datovou tabulku, ověřte povinné údaje a stiskněte F5. Poslední platný náhled zůstává zachovaný. Finální vydání vždy znovu provede kontrolu.

## Outlook koncept se neotevřel

Ověřte, že je nainstalovaný desktopový Outlook a že je dostupný profil. PDF zůstává uložené v archivu. Stav se na Odesláno nezmění.

## Kontrola hlásí chybějící identitu TURTO

Otevřete produkt v Katalogu a doplňte interní kód i interní název. U položek převzatých z Přijaté nabídky lze zachovat dodavatelský název bez zákaznického kódu.

## PDF neodpovídá změnám

Od posledního vydání se změnil zákaznický obsah nebo cena. Otevřete Zkontrolovat a vydat a vytvořte novou revizi.

## Aktualizace se nestáhla

Zkontrolujte internetové připojení a spusťte ruční kontrolu v Nastavení. Při dočasné síťové chybě zůstává program beze změny a kontrolu zopakuje později.

## Program po aktualizaci nestartuje

Použijte uložený nouzový aktualizační nebo rollback postup. Databázi nemažte ani nepřesouvejte. Pro diagnostiku zachovejte soubory logů a poslední zálohu.""",
    },
}


class HelpCentre:
    def __init__(self, M: Any, app: Any):
        self.M = M
        self.app = app
        self.page = app.tabs["help"]
        self.query = M.tk.StringVar(value="")
        self.status = M.tk.StringVar(value="")
        self.current = "help_start"
        self._build()

    def _build(self) -> None:
        M = self.M
        for child in self.page.winfo_children():
            child.destroy()

        header = M.ttk.Frame(self.page, style="App.TFrame")
        header.pack(fill="x", pady=(0, 10))
        left = M.ttk.Frame(header, style="App.TFrame")
        left.pack(side="left", fill="x", expand=True)
        M.ttk.Label(
            left, text="Nápověda a pracovní postupy", style="Title.TLabel"
        ).pack(anchor="w")
        M.ttk.Label(
            left,
            text=(
                "Vyhledávatelný průvodce CRM, nabídkami, cenami, "
                "Outlookem, daty a řešením potíží"
            ),
            style="PageSubtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        search = M.ttk.Frame(self.page, style="Panel.TFrame", padding=(10, 8))
        search.pack(fill="x", pady=(0, 8))
        M.ttk.Label(search, text="Hledat v nápovědě", style="FilterLabel.TLabel").pack(
            side="left", padx=(0, 8)
        )
        entry = M.ttk.Entry(search, textvariable=self.query)
        entry.pack(side="left", fill="x", expand=True)
        M.ttk.Button(
            search, text="Vymazat", command=lambda: self.query.set("")
        ).pack(side="left", padx=(7, 0))
        M.ttk.Label(
            search, textvariable=self.status, style="PageSubtitle.TLabel"
        ).pack(side="right", padx=(12, 0))

        body = M.ttk.Panedwindow(self.page, orient="horizontal")
        body.pack(fill="both", expand=True)
        navigation = M.ttk.Frame(body, style="Panel.TFrame", padding=8)
        article = M.ttk.Frame(body, style="Card.TFrame", padding=0)
        body.add(navigation, weight=1)
        body.add(article, weight=4)
        navigation.columnconfigure(0, weight=1)
        navigation.rowconfigure(0, weight=1)
        article.columnconfigure(0, weight=1)
        article.rowconfigure(0, weight=1)

        self.tree = M.ttk.Treeview(
            navigation, show="tree", selectmode="browse", height=25
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        nav_scroll = M.ttk.Scrollbar(
            navigation, orient="vertical", command=self.tree.yview
        )
        nav_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=nav_scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._selected, add="+")

        self.text = M.tk.Text(
            article,
            wrap="word",
            font=("Calibri", 11),
            relief="flat",
            borderwidth=0,
            padx=24,
            pady=20,
            spacing1=1,
            spacing3=4,
        )
        text_scroll = M.ttk.Scrollbar(
            article, orient="vertical", command=self.text.yview
        )
        self.text.configure(yscrollcommand=text_scroll.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        text_scroll.grid(row=0, column=1, sticky="ns")
        self._configure_tags()

        self.query.trace_add("write", lambda *_: self._schedule_index())
        self._index_after = None
        self.rebuild_index()
        self.show("help_start")
        entry.bind("<Escape>", lambda _event: (self.query.set(""), "break")[1])
        self.search_entry = entry

    def _configure_tags(self) -> None:
        tags = {
            "title": {"font": ("Calibri", 20, "bold"), "spacing3": 12},
            "summary": {
                "font": ("Calibri", 11),
                "foreground": "#5b6670",
                "spacing3": 16,
            },
            "h2": {
                "font": ("Calibri", 14, "bold"),
                "foreground": "#17324a",
                "spacing1": 14,
                "spacing3": 6,
            },
            "step": {
                "font": ("Calibri", 11, "bold"),
                "foreground": "#17324a",
                "lmargin1": 8,
                "lmargin2": 28,
            },
            "bullet": {"lmargin1": 12, "lmargin2": 30},
            "tip": {
                "font": ("Calibri", 10, "bold"),
                "foreground": "#5b4308",
                "background": "#f7edcb",
                "lmargin1": 10,
                "lmargin2": 10,
                "rmargin": 10,
                "spacing1": 8,
                "spacing3": 8,
            },
            "warning": {
                "font": ("Calibri", 10, "bold"),
                "foreground": "#6c2020",
                "background": "#f5dddd",
                "lmargin1": 10,
                "lmargin2": 10,
                "rmargin": 10,
                "spacing1": 8,
                "spacing3": 8,
            },
            "keys": {
                "font": ("Calibri", 10, "bold"),
                "foreground": "#244d7a",
                "background": "#e7f0f8",
                "lmargin1": 10,
                "lmargin2": 10,
                "rmargin": 10,
                "spacing1": 8,
                "spacing3": 8,
            },
            "footer": {
                "font": ("Calibri", 9),
                "foreground": "#7a8288",
                "spacing1": 18,
            },
        }
        for name, options in tags.items():
            try:
                self.text.tag_configure(name, **options)
            except Exception:
                pass

    def _schedule_index(self) -> None:
        try:
            if self._index_after is not None:
                self.page.after_cancel(self._index_after)
        except Exception:
            pass
        try:
            self._index_after = self.page.after(120, self.rebuild_index)
        except Exception:
            self._index_after = None
            self.rebuild_index()

    def rebuild_index(self) -> None:
        self._index_after = None
        query = _fold(self.query.get())
        words = [word for word in query.split() if word]
        matches: list[tuple[str, dict[str, Any]]] = []
        for key, topic in HELP_TOPICS.items():
            haystack = _fold(
                " ".join(
                    (
                        topic["title"],
                        topic["summary"],
                        topic["keywords"],
                        topic["body"],
                    )
                )
            )
            if all(word in haystack for word in words):
                matches.append((key, topic))

        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        categories: dict[str, str] = {}
        for key, topic in matches:
            category = topic["category"]
            parent = categories.get(category)
            if parent is None:
                parent = "category:" + _fold(category).replace(" ", "_")
                categories[category] = parent
                self.tree.insert(
                    "",
                    "end",
                    iid=parent,
                    text=category,
                    open=True,
                    tags=("category",),
                )
            self.tree.insert(parent, "end", iid=key, text=topic["title"])
        self.status.set(
            f"{len(matches)} "
            + ("téma" if len(matches) == 1 else ("témata" if 2 <= len(matches) <= 4 else "témat"))
        )
        if self.current in {key for key, _topic in matches}:
            try:
                self.tree.selection_set(self.current)
                self.tree.see(self.current)
            except Exception:
                pass
        elif matches:
            self.show(matches[0][0], select=True)
        else:
            self._render_no_results()

    def _selected(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        key = str(selection[0])
        if key in HELP_TOPICS:
            self.show(key, select=False)

    def _render_no_results(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", "Nic jsme nenašli\n", "title")
        self.text.insert(
            "end",
            "Zkuste kratší výraz, například nabídka, Outlook, cena, "
            "aktualizace nebo záloha.",
            "summary",
        )
        self.text.configure(state="disabled")

    def show(self, key: str, *, select: bool = True) -> None:
        if key not in HELP_TOPICS:
            key = "help_start"
        if self.query.get() and not self.tree.exists(key):
            self.query.set("")
            try:
                self.page.after(130, lambda: self.show(key))
            except Exception:
                pass
            return
        self.current = key
        topic = HELP_TOPICS[key]
        if select and self.tree.exists(key):
            try:
                self.tree.selection_set(key)
                self.tree.see(key)
            except Exception:
                pass

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", topic["title"] + "\n", "title")
        self.text.insert(
            "end", topic["summary"] + "\n\n", "summary"
        )
        for raw_line in topic["body"].splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                self.text.insert("end", "\n")
            elif stripped.startswith("## "):
                self.text.insert("end", stripped[3:] + "\n", "h2")
            elif re.match(r"^\d+\.\s", stripped):
                self.text.insert("end", stripped + "\n", "step")
            elif stripped.startswith("- "):
                self.text.insert("end", "• " + stripped[2:] + "\n", "bullet")
            elif stripped.startswith("TIP:"):
                self.text.insert("end", "  " + stripped + "  \n", "tip")
            elif stripped.startswith("POZOR:"):
                self.text.insert("end", "  " + stripped + "  \n", "warning")
            elif stripped.startswith("KLÁVESY:"):
                self.text.insert("end", "  " + stripped + "  \n", "keys")
            else:
                self.text.insert("end", stripped + "\n")
        self.text.insert(
            "end",
            f"\nTURTO CRM {getattr(self.M, 'APP_VERSION', '')} · "
            "Vytvořil Ing. Jaroslav Kučera",
            "footer",
        )
        self.text.configure(state="disabled")
        self.text.yview_moveto(0.0)


def _open_help_topic(M: Any, app: Any, key: str) -> None:
    try:
        app.show_page("help")
    except Exception:
        pass

    def show() -> None:
        centre = getattr(app, "_v780_help_centre", None)
        if centre is not None:
            centre.show(key)
            return
        callback = getattr(app, "show_help_topic", None)
        if callable(callback):
            callback(key)

    try:
        app.after(40, show)
    except Exception:
        show()


def _document_summary(
    document: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, str]:
    from price_lists_domain.issued_offers import service

    totals = service.calculate_totals(
        items, document.get("global_discount_pct")
    )
    currency = _text(document.get("currency"), "CZK")
    priced = sum(
        1
        for item in items
        if _text(item.get("row_type"), "product").casefold()
        not in {"heading", "text"}
    )
    return {
        "Číslo": _text(document.get("document_number"), "bude přiděleno při uložení"),
        "Odběratel": _text(document.get("customer_name_snapshot"), "není vybrán"),
        "Kontakt": _text(document.get("customer_contact_snapshot"), "není vybrán"),
        "E-mail": _text(document.get("customer_email_snapshot"), "není vyplněn"),
        "Předmět": _text(
            document.get("offer_subject")
            or document.get("project_name")
            or document.get("action_name"),
            "není vyplněn",
        ),
        "Platnost": _text(document.get("valid_to"), "bez omezení"),
        "Položky": f"{priced} oceněných / {len(items)} řádků",
        "Celkem bez DPH": _money(totals.subtotal_net, currency),
        "Celkem s DPH": _money(totals.total_gross, currency),
        "Šablona": _text(document.get("template_name"), "vybraná šablona"),
    }


class OfferReleaseDialog:
    def __init__(
        self,
        M: Any,
        app: Any,
        *,
        editor: Any = None,
        document_id: int | None = None,
        initial_action: str = "release",
    ):
        self.M = M
        self.app = app
        self.editor = editor
        self.document_id = (
            int(document_id)
            if document_id
            else int(getattr(editor, "document_id", 0) or 0) or None
        )
        self.initial_action = initial_action
        self.force_revision = M.tk.BooleanVar(value=False)
        self.report: PreflightReport | None = None
        self.document: dict[str, Any] = {}
        self.items: list[dict[str, Any]] = []
        self.win = M.tk.Toplevel(
            getattr(editor, "win", None) if editor is not None else app
        )
        self.win.title("Kontrola a vydání cenové nabídky")
        self.win.transient(
            getattr(editor, "win", None) if editor is not None else app
        )
        self.win.grab_set()
        M.enable_dialog_maximize(self.win, 1120, 760)
        self._build()
        self.refresh()
        try:
            M.center_dialog(
                self.win,
                getattr(editor, "win", None) if editor is not None else app,
            )
        except Exception:
            pass

    def _build(self) -> None:
        M = self.M
        outer = M.ttk.Frame(self.win, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        title = M.ttk.Frame(outer, style="Panel.TFrame", padding=(14, 10))
        title.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        title.columnconfigure(0, weight=1)
        M.ttk.Label(
            title,
            text="Kontrola a řízené vydání",
            font=("Calibri", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.headline = M.tk.StringVar(value="Načítám kontrolu…")
        M.ttk.Label(
            title, textvariable=self.headline, style="PageSubtitle.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        M.ttk.Button(
            title,
            text="? Průvodce vydáním",
            command=lambda: _open_help_topic(M, self.app, "help_offer_release"),
        ).grid(row=0, column=1, rowspan=2, padx=(12, 0))

        steps = M.ttk.Frame(outer, style="Card.TFrame", padding=(10, 8))
        steps.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.step_vars: list[Any] = []
        for index, label in enumerate(
            ("1  Odběratel", "2  Položky a ceny", "3  Kontrola", "4  Vydání")
        ):
            steps.columnconfigure(index, weight=1)
            variable = M.tk.StringVar(value=label)
            self.step_vars.append(variable)
            M.ttk.Label(
                steps,
                textvariable=variable,
                font=("Calibri", 10, "bold"),
                anchor="center",
            ).grid(row=0, column=index, sticky="ew", padx=4)

        body = M.ttk.Panedwindow(outer, orient="horizontal")
        body.grid(row=2, column=0, sticky="nsew")
        summary_frame = M.ttk.Frame(body, style="Card.TFrame", padding=12)
        checks_frame = M.ttk.Frame(body, style="Panel.TFrame", padding=10)
        body.add(summary_frame, weight=2)
        body.add(checks_frame, weight=3)
        summary_frame.columnconfigure(1, weight=1)
        checks_frame.columnconfigure(0, weight=1)
        checks_frame.rowconfigure(1, weight=1)

        M.ttk.Label(
            summary_frame, text="Souhrn dokumentu", font=("Calibri", 13, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.summary_vars: dict[str, Any] = {}
        for row, label in enumerate(
            (
                "Číslo",
                "Odběratel",
                "Kontakt",
                "E-mail",
                "Předmět",
                "Platnost",
                "Položky",
                "Celkem bez DPH",
                "Celkem s DPH",
                "Šablona",
            ),
            1,
        ):
            M.ttk.Label(
                summary_frame, text=label, style="FilterLabel.TLabel"
            ).grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=3)
            variable = M.tk.StringVar(value="")
            self.summary_vars[label] = variable
            M.ttk.Label(
                summary_frame,
                textvariable=variable,
                wraplength=380,
                justify="left",
            ).grid(row=row, column=1, sticky="nw", pady=3)

        M.ttk.Separator(summary_frame).grid(
            row=12, column=0, columnspan=2, sticky="ew", pady=10
        )
        self.pdf_status = M.tk.StringVar(value="")
        M.ttk.Label(
            summary_frame, text="Stav PDF", style="FilterLabel.TLabel"
        ).grid(row=13, column=0, sticky="nw", padx=(0, 10), pady=3)
        M.ttk.Label(
            summary_frame,
            textvariable=self.pdf_status,
            wraplength=380,
            justify="left",
        ).grid(row=13, column=1, sticky="nw", pady=3)
        M.ttk.Checkbutton(
            summary_frame,
            text="Vytvořit novou revizi i bez změny",
            variable=self.force_revision,
        ).grid(row=14, column=0, columnspan=2, sticky="w", pady=(8, 2))
        M.ttk.Label(
            summary_frame,
            text=(
                "Běžně se aktuální shodné PDF znovu nevytváří. "
                "Starší revize se nikdy nepřepisují."
            ),
            style="PageSubtitle.TLabel",
            wraplength=430,
        ).grid(row=15, column=0, columnspan=2, sticky="w", pady=(2, 0))
        output_tools = M.ttk.Frame(summary_frame)
        output_tools.grid(
            row=16, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        self.open_pdf_button = M.ttk.Button(
            output_tools,
            text="Otevřít aktuální PDF",
            command=self.open_current_pdf,
        )
        self.open_pdf_button.pack(side="left")
        self.open_folder_button = M.ttk.Button(
            output_tools,
            text="Otevřít složku",
            command=self.open_current_folder,
        )
        self.open_folder_button.pack(side="left", padx=(5, 0))

        M.ttk.Label(
            checks_frame,
            text="Výsledky kontroly",
            font=("Calibri", 13, "bold"),
        ).grid(row=0, column=0, sticky="w", pady=(0, 7))
        columns = ("Stav", "Oblast", "Kontrola", "Výsledek")
        self.tree = M.ttk.Treeview(
            checks_frame, columns=columns, show="headings", selectmode="browse"
        )
        for column, width in zip(columns, (75, 115, 190, 430)):
            self.tree.heading(column, text=column)
            self.tree.column(
                column,
                width=width,
                minwidth=55,
                stretch=column == "Výsledek",
                anchor="w",
            )
        self.tree.grid(row=1, column=0, sticky="nsew")
        scroll = M.ttk.Scrollbar(
            checks_frame, orient="vertical", command=self.tree.yview
        )
        scroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.tag_configure(
            "ok", background="#d8eadc", foreground="#24502d"
        )
        self.tree.tag_configure(
            "warning", background="#f7edcb", foreground="#5b4308"
        )
        self.tree.tag_configure(
            "error", background="#f5dddd", foreground="#6c2020"
        )

        footer = M.ttk.Frame(outer, style="Panel.TFrame", padding=(10, 8))
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        M.ttk.Button(
            footer, text="Zpět k úpravám", command=self.win.destroy
        ).pack(side="right")
        self.email_button = M.ttk.Button(
            footer,
            text="Vydat PDF a připravit e-mail",
            command=lambda: self.issue(prepare_email=True),
        )
        self.email_button.pack(side="right", padx=5)
        self.issue_button = M.ttk.Button(
            footer,
            text="Vydat / otevřít PDF",
            style="Accent.TButton",
            command=lambda: self.issue(prepare_email=False),
        )
        self.issue_button.pack(side="right", padx=5)
        self.sent_button = M.ttk.Button(
            footer,
            text="Potvrdit odeslání…",
            command=self.confirm_sent,
        )
        self.sent_button.pack(side="right", padx=(5, 12))
        if self.editor is not None:
            M.ttk.Button(
                footer,
                text="Uložit koncept",
                command=self.save_editor,
            ).pack(side="left")
        M.ttk.Button(
            footer, text="Obnovit kontrolu", command=self.refresh
        ).pack(side="left", padx=5)

    def _source(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        from price_lists_domain.issued_offers import service

        if self.editor is not None:
            document = dict(self.editor.collect())
            document.update(
                {
                    "document_number": _text(
                        self.editor.document.get("document_number")
                    ),
                    "template_name": _text(
                        self.editor.template.get()
                        if hasattr(self.editor, "template")
                        else self.editor.document.get("template_name")
                    ),
                    "project_name": _text(
                        self.editor.project.get()
                        if hasattr(self.editor, "project")
                        else self.editor.document.get("project_name")
                    ),
                    "action_name": _text(
                        self.editor.action.get()
                        if hasattr(self.editor, "action")
                        else self.editor.document.get("action_name")
                    ),
                }
            )
            return document, [
                service.normalize_item(dict(item), index)
                for index, item in enumerate(self.editor.items, 1)
            ]
        if not self.document_id:
            return {}, []
        return service.load_document(self.M, int(self.document_id))

    def refresh(self) -> None:
        self.document, self.items = self._source()
        self._base_report = offer_preflight(
            self.document, self.items, for_email=False
        )
        self._email_report = offer_preflight(
            self.document, self.items, for_email=True
        )
        self.report = (
            self._email_report
            if self.initial_action == "email"
            else self._base_report
        )
        self.headline.set(self.report.headline)
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        symbols = {"ok": "✓", "warning": "!", "error": "×"}
        labels = {"ok": "Splněno", "warning": "Doporučení", "error": "Chyba"}
        for index, check in enumerate(self.report.checks):
            self.tree.insert(
                "",
                "end",
                iid=f"c{index}",
                values=(
                    symbols[check.level] + " " + labels[check.level],
                    check.section,
                    check.label,
                    check.message,
                ),
                tags=(check.level,),
            )
        first_issue = next(
            (
                f"c{index}"
                for index, check in enumerate(self.report.checks)
                if check.level in {"error", "warning"}
            ),
            None,
        )
        if first_issue:
            try:
                self.tree.selection_set(first_issue)
                self.tree.see(first_issue)
            except Exception:
                pass

        summary = _document_summary(self.document, self.items)
        for label, variable in self.summary_vars.items():
            variable.set(summary.get(label, ""))
        if self.document_id:
            try:
                state = pdf_state(self.M, int(self.document_id))
                self.pdf_status.set(state.label)
            except Exception as exc:
                state = None
                self.pdf_status.set("Stav PDF se nepodařilo ověřit: " + _text(exc))
        else:
            state = None
            self.pdf_status.set("PDF vznikne až po prvním uložení nabídky.")
        self._pdf_state = state
        can_open_pdf = bool(
            state is not None
            and state.path is not None
            and state.path.is_file()
        )
        for button in (self.open_pdf_button, self.open_folder_button):
            try:
                button.state(
                    ["!disabled"] if can_open_pdf else ["disabled"]
                )
            except Exception:
                button.configure(
                    state="normal" if can_open_pdf else "disabled"
                )

        customer_ok = bool(_text(self.document.get("customer_name_snapshot")))
        item_ok = any(
            _text(item.get("row_type"), "product").casefold()
            not in {"heading", "text"}
            for item in self.items
        )
        self.step_vars[0].set(
            ("✓ " if customer_ok else "○ ") + "1  Odběratel"
        )
        self.step_vars[1].set(("✓ " if item_ok else "○ ") + "2  Položky a ceny")
        self.step_vars[2].set(
            ("✓ " if self._base_report.ready else "× ") + "3  Kontrola"
        )
        issued = bool(state and state.status == "current")
        self.step_vars[3].set(("✓ " if issued else "○ ") + "4  Vydání")

        can_issue = self._base_report.ready
        can_email = self._email_report.ready
        for button, enabled in (
            (self.issue_button, can_issue),
            (self.email_button, can_email),
        ):
            try:
                button.state(["!disabled"] if enabled else ["disabled"])
            except Exception:
                button.configure(state="normal" if enabled else "disabled")
        status = _text(self.document.get("status"), "Rozpracováno")
        can_mark_sent = bool(self.document_id and status != "Odesláno")
        try:
            self.sent_button.state(
                ["!disabled"] if can_mark_sent else ["disabled"]
            )
        except Exception:
            self.sent_button.configure(
                state="normal" if can_mark_sent else "disabled"
            )

    def open_current_pdf(self) -> None:
        state = getattr(self, "_pdf_state", None)
        if state and state.path and state.path.is_file():
            from price_lists_domain.issued_offers import service

            service.open_path(state.path)

    def open_current_folder(self) -> None:
        state = getattr(self, "_pdf_state", None)
        if state and state.path and state.path.is_file():
            from price_lists_domain.issued_offers import service

            service.open_path(state.path.parent)

    def save_editor(self, quiet: bool = False) -> int | None:
        if self.editor is None:
            return self.document_id
        if getattr(self.editor, "locked", False) and self.document_id:
            return int(self.document_id)
        result = self.editor.save(quiet=quiet)
        if result:
            self.document_id = int(result)
            self.refresh()
        return result

    def issue(self, *, prepare_email: bool) -> None:
        from price_lists_domain.issued_offers import service

        if self.editor is not None:
            if not self.save_editor(quiet=True):
                return
        if not self.document_id:
            return
        document, items = service.load_document(self.M, int(self.document_id))
        report = offer_preflight(document, items, for_email=prepare_email)
        if report.errors:
            self.report = report
            self.initial_action = "email" if prepare_email else "release"
            self.refresh()
            self.M.messagebox.showwarning(
                "Kontrola před vydáním",
                report.headline
                + "\n\nOpravte červeně označené body a kontrolu zopakujte.",
                parent=self.win,
            )
            return
        if bool(document.get("locked")) and pdf_state(
            self.M, int(self.document_id)
        ).status not in {"current"}:
            self.M.messagebox.showwarning(
                "Uzamčená nabídka",
                "Tento dokument je uzamčený a nelze pro něj vytvořit změněnou "
                "revizi. Vytvořte duplikát nabídky.",
                parent=self.win,
            )
            return

        if _text(document.get("status")) == "Rozpracováno":
            service.set_status(self.M, int(self.document_id), "Připraveno")
        try:
            path = ensure_current_pdf(
                self.M,
                int(self.document_id),
                force_revision=bool(self.force_revision.get()),
                open_after=not prepare_email,
            )
            if prepare_email:
                if not _create_professional_outlook_draft(
                    self.M, self.app, int(self.document_id), parent=self.win
                ):
                    return
            try:
                self.app.refresh_issued_offers()
            except Exception:
                pass
            if self.editor is not None:
                try:
                    self.editor.document, self.editor.items = service.load_document(
                        self.M, int(self.document_id)
                    )
                    self.editor.status.set(
                        _text(self.editor.document.get("status"), "Připraveno")
                    )
                    self.editor.refresh_items()
                    self.editor.refresh_status()
                    self.editor._v780_saved_fingerprint = commercial_fingerprint(
                        self.editor.document, self.editor.items
                    )
                    self.editor._v780_update_readiness()
                except Exception:
                    pass
            state = pdf_state(self.M, int(self.document_id))
            message = (
                f"Nabídka je připravena.\n\n"
                f"PDF: {path}\n"
                f"Revize: "
                f"{'R' + format(int(state.revision_no), '02d') if state.revision_no is not None else '—'}"
            )
            if prepare_email:
                message += (
                    "\n\nOutlook koncept byl otevřen. Koncept není odeslaný "
                    "e-mail; po skutečném odeslání použijte Potvrdit odeslání."
                )
            self.M.messagebox.showinfo(
                "Vydaná nabídka", message, parent=self.win
            )
            self.refresh()
        except Exception as exc:
            self.M.messagebox.showerror(
                "Vydání nabídky",
                "Nabídku se nepodařilo vydat:\n\n" + _text(exc),
                parent=self.win,
            )

    def confirm_sent(self) -> None:
        if not self.document_id:
            return
        if _confirm_sent(
            self.M,
            self.app,
            int(self.document_id),
            parent=self.win,
        ):
            if self.editor is not None:
                self.editor._v780_apply_sent_state()
            self.refresh()


def _create_professional_outlook_draft(
    M: Any,
    app: Any,
    document_id: int,
    *,
    parent: Any = None,
) -> bool:
    from price_lists_domain.issued_offers import service

    document, items = service.load_document(M, int(document_id))
    report = offer_preflight(document, items, for_email=True)
    if report.errors:
        M.messagebox.showwarning(
            "Příprava e-mailu",
            report.headline + "\n\nDoplňte e-mail a povinné údaje nabídky.",
            parent=parent or app,
        )
        return False
    email = _text(document.get("customer_email_snapshot"))
    pdf = ensure_current_pdf(M, int(document_id), open_after=False)
    subject = f"Cenová nabídka {document.get('document_number') or ''}"
    offer_subject = _text(
        document.get("offer_subject")
        or document.get("project_name")
        or document.get("action_name")
    )
    if offer_subject:
        subject += " – " + offer_subject

    intro = "Dobrý den,"
    reference = _text(document.get("document_number"))
    body_lines = [
        intro,
        "",
        f"v příloze zasíláme cenovou nabídku {reference}"
        + (f" pro akci {offer_subject}" if offer_subject else "")
        + ".",
        "",
        "V případě dotazů nebo potřeby upřesnění jsem Vám k dispozici.",
        "",
        "Předem velice děkuji,",
        "",
    ]
    plain_body = "\r\n".join(body_lines)
    html_body = "".join(
        "<p style='font-family:Calibri;font-size:11pt;margin:0 0 10pt 0'>"
        + html.escape(line)
        + "</p>"
        for line in body_lines
        if line
    )
    try:
        import win32com.client

        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.To = email
        mail.CC = _text(getattr(M, "CC_ALWAYS", "info@turto.cz"), "info@turto.cz")
        mail.Subject = subject
        mail.Attachments.Add(str(pdf))
        # Display first: Outlook inserts the account signature at that point.
        mail.Display()
        try:
            signature = _text(mail.HTMLBody)
            mail.HTMLBody = html_body + signature
        except Exception:
            try:
                signature_plain = _text(mail.Body)
                mail.Body = plain_body + signature_plain
            except Exception:
                mail.Body = plain_body
        try:
            inspector = mail.GetInspector
            hwnd = int(getattr(inspector, "HWND", 0) or 0)
            if hwnd:
                import ctypes

                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
        if _text(document.get("status")) == "Rozpracováno":
            service.set_status(M, int(document_id), "Připraveno")
        _record_history(
            M,
            int(document_id),
            "email_draft",
            f"Připraven Outlook koncept pro {email}; přiloženo {Path(pdf).name}.",
        )
        try:
            app.refresh_issued_offers()
        except Exception:
            pass
        return True
    except Exception as exc:
        M.messagebox.showerror(
            "Vydané nabídky",
            "Koncept Outlooku se nepodařilo vytvořit:\n\n"
            + _text(exc)
            + "\n\nPDF zůstalo uložené zde:\n"
            + str(pdf),
            parent=parent or app,
        )
        return False


def _confirm_sent(
    M: Any,
    app: Any,
    document_id: int,
    *,
    parent: Any = None,
) -> bool:
    from price_lists_domain.issued_offers import service

    document, _items = service.load_document(M, int(document_id))
    if _text(document.get("status")) == "Odesláno":
        M.messagebox.showinfo(
            "Vydaná nabídka",
            "Nabídka je již označená jako Odesláno.",
            parent=parent or app,
        )
        return False
    if not M.messagebox.askyesno(
        "Potvrdit skutečné odeslání",
        f"Potvrzujete, že nabídka {document.get('document_number') or ''} "
        "byla skutečně odeslána zákazníkovi?\n\n"
        "Tuto volbu použijte až po kontrole složky Odeslaná pošta. "
        "Dokument se označí jako Odesláno a uzamkne proti změnám.",
        parent=parent or app,
    ):
        return False
    service.set_status(M, int(document_id), "Odesláno")
    _record_history(
        M,
        int(document_id),
        "sent_confirmation",
        "Uživatel výslovně potvrdil skutečné odeslání nabídky.",
    )
    try:
        app.refresh_issued_offers()
    except Exception:
        pass
    return True


def _find_outer_row(instance: Any, row: int) -> Any:
    try:
        for child in instance.outer.winfo_children():
            info = child.grid_info()
            if int(info.get("row", -1)) == int(row):
                return child
    except Exception:
        pass
    return None


def _install_editor_workflow(
    M: Any,
    issued_editor: Any,
    service: Any,
) -> None:
    Editor = issued_editor.IssuedOfferEditor
    if getattr(Editor, "_turto_v780_professional_release", False):
        return

    previous_init = Editor.__init__
    previous_save = Editor.save
    previous_refresh_items = Editor.refresh_items

    def current_fingerprint(self: Any) -> str:
        try:
            document = self.collect()
            document["template_name"] = _text(self.template.get())
            document["project_name"] = _text(self.project.get())
            document["action_name"] = _text(self.action.get())
        except Exception:
            document = dict(getattr(self, "document", {}) or {})
        return commercial_fingerprint(
            document, list(getattr(self, "items", []) or [])
        )

    def update_readiness(self: Any) -> None:
        if not _widget_exists(getattr(self, "win", None)):
            return
        try:
            document = self.collect()
            document.update(
                template_name=_text(self.template.get()),
                project_name=_text(self.project.get()),
                action_name=_text(self.action.get()),
            )
            items = [
                service.normalize_item(dict(item), index)
                for index, item in enumerate(self.items, 1)
            ]
            report = offer_preflight(document, items)
            dirty = (
                current_fingerprint(self)
                != _text(getattr(self, "_v780_saved_fingerprint", ""))
            )
            customer_ok = bool(_text(document.get("customer_name_snapshot")))
            item_ok = any(
                _text(item.get("row_type"), "product").casefold()
                not in {"heading", "text"}
                for item in items
            )
            try:
                state = (
                    pdf_state(M, int(self.document_id))
                    if self.document_id
                    else PdfState("none", None, None, "", "", "")
                )
            except Exception:
                state = PdfState("none", None, None, "", "", "")
            self._v780_step_vars[0].set(
                ("✓ " if customer_ok else "○ ") + "1  Odběratel"
            )
            self._v780_step_vars[1].set(
                ("✓ " if item_ok else "○ ") + "2  Položky a ceny"
            )
            self._v780_step_vars[2].set(
                ("✓ " if report.ready else "× ") + "3  Kontrola"
            )
            self._v780_step_vars[3].set(
                ("✓ " if state.status == "current" else "○ ") + "4  Vydání"
            )
            if self.locked:
                text = (
                    f"Uzamčený dokument · {state.label}. "
                    "Pro změnu vytvořte duplikát."
                )
            elif dirty:
                text = (
                    "Neuložené změny · "
                    + (
                        report.headline
                        if report.errors
                        else "po uložení proveďte kontrolu a vydání."
                    )
                )
            else:
                text = report.headline + " · " + state.label
            self._v780_readiness.set(text)
            self._v780_last_report = report
            self._v780_last_pdf_state = state

            status = _text(self.status.get())
            can_mark = bool(self.document_id and status != "Odesláno")
            try:
                self._v780_sent_button.state(
                    ["!disabled"] if can_mark else ["disabled"]
                )
            except Exception:
                self._v780_sent_button.configure(
                    state="normal" if can_mark else "disabled"
                )
        except Exception:
            pass

    def schedule_readiness(self: Any, delay: int = 120) -> None:
        try:
            pending = getattr(self, "_v780_readiness_after", None)
            if pending is not None:
                self.win.after_cancel(pending)
            self._v780_readiness_after = self.win.after(
                max(20, int(delay)),
                lambda: (
                    setattr(self, "_v780_readiness_after", None),
                    update_readiness(self),
                ),
            )
        except Exception:
            update_readiness(self)

    def open_release_dialog(
        self: Any, initial_action: str = "release"
    ) -> Any:
        current = getattr(self, "_v780_release_dialog", None)
        try:
            if current is not None and current.win.winfo_exists():
                current.win.deiconify()
                current.win.lift()
                current.win.focus_force()
                current.initial_action = initial_action
                current.refresh()
                return current
        except Exception:
            pass
        dialog = OfferReleaseDialog(
            M,
            self.app,
            editor=self,
            initial_action=initial_action,
        )
        self._v780_release_dialog = dialog
        return dialog

    def apply_sent_state(self: Any) -> None:
        if not self.document_id:
            return
        try:
            self.document, self.items = service.load_document(
                M, int(self.document_id)
            )
            self.status.set("Odesláno")
            self._v780_loaded_status = "Odesláno"
            self.locked = True
            self.set_readonly(True)
            self.refresh_items()
            self.refresh_status()
            self._v780_saved_fingerprint = commercial_fingerprint(
                self.document, self.items
            )
            update_readiness(self)
        except Exception:
            pass

    def confirm_sent(self: Any) -> None:
        if not self.document_id:
            return M.messagebox.showinfo(
                "Vydaná nabídka",
                "Nejprve nabídku uložte a vydejte.",
                parent=self.win,
            )
        if _confirm_sent(
            M, self.app, int(self.document_id), parent=self.win
        ):
            apply_sent_state(self)

    def init(self: Any, *args: Any, **kwargs: Any):
        previous_init(self, *args, **kwargs)
        try:
            # Insert the workflow strip between the document heading and fields.
            for child in list(self.outer.winfo_children()):
                info = child.grid_info()
                row = int(info.get("row", -1))
                if row >= 1:
                    child.grid_configure(row=row + 1)
            self.outer.rowconfigure(2, weight=0)
            self.outer.rowconfigure(3, weight=1)

            workflow = M.ttk.Frame(
                self.outer, style="Card.TFrame", padding=(10, 8)
            )
            workflow.grid(row=1, column=0, sticky="ew", pady=(0, 7))
            for column in range(4):
                workflow.columnconfigure(column, weight=1)
            workflow.columnconfigure(4, weight=0)
            self._v780_step_vars = []
            for column, label in enumerate(
                (
                    "1  Odběratel",
                    "2  Položky a ceny",
                    "3  Kontrola",
                    "4  Vydání",
                )
            ):
                variable = M.tk.StringVar(value="○ " + label)
                self._v780_step_vars.append(variable)
                M.ttk.Label(
                    workflow,
                    textvariable=variable,
                    font=("Calibri", 10, "bold"),
                    anchor="center",
                ).grid(row=0, column=column, sticky="ew", padx=3)
            self._v780_readiness = M.tk.StringVar(
                value="Kontroluji připravenost…"
            )
            M.ttk.Label(
                workflow,
                textvariable=self._v780_readiness,
                style="PageSubtitle.TLabel",
                wraplength=900,
            ).grid(
                row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(5, 0)
            )
            controls = M.ttk.Frame(workflow)
            controls.grid(row=0, column=4, rowspan=2, sticky="e", padx=(12, 0))
            M.ttk.Button(
                controls,
                text="Kontrola před vydáním",
                style="Accent.TButton",
                command=lambda: open_release_dialog(self),
            ).pack(side="left")
            M.ttk.Button(
                controls,
                text="?",
                width=3,
                command=lambda: _open_help_topic(
                    M, self.app, "help_issued_offers"
                ),
            ).pack(side="left", padx=(5, 0))

            footer = _find_outer_row(self, 4)
            if footer is not None:
                for button in _walk(footer):
                    try:
                        text = _text(button.cget("text"))
                    except Exception:
                        continue
                    if text == "Uložit":
                        button.configure(text="Uložit koncept")
                    elif "Vytvořit a otevřít PDF" in text:
                        button.configure(
                            text="Zkontrolovat a vydat…",
                            command=lambda: open_release_dialog(self),
                            style="Accent.TButton",
                        )
                    elif text == "Outlook koncept":
                        button.configure(
                            text="Připravit e-mail…",
                            command=lambda: open_release_dialog(
                                self, "email"
                            ),
                        )
                self._v780_sent_button = M.ttk.Button(
                    footer,
                    text="Potvrdit odeslání…",
                    command=lambda: confirm_sent(self),
                )
                self._v780_sent_button.pack(
                    side="right", padx=(5, 12)
                )
            else:
                self._v780_sent_button = M.ttk.Button(
                    workflow,
                    text="Potvrdit odeslání…",
                    command=lambda: confirm_sent(self),
                )
                self._v780_sent_button.grid(
                    row=2, column=4, sticky="e", pady=(5, 0)
                )

            self._v780_saved_fingerprint = (
                commercial_fingerprint(self.document, self.items)
                if self.document_id
                else current_fingerprint(self)
            )
            self._v780_loaded_status = _text(
                self.document.get("status"), "Rozpracováno"
            )
            # Odesláno is a controlled transition. It is deliberately removed
            # from the ordinary status selector and is available only through
            # the explicit confirmation action.
            allowed_statuses = [
                value
                for value in service.STATUSES
                if value != "Odesláno"
                or self._v780_loaded_status == "Odesláno"
            ]
            for widget in _walk(self.outer):
                try:
                    if (
                        widget.winfo_class() == "TCombobox"
                        and _text(widget.cget("textvariable")) == str(self.status)
                    ):
                        widget.configure(values=allowed_statuses)
                except Exception:
                    pass
            self._v780_readiness_after = None
            variables = [
                getattr(self, name, None)
                for name in (
                    "issue_date",
                    "valid_to",
                    "status",
                    "currency",
                    "subject",
                    "reference",
                    "salesperson",
                    "global_discount",
                    "company",
                    "contact",
                    "project",
                    "action",
                    "template",
                )
            ]
            for variable in variables:
                if variable is not None:
                    try:
                        variable.trace_add(
                            "write",
                            lambda *_args, current=self: schedule_readiness(
                                current
                            ),
                        )
                    except Exception:
                        pass
            for widget in (
                self.payment_terms,
                self.delivery_terms,
                self.delivery_time,
                self.customer_note,
                self.internal_note,
            ):
                try:
                    widget.edit_modified(False)

                    def modified(
                        _event=None, current=self, control=widget
                    ):
                        if control.edit_modified():
                            control.edit_modified(False)
                            schedule_readiness(current)
                    widget.bind("<<Modified>>", modified, add="+")
                except Exception:
                    pass
            self.win.bind(
                "<Control-s>",
                lambda _event: (
                    self.save(quiet=False),
                    "break",
                )[1],
                add="+",
            )
            self.win.bind(
                "<Control-Return>",
                lambda _event: (
                    open_release_dialog(self),
                    "break",
                )[1],
                add="+",
            )
            self.win.bind(
                "<F1>",
                lambda _event: (
                    _open_help_topic(
                        M, self.app, "help_issued_offers"
                    ),
                    "break",
                )[1],
                add="+",
            )
            schedule_readiness(self, 40)
        except Exception:
            pass

    def save(self: Any, *args: Any, **kwargs: Any):
        desired_status = _text(self.status.get(), "Rozpracováno")
        loaded_status = _text(
            getattr(self, "_v780_loaded_status", "Rozpracováno"),
            "Rozpracováno",
        )
        if desired_status == "Odesláno" and loaded_status != "Odesláno":
            self.status.set(
                "Připraveno"
                if loaded_status == "Rozpracováno"
                else loaded_status
            )
            M.messagebox.showwarning(
                "Kontrolované odeslání",
                "Stav Odesláno nelze nastavit pouhým uložením. "
                "Po skutečném odeslání zprávy v Outlooku použijte "
                "Potvrdit odeslání.",
                parent=self.win,
            )
            return None
        result = previous_save(self, *args, **kwargs)
        if result:
            try:
                self._v780_saved_fingerprint = commercial_fingerprint(
                    self.document, self.items
                )
            except Exception:
                self._v780_saved_fingerprint = current_fingerprint(self)
            self._v780_loaded_status = _text(
                self.document.get("status") or self.status.get(),
                "Rozpracováno",
            )
            schedule_readiness(self, 30)
        return result

    def refresh_items(self: Any, *args: Any, **kwargs: Any):
        result = previous_refresh_items(self, *args, **kwargs)
        if hasattr(self, "_v780_readiness"):
            schedule_readiness(self)
        return result

    def close(self: Any) -> None:
        if getattr(self, "locked", False):
            self.win.destroy()
            return
        dirty = current_fingerprint(self) != _text(
            getattr(self, "_v780_saved_fingerprint", "")
        )
        if not dirty:
            self.win.destroy()
            return
        answer = M.messagebox.askyesnocancel(
            "Neuložené změny",
            "V nabídce jsou neuložené změny.\n\n"
            "Ano = uložit koncept a zavřít\n"
            "Ne = zavřít bez uložení\n"
            "Zrušit = vrátit se do nabídky",
            parent=self.win,
        )
        if answer is None:
            return
        if answer:
            if self.save(quiet=True):
                self.win.destroy()
        else:
            self.win.destroy()

    Editor.__init__ = init
    Editor.save = save
    Editor.refresh_items = refresh_items
    Editor.close = close
    Editor.generate_pdf = (
        lambda self, open_after=True: open_release_dialog(self, "release")
    )
    Editor.outlook_draft = (
        lambda self: open_release_dialog(self, "email")
    )
    Editor.open_release_dialog = open_release_dialog
    Editor.confirm_sent = confirm_sent
    Editor._v780_apply_sent_state = apply_sent_state
    Editor._v780_update_readiness = update_readiness
    Editor._v780_current_fingerprint = current_fingerprint
    Editor._turto_v780_professional_release = True


def _install_page_workflow(
    M: Any,
    issued_page: Any,
    service: Any,
) -> None:
    if getattr(issued_page, "_turto_v780_professional_page", False):
        return

    def open_release_from_selection(
        module: Any, app: Any, initial_action: str = "release"
    ) -> None:
        row = issued_page._selected_one(module, app)
        if not row:
            return
        editor = app.open_issued_offer_editor(int(row["id"]))
        try:
            editor.win.after(
                80, lambda: editor.open_release_dialog(initial_action)
            )
        except Exception:
            editor.open_release_dialog(initial_action)

    issued_page._render_selected = (
        lambda module, app, open_after=False: open_release_from_selection(
            module, app, "release"
        )
    )
    issued_page._draft_selected = (
        lambda module, app: open_release_from_selection(
            module, app, "email"
        )
    )

    def change_status(module: Any, app: Any) -> None:
        row = issued_page._selected_one(module, app)
        if not row:
            return
        dialog = module.tk.Toplevel(app)
        dialog.title("Změnit stav vydané nabídky")
        dialog.transient(app)
        dialog.grab_set()
        frame = module.ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        current = _text(row.get("status"), "Rozpracováno")
        value = module.tk.StringVar(value=current)
        module.ttk.Label(
            frame,
            text=f"{row.get('document_number') or ''} · {row.get('customer') or ''}",
            font=("Calibri", 12, "bold"),
            wraplength=480,
        ).pack(anchor="w", pady=(0, 10))
        module.ttk.Label(frame, text="Nový stav").pack(anchor="w")
        available = [
            status
            for status in service.STATUSES
            if status != "Odesláno" or current == "Odesláno"
        ]
        issued_page._combobox(
            module, frame, value, available
        ).pack(fill="x", pady=(5, 7))
        module.ttk.Label(
            frame,
            text=(
                "Stav Odesláno se nastavuje samostatnou akcí Potvrdit "
                "odeslání až po kontrole Odeslané pošty v Outlooku."
            ),
            style="PageSubtitle.TLabel",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 12))

        def save() -> None:
            selected = _text(value.get())
            if selected == "Odesláno" and current != "Odesláno":
                dialog.destroy()
                _confirm_sent(
                    module, app, int(row["id"]), parent=app
                )
                return
            service.set_status(module, int(row["id"]), selected)
            _record_history(
                module,
                int(row["id"]),
                "status_change",
                f"Stav změněn z {current} na {selected}.",
            )
            dialog.destroy()
            issued_page.refresh_issued_offers(module, app)

        buttons = module.ttk.Frame(frame)
        buttons.pack(fill="x")
        module.ttk.Button(
            buttons, text="Zrušit", command=dialog.destroy
        ).pack(side="right")
        module.ttk.Button(
            buttons,
            text="Uložit stav",
            style="Accent.TButton",
            command=save,
        ).pack(side="right", padx=(0, 5))
        try:
            module.center_dialog(dialog, app)
        except Exception:
            pass

    issued_page._change_status = change_status

    previous_build = issued_page.build_issued_offers
    previous_detail = issued_page._refresh_detail

    def build_issued_offers(module: Any, app: Any):
        result = previous_build(module, app)
        page = app.tabs.get("issued_offers")
        if not _widget_exists(page):
            return result
        try:
            for widget in _walk(page):
                try:
                    text = _text(widget.cget("text"))
                except Exception:
                    continue
                if text == "Vytvořit PDF":
                    widget.configure(text="Zkontrolovat a vydat…")
                elif text == "Vytvořit a otevřít PDF":
                    widget.configure(text="Zkontrolovat a vydat…")
                elif text == "Outlook koncept":
                    widget.configure(text="Připravit e-mail…")

            children = page.winfo_children()
            title_row = children[0] if children else None
            if _widget_exists(title_row) and not _widget_exists(
                getattr(app, "_v780_issued_help_button", None)
            ):
                button = module.ttk.Button(
                    title_row,
                    text="? Průvodce",
                    command=lambda: _open_help_topic(
                        module, app, "help_issued_offers"
                    ),
                )
                button.pack(side="right", anchor="n", padx=(0, 7), pady=(2, 0))
                app._v780_issued_help_button = button

            toolbar = next(
                (
                    child
                    for child in page.winfo_children()
                    if child is not title_row
                    and "Panel" in _text(child.cget("style"))
                ),
                None,
            )
            if _widget_exists(toolbar) and not _widget_exists(
                getattr(app, "_v780_mark_sent_button", None)
            ):
                button = module.ttk.Button(
                    toolbar,
                    text="Potvrdit odeslání…",
                    command=lambda: _mark_selected_sent(module, app),
                )
                button.pack(side="left", padx=(14, 4))
                app._v780_mark_sent_button = button

            tree = getattr(app, "issued_offer_tree", None)
            if _widget_exists(tree):
                context = module.tk.Menu(tree, tearoff=False)
                context.add_command(
                    label="Otevřít nabídku",
                    command=lambda: issued_page._open_selected(module, app),
                )
                context.add_command(
                    label="Zkontrolovat a vydat…",
                    command=lambda: open_release_from_selection(
                        module, app, "release"
                    ),
                )
                context.add_command(
                    label="Připravit e-mail…",
                    command=lambda: open_release_from_selection(
                        module, app, "email"
                    ),
                )
                context.add_command(
                    label="Potvrdit odeslání…",
                    command=lambda: _mark_selected_sent(module, app),
                )
                context.add_separator()
                context.add_command(
                    label="Otevřít poslední PDF",
                    command=lambda: issued_page._open_pdf(module, app),
                )
                context.add_command(
                    label="Duplikovat nabídku",
                    command=lambda: issued_page._duplicate_selected(
                        module, app
                    ),
                )
                context.add_command(
                    label="Změnit stav…",
                    command=lambda: change_status(module, app),
                )
                context.add_command(
                    label="Archivovat / obnovit",
                    command=lambda: issued_page._toggle_archive(
                        module, app
                    ),
                )

                def popup(event: Any):
                    iid = tree.identify_row(event.y)
                    if iid and iid not in tree.selection():
                        tree.selection_set(iid)
                    if not iid:
                        return "break"
                    try:
                        context.tk_popup(event.x_root, event.y_root)
                    finally:
                        try:
                            context.grab_release()
                        except Exception:
                            pass
                    return "break"

                tree.bind("<Button-3>", popup, add=False)
                app._v780_issued_context_menu = context
        except Exception:
            pass
        return result

    def refresh_detail(module: Any, app: Any):
        result = previous_detail(module, app)
        try:
            rows = issued_page._selected_rows(app)
            if len(rows) != 1:
                return result
            row = rows[0]
            state = pdf_state(module, int(row["id"]))
            status = (
                "Archivováno"
                if row.get("archived")
                else _text(row.get("status"), "Rozpracováno")
            )
            if status == "Rozpracováno":
                next_step = "Doplnit údaje a spustit kontrolu před vydáním."
            elif status == "Připraveno":
                next_step = (
                    "Připravit e-mail nebo potvrdit skutečné odeslání."
                )
            elif status == "Odesláno":
                next_step = "Vyčkat na reakci zákazníka a aktualizovat výsledek."
            else:
                next_step = "Dokument je v ukončeném obchodním stavu."
            extra = (
                "\n\nKontrolovaný proces\n"
                f"PDF: {state.label}\n"
                f"E-mail: {_text(row.get('customer_email_snapshot'), 'není vyplněn')}\n"
                f"Další krok: {next_step}"
            )
            current = _text(app.issued_offer_detail_text.get())
            if "Kontrolovaný proces" not in current:
                app.issued_offer_detail_text.set(current + extra)
        except Exception:
            pass
        return result

    issued_page.build_issued_offers = build_issued_offers
    issued_page._refresh_detail = refresh_detail
    M.App.build_issued_offers = (
        lambda self: build_issued_offers(M, self)
    )
    issued_page._turto_v780_professional_page = True


def _mark_selected_sent(M: Any, app: Any) -> None:
    try:
        from price_lists_domain.issued_offers import page as issued_page

        row = issued_page._selected_one(M, app)
        if row:
            _confirm_sent(M, app, int(row["id"]), parent=app)
    except Exception as exc:
        M.messagebox.showerror(
            "Vydaná nabídka", _text(exc), parent=app
        )


def _install_help(M: Any) -> None:
    def build_help(self: Any) -> None:
        centre = HelpCentre(M, self)
        self._v780_help_centre = centre
        self.help_text = centre.text
        self.help_tree = centre.tree
        self.help_query = centre.query

    def show_help_topic(self: Any, key: str) -> None:
        centre = getattr(self, "_v780_help_centre", None)
        if centre is None:
            build_help(self)
            centre = self._v780_help_centre
        centre.show(key)

    M.App.build_help = build_help
    M.App.show_help_topic = show_help_topic
    M.open_help_topic = lambda app, key="help_start": _open_help_topic(
        M, app, key
    )

    previous_init = M.App.__init__

    def app_init(self: Any, *args: Any, **kwargs: Any):
        result = previous_init(self, *args, **kwargs)
        try:
            self.bind(
                "<F1>",
                lambda _event: (
                    _open_help_topic(M, self, "help_start"),
                    "break",
                )[1],
                add="+",
            )
        except Exception:
            pass
        return result

    M.App.__init__ = app_init


def apply(M: Any) -> None:
    if getattr(M, "_turto_v780_professional_offer_workflow", False):
        return
    try:
        from price_lists_domain.issued_offers import (
            editor as issued_editor,
            page as issued_page,
            pdf_renderer,
            service,
        )
    except Exception:
        M._turto_v780_professional_offer_workflow = True
        return

    previous_record_revision = service.record_revision

    def record_revision(
        module: Any,
        document_id: int,
        revision_no: int,
        pdf_path: Path,
        data_snapshot: dict[str, Any],
    ) -> None:
        snapshot = dict(data_snapshot or {})
        snapshot["_commercial_fingerprint"] = commercial_fingerprint(
            snapshot, list(snapshot.get("items") or [])
        )
        snapshot["_template_fingerprint"] = template_fingerprint(
            module, snapshot.get("template_id")
        )
        snapshot["_release_fingerprint"] = release_fingerprint(
            module, snapshot, list(snapshot.get("items") or [])
        )
        previous_record_revision(
            module,
            int(document_id),
            int(revision_no),
            Path(pdf_path),
            snapshot,
        )

    service.record_revision = record_revision

    def latest_or_render(module: Any, document_id: int) -> Path:
        return ensure_current_pdf(module, int(document_id), open_after=False)

    pdf_renderer.latest_or_render = latest_or_render
    pdf_renderer.create_outlook_draft = (
        lambda module, app, document_id: _create_professional_outlook_draft(
            module, app, int(document_id), parent=app
        )
    )
    M.create_issued_offer_outlook_draft = (
        lambda app, document_id: _create_professional_outlook_draft(
            M, app, int(document_id), parent=app
        )
    )
    M.issued_offer_preflight = offer_preflight
    M.issued_offer_commercial_fingerprint = commercial_fingerprint
    M.issued_offer_pdf_state = lambda document_id: pdf_state(
        M, int(document_id)
    )
    M.ensure_current_issued_offer_pdf = lambda document_id, force_revision=False, open_after=False: ensure_current_pdf(
        M,
        int(document_id),
        force_revision=bool(force_revision),
        open_after=bool(open_after),
    )
    M.confirm_issued_offer_sent = lambda app, document_id, parent=None: _confirm_sent(
        M, app, int(document_id), parent=parent or app
    )
    M.open_offer_release_dialog = lambda app, document_id=None, editor=None, initial_action="release": OfferReleaseDialog(
        M,
        app,
        editor=editor,
        document_id=document_id,
        initial_action=initial_action,
    )

    _install_help(M)
    _install_editor_workflow(M, issued_editor, service)
    _install_page_workflow(M, issued_page, service)

    M.V780_PROFESSIONAL_OFFER_WORKFLOW = {
        "canonical_pdf_renderer": True,
        "preflight": True,
        "commercial_fingerprint": True,
        "stale_pdf_detection": True,
        "explicit_sent_confirmation": True,
        "outlook_draft_is_not_sent": True,
        "searchable_help_topics": len(HELP_TOPICS),
    }
    M._turto_v780_professional_offer_workflow = True


__all__ = [
    "apply",
    "commercial_fingerprint",
    "template_fingerprint",
    "release_fingerprint",
    "offer_preflight",
    "pdf_state",
    "ensure_current_pdf",
    "HELP_TOPICS",
    "OfferCheck",
    "PreflightReport",
    "PdfState",
]
