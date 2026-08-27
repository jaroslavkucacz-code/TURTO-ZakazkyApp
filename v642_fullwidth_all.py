# TURTO CRM 6.0.42 - full-width tables on all main tabs


def apply(M):
    short_cols={
        'id','nabídky','nabidky','počet','pocet','ks','měna','mena','stav','datum','přijato','prijato',
        'deadline','zahájení','zahajeni','dokončení','dokonceni','poptáno','poptano','obdrženo','obdrzeno'
    }

    def _target_column(tree):
        try: cols=list(tree.cget('columns'))
        except Exception: return None
        if not cols:return None
        # Prefer descriptive text columns close to the right edge.
        preferred=('Poznámka','Poznamka','Příjemci','Prijemci','Poptáváno','Poptavano','Co se řeší','Co se resi',
                   'Generální dodavatel','Generalni dodavatel','Investor','Adresa','Akce','Příležitost','Prilezitost',
                   'Společnost','Spolecnost','Dodavatel','Odběratel','Odberatel','Název Akce','Nazev Akce')
        for c in reversed(cols):
            if c in preferred:return c
        for c in reversed(cols):
            if str(c).strip().casefold() not in short_cols:return c
        return cols[-1]

    def _fullwidth(tree):
        try:
            cols=list(tree.cget('columns'))
            if not cols:return
            target=_target_column(tree)
            for c in cols:
                try: tree.column(c,stretch=(c==target))
                except Exception: pass
        except Exception: pass

    # Main app trees are created through App.tree. Patch the factory before App starts
    # so every tab automatically receives one stretchable descriptive column.
    old_tree=getattr(M.App,'tree',None)
    if callable(old_tree):
        def tree(self,*a,**k):
            t=old_tree(self,*a,**k)
            _fullwidth(t)
            return t
        M.App.tree=tree

    # Some newer/detail tabs create Treeview directly. Cover all Treeviews inside the
    # main application once UI construction is complete, without resize/scroll hooks.
    def _walk(widget):
        try:
            for ch in widget.winfo_children():
                try:
                    if ch.winfo_class()=='Treeview':_fullwidth(ch)
                except Exception:pass
                _walk(ch)
        except Exception:pass

    old_init=M.App.__init__
    def init(self,*a,**k):
        r=old_init(self,*a,**k)
        try:self.after_idle(lambda:_walk(self))
        except Exception:pass
        try:self.after(1200,lambda:_walk(self))
        except Exception:pass
        return r
    M.App.__init__=init
