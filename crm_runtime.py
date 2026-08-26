# TURTO Zakazky CRM - stable runtime integrations
# v6.0.3: robust Calibri text widgets + network DB health/locking diagnostics.
import os, sys, shutil, subprocess, hashlib, socket, json, sqlite3, datetime
from pathlib import Path
APP_USER_MODEL_ID="TURTO.ZakazkyCRM";GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main";M=None;NETWORK_MODE=False

def _hash_password(p):return hashlib.sha256(("TURTO-CRM|"+p).encode()).hexdigest()
def _cfg_path():return Path(M.DATA_ROOT)/"crm_client.json"
def _cfg():
    try:return json.loads(_cfg_path().read_text(encoding="utf-8"))
    except:return {"mode":"local","network_db":""}
def _save_cfg(mode,path=""):_cfg_path().write_text(json.dumps({"mode":mode,"network_db":path},ensure_ascii=False,indent=2),encoding="utf-8")
def _fatal(path):
    try:
        import tkinter as tk;from tkinter import messagebox
        r=tk.Tk();r.withdraw();messagebox.showerror("TURTO CRM – síťová databáze",f"Centrální databáze není dostupná:\n\n{path}\n\nZkontrolujte LAN/VPN. CRM se nepřepne na starou lokální kopii.");r.destroy()
    except:pass
    raise SystemExit(2)
def _activate(module):
    global NETWORK_MODE
    c=_cfg();NETWORK_MODE=str(c.get("mode","local")).lower()=="network"
    if not NETWORK_MODE:return
    p=Path(str(c.get("network_db","")).strip())
    if not p.exists():_fatal(p)
    try:
        x=sqlite3.connect(str(p),timeout=10);x.execute("SELECT count(*) FROM sqlite_master").fetchone();x.close()
    except:_fatal(p)
    module.DB=p;module.LIVE_DB=p
def _db_wrapper(module):
    def db():
        c=sqlite3.connect(str(module.DB),timeout=20);c.row_factory=sqlite3.Row
        try:c.create_collation("CZECH",module._czech_collate)
        except:pass
        c.execute("PRAGMA foreign_keys=ON");c.execute("PRAGMA busy_timeout=20000")
        try:c.execute("PRAGMA journal_mode=DELETE" if NETWORK_MODE else "PRAGMA journal_mode=WAL")
        except:pass
        return c
    module.db=db
def _ensure():
    with M.db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS crm_admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL)");c.execute("INSERT OR IGNORE INTO crm_admin VALUES(1,?)",(_hash_password("TURTO"),))
        c.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
        r=c.execute("SELECT id FROM users WHERE upper(trim(name))='ADMIN' LIMIT 1").fetchone()
        if r:c.execute("UPDATE users SET name='ADMIN',active=1 WHERE id=?",(r[0],))
        else:c.execute("INSERT INTO users(name,active) VALUES('ADMIN',1)")
def _login(parent):
    import tkinter as tk;from tkinter import ttk,messagebox
    d=tk.Toplevel(parent);d.title("Přihlášení ADMIN");d.transient(parent);d.grab_set();p=tk.StringVar();ok={"v":False};f=ttk.Frame(d,padding=20);f.pack();ttk.Label(f,text="ADMIN",style="Section.TLabel").pack(anchor="w");e=ttk.Entry(f,textvariable=p,show="•",width=32);e.pack(pady=10);e.focus_set()
    def go():
        with M.db() as c:r=c.execute("SELECT password_hash FROM crm_admin WHERE id=1").fetchone()
        if r and r[0]==_hash_password(p.get()):ok["v"]=True;d.destroy()
        else:messagebox.showerror("ADMIN","Nesprávné heslo.",parent=d)
    ttk.Button(f,text="Přihlásit",style="Accent.TButton",command=go).pack(anchor="e");e.bind("<Return>",lambda x:go());parent.wait_window(d);return ok["v"]
def _backup(src,dst):
    Path(dst).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(src)) as s,sqlite3.connect(str(dst)) as d:s.backup(d)
