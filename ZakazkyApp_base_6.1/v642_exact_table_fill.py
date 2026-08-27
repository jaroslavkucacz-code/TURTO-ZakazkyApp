# TURTO CRM 6.0.44 - exact right-edge fill + per-tab default date sorting
from datetime import datetime


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
            for c in cols:
                if c not in base:base[c]=int(tree.column(c,'width'))
            usable=max(1,int(tree.winfo_width())-4)
            fixed=sum(int(base.get(c,tree.column(c,'width'))) for c in cols if c!=target)
            target_base=int(base.get(target,tree.column(target,'width')))
            wanted=max(target_base,usable-fixed)
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

    def _parse_date(value):
        s=str(value or '').strip()
        for fmt in ('%d.%m.%Y','%Y-%m-%d','%d.%m.%y'):
            try:return datetime.strptime(s,fmt)
            except Exception:pass
        return datetime.min

    def _sort_tree(tree,candidates):
        if tree is None:return
        try:
            cols=list(tree.cget('columns'))
            col=next((c for c in candidates if c in cols),None)
            if not col:return
            rows=[(_parse_date(tree.set(iid,col)),iid) for iid in tree.get_children('')]
            rows.sort(key=lambda x:x[0],reverse=True)
            for pos,(_,iid) in enumerate(rows):tree.move(iid,'',pos)
        except Exception:pass

    def _apply_default_sort(app):
        # Příležitosti: datum přijetí, nejnovější nahoře.
        _sort_tree(getattr(app,'action_tree',None),('Přijato','Datum přijetí','Přijetí'))
        # Poptávky a MIVO: datum poptávky, nejnovější nahoře.
        _sort_tree(getattr(app,'request_tree',None),('Poptáno','Datum poptávky','Poptávka'))
        _sort_tree(getattr(app,'mivo_tree',None),('Poptáno','Datum poptávky','Poptávka'))

    def normalize(app):
        _walk(app)
        _apply_default_sort(app)
        try:app.after_idle(lambda:_walk(app))
        except Exception:pass

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

    # Re-apply the requested default after the relevant data refreshes too.
    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:_apply_default_sort(self))
                except Exception:_apply_default_sort(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.after(700,lambda:normalize(self))
            self.after(1800,lambda:normalize(self))
        except Exception:pass
        return r
    M.App.__init__=init
