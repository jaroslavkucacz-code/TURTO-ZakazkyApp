# TURTO CRM 6.0.28 - modern palette + only active page participates in layout


def apply(M):
    # ------------------------------------------------------------------
    # 1) ACTIVE PAGE ONLY IN GRID
    # Older versions keep all main pages gridded on top of each other and use
    # tkraise(). Tk therefore recomputes geometry of every hidden page during a
    # border resize. Keep only the visible page managed by grid instead.
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
            try:
                tabs[previous].grid_remove()
            except Exception:
                pass

        page = tabs[key]
        try:
            # grid() restores the previous row/column/sticky options after
            # grid_remove(), so the page returns at exactly the same position.
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
    # 2) MODERN GRAPHITE / PASTEL STATUS PALETTE
    # Keep status semantics, but use quieter modern tones instead of saturated
    # full-row colors. Selection remains visually distinct from status color.
    # ------------------------------------------------------------------
    DARK = {
        'status_active': ('#18324A', '#D9EAFA'),   # muted blue
        'status_offer':  ('#123C3A', '#D6F4EF'),   # teal
        'status_wait':   ('#463716', '#F8E7B0'),   # amber
        'status_done':   ('#183B2A', '#D9F2E3'),   # green
        'status_cancel': ('#48282D', '#F4DADD'),   # wine red
        'status_late':   ('#4A2525', '#FFD9D9'),
        'status_soon':   ('#463716', '#F8E7B0'),
    }
    LIGHT = {
        'status_active': ('#EAF3FB', '#1E3A52'),
        'status_offer':  ('#E6F6F3', '#175A55'),
        'status_wait':   ('#FFF4D6', '#6B5315'),
        'status_done':   ('#E8F5EC', '#24563A'),
        'status_cancel': ('#F8E9EB', '#704047'),
        'status_late':   ('#FCE7E7', '#7D3535'),
        'status_soon':   ('#FFF4D6', '#6B5315'),
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
                try:
                    tree.tag_configure(tag, background=bg, foreground=fg)
                except Exception:
                    pass
            # A little more breathing room reads more like a modern data grid.
            try:
                style_name = str(tree.cget('style') or 'Treeview')
                style = M.ttk.Style(tree)
                style.configure(style_name, rowheight=30)
                # Strong neutral selection so selection does not look like status.
                if dark:
                    style.map(style_name,
                              background=[('selected', '#315A7D')],
                              foreground=[('selected', '#FFFFFF')])
                else:
                    style.map(style_name,
                              background=[('selected', '#CFE4F6')],
                              foreground=[('selected', '#102A3D')])
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
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass
        walk(app)

    # Theme changes can overwrite Treeview tags/styles; reapply afterward.
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
        # Run after all previous delayed resize hooks have been installed.
        try:self.after(1450, lambda:detach_hidden_pages(self))
        except Exception:pass
        try:self.after(1550, lambda:apply_modern_palette(self))
        except Exception:pass
        return result
    M.App.__init__ = init

    # Reapply modern palette after common refreshes that can recreate/configure rows.
    for refresh_name in ('refresh_dash','refresh_actions','refresh_requests','refresh_offers','refresh_tasks','refresh_projects','refresh_people','refresh_companies','refresh_all'):
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
                        widget.insert('end', '\n\nMODERN UI + RESIZE 6.0.28\nHlavní stránky už nejsou všechny současně aktivní v grid layoutu. Při přepnutí se předchozí stránka geometricky odpojí a nová se zobrazí, takže při ruční změně velikosti hlavního okna Tk přepočítává jen aktuální stránku. Stavové barvy používají modernější tlumenou paletu: modrá pro rozpracováno, tyrkysová pro připraveno/nabídku, jantarová pro čekání, zelená pro hotovo a jemná vínová pro zrušeno. Výběr řádku má samostatnou neutrální barvu.')
                        widget.configure(state='disabled')
                    for child in widget.winfo_children():walk(child)
                walk(page)
            except Exception:pass
            return result
        M.App.build_help = help_page
    except Exception:
        pass
