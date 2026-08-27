# TURTO CRM 6.1+ active extension layer
#
# Since 6.1.5 all main Treeview tables use the same native ttk geometry model.
# Requests are the reference: one descriptive column stretches natively and no
# delayed/manual width animation is needed during tab switches.


def apply(M):
    """Apply changes introduced after the consolidated 6.1 baseline."""

    COMPACT={
        'Stav','Přijato','Deadline','Poptáno','Obdrženo','Datum','Zahájení','Dokončení',
        'ID','Počet','Nabídky','Měna','Ks','MJ','Příležitostí'
    }
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

    def tree_name(app,tree):
        for name in PREFERRED:
            if getattr(app,name,None) is tree:return name
        return ''

    def display_columns(tree):
        try:
            allcols=list(tree.cget('columns'))
            raw=list(tree.cget('displaycolumns'))
            if not raw or raw==['#all']:return allcols
            out=[]
            for c in raw:
                if str(c).isdigit():
                    i=int(c)
                    if 0<=i<len(allcols):out.append(allcols[i])
                elif c in allcols:out.append(c)
            return out or allcols
        except Exception:return []

    def choose_target(app,tree,cols):
        for c in PREFERRED.get(tree_name(app,tree),()):
            if c in cols:return c
        for c in reversed(cols):
            if str(c) not in COMPACT:return c
        return cols[-1] if cols else None

    def normalize_tree(app,tree):
        try:
            if tree is None or not tree.winfo_exists():return
            cols=display_columns(tree)
            if not cols:return
            target=choose_target(app,tree,cols)
            if not target:return

            # Save the construction widths once. These are preferred widths only;
            # ttk itself gets the spare horizontal area through stretch=True.
            if not hasattr(tree,'_native_design_widths'):
                d={}
                for c in cols:
                    try:w=int(tree.column(c,'width'))
                    except Exception:w=100
                    # Protect against a previously contaminated giant fitted width.
                    d[c]=min(w,500)
                tree._native_design_widths=d
            d=tree._native_design_widths
            for c in cols:
                if c not in d:
                    try:d[c]=min(int(tree.column(c,'width')),500)
                    except Exception:d[c]=100

            for c in cols:
                w=max(40,int(d[c]))
                tree.column(c,
                            width=w,
                            minwidth=(60 if c==target else min(w,60)),
                            stretch=(c==target))
            try:tree.xview_moveto(0.0)
            except Exception:pass
        except Exception:pass

    def walk(app,w):
        try:
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=='Treeview':normalize_tree(app,c)
                except Exception:pass
                walk(app,c)
        except Exception:pass

    def normalize_all(app):
        walk(app,app)

    # Standard main tables get the rule at construction time, before first paint.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k)
            normalize_tree(self,t)
            return t
        M.App.tree=tree

    # Directly created feature tables are normalized after refresh, synchronously.
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

    # No after_idle/after resize animation: the same native ttk rule is already
    # attached before a tab becomes visible.
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
