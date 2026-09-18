"""Explicit, secret-free connection profiles for the isolated network pilot."""
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re


@dataclass(frozen=True)
class Profile:
    host: str
    dbname: str
    user: str
    port: int = 5432
    sslmode: str = 'verify-full'
    sslrootcert: str = ''
    password_env: str = 'TURTO_PG_PASSWORD'
    connect_timeout: int = 10

    def __post_init__(self):
        for name in ('host', 'dbname', 'user'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or any(c in value for c in '\r\n\x00'):
                raise ValueError(f'Neplatná hodnota {name}.')
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Port musí být celé číslo od 1 do 65535.')
        if type(self.connect_timeout) is not int or not 1 <= self.connect_timeout <= 60:
            raise ValueError('Časový limit musí být 1 až 60 sekund.')
        if self.sslmode not in ('verify-full', 'disable'):
            raise ValueError('Použijte verify-full; disable je povoleno jen pro místní test.')
        if self.sslmode == 'disable' and self.host not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Nešifrované spojení je povoleno jen na tomto počítači.')
        if not isinstance(self.password_env, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', self.password_env):
            raise ValueError('Neplatný název proměnné s heslem.')
        if not isinstance(self.sslrootcert, str) or '\x00' in self.sslrootcert:
            raise ValueError('Neplatná cesta k certifikátu.')

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError('Profil obsahuje neznámé položky. Heslo patří do prostředí, ne do JSON.')
        return cls(**data)

    def public(self):
        return asdict(self)

    def connect(self):
        try:
            import psycopg
        except ImportError:
            raise RuntimeError('Nainstalujte requirements-network.txt pro test PostgreSQL.') from None
        kwargs = {k: v for k, v in asdict(self).items() if k != 'password_env' and v != ''}
        kwargs['application_name'] = 'TURTO CRM migration rehearsal'
        kwargs['options'] = '-c statement_timeout=300000 -c lock_timeout=10000 -c idle_in_transaction_session_timeout=300000'
        if self.password_env in os.environ:
            kwargs['password'] = os.environ[self.password_env]
        # No fallback to SQLite: a failed server connection is always an error.
        return psycopg.connect(**kwargs, autocommit=True)

    def process_env(self):
        env = os.environ.copy()
        # Prevent ambient libpq connection settings from redirecting the backup.
        for key in tuple(env):
            if key.startswith('PG'):
                env.pop(key)
        env.update(PGHOST=self.host, PGPORT=str(self.port), PGDATABASE=self.dbname,
                   PGUSER=self.user, PGSSLMODE=self.sslmode,
                   PGCONNECT_TIMEOUT=str(self.connect_timeout), PGAPPNAME='TURTO CRM pilot backup')
        if self.sslrootcert:
            env['PGSSLROOTCERT'] = self.sslrootcert
        if self.password_env in os.environ:
            env['PGPASSWORD'] = os.environ[self.password_env]
        return env
