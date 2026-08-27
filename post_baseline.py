# TURTO CRM 6.1+ active extension layer
# 6.1.9: deterministic widths, correct initial layout and safe context clicks.


def apply(M):
    COMPACT={'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení','ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí','Cena','Celkem'}

    def display_columns(tree):
        try:
            allcols=list(tree.cget('columns'));raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']:return allcols
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols):out.append(allcols[i])
                elif c in allcols:out.append(c)
            return out or allcols
        except Exception:return []

    def ensure_design(tree,cols):
        if not hasattr(tree,'_v617_design_widths'):
            d={}
            for c in cols:
                try:w=int(tree.column(c,'width'))
                except Exception:w=100
                d[c]=max(50,min(w,500))
            tree._v617_design_widths=d
        return tree._v617_design_widths

    def fit_tree(tree,available=None):
        try:
            cols=display_columns(tree)
            if not cols:return
            d=ensure_design(tree,cols)
            for c in cols:
                if c not in d:
                    try:d[c]=max(50,min(int(tree.column(c,'width')),500))
                    except Exception:d[c]=100
            flex=[c for c in cols if str(c) not in COMPACT] or [cols[-1]]
            if available is None:available=int(tree.winfo_width())
            # Width 1 is the Tk pre-layout placeholder. Do not use it to size columns.
            if int(available)<=10:return
            available=max(1,int(available)-4);preferred=sum(int(d[c]) for c in cols)
            q,r=divmod(max(0,available-preferred),len(flex))
            for c in cols:
                w=int(d[c])
                if c in flex:
                    i=flex.index(c);w+=q+(1 if i<r else 0)
                tree.column(c,width=w,minwidth=max(50,min(int(d[c]),120)),stretch=False)
            try:tree.xview_moveto(0.0)
            except Exception:pass
        except Exception:pass

    def install_tree(tree):
        try:
            if tree is None or not tree.winfo_exists():return
            cols=display_columns(tree)
            if not cols:return
            ensure_design(tree,cols)
            if not getattr(tree,'_v617_width_bound',False):
                tree._v617_width_bound=True
                tree.bind('<Configure>',lambda e:fit_tree(tree,getattr(e,'width',None)),add='+')
                tree.bind('<Map>',lambda e:fit_tree(tree),add='+')
            # Right-click/context actions are valid only over a real data row.
            if not getattr(tree,'_v619_context_guard',False):
                tree._v619_context_guard=True
                def context_guard(e):
                    try:
                        region=tree.identify_region(e.x,e.y)
                        row=tree.identify_row(e.y)
                        if region not in ('tree','cell') or not row:return 'break'
                    except Exception:return 'break'
                # Run before widget-specific right-click handlers.
                tree.bind('<Button-3>',context_guard,add=False)
            fit_tree(tree)
        except Exception:pass

    def walk(w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':install_tree(c)
                except Exception:pass
                walk(c)
        except Exception:pass

    def normalize_all(app):walk(app)

    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k);install_tree(t);return t
        M.App.tree=tree

    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_projects','refresh_offers','refresh_tasks','refresh_companies','refresh_people','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k);normalize_all(self);return r
            return wrapped
        setattr(M.App,name,make(old))

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k);normalize_all(self);return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            # Force Tk to resolve the maximized/main-window geometry before the
            # first visible table receives its final widths.
            self.update_idletasks()
            normalize_all(self)
            self.update_idletasks()
            normalize_all(self)
        except Exception:pass
        return r
    M.App.__init__=init
