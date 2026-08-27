# TURTO CRM 6.1+ active extension layer
#
# New changes after the 6.1 consolidation belong here.  Since 6.1.3 all main
# Treeview tables use one geometry manager instead of per-tab width fixes.


def apply(M):
    """Apply changes introduced after the consolidated 6.1 baseline."""

    COMPACT={
        'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení',
        'ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí'
    }
    # Natural fill columns for known main tables.  The first existing name wins.
    PREFERRED={
        'action_tree':('Poznámka','Co se řeší','Příležitost'),
        'request_tree':('Poznámka','Předmět','Akce','Společnost'),
        'mivo_tree':('Poznámka','Předmět','Akce','Společnost'),
        'project_tree':('Generální dodavatel','Investor','Adresa','Název Akce'),
        'offer_tree':('Název z nabídky','Dodavatel','Poptávka','Akce'),
        'task_tree':('Poznámka','Úkol','Popis','Akce'),
        'company_tree':('Adresa','Název','Společnost'),
        'people_tree':('Společnost','E-mail','Poznámka'),
    }

    def _tree_name(app,tree):
        for name in PREFERRED:
            if getattr(app,name,None) is tree:return name
        return ''

    def _display_columns(tree):
        try:
            allcols=list(tree.cget('columns'))
            dc=list(tree.cget('displaycolumns'))
            if not dc or dc==['#all']:return allcols
            out=[]
            for c in dc:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols):out.append(allcols[i])
                elif c in allcols:out.append(c)
            return out or allcols
        except Exception:return []

    def _target(app,tree,cols):
        name=_tree_name(app,tree)
        for c in PREFERRED.get(name,()):
            if c in cols:return c
        for c in reversed(cols):
            if str(c) not in COMPACT:return c
        return cols[-1] if cols else None

    def _capture_design(tree,cols):
        if hasattr(tree,'_layout_design_widths'):
            d=tree._layout_design_widths
            for c in cols:
                if c not in d:
                    try:d[c]=int(tree.column(c,'width'))
                    except Exception:d[c]=100
            return d
        # Prefer the legacy fitter's original baseline when it is available;
        # otherwise current widths are still the construction-time widths here.
        legacy=getattr(tree,'_v642_base_widths',None)
        d={}
        for c in cols:
            try:d[c]=int((legacy or {}).get(c,tree.column(c,'width')))
            except Exception:d[c]=100
        tree._layout_design_widths=d
        return d

    def _fit_tree(app,tree,available=None):
        try:
            if tree is None or not tree.winfo_exists():return
            cols=_display_columns(tree)
            if not cols:return
            target=_target(app,tree,cols)
            if not target:return
            design=_capture_design(tree,cols)

            # When the tree is hidden during a tab switch winfo_width() can still
            # contain the previous/stale geometry.  The caller can therefore pass
            # the Notebook's width and prepare the table before it becomes visible.
            if available is None:
                available=int(tree.winfo_width())
            available=max(1,int(available)-6)
            fixed=sum(int(design.get(c,100)) for c in cols if c!=target)
            wanted=max(int(design.get(target,100)),available-fixed)
            final={c:(wanted if c==target else int(design.get(c,100))) for c in cols}

            for c in cols:
                tree.column(c,width=final[c],stretch=False)

            # Synchronize the historical v642 fitter so a later legacy Configure
            # pass preserves exactly the same geometry instead of undoing it.
            try:
                if hasattr(tree,'_v642_base_widths'):
                    tree._v642_base_widths.update(final)
            except Exception:pass
            try:tree.xview_moveto(0)
            except Exception:pass
        except Exception:pass

    def _walk_trees(w):
        out=[]
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':out.append(c)
                except Exception:pass
                out.extend(_walk_trees(c))
        except Exception:pass
        return out

    def _fit_widget(app,w,available=None):
        for tree in _walk_trees(w):_fit_tree(app,tree,available)

    def _fit_all(app):
        # Visible tables use their real width; hidden main-tab tables are also
        # prepared from the containing Notebook width so they are ready before show.
        try:
            for tree in _walk_trees(app):
                width=None
                if not tree.winfo_ismapped():
                    p=tree
                    while p is not None:
                        try:p=p.master
                        except Exception:p=None
                        if p is not None:
                            try:
                                if p.winfo_class()=='TNotebook':
                                    width=max(1,int(p.winfo_width())-8);break
                            except Exception:pass
                _fit_tree(app,tree,width)
        except Exception:pass

    def _install_notebook_prefit(app,nb):
        if getattr(nb,'_layout_prefit_bound',False):return
        nb._layout_prefit_bound=True

        def before_click(e):
            # ButtonPress happens before ttk changes the selected tab.  Prepare
            # the destination page now, eliminating the one-frame white flash.
            try:
                idx=nb.index('@%d,%d'%(e.x,e.y))
                tabs=nb.tabs()
                if idx<0 or idx>=len(tabs):return
                page=nb.nametowidget(tabs[idx])
                _fit_widget(app,page,max(1,int(nb.winfo_width())-8))
            except Exception:pass

        def after_change(e=None):
            try:
                page=nb.nametowidget(nb.select())
                _fit_widget(app,page,max(1,int(nb.winfo_width())-8))
            except Exception:pass

        nb.bind('<ButtonPress-1>',before_click,add='+')
        nb.bind('<<NotebookTabChanged>>',after_change,add='+')

    def _install_everywhere(app,w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='TNotebook':_install_notebook_prefit(app,c)
                except Exception:pass
                _install_everywhere(app,c)
        except Exception:pass

    # Any refresh can change columns or run older normalization code. One common
    # final pass is cheap and keeps every tab on the same principle.
    refreshes=(
        'refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo',
        'refresh_projects','refresh_offers','refresh_tasks','refresh_companies',
        'refresh_people','refresh_all'
    )
    for name in refreshes:
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:_fit_all(self)
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            _install_everywhere(self,self)
            _fit_all(self)
            # Recalculate all hidden tabs whenever the main window size changes,
            # so a later tab click never starts from stale geometry.
            pending={'id':None}
            def root_configure(e=None):
                try:
                    if e is not None and e.widget is not self:return
                    if pending['id'] is not None:self.after_cancel(pending['id'])
                except Exception:pass
                try:pending['id']=self.after(25,lambda:_fit_all(self))
                except Exception:pass
            self.bind('<Configure>',root_configure,add='+')
            self.after(400,lambda:_fit_all(self))
            self.after(1200,lambda:_fit_all(self))
        except Exception:pass
        return r
    M.App.__init__=init
