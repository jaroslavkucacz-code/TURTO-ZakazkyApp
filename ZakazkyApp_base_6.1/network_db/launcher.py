"""Standalone pilot. Never imports the production app, updater or data location."""
import argparse
from pathlib import Path
import sys


def main():
    if Path(sys.executable).stem == 'TURTO-CRM-Mistni-Ukazka':
        if '--demo-smoke-test' in sys.argv:
            from .local_demo_smoke import main as smoke
            return smoke()
        from .local_demo_ui import main as demo
        return demo()
    if Path(sys.executable).stem.endswith('-Admin'):
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.reconfigure(encoding='utf-8')
        from .__main__ import main as admin
        return admin()
    parser = argparse.ArgumentParser(description='TURTO CRM – síťový pilot')
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--config', help=argparse.SUPPRESS)
    parser.add_argument('--report', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke_test:
        from .smoke import run
        return run(args.config, args.report)
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TURTO.CRM.NetworkPilot')
    import tkinter as tk
    from .ui import open_pilot
    root = tk.Tk(); root.withdraw()
    win = open_pilot(root)
    icon = Path(__file__).with_name('turto_logo.ico')
    if icon.is_file():
        try: win.iconbitmap(str(icon))
        except tk.TclError: pass
    win.bind('<Destroy>', lambda e=None: root.destroy() if e is not None and e.widget is win else None)
    if not win.profile_path.get():
        win.after_idle(win.configure_connection)
    root.mainloop()
    return 0
