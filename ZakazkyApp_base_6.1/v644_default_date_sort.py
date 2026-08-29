# TURTO CRM 6.3.31 - single owner of default table sorting
from datetime import datetime


WARNING_MARKERS = ("⚠️", "⚠", "▲", "△")
PAGE_SORTS = {
    "actions": ("date", "action_tree", ("Přijato", "Datum přijetí", "Přijetí")),
    "requests": ("date", "request_tree", ("Poptáno", "Datum poptávky", "Poptávka")),
    "mivo": ("date", "mivo_tree", ("Poptáno", "Datum poptávky", "Poptávka")),
    "projects": ("alpha", "project_tree", ("Název Akce", "Název akce", "Akce", "Název")),
}


def apply(M):
    if getattr(M, "_turto_default_sort_v6331", False):
        return

    def widget_exists(widget):
        try:
            return widget is not None and bool(widget.winfo_exists())
        except Exception:
            return widget is not None

    def parse_date(value):
        # Keep the 6.3.21 regression fix: a temporary visual warning marker must
        # never make a real date sort as an empty value.
        text = str(value or "").strip()
        for marker in WARNING_MARKERS:
            text = text.replace(marker, "")
        text = " ".join(text.split())
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
            try:
                return datetime.strptime(text, fmt)
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
        if not widget_exists(tree):
            return
        try:
            columns = list(tree.cget("columns"))
            column = next((candidate for candidate in candidates if candidate in columns), None)
            if not column:
                return
            rows = [(parse_date(tree.set(iid, column)), iid) for iid in tree.get_children("")]
            rows.sort(key=lambda pair: pair[0], reverse=True)
            for position, (_value, iid) in enumerate(rows):
                tree.move(iid, "", position)
            reset_sort_state(tree)
        except Exception:
            pass

    def sort_alpha(tree, candidates):
        if not widget_exists(tree):
            return
        try:
            columns = list(tree.cget("columns"))
            column = next((candidate for candidate in candidates if candidate in columns), None)
            if not column:
                return
            key = getattr(M, "czech_sort_key", lambda value: str(value or "").strip().casefold())
            rows = list(tree.get_children(""))
            rows.sort(key=lambda iid: key(tree.set(iid, column)))
            for position, iid in enumerate(rows):
                tree.move(iid, "", position)
            reset_sort_state(tree)
        except Exception:
            pass

    def apply_default(app, page_key=None):
        # No global sort sweep. Only the table that has just been refreshed is
        # touched, so switching tabs cannot repeatedly sort unrelated datasets.
        key = page_key or getattr(app, "_current_page", None)
        spec = PAGE_SORTS.get(key)
        if not spec:
            return
        mode, attribute, candidates = spec
        tree = getattr(app, attribute, None)
        if mode == "date":
            sort_date(tree, candidates)
        else:
            sort_alpha(tree, candidates)

    def schedule_default(app, page_key):
        if getattr(app, "_turto_closing", False):
            return
        jobs = getattr(app, "_turto_default_sort_jobs", None)
        if jobs is None:
            jobs = {}
            app._turto_default_sort_jobs = jobs
        previous = jobs.pop(page_key, None)
        if previous is not None:
            try:
                app.after_cancel(previous)
            except Exception:
                pass

        def run():
            jobs.pop(page_key, None)
            if getattr(app, "_turto_closing", False):
                return
            # Hidden tables do not need work. The navigation owner applies the
            # default immediately after the page is actually refreshed.
            if getattr(app, "_current_page", None) != page_key:
                return
            apply_default(app, page_key)

        try:
            jobs[page_key] = app.after_idle(run)
        except Exception:
            apply_default(app, page_key)

    for method_name, page_key in (
        ("refresh_actions", "actions"),
        ("refresh_requests", "requests"),
        ("refresh_mivo_requests", "mivo"),
        ("refresh_mivo", "mivo"),
        ("refresh_projects", "projects"),
    ):
        original = getattr(M.App, method_name, None)
        if not callable(original):
            continue

        def make(function, key):
            def wrapped(self, *args, **kwargs):
                result = function(self, *args, **kwargs)
                # The responsive navigation owner applies the sort once after a
                # controlled page refresh. Direct refresh calls still receive it.
                if not getattr(self, "_turto_page_refresh_running", False):
                    schedule_default(self, key)
                return result
            return wrapped

        setattr(M.App, method_name, make(original, page_key))

    M.apply_default_table_sort = apply_default
    M._turto_default_sort_v6331 = True
