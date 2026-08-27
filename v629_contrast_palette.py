# TURTO CRM 6.0.29 - stronger modern contrast palette incl. Poptavky tags


def apply(M):
    DARK = {
        'status_active': ('#244E73', '#F4FAFF'),
        'status_offer':  ('#176A63', '#F1FFFC'),
        'status_wait':   ('#7A5A12', '#FFF5CF'),
        'status_done':   ('#2D6A48', '#F2FFF7'),
        'status_cancel': ('#753743', '#FFF3F5'),
        'status_late':   ('#8A3434', '#FFF3F3'),
        'status_soon':   ('#7A5A12', '#FFF5CF'),
        # Poptavky use their own row tags in the base app.
        'req_fresh':     ('#7A5A12', '#FFF5CF'),   # ceka na odpoved
        'req_received':  ('#176A63', '#F1FFFC'),   # prijata odpoved / uzavrena reakce
    }
    LIGHT = {
        'status_active': ('#CFE7FA', '#173A55'),
        'status_offer':  ('#CBEDE7', '#124D48'),
        'status_wait':   ('#F9E4A4', '#5B420C'),
        'status_done':   ('#CDE9D8', '#1E4F35'),
        'status_cancel': ('#F0C9D0', '#66303A'),
        'status_late':   ('#F3C1C1', '#6D2C2C'),
        'status_soon':   ('#F9E4A4', '#5B420C'),
        'req_fresh':     ('#F9E4A4', '#5B420C'),
        'req_received':  ('#CBEDE7', '#124D48'),
    }

    def is_dark(app):
        try:
            return 'tmav' in str(app.theme.get() or '').casefold()
        except Exception:
            return True

    def recolor(app):
        palette = DARK if is_dark(app) else LIGHT
        dark = is_dark(app)

        def walk(widget):
            try:
                if isinstance(widget, M.ttk.Treeview):
                    for tag, (bg, fg) in palette.items():
                        try:
                            widget.tag_configure(tag, background=bg, foreground=fg)
                        except Exception:
                            pass
                    try:
                        style_name = str(widget.cget('style') or 'Treeview')
                        style = M.ttk.Style(widget)
                        style.configure(style_name, rowheight=30)
                        if dark:
                            style.map(style_name,
                                      background=[('selected', '#2F6F9F')],
                                      foreground=[('selected', '#FFFFFF')])
                        else:
                            style.map(style_name,
                                      background=[('selected', '#A9D2F0')],
                                      foreground=[('selected', '#102C42')])
                    except Exception:
                        pass
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass

        walk(app)

    old_theme = getattr(M.App, 'apply_theme', None)
    if callable(old_theme):
        def themed(self, *args, **kwargs):
            result = old_theme(self, *args, **kwargs)
            try:self.after_idle(lambda:recolor(self))
            except Exception:recolor(self)
            return result
        M.App.apply_theme = themed

    old_init = M.App.__init__
    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:self.after(1700, lambda:recolor(self))
        except Exception:pass
        return result
    M.App.__init__ = init

    for name in ('refresh_dash','refresh_actions','refresh_requests','refresh_mivo_requests','refresh_offers','refresh_tasks','refresh_projects','refresh_all'):
        old = getattr(M.App, name, None)
        if not callable(old):
            continue
        def make(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                try:self.after_idle(lambda:recolor(self))
                except Exception:pass
                return result
            return wrapped
        setattr(M.App, name, make(old))

    try:
        old_help = M.App.build_help
        def help_page(self):
            result = old_help(self)
            try:
                import tkinter as tk
                page = self.tabs['help']
                def walk(widget):
                    if isinstance(widget, tk.Text):
                        widget.configure(state='normal')
                        widget.insert('end', '\n\nBAREVNOST 6.0.29\nStavove barvy maji vyssi kontrast, ale zustavaji moderni a tlumene. Poptavky jsou nově zahrnuty stejnym systemem: cekajici radky pouzivaji jantarovy akcent, prijata odpoved tyrkysovy akcent a archiv/zruseno stejny vinovy stav jako v ostatnich castech CRM.')
                        widget.configure(state='disabled')
                    for child in widget.winfo_children():walk(child)
                walk(page)
            except Exception:pass
            return result
        M.App.build_help = help_page
    except Exception:
        pass
