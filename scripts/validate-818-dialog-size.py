#!/usr/bin/env python3
"""Real Windows dialog sizing, main-window ownership and compact popup checks."""
import os
from pathlib import Path
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))
import v770_runtime_policy as policy


def geometry_checks():
    # Independent examples include displays left of and above the primary one.
    assert policy._dialog_geometry((100, 100, 1000, 700), (0, 0, 1920, 1040)) == (900, 630, 150, 135)
    assert policy._dialog_geometry((-1800, 100, 1200, 800), (-1920, 0, 0, 1040)) == (1080, 720, -1740, 140)
    assert policy._dialog_geometry((100, -1000, 1000, 800), (0, -1080, 1920, 0)) == (900, 720, 150, -960)
    for owner, area in [((20, 20, 2560, 1440), (0, 0, 1280, 720)),
                        ((-2300, -200, 2500, 1600), (-1920, 0, 0, 1040)),
                        ((0, 0, 500, 300), (0, 0, 640, 480))]:
        w, h, x, y = policy._dialog_geometry(owner, area)
        assert area[0] <= x < x+w <= area[2]
        assert area[1] <= y < y+h+30 <= area[3]
    print('Dialog geometry: normal, small, off-screen and negative-coordinate monitors OK', flush=True)


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
    import win32gui
    from PIL import ImageGrab
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform.form_behavior_817 import children
    from price_lists_domain.issued_offers.template_settings import TemplateEditor
    from update_progress import ProgressWindow
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    app.APP_VERSION = (REPO / 'build/windows/version.txt').read_text().strip()
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    root = app.App()
    errors = []
    root.report_callback_exception = lambda *exc: errors.append(str(exc))

    def check(win, label):
        settle(root)
        monitor = win32api.MonitorFromWindow(root.winfo_id(), 2)
        area = tuple(win32api.GetMonitorInfo(monitor)['Work'])
        assert policy._workarea_for_window(root) == area
        owner = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height())
        expected = policy._dialog_geometry(owner, area)
        actual = (win.winfo_width(), win.winfo_height())
        assert all(abs(a-b) <= 2 for a, b in zip(actual, expected[:2])), (label, actual, expected, win.geometry())
        rect = win32gui.GetWindowRect(win32gui.GetAncestor(win.winfo_id(), 2))
        assert rect[0] >= area[0]-2 and rect[1] >= area[1]-2 and rect[2] <= area[2]+2 and rect[3] <= area[3]+2, (label, rect, area)
        assert win32api.MonitorFromWindow(win.winfo_id(), 2) == monitor, (label, 'wrong monitor')
        print('Dialog size OK:', label, actual, 'main:', owner[2:], flush=True)

    def capture(name):
        dest = REPO / 'dist/branding-preview'
        dest.mkdir(parents=True, exist_ok=True)
        rect = win32gui.GetWindowRect(win32gui.GetAncestor(root.winfo_id(), 2))
        ImageGrab.grab(bbox=rect, all_screens=True).save(dest / name)

    try:
        root.state('normal')
        root.geometry('1200x780+20+20')
        settle(root, 4.2)
        for state in ('normal', 'zoomed'):
            root.state(state)
            settle(root)
            for cls in (app.CompanyDialog, app.PersonDialog, app.ProjectDialog,
                        app.TaskDialog, app.ActionDialog, app.RequestDialog, app.UserNotesDialog):
                win = cls(root)
                check(win, state + ':' + cls.__name__)
                if cls is app.ProjectDialog:
                    capture('dialog-818-' + state + '.png')
                win.destroy()
            editor = app.IssuedOfferEditor(app, root)
            check(editor.win, state + ':IssuedOfferEditor')
            editor.win.destroy()
            template = TemplateEditor(app, root)
            check(template.win, state + ':TemplateEditor')
            template.close()

        # A child form uses the main window, not 90% of an already sized dialog.
        outer = app.CompanyDialog(root)
        check(outer, 'outer')
        outer.geometry('650x450+25+25')
        settle(root)
        nested = app.PersonDialog(outer)
        check(nested, 'nested PersonDialog')
        nested.destroy()
        assert outer.winfo_width() == 650 and outer.winfo_height() == 450
        outer.destroy()

        # Delayed first display still receives the policy, while subsequent
        # manual resizing, moving and maximize/restore are respected.
        delayed = app.tk.Toplevel(root)
        delayed.withdraw()
        app.ttk.Entry(delayed).pack()
        settle(root, .4)
        delayed.deiconify()
        check(delayed, 'delayed first map')
        delayed.geometry('640x420+35+35')
        policy._place_dialog(delayed, root)
        settle(root)
        assert (delayed.winfo_width(), delayed.winfo_height()) == (640, 420)
        delayed.state('zoomed')
        settle(root)
        policy._place_dialog(delayed, root)
        assert delayed.state() == 'zoomed'
        delayed.state('normal')
        settle(root)
        assert (delayed.winfo_width(), delayed.winfo_height()) == (640, 420)
        delayed.destroy()

        # Suggestion windows, calendars and progress stay compact.
        win = app.ProjectDialog(root)
        settle(root)
        picker = next(w for w in children(win) if isinstance(w, app.DatePicker))
        picker.open_calendar()
        settle(root)
        calendar = next(w for w in picker.winfo_children() if isinstance(w, app.tk.Toplevel))
        assert calendar.winfo_width() < root.winfo_width() * .7
        assert calendar.winfo_height() < root.winfo_height() * .7
        calendar.destroy()
        win.destroy()
        progress = ProgressWindow(root, '8.0.18')
        settle(root)
        assert progress.window.winfo_height() < root.winfo_height() * .6
        progress.destroy()
        popup = app.tk.Toplevel(root)
        popup.overrideredirect(True)
        popup.geometry('300x80+50+50')
        settle(root)
        assert (popup.winfo_width(), popup.winfo_height()) == (300, 80)
        popup.destroy()

        # Exercise every physically available monitor; arithmetic above covers
        # negative origins even on single-monitor hosted Windows runners.
        monitors = win32api.EnumDisplayMonitors()
        for monitor, _, _ in monitors:
            left, top, right, bottom = win32api.GetMonitorInfo(monitor)['Work']
            root.state('normal')
            root.geometry(f'{min(1000, right-left-60)}x{min(700, bottom-top-80)}+{left+20}+{top+20}')
            settle(root)
            win = app.TaskDialog(root)
            check(win, 'physical monitor ' + str(monitor))
            win.destroy()
        assert not errors, errors
        print(f'8.0.18 dialogs: 90% sizing, nested ownership, normal/maximized main, compact popups and {len(monitors)} physical monitor(s) OK', flush=True)
    finally:
        root._turto_closing = True
        root.destroy()


if __name__ == '__main__':
    geometry_checks()
    if sys.platform == 'win32':
        with tempfile.TemporaryDirectory(prefix='turto-dialog-818-', ignore_cleanup_errors=True) as td:
            run(td)
