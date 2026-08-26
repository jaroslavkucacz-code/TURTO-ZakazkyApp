# TURTO Zakazky CRM v5.8.1 UI cleanup
# Removes the duplicate FOCUS CRM visual block only; no database records are changed.

def apply(M):
    def remove_focus(root):
        try:
            for w in list(root.winfo_children()):
                remove_focus(w)
                try:
                    text=str(w.cget('text') or '').strip().casefold()
                except Exception:
                    text=''
                if 'focus crm' in text:
                    try:w.pack_forget()
                    except Exception:
                        try:w.grid_remove()
                        except Exception:
                            try:w.place_forget()
                            except Exception:pass
        except Exception:
            pass

    for name in ('refresh_dashboard','build_dashboard','refresh_all'):
        fn=getattr(M.App,name,None)
        if not fn:continue
        def make_wrapper(original):
            def wrapped(self,*a,**kw):
                result=original(self,*a,**kw)
                try:self.after_idle(remove_focus,self)
                except Exception:pass
                return result
            return wrapped
        setattr(M.App,name,make_wrapper(fn))

    old_init=M.App.__init__
    def init(self,*a,**kw):
        result=old_init(self,*a,**kw)
        try:self.after(150,remove_focus,self)
        except Exception:pass
        return result
    M.App.__init__=init
