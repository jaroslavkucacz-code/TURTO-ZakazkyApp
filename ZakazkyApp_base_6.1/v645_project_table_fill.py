# TURTO CRM 6.0.45 - deterministic Actions table fill


def apply(M):
    def fit_projects(app):
        t=getattr(app,'project_tree',None)
        if t is None:return
        try:
            cols=list(t.cget('columns'))
            if not cols:return
            # Keep compact trailing counters compact. Use Generální dodavatel
            # (4th data column) as the elastic content column whenever present.
            target=cols[3] if len(cols)>=4 else cols[-1]
            # Stable preferred widths for the standard Actions table.
            preferred=[190,190,180,220,170,170,150,100]
            base={}
            for i,c in enumerate(cols):
                if i<len(preferred):base[c]=preferred[i]
                else:
                    try:base[c]=min(int(t.column(c,'width')),180)
                    except Exception:base[c]=120
            usable=max(1,int(t.winfo_width())-4)
            fixed=sum(base[c] for c in cols if c!=target)
            target_width=max(base[target],usable-fixed)
            for c in cols:
                t.column(c,width=(target_width if c==target else base[c]),stretch=False)
            # Always return the main Actions table to the left edge after a refresh
            # or tab switch; older elastic-width patches could leave a stale xview.
            try:t.xview_moveto(0.0)
            except Exception:pass
            # Replace contaminated width cache from earlier generic fit layer.
            try:t._v642_base_widths=dict(base)
            except Exception:pass
        except Exception:pass

    old_refresh=getattr(M.App,'refresh_projects',None)
    if callable(old_refresh):
        def refresh_projects(self,*a,**k):
            r=old_refresh(self,*a,**k)
            try:self.after_idle(lambda:fit_projects(self))
            except Exception:fit_projects(self)
            return r
        M.App.refresh_projects=refresh_projects

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k)
            try:self.after_idle(lambda:fit_projects(self))
            except Exception:pass
            return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.after(900,lambda:fit_projects(self))
            self.after(2200,lambda:fit_projects(self))
        except Exception:pass
        return r
    M.App.__init__=init
