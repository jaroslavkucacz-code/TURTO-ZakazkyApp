from __future__ import annotations

import ctypes
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    patch_file = ROOT / 'patch_v015.py'
    if patch_file.exists():
        from patch_v015 import apply_patch
        apply_patch(ROOT)
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
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
