import csv
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'ZakazkyApp_base_6.1'))
from price_lists_domain.monthly_reports.db import Database
from price_lists_domain.monthly_reports.data_import import preview_imports,apply_imports,parse_file,number
from price_lists_domain.monthly_reports.report_model import Analytics,collect_report
from price_lists_domain.monthly_reports.management import collect_management,customer_changes


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=Database(self.root/'test.db')
    def tearDown(self):self.tmp.cleanup()
    def csv(self,name,rows):
        p=self.root/name
        with p.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f,delimiter=';').writerows(rows)
        return p
    def dl(self,name='dl.csv',no='26SV1',value='1000',dt='2026-08-01',customer='Alpha'):
        return self.csv(name,[['Číslo','Datum','Kč základní','Firma','Středisko','Zakázka'],[no,dt,value,customer,'M','Akce A']])
    def apply(self,paths,update=False):
        b=preview_imports(self.db,paths)
        return apply_imports(self.db,b,self.root/'archive',self.root/'backup',update)
    def test_preview_no_writes_and_duplicate(self):
        p=self.dl();b=preview_imports(self.db,[p]);self.assertEqual(self.db.scalar('SELECT count(*) FROM delivery_notes'),0)
        self.assertEqual(b.summaries[0]['new'],1)
        result=self.apply([p]);self.assertEqual(result['changed'],1);self.assertTrue(Path(result['backup']).exists())
        with closing(sqlite3.connect(result['backup'])) as c:self.assertEqual(c.execute('SELECT count(*) FROM delivery_notes').fetchone()[0],0)
        self.assertEqual(self.apply([p])['duplicates'],1);self.assertEqual(self.db.scalar('SELECT count(*) FROM imports'),1)
    def test_existing_changes_need_selection(self):
        p=self.dl();self.apply([p]);q=self.dl('corrected.csv',value='2200')
        self.assertEqual(preview_imports(self.db,[q]).summaries[0]['changed'],1)
        self.assertEqual(self.apply([q])['changed'],0)
        self.assertEqual(self.apply([q],True)['changed'],1)
        self.assertEqual(self.db.scalar('SELECT base_amount FROM delivery_notes'),2200)
    def test_stale_preview_and_changed_source(self):
        p=self.dl();b=preview_imports(self.db,[p]);self.db.execute("INSERT INTO monthly_summary(period) VALUES ('2020-01')")
        with self.assertRaisesRegex(ValueError,'Databáze se'):apply_imports(self.db,b,self.root/'ar',self.root/'bu')
        b=preview_imports(self.db,[p]);p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'soubor se'):apply_imports(self.db,b,self.root/'ar',self.root/'bu')
    def test_invalid_rows_numbers_and_empty(self):
        for value in ('nan','inf','xyz',''):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_file(self.dl(value=value))
        with self.assertRaises(ValueError):parse_file(self.dl(dt='2026-02-30'))
        p=self.csv('empty.csv',[['Číslo','Datum','Kč základní']])
        with self.assertRaises(ValueError):parse_file(p)
        self.assertEqual(number('1 234,56','test'),1234.56)
    def test_batch_rollback_on_sql_failure(self):
        p=self.dl();q=self.dl('second.csv',no='26SV2')
        self.db.execute("CREATE TRIGGER refuse BEFORE INSERT ON delivery_notes WHEN NEW.doc_no='26SV2' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.apply([p,q])
        self.assertEqual(self.db.scalar('SELECT count(*) FROM imports'),0)
        self.assertEqual(self.db.scalar('SELECT count(*) FROM delivery_notes'),0)
    def test_profit_first_then_delivery_and_item_replace(self):
        p=self.csv('profit.csv',[['Číslo DL','Datum','Firma','Kód','Název','Množství','Zisk celkem','Prodej celkem bez DPH','Náklad celkem bez DPH'],
             ['26SV1','2026-08-01','Alpha','','Výrobek','2','200','1000','800']])
        self.apply([p]);self.assertEqual(self.db.scalar('SELECT count(*) FROM profit_items'),1)
        q=self.dl();self.assertEqual(self.apply([q])['changed'],1)
        self.assertEqual(self.db.scalar('SELECT count(*) FROM profit_items'),1)
        self.assertEqual(collect_management(Analytics(self.db),2026,8)['coverage'][0]['missing_delivery'],0)
        self.assertEqual(Analytics(self.db).kpis(2026,8)['margin'],20)
        p.write_text(p.read_text(encoding='utf-8-sig').replace(';200;1000;800',';300;1000;700'),encoding='utf-8-sig')
        self.apply([p],True);self.assertEqual(self.db.scalar('SELECT count(*) FROM profit_items'),1)
        self.assertEqual(self.db.scalar('SELECT profit_total FROM profit_documents'),300)
    def test_mixed_order_and_partial_hash_retry(self):
        p=self.dl();q=self.csv('profit.csv',[['Číslo DL','Datum','Firma','Název','Množství','Zisk celkem'],['26SV1','2026-08-01','Alpha','X',1,200]])
        self.apply([q,p]);self.assertEqual(self.db.scalar('SELECT base_amount FROM delivery_notes'),1000)
        # A changed file with one existing and one new record stays eligible for a later full import.
        c=self.csv('partial.csv',[['Číslo','Datum','Kč základní','Firma'],['26SV1','2026-08-01',1500,'Alpha'],['26SV2','2026-08-02',500,'Beta']])
        self.assertEqual(self.apply([c])['changed'],1)
        self.assertFalse(preview_imports(self.db,[c]).sources[0].duplicate)
        self.assertEqual(self.apply([c],True)['changed'],1)
    def test_reordered_headers_xlsx_and_epoch1904(self):
        import xlsxwriter
        p=self.root/'dates.xlsx'
        wb=xlsxwriter.Workbook(p,{'date_1904':True});ws=wb.add_worksheet('Export');ws.write_row(0,0,['Firma','Kč základní','Číslo','Datum'])
        from datetime import datetime
        ws.write_row(1,0,['Alpha',42,'00001']);ws.write_datetime(1,3,datetime(2026,9,15));wb.close()
        record=parse_file(p).components[0].records['00001'];self.assertEqual(record['doc_date'],'2026-09-15')
    def test_same_document_in_batch_rejected(self):
        p=self.dl();q=self.dl('new.csv',value=200)
        with self.assertRaisesRegex(ValueError,'opakuje'):preview_imports(self.db,[p,q])
    def test_reports_missing_comparison_partial_profit_and_exports(self):
        self.apply([self.dl()]);changes=customer_changes(Analytics(self.db),2026,8)
        self.assertIsNone(changes[0]['previous_revenue']);self.assertIsNone(changes[0]['change_percent'])
        self.apply([self.dl('lastyear.csv',no='25SV1',value='500',dt='2025-08-01')])
        a=Analytics(self.db);changes=customer_changes(a,2026,8);self.assertEqual(changes[0]['change'],500)
        self.assertEqual(changes[0]['state'],'Růst')
        r=collect_management(a,2026,8);self.assertIsNone(r['projects'][0]['profit']);self.assertIsNone(r['projects'][0]['margin'])
        self.assertEqual(r['coverage'][0]['profit_documents'],0)
        from price_lists_domain.monthly_reports.exports import export_excel
        from price_lists_domain.monthly_reports.reporting import build_html
        p=export_excel(self.root/'test.xlsx',a,2026,8)
        from price_lists_domain.monthly_reports.xlsx_reader import XlsxReader
        with XlsxReader(p) as reader:self.assertIn('Kontrola dat',reader.sheet_names)
        html=build_html(a,2026,8);self.assertIn('Největší změny zákazníků',html);self.assertNotIn('Vytvořil Ing.',html)
        # No current-period data must not mark last year's customers as lost.
        empty=customer_changes(a,2027,8);self.assertIsNone(empty[0]['revenue'])
        self.assertEqual(empty[0]['state'],'Chybí srovnávací podklady')


if __name__=='__main__':unittest.main()
