# TURTO CRM 6.0.35 - default Actions sorting + reset on tab switch


def apply(M):
    def _action_name_column(tree):
        try:
            cols=list(tree.cget('columns'))
            for c in ('Akce','Název akce','Název','Příležitost'):
                if c in cols:return c
            # fallback: first text-like column
            return cols[0] if cols else None
        except Exception:
            return None

    def _sort_actions_default(app):
        tree=getattr(app,'action_tree',None)
        if tree is None:return
        try:
            col=_action_name_column(tree)
            if not col:return
            rows=list(tree.get_children(''))
            rows.sort(key=lambda iid:str(tree.set(iid,col) or '').strip().casefold())
            for pos,iid in enumerate(rows):tree.move(iid,'',pos)
            # reset any remembered interactive sort state so next header click
            # starts from the default state rather than an old direction.
            try:tree._sort_state={};tree._active_sort=None
            except Exception:pass
        except Exception:
            pass

    # Apply after normal Actions refreshes.
    old_refresh=getattr(M.App,'refresh_actions',None)
    if callable(old_refresh):
        def refresh_actions(self,*a,**k):
            r=old_refresh(self,*a,**k)
            try:self.after_idle(lambda:_sort_actions_default(self))
            except Exception:_sort_actions_default(self)
            return r
        M.App.refresh_actions=refresh_actions

    # When leaving/entering pages, reset Actions to its default alphabetical order.
    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,key,*a,**k):
            prev=getattr(self,'_v635_page',None)
            # If we are leaving Actions, normalize it immediately so returning
            # never restores a temporary user sort.
            if prev in ('actions','action','opportunities','opportunity') and prev!=key:
                _sort_actions_default(self)
            r=old_show(self,key,*a,**k)
            if key in ('actions','action','opportunities','opportunity'):
                try:self.after_idle(lambda:_sort_actions_default(self))
                except Exception:_sort_actions_default(self)
            self._v635_page=key
            return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(2200,lambda:_sort_actions_default(self))
        except Exception:pass
        return r
    M.App.__init__=init
