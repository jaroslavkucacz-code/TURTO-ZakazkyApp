"""Offer-local row moves. Catalog assignments and historical documents are untouched."""
from . import service

TAXONOMY = ('category_id', 'subgroup_id', 'category_name_snapshot',
            'subgroup_name_snapshot', 'category', 'subgroup')


def group_key(item):
    return (item.get('category_id') or str(item.get('category_name_snapshot') or item.get('category') or '').casefold(),
            item.get('subgroup_id') or str(item.get('subgroup_name_snapshot') or item.get('subgroup') or '').casefold())


def target_item(items, region):
    index = region.get('index')
    if index is None:
        members = region.get('indices', [])
        if not members: return None
        index = members[0]
    target = dict(items[index])
    if region.get('kind') == 'category':
        target.update(subgroup_id=None, subgroup_name_snapshot='', subgroup='', group_margin_pct=None, group_discount_pct=None)
    return target


def move(items, source, region, after=False):
    """Return new selected index. Caller confirms any taxonomy change beforehand."""
    from v710_cleanup import group_offer_items
    if not 0 <= source < len(items): return source
    original = items[source]
    if original.get('row_type', 'product') != 'product': return source
    target = target_item(items, region)
    if target is None or target.get('row_type', 'product') != 'product': return source
    anchor = region.get('index')
    if anchor is None: anchor = region['indices'][0]
    if anchor == source and group_key(original) == group_key(target): return source
    changed = dict(original)
    if group_key(original) != group_key(target):
        for key in TAXONOMY: changed[key] = target.get(key)
        # Preserve the customer's prices. Different target defaults become
        # explicit line exceptions; users may subsequently choose inheritance.
        for field in ('margin_pct', 'discount_pct'):
            default = target.get('group_'+field)
            changed['group_'+field] = default
            if default is None or service.number(default) != service.number(changed.get(field)):
                changed[field.replace('_pct', '_override')] = 1
    order = [t['index'] for t in group_offer_items(items) if t['kind'] == 'item']
    order.remove(source)
    if anchor == source:
        insertion = 0
    else:
        insertion = order.index(anchor) + int(after)
    order.insert(insertion, source)
    result = [changed if i == source else dict(items[i]) for i in order]
    for position, item in enumerate(result, 1): item['position'] = position
    items[:] = result
    return insertion


def warning(original, target):
    category = target.get('category_name_snapshot') or target.get('category') or 'Nezařazeno'
    subgroup = target.get('subgroup_name_snapshot') or target.get('subgroup') or 'Bez podskupiny'
    return (f'Přesunout položku do zařazení:\n{category} › {subgroup}?\n\n'
            'Ceny, marže a sleva položky zůstanou zachované. Pokud se liší od nastavení cílové '
            'podskupiny, budou označené jako individuální. Změna platí pouze pro tuto nabídku.')
