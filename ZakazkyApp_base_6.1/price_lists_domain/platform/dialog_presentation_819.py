"""Keep the first Windows surface invisible until its native geometry settles.

Mapping remains available to modal grabs, wait_visibility and legacy form
builders. No nested Tk loop, global focus override or repeated hiding is used.
"""
import sys
import weakref


def begin(win):
    if sys.platform != 'win32':
        return
    try:
        win._turto_dialog_alpha_819 = float(win.attributes('-alpha'))
        win.attributes('-alpha', 0.0)
        win._turto_dialog_pending_819 = True
        win._turto_dialog_jobs_819 = set()
        root_ref = weakref.ref(win._root())
        win_ref = weakref.ref(win)

        def destroyed(event):
            current, root = win_ref(), root_ref()
            if current is None or root is None or event.widget is not current:
                return
            for job in tuple(current._turto_dialog_jobs_819):
                try:
                    root.after_cancel(job)
                except Exception:
                    pass
            current._turto_dialog_jobs_819.clear()
        win.bind('<Destroy>', destroyed, add='+')
    except Exception as exc:
        win._turto_dialog_presentation_error_819 = str(exc)
        win._turto_dialog_pending_819 = False
        try:
            win.attributes('-alpha', getattr(win, '_turto_dialog_alpha_819', 1.0))
        except Exception:
            pass


def mapped(win, place):
    if not getattr(win, '_turto_dialog_pending_819', False):
        place(win)
        return
    if win._turto_dialog_jobs_819:
        return
    root_ref, win_ref = weakref.ref(win._root()), weakref.ref(win)

    def schedule(callback, idle=False):
        root, current = root_ref(), win_ref()
        if root is None or current is None or not current.winfo_exists():
            return
        def run():
            current = win_ref()
            if current is None or not current.winfo_exists():
                return
            current._turto_dialog_jobs_819.discard(job)
            callback(current)
        job = root.after_idle(run) if idle else root.after(0, run)
        current._turto_dialog_jobs_819.add(job)

    def reveal(current, attempt=0):
        if not current.winfo_ismapped():
            # A caller explicitly withdrew/iconified the window. Its later Map
            # will restart presentation; never deiconify a caller-owned popup.
            return
        if not current.overrideredirect():
            place(current)
            target = getattr(current, '_turto_dialog_target_818', None)
            if target is not None and current.state() != 'zoomed':
                actual = (current.winfo_width(), current.winfo_height(),
                          current.winfo_x(), current.winfo_y())
                if any(abs(a-b) > 2 for a, b in zip(actual, target)):
                    if attempt < 4:
                        schedule(lambda w: schedule(lambda w: reveal(w, attempt+1)), idle=True)
                        return
                    # A window-manager failure must never strand an invisible
                    # modal form. Retain a diagnostic for the runtime probe.
                    current._turto_dialog_presentation_error_819 = f'Geometry did not settle: {actual} != {target}'
        current._turto_dialog_pending_819 = False
        current.attributes('-alpha', current._turto_dialog_alpha_819)
        current._turto_dialog_presented_819 = True

    def position(current):
        place(current)
        # Geometry requests flush during idle; a timer runs after construction
        # code using update_idletasks has returned to the normal event loop.
        schedule(lambda w: schedule(reveal), idle=True)

    schedule(position, idle=True)
