# TURTO CRM 6.0.40 - overdue request emphasis without warning icons
from datetime import date, datetime


def apply(M):
    WARNING_CHARS=("⚠️","⚠","▲","△")

    def _parse_date(value):
        text=str(value or '').strip()
        for mark in WARNING_CHARS:
            text=text.replace(mark,'')
        text=' '.join(text.split())
        for fmt in ('%d.%m.%Y','%Y-%m-%d','%d.%m.%y'):
            try:return datetime.strptime(text,fmt).date()
            except Exception:pass
        return None

    def _is_overdue_waiting(tree,iid):
        """Directly derive 7+ day waiting state; do not depend on transient ⚠ text."""
        try:
            cols=set(tree.cget('columns') or ())
            if 'Stav' not in cols or 'Poptáno' not in cols:return False
            state=str(tree.set(iid,'Stav') or '').strip().casefold()
            if state not in ('čekám','cekam'):return False
            asked=_parse_date(tree.set(iid,'Poptáno'))
            return bool(asked and (date.today()-asked).days>=7)
        except Exception:
            return False

    def _clean_tree(tree):
        if tree is None:return
        try:
            tree.tag_configure('warning_bold',font=('Calibri',10,'bold'))
        except Exception:pass
        try:
            for iid in tree.get_children(''):
                vals=list(tree.item(iid,'values') or ())
                changed=False
                for i,v in enumerate(vals):
                    s=str(v or '')
                    ns=s
                    for mark in WARNING_CHARS:
                        ns=ns.replace(mark,'')
                    ns=' '.join(ns.split()) if ns!=s else ns
                    if ns!=s:
                        vals[i]=ns
                        changed=True
                if changed:
                    tree.item(iid,values=tuple(vals))

                tags=[t for t in (tree.item(iid,'tags') or ()) if t!='warning_bold']
                # Waiting requests older than 7 days are bold in both Poptávky
                # and MIVO. Existing status/background tags stay untouched.
                if _is_overdue_waiting(tree,iid):
                    tags.append('warning_bold')
                tree.item(iid,tags=tuple(tags))
        except Exception:pass

    def _cleanup(app):
        for name in ('request_tree','mivo_tree'):
            _clean_tree(getattr(app,name,None))

    # Cleanup after normal refreshes. Use delayed passes because older refresh
    # callbacks still decorate Poptáno briefly after the row is inserted.
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
