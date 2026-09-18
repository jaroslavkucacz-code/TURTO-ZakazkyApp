"""Explicit installation of the bundled artificial CRM dataset on a test server."""
from pathlib import Path
from .migration import migrate, schema_name
from .directory import install, _owner


def prepare(profile, schema):
    source = Path(__file__).with_name('demo.db')
    if not source.is_file():
        raise ValueError('Ukázková databáze chybí. Použijte připravený Windows balíček pilotu.')
    migrate(source, profile, schema)
    install(profile, schema)


def users(profile, schema):
    from psycopg import sql
    schema_name(schema)
    with profile.connect() as con:
        _owner(con, schema)
        return [{'id': row[0], 'name': row[1], 'active': row[2], 'permissions': row[3]}
                for row in con.execute(sql.SQL('SELECT id,name,active,tab_permissions FROM {} ORDER BY id').format(
                    sql.Identifier(schema, 'users')))]
