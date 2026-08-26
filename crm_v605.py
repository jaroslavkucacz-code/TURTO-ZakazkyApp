# TURTO CRM v6.0.5 incremental features
import datetime, json, os, re, socket
M=None

def _audit(entity,eid,action,field='',old='',new='',undo_sql=''):
    try:
        app=getattr(M,'_active_app',None);user=app.active_user.get() if app and hasattr(app,'active_user') else M.get_setting('active_user','')
        with M.db() as c:c.execute('INSERT INTO audit_history(user_name,computer_name,entity_type,entity_id,action,field_name,old_value,new_value,undo_sql) VALUES(?,?,?,?,?,?,?,?,?)',(user,socket.gethostname(),entity,str(eid),action,field,str(old or ''),str(new or ''),undo_sql))
    except Exception:pass

def _ensure():
    with M.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS recipient_usage(company_id INTEGER,person_id INTEGER,use_count INTEGER DEFAULT 0,last_used TEXT,PRIMARY KEY(company_id,person_id))')

def _patch_status_audit():
    # Detect status changes after the normal refresh path, independent of which quick-status UI was used.
    old=M.App.refresh_actions
    def refresh(self,*a,**k):
        before=getattr(self,'_v605_status_snapshot',{})
        r=old(self,*a,**k)
        try:
            with M.db() as c:now={x['id']:x['status'] for x in c.execute('SELECT id,status FROM actions')}
            if before:
                for aid,new in now.items():
                    oldv=before.get(aid)
                    if oldv is not None and oldv!=new:
                        safe=str(oldv).replace("'","''");_audit('Příležitost',aid,'Změna stavu','Stav',oldv,new,f"UPDATE actions SET status='{safe}' WHERE id={int(aid)}")
            self._v605_status_snapshot=now
        except Exception:pass
        return r
    M.App.refresh_actions=refresh

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

def _patch_mivo():
    old=M.App.refresh_mivo_requests
    def refresh(self,*a,**k):
        r=old(self,*a,**k)
        try:
            for iid in self.mivo_tree.get_children():
                vals=self.mivo_tree.item(iid,'values');txt=str(vals[2] if len(vals)>2 else '')
                m=re.search(r'(\d+)',txt);days=int(m.group(1)) if m else 0
                tag='status_late' if days>=22 else ('status_soon' if days>=15 else ('status_wait' if days>=8 else 'status_active'))
                self.mivo_tree.item(iid,tags=(tag,))
        except Exception:pass
        return r
    M.App.refresh_mivo_requests=refresh

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
    M.App.apply_theme=theme

def _patch_admin_history():
    old=M.open_admin if hasattr(M,'open_admin') else None
    # runtime open_admin already displays audit rows; add Undo button by wrapping after window construction is handled in next audit expansion.

def apply(module):
    global M;M=module;_ensure();_patch_status_audit();_patch_sort_reset();_patch_mivo();_patch_palette()
