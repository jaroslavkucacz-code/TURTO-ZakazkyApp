# TURTO CRM 6.1+ active extension layer
#
# New changes after the 6.1 consolidation belong here (or in clearly named
# modules imported from here). The frozen 6.1 baseline is not edited for each
# small release. When this layer grows too much, create the next baseline.


def apply(M):
    """Apply changes introduced after the consolidated 6.1 baseline."""

    def _fit_opportunities(app):
        tree=getattr(app,'action_tree',None)
        if tree is None:
            return
        try:
            if not tree.winfo_exists() or not tree.winfo_ismapped():
                return
            cols=list(tree.cget('columns'))
            if not cols:
                return
            # This table is defined as:
            # Stav, Přijato, Deadline, Příležitost, Společnost, Obchodník,
            # Co se řeší, Poznámka. Poznámka is intentionally the fill column.
            target='Poznámka' if 'Poznámka' in cols else cols[-1]

            # Use the real design widths from the Opportunities tab instead of
            # widths previously mutated by generic table fitters.
            design=(120,90,90,280,200,160,230,220)
            if len(cols)==len(design):
                base={c:design[i] for i,c in enumerate(cols)}
            else:
                base={c:int(tree.column(c,'width')) for c in cols}
                base[target]=min(base.get(target,220),220)

            usable=max(1,int(tree.winfo_width())-6)
            fixed=sum(int(base[c]) for c in cols if c!=target)
            wanted=max(int(base[target]),usable-fixed)

            for c in cols:
                tree.column(c,width=(wanted if c==target else int(base[c])),stretch=False)

            # Older consolidated fitters may run after us. Keep their baseline in
            # sync so they preserve this exact geometry instead of reverting it.
            try:
                if hasattr(tree,'_v642_base_widths'):
                    for c in cols:
                        tree._v642_base_widths[c]=(wanted if c==target else int(base[c]))
            except Exception:
                pass
            try:
                tree._post_base_widths=dict(base)
                tree._post_base_widths[target]=wanted
            except Exception:
                pass
            try:tree.xview_moveto(0)
            except Exception:pass
        except Exception:
            pass

    def _schedule_fit(app):
        try:
            # Run after idle and again after legacy geometry passes have finished.
            app.after_idle(lambda:_fit_opportunities(app))
            app.after(120,lambda:_fit_opportunities(app))
            app.after(450,lambda:_fit_opportunities(app))
        except Exception:
            pass

    for name in ('refresh_actions','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):
            continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                _schedule_fit(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    # v642 also normalizes geometry in show_page; schedule our precise
    # Opportunities geometry after that wrapper returns.
    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k)
            _schedule_fit(self)
            return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            # The consolidated baseline has late table normalization passes at
            # startup, so the final pass must run after them as well.
            self.after(500,lambda:_fit_opportunities(self))
            self.after(1500,lambda:_fit_opportunities(self))
            self.after(2300,lambda:_fit_opportunities(self))
            tree=getattr(self,'action_tree',None)
            if tree is not None and not getattr(tree,'_post_opportunity_fit_bound',False):
                tree._post_opportunity_fit_bound=True
                pending={'id':None}
                def on_configure(e=None):
                    try:
                        if pending['id'] is not None:self.after_cancel(pending['id'])
                    except Exception:pass
                    try:pending['id']=self.after(90,lambda:_fit_opportunities(self))
                    except Exception:pass
                tree.bind('<Configure>',on_configure,add='+')
        except Exception:
            pass
        return r
    M.App.__init__=init
