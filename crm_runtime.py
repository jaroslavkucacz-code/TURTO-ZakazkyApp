# TURTO Zakazky CRM - stable runtime integrations
# v6.0.1: visible protected ADMIN user + multi-PC administration foundation.
import os, sys, shutil, subprocess, hashlib, socket
from pathlib import Path
APP_USER_MODEL_ID="TURTO.ZakazkyCRM";GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main";M=None

def _hash_password(p):return hashlib.sha256(("TURTO-CRM|"+p).encode()).hexdigest()
def _ensure_v6_schema():
    with M.db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS crm_admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL)")
        con.execute("INSERT OR IGNORE INTO crm_admin(id,password_hash) VALUES(1,?)",(_hash_password("TURTO"),))
        con.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
        # ADMIN is a real visible user, but protected from ordinary management.
        r=con.execute("SELECT id FROM users WHERE upper(trim(name))='ADMIN' LIMIT 1").fetchone()
        if r:con.execute("UPDATE users SET name='ADMIN',active=1 WHERE id=?",(r[0],))
        else:con.execute("INSERT INTO users(name,active) VALUES('ADMIN',1)")

def _admin_login(parent):
    import tkinter as tk
    from tkinter import ttk,messagebox
    d=tk.Toplevel(parent);d.title("Přihlášení ADMIN");d.transient(parent);d.grab_set();d.resizable(False,False);pw=tk.StringVar();ok={"v":False}
    f=ttk.Frame(d,padding=20);f.pack(fill="both",expand=True);ttk.Label(f,text="ADMIN",style="Section.TLabel").pack(anchor="w");ttk.Label(f,text="Zadejte heslo správce").pack(anchor="w",pady=(10,3));e=ttk.Entry(f,textvariable=pw,show="•",width=34);e.pack(fill="x");e.focus_set()
    def go():
        with M.db() as con:r=con.execute("SELECT password_hash FROM crm_admin WHERE id=1").fetchone()
        if r and r[0]==_hash_password(pw.get()):ok["v"]=True;d.destroy()
        else:messagebox.showerror("ADMIN","Nesprávné heslo.",parent=d)
    ttk.Button(f,text="Přihlásit",style="Accent.TButton",command=go).pack(anchor="e",pady=(12,0));e.bind("<Return>",lambda e:go());parent.wait_window(d);return ok["v"]

