"""Offer-local group pricing; explicit line exceptions survive save and reopen."""
import math
from . import service

FIELDS = {'margin_pct', 'discount_pct'}


def parse(value, field):
    try:
        value = float(str(value).replace('\u00a0', '').replace(' ', '').replace(',', '.'))
    except (ValueError, TypeError):
        raise ValueError('Zadejte číselnou hodnotu.') from None
    if not math.isfinite(value): raise ValueError('Zadejte konečnou číselnou hodnotu.')
    if field == 'purchase_unit_price' and value < 0: raise ValueError('Nákupní cena nesmí být záporná.')
    if field == 'margin_pct' and value < -100: raise ValueError('Marže nesmí být nižší než −100 %.')
    if field == 'discount_pct' and not -100 <= value <= 100: raise ValueError('Sleva musí být mezi −100 a 100 %.')
    return value


def apply(items, indices, field, value, group=False):
    if field not in FIELDS | {'purchase_unit_price'}: raise ValueError('Neplatné cenové pole.')
    value = parse(value, field)
    changes = {}
    for index in indices:
        item = dict(items[index])
        if item.get('row_type', 'product') in {'heading', 'text'}: continue
        if field in FIELDS:
            override = field.replace('_pct', '_override')
            if group:
                item['group_'+field] = value
                if item.get(override):
                    changes[index] = item
                    continue
            else:
                item[override] = 1
        item[field] = value
        changes[index] = service.normalize_item(item, index+1, recalculate_sale=True)
    for index, item in changes.items(): items[index] = item


def inherit(items, index, field):
    item = dict(items[index])
    value = item.get('group_'+field)
    if field not in FIELDS or value is None: return False
    item[field] = value
    item[field.replace('_pct', '_override')] = 0
    items[index] = service.normalize_item(item, index+1, recalculate_sale=True)
    return True


def mark_individual(previous, current):
    for field in FIELDS:
        if service.number(previous.get(field)) != service.number(current.get(field)):
            current[field.replace('_pct', '_override')] = 1
    return current


def adopt_defaults(items):
    """A newly added line inherits this offer's subgroup settings, when unique."""
    from v710_cleanup import group_offer_items
    groups = []
    current = None
    for token in group_offer_items(items):
        if token['kind']=='group':
            current = [] if token.get('subgroup') not in ('',None,'Bez podskupiny') else None
            if current is not None: groups.append(current)
        elif current is not None and token['item'].get('row_type','product')=='product':
            current.append(token['index'])
    for indices in groups:
        for field in FIELDS:
            values = {items[i].get('group_'+field) for i in indices if items[i].get('group_'+field) is not None}
            if len(values)!=1: continue
            value = next(iter(values))
            added = [i for i in indices if items[i].get('group_'+field) is None]
            apply(items, added, field, value, group=True)
