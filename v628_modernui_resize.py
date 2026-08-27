# TURTO CRM 6.0.29 - modern palette + only active page participates in layout


def apply(M):
    # ------------------------------------------------------------------
    # 1) ACTIVE PAGE ONLY IN GRID
    # ------------------------------------------------------------------
    def show_page_light(self, key):
        tabs = getattr(self, 'tabs', {})
        if key not in tabs:
            return
        previous = getattr(self, '_current_page', None)

        try:
            for name, button in self.nav.items():
                button.configure(style='TopNavActive.TButton' if name == key else 'TopNav.TButton')
        except Exception:
            pass

        if previous and previous != key and previous in tabs:
            try: tabs[previous].grid_remove()
            except Exception: pass

        page = tabs[key]
        try:
            page.grid()
            page.tkraise()
        except Exception:
            return

        self._current_page = key
        if previous != key:
            for name in ('action_tree','request_tree','mivo_tree','offer_tree','task_tree','project_tree','people_tree','company_tree'):
                try:
                    tree = getattr(self, name, None)
                    if tree is not None:
                        tree._sort_state = {}
                        tree._active_sort = None
                except Exception:
                    pass

    M.App.show_page = show_page_light

    def detach_hidden_pages(app):
        try:
            current = getattr(app, '_current_page', None) or 'dash'
            for key, page in app.tabs.items():
                if key == current:
                    try: page.grid()
                    except Exception: pass
                else:
                    try: page.grid_remove()
                    except Exception: pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2) STRONGER MODERN STATUS PALETTE
    # Poptavky use req_fresh/req_received, so include them explicitly.
    # ------------------------------------------------------------------
    DARK = {
        'status_active': ('#244E73', '#F4FAFF'),
        'status_offer':  ('#176A63', '#F1FFFC'),
        'status_wait':   ('#7A5A12', '#FFF5CF'),
        'status_done':   ('#2D6A48', '#F2FFF7'),
        'status_cancel': ('#753743', '#FFF3F5'),
        'status_late':   ('#8A3434', '#FFF3F3'),
        'status_soon':   ('#7A5A12', '#FFF5CF'),
        'req_fresh':     ('#7A5A12', '#FFF5CF'),
        'req_received':  ('#176A63', '#F1FFFC'),
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

    def modernize_tree(tree, palette, dark):
        try:
            if not isinstance(tree, M.ttk.Treeview):
                return
            for tag, (bg, fg) in palette.items():
                try: tree.tag_configure(tag, background=bg, foreground=fg)
                except Exception: pass
            try:
                style_name = str(tree.cget('style') or 'Treeview')
                style = M.ttk.Style(tree)
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
        except Exception:
            pass

    def apply_modern_palette(app):
        palette = DARK if is_dark(app) else LIGHT
        dark = is_dark(app)
        def walk(widget):
            try:
                modernize_tree(widget, palette, dark)
                for child in widget.winfo_children(): walk(child)
            except Exception:
                pass
        walk(app)

    old_theme = getattr(M.App, 'apply_theme', None)
    if callable(old_theme):
        def apply_theme_modern(self, *args, **kwargs):
            result = old_theme(self, *args, **kwargs)
            try:self.after_idle(lambda:apply_modern_palette(self))
            except Exception:apply_modern_palette(self)
            return result
        M.App.apply_theme = apply_theme_modern

    old_init = M.App.__init__
    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:self.after(1450, lambda:detach_hidden_pages(self))
        except Exception:pass
        try:self.after(1550, lambda:apply_modern_palette(self))
        except Exception:pass
        return result
    M.App.__init__ = init

    for refresh_name in ('refresh_dash','refresh_actions','refresh_requests','refresh_mivo_requests','refresh_offers','refresh_tasks','refresh_projects','refresh_people','refresh_companies','refresh_all'):
        old = getattr(M.App, refresh_name, None)
        if not callable(old):
            continue
        def make_wrapper(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                try:self.after_idle(lambda:apply_modern_palette(self))
                except Exception:pass
                return result
            return wrapped
        setattr(M.App, refresh_name, make_wrapper(old))

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
                        widget.insert('end', '\n\nBAREVNOST 6.0.29\nStavove barvy maji vyssi kontrast a Poptavky jsou zahrnuty stejnym systemem. Cekajici poptavky pouzivaji jantarovy akcent, prijata odpoved tyrkysovy a archiv/zruseno vinovy. Optimalizace resize hlavniho okna zustava zachovana.')
                        widget.configure(state='disabled')
                    for child in widget.winfo_children(): walk(child)
                walk(page)
            except Exception:pass
            return result
        M.App.build_help = help_page
    except Exception:
        pass
