# TURTO Zakazky CRM - stable runtime integrations
# v6.0.4: per-PC last user, safer dialogs, taskbar identity, theme palettes, live update checks + notes.
import os, sys, subprocess, hashlib, json, sqlite3, datetime, urllib.request
from pathlib import Path
APP_USER_MODEL_ID="TURTO.ZakazkyCRM"
GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
M=None
NETWORK_MODE=False

# ---------- client config / DB ----------
def _cfg_path(): return Path(M.DATA_ROOT)/"crm_client.json"
def _cfg():
    try:return json.loads(_cfg_path().read_text(encoding="utf-8"))
    except:return {"mode":"local","network_db":"","last_user":""}
def _save_cfg(**changes):
    c=_cfg();c.update(changes);_cfg_path().parent.mkdir(parents=True,exist_ok=True);_cfg_path().write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")
def _fatal(path):
    try:
        import tkinter as tk;from tkinter import messagebox
        r=tk.Tk();r.withdraw();messagebox.showerror("TURTO CRM – síťová databáze",f"Centrální databáze není dostupná:\n\n{path}\n\nZkontrolujte LAN/VPN. CRM se z bezpečnostních důvodů nepřepne na lokální kopii.",parent=r);r.destroy()
    except:pass
    raise SystemExit(2)
def _activate(module):
    global NETWORK_MODE
    c=_cfg();NETWORK_MODE=str(c.get("mode","local")).lower()=="network"
    if not NETWORK_MODE:return
    p=Path(str(c.get("network_db","")).strip())
    if not p.exists() or not p.is_file():_fatal(p)
    try:
        x=sqlite3.connect(str(p),timeout=10);x.execute("SELECT count(*) FROM sqlite_master").fetchone();x.close()
    except Exception:_fatal(p)
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

def _hash_password(p):return hashlib.sha256(("TURTO-CRM|"+p).encode()).hexdigest()
def _ensure():
    with M.db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS crm_admin(id INTEGER PRIMARY KEY CHECK(id=1),password_hash TEXT NOT NULL)")
        c.execute("INSERT OR IGNORE INTO crm_admin VALUES(1,?)",(_hash_password("TURTO"),))
        c.execute("CREATE TABLE IF NOT EXISTS audit_history(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,user_name TEXT,computer_name TEXT,entity_type TEXT,entity_id TEXT,action TEXT,field_name TEXT,old_value TEXT,new_value TEXT,undo_sql TEXT,undone INTEGER DEFAULT 0)")
        r=c.execute("SELECT id FROM users WHERE upper(trim(name))='ADMIN' LIMIT 1").fetchone()
        if r:c.execute("UPDATE users SET name='ADMIN',active=1 WHERE id=?",(r[0],))
        else:c.execute("INSERT INTO users(name,active) VALUES('ADMIN',1)")

def _audit(entity_type,entity_id,action,field_name="",old_value="",new_value=""):
    try:
        user=getattr(getattr(M,"_active_app",None),"active_user",None)
        user=user.get() if user else M.get_setting("active_user","")
        with M.db() as c:c.execute("INSERT INTO audit_history(user_name,computer_name,entity_type,entity_id,action,field_name,old_value,new_value) VALUES(?,?,?,?,?,?,?,?)",(user,os.environ.get("COMPUTERNAME","") or __import__('socket').gethostname(),entity_type,str(entity_id or ""),action,field_name,str(old_value or ""),str(new_value or "")))
    except:pass

# ---------- ADMIN ----------
def _login(parent):
    import tkinter as tk;from tkinter import ttk,messagebox
    d=tk.Toplevel(parent);d.title("Přihlášení ADMIN");d.transient(parent);d.grab_set();p=tk.StringVar();ok={"v":False};f=ttk.Frame(d,padding=20);f.pack();ttk.Label(f,text="ADMIN",style="Section.TLabel").pack(anchor="w");ttk.Label(f,text="Heslo správce:").pack(anchor="w",pady=(10,3));e=ttk.Entry(f,textvariable=p,show="•",width=32);e.pack();e.focus_set()
    def go():
        with M.db() as c:r=c.execute("SELECT password_hash FROM crm_admin WHERE id=1").fetchone()
        if r and r[0]==_hash_password(p.get()):ok["v"]=True;d.destroy()
        else:messagebox.showerror("ADMIN","Nesprávné heslo.",parent=d)
    ttk.Button(f,text="Přihlásit",style="Accent.TButton",command=go).pack(anchor="e",pady=(12,0));e.bind("<Return>",lambda x:go());parent.wait_window(d);return ok["v"]
