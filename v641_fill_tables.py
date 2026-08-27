# TURTO CRM 6.0.42 - fill all tab tables to the right edge


def apply(M):
    compact={'Nabídky','Počet','ID','Měna','Ks','MJ'}
    preferred=('Poznámka','Příjemci','Poptáváno','Co se řeší','Generální dodavatel','Investor','Adresa','Akce','Příležitost','Společnost','Dodavatel','Odběratel','Název Akce')

    def choose_col(t):
        try:cols=list(t.cget('columns'))
        except Exception:return None
        if not cols:return None
        # Prefer the right-most descriptive text column. Compact helper/count
        # columns stay fixed and do not absorb the empty area.
        for c in reversed(cols):
            if c in preferred:return c
        for c in reversed(cols):
            if c not in compact:return c
        return cols[-1]

    def fill(t):
        try:
            cols=list(t.cget('columns'))
            if not cols:return
            target=choose_col(t)
            for c in cols:
                try:t.column(c,stretch=(c==target))
                except Exception:pass
        except Exception:pass

    # Every standard main-table created after this patch automatically fills
    # the available width.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,parent,cols,widths,*a,**k):
            t=old_tree(self,parent,cols,widths,*a,**k)
            fill(t)
            return t
        M.App.tree=tree

    def walk(widget):
        # Cover Treeviews created directly by individual tabs/features as well,
        # not only the original named trees. No resize/scroll callbacks are
        # installed; native ttk stretch handles the available width smoothly.
        try:
            for child in widget.winfo_children():
                try:
                    if child.winfo_class()=='Treeview':fill(child)
                except Exception:pass
                walk(child)
        except Exception:pass

    def normalize(app):
        walk(app)

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after_idle(lambda:normalize(self))
        except Exception:pass
        try:self.after(1600,lambda:normalize(self))
        except Exception:pass
        return r
    M.App.__init__=init

    # Some tabs add helper columns during refresh. Re-normalize after business
    # refreshes only; never on scrolling or window resizing.
    for name in ('refresh_projects','refresh_actions','refresh_requests','refresh_companies','refresh_people','refresh_tasks','refresh_mivo_requests','refresh_offers','refresh_all'):
        old=getattr(M.App,name,None)
        if not callable(old):continue
        def make(fn):
            def wrapped(self,*a,**k):
                r=fn(self,*a,**k)
                try:self.after_idle(lambda:normalize(self))
                except Exception:pass
                return r
            return wrapped
        setattr(M.App,name,make(old))
