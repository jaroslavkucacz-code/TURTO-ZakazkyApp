from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
if not FROZEN and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_USER_MODEL_ID = 'cz.turto.mesicni-prehledy'


def _prepare_windows() -> None:
    if sys.platform != 'win32':
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _self_test() -> int:
    from src.constants import APP_VERSION
    from src.config import app_root, user_data_root
    if APP_VERSION != '1.1.1':
        return 11
    if app_root().resolve() != ROOT.resolve():
        return 12
    try:
        data_root = user_data_root()
        data_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        return 13
    try:
        import xlsxwriter  # noqa: F401
    except Exception:
        return 14
    return 0


if '--turto-self-test' in sys.argv:
    code=_self_test()
    if code: raise SystemExit(code)
    from src.runtime_check import run_model_check
    raise SystemExit(run_model_check())
if '--turto-chart-self-test' in sys.argv:
    from src.chart_check import run_chart_check
    raise SystemExit(run_chart_check())
if '--turto-ui-self-test' in sys.argv:
    from src.runtime_check import run_ui_check
    raise SystemExit(run_ui_check())

try:
    _prepare_windows()
    from src.ui import App
    app = App()
    app.mainloop()
except Exception:
    try:
        from src.config import user_data_root
        log = user_data_root() / 'turto_error.log'
    except Exception:
        log = ROOT / 'turto_error.log'
    try:
        log.write_text(traceback.format_exc(), encoding='utf-8')
    except Exception:
        pass
    try:
        import tkinter.messagebox as mb
        mb.showerror('TURTO – chyba', f'Program se nepodařilo spustit.\n\nPodrobnosti jsou v souboru:\n{log}')
    except Exception:
        pass
