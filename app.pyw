from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_USER_MODEL_ID = 'cz.turto.mesicni-prehledy'

try:
    # Hotfix 0.2.1: nepouštět poškozený patch_v020.py.
    patch_file = ROOT / 'patch_v021.py'
    if patch_file.exists():
        from patch_v021 import apply_patch
        apply_patch(ROOT)

    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    try:
        from src.windows_integration import ensure_windows_shortcuts
        ensure_windows_shortcuts(ROOT)
    except Exception:
        pass

    from src.ui import App
    app = App()
    app.mainloop()
except Exception:
    log = ROOT / 'turto_error.log'
    log.write_text(traceback.format_exc(), encoding='utf-8')
    try:
        import tkinter.messagebox as mb
        mb.showerror('TURTO – chyba', f'Program se nepodařilo spustit.\n\nPodrobnosti jsou v souboru:\n{log}')
    except Exception:
        pass
