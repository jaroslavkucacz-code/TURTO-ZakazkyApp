"""Server-owned directory API for an isolated, already migrated pilot schema.

Personal PostgreSQL logins can execute only the public functions below. They
cannot read/write CRM tables, role bindings or audit records directly.
"""
from pathlib import Path
from .migration import schema_name, verify

API_SIGNATURES = ('network_identity()', 'network_companies(text,integer,integer)',
                  'network_company(bigint)', 'network_save_company(bigint,bigint,jsonb,uuid)',
                  'network_company_history(bigint)', 'network_operation(uuid)')


def _owner(con, schema):
    row = con.execute('''SELECT n.nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
        OR (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
        FROM pg_namespace n WHERE n.nspname=%s''', (schema,)).fetchone()
    if not row or not row[0]:
        raise ValueError('Přípravu serveru smí provést pouze vlastník schématu nebo správce PostgreSQL.')


def install(profile, schema):
    """Install once. Never silently adopt an edited or partly upgraded copy."""
    from psycopg import sql
    schema_name(schema)
    with profile.connect() as con, con.transaction():
        _owner(con, schema)
        con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('TURTO directory ' + schema,))
        manifest = con.execute(sql.SQL('SELECT manifest FROM {} WHERE id=1 FOR UPDATE').format(
            sql.Identifier(schema, '_turto_pilot_manifest'))).fetchone()[0]
        if manifest.get('directory_api_version') == 1:
            return  # Safe idempotence; never resets revisions or permissions.
        if manifest.get('directory_api_version') is not None:
            raise ValueError('Nepodporovaná verze serverové agendy.')
        # Guard against changes between verification and installation.
        con.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(
            sql.SQL(',').join(sql.Identifier(schema, t['name']) for t in manifest['tables'])))
        if not verify(profile, schema)['ok']:
            raise ValueError('Kopie se změnila od převodu. Nejprve prověřte rozdíly.')
        if manifest.get('application_ready') is not False:
            raise ValueError('Síťový pilot lze připravit jen v testovací kopii.')
        # Defaults, grants and statements in this SQL file are owned here, never
        # taken from input database DDL or user text. Schema names are quoted.
        template = Path(__file__).with_name('directory.sql').read_text(encoding='utf-8')
        statement = template.replace('__SCHEMA__', sql.Identifier(schema).as_string(con))
        con.execute(statement, prepare=False)
        for signature in ('network_claims(integer)', *API_SIGNATURES):
            con.execute(sql.SQL('REVOKE ALL ON FUNCTION {}.{} FROM PUBLIC').format(
                sql.Identifier(schema), sql.SQL(signature)))
        con.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        con.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        con.execute(sql.SQL("UPDATE {} SET manifest=manifest || %s::jsonb WHERE id=1").format(
            sql.Identifier(schema, '_turto_pilot_manifest')),
            ('{"directory_api_version":1,"application_ready":false}',))


def authorize(profile, schema, login, user_id):
    """Bind an existing restricted database login to an existing CRM identity."""
    from psycopg import sql
    schema_name(schema)
    if not isinstance(login, str) or not login or len(login.encode('utf-8')) > 63:
        raise ValueError('Neplatný serverový účet.')
    if type(user_id) is not int or user_id <= 0:
        raise ValueError('Neplatné ID uživatele CRM.')
    with profile.connect() as con, con.transaction():
        _owner(con, schema)
        role = con.execute('''SELECT oid,rolcanlogin,rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls
                              FROM pg_roles WHERE rolname=%s''', (login,)).fetchone()
        if not role or not role[1] or any(role[2:]):
            raise ValueError('Použijte osobní účet LOGIN bez správních oprávnění.')
        if con.execute('SELECT 1 FROM pg_auth_members WHERE member=%s', (role[0],)).fetchone():
            raise ValueError('Pilot vyžaduje samostatný účet bez členství v jiných databázových rolích.')
        if con.execute('SELECT datdba=%s FROM pg_database WHERE datname=current_database()', (role[0],)).fetchone()[0]:
            raise ValueError('Pro běžnou práci nelze použít vlastníka databáze.')
        if con.execute('SELECT has_schema_privilege(%s,%s,%s)', (login, schema, 'CREATE')).fetchone()[0]:
            raise ValueError('Osobní účet nesmí mít právo měnit schéma.')
        direct = con.execute('''SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relkind IN ('r','p') AND
            has_table_privilege(%s,c.oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') LIMIT 1''',
                             (schema, login)).fetchone()
        if direct:
            raise ValueError('Osobní účet má přímý přístup k tabulkám; nejprve jej odeberte.')
        user = con.execute(sql.SQL('SELECT id FROM {} WHERE id=%s AND active=1 FOR SHARE').format(
            sql.Identifier(schema, 'users')), (user_id,)).fetchone()
        if not user:
            raise ValueError('Vybraný uživatel CRM neexistuje nebo není aktivní.')
        # pg_restore --no-privileges restores PostgreSQL's default function ACL.
        # Seal it again before granting schema access on a restored copy.
        for signature in ('network_claims(integer)', *API_SIGNATURES):
            con.execute(sql.SQL('REVOKE ALL ON FUNCTION {}.{} FROM PUBLIC').format(
                sql.Identifier(schema), sql.SQL(signature)))
        con.execute(sql.SQL('''INSERT INTO {}(db_login,user_id) VALUES(%s,%s)
            ON CONFLICT(db_login) DO UPDATE SET user_id=excluded.user_id''').format(
                sql.Identifier(schema, '_network_logins')), (login, user_id))
        con.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), sql.Identifier(login)))
        for signature in API_SIGNATURES:
            con.execute(sql.SQL('GRANT EXECUTE ON FUNCTION {}.{} TO {}').format(
                sql.Identifier(schema), sql.SQL(signature), sql.Identifier(login)))


def revoke(profile, schema, login):
    from psycopg import sql
    schema_name(schema)
    with profile.connect() as con, con.transaction():
        _owner(con, schema)
        con.execute(sql.SQL('DELETE FROM {} WHERE db_login=%s').format(
            sql.Identifier(schema, '_network_logins')), (login,))
        # Bindings are checked on every call, so removal also revokes existing sessions.
