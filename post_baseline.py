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
            if not tree.winfo_exists():
                return
            cols=list(tree.cget('columns'))
            if not cols:
                return

            # Keep the compact/date/status fields fixed and let the final
            # descriptive column absorb all spare room. Prefer Poznámka, which
            # is the natural long-text column on the Opportunities tab.
            target='Poznámka' if 'Poznámka' in cols else None
            if target is None:
                compact={'Stav','Přijato','Deadline','Datum','ID','Počet','Nabídky'}
                for c in reversed(cols):
                    if c not in compact:
                        target=c
                        break
            if target is None:
                target=cols[-1]

            # Capture preferred widths once, but do not inherit an accidentally
            # stretched width from an older runtime pass.
            if not hasattr(tree,'_post_base_widths'):
                tree._post_base_widths={c:int(tree.column(c,'width')) for c in cols}
            base=tree._post_base_widths
            for c in cols:
                if c not in base:
                    base[c]=int(tree.column(c,'width'))

            usable=max(1,int(tree.winfo_width())-4)
            fixed=sum(int(base[c]) for c in cols if c!=target)
            wanted=max(int(base[target]),usable-fixed)

            for c in cols:
                tree.column(c,
                            width=(wanted if c==target else int(base[c])),
                            stretch=(c==target))
            # Always return to the left edge after a refresh. This also avoids
            # a stale horizontal-scroll position making a blank strip visible.
            try:tree.xview_moveto(0)
            except Exception:pass
        except Exception:
            pass

    def _schedule_fit(app):
        try:
            app.after_idle(lambda:_fit_opportunities(app))
            app.after(80,lambda:_fit_opportunities(app))
        except Exception:
            pass

    # Apply after refreshes which can recreate rows/column geometry.
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

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.after(500,lambda:_fit_opportunities(self))
            self.after(1500,lambda:_fit_opportunities(self))
            tree=getattr(self,'action_tree',None)
            if tree is not None and not getattr(tree,'_post_opportunity_fit_bound',False):
                tree._post_opportunity_fit_bound=True
                pending={'id':None}
                def on_configure(e=None):
                    try:
                        if pending['id'] is not None:
                            self.after_cancel(pending['id'])
                    except Exception:pass
                    try:
                        pending['id']=self.after(40,lambda:_fit_opportunities(self))
                    except Exception:pass
                tree.bind('<Configure>',on_configure,add='+')
        except Exception:
            pass
        return r
    M.App.__init__=init
