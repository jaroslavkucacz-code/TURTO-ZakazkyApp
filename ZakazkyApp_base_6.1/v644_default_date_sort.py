# TURTO CRM 6.3.1 - single owner of default table sorting
from datetime import datetime


WARNING_MARKERS = ('⚠️', '⚠', '▲', '△')


def apply(M):
    def parse_date(value):
        # Date cells can be decorated briefly by older warning/highlight callbacks
        # before v640 removes the visual marker. Sorting must always use the real
        # date value, otherwise a transient "⚠ 20.08.2026" is treated as empty and
        # waiting requests jump to the end until the next page refresh.
        s = str(value or '').strip()
        for marker in WARNING_MARKERS:
            s = s.replace(marker, '')
        s = ' '.join(s.split())
        for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d.%m.%y'):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
        return datetime.min

    def reset_sort_state(tree):
        try:
            tree._sort_state = {}
            tree._active_sort = None
        except Exception:
            pass

    def sort_date(tree, candidates):
        if tree is None:
            return
        try:
            cols = list(tree.cget('columns'))
            col = next((c for c in candidates if c in cols), None)
            if not col:
                return
            rows = [
                (parse_date(tree.set(iid, col)), iid)
                for iid in tree.get_children('')
            ]
            rows.sort(key=lambda x: x[0], reverse=True)
            for pos, (_, iid) in enumerate(rows):
                tree.move(iid, '', pos)
            reset_sort_state(tree)
        except Exception:
            pass

    def sort_alpha(tree, candidates):
        if tree is None:
            return
        try:
            cols = list(tree.cget('columns'))
            col = next((c for c in candidates if c in cols), None)
            if not col:
                return
            key = getattr(
                M,
                'czech_sort_key',
                lambda v: str(v or '').strip().casefold(),
            )
            rows = list(tree.get_children(''))
            rows.sort(key=lambda iid: key(tree.set(iid, col)))
            for pos, iid in enumerate(rows):
                tree.move(iid, '', pos)
            reset_sort_state(tree)
        except Exception:
            pass

    def apply_defaults(app):
        # Příležitosti: nejnovější Přijato nahoře.
        sort_date(
            getattr(app, 'action_tree', None),
            ('Přijato', 'Datum přijetí', 'Přijetí'),
        )
        # Poptávky + MIVO: nejnovější Poptáno nahoře.
        sort_date(
            getattr(app, 'request_tree', None),
            ('Poptáno', 'Datum poptávky', 'Poptávka'),
        )
        sort_date(
            getattr(app, 'mivo_tree', None),
            ('Poptáno', 'Datum poptávky', 'Poptávka'),
        )
        # Akce: abecedně podle názvu.
        sort_alpha(
            getattr(app, 'project_tree', None),
            ('Název Akce', 'Název akce', 'Akce', 'Název'),
        )

    for name in (
        'refresh_actions',
        'refresh_requests',
        'refresh_mivo_requests',
        'refresh_mivo',
        'refresh_projects',
        'refresh_all',
    ):
        old = getattr(M.App, name, None)
        if not callable(old):
            continue

        def make(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                try:
                    self.after_idle(lambda: apply_defaults(self))
                except Exception:
                    apply_defaults(self)
                return result

            return wrapped

        setattr(M.App, name, make(old))

    old_show = getattr(M.App, 'show_page', None)
    if callable(old_show):
        def show_page(self, *args, **kwargs):
            result = old_show(self, *args, **kwargs)
            try:
                self.after_idle(lambda: apply_defaults(self))
            except Exception:
                apply_defaults(self)
            return result

        M.App.show_page = show_page

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after(250, lambda: apply_defaults(self))
            self.after(1000, lambda: apply_defaults(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init
