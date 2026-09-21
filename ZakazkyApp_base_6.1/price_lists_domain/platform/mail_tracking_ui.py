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
        page = app.tabs[key]
        bar = M.ttk.Frame(page, style='Panel.TFrame', padding=(10, 6))
        first = next(iter(page.pack_slaves()), None)
        bar.pack(fill='x', **({'after': first} if first else {}))
        M.ttk.Button(bar, text='Ověřit odeslání v Outlooku', command=lambda: start_check(app, manual=True)).pack(side='left')
        M.ttk.Label(bar, text='Odeslání se ověřuje v klasickém Outlooku. Doručení a přečtení se nesleduje.',
                    wraplength=750).pack(side='left', padx=12)
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

    def start_check(app, manual=False):
        if app._mail_checks is not None:return
        session = access.refresh_session(M)
        if session is None or not session.active:return
        attempts = tracking.pending(M, session.user_id)
        from .access_controls import _request_page
        attempts = [r for r in attempts if access.level(M, _request_page(M, rid=r['request_id'])) >= access.EDIT]
        if not attempts:
            if manual:M.messagebox.showinfo('E-mail', 'Nemáte žádný neověřený koncept vytvořený v této verzi CRM. Již ověřené odeslání zůstává evidované.', parent=app)
            return
        app._mail_checks = (app._mail_executor.submit(tracking.check_outlook, attempts), attempts, session.user_id, str(M.DB), manual)
        app.after(150, lambda: finish_check(app))

    def finish_check(app):
        if getattr(app, '_turto_closing', False):return
        pending = app._mail_checks
        if pending is None:return
        future, attempts, uid, db, manual = pending
        if not future.done():
            app.after(150, lambda: finish_check(app));return
        app._mail_checks = None
        session = access.refresh_session(M)
        # A result from another login or database must never write through the new session.
        if session is None or session.user_id != uid or str(M.DB) != db:return
        try:
            tracking.record_checks(M, attempts, future.result())
            paint(app)
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
