"""Invoked only by the frozen installer's explicit --smoke-test entry point."""
def check(module):
    import tkinter as tk
    from . import PAGES
    from .ui import ReportWorkspace
    from .exports import export_excel, _build_pdf_html
    root = tk.Tk()
    root.withdraw()
    root.theme = tk.StringVar(master=root, value='Světlý')
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    widget = None
    try:
        widget = ReportWorkspace(root, module, (str(module.DB), 'SMOKE'))
        widget.pack(fill='both', expand=True)
        for label in PAGES.values():
            widget.show_page(label)
            root.update()
            if widget.last_error:raise RuntimeError(widget.last_error)
        path = widget.store.directory('exports') / 'frozen-smoke.xlsx'
        export_excel(path, widget.analytics, 2026, 8)
        assert path.stat().st_size > 1000
        assert '<html' in _build_pdf_html(widget.analytics, 2026, 8).lower()
        if errors:raise RuntimeError(str(errors))
        return list(PAGES)
    finally:
        if widget is not None:widget.destroy()
        for token in root.tk.splitlist(root.tk.call('after', 'info')):root.after_cancel(token)
        root.destroy()
