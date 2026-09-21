"""Background Outlook checks and request/MIVO status controls."""
from concurrent.futures import ThreadPoolExecutor
from . import mail_tracking as tracking, user_access as access


def apply(M):
    def prepare_page(app, key, tree_name):
        tree = getattr(app, tree_name, None)
        if tree is None:return
        columns = list(map(str, tree.cget('columns')))
        if 'E-mail' not in columns:
            headings = {name: dict(tree.heading(name)) for name in columns}
            sizes = {name: dict(tree.column(name)) for name in columns}
            tree.configure(columns=(*columns, 'E-mail'))
            for name in columns:
                sizes[name].pop('id', None)
                tree.column(name, **sizes[name])
                tree.heading(name, **headings[name])
            tree.heading('E-mail', text='E-mail')
            tree.column('E-mail', width=245, minwidth=150, stretch=True, anchor='w')
        if getattr(tree, '_mail_tracking_controls', False):return
        display = list(map(str, tree.cget('displaycolumns')))
        if not display or '#all' in display:display = list(map(str,tree.cget('columns')))
        display = [name for name in display if name != 'E-mail']
        tree.configure(displaycolumns=(display[0], 'E-mail', *display[1:]))
        tree.configure(selectmode='extended')
        tree._mail_tracking_controls = True
    for method, key, tree in (('build_requests','requests','request_tree'),('build_mivo','mivo','mivo_tree')):
        previous = getattr(M.App, method)
        def wrap_build(fn, page, tree_name):
            def build_page(app, *args, **kwargs):
                result = fn(app, *args, **kwargs)
                prepare_page(app, page, tree_name)
                return result
            return build_page
        setattr(M.App, method, wrap_build(previous, key, tree))
    previous_build = M.App.build
    def build(app, *args, **kwargs):
        result = previous_build(app, *args, **kwargs)
        app._mail_checks = None
        app._mail_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='turto-mail-check')
        for key, tree_name in (('requests', 'request_tree'), ('mivo', 'mivo_tree')):
            prepare_page(app, key, tree_name)
        app._mail_timer = app.after(6000, lambda: tick(app))
        return result
    M.App.build = build

    def paint(app):
        status = tracking.status_rows(M)
        for key, tree_name in (('requests','request_tree'),('mivo','mivo_tree')):
            tree = getattr(app, tree_name, None)
            if tree is None:continue
            prepare_page(app, key, tree_name)
            for iid in tree.get_children():
                if iid.startswith('r'):
                    # Numeric data-column IDs avoid Tk 9's cached name/index
                    # representation crossing the two different request schemas.
                    column = list(map(str,tree.cget('columns'))).index('E-mail')
                    tree.set(iid, str(column), tracking.label(status.get(int(iid[1:]))))
    for name in ('refresh_requests', 'refresh_mivo_requests'):
        previous = getattr(M.App, name, None)
        if previous is None:continue
        def wrap(fn):
            def refresh(app, *args, **kwargs):
                result = fn(app, *args, **kwargs)
                paint(app)
                return result
            return refresh
        setattr(M.App, name, wrap(previous))
    M.App.refresh_mail_status = paint

    def editable_attempts(attempts):
        from .access_controls import _request_page
        return [r for r in attempts if access.level(M, _request_page(M, rid=r['request_id'])) >= access.EDIT]

    def submit_check(app, attempts, uid, db, manual):
        # Small batches keep the Windows environment payload bounded and let
        # the UI stop between batches after closing, changing login or database.
        batch, remaining = attempts[:25], attempts[25:]
        app._mail_checks = (app._mail_executor.submit(tracking.check_outlook, batch), batch, uid, db, manual, remaining)
        app.after(150, lambda: finish_check(app))

    def start_check(app, manual=False, request_ids=None):
        if app._mail_checks is not None:
            if manual:M.messagebox.showinfo('E-mail', 'Kontrola odeslání právě probíhá. Po jejím dokončení můžete ověřit další výběr.', parent=app)
            return
        session = access.refresh_session(M)
        if session is None or not session.active:return
        attempts = editable_attempts(tracking.pending(M, session.user_id, request_ids))
        if not attempts:
            if manual:
                message = ('U vybraných poptávek nemáte žádný neověřený e-mail vytvořený z CRM.' if request_ids is not None
                           else 'Nemáte žádný neověřený e-mail vytvořený z CRM.')
                M.messagebox.showinfo('E-mail', message + ' Již ověřené odeslání zůstává evidované.', parent=app)
            return
        submit_check(app, attempts, session.user_id, str(M.DB), manual)

    def check_selected(app, tree):
        request_ids = [int(iid[1:]) for iid in tree.selection() if iid.startswith('r') and iid[1:].isdigit()]
        if not request_ids:
            M.messagebox.showinfo('E-mail', 'Vyberte alespoň jednu poptávku.', parent=app)
            return
        start_check(app, manual=True, request_ids=request_ids)
    M.App.check_selected_request_mail = check_selected

    def finish_check(app):
        if getattr(app, '_turto_closing', False):return
        pending = app._mail_checks
        if pending is None:return
        future, attempts, uid, db, manual, remaining = pending
        if not future.done():
            app.after(150, lambda: finish_check(app));return
        app._mail_checks = None
        session = access.refresh_session(M)
        # A result from another login or database must never write through the new session.
        if session is None or not session.active or session.user_id != uid or str(M.DB) != db:return
        try:
            tracking.record_checks(M, editable_attempts(attempts), future.result())
            paint(app)
            remaining = editable_attempts(remaining)
            if remaining:
                submit_check(app, remaining, uid, db, manual)
                return
            if manual:
                M.messagebox.showinfo('E-mail', 'Kontrola dokončena. Stav najdete ve sloupci E-mail. Nenalezená zpráva zůstává „Odeslání neověřeno“.', parent=app)
        except Exception:
            if manual:M.messagebox.showwarning('E-mail', 'Odeslání se nepodařilo ověřit. Zkuste kontrolu znovu s otevřeným klasickým Outlookem.', parent=app)

    def tick(app):
        if getattr(app, '_turto_closing', False):return
        start_check(app)
        app._mail_timer = app.after(180000, lambda: tick(app))
    M.App.check_request_mail = start_check
    previous_close = M.App.close_app
    def close(app, *args, **kwargs):
        executor = getattr(app, '_mail_executor', None)
        if executor:executor.shutdown(wait=False, cancel_futures=True)
        return previous_close(app, *args, **kwargs)
    M.App.close_app = close
