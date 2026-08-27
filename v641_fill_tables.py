# TURTO CRM 6.0.41 - fill main tables to the right edge


def apply(M):
    # Main tables are created through App.tree(). Keep fixed widths as their
    # preferred/minimum layout, but let the final visible data column absorb
    # any otherwise empty horizontal space. This removes the white strip at
    # the right side when the window/table is wider than the column sum.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,parent,cols,widths,*a,**k):
            t=old_tree(self,parent,cols,widths,*a,**k)
            try:
                visible=list(t.cget('columns'))
                if visible:
                    for col in visible:
                        try:t.column(col,stretch=False)
                        except Exception:pass
                    # Last column fills free space. If a narrow numeric helper
                    # column such as Nabídky is appended later, older columns
                    # remain stable and the helper may explicitly disable stretch.
                    t.column(visible[-1],stretch=True)
            except Exception:pass
            return t
        M.App.tree=tree

    def normalize(app):
        # Re-apply to already-created primary trees after older feature layers
        # may have modified columns at runtime.
        for name in ('project_tree','action_tree','request_tree','people_tree','company_tree','task_tree','mivo_tree','offer_tree'):
            t=getattr(app,name,None)
            if t is None:continue
            try:
                cols=list(t.cget('columns'))
                if not cols:continue
                # Prefer the last substantial text column; keep known compact
                # counter columns fixed and stretch the preceding one instead.
                stretch_col=cols[-1]
                if stretch_col in ('Nabídky','Počet','ID') and len(cols)>1:
                    stretch_col=cols[-2]
                for c in cols:
                    t.column(c,stretch=(c==stretch_col))
            except Exception:pass

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after(1800,lambda:normalize(self))
        except Exception:pass
        return r
    M.App.__init__=init

    for name in ('refresh_projects','refresh_actions','refresh_requests','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:normalize(self))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))
