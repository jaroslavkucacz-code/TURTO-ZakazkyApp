# TURTO CRM - one canonical updater schedule + modal-grab safety.
# Update detection/dialog/install is owned by App.check_for_updates.
# This layer only applies the ADMIN auto-update setting, debounces silent calls
# and schedules the next automatic check during long-running sessions.
import time


def apply(M):
    # ------------------------------------------------------------------
    # One update mechanism.
    #
    # The base App already schedules one startup call to check_for_updates().
    # Do not perform another HTTP check or create another update window here.
    # ------------------------------------------------------------------
    old_check = getattr(M.App, 'check_for_updates', None)
    if callable(old_check):
        def check_for_updates(self, *args, **kwargs):
            silent = bool(kwargs.get('silent', False))
            if not kwargs and args:
                # check_for_updates(silent) remains compatible with positional use.
                silent = bool(args[0])

            if silent and str(M.get_setting('company_auto_updates', '1')) == '0':
                return None

            if silent:
                now = time.monotonic()
                last = float(
                    getattr(self, '_turto_last_auto_update_check', 0.0)
                    or 0.0
                )
                # Protect against two runtime layers/timers calling the canonical
                # checker nearly simultaneously.
                if now - last < 30.0:
                    return None
                self._turto_last_auto_update_check = now

            return old_check(self, *args, **kwargs)

        M.App.check_for_updates = check_for_updates

    try:
        import crm_runtime as runtime

        def live_update_checks(app):
            # Startup is already handled by App.__init__. Schedule only the
            # subsequent long-running checks.
            def periodic():
                try:
                    app.check_for_updates(silent=True)
                except Exception:
                    pass
                finally:
                    try:
                        app.after(10 * 60 * 1000, periodic)
                    except Exception:
                        pass

            try:
                app.after(10 * 60 * 1000, periodic)
            except Exception:
                pass

        runtime._live_update_checks = live_update_checks
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Release invalid/hidden modal grabs only; visible dialogs remain modal.
    # ------------------------------------------------------------------
    def modal_safety(app):
        try:
            grabbed = app.grab_current()
            if grabbed is not None:
                try:
                    invalid = (
                        not bool(grabbed.winfo_exists())
                        or not bool(grabbed.winfo_viewable())
                    )
                except Exception:
                    invalid = True
                if invalid:
                    try:
                        grabbed.grab_release()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            app.after(1000, lambda: modal_safety(app))
        except Exception:
            pass

    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after(1000, lambda: modal_safety(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init
