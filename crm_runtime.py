# TURTO Zakazky CRM - stable runtime integrations
# v6.0: multi-PC foundation, ADMIN controls, audit history and central settings.
import os, sys, time, shutil, threading, subprocess, json, hashlib, socket
from pathlib import Path

APP_USER_MODEL_ID="TURTO.ZakazkyCRM"
GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
M=None
LEGACY_FILES=("v58_features.py","v581_cleanup.py","Spustit_Zakazky_v5.bat","Spustit_Zakazky_v5.vbs","Spustit_QT_PREVIEW.bat","Spustit_Qt_PREVIEW.bat","qt_preview_v5.py","AUDIT_v2.22.txt","DULEZITE_v2.8_JEDNORAZOVY_RESET.txt","latest.example.json","Vytvorit_EXE.bat","Vytvorit_manifest_aktualizace.py")

def _is_legacy_install_root(root):return root.name.lower().startswith("zakazkyapp_v") and root.parent.name.upper()=="APP_TURTO_CRM"
def _copy_program_tree(src,dst):
    skip=set(LEGACY_FILES)|{"__pycache__","v5_error.log","update_error.log","crm_features_error.log","crm_runtime_error.log"}
    for p in src.iterdir():
        if p.name in skip:continue
        t=dst/p.name
        if p.is_dir():shutil.copytree(p,t,dirs_exist_ok=True)
        elif p.is_file():t.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,t)
def _launch_stable_root(root):
    vbs=root/"Spustit_Zakazky.vbs";pyw=root/"ZakazkyCRM.pyw"
    if sys.platform.startswith("win") and vbs.exists():subprocess.Popen(["wscript.exe",str(vbs)],cwd=str(root))
    elif pyw.exists():subprocess.Popen([sys.executable,str(pyw)],cwd=str(root))
def _migrate_install_root_if_needed():
    root=Path(M.ROOT).resolve()
    if not _is_legacy_install_root(root):return False
    try:_copy_program_tree(root,root.parent);_launch_stable_root(root.parent);return True
    except Exception:return False
def _cleanup():
    root=Path(M.ROOT).resolve()
    for n in LEGACY_FILES:
        try:(root/n).unlink(missing_ok=True)
        except:pass
    try:shutil.rmtree(root/"__pycache__",ignore_errors=True)
    except:pass

def _set_windows_app_id():
    if sys.platform.startswith("win"):
        try:import ctypes;ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except:pass
def _set_window_icon(app):
    try:
        ico=Path(M.ROOT)/"turto_logo.ico"
        if ico.exists():app.iconbitmap(default=str(ico))
    except:pass

def _schedule_update_check(app):
    def run():
        try:
            # ADMIN controls this centrally through DB setting; default is enabled.
            enabled=str(M.get_setting("company_auto_updates","1")).strip().lower() not in ("0","false","no")
            if not enabled:return
            M.set_setting("update_source",GITHUB_UPDATE)
            if hasattr(app,"update_source"):app.update_source.set(GITHUB_UPDATE)
            app.check_for_updates(silent=True)
        except:pass
    try:app.after(4500,run)
    except:pass

def _hash_password(p):return hashlib.sha256(("TURTO-CRM|"+p).encode("utf-8")).hexdigest()
def _ensure_v6_schema():
    try:
        with M.db() as con:
            con.execute("CREATE TABLE IF NOT EXISTS crm_admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL)")
            con.execute("INSERT OR IGNORE INTO crm_admin(id,password_hash) VALUES(1,?)",(_hash_password("TURTO"),))
            con.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_history_created ON audit_history(created_at DESC)")
    except:pass

def audit(user,entity_type,entity_id,action,field_name="",old_value="",new_value="",undo_sql=""):
    try:
        with M.db() as con:con.execute("INSERT INTO audit_history(user_name,computer_name,entity_type,entity_id,action,field_name,old_value,new_value,undo_sql) VALUES(?,?,?,?,?,?,?,?,?)",(user or "",socket.gethostname(),entity_type or "",str(entity_id or ""),action or "",field_name or "",str(old_value or ""),str(new_value or ""),undo_sql or ""))
    except:pass

def _admin_login(parent):
    import tkinter as tk
    from tkinter import ttk,messagebox
    d=tk.Toplevel(parent);d.title("ADMIN");d.transient(parent);d.grab_set();d.resizable(False,False);ok={"v":False};pw=tk.StringVar()
    f=ttk.Frame(d,padding=18);f.pack(fill="both",expand=True);ttk.Label(f,text="Administrace TURTO CRM",style="Section.TLabel").pack(anchor="w");ttk.Label(f,text="Heslo ADMIN:").pack(anchor="w",pady=(12,3));e=ttk.Entry(f,textvariable=pw,show="•",width=32);e.pack(fill="x");e.focus_set()
    def login():
        try:
            with M.db() as con:r=con.execute("SELECT password_hash FROM crm_admin WHERE id=1").fetchone()
            if r and r[0]==_hash_password(pw.get()):ok["v"]=True;d.destroy()
            else:messagebox.showerror("ADMIN","Nesprávné heslo.",parent=d)
        except Exception as ex:messagebox.showerror("ADMIN",str(ex),parent=d)
    ttk.Button(f,text="Přihlásit",style="Accent.TButton",command=login).pack(anchor="e",pady=(12,0));e.bind("<Return>",lambda x:login());parent.wait_window(d);return ok["v"]

