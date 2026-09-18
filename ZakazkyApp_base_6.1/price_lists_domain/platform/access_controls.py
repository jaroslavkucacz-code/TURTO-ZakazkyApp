"""Navigation, form and command access checks over the composed desktop UI."""
from functools import wraps
import sqlite3
import tkinter as tk

from . import user_access as access
from .form_behavior_817 import children, mark_saved

# Read-only pages retain searching, sorting, opening details and existing files.
# Unknown action buttons are disabled until explicitly classified as read-only.
READ_BUTTONS = ('zavřít', 'zrušit', 'otevřít', 'upravit / otevřít', 'editovat', 'upravit',
                'historie', 'zobrazit', 'sloupce', 'export', 'extrakce', 'předchozí', 'další',
                'obnovit přehled', 'obnovit zobrazení', 'hledat', 'vyhledat', 'přejít',
                'načíst fotograf', 'reset filtr', 'vyčistit filtr', 'filtr', 'zrušit filtr')
INPUTS = {'Entry', 'TEntry', 'TCombobox', 'Text', 'Spinbox', 'TSpinbox',
          'Checkbutton', 'TCheckbutton', 'Radiobutton', 'TRadiobutton'}


def _text(widget):
    text = str(widget.cget('text')).strip().casefold()
    return text.lstrip('⌂▣▤✎🗑📦↩⚙📂📁🔎🔍←→?📝 ').strip()


def _read_button(widget, form):
    text = _text(widget)
    if form:
        return text.startswith(('zavřít', 'zrušit', 'historie', 'zobrazit', 'otevřít poslední pdf',
                                'otevřít výchozí nabídku', 'extrakce', 'sloupce'))
    return text.startswith(READ_BUTTONS) and not text.startswith(('upravit polož', 'upravit text', 'upravit šablon'))


def restrict_widgets(M, parent, page, form=False):
    if page == 'help':
        return
    readonly = access.level(M, page) < access.EDIT
    for widget in children(parent):
        cls = widget.winfo_class()
        should_disable = (cls in {'Button', 'TButton', 'Menubutton', 'TMenubutton'} and not _read_button(widget, form))
        should_disable |= (form or page == 'settings') and cls in INPUTS and not getattr(widget, '_turto_search_input', False)
        if not should_disable:
            continue
        if readonly:
            if not hasattr(widget, '_access_previous_state'):
                try:
                    widget._access_previous_state = str(widget.cget('state'))
                except tk.TclError:
                    continue
            widget.configure(state='disabled')
        elif hasattr(widget, '_access_previous_state'):
            widget.configure(state=widget._access_previous_state)
            del widget._access_previous_state
    if form:
        parent._access_page = page
        if readonly and not getattr(parent, '_access_readonly_title', False):
            parent.title(parent.title() + ' — jen pro čtení')
            parent._access_readonly_title = True
        mark_saved(parent)


def refresh_controls(M, app):
    previous = getattr(app, '_access_restricted_pages', set())
    restricted = {key for key in getattr(app, 'tabs', {}) if access.level(M, key) < access.EDIT}
    app._access_restricted_pages = restricted
    for key, page in getattr(app, 'tabs', {}).items():
        if key.startswith('reports_') or key not in restricted | previous:
            continue  # All report routes share one workspace with its own controls.
        restrict_widgets(M, page, key)
    for key, attribute in (('settings', 'settings_button'), ('help', 'help_button')):
        button = getattr(app, attribute, None)
        if button is not None and button.winfo_exists():
            if access.level(M, key) == access.HIDDEN:
                button.grid_remove()
                button._access_hidden = True
            elif getattr(button, '_access_hidden', False):
                button.grid()
                button._access_hidden = False


def guarded(M, function, page, write=True):
    @wraps(function)
    def call(self, *args, **kwargs):
        target = page(self, *args, **kwargs) if callable(page) else page
        parent = getattr(self, 'win', self)
        if not access.allowed(M, parent, target, write):
            return None
        return function(self, *args, **kwargs)
    return call


def wrap_methods(M, cls, names, page, write=True):
    for name in names:
        original = getattr(cls, name, None)
        if callable(original):
            setattr(cls, name, guarded(M, original, page, write))