def _valid(path):
    try:
        c=sqlite3.connect(str(path),timeout=10);n={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};c.close();missing={"users","settings","actions","companies"}-n;return (not missing,"" if not missing else "Chybí: "+", ".join(missing))
    except Exception as e:return False,str(e)
def _restart(app):
    root=Path(M.ROOT);v=root/"Spustit_Zakazky.vbs";subprocess.Popen(["wscript.exe",str(v)],cwd=str(root)) if sys.platform.startswith("win") and v.exists() else None;app.destroy()
def open_admin(app,auth=False):
    if not auth and not _login(app):return
    import tkinter as tk;from tkinter import ttk,messagebox,filedialog
    d=tk.Toplevel(app);d.title("ADMIN – TURTO CRM");M.enable_dialog_maximize(d,1150,780);nb=ttk.Notebook(d);nb.pack(fill="both",expand=True,padx=12,pady=12)
    dbf=ttk.Frame(nb,padding=16);usr=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16)
    for w,t in ((dbf,"Databáze"),(usr,"Uživatelé"),(hist,"HISTORIE"),(upd,"Aktualizace")):nb.add(w,text=t)
    ttk.Label(dbf,text="Centrální databáze",style="Section.TLabel").pack(anchor="w");ttk.Label(dbf,text=f"Režim: {'SÍŤOVÝ' if NETWORK_MODE else 'LOKÁLNÍ'}   •   {M.DB}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
    p=tk.StringVar(value=_cfg().get("network_db","") or "");row=ttk.Frame(dbf);row.pack(fill="x");ttk.Entry(row,textvariable=p).pack(side="left",fill="x",expand=True);ttk.Button(row,text="Vybrat…",command=lambda:p.set(filedialog.askopenfilename(parent=d,filetypes=[("SQLite DB","*.db")]) or p.get())).pack(side="left",padx=6)
    b=ttk.Frame(dbf);b.pack(fill="x",pady=10)
    def create():
        target=p.get().strip()
        if not target:return messagebox.showwarning("ADMIN","Vyberte cestu.",parent=d)
        try:
            stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S");_backup(M.DB,Path(M.BACKUP_DIR)/f"pred_sitovou_migraci_{stamp}.db");_backup(M.DB,target);_save_cfg("network",target);messagebox.showinfo("ADMIN","Síťová DB vytvořena. CRM se restartuje.",parent=d);d.destroy();_restart(app)
        except Exception as e:messagebox.showerror("ADMIN",str(e),parent=d)
    def connect():
        ok,msg=_valid(p.get().strip())
        if not ok:return messagebox.showerror("ADMIN",msg,parent=d)
        _save_cfg("network",p.get().strip());d.destroy();_restart(app)
    ttk.Button(b,text="Vytvořit síťovou DB z aktuální",style="Accent.TButton",command=create).pack(side="left");ttk.Button(b,text="Připojit existující",command=connect).pack(side="left",padx=6);ttk.Button(b,text="Lokální režim",command=lambda:(_save_cfg("local",""),d.destroy(),_restart(app))).pack(side="left")
    # Network health check + write lock test without changing business data.
    def testnet():
        target=Path(p.get().strip() or M.DB)
        try:
            c=sqlite3.connect(str(target),timeout=5);c.execute("BEGIN IMMEDIATE");c.execute("ROLLBACK");c.close();messagebox.showinfo("Test databáze","Čtení i získání zapisovacího zámku proběhlo úspěšně.",parent=d)
        except Exception as e:messagebox.showerror("Test databáze",f"Test selhal:\n{e}",parent=d)
    ttk.Button(dbf,text="Otestovat síťovou databázi",command=testnet).pack(anchor="w",pady=(0,8));ttk.Label(dbf,text="Při nedostupné VPN se síťový klient nespustí lokálně. Tím nevznikají dvě paralelní verze dat.",style="PageSubtitle.TLabel").pack(anchor="w")
    ttk.Label(usr,text="Správa uživatelů",style="Section.TLabel").pack(anchor="w");ttk.Label(usr,text="Pouze ADMIN může přidávat, upravovat nebo odebírat uživatele.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,8));ttk.Button(usr,text="Spravovat uživatele…",style="Accent.TButton",command=app.manage_users).pack(anchor="w")
    ttk.Label(hist,text="Auditní HISTORIE",style="Section.TLabel").pack(anchor="w");cols=("Čas","Uživatel","PC","Objekt","Akce","Pole","Původní","Nová");t=ttk.Treeview(hist,columns=cols,show="headings");[t.heading(x,text=x) for x in cols];t.pack(fill="both",expand=True)
    with M.db() as c:rows=c.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000").fetchall()
    for x in rows:t.insert("","end",values=(x["created_at"],x["user_name"],x["computer_name"],f"{x['entity_type']} {x['entity_id']}",x["action"],x["field_name"],x["old_value"],x["new_value"]))
    auto=tk.BooleanVar(value=str(M.get_setting("company_auto_updates","1"))!="0");ttk.Label(upd,text="Firemní aktualizace",style="Section.TLabel").pack(anchor="w");ttk.Checkbutton(upd,text="Automaticky kontrolovat aktualizace při startu",variable=auto).pack(anchor="w",pady=10);ttk.Button(upd,text="Uložit",command=lambda:M.set_setting("company_auto_updates","1" if auto.get() else "0")).pack(anchor="w")
def _patch_users(module):
    sel=module.App.select_user;manage=module.App.manage_users
    def select(self,name):
        if str(name).strip().upper()=="ADMIN":
            prev=self.active_user.get()
            if not _login(self):self.active_user.set(prev);self.refresh_user_button();return
            self.active_user.set("ADMIN");module.set_setting("active_user","ADMIN");self.on_user_changed();self.after(100,lambda:open_admin(self,True));return
        return sel(self,name)
    def mgr(self,*a,**k):
        if self.active_user.get().strip().upper()!="ADMIN":return module.messagebox.showwarning("Uživatelé","Správu uživatelů může otevřít pouze ADMIN.",parent=self)
        try:return manage(self,*a,**k)
        finally:_ensure()
    def menu(self):
        m=module.tk.Menu(self,tearoff=0,font=("Calibri",11));
        with module.db() as c:users=[r["name"] for r in c.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        cur=self.active_user.get()
        for n in users:m.add_command(label=("✓ " if n==cur else "   ")+n,command=lambda x=n:self.select_user(x))
        if cur.strip().upper()=="ADMIN":m.add_separator();m.add_command(label="Administrace…",command=lambda:open_admin(self))
        try:m.tk_popup(self.user_button.winfo_rootx(),self.user_button.winfo_rooty()+self.user_button.winfo_height())
        finally:m.grab_release()
    module.App.select_user=select;module.App.manage_users=mgr;module.App.open_user_menu=menu
def _force_calibri(app):
    # Apply after dialogs/widgets are created too. Tk Text has its own font and ignored the previous ttk-only styling.
    import tkinter as tk
    def walk(w):
        try:
            if isinstance(w,tk.Text):w.configure(font=("Calibri",11))
            for c in w.winfo_children():walk(c)
        except:pass
    walk(app)
    # bind creation-heavy interactions; periodic lightweight sweep catches modal dialogs.
    try:app.after(700,lambda:_force_calibri(app))
    except:pass
def _updates(app):
    def run():
        try:
            if str(M.get_setting("company_auto_updates","1"))!="0":M.set_setting("update_source",GITHUB_UPDATE);app.check_for_updates(silent=True)
        except:pass
    app.after(4500,run)
def apply(module):
    global M;M=module;_activate(module);_db_wrapper(module);_ensure();_patch_users(module);module.App.open_admin=open_admin
    old=module.App.__init__
    def init(self,*a,**k):
        r=old(self,*a,**k);_force_calibri(self);_updates(self)
        try:self.footer_db.configure(text=f"Databáze: {'SÍŤOVÁ' if NETWORK_MODE else 'LOKÁLNÍ'} • {M.DB}")
        except:pass
        return r
    module.App.__init__=init
