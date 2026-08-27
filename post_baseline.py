# TURTO CRM 6.1+ active extension layer
#
# Since 6.1.6 all main Treeview tables use the same native ttk width policy:
# compact/date/status/count columns stay fixed, all descriptive columns are
# allowed to stretch natively. This works on both narrow and very wide screens
# without delayed/manual resize passes or a white unused strip at the right.


def apply(M):
    """Apply changes introduced after the consolidated 6.1 baseline."""

    COMPACT={
        'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení',
        'ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'
    }

    def display_columns(tree):
        try:
            allcols=list(tree.cget('columns'))
            raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']:
                return allcols
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols):out.append(allcols[i])
                elif c in allcols:
                    out.append(c)
            return out or allcols
        except Exception:
            return []

    def normalize_tree(tree):
        try:
            if tree is None or not tree.winfo_exists():return
            cols=display_columns(tree)
            if not cols:return

            # Capture construction widths once. They remain the preferred/minimum
            # widths; ttk distributes any surplus width natively among descriptive
            # columns before the widget is painted.
            if not hasattr(tree,'_native_design_widths'):
                d={}
                for c in cols:
                    try:w=int(tree.column(c,'width'))
                    except Exception:w=100
                    d[c]=max(50,min(w,500))
                tree._native_design_widths=d
            d=tree._native_design_widths

            descriptive=[c for c in cols if str(c) not in COMPACT]
            # Every real table should have a descriptive field; if not, let the
            # final visible column absorb surplus rather than leave a white strip.
            if not descriptive:
                descriptive=[cols[-1]]

            for c in cols:
                if c not in d:
                    try:d[c]=max(50,min(int(tree.column(c,'width')),500))
                    except Exception:d[c]=100
                w=int(d[c])
                is_flex=c in descriptive
                # Keep meaningful minimum widths. On a narrow screen the sum can
                # exceed the viewport and the existing horizontal scrollbar takes
                # over; on a wide screen ttk expands all descriptive columns.
                minw=max(55,min(w,120 if is_flex else w))
                tree.column(c,width=w,minwidth=minw,stretch=is_flex)

            try:tree.xview_moveto(0.0)
            except Exception:pass
        except Exception:
            pass

    def walk(w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':normalize_tree(c)
                except Exception:pass
                walk(c)
        except Exception:pass

    def normalize_all(app):
        walk(app)

    # Apply at Treeview construction time so the first rendered frame already
    # has the final width policy; there is no after_idle resize animation.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k)
            normalize_tree(t)
            return t
        M.App.tree=tree

    # Feature modules may create or alter columns during a refresh. Re-apply the
    # same synchronous native rule, without manually calculating pixel widths.
    for name in (
        'refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo',
        'refresh_projects','refresh_offers','refresh_tasks','refresh_companies',
        'refresh_people','refresh_all'
    ):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                normalize_all(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k)
            normalize_all(self)
            return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:normalize_all(self)
        except Exception:pass
        return r
    M.App.__init__=init
