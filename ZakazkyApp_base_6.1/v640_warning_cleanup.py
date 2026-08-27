# TURTO CRM 6.0.40 - remove warning triangles; bold only


def apply(M):
    WARNING_CHARS=("⚠️","⚠","▲","△")

    def _clean_tree(tree):
        if tree is None:return
        try:
            tree.tag_configure('warning_bold',font=('Calibri',10,'bold'))
        except Exception:pass
        try:
            for iid in tree.get_children(''):
                vals=list(tree.item(iid,'values') or ())
                had_warning=False
                changed=False
                for i,v in enumerate(vals):
                    s=str(v or '')
                    ns=s
                    for mark in WARNING_CHARS:
                        if mark in ns:
                            had_warning=True
                            ns=ns.replace(mark,'')
                    ns=' '.join(ns.split()) if ns!=s else ns
                    if ns!=s:
                        vals[i]=ns
                        changed=True
                tags=[t for t in (tree.item(iid,'tags') or ()) if t!='warning_bold']
                # Rows that previously carried the warning icon stay visually
                # emphasized, but only by bold text. Existing status/background
                # tags are preserved unchanged.
                if had_warning:
                    tags.append('warning_bold')
                if changed:
                    tree.item(iid,values=tuple(vals))
                tree.item(iid,tags=tuple(tags))
        except Exception:pass

    def _cleanup(app):
        for name in ('request_tree','mivo_tree'):
            _clean_tree(getattr(app,name,None))

    # Cleanup after normal refreshes. Use a few delayed passes because some
    # legacy refresh wrappers schedule their own row formatting shortly after
    # the refresh. No scroll/resize bindings are added.
    for name in ('refresh_requests','refresh_mivo_requests','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                for ms in (0,40,160,450):
                    try:self.after(ms,lambda s=self:_cleanup(s))
                    except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        for ms in (1200,2600,4200):
            try:self.after(ms,lambda s=self:_cleanup(s))
            except Exception:pass
        return r
    M.App.__init__=init
