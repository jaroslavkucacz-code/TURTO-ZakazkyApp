"""Template-owned subgroup presentation. Never changes product/pricing data."""
import copy

FLAGS = ('show_description', 'show_code', 'show_line_note')


def scope(item):
    return dict(category_id=item.get('category_id') or None, subgroup_id=item.get('subgroup_id') or None,
                category=str(item.get('category_name_snapshot') or item.get('category') or 'Nezařazeno').strip(),
                subgroup=str(item.get('subgroup_name_snapshot') or item.get('subgroup') or 'Bez podskupiny').strip())


def key(value):
    if value.get('subgroup_id'):
        return ('subgroup', int(value['subgroup_id']))
    if value.get('category_id') and value['subgroup'] == 'Bez podskupiny':
        return ('category', int(value['category_id']))
    return ('names', value['category'].casefold(), value['subgroup'].casefold())


def names(value):
    return value['category'].casefold(), value['subgroup'].casefold()


def find(rules, item):
    target = scope(item)
    exact = next((r for r in rules if key(r) == key(target)), None)
    if exact is not None:
        return exact
    # Unbound imported rules can match names; local foreign IDs cannot collide.
    matches = [r for r in rules if names(r) == names(target)
               and (not target.get('subgroup_id') or not r.get('subgroup_id'))
               and (not target.get('category_id') or not r.get('category_id'))]
    return matches[0] if len(matches) == 1 else None


def normalize(rules):
    from .template_layout import COLUMNS
    if not isinstance(rules, list) or len(rules) > 2000:
        raise ValueError('Neplatné nastavení podskupin (nejvýše 2000).')
    result, seen = [], set()
    for value in rules:
        if not isinstance(value, dict):
            raise ValueError('Nastavení podskupiny musí být objekt.')
        r = scope(value)
        for field in ('category_id', 'subgroup_id'):
            v = r[field]
            if v is not None:
                if isinstance(v, bool) or not str(v).isdigit() or int(v) <= 0:
                    raise ValueError('Neplatný identifikátor podskupiny.')
                r[field] = int(v)
        if any(not r[f] or len(r[f]) > 500 for f in ('category', 'subgroup')):
            raise ValueError('Název skupiny nebo podskupiny je příliš dlouhý.')
        columns = value.get('columns')
        if (not isinstance(columns, list) or not columns or len(columns) > len(COLUMNS)
                or any(not isinstance(c, str) or c not in COLUMNS for c in columns)
                or len(set(columns)) != len(columns) or 'name' not in columns):
            raise ValueError('Vyberte platné sloupce podskupiny; název výrobku musí zůstat zobrazený.')
        r['columns'] = list(columns)
        for field in FLAGS:
            v = value.get(field, True)
            if v not in (True, False, 0, 1):
                raise ValueError('Neplatná volba podskupiny: ' + field)
            r[field] = bool(v)
        if key(r) in seen:
            raise ValueError('Nastavení stejné podskupiny je uvedeno vícekrát.')
        seen.add(key(r))
        result.append(r)
    return result


def column_order(layout):
    """Keep shared ordering and place optional fields beside related columns."""
    standard = ('position', 'name', 'image', 'code', 'recommended', 'discount', 'unit_price', 'quantity', 'total')
    order = [c['key'] for c in layout['columns']]
    for at, column in enumerate(standard):
        if column not in order:
            following = next((k for k in standard[at+1:] if k in order), None)
            order.insert(order.index(following) if following else len(order), column)
    return order


def effective(layout, item):
    from .template_layout import COLUMNS
    result = dict(layout)
    rule = find(layout.get('subgroup_layouts', []), item)
    if rule is not None:
        definitions = {k: dict(key=k, label=v[0], width=v[1]) for k, v in COLUMNS.items()}
        definitions.update({c['key']: c for c in layout['columns']})
        result['columns'] = [dict(definitions[k]) for k in column_order(layout) if k in rule['columns']]
        result['show_images'] = True  # The subgroup's image column is explicit.
        result.update({f: rule[f] for f in FLAGS})
    return result


def choices(layout, item):
    from .template_layout import COLUMNS
    current = effective(layout, item)
    result = {'col:' + k: False for k in COLUMNS}
    result.update({'col:' + c['key']: True for c in current['columns'] if c['key'] != 'image' or current['show_images']})
    result.update({f: current.get(f, True) for f in FLAGS})
    return result


def change(layout, targets, changes, inherit=False):
    """Apply only explicit deltas; mixed selections retain all other differences."""
    from .template_layout import COLUMNS
    result = copy.deepcopy(layout.get('subgroup_layouts', []))
    for target in targets:
        old = find(result, target)
        current = choices(dict(layout, subgroup_layouts=result), target)
        current.update(changes)
        if old is not None:
            result.remove(old)
        if inherit:
            continue
        order = column_order(layout)
        rule = scope(target)
        rule.update(columns=[k for k in order if current['col:' + k]], **{f: current[f] for f in FLAGS})
        result.append(rule)
    return normalize(result)


def portable(layout):
    result = copy.deepcopy(layout)
    for rule in result.get('subgroup_layouts', []):
        rule['category_id'] = rule['subgroup_id'] = None
    return result
