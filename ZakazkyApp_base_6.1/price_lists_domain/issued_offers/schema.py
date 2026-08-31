"""Additive schema for TURTO CRM issued business documents."""
from __future__ import annotations


def _columns(con, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _add_column(con, table: str, declaration: str) -> None:
    name = declaration.split()[0]
    if name not in _columns(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {declaration}")


def ensure_business_documents_schema(M) -> None:
    """Create/extend issued-document tables without rewriting historic rows."""
    with M.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS business_documents(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_type TEXT NOT NULL,
              direction TEXT NOT NULL DEFAULT 'issued',
              document_number TEXT DEFAULT '',
              issue_date TEXT DEFAULT '',
              due_date TEXT DEFAULT '',
              valid_to TEXT DEFAULT '',
              company_id INTEGER,
              project_id INTEGER,
              status TEXT DEFAULT 'Rozpracováno',
              currency TEXT DEFAULT 'CZK',
              total_value REAL DEFAULT 0,
              note TEXT DEFAULT '',
              source_path TEXT DEFAULT '',
              archived INTEGER NOT NULL DEFAULT 0,
              archived_at TEXT DEFAULT '',
              archived_by TEXT DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(company_id) REFERENCES companies(id),
              FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            CREATE TABLE IF NOT EXISTS business_document_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_id INTEGER NOT NULL,
              position INTEGER DEFAULT 0,
              product_code TEXT DEFAULT '',
              item_key TEXT DEFAULT '',
              name TEXT DEFAULT '',
              description TEXT DEFAULT '',
              quantity REAL DEFAULT 0,
              unit TEXT DEFAULT '',
              unit_price REAL DEFAULT 0,
              discount_pct REAL DEFAULT 0,
              total_price REAL DEFAULT 0,
              category_id INTEGER,
              FOREIGN KEY(document_id) REFERENCES business_documents(id) ON DELETE CASCADE,
              FOREIGN KEY(category_id) REFERENCES product_categories(id)
            );
            CREATE TABLE IF NOT EXISTS business_document_templates(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL COLLATE CZECH,
              document_type TEXT NOT NULL DEFAULT 'issued_offer',
              active INTEGER NOT NULL DEFAULT 1,
              is_default INTEGER NOT NULL DEFAULT 0,
              header_path TEXT DEFAULT '',
              footer_path TEXT DEFAULT '',
              header_height_mm REAL NOT NULL DEFAULT 28,
              footer_height_mm REAL NOT NULL DEFAULT 15,
              margin_left_mm REAL NOT NULL DEFAULT 14,
              margin_right_mm REAL NOT NULL DEFAULT 14,
              body_top_gap_mm REAL NOT NULL DEFAULT 5,
              body_bottom_gap_mm REAL NOT NULL DEFAULT 5,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS business_document_revisions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_id INTEGER NOT NULL,
              revision_no INTEGER NOT NULL DEFAULT 0,
              pdf_path TEXT NOT NULL DEFAULT '',
              pdf_sha256 TEXT NOT NULL DEFAULT '',
              file_size INTEGER NOT NULL DEFAULT 0,
              status_snapshot TEXT DEFAULT '',
              data_json TEXT DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_by TEXT DEFAULT '',
              UNIQUE(document_id,revision_no),
              FOREIGN KEY(document_id) REFERENCES business_documents(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS business_document_history(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_id INTEGER NOT NULL,
              event_type TEXT NOT NULL DEFAULT '',
              old_status TEXT DEFAULT '',
              new_status TEXT DEFAULT '',
              note TEXT DEFAULT '',
              user_name TEXT DEFAULT '',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(document_id) REFERENCES business_documents(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS document_sequences(
              document_type TEXT NOT NULL,
              calendar_year INTEGER NOT NULL,
              last_number INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(document_type,calendar_year)
            );
            """
        )

        document_columns = (
            "offer_subject TEXT DEFAULT ''",
            "customer_contact_id INTEGER",
            "customer_name_snapshot TEXT DEFAULT ''",
            "customer_address_snapshot TEXT DEFAULT ''",
            "customer_ico_snapshot TEXT DEFAULT ''",
            "customer_dic_snapshot TEXT DEFAULT ''",
            "customer_contact_snapshot TEXT DEFAULT ''",
            "customer_email_snapshot TEXT DEFAULT ''",
            "customer_phone_snapshot TEXT DEFAULT ''",
            "issuer_name_snapshot TEXT DEFAULT ''",
            "issuer_address_snapshot TEXT DEFAULT ''",
            "issuer_ico_snapshot TEXT DEFAULT ''",
            "issuer_dic_snapshot TEXT DEFAULT ''",
            "issuer_contact_snapshot TEXT DEFAULT ''",
            "issuer_email_snapshot TEXT DEFAULT ''",
            "issuer_phone_snapshot TEXT DEFAULT ''",
            "issuer_bank_snapshot TEXT DEFAULT ''",
            "salesperson_snapshot TEXT DEFAULT ''",
            "customer_reference TEXT DEFAULT ''",
            "delivery_address TEXT DEFAULT ''",
            "payment_terms TEXT DEFAULT ''",
            "delivery_terms TEXT DEFAULT ''",
            "delivery_time TEXT DEFAULT ''",
            "customer_note TEXT DEFAULT ''",
            "internal_note TEXT DEFAULT ''",
            "vat_mode TEXT NOT NULL DEFAULT 'without'",
            "global_discount_pct REAL NOT NULL DEFAULT 0",
            "subtotal_net REAL NOT NULL DEFAULT 0",
            "vat_total REAL NOT NULL DEFAULT 0",
            "total_gross REAL NOT NULL DEFAULT 0",
            "template_id INTEGER",
            "revision_no INTEGER NOT NULL DEFAULT -1",
            "locked INTEGER NOT NULL DEFAULT 0",
            "sent_at TEXT DEFAULT ''",
            "accepted_at TEXT DEFAULT ''",
            "rejected_at TEXT DEFAULT ''",
            "last_pdf_path TEXT DEFAULT ''",
            "last_pdf_sha256 TEXT DEFAULT ''",
            "created_by TEXT DEFAULT ''",
            "updated_by TEXT DEFAULT ''",
        )
        for declaration in document_columns:
            _add_column(con, "business_documents", declaration)

        item_columns = (
            "row_type TEXT NOT NULL DEFAULT 'product'",
            "subgroup_id INTEGER REFERENCES product_subgroups(id)",
            "catalog_product_id INTEGER REFERENCES catalog_products(id)",
            "internal_code_snapshot TEXT DEFAULT ''",
            "internal_name_snapshot TEXT DEFAULT ''",
            "purchase_unit_price REAL DEFAULT 0",
            "purchase_currency TEXT DEFAULT 'CZK'",
            "margin_pct REAL DEFAULT 0",
            "recommended_unit_price REAL DEFAULT 0",
            "show_recommended_price INTEGER DEFAULT 1",
            "vat_rate REAL NOT NULL DEFAULT 21",
            "price_source_label TEXT DEFAULT ''",
            "source_price_list_item_id INTEGER",
            "source_supplier_offer_item_id INTEGER",
            "line_note TEXT DEFAULT ''",
        )
        for declaration in item_columns:
            _add_column(con, "business_document_items", declaration)

        con.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_business_documents_offer_workset
              ON business_documents(document_type,direction,archived,status,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_documents_offer_customer
              ON business_documents(document_type,company_id,archived,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_documents_offer_project
              ON business_documents(document_type,project_id,archived,issue_date DESC,id DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_business_document_number
              ON business_documents(document_type,document_number)
              WHERE trim(coalesce(document_number,''))<>'';
            CREATE INDEX IF NOT EXISTS idx_business_document_items_product
              ON business_document_items(catalog_product_id,document_id,position,id);
            CREATE INDEX IF NOT EXISTS idx_business_document_revisions_doc
              ON business_document_revisions(document_id,revision_no DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_document_history_doc
              ON business_document_history(document_id,created_at DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_templates_default
              ON business_document_templates(document_type,active,is_default,id);
            """
        )
        con.execute(
            """INSERT INTO business_document_templates(
                   name,document_type,active,is_default,header_height_mm,footer_height_mm,
                   margin_left_mm,margin_right_mm,body_top_gap_mm,body_bottom_gap_mm
               )
               SELECT 'Standardní nabídka TURTO','issued_offer',1,1,28,15,14,14,5,5
               WHERE NOT EXISTS(
                 SELECT 1 FROM business_document_templates WHERE document_type='issued_offer'
               )"""
        )
        default_row = con.execute(
            """SELECT id FROM business_document_templates
               WHERE document_type='issued_offer' AND active=1
               ORDER BY is_default DESC,id LIMIT 1"""
        ).fetchone()
        if default_row:
            con.execute(
                "UPDATE business_document_templates SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END WHERE document_type='issued_offer'",
                (default_row["id"],),
            )


__all__ = ["ensure_business_documents_schema"]
