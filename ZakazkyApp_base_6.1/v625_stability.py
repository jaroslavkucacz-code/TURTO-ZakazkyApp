# TURTO CRM - nonmodal update checks and modal-grab safety.
# Outlook import and Treeview resize are owned by post_baseline/v631.
import datetime
import json
import urllib.request


def apply(M):
    # ------------------------------------------------------------------
    # Nonmodal live-update notice.
    # ------------------------------------------------------------------
    try:
        import crm_runtime as runtime

        def version_tuple(value):
            try:
                return tuple(int(part) for part in str(value).split('.'))
            except Exception:
                return (0,)

        def live_update_checks(app):
            state = {'version': '', 'checking': False}

            def show_notice(version, notes):
                try:
                    old = getattr(app, '_update_notice_window', None)
                    if old is not None and old.winfo_exists():
                        old.destroy()
                except Exception:
                    pass
                try:
                    dialog = M.tk.Toplevel(app)
                    app._update_notice_window = dialog
                    dialog.title(f'Aktualizace {version}')
                    dialog.transient(app)
                    try:
                        M.enable_dialog_maximize(dialog, 680, 420)
                    except Exception:
                        pass
                    frame = M.ttk.Frame(dialog, padding=18)
                    frame.pack(fill='both', expand=True)
                    M.ttk.Label(
                        frame,
                        text=f'Je dostupná nová verze {version}',
                        style='Section.TLabel',
                    ).pack(anchor='w')
                    M.ttk.Label(
                        frame,
                        text='Co aktualizace obsahuje:',
                        style='PageSubtitle.TLabel',
                    ).pack(anchor='w', pady=(12, 4))
                    text = M.tk.Text(
                        frame,
                        height=9,
                        wrap='word',
                        font=('Calibri', 11),
                    )
                    text.pack(fill='both', expand=True)
                    text.insert('1.0', notes)
                    text.configure(state='disabled')
                    bar = M.ttk.Frame(frame)
                    bar.pack(fill='x', pady=(12, 0))
                    M.ttk.Button(
                        bar,
                        text='Později',
                        command=dialog.destroy,
                    ).pack(side='right')
                    M.ttk.Button(
                        bar,
                        text='Aktualizovat',
                        style='Accent.TButton',
                        command=lambda: (
                            dialog.destroy(),
                            app.check_for_updates(silent=False),
                        ),
                    ).pack(side='right', padx=6)
                    try:
                        dialog.lift()
                    except Exception:
                        pass
                except Exception:
                    pass

            def check_worker():
                if state['checking']:
                    return
                state['checking'] = True
                try:
                    if str(M.get_setting('company_auto_updates', '1')) == '0':
                        return
                    request = urllib.request.Request(
                        runtime.GITHUB_UPDATE
                        + '/latest.json?ts='
                        + str(int(datetime.datetime.now().timestamp())),
                        headers={'User-Agent': 'TURTO-CRM'},
                    )
                    with urllib.request.urlopen(request, timeout=8) as response:
                        data = json.load(response)
                    new_version = str(data.get('version', '')).strip()
                    current = str(M.APP_VERSION)
                    if (
                        new_version
                        and version_tuple(new_version) > version_tuple(current)
                        and state['version'] != new_version
                    ):
                        state['version'] = new_version
                        notes = (
                            str(data.get('notes', '')).strip()
                            or 'Drobné opravy a vylepšení.'
                        )
                        app.after(
                            0,
                            lambda v=new_version, n=notes: show_notice(v, n),
                        )
                except Exception:
                    pass
                finally:
                    state['checking'] = False

            def schedule():
                try:
                    import threading

                    threading.Thread(
                        target=check_worker,
                        daemon=True,
                    ).start()
                except Exception:
                    check_worker()
                try:
                    app.after(10 * 60 * 1000, schedule)
                except Exception:
                    pass

            app.after(1200, schedule)

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