def open_admin(app,already_authenticated=False):
    if not already_authenticated and not _admin_login(app):return
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    d=tk.Toplevel(app);d.title("ADMIN – TURTO CRM");M.enable_dialog_maximize(d,1080,720);d.transient(app)
    nb=ttk.Notebook(d);nb.pack(fill="both",expand=True,padx=12,pady=12)
    dbf=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16);users=ttk.Frame(nb,padding=16)
    for w,t in ((dbf,"Databáze"),(users,"Uživatelé"),(hist,"HISTORIE"),(upd,"Aktualizace")):nb.add(w,text=t)
    ttk.Label(dbf,text="Centrální / síťová databáze",style="Section.TLabel").pack(anchor="w");ttk.Label(dbf,text="Společné umístění dostupné přes LAN/VPN. Přepnutí datové vrstvy doplníme v následujícím kroku.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
    path=tk.StringVar(value=M.get_setting("network_db_path","") or "");r=ttk.Frame(dbf);r.pack(fill="x");ttk.Entry(r,textvariable=path).pack(side="left",fill="x",expand=True);ttk.Button(r,text="Vybrat…",command=lambda:path.set(filedialog.asksaveasfilename(parent=d,defaultextension=".db",filetypes=[("SQLite DB","*.db")]) or path.get())).pack(side="left",padx=6)
    ttk.Button(dbf,text="Uložit umístění",style="Accent.TButton",command=lambda:(M.set_setting("network_db_path",path.get().strip()),messagebox.showinfo("ADMIN","Umístění uloženo.",parent=d))).pack(anchor="w",pady=10)
    ttk.Label(users,text="Správa uživatelů",style="Section.TLabel").pack(anchor="w");ttk.Label(users,text="ADMIN je systémový účet a nelze jej smazat ani přejmenovat.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,8))
    with M.db() as con:un=[x[0] for x in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
    ttk.Label(users,text="\n".join(un)).pack(anchor="w")
    ttk.Label(hist,text="Auditní HISTORIE",style="Section.TLabel").pack(anchor="w");cols=("Čas","Uživatel","PC","Objekt","Akce","Pole","Původní","Nová");tree=ttk.Treeview(hist,columns=cols,show="headings");[tree.heading(c,text=c) for c in cols];tree.pack(fill="both",expand=True,pady=(8,0))
    with M.db() as con:rows=con.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000").fetchall()
    for x in rows:tree.insert("","end",values=(x["created_at"],x["user_name"],x["computer_name"],f"{x['entity_type']} {x['entity_id']}",x["action"],x["field_name"],x["old_value"],x["new_value"]))
    auto=tk.BooleanVar(value=str(M.get_setting("company_auto_updates","1"))!="0");ttk.Label(upd,text="Firemní aktualizace",style="Section.TLabel").pack(anchor="w");ttk.Checkbutton(upd,text="Automaticky kontrolovat aktualizace při startu",variable=auto).pack(anchor="w",pady=10);ttk.Button(upd,text="Uložit",style="Accent.TButton",command=lambda:(M.set_setting("company_auto_updates","1" if auto.get() else "0"),messagebox.showinfo("ADMIN","Nastavení uloženo.",parent=d))).pack(anchor="w")

def _schedule_update_check(app):
    def run():
        try:
            if str(M.get_setting("company_auto_updates","1"))=="0":return
            M.set_setting("update_source",GITHUB_UPDATE);app.check_for_updates(silent=True)
        except:pass
    app.after(4500,run)
def _set_identity(app):
    try:
        if sys.platform.startswith("win"):
            import ctypes;ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        ico=Path(M.ROOT)/"turto_logo.ico"
        if ico.exists():app.iconbitmap(default=str(ico))
    except:pass

def _patch_users(module):
    # ADMIN selection always requires password. Cancel returns to previous user.
    original_select=module.App.select_user
    def select_user(self,name):
        if (name or "").strip().upper()=="ADMIN":
            previous=self.active_user.get().strip()
            if not _admin_login(self):
                self.active_user.set(previous);self.refresh_user_button();return
            module.set_setting("active_user","ADMIN");self.active_user.set("ADMIN");self.on_user_changed();self.after(100,lambda:open_admin(self,True));return
        return original_select(self,name)
    module.App.select_user=select_user
    # Keep ADMIN out of destructive ordinary user manager operations by restoring it after every manager close/refresh.
    original_manage=getattr(module.App,"manage_users",None)
    if original_manage:
        def manage(self,*a,**kw):
            try:return original_manage(self,*a,**kw)
            finally:_ensure_v6_schema()
        module.App.manage_users=manage

def create_windows_shortcuts(app):
    # Existing stable launcher remains valid; implementation intentionally unchanged.
    try:
        root=Path(M.ROOT);vbs=root/"Spustit_Zakazky.vbs"
        if sys.platform.startswith("win") and vbs.exists():
            desktop=Path(os.environ.get("USERPROFILE",str(Path.home())))/"Desktop"/"TURTO Zakázky CRM.lnk";ico=root/"turto_logo.ico"
            ps=f"$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut('{desktop}');$s.TargetPath='wscript.exe';$s.Arguments='\"{vbs}\"';$s.WorkingDirectory='{root}';$s.IconLocation='{ico},0';$s.Save()";subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except:pass

def apply(module):
    global M;M=module;_ensure_v6_schema();_patch_users(module);module.App.open_admin=open_admin;module.App.create_desktop_shortcut=create_windows_shortcuts
    old=module.App.__init__
    def init(self,*a,**kw):
        r=old(self,*a,**kw);_set_identity(self);_schedule_update_check(self);return r
    module.App.__init__=init
