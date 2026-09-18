"""Typed, bounded calls to the server directory API; never a SQLite fallback."""
import json
from uuid import UUID, uuid4
from .migration import schema_name


class DirectoryError(ValueError):
    pass


class AccessDenied(DirectoryError):
    pass


class Conflict(DirectoryError):
    pass


class ConnectionUnavailable(DirectoryError):
    pass


class UncertainWrite(DirectoryError):
    def __init__(self, request_id):
        self.request_id = str(request_id)
        super().__init__('Spojení se přerušilo. Výsledek uložení je nutné ověřit na serveru.')


class DirectoryClient:
    def __init__(self, profile, schema, password=None):
        self.profile, self.schema = profile, schema_name(schema)
        self._password = password  # Memory only; never written to a profile or diagnostic.
        self._closed = False

    def close(self):
        self._password = None
        self._closed = True

    def _call(self, name, args=(), writing=None):
        if self._closed:
            raise AccessDenied('Přihlaste se znovu osobním serverovým účtem.')
        import psycopg
        from psycopg import sql
        submitted = False
        try:
            with self.profile.connect(password=self._password) as con:
                con.execute("SET statement_timeout='15000'; SET lock_timeout='5000'")
                statement = sql.SQL('SELECT {}({})').format(sql.Identifier(self.schema, name),
                    sql.SQL(',').join(sql.Placeholder() for _ in args))
                submitted = True
                return con.execute(statement, args).fetchone()[0]
        except psycopg.Error as exc:
            if exc.sqlstate in ('P2001', '42501', '28000', '28P01'):
                raise AccessDenied('Přístup byl zamítnut. Ověřte účet, heslo a oprávnění.') from None
            if exc.sqlstate == 'P2002':
                raise Conflict('Společnost mezitím změnil jiný uživatel. Vaše úpravy se neuložily; načtěte aktuální údaje.') from None
            if exc.sqlstate == 'P2003':
                raise DirectoryError('Společnost už neexistuje.') from None
            if exc.sqlstate and exc.sqlstate.startswith(('22', '23')):
                raise DirectoryError('Neplatné údaje společnosti. Zkontrolujte vyplněná pole.') from None
            if exc.sqlstate is None or exc.sqlstate.startswith('08'):
                if writing is not None and submitted:
                    raise UncertainWrite(writing) from None
                raise ConnectionUnavailable('Připojení k firemnímu serveru se nezdařilo. Ověřte firemní síť nebo VPN, účet, heslo a certifikát.') from None
            raise DirectoryError('Serverová operace nebyla dokončena. Ověřte spojení a přípravu pilotu.') from None

    def identity(self):
        return self._call('network_identity')

    def companies(self, query='', limit=100, offset=0):
        return self._call('network_companies', (query, limit, offset))

    def company(self, company_id):
        return self._call('network_company', (company_id,))

    def save(self, company_id, revision, values, request_id=None):
        request_id = UUID(str(request_id)) if request_id else uuid4()
        return self._call('network_save_company',
                          (company_id, revision, json.dumps(values, ensure_ascii=False), request_id), writing=request_id)

    def history(self, company_id):
        return self._call('network_company_history', (company_id,))

    def operation(self, request_id):
        return self._call('network_operation', (UUID(str(request_id)),))
