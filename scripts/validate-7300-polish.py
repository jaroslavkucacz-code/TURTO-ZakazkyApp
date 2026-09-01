#!/usr/bin/env python3
"""Regression checks for TURTO CRM 7.3 preview, offers and company merge."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys
import tempfile


def main() -> None:
    source = pathlib.Path(
        sys.argv[1] if len(sys.argv) > 1 else "ZakazkyApp_base_6.1"
    ).resolve()
    repository = source.parent
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(repository))

    import fitz
    import v730_polish
    from price_lists_domain.issued_offers import font_support

    class StubApp:
        def build_companies(self):
            return None

        def refresh_companies(self):
            return None

        def build_offers(self):
            return None

        def show_help_topic(self, _key):
            return None

    class Module:
        App = StubApp

        def __init__(self, root):
            self.root = pathlib.Path(root)
            self.DB = self.root / "test.db"

        def db(self):
            con = sqlite3.connect(self.DB)
            con.row_factory = sqlite3.Row
            con.create_collation(
                "CZECH", lambda a, b: (str(a) > str(b)) - (str(a) < str(b))
            )
            con.execute("PRAGMA foreign_keys=ON")
            return con

        def ensure_schema(self):
            with self.db() as con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS companies(
                      id INTEGER PRIMARY KEY,
                      short_name TEXT NOT NULL,
                      official_name TEXT DEFAULT '',
                      ico TEXT DEFAULT '',
                      dic TEXT DEFAULT '',
                      address TEXT DEFAULT '',
                      legal_form TEXT DEFAULT '',
                      web TEXT DEFAULT '',
                      note TEXT DEFAULT '',
                      ares_checked TEXT DEFAULT '',
                      active INTEGER DEFAULT 1,
                      date_created TEXT DEFAULT '',
                      ares_last_change TEXT DEFAULT '',
                      cz_nace TEXT DEFAULT '',
                      financial_office TEXT DEFAULT '',
                      district TEXT DEFAULT '',
                      municipality TEXT DEFAULT '',
                      ares_raw_json TEXT DEFAULT ''
                    );
                    CREATE TABLE IF NOT EXISTS people(
                      id INTEGER PRIMARY KEY,
                      name TEXT NOT NULL,
                      email TEXT NOT NULL,
                      phone TEXT DEFAULT '',
                      role TEXT DEFAULT '',
                      company_id INTEGER,
                      note TEXT DEFAULT '',
                      active INTEGER DEFAULT 1,
                      FOREIGN KEY(company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS actions(
                      id INTEGER PRIMARY KEY,
                      name TEXT,
                      company_id INTEGER,
                      FOREIGN KEY(company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS requests(
                      id INTEGER PRIMARY KEY,
                      company_id INTEGER,
                      requested_for_company_id INTEGER,
                      FOREIGN KEY(company_id) REFERENCES companies(id),
                      FOREIGN KEY(requested_for_company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS supplier_offers(
                      id INTEGER PRIMARY KEY,
                      supplier_company_id INTEGER,
                      customer_company_id INTEGER,
                      FOREIGN KEY(supplier_company_id) REFERENCES companies(id),
                      FOREIGN KEY(customer_company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS price_lists(
                      id INTEGER PRIMARY KEY,
                      supplier_company_id INTEGER,
                      FOREIGN KEY(supplier_company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS catalog_product_sources(
                      id INTEGER PRIMARY KEY,
                      source_key TEXT UNIQUE,
                      supplier_company_id INTEGER,
                      note TEXT DEFAULT '',
                      FOREIGN KEY(supplier_company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS business_documents(
                      id INTEGER PRIMARY KEY,
                      company_id INTEGER,
                      customer_contact_id INTEGER,
                      customer_name_snapshot TEXT DEFAULT '',
                      FOREIGN KEY(company_id) REFERENCES companies(id),
                      FOREIGN KEY(customer_contact_id) REFERENCES people(id)
                    );
                    CREATE TABLE IF NOT EXISTS action_history(
                      id INTEGER PRIMARY KEY,
                      related_company_id INTEGER,
                      FOREIGN KEY(related_company_id) REFERENCES companies(id)
                    );
                    CREATE TABLE IF NOT EXISTS customer_product_discounts(
                      id INTEGER PRIMARY KEY,
                      product_id INTEGER,
                      company_id INTEGER,
                      action_id INTEGER,
                      discount_pct REAL,
                      note TEXT DEFAULT '',
                      active INTEGER DEFAULT 1,
                      updated_at TEXT DEFAULT '',
                      FOREIGN KEY(company_id) REFERENCES companies(id)
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_discount_company
                      ON customer_product_discounts(product_id,company_id)
                      WHERE action_id IS NULL;
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_discount_action
                      ON customer_product_discounts(product_id,company_id,action_id)
                      WHERE action_id IS NOT NULL;
                    CREATE TABLE IF NOT EXISTS guarded_refs(
                      id INTEGER PRIMARY KEY,
                      company_id INTEGER,
                      FOREIGN KEY(company_id) REFERENCES companies(id)
                    );
                    """
                )

    with tempfile.TemporaryDirectory(prefix="turto7300_") as tmp:
        module = Module(tmp)
        module.ensure_schema()
        v730_polish.apply(module)
        module.ensure_schema()

        # Repeated temporary documents must never reuse a stale font-resource
        # cache. Czech text is inserted through the same helper as issued PDFs.
        try:
            font_support._PAGE_FONTS[(123, 0)] = ("TURTORegular", "TURTOBold")
        except Exception:
            pass
        for index in range(35):
            pdf = fitz.open()
            page = pdf.new_page()
            font_support.fit_text(
                page,
                fitz.Rect(30, 30, 550, 75),
                f"Příliš žluťoučký kůň – opakování {index}",
                fontsize=11,
            )
            font_support.fit_text(
                page,
                fitz.Rect(30, 80, 550, 120),
                "Český tučný nadpis",
                fontsize=11,
                fontname="hebo",
            )
            payload = pdf.tobytes()
            pdf.close()
            assert len(payload) > 1000

        with module.db() as con:
            con.executescript(
                """
                INSERT INTO companies(
                  id,short_name,official_name,ico,dic,address,legal_form,web,note,
                  ares_checked,active,date_created,ares_last_change,cz_nace,
                  financial_office,district,municipality,ares_raw_json,
                  merged_into_company_id,merged_at,merged_by
                ) VALUES(
                  1,'ARES','ARES Firma s.r.o.','12345678','CZ12345678',
                  'Praha','s.r.o.','https://ares.example','cílová poznámka',
                  '2026-08-31',1,'2001-01-01','','62010','','Praha','Praha','{}',
                  NULL,'',''
                );
                INSERT INTO companies(
                  id,short_name,official_name,ico,dic,address,legal_form,web,note,
                  ares_checked,active,date_created,ares_last_change,cz_nace,
                  financial_office,district,municipality,ares_raw_json,
                  merged_into_company_id,merged_at,merged_by
                ) VALUES(
                  2,'MAIL','Firma','','','','','','zdrojová poznámka','',1,
                  '','','','FÚ Plzeň','','','',NULL,'',''
                );
                INSERT INTO people VALUES(
                  10,'Jan Novák','jan@example.cz','','Projektant',1,'',1
                );
                INSERT INTO people VALUES(
                  11,'Jan Novák','JAN@EXAMPLE.CZ','777111222','',2,'doplnit',1
                );
                INSERT INTO people VALUES(
                  12,'Eva Nová','eva@example.cz','777333444','Obchodník',2,'',1
                );
                INSERT INTO actions VALUES(20,'Akce',2);
                INSERT INTO requests VALUES(30,2,2);
                INSERT INTO supplier_offers VALUES(40,2,2);
                INSERT INTO price_lists VALUES(50,2);
                INSERT INTO catalog_product_sources VALUES(60,'supplier:mail',2,'');
                INSERT INTO business_documents VALUES(70,2,11,'Původní Firma');
                INSERT INTO action_history VALUES(80,2);
                INSERT INTO customer_product_discounts
                  VALUES(90,100,1,NULL,12,'cílové pravidlo',1,'');
                INSERT INTO customer_product_discounts
                  VALUES(91,100,2,NULL,18,'zdrojové pravidlo',1,'');
                INSERT INTO customer_product_discounts
                  VALUES(92,101,2,NULL,7,'přesunout',1,'');
                INSERT INTO guarded_refs VALUES(95,2);
                CREATE TRIGGER guard_company_move
                  BEFORE UPDATE OF company_id ON guarded_refs
                  WHEN NEW.company_id=1
                  BEGIN SELECT RAISE(ABORT,'test rollback'); END;
                """
            )

        stats = module.company_merge_stats(2)
        assert stats["contacts"] == 2, stats
        assert stats["requests"] == 1, stats
        assert stats["received_offers"] == 1, stats
        assert stats["issued_offers"] == 1, stats
        assert stats["discounts"] == 2, stats

        # A failure in any live reference must roll back field completion,
        # contact moves and all previously updated references.
        try:
            module.merge_company_records(2, 1, "Tester")
        except Exception as exc:
            assert "rollback" in str(exc)
        else:
            raise AssertionError("The merge guard should have aborted the transaction")
        with module.db() as con:
            assert con.execute("SELECT company_id FROM actions WHERE id=20").fetchone()[0] == 2
            assert con.execute("SELECT company_id FROM people WHERE id=11").fetchone()[0] == 2
            assert con.execute("SELECT financial_office FROM companies WHERE id=1").fetchone()[0] == ""
            con.execute("DROP TRIGGER guard_company_move")

        report = module.merge_company_records(2, 1, "Tester")
        assert report["contacts_moved"] == 2, report
        assert report["contacts_combined"] == 1, report
        assert report["discounts"] == {"moved": 1, "combined": 1}, report

        with module.db() as con:
            target = con.execute("SELECT * FROM companies WHERE id=1").fetchone()
            source_row = con.execute("SELECT * FROM companies WHERE id=2").fetchone()
            assert target["ico"] == "12345678"
            assert target["address"] == "Praha"
            assert target["financial_office"] == "FÚ Plzeň"
            assert target["web"] == "https://ares.example"
            assert "zdrojová poznámka" in target["note"]
            assert source_row["active"] == 0
            assert source_row["merged_into_company_id"] == 1
            assert source_row["merged_by"] == "Tester"

            assert con.execute("SELECT company_id FROM actions WHERE id=20").fetchone()[0] == 1
            request = con.execute(
                "SELECT company_id,requested_for_company_id FROM requests WHERE id=30"
            ).fetchone()
            assert tuple(request) == (1, 1)
            received = con.execute(
                "SELECT supplier_company_id,customer_company_id FROM supplier_offers WHERE id=40"
            ).fetchone()
            assert tuple(received) == (1, 1)
            assert con.execute("SELECT supplier_company_id FROM price_lists WHERE id=50").fetchone()[0] == 1
            assert con.execute(
                "SELECT supplier_company_id FROM catalog_product_sources WHERE id=60"
            ).fetchone()[0] == 1
            assert con.execute("SELECT related_company_id FROM action_history WHERE id=80").fetchone()[0] == 1
            assert con.execute("SELECT company_id FROM guarded_refs WHERE id=95").fetchone()[0] == 1

            document = con.execute(
                "SELECT company_id,customer_contact_id,customer_name_snapshot "
                "FROM business_documents WHERE id=70"
            ).fetchone()
            assert document["company_id"] == 1
            assert document["customer_contact_id"] == 10
            assert document["customer_name_snapshot"] == "Původní Firma"

            retained_person = con.execute("SELECT * FROM people WHERE id=10").fetchone()
            assert retained_person["phone"] == "777111222"
            assert con.execute("SELECT COUNT(*) FROM people WHERE company_id=1").fetchone()[0] == 2

            discounts = con.execute(
                "SELECT product_id,company_id,discount_pct,note "
                "FROM customer_product_discounts ORDER BY product_id"
            ).fetchall()
            assert len(discounts) == 2, discounts
            assert tuple(discounts[0]) == (100, 1, 12.0, "cílové pravidlo")
            assert tuple(discounts[1]) == (101, 1, 7.0, "přesunout")

            history = con.execute("SELECT * FROM company_merge_history").fetchone()
            assert history and history["source_company_id"] == 2
            stored_report = json.loads(history["report_json"])
            assert stored_report["contacts_combined"] == 1

        module_source = (source / "v730_polish.py").read_text(encoding="utf-8")
        assert "fontbuffer=regular_bytes" in module_source
        assert "Poslední platný náhled zůstal zobrazen" in module_source
        assert "Do not remove the last valid preview" in module_source
        assert "Sloupce…" in module_source
        assert "Barvy jsou upozornění" in module_source
        assert "company_merge_history" in module_source
        assert "⇄ Sloučit společnosti…" in module_source

        launcher = (source / "ZakazkyCRM.pyw").read_text(encoding="utf-8")
        assert "import app" in launcher and "v730_polish" in launcher
        assert launcher.index("v720_visual_offer.apply(app)") < launcher.index(
            "v730_polish.apply(app)"
        )
        version = (repository / "release_version.txt").read_text(encoding="utf-8").strip()
        try:
            version_tuple = tuple(int(part) for part in version.split("."))
        except ValueError as exc:
            raise AssertionError(version) from exc
        assert version_tuple >= (7, 3, 0), version
        print(f"TURTO CRM {version} preview, offers and company-merge checks passed")


if __name__ == "__main__":
    main()
