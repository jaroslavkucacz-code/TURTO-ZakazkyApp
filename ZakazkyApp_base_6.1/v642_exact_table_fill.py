# TURTO CRM legacy v642 layer
# From 6.1.4 this module keeps only the requested default date sorting.
# All Treeview geometry is owned exclusively by post_baseline.py.
from datetime import datetime


def apply(M):
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
        _sort_tree(getattr(app,'action_tree',None),('Přijato','Datum přijetí','Přijetí'))
        _sort_tree(getattr(app,'request_tree',None),('Poptáno','Datum poptávky','Poptávka'))
        _sort_tree(getattr(app,'mivo_tree',None),('Poptáno','Datum poptávky','Poptávka'))

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
            self.after(700,lambda:_apply_default_sort(self))
            self.after(1800,lambda:_apply_default_sort(self))
        except Exception:pass
        return r
    M.App.__init__=init
