# TURTO CRM 6.0.11 - audit expansion and ADMIN undo
import socket

def apply(M):
    try:
        with M.db() as c:
            c.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
    except:pass

    def audit(entity,eid,action,field='',old='',new='',undo_sql=''):
        try:
            app=getattr(M,'_active_app',None);user=app.active_user.get() if app and hasattr(app,'active_user') else M.get_setting('active_user','')
            with M.db() as c:c.execute("INSERT INTO audit_history(user_name,computer_name,entity_type,entity_id,action,field_name,old_value,new_value,undo_sql) VALUES(?,?,?,?,?,?,?,?,?)",(user,socket.gethostname(),entity,str(eid),action,field,str(old or ''),str(new or ''),undo_sql))
        except:pass

    # Expand audit beyond status: compare important opportunity fields on every refresh.
    old_refresh=M.App.refresh_actions
    def refresh(self,*a,**k):
        before=getattr(self,'_v611_action_snapshot',{})
        r=old_refresh(self,*a,**k)
        try:
            with M.db() as c:
                rows=c.execute("SELECT id,name,company_id,salesperson_id,deadline,status,products,note FROM actions").fetchall()
                now={x['id']:dict(x) for x in rows}
            if before:
                labels={'name':'Název','company_id':'Společnost','salesperson_id':'Obchodník','deadline':'Deadline','status':'Stav','products':'Co se řeší','note':'Poznámka'}
                for aid,nv in now.items():
                    ov=before.get(aid)
                    if not ov:continue
                    for key,label in labels.items():
                        a='' if ov.get(key) is None else ov.get(key);b='' if nv.get(key) is None else nv.get(key)
                        if str(a)!=str(b):
                            # status already has older audit patch; avoid duplicate status rows
                            if key=='status':continue
                            col=key;safe=str(a).replace("'","''")
                            if isinstance(a,(int,float)):sql=f"UPDATE actions SET {col}={a} WHERE id={int(aid)}"
                            elif a=='':sql=f"UPDATE actions SET {col}=NULL WHERE id={int(aid)}"
                            else:sql=f"UPDATE actions SET {col}='{safe}' WHERE id={int(aid)}"
                            audit('Příležitost',aid,'Úprava',label,a,b,sql)
            self._v611_action_snapshot=now
        except:pass
        return r
    M.App.refresh_actions=refresh

    # Tasks: capture create/edit/delete by snapshot refresh path when available.
    if hasattr(M.App,'refresh_tasks'):
        old_tasks=M.App.refresh_tasks
        def tasks(self,*a,**k):
            before=getattr(self,'_v611_task_snapshot',{})
            r=old_tasks(self,*a,**k)
            try:
                with M.db() as c:now={x['id']:dict(x) for x in c.execute("SELECT id,action_id,due_date,text,note,assigned_user,done FROM tasks")}
                if before:
                    for tid,nv in now.items():
                        ov=before.get(tid)
                        if not ov:audit('Úkol',tid,'Vytvoření','', '',nv.get('text',''));continue
                        for key,label in {'due_date':'Termín','text':'Úkol','note':'Poznámka','assigned_user':'Řeší','done':'Hotovo'}.items():
                            if str(ov.get(key,''))!=str(nv.get(key,'')):audit('Úkol',tid,'Úprava',label,ov.get(key,''),nv.get(key,''))
                    for tid,ov in before.items():
                        if tid not in now:audit('Úkol',tid,'Smazání','',ov.get('text',''),'')
                self._v611_task_snapshot=now
            except:pass
            return r
        M.App.refresh_tasks=tasks

    # Requests: capture status/date changes and creation/deletion.
    old_requests=M.App.refresh_requests
    def requests(self,*a,**k):
        before=getattr(self,'_v611_req_snapshot',{})
        r=old_requests(self,*a,**k)
        try:
            with M.db() as c:now={x['id']:dict(x) for x in c.execute("SELECT id,company_id,action_id,asked_date,received_date,item,note,assigned_user,archived FROM requests")}
            if before:
                for rid,nv in now.items():
                    ov=before.get(rid)
                    if not ov:audit('Poptávka',rid,'Vytvoření','', '',nv.get('item',''));continue
                    for key,label in {'asked_date':'Poptáno','received_date':'Obdrženo','item':'Poptáváno','note':'Poznámka','assigned_user':'Řeší','archived':'Archiv'}.items():
                        if str(ov.get(key,''))!=str(nv.get(key,'')):audit('Poptávka',rid,'Úprava',label,ov.get(key,''),nv.get(key,''))
                for rid,ov in before.items():
                    if rid not in now:audit('Poptávka',rid,'Smazání','',ov.get('item',''),'')
            self._v611_req_snapshot=now
        except:pass
        return r
    M.App.refresh_requests=requests
