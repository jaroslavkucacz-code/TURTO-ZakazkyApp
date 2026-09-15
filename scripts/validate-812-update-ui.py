#!/usr/bin/env python3
"""Exercise real CRM buttons, responsive progress and standalone window lifetime."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / 'ZakazkyApp_base_6.1'
sys.path.insert(0, str(BASE))


def pump(win, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        win.update()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('UI did not reach expected state')


def button(win, text):
    for widget in win.winfo_children():
        if widget.winfo_class() in {'TButton', 'Button'} and str(widget.cget('text')) == text:
            return widget
        try:
            return button(widget, text)
        except LookupError:
            pass
    raise LookupError(text)


def capture(win, name):
    from PIL import ImageGrab
    win.update_idletasks()
    dest = REPO / 'dist/branding-preview'
    dest.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(win.winfo_rootx(), win.winfo_rooty(),
        win.winfo_rootx()+win.winfo_width(), win.winfo_rooty()+win.winfo_height())).save(dest / name)


def run_ui(td):
    os.environ['TURTO_CRM_DATA_ROOT'] = td
    os.environ['LOCALAPPDATA'] = str(Path(td) / 'local')
    os.environ['TURTO_DISABLE_AUTO_UPDATE'] = '1'
    import app
    import data_location
    import runtime_bootstrap
    from price_lists_domain.platform import automatic_updates as updates, exe_distribution
    from update_progress import ProgressWindow
    data_location.apply_to_app(app)
    app.ensure_schema()
    runtime_bootstrap.apply_all(app)
    exe_distribution.apply(app)
    app.APP_VERSION = '8.0.11'
    app.ensure_schema()
    app.ensure_test_user()
    app.App.maybe_show_morning_overview = lambda self: None
    app.messagebox.showinfo = lambda *a, **k: None
    app.messagebox.showwarning = lambda *a, **k: None
    window = app.App()
    window.state('normal')
    window.geometry('1220x720+0+0')
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(str(exc))
    gate = threading.Event()
    package = Path(td) / 'download.zip'
    package.write_bytes(b'PK-fixture')
    finished = threading.Event()
    def download(manifest, report):
        report('Stahuji aktualizaci…', .35, 'Staženo 35 MB ze 100 MB')
        gate.wait(10)
        finished.set()
        return package
    try:
        with mock.patch.object(updates, '_read_official_manifest', return_value={'version': '8.0.12', 'notes': 'Instalaci spouštíte vy. Během aktualizace vidíte průběh.'}), mock.patch.object(updates, '_launch_updater') as launch, mock.patch.object(app, '_download_update_with_progress', side_effect=download) as downloader, mock.patch.object(app, '_prepare_update_runtime'):
            os.environ['TURTO_DISABLE_AUTO_UPDATE'] = ''
            window.check_for_updates(silent=True)
            pump(window, lambda: not window._turto_auto_update_running)
            assert window._turto_update_banner.winfo_viewable()
            assert getattr(window, '_turto_update_offer', None) is None
            downloader.assert_not_called()
            capture(window, 'update-available.png')
            button(window._turto_update_banner, 'Zobrazit aktualizaci').invoke()
            window.update()
            capture(window._turto_update_offer, 'update-offer.png')
            button(window._turto_update_offer, 'Později').invoke()
            launch.assert_not_called()
            downloader.assert_not_called()
            window.open_update_dialog()
            button(window._turto_update_offer, 'Nainstalovat aktualizaci').invoke()
            progress = window._turto_update_progress
            pump(window, lambda: float(progress.bar.cget('value')) == 35)
            assert progress.window.winfo_viewable()
            assert window.winfo_exists()
            assert not window.install_available_update()
            assert not window.check_for_updates(silent=True)
            progress.request_close()
            assert progress.window.winfo_exists(), 'Busy progress window can disappear'
            capture(progress.window, 'update-download.png')
            gate.set()
            pump(window, lambda: launch.call_count == 1)
            assert finished.is_set()
            downloader.assert_called_once()
            progress.fail('Test přerušení spojení. CRM zůstalo otevřené.')
            pump(window, lambda: not progress.busy)
            assert not progress.closed
            assert not progress.close_button.instate(['disabled'])
            progress.request_close()
            assert progress.closed
        assert not errors, errors
    finally:
        gate.set()
        window._turto_closing = True
        window.destroy()

    # A separate root survives without any CRM owner and remains responsive
    # while the worker waits. Only completion, after restart readiness, closes it.
    standalone = ProgressWindow(version='8.0.12')
    standalone.window.report_callback_exception = lambda *exc: errors.append(str(exc))
    reported = threading.Event()
    def report():
        standalone.report('Zálohuji databázi…', detail='Ukládám zálohu vašich dat.')
        reported.set()
    worker = threading.Thread(target=report)
    worker.start()
    pump(standalone.window, lambda: reported.is_set() and standalone.stage.cget('text') == 'Zálohuji databázi…')
    worker.join()
    assert standalone.window.winfo_viewable()
    capture(standalone.window, 'update-installation.png')
    standalone.report('Spouštím TURTO CRM…')
    pump(standalone.window, lambda: standalone.stage.cget('text') == 'Spouštím TURTO CRM…')
    assert not standalone.closed
    standalone.complete()
    standalone.window.mainloop()
    assert standalone.closed and not errors, errors
    print('CRM update offer, explicit install button, responsive progress and standalone lifetime: OK')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--data-root':
        run_ui(sys.argv[2])
    else:
        with tempfile.TemporaryDirectory(prefix='turto-update-ui-') as td:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--data-root', td], check=True, timeout=120)
