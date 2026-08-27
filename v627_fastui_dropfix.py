# TURTO CRM 6.0.27 - Fast UI, exact dashboard palette, native Outlook OLE drop
import os


def apply(M):
    # ------------------------------------------------------------------
    # 1) FAST PAGE SWITCHING
    # Replace the v6.0.26 WM_SETREDRAW wrapper completely. Pages are already
    # built at startup, so switch styles first and raise the prepared page last.
    # This avoids both the visible progressive build-up and the pause caused by
    # update_idletasks() while redraw was locked.
    # ------------------------------------------------------------------
    def show_page_fast(self, key):
        previous = getattr(self, '_current_page', None)
        if key not in getattr(self, 'tabs', {}):
            return
        try:
            for name, button in self.nav.items():
                button.configure(style='TopNavActive.TButton' if name == key else 'TopNav.TButton')
        except Exception:
            pass
        try:
            self.tabs[key].tkraise()
        except Exception:
            return
        self._current_page = key
        if previous != key:
            # Preserve the sort-reset behavior originally added in crm_v605.
            for name in ('action_tree','request_tree','mivo_tree','offer_tree','task_tree','project_tree','people_tree','company_tree'):
                try:
                    tree = getattr(self, name, None)
                    if tree is not None:
                        tree._sort_state = {}
                        tree._active_sort = None
                except Exception:
                    pass

    M.App.show_page = show_page_fast

    # ------------------------------------------------------------------
    # 2) LIGHTWEIGHT LIVE RESIZE
    # Do no custom Treeview work while Windows is delivering the stream of
    # <Configure> events from a border drag. Only after the main window settles
    # do filter alignment/date overlays update once.
    # ------------------------------------------------------------------
    def install_fast_resize(app):
        try:
            trees = []
            def walk(widget):
                try:
                    if isinstance(widget, M.ttk.Treeview):
                        trees.append(widget)
                    for child in widget.winfo_children():
                        walk(child)
                except Exception:
                    pass
            walk(app)
            for tree in trees:
                try:
                    tree.unbind('<Configure>')
                except Exception:
                    pass

            state = {'after': None}

            def settle():
                state['after'] = None
                # Only touch trees on the currently visible page.
                try:
                    page = app.tabs.get(getattr(app, '_current_page', ''))
                except Exception:
                    page = None
                if page is None:
                    return
                visible = []
                def collect(widget):
                    try:
                        if isinstance(widget, M.ttk.Treeview):
                            visible.append(widget)
                        for child in widget.winfo_children():
                            collect(child)
                    except Exception:
                        pass
                collect(page)
                for tree in visible:
                    try:
                        fn = getattr(tree, '_sync_filter_bar', None)
                        if callable(fn):
                            fn()
                    except Exception:
                        pass
                    try:
                        fn = getattr(tree, '_date_cell_redraw', None)
                        if callable(fn):
                            fn()
                    except Exception:
                        pass

            def root_cfg(event=None):
                # Ignore configure events from descendants; only main-window size.
                try:
                    if event is not None and event.widget is not app:
                        return
                except Exception:
                    pass
                try:
                    if state['after'] is not None:
                        app.after_cancel(state['after'])
                except Exception:
                    pass
                try:
                    state['after'] = app.after(120, settle)
                except Exception:
                    pass

            app.bind('<Configure>', root_cfg, add='+')
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 3) EXACT DASHBOARD STATUS PALETTE
    # v622 searched all cell text and also missed the actual 'dash' tab key.
    # Here the real Stav column decides the tag; no words in names/descriptions
    # can accidentally recolor a row.
    # ------------------------------------------------------------------
    STATUS_TAGS = {
        'rozpracováno': 'status_active',
        'rozpracovano': 'status_active',
        'připraveno': 'status_offer',
        'pripraveno': 'status_offer',
        'hotovo': 'status_done',
        'zrušeno': 'status_cancel',
        'zruseno': 'status_cancel',
    }

    def recolor_status_tree(tree):
        try:
            if not isinstance(tree, M.ttk.Treeview):
                return False
            columns = list(tree.cget('columns') or ())
            status_idx = None
            for idx, col in enumerate(columns):
                try:
                    heading = str(tree.heading(col, 'text') or '').strip().casefold()
                except Exception:
                    heading = str(col).strip().casefold()
                if heading == 'stav' or 'stav' in heading:
                    status_idx = idx
                    break
            if status_idx is None:
                return False
            for iid in tree.get_children(''):
                try:
                    values = tree.item(iid, 'values')
                    if status_idx >= len(values):
                        continue
                    status = str(values[status_idx] or '').strip().casefold()
                    tag = STATUS_TAGS.get(status)
                    if tag:
                        tree.item(iid, tags=(tag,))
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def recolor_dashboard(app):
        try:
            page = app.tabs.get('dash')
        except Exception:
            page = None
        if page is None:
            return
        def walk(widget):
            try:
                recolor_status_tree(widget)
                for child in widget.winfo_children():
                    walk(child)
            except Exception:
                pass
        walk(page)

    for refresh_name in ('refresh_dash','refresh_dashboard','refresh_all','refresh_actions'):
        old = getattr(M.App, refresh_name, None)
        if not callable(old):
            continue
        def make_wrapper(fn):
            def wrapped(self, *args, **kwargs):
                result = fn(self, *args, **kwargs)
                try:
                    self.after_idle(lambda: recolor_dashboard(self))
                except Exception:
                    recolor_dashboard(self)
                return result
            return wrapped
        setattr(M.App, refresh_name, make_wrapper(old))

    # ------------------------------------------------------------------
    # 4) NATIVE OUTLOOK OLE DROP TARGET
    # tkinterdnd2 handles real filesystem paths, but Outlook drags MailItems as
    # virtual Shell/OLE data (FileGroupDescriptor/FileContents). Register the Tk
    # top-level HWND directly with OLE. On a virtual Outlook drop we use the
    # already-hardened v625 Outlook COM selection import, which saves Unicode MSG
    # and feeds the same process_offer_msg() pipeline.
    # ------------------------------------------------------------------
    def install_native_outlook_drop(app):
        if os.name != 'nt':
            return False
        try:
            import pythoncom
            import win32clipboard
            import win32com.server.policy
            from win32comext.shell import shellcon
        except Exception as exc:
            app._v627_ole_drop_error = 'Chybí pywin32: ' + str(exc)
            return False

        try:
            fmt_w = win32clipboard.RegisterClipboardFormat('FileGroupDescriptorW')
            fmt_a = win32clipboard.RegisterClipboardFormat('FileGroupDescriptor')
        except Exception as exc:
            app._v627_ole_drop_error = str(exc)
            return False

        def has_virtual_mail(data_object):
            for fmt in (fmt_w, fmt_a):
                try:
                    data_object.QueryGetData((fmt, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL))
                    return True
                except Exception:
                    pass
            return False

        class OutlookDropTarget(win32com.server.policy.DesignatedWrapPolicy):
            _public_methods_ = ['DragEnter','DragOver','DragLeave','Drop']
            _com_interfaces_ = [pythoncom.IID_IDropTarget]

            def __init__(self, owner):
                self._wrap_(self)
                self.owner = owner
                self.accept = False

            def DragEnter(self, data_object, key_state, point, effect):
                self.accept = has_virtual_mail(data_object)
                return shellcon.DROPEFFECT_COPY if self.accept else shellcon.DROPEFFECT_NONE

            def DragOver(self, key_state, point, effect):
                return shellcon.DROPEFFECT_COPY if self.accept else shellcon.DROPEFFECT_NONE

            def DragLeave(self):
                self.accept = False

            def Drop(self, data_object, key_state, point, effect):
                ok = self.accept or has_virtual_mail(data_object)
                self.accept = False
                if ok:
                    # Execute import after returning from OLE Drop callback.
                    try:
                        self.owner.after(0, self.owner.import_selected_outlook_offer)
                    except Exception:
                        pass
                    return shellcon.DROPEFFECT_COPY
                return shellcon.DROPEFFECT_NONE

        try:
            # RegisterDragDrop requires OLE initialization on the window's UI thread.
            pythoncom.OleInitialize()
            target = OutlookDropTarget(app)
            wrapped = pythoncom.WrapObject(target, pythoncom.IID_IDropTarget, pythoncom.IID_IDropTarget)
            hwnd = int(app.winfo_id())
            pythoncom.RegisterDragDrop(hwnd, wrapped)
            # Keep strong references for the lifetime of the Tk window.
            app._v627_ole_target = target
            app._v627_ole_target_wrapped = wrapped
            app._v627_ole_hwnd = hwnd
            app._v627_ole_drop_error = ''
            return True
        except Exception as exc:
            app._v627_ole_drop_error = str(exc)
            return False

    old_init = M.App.__init__
    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        # v625/v626 install their resize handlers later; override them last.
        try:
            self.after(1150, lambda: install_fast_resize(self))
        except Exception:
            pass
        try:
            self.after_idle(lambda: recolor_dashboard(self))
        except Exception:
            pass
        # OLE registration must run on the Tk UI thread after HWND creation.
        try:
            self.after(1300, lambda: install_native_outlook_drop(self))
        except Exception:
            pass
        return result
    M.App.__init__ = init

    # Help note.
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
                        widget.insert('end', '\n\nFAST UI + OUTLOOK DROP 6.0.27\nPřepínání hlavních záložek už nepoužívá blokování WM_SETREDRAW ani update_idletasks; připravená stránka se zvedne až po změně navigačních stylů. Během živého resize se neprovádějí vlastní přepočty Treeview a dorovnání viditelné stránky proběhne jednou po skončení změny velikosti. Přehled aktivních příležitostí barví řádky výhradně podle skutečného sloupce Stav. Ve Windows je navíc hlavní okno registrováno jako nativní OLE drop target pro virtuální Outlook MailItem; po přetažení se zpráva převezme přes Outlook COM jako Unicode MSG a zpracuje stejným jádrem jako běžný MSG soubor.')
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