def _backup(src,dst):
    Path(dst).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(src)) as s,sqlite3.connect(str(dst)) as d:s.backup(d)
def _valid(path):
    try:
        p=Path(path)
        if not p.exists():return False,"Soubor neexistuje."
        c=sqlite3.connect(str(p),timeout=10);names={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")};c.close();missing={"users","settings","actions","companies"}-names
        return (not missing,"" if not missing else "Chybí tabulky: "+", ".join(sorted(missing)))
    except Exception as e:return False,str(e)
def _restart(app):
    root=Path(M.ROOT);v=root/"Spustit_Zakazky.vbs"
    if sys.platform.startswith("win") and v.exists():subprocess.Popen(["wscript.exe",str(v)],cwd=str(root))
    app.destroy()
def open_admin(app,auth=False):
    if not auth and not _login(app):return
    import tkinter as tk;from tkinter import ttk,messagebox,filedialog
    d=tk.Toplevel(app);d.title("ADMIN – TURTO CRM");M.enable_dialog_maximize(d,1150,780);d.transient(app)
    nb=ttk.Notebook(d);nb.pack(fill="both",expand=True,padx=12,pady=12)
    dbf=ttk.Frame(nb,padding=16);usr=ttk.Frame(nb,padding=16);hist=ttk.Frame(nb,padding=16);upd=ttk.Frame(nb,padding=16)
    for w,t in ((dbf,"Databáze"),(usr,"Uživatelé"),(hist,"HISTORIE"),(upd,"Aktualizace")):nb.add(w,text=t)
    ttk.Label(dbf,text="Centrální databáze",style="Section.TLabel").pack(anchor="w");ttk.Label(dbf,text=f"Režim: {'SÍŤOVÝ' if NETWORK_MODE else 'LOKÁLNÍ'}   •   {M.DB}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
    p=tk.StringVar(value=_cfg().get("network_db","") or "");row=ttk.Frame(dbf);row.pack(fill="x");entry=ttk.Entry(row,textvariable=p);entry.pack(side="left",fill="x",expand=True);ttk.Button(row,text="Vybrat…",command=lambda:p.set(filedialog.askopenfilename(parent=d,filetypes=[("SQLite DB","*.db"),("Všechny soubory","*.*")]) or p.get())).pack(side="left",padx=6)
    b=ttk.Frame(dbf);b.pack(fill="x",pady=10)
    def create():
        target=p.get().strip()
        if not target:return messagebox.showwarning("ADMIN","Vyberte síťovou cestu.",parent=d)
        try:
            stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S");_backup(M.DB,Path(M.BACKUP_DIR)/f"pred_sitovou_migraci_{stamp}.db");_backup(M.DB,target);_save_cfg(mode="network",network_db=target);_audit("database",target,"Vytvořena síťová DB");messagebox.showinfo("ADMIN","Síťová DB vytvořena. CRM se restartuje.",parent=d);d.destroy();_restart(app)
        except Exception as e:messagebox.showerror("ADMIN",str(e),parent=d)
    def connect():
        ok,msg=_valid(p.get().strip())
        if not ok:return messagebox.showerror("ADMIN",msg,parent=d)
        _save_cfg(mode="network",network_db=p.get().strip());_audit("database",p.get().strip(),"Připojena síťová DB");d.destroy();_restart(app)
    def local():_save_cfg(mode="local",network_db="");_audit("database","local","Přepnuto na lokální DB");d.destroy();_restart(app)
    ttk.Button(b,text="Vytvořit síťovou DB z aktuální",style="Accent.TButton",command=create).pack(side="left");ttk.Button(b,text="Připojit existující",command=connect).pack(side="left",padx=6);ttk.Button(b,text="Lokální režim",command=local).pack(side="left")
    test_btn=ttk.Button(dbf,text="Otestovat síťovou databázi");test_btn.pack(anchor="w",pady=(0,8))
    def testnet():
        target=p.get().strip()
        if not target:return messagebox.showwarning("Test databáze","Nejdřív vyberte konkrétní síťovou databázi.",parent=d)
        try:
            c=sqlite3.connect(target,timeout=5);c.execute("SELECT count(*) FROM sqlite_master").fetchone();c.execute("BEGIN IMMEDIATE");c.execute("ROLLBACK");c.close();messagebox.showinfo("Test databáze",f"Test proběhl úspěšně.\n\nDatabáze:\n{target}\n\nČtení i získání zapisovacího zámku je funkční.",parent=d)
        except Exception as e:messagebox.showerror("Test databáze",f"Test selhal pro:\n{target}\n\n{e}",parent=d)
    test_btn.configure(command=testnet,state="normal" if p.get().strip() else "disabled");p.trace_add("write",lambda *_:test_btn.configure(state="normal" if p.get().strip() else "disabled"))
    ttk.Label(dbf,text="Při nedostupné VPN se síťový klient nespustí lokálně. Tím nevznikají dvě paralelní verze dat.",style="PageSubtitle.TLabel").pack(anchor="w")
    ttk.Label(usr,text="Správa uživatelů",style="Section.TLabel").pack(anchor="w");ttk.Label(usr,text="Pouze ADMIN může přidávat, upravovat nebo odebírat uživatele.",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,8));ttk.Button(usr,text="Spravovat uživatele…",style="Accent.TButton",command=app.manage_users).pack(anchor="w")
    ttk.Label(hist,text="Auditní HISTORIE",style="Section.TLabel").pack(anchor="w");cols=("Čas","Uživatel","PC","Objekt","Akce","Pole","Původní","Nová");t=ttk.Treeview(hist,columns=cols,show="headings");[t.heading(x,text=x) for x in cols];t.pack(fill="both",expand=True)
    with M.db() as c:rows=c.execute("SELECT * FROM audit_history ORDER BY id DESC LIMIT 1000").fetchall()
    for x in rows:t.insert("","end",values=(x["created_at"],x["user_name"],x["computer_name"],f"{x['entity_type']} {x['entity_id']}",x["action"],x["field_name"],x["old_value"],x["new_value"]))
    auto=tk.BooleanVar(value=str(M.get_setting("company_auto_updates","1"))!="0");ttk.Label(upd,text="Firemní aktualizace",style="Section.TLabel").pack(anchor="w");ttk.Checkbutton(upd,text="Automaticky kontrolovat aktualizace při startu i během běhu aplikace",variable=auto).pack(anchor="w",pady=10);ttk.Label(upd,text="Kontrola během běhu probíhá přibližně každých 10 minut.",style="PageSubtitle.TLabel").pack(anchor="w");ttk.Button(upd,text="Uložit",command=lambda:M.set_setting("company_auto_updates","1" if auto.get() else "0")).pack(anchor="w",pady=8)

# ---------- users: local last-user per PC ----------
def _patch_users(module):
    original_select=module.App.select_user;original_manage=module.App.manage_users
    def select(self,name):
        name=str(name or "").strip()
        if name.upper()=="ADMIN":
            prev=self.active_user.get().strip()
            if not _login(self):self.active_user.set(prev);self.refresh_user_button();return
            self.active_user.set("ADMIN");module.set_setting("active_user","ADMIN");self.on_user_changed();self.after(100,lambda:open_admin(self,True));return
        r=original_select(self,name);_save_cfg(last_user=name);return r
    def mgr(self,*a,**k):
        if self.active_user.get().strip().upper()!="ADMIN":return module.messagebox.showwarning("Uživatelé","Správu uživatelů může otevřít pouze ADMIN.",parent=self)
        try:return original_manage(self,*a,**k)
        finally:_ensure()
    def menu(self):
        m=module.tk.Menu(self,tearoff=0,font=("Calibri",11))
        with module.db() as c:users=[r["name"] for r in c.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        cur=self.active_user.get()
        for n in users:m.add_command(label=("✓ " if n==cur else "   ")+n,command=lambda x=n:self.select_user(x))
        if cur.strip().upper()=="ADMIN":m.add_separator();m.add_command(label="Administrace…",command=lambda:open_admin(self))
        try:m.tk_popup(self.user_button.winfo_rootx(),self.user_button.winfo_rooty()+self.user_button.winfo_height())
        finally:m.grab_release()
    module.App.select_user=select;module.App.manage_users=mgr;module.App.open_user_menu=menu

def _restore_local_user(app):
    c=_cfg();last=str(c.get("last_user","")).strip()
    with M.db() as con:valid=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 AND upper(trim(name))<>'ADMIN' ORDER BY name COLLATE CZECH")]
    chosen=last if last in valid else (app.active_user.get().strip() if app.active_user.get().strip() in valid else (valid[0] if valid else "ADMIN"))
    if chosen.upper()=="ADMIN" and valid:chosen=valid[0]
    if chosen and chosen.upper()!="ADMIN":
        app.active_user.set(chosen);M.set_setting("active_user",chosen);_save_cfg(last_user=chosen);app.on_user_changed()

# ---------- fonts / dialogs / taskbar ----------
def _force_calibri(app):
    import tkinter as tk
    def walk(w):
        try:
            if isinstance(w,tk.Text):w.configure(font=("Calibri",11))
            for c in w.winfo_children():walk(c)
        except:pass
    walk(app);app.after(1200,lambda:_force_calibri(app))

def _safe_dialog_sizer(module):
    def safe(win,w=900,h=650):
        try:
            win.update_idletasks();sw=win.winfo_screenwidth();sh=win.winfo_screenheight();mw=max(420,min(int(w),sw-80));mh=max(260,min(int(h),sh-120));x=max(10,(sw-mw)//2);y=max(10,(sh-mh)//2);win.geometry(f"{mw}x{mh}+{x}+{y}");win.minsize(min(420,mw),min(260,mh));win.resizable(True,True)
        except:pass
    module.enable_dialog_maximize=safe

def _window_identity_sweep(app):
    import tkinter as tk
    try:
        ico=Path(M.ROOT)/"turto_logo.ico"
        for w in app.winfo_children():
            pass
        def walk(w):
            for c in w.winfo_children():
                try:
                    if isinstance(c,tk.Toplevel):
                        if ico.exists():c.iconbitmap(default=str(ico))
                        try:c.group(app)
                        except:pass
                    walk(c)
                except:pass
        walk(app)
    except:pass
    app.after(1000,lambda:_window_identity_sweep(app))

def _raise_dialog_chain(app,event=None):
    try:
        g=app.grab_current()
        if g and g.winfo_exists():g.lift();g.focus_force();return
        tops=[]
        def walk(w):
            for c in w.winfo_children():
                try:
                    if c.winfo_class()=="Toplevel" and c.state()!="withdrawn":tops.append(c)
                    walk(c)
                except:pass
        walk(app)
        if tops:tops[-1].lift();tops[-1].focus_force()
    except:pass

def _set_taskbar_identity(app):
    try:
        if sys.platform.startswith("win"):
            import ctypes;ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        ico=Path(M.ROOT)/"turto_logo.ico"
        if ico.exists():app.iconbitmap(default=str(ico))
        png=Path(M.ROOT)/"turto_logo.png"
        if png.exists():
            import tkinter as tk;ph=tk.PhotoImage(file=str(png));app.iconphoto(True,ph);app._turto_icon=ph
        app.bind("<Map>",lambda e:_raise_dialog_chain(app),add="+");app.bind("<FocusIn>",lambda e:_raise_dialog_chain(app),add="+")
    except:pass

def create_windows_shortcuts(app):
    if not sys.platform.startswith("win"):return
    try:
        root=Path(M.ROOT);launcher=root/"ZakazkyCRM.pyw";ico=root/"turto_logo.ico";exe=Path(sys.executable).resolve();pyw=exe.with_name("pythonw.exe");exe=pyw if pyw.exists() else exe
        desktop=Path(os.environ.get("USERPROFILE",str(Path.home())))/"Desktop"/"TURTO Zakázky CRM.lnk";start=Path(os.environ.get("APPDATA",""))/"Microsoft"/"Windows"/"Start Menu"/"Programs"/"TURTO Zakázky CRM.lnk"
        q=lambda s:str(s).replace("'","''")
        ps=f"$ws=New-Object -ComObject WScript.Shell;foreach($p in @('{q(desktop)}','{q(start)}')){{$s=$ws.CreateShortcut($p);$s.TargetPath='{q(exe)}';$s.Arguments='\"{q(launcher)}\"';$s.WorkingDirectory='{q(root)}';$s.IconLocation='{q(ico)},0';$s.Description='TURTO Zakázky CRM';$s.Save()}}"
        subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-Command",ps],creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        M.messagebox.showinfo("Zástupce","Vytvořen zástupce TURTO Zakázky CRM na ploše a v nabídce Start. Z něj lze aplikaci připnout na hlavní panel.",parent=app)
    except Exception as e:M.messagebox.showerror("Zástupce",str(e),parent=app)

# ---------- theme-aware row colors ----------
LIGHT={"status_active":("#dcecf8","#17324a"),"status_wait":("#fff0bf","#594300"),"status_soon":("#ffd9b3","#6b3600"),"status_late":("#ffd0d0","#771d1d"),"status_done":("#d9f0df","#20542d"),"status_won":("#cdebd5","#1f5630"),"status_cancel":("#e6e8eb","#4a5158"),"status_offer":("#e9ddf5","#52386b")}
DARK={"status_active":("#294d68","#f2f8fc"),"status_wait":("#6b5517","#fff4c6"),"status_soon":("#75431d","#ffe1c2"),"status_late":("#773333","#ffe4e4"),"status_done":("#315d3d","#e3f8e8"),"status_won":("#286340","#e1f8e8"),"status_cancel":("#48515a","#f0f2f4"),"status_offer":("#5a4670","#f1e8fa")}
def _apply_tree_palette(app):
    import tkinter.ttk as ttk
    theme=(app.theme.get() if hasattr(app,"theme") else "Světlý").lower();pal=DARK if "tmav" in theme else LIGHT
    aliases={"late":"status_late","soon":"status_soon","waiting":"status_wait","done":"status_done","won":"status_won","lost":"status_cancel","info":"status_active","req_fresh":"status_active","req_mid":"status_wait","req_old":"status_soon","req_received":"status_done"}
    def walk(w):
        try:
            if isinstance(w,ttk.Treeview):
                for tag,(bg,fg) in pal.items():w.tag_configure(tag,background=bg,foreground=fg)
                for a,b in aliases.items():bg,fg=pal[b];w.tag_configure(a,background=bg,foreground=fg)
            for c in w.winfo_children():walk(c)
        except:pass
    walk(app)
def _patch_theme(module):
    old=module.App.apply_theme
    def apply(self,*a,**k):
        r=old(self,*a,**k);self.after_idle(lambda:_apply_tree_palette(self));return r
    module.App.apply_theme=apply

# ---------- live update checks with release notes ----------
def _ver(v):
    try:return tuple(int(x) for x in str(v).split("."))
    except:return (0,)
def _live_update_checks(app):
    offered={"version":""}
    def check():
        try:
            if str(M.get_setting("company_auto_updates","1"))=="0":return
            req=urllib.request.Request(GITHUB_UPDATE+"/latest.json?ts="+str(int(datetime.datetime.now().timestamp())),headers={"User-Agent":"TURTO-CRM"})
            with urllib.request.urlopen(req,timeout=8) as r:data=json.load(r)
            nv=str(data.get("version","")).strip();cur=str(M.APP_VERSION)
            if nv and _ver(nv)>_ver(cur) and offered["version"]!=nv:
                offered["version"]=nv;notes=str(data.get("notes","")).strip() or "Drobné opravy a vylepšení."
                def offer():
                    import tkinter as tk;from tkinter import ttk
                    d=tk.Toplevel(app);d.title(f"Aktualizace {nv}");d.transient(app);d.grab_set();M.enable_dialog_maximize(d,620,380);f=ttk.Frame(d,padding=18);f.pack(fill="both",expand=True);ttk.Label(f,text=f"Je dostupná nová verze {nv}",style="Section.TLabel").pack(anchor="w");ttk.Label(f,text="Co aktualizace obsahuje:",style="PageSubtitle.TLabel").pack(anchor="w",pady=(12,4));txt=tk.Text(f,height=8,wrap="word",font=("Calibri",11));txt.pack(fill="both",expand=True);txt.insert("1.0",notes);txt.configure(state="disabled");bar=ttk.Frame(f);bar.pack(fill="x",pady=(12,0));ttk.Button(bar,text="Později",command=d.destroy).pack(side="right");ttk.Button(bar,text="Aktualizovat",style="Accent.TButton",command=lambda:(d.destroy(),app.check_for_updates(silent=False))).pack(side="right",padx=6)
                app.after(0,offer)
        except:pass
        finally:
            try:app.after(10*60*1000,check)
            except:pass
    app.after(5000,check)

# ---------- apply ----------
def apply(module):
    global M;M=module;_activate(module);_db_wrapper(module);_safe_dialog_sizer(module);_ensure();_patch_users(module);_patch_theme(module);module.App.open_admin=open_admin;module.App.create_desktop_shortcut=create_windows_shortcuts
    old=module.App.__init__
    def init(self,*a,**k):
        M._active_app=self
        r=old(self,*a,**k);_restore_local_user(self);_force_calibri(self);_set_taskbar_identity(self);_window_identity_sweep(self);_apply_tree_palette(self);_live_update_checks(self)
        try:self.footer_db.configure(text=f"Databáze: {'SÍŤOVÁ' if NETWORK_MODE else 'LOKÁLNÍ'} • {M.DB}")
        except:pass
        return r
    module.App.__init__=init
