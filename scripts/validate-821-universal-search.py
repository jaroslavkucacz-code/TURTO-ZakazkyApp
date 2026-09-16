#!/usr/bin/env python3
"""Literal matching and real Windows compound search across CRM workspaces."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.platform import universal_search as search


def source_checks():
    assert search.normalize(' ŽLUŤOUČKÁ  ŘEČ ') == 'zlutoucka rec'
    assert '16.09.2026' in search.searchable_text('2026-09-16')
    con = sqlite3.connect(':memory:')
    search.register_sql(con)
    con.execute('CREATE TABLE rows(name,company)')
    con.executemany('INSERT INTO rows VALUES(?,?)', [('Other', 'x')] * 600)
    con.execute('INSERT INTO rows VALUES(?,?)', ('Kolbenova 100%_!', 'ŽLUŤOUČKÁ'))
    clauses, params = [], []
    search.add_sql_terms(clauses, params, ['zlutoucka', '100%_!'], ['name', 'company'])
    sql = ' AND '.join(clauses)
    assert con.execute('SELECT count(*) FROM rows WHERE ' + sql, params).fetchone()[0] == 1
    assert con.execute('SELECT name FROM rows WHERE ' + sql + ' LIMIT 50', params).fetchone()[0] == 'Kolbenova 100%_!'
    assert not con.execute('SELECT name FROM rows WHERE ' + sql, ['zlutoucka', "' OR 1=1 --"]).fetchall()
    con.close()
    print('8.0.21: diacritics, literal wildcard characters, SQL binding and filtering before paging OK', flush=True)


def settle(root, seconds=.5):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform import commercial_workspace as commercial
    from price_lists_domain.platform import product_workspace
    from price_lists_domain.issued_offers import page as issued, service
    from price_lists_domain.platform.form_behavior_817 import values
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    root = app.App()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    fixture = {}
    try:
        root.state('normal')
        root.geometry('1280x900+0+0')
        settle(root, 4)
        with app.db() as con:
            for suffix in ('ALPHA', 'BETA'):
                name = '821 ' + suffix
                cid = con.execute('INSERT INTO companies(short_name,official_name,address) VALUES(?,?,?)',
                    (name, name, 'Žluťoučká Praha')).lastrowid
                pid = con.execute('INSERT INTO projects(name,investor) VALUES(?,?)', (name, 'Žluťoučká')).lastrowid
                aid = con.execute('INSERT INTO actions(name,company_id,project_id,created_date,status) VALUES(?,?,?,?,?)',
                    (name, cid, pid, '2099-09-16', 'Rozpracováno')).lastrowid
                person = con.execute('INSERT INTO people(name,email,company_id) VALUES(?,?,?)',
                    (name, suffix + '@zlutoucka.invalid', cid)).lastrowid
                task = con.execute('INSERT INTO tasks(action_id,due_date,text,assigned_user) VALUES(?,?,?,?)',
                    (aid, '2099-09-16', name, 'Žluťoučká')).lastrowid
                rid = con.execute('INSERT INTO requests(company_id,action_id,asked_date,item) VALUES(?,?,?,?)',
                    (cid, aid, '2099-09-16', name)).lastrowid
                fixture[suffix] = dict(actions='a'+str(aid), projects='p'+str(pid), people='p'+str(person),
                                      companies='c'+str(cid), tasks='t'+str(task), requests='r'+str(rid))
            mivo = con.execute("INSERT INTO companies(short_name,official_name) VALUES('MIVO','MIVO')").lastrowid
            for suffix in ('ALPHA', 'BETA'):
                rid = con.execute('INSERT INTO requests(company_id,asked_date,item) VALUES(?,?,?)',
                    (mivo, '2099-09-16', '821 '+suffix)).lastrowid
                fixture[suffix]['mivo'] = 'r'+str(rid)
            # The target is inserted FIRST and older than 300 filler rows: it
            # cannot appear on the initial first page of either offers table.
            for i in range(301):
                target = i == 0
                label = '821 Žluťoučká ALPHA' if target else '821 filler '+str(i)
                date = '2000-01-01' if target else '2099-09-16'
                oid = con.execute('INSERT INTO supplier_offers(offer_date,offer_number,supplier_name) VALUES(?,?,?)',
                    (date, label, 'Supplier')).lastrowid
                bid = con.execute('INSERT INTO business_documents(document_type,direction,document_number,issue_date,customer_name_snapshot) VALUES(?,?,?,?,?)',
                    (service.DOCUMENT_TYPE, service.DOCUMENT_DIRECTION, label, date, 'Customer')).lastrowid
                cp = con.execute('INSERT INTO catalog_products(internal_code,internal_name,manufacturer_name) VALUES(?,?,?)',
                    (str(i), label, 'Maker')).lastrowid
                if target:
                    target_offer, target_issued, target_product = 'o'+str(oid), 'bo'+str(bid), cp
            pl = con.execute("INSERT INTO price_lists(title,supplier_name,valid_from,parse_status) VALUES('821 Žluťoučká ALPHA','Supplier','2000-01-01','OK')").lastrowid
            for i in range(301):
                label = 'ZZZ 821 Žluťoučká ALPHA' if i == 0 else 'AAA filler '+str(i)
                item = con.execute('INSERT INTO price_list_items(price_list_id,product_code,name,normalized_unit_price,source_price,currency,unit) VALUES(?,?,?,?,?,?,?)',
                    (pl, str(i), label, 10, 10, 'CZK', 'ks')).lastrowid
                if i == 0:
                    target_price = 'pc'+str(item)

        def type_term(bar, text, confirm=False):
            bar.entry.focus_force()
            bar.draft.set(text)
            settle(root)
            if confirm:
                bar.entry.event_generate('<Return>')
                settle(root)
                assert bar.draft.get() == '' and root.focus_get() is bar.entry

        trees = dict(actions='action_tree', requests='request_tree', mivo='mivo_tree', projects='project_tree',
                     people='people_tree', companies='company_tree', tasks='task_tree')
        for key, attribute in trees.items():
            root.show_page(key)
            settle(root)
            tree = getattr(root, attribute)
            bar = root._table_searches[key]
            type_term(bar, '821', True)
            assert set(fixture[s][key] for s in fixture) <= set(tree.get_children()), key
            type_term(bar, 'alpha', True)
            assert tuple(tree.get_children()) == (fixture['ALPHA'][key],), (key, tree.get_children())
            type_term(bar, 'no match')
            assert not tree.get_children(), key
            bar.draft.set('')
            settle(root)
            bar.buttons[1].invoke()
            settle(root)
            assert set(fixture[s][key] for s in fixture) <= set(tree.get_children()), key
            bar.clear_button.invoke()
            settle(root)
            assert not bar.terms and set(fixture[s][key] for s in fixture) <= set(tree.get_children())
            print('Compound main table OK:', key, flush=True)

        for page, key, attribute, target in (
            ('offers', 'offers', 'offer_tree', target_offer),
            ('issued_offers', 'issued_offers', 'issued_offer_tree', target_issued),
            ('pricelists', 'prices', 'price_current_tree', target_price),
        ):
            root.show_page(page)
            settle(root)
            bar, tree = root._table_searches[key], getattr(root, attribute)
            type_term(bar, 'zlutoucka', True)
            type_term(bar, 'alpha')
            assert target in tree.get_children(), (key, tree.get_children())
            assert len(tree.get_children()) == 1, key
            bar.clear()
            settle(root)
            print('Whole-dataset paginated search OK:', key, flush=True)
        root.price_notebook.select(1)
        settle(root)
        bar = root._table_searches['price_evidence']
        type_term(bar, 'zlutoucka', True)
        type_term(bar, 'alpha')
        assert 'pl'+str(pl) in root.price_list_evidence_tree.get_children()
        bar.clear()

        # Catalogue query is also used by the embedded and dialog workspace.
        count, rows, _ = product_workspace._catalog_rows(app, {'kind':'all'}, search_terms=['zlutoucka','alpha'])
        assert count >= 1 and target_product in [row['id'] for row in rows]
        picker_rows = service.catalog_products(app, '', 50, search_terms=['zlutoucka','alpha'])
        assert target_product in [row['catalog_product_id'] for row in picker_rows]

        root.show_page('actions')
        settle(root)
        bar, tree = root._table_searches['actions'], root.action_tree
        original = tree.cget('displaycolumns')
        tree.configure(displaycolumns=('Stav', 'Přijato'))
        type_term(bar, 'alpha', True)
        assert tuple(tree.get_children()) == (fixture['ALPHA']['actions'],)
        tree.configure(displaycolumns=original)
        bar.entry.event_generate('<Return>')  # Empty confirmation changes nothing.
        assert bar.confirmed == ['alpha']
        bar.draft.set('alpha')
        bar.confirm()
        assert bar.confirmed == ['alpha']  # Case/diacritic-equivalent duplicates.
        for i in range(18):
            bar.draft.set('delší potvrzená podmínka '+str(i))
            bar.confirm()
        settle(root)
        assert all(button.winfo_ismapped() for button in bar.buttons)
        assert len({int(button.place_info()['y']) for button in bar.buttons}) > 1
        bar.clear()
        settle(root)

        # Search must not mark an editor form dirty; Enter does not bubble to save.
        win = app.tk.Toplevel(root)
        saved = []
        win.bind('<Return>', lambda event: saved.append(True))
        local = search.SearchBar(win, lambda: None)
        local.pack(fill='x')
        settle(root)
        before = values(win)
        type_term(local, 'žluťoučká', True)
        assert values(win) == before and not saved
        local.draft.set('pending callback')
        win.destroy()
        settle(root)
        assert not errors, errors
        print('8.0.21: Windows live/Enter/chips/clear, all main tables, pagination, hidden columns, wrapping, dialog routing and teardown OK', flush=True)
    finally:
        root._turto_closing = True
        root.destroy()


if __name__ == '__main__':
    source_checks()
    if '--source-only' not in sys.argv:
        with tempfile.TemporaryDirectory(prefix='turto-821-') as td:
            run(td)
