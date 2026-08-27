# TURTO CRM 6.0.42 - exact right-edge fill for every Treeview


def apply(M):
    COMPACT={'Nabídky','Počet','ID','Měna','Ks','MJ','Stav','Přijato','Deadline','Poptáno','Obdrženo','Zahájení','Dokončení','Datum'}

    def _choose_target(tree):
        try:
            cols=list(tree.cget('displaycolumns'))
            if not cols or cols==['#all']:
                cols=list(tree.cget('columns'))
            else:
                allcols=list(tree.cget('columns'))
                cols=[allcols[int(x)] if str(x).isdigit() else x for x in cols]
            if not cols:return None,[]
            # Prefer a real text/content column from the right. Compact counters,
            # dates and status fields stay at their normal width.
            target=None
            for c in reversed(cols):
                if str(c) not in COMPACT:
                    target=c;break
            if target is None:target=cols[-1]
            return target,cols
        except Exception:
            return None,[]

    def _fit(tree):
        try:
            if not tree.winfo_exists() or not tree.winfo_ismapped():return
            target,cols=_choose_target(tree)
            if not target or not cols:return
            if not hasattr(tree,'_v642_base_widths'):
                tree._v642_base_widths={c:int(tree.column(c,'width')) for c in cols}
            base=tree._v642_base_widths
            # New columns can be appended by feature modules after installation.
            for c in cols:
                if c not in base:base[c]=int(tree.column(c,'width'))
            usable=max(1,int(tree.winfo_width())-4)
            fixed=sum(int(base.get(c,tree.column(c,'width'))) for c in cols if c!=target)
            target_base=int(base.get(target,tree.column(target,'width')))
            wanted=max(target_base,usable-fixed)
            # Only one column absorbs spare room; widths remain deterministic.
            for c in cols:
                tree.column(c,width=(wanted if c==target else int(base.get(c,tree.column(c,'width')))),stretch=False)
        except Exception:
            pass

    def _install(tree):
        if tree is None:return
        try:
            if getattr(tree,'_v642_installed',False):
                _fit(tree);return
            tree._v642_installed=True
            tree._v642_fit_pending=False
            def schedule(e=None):
                if getattr(tree,'_v642_fit_pending',False):return
                tree._v642_fit_pending=True
                def run():
                    tree._v642_fit_pending=False
                    _fit(tree)
                try:tree.after_idle(run)
                except Exception:pass
            tree.bind('<Configure>',schedule,add='+')
            tree.after_idle(lambda:_fit(tree))
        except Exception:pass

    def _walk(w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':_install(c)
                except Exception:pass
                _walk(c)
        except Exception:pass

    def normalize(app):
        _walk(app)
        # second pass after geometry settles
        try:app.after_idle(lambda:_walk(app))
        except Exception:pass

    # Every Treeview created through the common factory gets the behavior
    # immediately; the recursive pass catches dialogs/older custom tabs too.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k);_install(t);return t
        M.App.tree=tree

    old_show=getattr(M.App,'show_page',None)
    if callable(old_show):
        def show_page(self,*a,**k):
            r=old_show(self,*a,**k)
            try:self.after_idle(lambda:normalize(self))
            except Exception:pass
            return r
        M.App.show_page=show_page

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.after(700,lambda:normalize(self))
            self.after(1800,lambda:normalize(self))
        except Exception:pass
        return r
    M.App.__init__=init
