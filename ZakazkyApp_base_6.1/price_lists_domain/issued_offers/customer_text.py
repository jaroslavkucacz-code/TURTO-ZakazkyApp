"""Keep importer provenance out of customer text, without changing prices.

Only explicitly labelled internal clauses are removed. Technical dimensions and
unlabelled numbers are never guessed to be purchase prices. Stored source offers
and historical PDFs are not mutated; a cleaned draft preserves the removed text
in the document's internal note. Renderers apply the same boundary defensively.
"""
from __future__ import annotations
import re

POLICY_VERSION = 1
ITEM_FIELDS = (
    'name', 'description', 'line_note', 'internal_name_snapshot',
    'supplier_name_snapshot', 'name_note_snapshot', '_v740_source_name',
)
DOCUMENT_FIELDS = (
    'offer_subject', 'customer_reference', 'customer_note', 'payment_terms',
    'delivery_terms', 'delivery_time', 'project_name', 'action_name',
)
# Generated notes are clauses separated with semicolons or line breaks.
# Whitespace after the marker may include the line wrap before the amount.
_PRIVATE = re.compile(
    r'(?<!\w)(?:zdrojov[áa]\s+cena|n[áa]kupn[íi]\s+cena|'
    r'po[řr]izovac[íi]\s+cena|source\s+price|purchase\s+price|'
    r'NC(?:\s*/\s*(?:MJ|ks|m))?)\s*[:=]\s*[^;|\r\n]*', re.IGNORECASE,
)


def split_customer_text(value):
    text = str(value or '')
    removed = [match.group(0).strip() for match in _PRIVATE.finditer(text)]
    if not removed:
        return text, []
    text = _PRIVATE.sub('', text)
    text = re.sub(r'[ \t]*([;|])[ \t]*(?=[;|]|$)', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[;|]\s*', '', text)
    text = '\n'.join(line.rstrip(' ;|\t') for line in text.splitlines()).strip(' ;|\t\r\n')
    return text, removed


def has_private_text(document, items=()):
    return any(_PRIVATE.search(str(document.get(k) or '')) for k in DOCUMENT_FIELDS) or any(
        _PRIVATE.search(str(item.get(k) or '')) for item in items for k in ITEM_FIELDS
    )


def sanitize_snapshot(document, items):
    """Return copies, preserving removed provenance in an internal-only field."""
    doc, result, notes = dict(document or {}), [], []
    for key in DOCUMENT_FIELDS:
        if key in doc:
            doc[key], removed = split_customer_text(doc[key])
            notes.extend(removed)
    for index, raw in enumerate(items or [], 1):
        item = dict(raw)
        for key in ITEM_FIELDS:
            if key in item:
                item[key], removed = split_customer_text(item[key])
                notes.extend(f'Položka {index}: {value}' for value in removed)
        result.append(item)
    existing = str(doc.get('internal_note') or '')
    unique = [n for n in dict.fromkeys(notes) if n not in existing]
    if unique:
        doc['internal_note'] = (existing + '\n' if existing else '') + '\n'.join(unique)
    return doc, result
