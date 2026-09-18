"""Build a fresh dataset using the actual CRM migrations, never user data."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))


def main():
    from network_db.source import snapshot
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        spec = importlib.util.spec_from_file_location('network_seed', REPO / 'scripts/validate-834-user-access.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        app, _ = module.prepare(tmp)
        with closing(app.db()) as con, con:
            for name, permission in (('Pilot – editor', 2), ('Pilot – čtenář', 1)):
                con.execute('INSERT INTO users(name,tab_permissions) VALUES(?,?)', (name, json.dumps({'companies': permission})))
            con.execute("INSERT INTO companies(short_name,official_name,address,note) VALUES(?,?,?,?)",
                        ('Zkušební společnost', 'Zkušební společnost TURTO – ukázková data', 'Ukázková adresa',
                         'Toto jsou umělá data pro vyzkoušení síťového pilotu.'))
        snapshot(app.DB, output)
    print('Artificial demo database built:', output.name)


if __name__ == '__main__':
    main()
