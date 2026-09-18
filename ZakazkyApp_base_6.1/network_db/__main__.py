"""python -m network_db: explicit CLI for rehearsal, never production activation."""
import argparse
import json
from pathlib import Path
import sys

from .profile import Profile
from .source import inspect, snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description='TURTO CRM – zkušební převod dat do PostgreSQL, bez přepnutí CRM')
    commands = parser.add_subparsers(dest='command', required=True)
    audit = commands.add_parser('inspect', help='Zkontrolovat kopii SQLite bez připojení k serveru')
    audit.add_argument('--source', required=True)
    audit.add_argument('--report', required=True)
    copy = commands.add_parser('snapshot', help='Vytvořit konzistentní místní kopii SQLite včetně WAL')
    copy.add_argument('--source', required=True)
    copy.add_argument('--target', required=True)
    ping = commands.add_parser('check', help='Ověřit spojení bez změny databáze')
    ping.add_argument('--profile', required=True)
    for name in ('migrate', 'verify', 'backup', 'directory-install', 'directory-authorize', 'directory-revoke'):
        command = commands.add_parser(name)
        command.add_argument('--profile', required=True)
        command.add_argument('--schema', required=True)
        if name == 'migrate':
            command.add_argument('--source', required=True, help='Předem vytvořená kopie SQLite')
            command.add_argument('--report', required=True)
        if name == 'backup':
            command.add_argument('--target', required=True)
            command.add_argument('--allow-pilot-changes', action='store_true')
        if name in ('directory-authorize', 'directory-revoke'):
            command.add_argument('--login', required=True)
        if name == 'directory-authorize':
            command.add_argument('--user-id', required=True, type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == 'snapshot':
            snapshot(args.source, args.target)
            print('Kopie byla vytvořena. Původní databáze nebyla upravena.')
            return 0
        if args.command == 'inspect':
            result = inspect(args.source)
        else:
            profile = Profile.load(args.profile)
            if args.command == 'check':
                with profile.connect() as con:
                    version = con.execute('SHOW server_version').fetchone()[0]
                print('Připojení funguje. PostgreSQL ' + version)
                return 0
            if args.command.startswith('directory-'):
                from .directory import install, authorize, revoke
                if args.command == 'directory-install':
                    install(profile, args.schema)
                elif args.command == 'directory-authorize':
                    authorize(profile, args.schema, args.login, args.user_id)
                else:
                    revoke(profile, args.schema, args.login)
                print('Nastavení síťového adresáře bylo dokončeno.')
                return 0
            from .migration import migrate, verify
            if args.command == 'migrate':
                # Reserve the report before changing the server; never overwrite
                # an earlier audit or the source DB via a mistaken --report path.
                with Path(args.report).open('x', encoding='utf-8') as output:
                    result = migrate(args.source, profile, args.schema)
                    output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                print('Kopie dat byla ověřena. Schéma: ' + args.schema + '. CRM stále používá SQLite.')
                return 0
            if args.command == 'verify':
                result = verify(profile, args.schema)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result['ok'] else 2
            from .backup import backup
            backup(profile, args.schema, args.target, allow_pilot_changes=args.allow_pilot_changes)
            print('Záloha pilotního schématu byla vytvořena. Obnovu ověřte v samostatné testovací databázi.')
            return 0
        with Path(args.report).open('x', encoding='utf-8') as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print('Kontrola dokončena. Tabulek: ' + str(len(result['tables'])))
        return 0
    except Exception as exc:
        # Driver/server errors may contain connection secrets or business values.
        # Known validation errors contain only our static, value-free messages.
        if type(exc) in (ValueError, RuntimeError, TimeoutError, FileExistsError, FileNotFoundError):
            message = str(exc) if type(exc) not in (FileExistsError, FileNotFoundError) else 'Soubor již existuje nebo chybí. Zkontrolujte cesty.'
        else:
            message = 'Operace selhala (' + type(exc).__name__ + '). Ověřte spojení, oprávnění a kompatibilitu vstupu.'
        print(message, file=sys.stderr)
        if args.command == 'migrate':
            print('Nevytvářejte místní náhradní data. Stav serverového převodu lze ověřit příkazem verify.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
