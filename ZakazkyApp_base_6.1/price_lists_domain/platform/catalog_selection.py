"""Catalogues change only through an explicit catalogue command."""

TABLES = frozenset({'work_topics', 'person_roles', 'materials', 'salespeople'})


def existing_name(con, table, text, original=()):
    if table not in TABLES:
        raise ValueError('Neplatný číselník.')
    text = (text or '').strip()
    if not text:
        return ''
    for row in con.execute(f'SELECT name FROM {table} WHERE active=1'):
        if (row['name'] or '').strip().casefold() == text.casefold():
            return row['name']
    # Keep historical values on an existing record without recreating them in
    # the catalogue, including values deliberately deactivated by the user.
    for name in original:
        if (name or '').strip().casefold() == text.casefold():
            return name.strip()
    raise ValueError('Vyberte celý název z našeptávače. Novou položku založte výslovně přes „Nová…“ nebo „Spravovat“.')


def create_name(con, table, text):
    if table not in TABLES:
        raise ValueError('Neplatný číselník.')
    name = (text or '').strip()
    if not name:
        raise ValueError('Vyplňte název nové položky.')
    for row in con.execute(f'SELECT name,active FROM {table}'):
        if (row['name'] or '').strip().casefold() == name.casefold():
            if not row['active']:
                raise ValueError('Položka už existuje jako neaktivní. Upravte ji ve správě číselníku.')
            return row['name']
    con.execute(f'INSERT INTO {table}(name,active) VALUES(?,1)', (name,))
    return name
