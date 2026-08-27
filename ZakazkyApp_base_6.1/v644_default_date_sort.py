# TURTO CRM 6.0.44 - default date sorting per tab
from datetime import datetime


def apply(M):
    def parse_date(value):
        s=str(value or '').strip()
        for fmt in ('%d.%m.%Y','%Y-%m-%d','%d.%m.%y'):
            try:return datetime.strptime(s,fmt)
            except Exception:pass
        return datetime.min

    def sort_tree(tree,candidates):
        if tree is None:return
        try:
            cols=list(tree.cget('columns'))
            col=next((c for c in candidates if c in cols),None)
            if not col:return
            rows=[]
            for iid in tree.get_children(''):
                rows.append((parse_date(tree.set(iid,col)),iid))
            # Newest first; empty/invalid dates stay at the bottom.
            rows.sort(key=lambda x:x[0],reverse=True)
            for pos,(_,iid) in enumerate(rows):tree.move(iid,'',pos)
        except Exception:pass

    def apply_defaults(app):
        # Opportunities = actions, sorted by received date.
        sort_tree(getattr(app,'action_tree',None),('Přijato','Datum přijetí','Přijetí'))
        # Requests and MIVO sorted by request/asked date.
        sort_tree(getattr(app,'request_tree',None),('Poptáno','Datum poptávky','Poptávka'))
        sort_tree(getattr(app,'mivo_tree',None),('Poptáno','Datum poptávky','Poptávka'))

    # Apply after the relevant refreshes so database/query order cannot override
    # the requested UI default.
    for name in ('refresh_actions','refresh_requests','refresh_mivo_requests','refresh_mivo','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:apply_defaults(self))
                except Exception:apply_defaults(self)
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:
            self.after(1200,lambda:apply_defaults(self))
            # Reset default ordering whenever the user changes the main tab.
            # Bind every Notebook owned by the main window; dialog notebooks are
            # not children of App and therefore are untouched.
            def bind_notebooks(w):
                try:
                    for c in w.winfo_children():
                        try:
                            if c.winfo_class()=='TNotebook':
                                c.bind('<<NotebookTabChanged>>',lambda e:self.after_idle(lambda:apply_defaults(self)),add='+')
                        except Exception:pass
                        bind_notebooks(c)
                except Exception:pass
            bind_notebooks(self)
        except Exception:pass
        return r
    M.App.__init__=init