def open_admin(app):
    if not _admin_login(app):return
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    d=tk.Toplevel(app);d.title("ADMIN – TURTO CRM");M.enable_dialog_maximize(d,1050,720);d.transient(app)
    nb=ttk.Notebook(d);nb.pack(fill="both",expand=True,padx=12,pady=12)
    dbf=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16);nb.add(dbf,text="Databáze");nb.add(hist,text="HISTORIE");nb.add(upd,text="Aktualizace")
    ttk.Label(dbf,text="Centrální / síťová databáze",style="Section.TLabel").pack(anchor="w")
    ttk.Label(dbf,text="Připravuje klienty na společnou databázi dostupnou přes LAN/VPN. Před změnou se vždy vytvoří záloha.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
    path=tk.StringVar(value=M.get_setting("network_db_path","") or "");row=ttk.Frame(dbf);row.pack(fill="x");ttk.Entry(row,textvariable=path).pack(side="left",fill="x",expand=True)
    ttk.Button(row,text="Vybrat…",command=lambda:path.set(filedialog.asksaveasfilename(parent=d,title="Síťová databáze",defaultextension=".db",filetypes=[("SQLite databáze","*.db")]) or path.get())).pack(side="left",padx=(6,0))
    def save_path():M.set_setting("network_db_path",path.get().strip());messagebox.showinfo("ADMIN","Umístění síťové databáze bylo uloženo. Přepnutí datové vrstvy bude provedeno bezpečně po ověření dostupnosti a kompatibility.",parent=d)
    ttk.Button(dbf,text="Uložit umístění",style="Accent.TButton",command=save_path).pack(anchor="w",pady=10)
    ttk.Label(hist,text="Auditní historie",style="Section.TLabel").pack(anchor="w");cols=("Čas","Uživatel","PC","Objekt","Akce","Pole","Původní","Nová")
    tree=ttk.Treeview(hist,columns=cols,show="headings");[tree.heading(c,text=c) for c in cols];tree.pack(fill="both",expand=True,pady=(8,0))
    try:
        with M.db() as con:rows=con.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000").fetchall()
        for r in rows:tree.insert("","end",iid=str(r["id"]),values=(r["created_at"],r["user_name"],r["computer_name"],f"{r['entity_type']} {r['entity_id']}",r["action"],r["field_name"],r["old_value"],r["new_value"]))
    except:pass
    ttk.Label(upd,text="Firemní aktualizace",style="Section.TLabel").pack(anchor="w");auto=tk.BooleanVar(value=str(M.get_setting("company_auto_updates","1"))!="0")
    def save_upd():M.set_setting("company_auto_updates","1" if auto.get() else "0");messagebox.showinfo("ADMIN","Nastavení aktualizací uloženo.",parent=d)
    ttk.Checkbutton(upd,text="Automaticky kontrolovat aktualizace při startu na všech klientech",variable=auto).pack(anchor="w",pady=10);ttk.Button(upd,text="Uložit",style="Accent.TButton",command=save_upd).pack(anchor="w")

def _inject_admin_button(app):
    # Keep UI change conservative: add ADMIN command to Settings if its frame can be found; otherwise Ctrl+Shift+A always works.
    try:app.bind_all("<Control-Shift-A>",lambda e:open_admin(app))
    except:pass
    try:
        import tkinter.ttk as ttk
        target=getattr(app,"settings_frame",None)
        if target:ttk.Button(target,text="ADMIN",style="Toolbar.TButton",command=lambda:open_admin(app)).pack(anchor="e",pady=6)
    except:pass

def _ps_quote(v):return str(v).replace("'","''")
def create_windows_shortcuts(app):
    if not sys.platform.startswith("win"):return
    root=Path(M.ROOT).resolve();launcher=root/"ZakazkyCRM.pyw";ico=root/"turto_logo.ico";exe=Path(sys.executable).resolve();pyw=exe.with_name("pythonw.exe")
    if pyw.exists():exe=pyw
    desktop=Path(os.environ.get("USERPROFILE",str(Path.home())))/"Desktop"/"TURTO Zakázky CRM.lnk";start=Path(os.environ.get("APPDATA",""))/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"TURTO Zakázky CRM.lnk"
    script=f"$ws=New-Object -ComObject WScript.Shell; foreach($p in @('{_ps_quote(desktop)}','{_ps_quote(start)}')){{$s=$ws.CreateShortcut($p);$s.TargetPath='{_ps_quote(exe)}';$s.Arguments='\"{_ps_quote(launcher)}\"';$s.WorkingDirectory='{_ps_quote(root)}';$s.IconLocation='{_ps_quote(ico)},0';$s.Save()}}"
    try:subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",script],check=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except:pass

def apply(module):
    global M;M=module;_set_windows_app_id()
    if _migrate_install_root_if_needed():raise SystemExit(0)
    _cleanup();_ensure_v6_schema();module.App.create_desktop_shortcut=create_windows_shortcuts;module.App.open_admin=open_admin
    old=module.App.__init__
    def init(self,*a,**kw):
        r=old(self,*a,**kw);_set_window_icon(self);_inject_admin_button(self);_schedule_update_check(self);return r
    module.App.__init__=init
