# TURTO Zakazky CRM - stable runtime integrations
# v6.0.2: real network DB selection/migration, ADMIN-only user management, Calibri notes.
import os, sys, shutil, subprocess, hashlib, socket, json, sqlite3
from pathlib import Path
APP_USER_MODEL_ID="TURTO.ZakazkyCRM"
GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
M=None
CLIENT_CONFIG_NAME="crm_client.json"
NETWORK_MODE=False


def _hash_password(p):
    return hashlib.sha256(("TURTO-CRM|"+p).encode("utf-8")).hexdigest()


def _client_config_path():
    return Path(M.DATA_ROOT)/CLIENT_CONFIG_NAME


def _read_client_config():
    try:
        p=_client_config_path()
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"mode":"local"}
    except Exception:
        return {"mode":"local"}


def _write_client_config(mode="local",network_db=""):
    p=_client_config_path();p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({"mode":mode,"network_db":network_db},ensure_ascii=False,indent=2),encoding="utf-8")


def _fatal_network_error(path):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r=tk.Tk();r.withdraw()
        messagebox.showerror("TURTO CRM – síťová databáze",
            "Centrální databáze není dostupná.\n\n"
            f"{path}\n\nZkontrolujte připojení k firemní síti nebo VPN.\n"
            "Aplikace se z bezpečnostních důvodů nepřepne na starou lokální kopii.",parent=r)
        r.destroy()
    except Exception:pass
    raise SystemExit(2)


def _activate_configured_database(module):
    global NETWORK_MODE
    cfg=_read_client_config()
    if str(cfg.get("mode","")).lower()!="network":
        NETWORK_MODE=False;return
    raw=str(cfg.get("network_db","")).strip()
    if not raw:_fatal_network_error("Nezadána cesta")
    p=Path(raw)
    if not p.exists() or not p.is_file():_fatal_network_error(raw)
    try:
        c=sqlite3.connect(str(p),timeout=10);c.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone();c.close()
    except Exception:_fatal_network_error(raw)
    module.DB=p;module.LIVE_DB=p;NETWORK_MODE=True


def _install_db_wrapper(module):
    def network_aware_db():
        con=sqlite3.connect(str(module.DB),timeout=15)
        con.row_factory=sqlite3.Row
        try:con.create_collation("CZECH",module._czech_collate)
        except Exception:pass
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        # WAL is excellent locally but unsuitable on many SMB/NAS shares.
        # Shared DB uses rollback journal and a generous lock timeout.
        try:con.execute("PRAGMA journal_mode=DELETE" if NETWORK_MODE else "PRAGMA journal_mode=WAL")
        except Exception:pass
        return con
    module.db=network_aware_db


def _ensure_v6_schema():
    with M.db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS crm_admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL)")
        con.execute("INSERT OR IGNORE INTO crm_admin(id,password_hash) VALUES(1,?)",(_hash_password("TURTO"),))
        con.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_audit_history_created ON audit_history(created_at DESC)")
        r=con.execute("SELECT id FROM users WHERE upper(trim(name))='ADMIN' LIMIT 1").fetchone()
        if r:con.execute("UPDATE users SET name='ADMIN',active=1 WHERE id=?",(r[0],))
        else:con.execute("INSERT INTO users(name,active) VALUES('ADMIN',1)")


def _admin_login(parent):
    import tkinter as tk
    from tkinter import ttk,messagebox
    d=tk.Toplevel(parent);d.title("Přihlášení ADMIN");d.transient(parent);d.grab_set();d.resizable(False,False)
    pw=tk.StringVar();ok={"v":False};f=ttk.Frame(d,padding=20);f.pack(fill="both",expand=True)
    ttk.Label(f,text="ADMIN",style="Section.TLabel").pack(anchor="w")
    ttk.Label(f,text="Zadejte heslo správce").pack(anchor="w",pady=(10,3))
    e=ttk.Entry(f,textvariable=pw,show="•",width=34);e.pack(fill="x");e.focus_set()
    def go():
        with M.db() as con:r=con.execute("SELECT password_hash FROM crm_admin WHERE id=1").fetchone()
        if r and r[0]==_hash_password(pw.get()):ok["v"]=True;d.destroy()
        else:messagebox.showerror("ADMIN","Nesprávné heslo.",parent=d)
    ttk.Button(f,text="Přihlásit",style="Accent.TButton",command=go).pack(anchor="e",pady=(12,0));e.bind("<Return>",lambda e:go())
    parent.wait_window(d);return ok["v"]


def _validate_existing_db(path):
    p=Path(path)
    if not p.exists() or not p.is_file():return False,"Soubor neexistuje."
    try:
        con=sqlite3.connect(str(p),timeout=10)
        names={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        need={"users","settings","actions","companies"}
        missing=need-names
        return (not missing, "" if not missing else "Chybí tabulky: "+", ".join(sorted(missing)))
    except Exception as e:return False,str(e)


def _backup_database(src,dst):
    dst=Path(dst);dst.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(src),timeout=15) as s,sqlite3.connect(str(dst),timeout=15) as d:s.backup(d)


