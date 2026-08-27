# TURTO CRM 6.0.22 - unify dashboard/current opportunities palette

def apply(M):
    """Use the same status colors in Overview / current opportunities as elsewhere."""

    def _status_tag(values):
        text=' '.join(str(v or '') for v in values).casefold()
        if any(x in text for x in ('zrušeno','zrušená','zrušené','archiv')):
            return 'status_cancel'
        if any(x in text for x in ('hotovo','hotová','dokončeno','dokončená')):
            return 'status_done'
        if any(x in text for x in ('připraveno','připravená','nabídka','nabídnuto')):
            return 'status_offer'
        if any(x in text for x in ('čeká','čekání','čekající')):
            return 'status_wait'
        return 'status_active'

    def _recolor_tree(tree):
        try:
            if not isinstance(tree,M.ttk.Treeview):return
            for iid in tree.get_children(''):
                try:tree.item(iid,tags=(_status_tag(tree.item(iid,'values')),))
                except Exception:pass
        except Exception:pass

    def _walk(widget):
        try:
            _recolor_tree(widget)
            for c in widget.winfo_children():_walk(c)
        except Exception:pass

    def _recolor_overview(app):
        # Prefer the actual Overview tab; fall back to known dashboard/current-opportunity widgets.
        try:
            for key in ('overview','dashboard','home'):
                p=getattr(app,'tabs',{}).get(key) if hasattr(app,'tabs') else None
                if p is not None:_walk(p)
        except Exception:pass
        for attr in ('dashboard_tree','overview_tree','home_tree','current_actions_tree','current_opportunities_tree','action_overview_tree','upcoming_tree'):
            try:_recolor_tree(getattr(app,attr,None))
            except Exception:pass

    # Reapply after every refresh path used by different generations of the app.
    for name in ('refresh_dash','refresh_dashboard','refresh_overview','refresh_home','refresh_all','refresh_actions'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(oldfn):
            def wrapped(self,*a,**k):
                r=oldfn(self,*a,**k)
                try:self.after_idle(lambda:_recolor_overview(self))
                except Exception:_recolor_overview(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    # Also recolor once after the whole UI has been created.
    old_init=M.App.__init__
    def init(self,*a,**k):
        old_init(self,*a,**k)
        try:self.after_idle(lambda:_recolor_overview(self))
        except Exception:pass
    M.App.__init__=init

    # Keep Help current.
    try:
        old_help=M.App.build_help
        def help_page(self):
            r=old_help(self)
            try:
                import tkinter as tk
                p=self.tabs['help']
                def walk(w):
                    if isinstance(w,tk.Text):
                        w.configure(state='normal')
                        w.insert('end','\n\nPŘEHLED 6.0.22\nPřehled aktuálních Příležitostí používá stejné stavové barvy jako seznam Příležitostí/Akcí a ostatní části CRM. Barvy se znovu aplikují po každém obnovení přehledu.')
                        w.configure(state='disabled')
                    for c in w.winfo_children():walk(c)
                walk(p)
            except Exception:pass
            return r
        M.App.build_help=help_page
    except Exception:pass
