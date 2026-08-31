"""Additive schema for issued offers and their immutable PDF revisions."""
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
    """Create only new tables and columns; never rewrite an existing document."""
    with M.db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS document_sequences(
              document_type TEXT NOT NULL,
              calendar_year INTEGER NOT NULL,
              last_number INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(document_type,calendar_year)
            );

            CREATE TABLE IF NOT EXISTS business_document_templates(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_type TEXT NOT NULL DEFAULT 'issued_offer',
              name TEXT NOT NULL COLLATE CZECH,
              active INTEGER NOT NULL DEFAULT 1,
              is_default INTEGER NOT NULL DEFAULT 0,
              header_path TEXT DEFAULT '',
              footer_path TEXT DEFAULT '',
              header_height_mm REAL NOT NULL DEFAULT 25,
              footer_height_mm REAL NOT NULL DEFAULT 14,
              margin_left_mm REAL NOT NULL DEFAULT 14,
              margin_right_mm REAL NOT NULL DEFAULT 14,
              body_top_gap_mm REAL NOT NULL DEFAULT 5,
              body_bottom_gap_mm REAL NOT NULL DEFAULT 5,
              header_every_page INTEGER NOT NULL DEFAULT 1,
              footer_every_page INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(document_type,name)
            );

            CREATE TABLE IF NOT EXISTS business_document_revisions(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              document_id INTEGER NOT NULL,
              revision_no INTEGER NOT NULL,
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
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              user_name TEXT DEFAULT '',
              FOREIGN KEY(document_id) REFERENCES business_documents(id) ON DELETE CASCADE
            );
            """
        )

        # Extend the foundation created by the Ceníky platform. All fields have
        # safe defaults so existing future-facing rows remain readable.
        for declaration in (
            "offer_subject TEXT DEFAULT ''",
            "customer_contact_id INTEGER REFERENCES people(id)",
            "action_id INTEGER REFERENCES actions(id)",
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
            "items_subtotal REAL NOT NULL DEFAULT 0",
            "subtotal_net REAL NOT NULL DEFAULT 0",
            "vat_total REAL NOT NULL DEFAULT 0",
            "total_gross REAL NOT NULL DEFAULT 0",
            "template_id INTEGER REFERENCES business_document_templates(id)",
            "revision_no INTEGER NOT NULL DEFAULT 0",
            "last_pdf_path TEXT DEFAULT ''",
            "last_pdf_sha256 TEXT DEFAULT ''",
            "locked INTEGER NOT NULL DEFAULT 0",
            "sent_at TEXT DEFAULT ''",
            "accepted_at TEXT DEFAULT ''",
            "rejected_at TEXT DEFAULT ''",
            "created_by TEXT DEFAULT ''",
            "updated_by TEXT DEFAULT ''",
        ):
            _add_column(con, "business_documents", declaration)

        for declaration in (
            "row_type TEXT NOT NULL DEFAULT 'product'",
            "purchase_currency TEXT DEFAULT 'CZK'",
            "vat_rate REAL NOT NULL DEFAULT 21",
            "internal_name_snapshot TEXT DEFAULT ''",
            "price_source_label TEXT DEFAULT ''",
            "source_price_list_item_id INTEGER REFERENCES price_list_items(id)",
            "source_supplier_offer_item_id INTEGER REFERENCES supplier_offer_items(id)",
            "line_note TEXT DEFAULT ''",
            "standard_discount_pct REAL DEFAULT 0",
            "discount_source_snapshot TEXT DEFAULT ''",
            "discount_rule_id INTEGER",
            "discount_manual_override INTEGER NOT NULL DEFAULT 0",
            "pricing_company_id_snapshot INTEGER",
            "pricing_action_id_snapshot INTEGER",
            "pricing_project_id_snapshot INTEGER",
        ):
            _add_column(con, "business_document_items", declaration)

        # The Ceníky foundation already provides these in current databases, but
        # installations upgraded from an earlier path receive them here too.
        for declaration in (
            "catalog_product_id INTEGER REFERENCES catalog_products(id)",
            "subgroup_id INTEGER REFERENCES product_subgroups(id)",
            "internal_code_snapshot TEXT DEFAULT ''",
            "purchase_unit_price REAL DEFAULT 0",
            "margin_pct REAL DEFAULT 0",
            "recommended_unit_price REAL DEFAULT 0",
            "show_recommended_price INTEGER DEFAULT 1",
        ):
            _add_column(con, "business_document_items", declaration)

        con.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_business_documents_issued_offer
              ON business_documents(document_type,direction,archived,status,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_documents_customer
              ON business_documents(company_id,document_type,archived,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_documents_project
              ON business_documents(project_id,document_type,archived,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_documents_action
              ON business_documents(action_id,document_type,archived,issue_date DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_document_revisions_document
              ON business_document_revisions(document_id,revision_no DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_document_history_document
              ON business_document_history(document_id,created_at DESC,id DESC);
            CREATE INDEX IF NOT EXISTS idx_business_document_items_catalog
              ON business_document_items(catalog_product_id,document_id,position,id);
            """
        )

        con.execute(
            """INSERT INTO business_document_templates(
                   document_type,name,active,is_default,header_height_mm,footer_height_mm,
                   margin_left_mm,margin_right_mm,body_top_gap_mm,body_bottom_gap_mm,
                   header_every_page,footer_every_page
               )
               SELECT 'issued_offer','Standardní nabídka TURTO',1,1,25,14,14,14,5,5,1,1
               WHERE NOT EXISTS(
                   SELECT 1 FROM business_document_templates WHERE document_type='issued_offer'
               )"""
        )


__all__ = ["ensure_business_documents_schema"]