def _restart_app(app):
    root=Path(M.ROOT);vbs=root/"Spustit_Zakazky.vbs";pyw=root/"ZakazkyCRM.pyw"
    try:
        if sys.platform.startswith("win") and vbs.exists():subprocess.Popen(["wscript.exe",str(vbs)],cwd=str(root))
        else:subprocess.Popen([sys.executable,str(pyw)],cwd=str(root))
    finally:app.destroy()


def open_admin(app,already_authenticated=False):
    if not already_authenticated and not _admin_login(app):return
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    d=tk.Toplevel(app);d.title("ADMIN – TURTO CRM");M.enable_dialog_maximize(d,1120,760);d.transient(app)
    nb=ttk.Notebook(d);nb.pack(fill="both",expand=True,padx=12,pady=12)
    dbf=ttk.Frame(nb,padding=16);users=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16)
    for w,t in ((dbf,"Databáze"),(users,"Uživatelé"),(hist,"HISTORIE"),(upd,"Aktualizace")):nb.add(w,text=t)

    cfg=_read_client_config();mode=cfg.get("mode","local");network_path=cfg.get("network_db","")
    ttk.Label(dbf,text="Centrální / síťová databáze",style="Section.TLabel").pack(anchor="w")
    ttk.Label(dbf,text=("Aktivní režim: SÍŤOVÝ" if NETWORK_MODE else "Aktivní režim: LOKÁLNÍ")+f"   •   Databáze: {M.DB}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,12))
    ttk.Label(dbf,text="Síťová cesta (LAN / VPN / UNC):").pack(anchor="w")
    path=tk.StringVar(value=network_path or "");row=ttk.Frame(dbf);row.pack(fill="x",pady=(3,10));ttk.Entry(row,textvariable=path).pack(side="left",fill="x",expand=True)
    ttk.Button(row,text="Vybrat existující…",command=lambda:path.set(filedialog.askopenfilename(parent=d,filetypes=[("SQLite DB","*.db"),("Všechny soubory","*.*")]) or path.get())).pack(side="left",padx=(6,0))
    ttk.Button(row,text="Umístění nové…",command=lambda:path.set(filedialog.asksaveasfilename(parent=d,defaultextension=".db",filetypes=[("SQLite DB","*.db")]) or path.get())).pack(side="left",padx=(6,0))

    buttons=ttk.Frame(dbf);buttons.pack(fill="x",pady=(0,12))
    def create_network():
        target=path.get().strip()
        if not target:return messagebox.showwarning("ADMIN","Vyberte umístění nové síťové databáze.",parent=d)
        tp=Path(target)
        if tp.exists() and not messagebox.askyesno("ADMIN","Soubor již existuje. Přepsat ho aktuální databází?",parent=d):return
        try:
            # extra local safety backup before any migration
            stamp=__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')
            safe=Path(M.BACKUP_DIR)/f"pred_sitovou_migraci_{stamp}.db";_backup_database(M.DB,safe)
            _backup_database(M.DB,tp)
            ok,msg=_validate_existing_db(tp)
            if not ok:raise RuntimeError(msg)
            _write_client_config("network",str(tp))
            messagebox.showinfo("ADMIN","Síťová databáze byla vytvořena z aktuálních dat.\n\nAplikace se nyní restartuje a připojí k ní.",parent=d)
            d.destroy();_restart_app(app)
        except Exception as e:messagebox.showerror("ADMIN",f"Převod se nepodařil:\n{e}",parent=d)
    def connect_network():
        target=path.get().strip();ok,msg=_validate_existing_db(target)
        if not ok:return messagebox.showerror("ADMIN",f"Databázi nelze připojit:\n{msg}",parent=d)
        _write_client_config("network",target)
        messagebox.showinfo("ADMIN","Tento počítač bude používat vybranou síťovou databázi.\nAplikace se restartuje.",parent=d);d.destroy();_restart_app(app)
    def use_local():
        if not messagebox.askyesno("ADMIN","Přepnout tento počítač zpět na jeho lokální databázi?",parent=d):return
        _write_client_config("local","");messagebox.showinfo("ADMIN","Počítač bude znovu používat lokální databázi.\nAplikace se restartuje.",parent=d);d.destroy();_restart_app(app)
    ttk.Button(buttons,text="Vytvořit síťovou DB z aktuální",style="Accent.TButton",command=create_network).pack(side="left",padx=(0,6))
    ttk.Button(buttons,text="Připojit existující síťovou DB",command=connect_network).pack(side="left",padx=6)
    ttk.Button(buttons,text="Používat lokální DB",command=use_local).pack(side="left",padx=6)
    ttk.Label(dbf,text="Při nedostupné síti/VPN se CRM z bezpečnostních důvodů nespustí nad starou lokální kopií.",style="PageSubtitle.TLabel").pack(anchor="w")

    ttk.Label(users,text="Správa uživatelů",style="Section.TLabel").pack(anchor="w")
    ttk.Label(users,text="Uživatele smí přidávat, upravovat a odebírat pouze ADMIN. ADMIN je systémový účet.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
    ttk.Button(users,text="Otevřít správu uživatelů…",style="Accent.TButton",command=lambda:app.manage_users()).pack(anchor="w")

    ttk.Label(hist,text="Auditní HISTORIE",style="Section.TLabel").pack(anchor="w")
    cols=("Čas","Uživatel","PC","Objekt","Akce","Pole","Původní","Nová");tree=ttk.Treeview(hist,columns=cols,show="headings")
    for c in cols:tree.heading(c,text=c)
    tree.pack(fill="both",expand=True,pady=(8,0))
    with M.db() as con:rows=con.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000").fetchall()
    for x in rows:tree.insert("","end",values=(x["created_at"],x["user_name"],x["computer_name"],f"{x['entity_type']} {x['entity_id']}",x["action"],x["field_name"],x["old_value"],x["new_value"]))

    auto=tk.BooleanVar(value=str(M.get_setting("company_auto_updates","1"))!="0")
    ttk.Label(upd,text="Firemní aktualizace",style="Section.TLabel").pack(anchor="w")
    ttk.Checkbutton(upd,text="Automaticky kontrolovat aktualizace při startu",variable=auto).pack(anchor="w",pady=10)
    ttk.Button(upd,text="Uložit",style="Accent.TButton",command=lambda:(M.set_setting("company_auto_updates","1" if auto.get() else "0"),messagebox.showinfo("ADMIN","Nastavení uloženo do aktivní databáze.",parent=d))).pack(anchor="w")


def _schedule_update_check(app):
    def run():
        try:
            if str(M.get_setting("company_auto_updates","1"))=="0":return
            M.set_setting("update_source",GITHUB_UPDATE);app.check_for_updates(silent=True)
        except Exception:pass
    app.after(4500,run)


def _set_identity(app):
    try:
        if sys.platform.startswith("win"):
            import ctypes;ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        ico=Path(M.ROOT)/"turto_logo.ico"
        if ico.exists():app.iconbitmap(default=str(ico))
    except Exception:pass


def _patch_users(module):
    original_select=module.App.select_user
    original_manage=module.App.manage_users
    def select_user(self,name):
        if (name or "").strip().upper()=="ADMIN":
            previous=self.active_user.get().strip()
            if not _admin_login(self):self.active_user.set(previous);self.refresh_user_button();return
            module.set_setting("active_user","ADMIN");self.active_user.set("ADMIN");self.on_user_changed();self.after(100,lambda:open_admin(self,True));return
        return original_select(self,name)
    def manage_users(self,*a,**kw):
        if self.active_user.get().strip().upper()!="ADMIN":
            return module.messagebox.showwarning("Uživatelé","Správu uživatelů může otevřít pouze ADMIN.",parent=self)
        try:return original_manage(self,*a,**kw)
        finally:_ensure_v6_schema()
    def open_user_menu(self):
        menu=module.tk.Menu(self,tearoff=0,font=("Calibri",11))
        with module.db() as con:users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        current=self.active_user.get()
        for name in users:menu.add_command(label=("✓ " if name==current else "   ")+name,command=lambda n=name:self.select_user(n))
        # Ordinary users only choose identity. User management is ADMIN-only.
        if current.strip().upper()=="ADMIN":
            menu.add_separator();menu.add_command(label="Správa uživatelů…",command=self.manage_users)
        try:menu.tk_popup(self.user_button.winfo_rootx(),self.user_button.winfo_rooty()+self.user_button.winfo_height())
        finally:menu.grab_release()
    module.App.select_user=select_user;module.App.manage_users=manage_users;module.App.open_user_menu=open_user_menu


def create_windows_shortcuts(app):
    try:
        root=Path(M.ROOT);vbs=root/"Spustit_Zakazky.vbs"
        if sys.platform.startswith("win") and vbs.exists():
            desktop=Path(os.environ.get("USERPROFILE",str(Path.home())))/"Desktop"/"TURTO Zakázky CRM.lnk";ico=root/"turto_logo.ico"
            ps=f"$w=New-Object -ComObject WScript.Shell;$s=$w.CreateShortcut('{desktop}');$s.TargetPath='wscript.exe';$s.Arguments='\"{vbs}\"';$s.WorkingDirectory='{root}';$s.IconLocation='{ico},0';$s.Save()"
            subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except Exception:pass


def apply(module):
    global M;M=module
    _activate_configured_database(module)
    _install_db_wrapper(module)
    _ensure_v6_schema();_patch_users(module)
    module.App.open_admin=open_admin;module.App.create_desktop_shortcut=create_windows_shortcuts
    old=module.App.__init__
    def init(self,*a,**kw):
        # Notes and all multiline text controls use the application's preferred Calibri.
        try:self.option_add("*Text.Font","Calibri 10")
        except Exception:pass
        r=old(self,*a,**kw);_set_identity(self);_schedule_update_check(self)
        try:
            if hasattr(self,"footer_db"):
                self.footer_db.configure(text=("Databáze: SÍŤOVÁ • " if NETWORK_MODE else "Databáze: LOKÁLNÍ • ")+Path(M.DB).name)
        except Exception:pass
        return r
    module.App.__init__=init
