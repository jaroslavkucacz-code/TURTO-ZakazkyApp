# TURTO CRM 6.0.15 - audit expansion + safe ADMIN undo incl. create/delete for simple records
import socket, datetime

def apply(M):
    try:
        with M.db() as c:c.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
    except:pass
    def q(v):
        if v is None or v=='':return 'NULL'
        if isinstance(v,(int,float)):return str(v)
        return "'"+str(v).replace("'","''")+"'"
    def qe(v):
        if v is None:return 'NULL'
        if isinstance(v,(int,float)):return str(v)
        return "'"+str(v).replace("'","''")+"'"
    def restore_sql(table,row):
        cols=list(row.keys());return f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(qe(row[c]) for c in cols)})"
    def audit(entity,eid,action,field='',old='',new='',undo_sql=''):
        try:
            app=getattr(M,'_active_app',None);user=app.active_user.get() if app and hasattr(app,'active_user') else M.get_setting('active_user','')
            with M.db() as c:c.execute("INSERT INTO audit_history(user_name,computer_name,entity_type,entity_id,action,field_name,old_value,new_value,undo_sql) VALUES(?,?,?,?,?,?,?,?,?)",(user,socket.gethostname(),entity,str(eid),action,field,str(old or ''),str(new or ''),undo_sql))
        except:pass

    old_refresh=M.App.refresh_actions
    def refresh(self,*a,**k):
        before=getattr(self,'_v611_action_snapshot',{});r=old_refresh(self,*a,**k)
        try:
            with M.db() as c:now={x['id']:dict(x) for x in c.execute("SELECT * FROM actions")}
            if before:
                labels={'name':'Název','company_id':'Společnost','salesperson_id':'Obchodník','deadline':'Deadline','products':'Co se řeší','note':'Poznámka'}
                for aid,nv in now.items():
                    ov=before.get(aid)
                    if not ov:continue
                    for key,label in labels.items():
                        a=ov.get(key);b=nv.get(key)
                        if str(a or '')!=str(b or ''):audit('Příležitost',aid,'Úprava',label,a,b,f"UPDATE actions SET {key}={q(a)} WHERE id={int(aid)}")
            self._v611_action_snapshot=now
        except:pass
        return r
    M.App.refresh_actions=refresh

    if hasattr(M.App,'refresh_tasks'):
        old_tasks=M.App.refresh_tasks
        def tasks(self,*a,**k):
            before=getattr(self,'_v611_task_snapshot',{});r=old_tasks(self,*a,**k)
            try:
                with M.db() as c:now={x['id']:dict(x) for x in c.execute("SELECT * FROM tasks")}
                if before:
                    for tid,nv in now.items():
                        ov=before.get(tid)
                        if not ov:
                            audit('Úkol',tid,'Vytvoření','', '',nv.get('text',''),f"DELETE FROM tasks WHERE id={int(tid)}")
                            continue
                        for key,label in {'due_date':'Termín','text':'Úkol','note':'Poznámka','assigned_user':'Řeší','done':'Hotovo'}.items():
                            a=ov.get(key);b=nv.get(key)
                            if str(a or '')!=str(b or ''):audit('Úkol',tid,'Úprava',label,a,b,f"UPDATE tasks SET {key}={q(a)} WHERE id={int(tid)}")
                    for tid,ov in before.items():
                        if tid not in now:audit('Úkol',tid,'Smazání','',ov.get('text',''),'',restore_sql('tasks',ov))
                self._v611_task_snapshot=now
            except:pass
            return r
        M.App.refresh_tasks=tasks

    old_requests=M.App.refresh_requests
    def requests(self,*a,**k):
        before=getattr(self,'_v611_req_snapshot',{});r=old_requests(self,*a,**k)
        try:
            with M.db() as c:now={x['id']:dict(x) for x in c.execute("SELECT * FROM requests")}
            if before:
                for rid,nv in now.items():
                    ov=before.get(rid)
                    if not ov:
                        audit('Poptávka',rid,'Vytvoření','', '',nv.get('item',''),f"DELETE FROM requests WHERE id={int(rid)}")
                        continue
                    for key,label in {'asked_date':'Poptáno','received_date':'Obdrženo','item':'Poptáváno','note':'Poznámka','assigned_user':'Řeší','archived':'Archiv'}.items():
                        a=ov.get(key);b=nv.get(key)
                        if str(a or '')!=str(b or ''):audit('Poptávka',rid,'Úprava',label,a,b,f"UPDATE requests SET {key}={q(a)} WHERE id={int(rid)}")
                for rid,ov in before.items():
                    if rid not in now:audit('Poptávka',rid,'Smazání','',ov.get('item',''),'',restore_sql('requests',ov))
            self._v611_req_snapshot=now
        except:pass
        return r
    M.App.refresh_requests=requests

    old_admin=getattr(M,'open_admin',None)
    if old_admin:
        def admin(app,auth=False):old_admin(app,auth)
        M.open_admin=admin

    def open_undo(app):
        import tkinter as tk
        from tkinter import ttk,messagebox
        d=tk.Toplevel(app);d.title('ADMIN – Vrátit změnu');M.enable_dialog_maximize(d,1180,760);d.transient(app);d.grab_set()
        ttk.Label(d,text='Vrátit auditovanou změnu',style='PageTitle.TLabel').pack(anchor='w',padx=14,pady=(14,4));ttk.Label(d,text='Lze vrátit pouze změny, pro které CRM bezpečně zná původní stav.',style='PageSubtitle.TLabel').pack(anchor='w',padx=14,pady=(0,8))
        cols=('Čas','Uživatel','Objekt','Pole','Původní','Nová','Stav');t=ttk.Treeview(d,columns=cols,show='headings');[t.heading(x,text=x) for x in cols];t.pack(fill='both',expand=True,padx=14,pady=8)
        def load():
            for i in t.get_children():t.delete(i)
            with M.db() as c:rows=c.execute("SELECT * FROM audit_history WHERE trim(coalesce(undo_sql,''))<>'' ORDER BY id DESC LIMIT 1000").fetchall()
            for x in rows:t.insert('', 'end', iid=str(x['id']),values=(x['created_at'],x['user_name'],f"{x['entity_type']} {x['entity_id']}",x['field_name'],x['old_value'],x['new_value'],'VRÁCENO' if x['undone'] else ''))
        def undo():
            s=t.selection()
            if not s:return messagebox.showinfo('Vrátit změnu','Vyberte změnu.',parent=d)
            iid=int(s[0])
            with M.db() as c:row=c.execute('SELECT * FROM audit_history WHERE id=?',(iid,)).fetchone()
            if not row or row['undone']:return messagebox.showinfo('Vrátit změnu','Tato změna už byla vrácena.',parent=d)
            if not row['undo_sql']:return messagebox.showinfo('Vrátit změnu','Tuto změnu nelze bezpečně vrátit.',parent=d)
            if not messagebox.askyesno('Vrátit změnu',f"Opravdu vrátit:\n{row['field_name']}: {row['new_value']} → {row['old_value']}?",parent=d):return
            try:
                with M.db() as c:c.execute('BEGIN IMMEDIATE');c.execute(row['undo_sql']);c.execute('UPDATE audit_history SET undone=1 WHERE id=?',(iid,));c.commit()
                audit(row['entity_type'],row['entity_id'],'ADMIN – vrácena změna',row['field_name'],row['new_value'],row['old_value'],'')
                try:app.refresh_all()
                except:pass
                load();messagebox.showinfo('Vrátit změnu','Změna byla vrácena a operace byla zapsána do historie.',parent=d)
            except Exception as e:messagebox.showerror('Vrátit změnu',f'Změnu se nepodařilo vrátit:\n{e}',parent=d)
        b=ttk.Frame(d);b.pack(fill='x',padx=14,pady=(0,14));ttk.Button(b,text='Vrátit vybranou změnu',style='Accent.TButton',command=undo).pack(side='right');ttk.Button(b,text='Obnovit',command=load).pack(side='right',padx=6);load()
    M.App.open_audit_undo=open_undo
