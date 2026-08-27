# TURTO CRM 6.0.26 - smoother page switching and resize
import os


def apply(M):
    # ------------------------------------------------------------------
    # 1) Atomic page painting on Windows.
    # Tk/ttk can visibly repaint a complex stacked page widget-by-widget.
    # WM_SETREDRAW lets us perform the page raise + nav style changes first
    # and then paint the completed state in one redraw pass.
    # ------------------------------------------------------------------
    old_show = M.App.show_page

    def show_page_smooth(self, key):
        if getattr(self, "_v626_switching", False):
            return old_show(self, key)

        previous = getattr(self, "_current_page", None)
        if previous == key:
            return old_show(self, key)

        self._v626_switching = True
        redraw_locked = False
        user32 = None
        hwnd = None
        try:
            if os.name == "nt":
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    hwnd = int(self.winfo_id())
                    # WM_SETREDRAW = 0x000B
                    user32.SendMessageW(hwnd, 0x000B, 0, 0)
                    redraw_locked = True
                except Exception:
                    redraw_locked = False

            result = old_show(self, key)

            # Finish pending geometry/style work while painting is frozen.
            # This avoids the visible "frame -> filters -> tree" build-up.
            try:
                self.update_idletasks()
            except Exception:
                pass
            return result
        finally:
            if redraw_locked and user32 is not None and hwnd is not None:
                try:
                    user32.SendMessageW(hwnd, 0x000B, 1, 0)
                    # RedrawWindow: invalidate + erase + all children + update now
                    RDW_INVALIDATE = 0x0001
                    RDW_ERASE = 0x0004
                    RDW_ALLCHILDREN = 0x0080
                    RDW_UPDATENOW = 0x0100
                    user32.RedrawWindow(
                        hwnd, None, None,
                        RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW,
                    )
                except Exception:
                    try:
                        self.update_idletasks()
                    except Exception:
                        pass
            self._v626_switching = False

    M.App.show_page = show_page_smooth

    # ------------------------------------------------------------------
    # 2) Faster, split resize settling.
    # v6.0.25 used one 180 ms delayed callback for filter alignment and date
    # redraw. That reduced work but made the interface visibly "jump" after
    # resizing. Here geometry alignment settles quickly; heavier cell redraw
    # follows separately and still does not touch database refresh methods.
    # ------------------------------------------------------------------
    def optimize_tree_configures(app):
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
                    tree.unbind("<Configure>")
                    state = {"geom": None, "cells": None}

                    def on_cfg(event, t=tree, s=state):
                        try:
                            if s["geom"] is not None:
                                t.after_cancel(s["geom"])
                        except Exception:
                            pass
                        try:
                            if s["cells"] is not None:
                                t.after_cancel(s["cells"])
                        except Exception:
                            pass

                        def geom_finish():
                            s["geom"] = None
                            try:
                                fn = getattr(t, "_sync_filter_bar", None)
                                if callable(fn):
                                    fn()
                            except Exception:
                                pass

                        def cell_finish():
                            s["cells"] = None
                            try:
                                fn = getattr(t, "_date_cell_redraw", None)
                                if callable(fn):
                                    fn()
                            except Exception:
                                pass

                        try:
                            s["geom"] = t.after(45, geom_finish)
                        except Exception:
                            pass
                        try:
                            s["cells"] = t.after(95, cell_finish)
                        except Exception:
                            pass

                    tree.bind("<Configure>", on_cfg, add="+")
                except Exception:
                    pass
        except Exception:
            pass

    # v625 installs its resize bindings after 500 ms. Re-apply ours after it.
    old_init = M.App.__init__

    def init(self, *args, **kwargs):
        result = old_init(self, *args, **kwargs)
        try:
            self.after(850, lambda: optimize_tree_configures(self))
        except Exception:
            pass
        return result

    M.App.__init__ = init

    # ------------------------------------------------------------------
    # 3) Keep page switches free of accidental heavy refresh calls.
    # This layer intentionally does not call refresh_* methods. Existing data
    # refresh remains driven by edits/actions as before, not by visual switch.
    # ------------------------------------------------------------------

    try:
        old_help = M.App.build_help

        def help_page(self):
            result = old_help(self)
            try:
                import tkinter as tk
                page = self.tabs["help"]

                def walk(widget):
                    if isinstance(widget, tk.Text):
                        widget.configure(state="normal")
                        widget.insert(
                            "end",
                            "\n\nPLYNULOST 6.0.26\nPřepínání hlavních záložek se ve Windows vykreslí jako hotový stav v jednom kroku místo postupného překreslování jednotlivých prvků. Při změně velikosti okna se rychlé geometrické dorovnání tabulek provádí po 45 ms a náročnější pomocné překreslení buněk samostatně po 95 ms; databázová data se při resize nenačítají znovu.",
                        )
                        widget.configure(state="disabled")
                    for child in widget.winfo_children():
                        walk(child)

                walk(page)
            except Exception:
                pass
            return result

        M.App.build_help = help_page
    except Exception:
        pass
