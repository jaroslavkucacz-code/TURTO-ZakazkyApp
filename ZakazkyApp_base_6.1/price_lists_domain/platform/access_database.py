"""Enforce tab write access at the CRM connection boundary, including inline SQL."""
import sqlite3

from .user_access import EDIT, TITLES

TABLE_PAGES = {
    'company_salespeople': 'portfolio',
    'actions': 'actions', 'companies': 'companies', 'people': 'people',
    'projects': 'projects', 'tasks': 'tasks', 'company_merge_history': 'companies',
    'customer_product_discounts': 'companies',
    'supplier_offers': 'offers', 'supplier_offer_items': 'offers',
    'offer_item_aliases': 'offers', 'offer_product_aliases': 'offers',
    'offer_product_images': 'offers', 'offer_image_assets': 'offers',
    'offer_source_messages': 'offers', 'offer_source_attachments': 'offers',
    'offer_supplier_parsers': 'offers',
    'price_lists': 'pricelists', 'price_list_files': 'pricelists',
    'price_list_items': 'pricelists', 'price_list_item_attributes': 'pricelists',
    'price_list_rules': 'pricelists', 'price_list_ocr_cache': 'pricelists',
    'materials': 'settings', 'salespeople': 'settings', 'work_topics': 'settings',
    'person_roles': 'settings', 'product_categories': 'settings', 'product_subgroups': 'settings',
    'catalog_products': 'settings', 'catalog_product_sources': 'settings',
    'business_document_templates': 'issued_offers', 'report_company_links': 'reports_customers',
}


def _triggers(con, table, expression):
    """TEMP triggers belong to this connection; they never alter the user's DB."""
    for action, rows in (('INSERT', ('NEW',)), ('UPDATE', ('OLD', 'NEW')), ('DELETE', ('OLD',))):
        condition = ' OR '.join(f'NOT ({expression(row)})' for row in rows)
        con.execute(f'''CREATE TEMP TRIGGER access_{table}_{action} BEFORE {action} ON main.{table}
            WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Oprávnění: změna dat v této záložce není povolena.'); END''')


def protect_connection(con, session):
    """Guard fresh connections with a stable session snapshot for the transaction.

    Shared request/document tables are checked per row, including both sides of
    a reassignment. Foreign-key cascades cannot bypass the parent-row guard.
    """
    admin = session.active and session.name.strip().casefold() == 'admin'
    if admin:
        return
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.create_function('turto_edit', 1, lambda page: int(page is None or session.level(page) >= EDIT))
    if 'request_mail_attempts' in tables:
        # Tracking is request metadata; it obeys the same MIVO/regular permission.
        def mail_page(row):
            return f"""turto_edit((SELECT CASE WHEN
                lower(trim(coalesce(c.short_name,'')))='mivo' OR lower(trim(coalesce(c.official_name,'')))='mivo'
                OR lower(trim(c.official_name)) LIKE 'mivo %' OR lower(trim(c.official_name)) LIKE 'mivo,%'
                OR lower(trim(c.official_name)) LIKE 'mivo.%' THEN 'mivo' ELSE 'requests' END
                FROM requests r LEFT JOIN companies c ON c.id=r.company_id WHERE r.id={row}.request_id))"""
        _triggers(con, 'request_mail_attempts', mail_page)
    # An ordinary user can never give themselves a role or edit permission JSON.
    if 'users' in tables:
        con.execute('''CREATE TEMP TRIGGER access_user_profile BEFORE UPDATE ON main.users
            WHEN NEW.job_title IS NOT OLD.job_title OR NEW.tab_permissions IS NOT OLD.tab_permissions
                 OR NEW.salesperson_id IS NOT OLD.salesperson_id OR NEW.person_id IS NOT OLD.person_id
                 OR NEW.name IS NOT OLD.name OR NEW.active IS NOT OLD.active OR NEW.id IS NOT OLD.id
            BEGIN SELECT RAISE(ABORT, 'Oprávnění uživatelů může měnit pouze ADMIN.'); END''')
        for operation in ('INSERT', 'DELETE'):
            con.execute(f'''CREATE TEMP TRIGGER access_user_{operation} BEFORE {operation} ON main.users
                BEGIN SELECT RAISE(ABORT, 'Uživatele může měnit pouze ADMIN.'); END''')
    denied = {page for page in TITLES if session.level(page) < EDIT}
    if not denied:
        return
    if 'settings' in tables and denied.intersection({'settings', 'issued_offers'}):
        def setting_page(key):
            key = str(key or '')
            if key in {'active_user', 'pending_update', 'update_source', 'theme'} or key.startswith(('last_', 'runtime_', 'ui_', 'table_', 'migration_')):
                return None  # Session/display state and updater bookkeeping.
            return 'issued_offers' if key.startswith('issued_offer_') else 'settings'
        con.create_function('turto_setting_page', 1, setting_page)
        _triggers(con, 'settings', lambda row: f'turto_edit(turto_setting_page({row}.key))')
    for table, page in TABLE_PAGES.items():
        if table in tables and page in denied:
            _triggers(con, table, lambda row: '0')

    if 'requests' in tables and denied.intersection({'requests', 'mivo'}):
        # Match the existing MIVO view's supplier-name rule.
        mivo = "(lower(trim(coalesce(c.short_name,'')))='mivo' OR lower(trim(coalesce(c.official_name,'')))='mivo' OR lower(trim(c.official_name)) LIKE 'mivo %' OR lower(trim(c.official_name)) LIKE 'mivo,%' OR lower(trim(c.official_name)) LIKE 'mivo.%')"
        def request_access(row):
            return f"turto_edit(CASE WHEN EXISTS(SELECT 1 FROM companies c WHERE c.id={row}.company_id AND {mivo}) THEN 'mivo' ELSE 'requests' END)"
        _triggers(con, 'requests', request_access)

    if 'business_documents' in tables and denied.intersection({'issued_offers', 'received_orders'}):
        def page(row):
            return f"CASE WHEN {row}.document_type='received_order' AND {row}.direction='received' THEN 'received_orders' ELSE 'issued_offers' END"
        _triggers(con, 'business_documents', lambda row: f'turto_edit({page(row)})')
        for table in ('business_document_items', 'business_document_revisions', 'business_document_history'):
            if table in tables:
                _triggers(con, table, lambda row: f"turto_edit((SELECT {page('d')} FROM business_documents d WHERE d.id={row}.document_id))")

    # Schema changes are maintenance operations, never an interactive workaround.
    ddl = {sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_DROP_TRIGGER}
    con.set_authorizer(lambda op, a, b, database, trigger:
                       sqlite3.SQLITE_DENY if op in ddl and database == 'main' else sqlite3.SQLITE_OK)