def _request_page(M, dialog=None, rid=None, company=None):
    if dialog is not None:
        return getattr(dialog, '_access_page', 'requests')
    with M.db() as con:
        if rid:
            row = con.execute('SELECT company_id FROM requests WHERE id=?', (rid,)).fetchone()
            if row and row[0] in M.mivo_company_ids(con):
                return 'mivo'
        elif company:
            name = str(company).strip().casefold()
            mids = set(M.mivo_company_ids(con))
            for row in con.execute('SELECT id,official_name,short_name FROM companies'):
                if row['id'] in mids and name in {str(row['official_name'] or '').strip().casefold(), str(row['short_name'] or '').strip().casefold()}:
                    return 'mivo'
            if name == 'mivo' or name.startswith(('mivo ', 'mivo,', 'mivo.')):
                return 'mivo'
    return 'requests'


def _form(M, cls, page, module_arg=False):
    original = cls.__init__
    @wraps(original)
    def init(self, *args, **kwargs):
        target = page
        if page == 'requests':
            target = _request_page(M, rid=kwargs.get('rid', args[1] if len(args) > 1 else None),
                                   company=kwargs.get('pre_company'))
        access.require(M, target, write=False)
        original(self, *args, **kwargs)
        win = getattr(self, 'win', self)
        self._access_page = target
        if isinstance(win, tk.Misc):
            restrict_widgets(M, win, target, form=True)
    cls.__init__ = init
    resolver = lambda self, *args, **kwargs: getattr(self, '_access_page', page)
    wrap_methods(M, cls, ('ok', 'save', 'generate_pdf', 'outlook_draft', 'edit_pdf_template',
                         'add_from_catalog', 'add_manual', 'add_special', 'edit_item', 'remove_items',
                         'remove_item', 'add_item', 'move_item', 'ensure_company_saved', 'detach_person'), resolver)


def _service(module, names, page):
    for name in names:
        original = getattr(module, name, None)
        if not callable(original):
            continue
        def wrap(fn):
            @wraps(fn)
            def call(M, *args, **kwargs):
                access.require(M, page)
                return fn(M, *args, **kwargs)
            return call
        setattr(module, name, wrap(original))


