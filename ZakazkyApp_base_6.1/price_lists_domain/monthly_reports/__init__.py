"""Embed the verified Měsíční přehledy 1.1.2 application in CRM navigation."""
from pathlib import Path
from ..platform import grouped_navigation as navigation, lazy_refresh

PAGES = {key: navigation.LABELS[key] for key in navigation.GROUPS['reports']}


def install(M):
    App = M.App
    if getattr(App, '_monthly_reports_832', False):
        return

    def refresh(app, key):
        from .ui import ReportWorkspace
        identity = (str(Path(M.DB).resolve()), app.active_user.get().strip())
        workspace = getattr(app, '_reports_workspace', None)
        if workspace is not None and workspace.identity != identity:
            if workspace.busy:
                raise RuntimeError('Nejprve dokončete import nebo export přehledů.')
            workspace.destroy()
            workspace = None
        if workspace is None:
            workspace = ReportWorkspace(app._reports_page, M, identity)
            app._reports_workspace = workspace
            workspace.pack(fill='both', expand=True)
        workspace.show_page(PAGES[key])

    for key in PAGES:
        method = 'refresh_' + key
        lazy_refresh.PAGE_REFRESH[key] = method
        setattr(App, method, lambda self, k=key: refresh(self, k))

    previous_activated = getattr(App, '_turto_page_activated', None)
    def activated(app, key):
        if callable(previous_activated):
            previous_activated(app, key)
        if key in PAGES:
            # Several leaf routes share one workspace and a single period filter.
            # Re-entering any route must display that route, even if loaded before.
            app._turto_mark_dirty({key})
    App._turto_page_activated = activated

    previous_build = App.build
    def build(app, *args, **kwargs):
        result = previous_build(app, *args, **kwargs)
        page = M.ttk.Frame(app.pages, style='App.TFrame')
        app._reports_page = page
        for key, label in PAGES.items():
            app.tabs[key] = page
            navigation.register_page(app, key, label)
        return result
    App.build = build

    def guard(app):
        workspace = getattr(app, '_reports_workspace', None)
        if workspace is not None and workspace.busy:
            M.messagebox.showinfo('Přehledy', 'Probíhá import nebo export přehledů. Počkejte prosím na jeho dokončení.', parent=app)
            return False
        return True

    # Do not abandon a running write by closing CRM or switching into TEST.
    previous_close = App.close_app
    def close(app, *args, **kwargs):
        if guard(app):
            return previous_close(app, *args, **kwargs)
    App.close_app = close
    previous_select = App.select_user
    def select(app, *args, **kwargs):
        if guard(app):
            workspace = getattr(app, '_reports_workspace', None)
            if workspace is not None:
                workspace.destroy()
                app._reports_workspace = None
            return previous_select(app, *args, **kwargs)
    App.select_user = select
    App._monthly_reports_832 = True
