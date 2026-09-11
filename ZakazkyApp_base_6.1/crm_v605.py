# TURTO CRM v6.0.5 incremental features
M=None

def _ensure():
    with M.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS recipient_usage(company_id INTEGER,person_id INTEGER,use_count INTEGER DEFAULT 0,last_used TEXT,PRIMARY KEY(company_id,person_id))')

# v611_audit is the single action snapshot owner. It now includes `status` and
# preserves the historical entity/action/field/undo contract for status changes
# (Příležitost / Změna stavu / Stav). The former v605 SELECT id,status snapshot
# is intentionally retired so each Příležitosti refresh reads actions once.

def _patch_sort_reset():
    old=M.App.show_page
    def show(self,k):
        prev=getattr(self,'_current_page',None);r=old(self,k)
        if prev!=k:
            for n in ('action_tree','request_tree','mivo_tree','offer_tree','task_tree','project_tree','people_tree','company_tree'):
                t=getattr(self,n,None)
                if t is not None:t._sort_state={};t._active_sort=None
        return r
    M.App.show_page=show

# v608_stability is the later owner of MIVO row state and the >10-day warning.
# The old v605 pass parsed the first number from the displayed date and recolored
# every MIVO row, only for v608 to overwrite those tags immediately afterwards.
# It is intentionally retired rather than kept as a duplicate full-table scan.

def _patch_palette():
    old=M.App.apply_theme
    def recolor(app):
        import tkinter.ttk as ttk
        dark='tmav' in app.theme.get().lower()
        offer=('#176b66','#e8fffc') if dark else ('#cfeee9','#15554f')
        def walk(w):
            try:
                if isinstance(w,ttk.Treeview):w.tag_configure('status_offer',background=offer[0],foreground=offer[1]);w.tag_configure('status_late',font=('Calibri',10,'bold'))
                for c in w.winfo_children():walk(c)
            except Exception:pass
        walk(app)
    def theme(self,*a,**k):r=old(self,*a,**k);self.after_idle(lambda:recolor(self));return r
    M.App.apply_theme=apply

def _patch_admin_history():
    old=M.open_admin if hasattr(M,'open_admin') else None
    # runtime open_admin already displays audit rows; add Undo button by wrapping after window construction is handled in next audit expansion.

def apply(module):
    global M;M=module;_ensure();_patch_sort_reset();_patch_palette()
