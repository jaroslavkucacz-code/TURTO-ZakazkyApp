"""Independent report store beside the active CRM database; never migrate CRM tables.

SQLite's backup API includes committed WAL pages and commits the destination
atomically. The source is opened read-only and every replacement is validated
in a temporary store, with a recovery snapshot of the previous destination.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .db import Database, SCHEMA


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=20)


def validate(connection):
    if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('Databáze přehledů neprošla kontrolou integrity.')
    with closing(sqlite3.connect(':memory:')) as expected:
        expected.executescript(SCHEMA)
        for (table,) in expected.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            columns = {row[1] for row in expected.execute(f'PRAGMA table_info("{table}")')}
            if table == 'profit_items':
                columns -= {'sales_unit', 'sales_total', 'cost_unit', 'cost_total', 'margin_amount', 'margin_percent'}
            actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            if not columns <= actual:
                raise ValueError('Vybraný soubor není podporovaná databáze Měsíčních přehledů.')
    version = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if version and int(version[0]) > 2:
        raise ValueError('Tato databáze vyžaduje novější verzi přehledů. Nejprve aktualizujte CRM.')
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Databáze přehledů obsahuje poškozené vazby.')


class ReportingStore:
    def __init__(self, crm_database):
        crm = Path(crm_database).resolve()
        self.root = crm.parent / (crm.stem + '_prehledy')
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'turto_dashboard.db'
        self.database = Database(self.path)

    def directory(self, name):
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def take_over(self, source):
        source = Path(source).resolve()
        if source == self.path.resolve():
            raise ValueError('Tato databáze je již otevřená v Přehledech.')
        backup = None
        with tempfile.TemporaryDirectory(prefix='prevzeti_', dir=self.root) as temp:
            staged = Path(temp) / 'reports.db'
            with closing(readonly(source)) as incoming, closing(sqlite3.connect(staged)) as copy:
                validate(incoming)
                incoming.backup(copy)
                validate(copy)
            # Apply supported schema upgrades only to the private copy.
            Database(staged)
            with closing(readonly(staged)) as incoming:
                validate(incoming)
                backup = self.database.backup(self.directory('backup'))
                with closing(sqlite3.connect(self.path, timeout=20)) as target:
                    incoming.backup(target)
        return backup


def standalone_database():
    """Suggest the installed app's actual configured file without changing it."""
    override = os.environ.get('TURTO_REPORTING_DATA_ROOT', '').strip()
    root = (Path(os.path.expandvars(os.path.expanduser(override))) if override else
            Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'TURTO' / 'MesicniPrehledy')
    config = {}
    try:
        value = json.loads((root / 'config.json').read_text(encoding='utf-8-sig'))
        if isinstance(value, dict):
            config = value
    except (OSError, ValueError):
        pass
    path = Path(os.path.expandvars(os.path.expanduser(str(config.get('database_path') or 'data/turto_dashboard.db'))))
    return (path if path.is_absolute() else root / path).resolve()


def preferences(module, user):
    value = module.get_user_setting(user, 'monthly_reports_preferences_832', '{}')
    try:
        config = json.loads(value)
    except (TypeError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    charts = config.get('chart_preferences')
    return {'default_period': str(config.get('default_period') or datetime.now().strftime('%Y-%m')),
            'mode': config.get('mode', 'Měsíc'),
            'chart_preferences': charts if isinstance(charts, dict) else {},
            'database_path': 'turto_dashboard.db', 'export_dir': 'exports',
            'import_archive_dir': 'imports', 'backup_dir': 'backup'}