def install_controls(M):
    app_operations = {
        'actions': ('new_action', 'delete_action', '_set_action_status', 'set_action_status', 'change_action_status', 'archive_action', 'restore_action'),
        'requests': ('new_request', 'save_request', 'hard_delete_request', 'delete_request', 'archive_request',
                     'restore_request', 'mark_received', 'mark_no_response'),
        'mivo': ('new_mivo_request',),
        'projects': ('new_project', 'delete_project', 'merge_project', 'archive_project', 'restore_project'),
        'tasks': ('new_task', 'delete_task', 'complete_task', 'complete_task_by_id'),
        'companies': ('new_company', 'archive_company', 'delete_company', 'merge_companies', 'restore_company'),
        'people': ('new_person', 'delete_person', 'import_people', 'import_people_csv', 'archive_person', 'restore_person'),
        'offers': ('import_offer_pdf', 'delete_offer', 'import_offers', 'import_offer_sources', 'import_selected_outlook_offer',
                   '_start_offer_batch', 'reprocess_offer', 'reprocess_selected_offers'),
        'pricelists': ('import_price_list', 'delete_price_list', 'archive_price_list', 'restore_price_list'),
        'issued_offers': ('new_issued_offer', 'create_issued_offer_from_supplier_offer', 'manage_issued_offer_templates',
                          'open_issued_offer_settings', 'render_issued_offer_pdf', 'draft_issued_offer_outlook'),
        'received_orders': ('create_received_order_from_offer',),
        'settings': ('manage_code_lists', 'manage_product_categories', 'manage_catalog_products', 'import_complete_data',
                     'restore_backup', 'open_storage_maintenance', 'choose_update_source'),
    }
    def request_command(app, *args, **kwargs):
        if getattr(app, 'request_tree', None) is getattr(app, 'mivo_tree', object()):
            return 'mivo'
        if args and hasattr(args[0], '_access_page'):
            return args[0]._access_page
        return 'requests'
    for page, names in app_operations.items():
        wrap_methods(M, M.App, names, request_command if page == 'requests' else page)
    for cls, page in (('CompanyDialog', 'companies'), ('PersonDialog', 'people'), ('ActionDialog', 'actions'),
                      ('ProjectDialog', 'projects'), ('TaskDialog', 'tasks'), ('RequestDialog', 'requests')):
        _form(M, getattr(M, cls), page)
    _form(M, M.OfferDetailDialog, 'offers')
    wrap_methods(M, M.OfferDetailDialog, ('link_action',), 'offers')
    from .price_dialogs import PriceListDetailDialog
    _form(M, PriceListDetailDialog, 'pricelists', True)
    wrap_methods(M, PriceListDetailDialog, ('assign_category', 'auto_categories'), 'pricelists')

    for name in ('import_complete_data', 'restore_backup'):
        original = getattr(M.App, name, None)
        if callable(original):
            def admin_only(fn):
                @wraps(fn)
                def call(app, *args, **kwargs):
                    access.require_admin(M)
                    return fn(app, *args, **kwargs)
                return call
            setattr(M.App, name, admin_only(original))

    from ..issued_offers import editor, service
    from ..received_orders import editor as orders_editor, service as orders_service
    _form(M, editor.IssuedOfferEditor, 'issued_offers', True)
    _form(M, orders_editor.ReceivedOrderEditor, 'received_orders', True)
    _service(service, ('save_document', 'duplicate_document', 'delete_document', 'delete_draft', 'set_status',
                       'set_archived', 'record_revision', 'save_template', 'set_default_template', 'deactivate_template',
                       'copy_template_asset'), 'issued_offers')
    _service(orders_service, ('save_document',), 'received_orders')
    from ..issued_offers import pdf_renderer
    _service(pdf_renderer, ('render_offer_pdf',), 'issued_offers')
    from . import action_assignees, received_item_labels
    _service(action_assignees, ('save',), 'actions')
    _service(received_item_labels, ('save_items', 'copy_from_manufacturer'), 'offers')
    previous_picker = action_assignees.open_picker
    def picker(module, app):
        if access.allowed(M, app, 'actions', write=False):
            win = previous_picker(module, app)
            if win is not None:
                restrict_widgets(M, win, 'actions', form=True)
            return win
    action_assignees.open_picker = picker

    from ..monthly_reports.company_ui import CompanyLinkDialog
    _form(M, CompanyLinkDialog, 'reports_customers')

    previous_error = M.App.report_callback_exception
    def callback_error(app, exception, value, traceback):
        if isinstance(value, access.AccessDenied) or (isinstance(value, sqlite3.Error) and 'Oprávnění' in str(value)):
            M.messagebox.showwarning('Oprávnění', str(value), parent=app)
        else:
            previous_error(app, exception, value, traceback)
    M.App.report_callback_exception = callback_error

    # Refreshes can change toolbar states after lazy navigation has completed.
    def wrap_refresh(fn):
        @wraps(fn)
        def refreshed(app, *args, **kwargs):
            result = fn(app, *args, **kwargs)
            key = getattr(app, '_current_page', None)
            if key in getattr(app, 'tabs', {}) and not key.startswith('reports_') and access.level(M, key) < access.EDIT:
                restrict_widgets(M, app.tabs[key], key)
            return result
        return refreshed
    for name in tuple(dir(M.App)):
        if name.startswith('refresh_') and name != 'refresh_user_access':
            fn = getattr(M.App, name)
            if callable(fn):
                setattr(M.App, name, wrap_refresh(fn))

    # Lazy report pages are rebuilt on each visit, and own a second database.
    from ..monthly_reports.ui import ReportWorkspace
    wrap_methods(M, ReportWorkspace, ('do_import', 'start_import', 'take_over_data'), 'reports_imports')
    wrap_methods(M, ReportWorkspace, ('open_company_links',), 'reports_customers', write=False)
    original_report_show = ReportWorkspace.show_page
    def report_show(workspace, name):
        from ..monthly_reports import PAGES
        page = next(key for key, label in PAGES.items() if label == name)
        access.require(M, page, write=False)
        result = original_report_show(workspace, name)
        restrict_widgets(M, workspace, page)
        # The import button is shared by all reports, but belongs to Importy.
        for widget in children(workspace):
            if widget.winfo_class() in {'Button', 'TButton'} and _text(widget).startswith(('importovat', 'převzít data')):
                widget.configure(state='normal' if access.level(M, 'reports_imports') == access.EDIT else 'disabled')
        return result
    ReportWorkspace.show_page = report_show
