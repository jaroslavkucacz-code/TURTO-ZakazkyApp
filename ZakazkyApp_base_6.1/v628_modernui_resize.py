# TURTO CRM 6.0.29 - modern palette + active page/layout ownership


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
            try:
                tabs[previous].grid_remove()
            except Exception:
                pass

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
                    try:
                        page.grid()
                    except Exception:
                        pass
                else:
                    try:
                        page.grid_remove()
                    except Exception:
                        pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2) DASHBOARD + NAVIGATION COMPOSITION
    # ------------------------------------------------------------------
    def dashboard_layout(app):
        """Three-zone dashboard: opportunities | tasks/requests | quick actions."""
        try:
            tree = getattr(app, 'dash_tree', None)
            task_tree = getattr(app, 'dash_tasks_tree', None)
            req_tree = getattr(app, 'dash_requests_tree', None)
            if tree is None or task_tree is None or req_tree is None:
                return

            # Keep the underlying data columns for compatibility, but only show
            # the four fields useful in the compact dashboard overview.
            tree.configure(displaycolumns=('Stav','Deadline','Příležitost','Společnost'))
            for col, width in (
                ('Stav', 135), ('Deadline', 95),
                ('Příležitost', 300), ('Společnost', 245),
            ):
                try:
                    tree.column(col, width=width)
                except Exception:
                    pass

            left = tree.master.master
            tasks = task_tree.master
            requests = req_tree.master
            right = tasks.master
            body = left.master
            quick = next(
                (w for w in right.winfo_children() if w not in (tasks, requests)),
                None,
            )
            if quick is None:
                return

            # Children of `right` were originally packed vertically. Reuse the
            # same widgets/parents and change only their geometry manager.
            for widget in (quick, tasks, requests):
                try:
                    widget.pack_forget()
                except Exception:
                    pass
                try:
                    widget.grid_forget()
                except Exception:
                    pass

            body.columnconfigure(0, weight=4)
            body.columnconfigure(1, weight=5)
            body.rowconfigure(0, weight=1)
            right.columnconfigure(0, weight=4)
            right.columnconfigure(1, weight=2)
            right.rowconfigure(0, weight=1)
            right.rowconfigure(1, weight=1)

            tasks.grid(row=0, column=0, sticky='nsew', pady=(0,10))
            requests.grid(row=1, column=0, sticky='nsew')
            quick.grid(row=0, column=1, rowspan=2, sticky='new', padx=(10,0))
        except Exception:
            pass

    def reorder_navigation(app):
        """Keep Akce between Společnosti and Úkoly without rebuilding pages."""
        try:
            order = (
                'dash','actions','requests','mivo','offers',
                'companies','projects','tasks','people','help',
            )
            for key in order:
                button = app.nav.get(key)
                if button is not None:
                    button.pack_forget()
            for key in order:
                button = app.nav.get(key)
                if button is not None:
                    button.pack(side='left', padx=2, pady=(0,2))
        except Exception:
            pass

    old_build_dash = getattr(M.App, 'build_dash', None)
    if callable(old_build_dash):
        def build_dash_modern(self, *args, **kwargs):
            result = old_build_dash(self, *args, **kwargs)
            try:
                self.after_idle(lambda: dashboard_layout(self))
            except Exception:
                dashboard_layout(self)
            return result
        M.App.build_dash = build_dash_modern

    old_build = getattr(M.App, 'build', None)
    if callable(old_build):
        def build_modern(self, *args, **kwargs):
            result = old_build(self, *args, **kwargs)
            reorder_navigation(self)
            try:
                self.after_idle(lambda: dashboard_layout(self))
            except Exception:
                dashboard_layout(self)
            return result
        M.App.build = build_modern

    # ------------------------------------------------------------------
    # 3) OUTLOOK SELECTION FEEDBACK IN NABÍDKY
    # ------------------------------------------------------------------
    def walk_widgets(widget):
        try:
            yield widget
            for child in widget.winfo_children():
                yield from walk_widgets(child)
        except Exception:
            return

    def install_outlook_indicator(app):
        """Show what the Outlook button will actually import; no OLE Drop reads."""
        try:
            page = getattr(app, 'tabs', {}).get('offers')
            if page is None:
                return
            hint = None
            outlook_button = None
            for widget in walk_widgets(page):
                try:
                    text = str(widget.cget('text') or '')
                except Exception:
                    continue
                if 'PDF / MSG lze také přetáhnout' in text:
                    hint = widget
                if 'Načíst z Outlooku' in text and widget.winfo_class() in ('TButton','Button'):
                    outlook_button = widget
            if hint is None:
                return
            app._offer_outlook_selection_label = hint
            if outlook_button is not None:
                try:
                    outlook_button.configure(text='✉ Načíst vybrané z Outlooku')
                except Exception:
                    pass
        except Exception:
            return

        def refresh_selection():
            try:
                if not app.winfo_exists():
                    return
            except Exception:
                return

            label = getattr(app, '_offer_outlook_selection_label', None)
            if label is None:
                return

            # Poll only while Nabídky are visible. This is ordinary Outlook COM
            # automation in the Tk loop, never code inside the native OLE Drop callback.
            if getattr(app, '_current_page', None) == 'offers':
                count = None
                pythoncom = None
                refs = []
                try:
                    import os
                    if os.name == 'nt':
                        import pythoncom
                        import win32com.client
                        pythoncom.CoInitialize()
                        try:
                            try:
                                outlook = win32com.client.GetActiveObject('Outlook.Application')
                            except Exception:
                                outlook = None
                            refs.append(outlook)
                            explorer = outlook.ActiveExplorer() if outlook is not None else None
                            refs.append(explorer)
                            selection = explorer.Selection if explorer is not None else None
                            refs.append(selection)
                            count = int(selection.Count) if selection is not None else 0
                        finally:
                            refs.clear()
                            pythoncom.CoUninitialize()
                except Exception:
                    count = None

                try:
                    if count is None:
                        label.configure(
                            text='Outlook: výběr není dostupný. Vyberte zprávy v Outlooku a použijte tlačítko Načíst.'
                        )
                    elif count <= 0:
                        label.configure(
                            text='Outlook: není vybraná žádná zpráva. Přetažení se nesčítá; načte se aktuální výběr Outlooku.'
                        )
                    elif count == 1:
                        label.configure(
                            text='✓ Outlook: aktuálně vybrána 1 zpráva — právě ta se načte tlačítkem.'
                        )
                    else:
                        label.configure(
                            text=f'✓ Outlook: aktuálně vybráno {count} zpráv — právě ty se načtou tlačítkem.'
                        )
                except Exception:
                    pass

            try:
                app._offer_outlook_indicator_after = app.after(1600, refresh_selection)
            except Exception:
                pass

        refresh_selection()

    # ------------------------------------------------------------------
    # 4) STRONGER MODERN STATUS PALETTE
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
                try:
                    tree.tag_configure(tag, background=bg, foreground=fg)
                except Exception:
                    pass
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
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass
        walk(app)

    old_theme = getattr(M.App, 'apply_theme', None)
    if callable(old_theme):
        def apply_theme_modern(self, *args, **kwargs):
            result = old_theme(self, *args, **kwargs)
            try:
                self.after_idle(lambda:apply_modern_palette(self))
            except Exception:
                apply_modern_palette(self)
            return result
        M.App.apply_theme = apply_theme_modern

    old_init = M.App.__init__
    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after(1450, lambda:detach_hidden_pages(self))
        except Exception:
            pass
        try:
            self.after(1550, lambda:apply_modern_palette(self))
        except Exception:
            pass
        try:
            self.after(1750, lambda:dashboard_layout(self))
        except Exception:
            pass
        try:
            self.after(1900, lambda:install_outlook_indicator(self))
        except Exception:
            pass
        return result
    M.App.__init__ = init

    for refresh_name in ('refresh_dash','refresh_actions','refresh_requests','refresh_mivo_requests','refresh_offers','refresh_tasks','refresh_projects','refresh_people','refresh_companies','refresh_all'):
        old = getattr(M.App, refresh_name, None)
        if not callable(old):
            continue
        def make_wrapper(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                try:
                    self.after_idle(lambda:apply_modern_palette(self))
                except Exception:
                    pass
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
                    for child in widget.winfo_children():
                        walk(child)
                walk(page)
            except Exception:
                pass
            return result
        M.App.build_help = help_page
    except Exception:
        pass
