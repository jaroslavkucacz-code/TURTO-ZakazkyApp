#!/usr/bin/env python3
"""Check the first native visible frame, not merely final settled geometry."""
import os
from pathlib import Path
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def settle(root, seconds=.45):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        root.update()
        time.sleep(.01)


def run(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import win32api
    import win32con
    import win32gui
    import app
    import data_location
    import runtime_bootstrap
    import v770_runtime_policy as policy
    from price_lists_domain.issued_offers.template_settings import TemplateEditor
    from dialog_chrome import is_compact_dialog
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    # Unexpected modal confirmations must fail visibly instead of hanging CI.
    def unexpected(*args, **kwargs):
        raise AssertionError(('Unexpected confirmation', args))
    app.messagebox.askyesnocancel = unexpected
    app.messagebox.askyesno = unexpected
    root = app.App()
    errors, revealed = [], []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))
    original_init = app.tk.Toplevel.__init__
    original_attributes = app.tk.Toplevel.attributes

    def native(win):
        hwnd = win32gui.GetAncestor(win.winfo_id(), 2)
        opacity = 255
        if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_LAYERED:
            _, opacity, flags = win32gui.GetLayeredWindowAttributes(hwnd)
            if not flags & win32con.LWA_ALPHA:
                opacity = 255
        return hwnd, opacity, win32gui.GetWindowRect(hwnd)

    def verify_position(win):
        if win.overrideredirect() or is_compact_dialog(win):
            return
        area = policy._workarea_for_window(root)
        owner = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
        w, h, x, y = policy._dialog_geometry(owner, area, frame_size=policy._dialog_frame_size(win))
        hwnd, opacity, rect = native(win)
        actual = (win.winfo_width(), win.winfo_height(), rect[0], rect[1])
        assert all(abs(a-b) <= 2 for a, b in zip(actual, (w, h, x, y))), ('visible before placement', win.title(), actual, (w, h, x, y))
        assert win32api.MonitorFromWindow(hwnd, 2) == win32api.MonitorFromWindow(root.winfo_id(), 2)

    def attributes(win, *args, **kwargs):
        # Observe the actual transition to native opacity, before another idle
        # pass could repair an incorrectly positioned first visible frame.
        result = original_attributes(win, *args, **kwargs)
        if len(args) >= 2 and args[0] == '-alpha' and float(args[1]) > 0:
            if win.winfo_ismapped():
                verify_position(win)
                assert native(win)[1] > 0, 'Window stayed natively transparent'
                win._probe_reveal_count = getattr(win, '_probe_reveal_count', 0) + 1
                revealed.append((win.title(), native(win)[2]))
        return result

    def init(win, *args, **kwargs):
        original_init(win, *args, **kwargs)
        win._probe_first_map_alpha = None
        def mapped(event):
            if event.widget is not win:
                return
            if win._probe_first_map_alpha is None:
                win._probe_first_map_alpha = native(win)[1]
                assert win._probe_first_map_alpha == 0, ('First Map was visible', win.title(), native(win))
            if native(win)[1] > 0:
                verify_position(win)
        win.bind('<Map>', mapped, add='+')

    def check(win, label):
        settle(root)
        assert win._probe_first_map_alpha == 0, label
        assert getattr(win, '_probe_reveal_count', 0) == 1, (label, 'Missing/duplicate reveal')
        assert not getattr(win, '_turto_dialog_presentation_error_819', None), (label, getattr(win, '_turto_dialog_presentation_error_819', None))
        assert not win._turto_dialog_pending_819 and win._turto_dialog_presented_819
        assert native(win)[1] == 255
        verify_position(win)
        print('First visible frame OK:', label, native(win)[2], flush=True)

    try:
        root.state('normal')
        root.geometry('1220x720+25+25')
        settle(root, 4.2)
        app.tk.Toplevel.__init__ = init
        app.tk.Toplevel.attributes = attributes
        for state in ('normal', 'zoomed'):
            root.state(state)
            settle(root)
            for cls in (app.CompanyDialog, app.PersonDialog, app.ProjectDialog,
                        app.TaskDialog, app.ActionDialog, app.RequestDialog, app.UserNotesDialog):
                win = cls(root)
                check(win, state + ':' + cls.__name__)
                win.destroy()
            editor = app.IssuedOfferEditor(app, root)
            check(editor.win, state + ':IssuedOfferEditor')
            editor.win.destroy()
            template = TemplateEditor(app, root)
            check(template.win, state + ':TemplateEditor')
            template.close()

        outer = app.CompanyDialog(root)
        check(outer, 'outer CompanyDialog')
        nested = app.PersonDialog(outer)
        check(nested, 'nested PersonDialog')
        nested.destroy(); outer.destroy()

        # Builders sometimes enter idle processing while adding controls, then
        # assign another legacy geometry. Neither may expose the first surface.
        factory = app.tk.Toplevel(root)
        app.ttk.Entry(factory).pack()
        root.update_idletasks()
        assert native(factory)[1] == 0
        factory.geometry('180x90+1+1')
        root.update_idletasks()
        assert native(factory)[1] == 0
        check(factory, 'constructor idle + late geometry')
        factory.destroy()

        delayed = app.tk.Toplevel(root)
        delayed.withdraw()
        app.ttk.Entry(delayed).pack()
        settle(root)
        assert delayed.state() == 'withdrawn' and not delayed.winfo_ismapped()
        delayed.deiconify()
        check(delayed, 'deliberately delayed window')
        # Reopening an existing window must not hide or move it again.
        delayed.withdraw(); delayed.deiconify()
        settle(root)
        assert delayed._probe_reveal_count == 1
        delayed.destroy()

        ephemeral = app.tk.Toplevel(root)
        disposals = []
        def dispose_during_map(event):
            if event.widget is not ephemeral:
                return
            jobs = set(ephemeral._turto_dialog_jobs_819)
            assert jobs, 'Did not exercise destruction before reveal'
            assert native(ephemeral)[1] == 0
            ephemeral.destroy()
            assert not jobs.intersection(root.tk.call('after', 'info'))
            disposals.append(True)
        # Windows may defer an empty Toplevel's Map beyond update_idletasks.
        # Destroy from the real Map, after the presentation owner queued work.
        ephemeral.bind('<Map>', dispose_during_map, add='+')
        settle(root)
        assert disposals == [True], disposals
        assert not errors, errors
        print(f'8.0.19: first Map hidden, {len(revealed)} native reveals already positioned, nested/delayed forms and pending-callback teardown OK', flush=True)
    finally:
        app.tk.Toplevel.__init__ = original_init
        app.tk.Toplevel.attributes = original_attributes
        root._turto_closing = True
        root.destroy()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='turto-first-show-819-', ignore_cleanup_errors=True) as td:
        run(td)
