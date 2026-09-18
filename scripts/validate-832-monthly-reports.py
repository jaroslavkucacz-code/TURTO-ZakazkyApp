#!/usr/bin/env python3
"""Reporting data takeover, financial regressions and real embedded Windows UI."""
from contextlib import closing
import csv
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'ZakazkyApp_base_6.1'))
from price_lists_domain.monthly_reports.storage import ReportingStore, readonly, standalone_database
from price_lists_domain.monthly_reports.db import Database
from reporting_832_import_tests import ImportTests


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ReportingStore(self.root / 'crm.db')
        self.source = Database(self.root / 'standalone.db')
        self.source.execute("INSERT INTO delivery_notes(doc_no,doc_date,base_amount) VALUES('original','2026-08-01',1250)")
        self.store.database.execute("INSERT INTO delivery_notes(doc_no,doc_date,base_amount) VALUES('previous','2026-08-01',200)")
    def tearDown(self):
        self.temp.cleanup()
    def test_copy_includes_wal_and_keeps_previous_backup(self):
        with closing(sqlite3.connect(self.source.path)) as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.execute("INSERT INTO delivery_notes(doc_no,doc_date,base_amount) VALUES('wal','2026-09-01',400)")
            con.commit()
            original = self.source.path.read_bytes()
            backup = self.store.take_over(self.source.path)
            self.assertEqual(self.store.database.scalar('SELECT sum(base_amount) FROM delivery_notes'), 1650)
            self.assertEqual(self.source.path.read_bytes(), original)
            self.assertEqual(con.execute('SELECT count(*) FROM delivery_notes').fetchone()[0], 2)
            with closing(readonly(backup)) as recovery:
                self.assertEqual(recovery.execute('SELECT doc_no FROM delivery_notes').fetchone()[0], 'previous')
    def test_wrong_missing_and_corrupt_database_preserve_destination(self):
        wrong = self.root / 'actual_crm.db'
        with closing(sqlite3.connect(wrong)) as con:
            con.execute('CREATE TABLE companies(id INTEGER, name TEXT)')
            con.commit()
        corrupt = self.root / 'corrupt.db'; corrupt.write_bytes(b'not sqlite')
        before = self.store.path.read_bytes()
        for candidate in (wrong, corrupt, self.root / 'missing.db', self.store.path):
            with self.subTest(candidate=candidate), self.assertRaises((ValueError, sqlite3.Error)):
                self.store.take_over(candidate)
            self.assertEqual(before, self.store.path.read_bytes())
        self.assertFalse((self.root / 'missing.db').exists())
    def test_backup_failure_never_replaces_data(self):
        before = self.store.path.read_bytes()
        with patch.object(self.store.database, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.store.take_over(self.source.path)
        self.assertEqual(before, self.store.path.read_bytes())
    def test_newer_schema_is_rejected_without_changing_either_store(self):
        self.source.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        before = self.source.path.read_bytes(), self.store.path.read_bytes()
        with self.assertRaises(ValueError):self.store.take_over(self.source.path)
        self.assertEqual(before, (self.source.path.read_bytes(), self.store.path.read_bytes()))
    def test_legacy_schema_is_upgraded_only_in_copy(self):
        for column in ('sales_unit','sales_total','cost_unit','cost_total','margin_amount','margin_percent'):
            self.source.execute('ALTER TABLE profit_items DROP COLUMN ' + column)
        self.source.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        before = self.source.path.read_bytes()
        self.store.take_over(self.source.path)
        self.assertEqual(before, self.source.path.read_bytes())
        self.assertEqual(self.store.database.scalar("SELECT value FROM meta WHERE key='schema_version'"), '2')
    def test_each_crm_database_and_test_have_separate_stores(self):
        other = ReportingStore(self.root / 'second.db')
        testing = ReportingStore(self.root / 'test_session' / 'zakazky_test.db')
        self.assertEqual(len({self.store.path, other.path, testing.path}), 3)
        self.assertEqual(other.database.scalar('SELECT count(*) FROM delivery_notes'), 0)
        self.assertEqual(testing.database.scalar('SELECT count(*) FROM delivery_notes'), 0)
        self.assertFalse((self.root / 'crm.db').exists(), 'Reporting must not open or create CRM business database')
    def test_discovery_uses_standalone_config_without_writing(self):
        folder = self.root / 'standalone'; folder.mkdir()
        config = folder / 'config.json'
        config.write_text(json.dumps({'database_path': str(self.source.path)}), encoding='utf-8-sig')
        before = config.read_bytes()
        with patch.dict(os.environ, {'TURTO_REPORTING_DATA_ROOT': str(folder)}):
            self.assertEqual(standalone_database(), self.source.path.resolve())
        self.assertEqual(config.read_bytes(), before)


def settle(root, seconds=.25):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(.01)


def wait_until(root, predicate, timeout=20):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:raise AssertionError('Timed out waiting for reporting operation')
        settle(root, .05)


def walk(root):
    yield root
    for child in root.winfo_children():yield from walk(child)


def ui_checks(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import tkinter as tk
    from tkinter import ttk
    import app, data_location, runtime_bootstrap
    from PIL import ImageGrab
    from price_lists_domain.monthly_reports import PAGES
    from price_lists_domain.monthly_reports.charts import BusinessChart, ShareChart
    from price_lists_domain.monthly_reports.xlsx_reader import XlsxReader
    from price_lists_domain.platform.calm_theme_820 import palette
    from price_lists_domain.platform.table_preferences_815 import key_for
    data_location.apply_to_app(app)
    app.ensure_schema(); runtime_bootstrap.apply_all(app); app.ensure_schema(); app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.APP_VERSION = (REPO / 'build/windows/version.txt').read_text().strip()
    errors = []
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    app.messagebox.showerror = lambda *a, **k: errors.append(str(a))
    app.App.report_callback_exception = lambda self, *exc: errors.append(str(exc))
    root = app.App()
    try:
        root.state('normal'); root.geometry('1220x850+0+0'); settle(root, 3)
        assert getattr(root, '_reports_workspace', None) is None, 'Do not load reports on CRM startup'
        root.nav['reports'].invoke(); settle(root, 1)
        w = root._reports_workspace
        assert w.current_page == 'Přehled' and w.last_error is None, w.last_error
        assert w.winfo_toplevel() is root and root._current_page == 'reports_overview'
        assert w.db.path != Path(app.DB)
        for key, label in PAGES.items():
            root.nav[key].invoke(); settle(root)
            assert w.current_page == label and w.last_error is None, (key, w.last_error)
        # Import through the actual preview dialog, cancelling first and then saving.
        source = Path(td) / 'delivery.csv'
        with source.open('w', encoding='utf-8-sig', newline='') as handle:
            csv.writer(handle, delimiter=';').writerows([
                ['Číslo','Datum','Kč základní','Firma','Středisko','Zakázka'],
                ['26SV1','2026-08-01',1000,'Alpha','M','Akce A'],
                ['26SV2','2026-08-02',2000,'Beta','J','Akce B'],
                ['25SV1','2025-08-01',800,'Alpha','M','Akce A']])
        def preview():
            return next((x for x in walk(root) if isinstance(x, tk.Toplevel) and x.title() == 'Kontrola před importem'), None)
        for save in (False, True):
            with patch('tkinter.filedialog.askopenfilenames', return_value=(str(source),)):
                w.do_import()
            # Closing or entering TEST must not abandon a pending import.
            previous_user = root.active_user.get(); root.close_app(); root.select_user('TEST')
            assert root.winfo_exists() and root.active_user.get() == previous_user and not root._turto_closing
            wait_until(root, lambda: preview() is not None)
            dialog = preview()
            assert w.db.scalar('SELECT count(*) FROM delivery_notes') == 0
            button = next(x for x in walk(dialog) if isinstance(x, tk.Button) and x.cget('text') == ('Uložit import' if save else 'Zrušit'))
            button.invoke(); wait_until(root, lambda: not w.busy)
        assert w.db.scalar('SELECT count(*) FROM delivery_notes') == 3
        assert w.analytics.kpis(2026, 8)['revenue'] == 3000
        w.period_var.set('2026-08'); w.mode_var.set('Měsíc'); w.refresh_current()
        assert w.db.scalar('SELECT count(*) FROM imports') == 1
        output = REPO / 'build/validation/reports-832'; output.mkdir(parents=True, exist_ok=True)
        for theme in ('Světlý', 'Tmavý'):
            root.apply_theme(theme); settle(root)
            for key, label in PAGES.items():
                root.nav[key].invoke(); settle(root, .35)
                assert w.current_page == label and w.last_error is None, (key, w.last_error)
                assert w.cget('bg') == palette(root)['bg']
                for name in ('reports', *PAGES):
                    button = root.nav[name]
                    assert button.winfo_viewable(), name
                    assert button.winfo_width() >= button.winfo_reqwidth(), (name, 'clipped')
                    assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width(), (name, 'outside')
                    assert button.winfo_rooty() + button.winfo_height() <= root.host.winfo_rooty(), (name, 'overlap')
                if key in ('reports_overview','reports_customers','reports_settings'):
                    ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),root.winfo_rootx()+root.winfo_width(),root.winfo_rooty()+root.winfo_height()), all_screens=True).save(output / f'{key}-{theme}.png')
        root.show_page('reports_customers'); settle(root)
        tree = next(x for x in walk(w.container) if isinstance(x, ttk.Treeview))
        assert len(tree.get_children()) == 2
        tree.search_var.set('Alpha'); assert len(tree.get_children()) == 1
        customers_key = key_for(tree)
        w.open_customer_detail('Alpha'); settle(root)
        w.open_document_detail('26SV1'); settle(root)
        assert len([x for x in walk(root) if isinstance(x, tk.Toplevel) and ('historie' in x.title() or 'položky dodacího listu' in x.title())]) == 2
        for x in tuple(w.winfo_children()):
            if isinstance(x, tk.Toplevel):x.destroy()
        root.show_page('reports_products'); settle(root)
        product_tree = next(x for x in walk(w.container) if isinstance(x, ttk.Treeview))
        assert key_for(product_tree) != customers_key
        root.show_page('reports_overview'); settle(root)
        chart = next(x for x in walk(w) if isinstance(x, BusinessChart))
        chart.set_view('lines')
        w.mode_var.set('YTD'); w.refresh_current()
        selected_db = w.db.path
        saved = app.get_user_setting(root.active_user.get(), 'monthly_reports_preferences_832')
        assert json.loads(saved)['mode'] == 'YTD'
        # Export through UI, including the actual installed Edge PDF engine.
        for suffix, method in (('xlsx', w.export_xlsx), ('pdf', w.export_pdf)):
            destination = Path(td) / ('report.' + suffix)
            with patch('tkinter.filedialog.asksaveasfilename', return_value=str(destination)):
                method()
            wait_until(root, lambda: not w.busy, 120)
            assert destination.exists() and destination.stat().st_size > 1000
            if suffix == 'xlsx':
                with XlsxReader(destination) as reader:assert 'Kontrola dat' in reader.sheet_names
            else:assert destination.read_bytes().startswith(b'%PDF-')
        # Restart the view via a real user switch; chart/scope preferences survive.
        current_user = root.active_user.get()
        root.select_user(current_user); root.show_page('reports_overview'); settle(root, .6)
        w = root._reports_workspace
        assert w.mode_var.get() == 'YTD' and w.db.path == selected_db
        chart = next(x for x in walk(w) if isinstance(x, BusinessChart))
        assert chart.view == 'lines'
        root.select_user('TEST'); root.show_page('reports_overview'); settle(root, .7)
        assert root._reports_workspace.db.path != selected_db
        assert root._reports_workspace.db.scalar('SELECT count(*) FROM delivery_notes') == 0
        root.select_user(current_user); root.show_page('reports_overview'); settle(root, .7)
        assert root._reports_workspace.db.path == selected_db
        assert root._reports_workspace.db.scalar('SELECT count(*) FROM delivery_notes') == 3
        for width in (1500, 1220):
            root.geometry(f'{width}x850+0+0'); settle(root)
            root.show_page('reports_settings'); settle(root)
            root.show_page('technical'); settle(root)
            root.show_page('reports'); settle(root)
            assert root._current_page == 'reports_settings'
        root.show_page('companies'); settle(root)
        assert not errors, errors
        print('8.0.32: eleven embedded pages, two themes, responsive navigation, import preview/cancel/save, drilldowns, XLSX/PDF, user preferences, TEST separation and shutdown guard OK', flush=True)
    finally:
        root._turto_closing = True
        for token in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(token)
        root.destroy()


if __name__ == '__main__':
    if '--ui-worker' in sys.argv:
        ui_checks(sys.argv[sys.argv.index('--ui-worker')+1])
    else:
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in (ImportTests, StorageTests))
        if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
        if '--source-only' not in sys.argv:
            with tempfile.TemporaryDirectory(prefix='turto-reports-832-') as td:
                subprocess.run([sys.executable,str(Path(__file__).resolve()),'--ui-worker',td], check=True)
