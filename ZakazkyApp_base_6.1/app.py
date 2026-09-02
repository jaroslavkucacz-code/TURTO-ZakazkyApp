import hashlib, json
import urllib.request, tempfile
import os, sys, sqlite3, shutil, json, tempfile, zipfile, csv, subprocess, threading, calendar, urllib.request, urllib.error, re, webbrowser, unicodedata
from zoneinfo import ZoneInfo
from pathlib import Path
from datetime import datetime, date
from urllib.parse import urlencode, quote
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import tkinter.font as tkfont

APP_NAME="Zakázky"
APP_VERSION="6.1.0"

def enable_windows_dpi_awareness():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

enable_windows_dpi_awareness()

CC_ALWAYS="info@turto.cz"
STATUSES=["Rozpracováno","Připraveno","Hotovo","Zrušeno"]

def app_dir():
    if getattr(sys,"frozen",False): return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

ROOT=app_dir()
LOGO=ROOT/"turto_logo.png"

def stable_root():
    if sys.platform.startswith("win"):
        base=Path(os.environ.get("USERPROFILE",str(Path.home()))) / "Documents"
    else:
        base=Path.home()/"Documents"
    return base/"TURTO Zakazky"

DATA_ROOT=stable_root()
DATA_DIR=DATA_ROOT/"data"
BACKUP_DIR=DATA_ROOT/"backup"
DB=DATA_DIR/"zakazky.db"
LIVE_DB=DB
TEST_DIR=DATA_ROOT/"test_session"
TEST_DB=TEST_DIR/"zakazky_test.db"
TEST_MARKER=TEST_DIR/"active.txt"
TEST_USER="TEST"
TEST_MODE=False

for p in (DATA_DIR,BACKUP_DIR): p.mkdir(parents=True,exist_ok=True)

def cleanup_stale_test_session():
    """Po pádu aplikace zahoď zbylou testovací DB ještě před běžným startem."""
    try:
        if TEST_DIR.exists():
            shutil.rmtree(TEST_DIR,ignore_errors=True)
    except Exception:
        pass

def migrate_v41_visual_once():
    """Jednorázově aktivuje nový tmavý/zlatý vzhled v4.1 pro existující uživatele."""
    with db() as con:
        marker=con.execute("SELECT value FROM settings WHERE key='v41_visual_migrated'").fetchone()
        if marker:return
        users=con.execute("SELECT name FROM users WHERE active=1").fetchall()
        for r in users:
            con.execute("""INSERT OR REPLACE INTO user_settings(user_name,key,value)
                           VALUES(?,'theme','Tmavý')""",(r["name"],))
        con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('v41_visual_migrated','1')")

def ensure_test_user():
    """Speciální TEST uživatel je dostupný v ostré databázi bez zásahu do historie."""
    with db() as con:
        r=con.execute("SELECT id FROM users WHERE lower(trim(name))='test' LIMIT 1").fetchone()
        if not r:
            con.execute("INSERT INTO users(name,active) VALUES(?,1)",(TEST_USER,))
        else:
            con.execute("UPDATE users SET active=1 WHERE id=?",(r["id"],))

def enter_test_mode():
    global DB,TEST_MODE
    if TEST_MODE:return True
    TEST_DIR.mkdir(parents=True,exist_ok=True)
    # SQLite backup API vytvoří konzistentní snapshot i při WAL režimu.
    with sqlite3.connect(LIVE_DB) as src, sqlite3.connect(TEST_DB) as dst:
        src.backup(dst)
    TEST_MARKER.write_text(datetime.now().isoformat(),encoding="utf-8")
    DB=TEST_DB;TEST_MODE=True
    return True

def leave_test_mode():
    global DB,TEST_MODE
    DB=LIVE_DB;TEST_MODE=False
    try:shutil.rmtree(TEST_DIR,ignore_errors=True)
    except Exception:pass

def bootstrap_db():
    if DB.exists(): return
    # Prefer a database from an older extracted version in the same folder if present.
    legacy=ROOT/"data"/"zakazky.db"
    seed=ROOT/"seed"/"zakazky.db"
    source=legacy if legacy.exists() else seed
    if source.exists(): shutil.copy2(source,DB)



def restore_people_from_v280_backup_once():
    """v2.9 only: recover Address-book people from the automatic pre-v2.8 backup.
    Business/test records are NOT restored. Existing people are never overwritten."""
    marker=BACKUP_DIR/"v290_people_recovery_done.txt"
    if marker.exists():
        return False
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    candidates=sorted(BACKUP_DIR.glob("zakazky_before_v280_excel_reset_*.db"),reverse=True)
    if not candidates:
        marker.write_text("Nebyla nalezena záloha před resetem v2.8; nebylo co obnovit.",
                          encoding="utf-8")
        return False
    old=candidates[0]
    restored=0
    try:
        with sqlite3.connect(old) as src, db() as dst:
            src.row_factory=sqlite3.Row
            old_people=src.execute("""SELECT p.*,c.official_name company_name
                                      FROM people p LEFT JOIN companies c ON c.id=p.company_id
                                      WHERE coalesce(p.active,1)=1""").fetchall()
            for p in old_people:
                name=(p["name"] or "").strip()
                email=(p["email"] or "").strip()
                if not name and not email:continue
                # Do not duplicate an already present e-mail/person.
                hit=None
                if email:
                    hit=dst.execute("SELECT id FROM people WHERE lower(trim(email))=lower(trim(?)) LIMIT 1",
                                    (email,)).fetchone()
                if not hit and name:
                    hit=dst.execute("SELECT id FROM people WHERE lower(trim(name))=lower(trim(?)) LIMIT 1",
                                    (name,)).fetchone()
                if hit:continue

                cid=None
                cname=(p["company_name"] or "").strip()
                if cname:
                    c=dst.execute("""SELECT id FROM companies
                                     WHERE lower(trim(official_name))=lower(trim(?)) AND active=1 LIMIT 1""",
                                  (cname,)).fetchone()
                    if c:cid=c["id"]
                    else:
                        cid=dst.execute("""INSERT INTO companies(short_name,official_name,active)
                                          VALUES(?,?,1)""",(cname,cname)).lastrowid
                dst.execute("""INSERT INTO people(name,email,phone,company_id,role,active)
                               VALUES(?,?,?,?,?,1)""",
                            (name,email,p["phone"] or "",cid,p["role"] or ""))
                restored+=1
        marker.write_text(
            f"Obnova Osob z {old.name}: {restored} kontaktů. "
            "Příležitosti/Poptávky/Úkoly z testovací DB obnoveny nebyly.",
            encoding="utf-8")
        return restored>0
    except Exception as e:
        # No destructive action: current DB remains usable; retry is possible next start.
        return False

_CZ_ORDER={
    "a":10,"á":11,"b":20,"c":30,"č":31,"d":40,"ď":41,
    "e":50,"é":51,"ě":52,"f":60,"g":70,"h":80,"ch":90,
    "i":100,"í":101,"j":110,"k":120,"l":130,"m":140,
    "n":150,"ň":151,"o":160,"ó":161,"p":170,"q":180,
    "r":190,"ř":191,"s":200,"š":201,"t":210,"ť":211,
    "u":220,"ú":221,"ů":222,"v":230,"w":240,"x":250,
    "y":260,"ý":261,"z":270,"ž":271
}

def czech_sort_key(value):
    """Deterministické české abecední řazení včetně CH, háčků a čárek."""
    s=str(value or "").strip().casefold()
    out=[];i=0
    while i<len(s):
        if i+1<len(s) and s[i:i+2]=="ch":
            out.append((_CZ_ORDER["ch"],""));i+=2;continue
        ch=s[i]
        if ch in _CZ_ORDER:
            out.append((_CZ_ORDER[ch],""))
        elif ch.isdigit():
            # Přirozenější řazení čísel v názvech.
            j=i
            while j<len(s) and s[j].isdigit():j+=1
            out.append((500,int(s[i:j])))
            i=j;continue
        elif ch.isspace():
            out.append((1,""))
        else:
            out.append((400,ch))
        i+=1
    return tuple(out)

def _czech_collate(a,b):
    ka=czech_sort_key(a);kb=czech_sort_key(b)
    return (ka>kb)-(ka<kb)

def db():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    con.create_collation("CZECH",_czech_collate)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    return con

def has_column(con,table,col):
    return any(r[1]==col for r in con.execute(f"PRAGMA table_info({table})"))

def norm_name(s):
    s=(s or "").lower().strip()
    s=re.sub(r"\b(s\.?\s*r\.?\s*o\.?|a\.?\s*s\.?|se|spol\.?\s*s\.?\s*r\.?\s*o\.?)\b","",s)
    s=re.sub(r"[^a-z0-9á-ž]+"," ",s)
    return " ".join(s.split())



class DatePicker(ttk.Frame):
    """Kompaktní český kalendář; ukládá YYYY-MM-DD."""
    MONTHS=("leden","únor","březen","duben","květen","červen",
            "červenec","srpen","září","říjen","listopad","prosinec")
    DAYS=("Po","Út","St","Čt","Pá","So","Ne")

    def __init__(self,parent,variable,width=14):
        super().__init__(parent)
        self.variable=variable
        self.entry=ttk.Entry(self,textvariable=variable,width=width)
        self.entry.pack(side="left",fill="x",expand=True)
        ttk.Button(self,text="▣",width=3,command=self.open_calendar).pack(side="left",padx=(4,0))

    def open_calendar(self):
        pop=tk.Toplevel(self)
        pop.title("Vybrat datum")
        pop.transient(self.winfo_toplevel())
        pop.resizable(False,False)
        pop.configure(background="#f4f7fa")
        try:
            selected=datetime.strptime(self.variable.get().strip(),"%Y-%m-%d").date()
        except Exception:
            selected=None
        current=selected or date.today()
        state={"year":current.year,"month":current.month}

        shell=tk.Frame(pop,bg="#f4f7fa",bd=0,padx=12,pady=12)
        shell.pack(fill="both",expand=True)
        card=tk.Frame(shell,bg="white",bd=1,relief="solid")
        card.pack(fill="both",expand=True)

        head=tk.Frame(card,bg="#17324a",padx=10,pady=9)
        head.pack(fill="x")
        prev=tk.Button(head,text="‹",font=("Calibri",15,"bold"),fg="white",bg="#17324a",
                       activeforeground="white",activebackground="#244d7a",bd=0,width=2)
        prev.pack(side="left")
        title=tk.Label(head,text="",font=("Calibri",12,"bold"),fg="white",bg="#17324a")
        title.pack(side="left",expand=True)
        nxt=tk.Button(head,text="›",font=("Calibri",15,"bold"),fg="white",bg="#17324a",
                      activeforeground="white",activebackground="#244d7a",bd=0,width=2)
        nxt.pack(side="right")

        grid=tk.Frame(card,bg="white",padx=8,pady=8)
        grid.pack(fill="both",expand=True)

        def choose(day):
            self.variable.set(f"{state['year']:04d}-{state['month']:02d}-{day:02d}")
            pop.destroy()

        def change(delta):
            m=state["month"]+delta;y=state["year"]
            if m<1:m=12;y-=1
            if m>12:m=1;y+=1
            state.update(year=y,month=m);render()

        prev.configure(command=lambda:change(-1))
        nxt.configure(command=lambda:change(1))

        def render():
            for w in grid.winfo_children():w.destroy()
            title.configure(text=f"{self.MONTHS[state['month']-1].capitalize()} {state['year']}")
            for cc,n in enumerate(self.DAYS):
                fg="#8a5a44" if cc>=5 else "#667085"
                tk.Label(grid,text=n,width=4,font=("Calibri",9,"bold"),
                         bg="white",fg=fg).grid(row=0,column=cc,padx=2,pady=(0,5))
            today=date.today()
            weeks=calendar.Calendar(firstweekday=0).monthdayscalendar(state["year"],state["month"])
            for rr,week in enumerate(weeks,1):
                for cc,day in enumerate(week):
                    if not day:
                        tk.Label(grid,text="",width=4,bg="white").grid(row=rr,column=cc,padx=2,pady=2)
                        continue
                    this_date=date(state["year"],state["month"],day)
                    bg="white";fg="#1f2937";relief="flat";bd=0
                    if cc>=5: fg="#8a5a44"
                    if selected and this_date==selected:
                        bg="#dcecff";fg="#17324a";relief="solid";bd=1
                    if this_date==today:
                        bg="#f6d889";fg="#47360b";relief="solid";bd=1
                    b=tk.Button(grid,text=str(day),width=3,height=1,
                                font=("Calibri",10),bg=bg,fg=fg,
                                activebackground="#e8eef5",activeforeground="#17324a",
                                relief=relief,bd=bd,command=lambda d=day:choose(d))
                    b.grid(row=rr,column=cc,padx=2,pady=2,ipadx=2,ipady=2)

        render()

        foot=tk.Frame(card,bg="#f8fafc",padx=9,pady=8)
        foot.pack(fill="x")
        tk.Button(foot,text="Vymazat datum",font=("Calibri",9),bd=0,
                  bg="#f8fafc",fg="#667085",activebackground="#eef2f6",
                  command=lambda:(self.variable.set(""),pop.destroy())).pack(side="left")
        tk.Button(foot,text="Dnes",font=("Calibri",9,"bold"),bd=0,
                  bg="#dcecff",fg="#17324a",activebackground="#cfe2f7",
                  command=lambda:(self.variable.set(date.today().isoformat()),pop.destroy())).pack(side="right")

        center_dialog(pop,self.winfo_toplevel())


def center_dialog(win,parent=None):
    """Otevře dialog uprostřed monitoru rodiče a udrží jej v pracovní ploše."""
    def _workarea(p):
        if sys.platform.startswith("win"):
            try:
                import ctypes
                from ctypes import wintypes
                class RECT(ctypes.Structure):
                    _fields_=[("left",ctypes.c_long),("top",ctypes.c_long),
                              ("right",ctypes.c_long),("bottom",ctypes.c_long)]
                class MONITORINFO(ctypes.Structure):
                    _fields_=[("cbSize",ctypes.c_ulong),("rcMonitor",RECT),
                              ("rcWork",RECT),("dwFlags",ctypes.c_ulong)]
                hwnd=p.winfo_id()
                mon=ctypes.windll.user32.MonitorFromWindow(hwnd,2)
                mi=MONITORINFO();mi.cbSize=ctypes.sizeof(MONITORINFO)
                ctypes.windll.user32.GetMonitorInfoW(mon,ctypes.byref(mi))
                return mi.rcWork.left,mi.rcWork.top,mi.rcWork.right,mi.rcWork.bottom
            except Exception:pass
        return 0,0,win.winfo_screenwidth(),win.winfo_screenheight()

    def _place():
        try:
            win.update_idletasks()
            p=parent or win.master
            if p is None:return
            p.update_idletasks()
            left,top,right,bottom=_workarea(p)
            aw=max(320,right-left);ah=max(240,bottom-top)
            pref=getattr(win,"_preferred_dialog_size",(0,0))
            content=getattr(win,"_dialog_content",None)
            content_w=content.winfo_reqwidth()+44 if content is not None else 0
            content_h=content.winfo_reqheight()+48 if content is not None else 0
            ww=min(max(win.winfo_reqwidth(),win.winfo_width(),pref[0],content_w),aw-20)
            # Height follows the actual form. pref[1] is only a practical minimum,
            # never a percentage-forced oversized height.
            wh=min(max(win.winfo_reqheight(),pref[1],content_h),ah-40)
            px=p.winfo_rootx();py=p.winfo_rooty();pw=p.winfo_width();ph=p.winfo_height()
            x=px+(pw-ww)//2;y=py+(ph-wh)//2
            x=max(left+5,min(x,right-ww-5));y=max(top+5,min(y,bottom-wh-5))
            win.geometry(f"{max(320,ww)}x{max(240,wh)}+{x}+{y}")
            sync=getattr(win,"_sync_dialog_scroll",None)
            if sync:win.after_idle(sync)
        except Exception:pass
    win.after_idle(_place)


def scrollable_dialog_frame(win,padding=18):
    """Moderní posuvný obsah dialogu bez zásahu do logiky formuláře."""
    outer=ttk.Frame(win,style="DialogShell.TFrame")
    outer.pack(fill="both",expand=True)
    outer.columnconfigure(0,weight=1)
    outer.rowconfigure(1,weight=1)

    # Vizuální hlavička dialogu je mimo vlastní formulář, takže nemění jeho grid řádky.
    head=ttk.Frame(outer,style="DialogHeader.TFrame",padding=(20,15))
    head.grid(row=0,column=0,columnspan=2,sticky="ew")
    title=(win.title() or "Detail").strip()
    subtitles={
        "Poptávka":"Dodavatel, odběratel, komunikace a stav poptávky",
        "Příležitost":"Obchodní případ, termíny a související Akce",
        "Akce":"Projekt, lokalita a související obchodní vazby",
        "Společnost":"Firemní údaje, ARES a kontaktní osoby",
        "Osoba":"Kontaktní údaje, společnost a funkce",
        "Úkol":"Termín, odpovědnost a návaznost na příležitost",
        "Nastavení":"Uživatelé, číselníky a provozní nastavení",
    }
    ttk.Label(head,text=title,style="DialogTitle.TLabel").pack(anchor="w")
    sub=subtitles.get(title,"")
    if sub:ttk.Label(head,text=sub,style="DialogSubtitle.TLabel").pack(anchor="w",pady=(2,0))

    try:
        canvas_bg=ttk.Style(win).lookup("DialogBody.TFrame","background") or ttk.Style(win).lookup("TFrame","background")
    except Exception:
        canvas_bg="#0f151a"

    canvas=tk.Canvas(outer,highlightthickness=0,borderwidth=0,background=canvas_bg)
    vs=ttk.Scrollbar(outer,orient="vertical",command=canvas.yview)
    hs=ttk.Scrollbar(outer,orient="horizontal",command=canvas.xview)
    canvas.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
    canvas.grid(row=1,column=0,sticky="nsew")
    vs.grid(row=1,column=1,sticky="ns")
    # Horizontální scroll se zobrazí jen tehdy, když je skutečně potřeba.
    hs.grid(row=2,column=0,sticky="ew")
    hs.grid_remove()

    inner=ttk.Frame(canvas,style="DialogBody.TFrame",padding=padding)
    win._dialog_content=inner
    win._dialog_canvas=canvas
    item=canvas.create_window((0,0),window=inner,anchor="nw")

    def _sync(_=None):
        try:
            canvas.update_idletasks()
            content_w=inner.winfo_reqwidth()
            view_w=max(1,canvas.winfo_width())
            req_w=max(content_w,view_w)
            canvas.itemconfigure(item,width=req_w)
            bbox=canvas.bbox(item)
            if bbox:canvas.configure(scrollregion=bbox)
            if content_w>view_w+8:hs.grid()
            else:hs.grid_remove()
        except Exception:pass

    inner.bind("<Configure>",_sync,add="+")
    canvas.bind("<Configure>",_sync,add="+")

    def _refresh_autocomplete_popups():
        try:
            for entry in list(_AUTOCOMPLETE_ENTRIES):
                try:
                    if entry.winfo_exists() and entry.winfo_toplevel() is win:
                        entry._reposition_popup()
                except Exception:pass
        except Exception:pass

    def _scroll_y(*args):
        try:
            canvas.yview(*args);win.after_idle(_refresh_autocomplete_popups)
        except Exception:pass
    vs.configure(command=_scroll_y)

    def _wheel(e):
        try:
            if getattr(e,"delta",0):
                canvas.yview_scroll(-1 if e.delta>0 else 1,"units")
                win.after_idle(_refresh_autocomplete_popups);return "break"
            if getattr(e,"num",0) in (4,5):
                canvas.yview_scroll(-1 if e.num==4 else 1,"units")
                win.after_idle(_refresh_autocomplete_popups);return "break"
        except Exception:pass

    win.bind("<MouseWheel>",_wheel,add="+")
    win.bind("<Button-4>",_wheel,add="+")
    win.bind("<Button-5>",_wheel,add="+")
    win._refresh_autocomplete_popups=_refresh_autocomplete_popups
    win._sync_dialog_scroll=_sync

    # Native Tk prvky (Text/Listbox/Canvas) vznikají až po apply_theme hlavního okna.
    # Po sestavení dialogu proto sladíme jejich barvy s aktuálním ttk tématem.
    def _skin_native():
        try:
            st=ttk.Style(win)
            field=st.lookup("TEntry","fieldbackground") or "#1a2228"
            fg=st.lookup("TLabel","foreground") or "#f3f5f6"
            border=st.lookup("TFrame","background") or field
            sel=st.lookup("Treeview","selectbackground") or "#735b1c"
            def walk(w):
                try:
                    cls=w.winfo_class()
                    if cls in ("Text","Listbox"):
                        w.configure(bg=field,fg=fg,insertbackground=fg,
                                    selectbackground=sel,selectforeground="white",
                                    highlightbackground=border,highlightcolor=border,
                                    relief="flat",borderwidth=1)
                    elif cls=="Canvas":
                        w.configure(bg=canvas_bg,highlightbackground=canvas_bg)
                except Exception:pass
                try:
                    for ch in w.winfo_children():walk(ch)
                except Exception:pass
            walk(win)
        except Exception:pass

    win.after_idle(_sync);win.after(60,_sync);win.after(180,_sync)
    win.after(80,_skin_native);win.after(240,_skin_native)
    return inner

def enable_dialog_maximize(win,min_width=620,min_height=420):
    """Resizable/maximizable dialog; never starts larger than the current monitor."""
    try:
        win.resizable(True,True)
        # Do not force a minimum larger than a small monitor/window.
        win.update_idletasks()
        sw=max(640,win.winfo_screenwidth());sh=max(480,win.winfo_screenheight())
        mw=min(max(420,min_width),max(420,sw-80))
        mh=min(max(300,min_height),max(300,sh-120))
        # Width stays comfortable; height is resolved after the form content
        # exists, so short dialogs do not get a large empty area.
        pref_w=min(max(mw,int(sw*0.62)),max(520,sw-80))
        pref_h=min(mh,max(360,sh-120))
        win._preferred_dialog_size=(pref_w,pref_h)
        win.minsize(min(520,pref_w),min(360,pref_h))
        win.maxsize(max(520,sw-20),max(360,sh-40))
        win.geometry(f"{pref_w}x{pref_h}")
        center_dialog(win,getattr(win,"master",None))
    except Exception:
        pass



class InlineChoice(ttk.Frame):
    """Ukotvený výběr uvnitř formuláře – žádný plovoucí Toplevel popup."""
    def __init__(self,master,textvariable=None,values=(),editable=True,max_rows=7,**kw):
        super().__init__(master)
        self.var=textvariable or tk.StringVar()
        self.values=[str(v) for v in values if str(v).strip()]
        self.editable=editable
        self.max_rows=max_rows
        self._setting=False
        self._shown=False

        self.columnconfigure(0,weight=1)
        self.entry=ttk.Entry(self,textvariable=self.var,**kw)
        self.entry.grid(row=0,column=0,sticky="ew")
        self.button=ttk.Button(self,text="⌄",width=3,command=self.toggle)
        self.button.grid(row=0,column=1,sticky="ns",padx=(3,0))

        self.listbox=tk.Listbox(self,height=min(self.max_rows,max(1,len(self.values))),
                                exportselection=False,activestyle="dotbox")
        self.scroll=ttk.Scrollbar(self,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.scroll.set)
        self.listbox.grid(row=1,column=0,sticky="nsew",pady=(2,0))
        self.scroll.grid(row=1,column=1,sticky="ns",pady=(2,0))
        self.listbox.grid_remove();self.scroll.grid_remove()

        self.entry.bind("<Button-1>",lambda e:self.after_idle(self.show),add="+")
        self.entry.bind("<FocusIn>",lambda e:self.after_idle(self.show),add="+")
        self.entry.bind("<Down>",lambda e:self._navigate(1))
        self.entry.bind("<Up>",lambda e:self._navigate(-1))
        self.entry.bind("<Return>",self._accept_entry)
        self.entry.bind("<Escape>",lambda e:self.hide())
        self.entry.bind("<FocusOut>",lambda e:self.after(120,self._hide_if_needed))
        self.listbox.bind("<ButtonRelease-1>",self._choose)
        self.listbox.bind("<Double-Button-1>",self._choose)
        self.listbox.bind("<Return>",self._choose)
        self.listbox.bind("<Escape>",lambda e:self.hide())
        self.listbox.bind("<FocusOut>",lambda e:self.after(120,self._hide_if_needed))
        self.listbox.bind("<Up>",lambda e:self._move(-1))
        self.listbox.bind("<Down>",lambda e:self._move(1))
        self.var.trace_add("write",self._changed)

    def set_values(self,values):
        self.values=[str(v) for v in values if str(v).strip()]
        if self._shown:self._fill()

    def _matches(self):
        q=(self.var.get() or "").strip().casefold()
        if not self.editable or not q:return self.values
        exact=[v for v in self.values if v.casefold()==q]
        if exact:return self.values
        return [v for v in self.values if q in v.casefold()]

    def _fill(self):
        vals=self._matches()
        self.listbox.delete(0,"end")
        for v in vals:self.listbox.insert("end",v)
        rows=min(self.max_rows,max(1,len(vals)))
        self.listbox.configure(height=rows)
        if vals:
            cur=(self.var.get() or "").strip().casefold()
            idx=next((i for i,v in enumerate(vals) if v.casefold()==cur),0)
            self.listbox.selection_clear(0,"end")
            self.listbox.selection_set(idx);self.listbox.activate(idx);self.listbox.see(idx)

    def show(self):
        if self._shown:return
        self._fill()
        if self.listbox.size()==0:return
        self._shown=True
        self.listbox.grid();self.scroll.grid()
        self.button.configure(text="⌃")
        try:
            top=self.winfo_toplevel()
            sync=getattr(top,"_sync_dialog_scroll",None)
            if sync:top.after_idle(sync)
        except Exception:pass

    def hide(self):
        if not self._shown:return
        self._shown=False
        self.listbox.grid_remove();self.scroll.grid_remove()
        self.button.configure(text="⌄")
        try:
            top=self.winfo_toplevel()
            sync=getattr(top,"_sync_dialog_scroll",None)
            if sync:top.after_idle(sync)
        except Exception:pass

    def toggle(self):
        self.hide() if self._shown else self.show()

    def _hide_if_needed(self):
        try:
            f=self.focus_get()
            if f in (self.entry,self.listbox,self.button):return
        except Exception:pass
        self.hide()

    def _changed(self,*_):
        if self._setting:return
        if self.editable and self.entry.focus_get()==self.entry:
            if not self._shown:self.show()
            else:self._fill()

    def _set(self,value):
        self._setting=True
        try:self.var.set(value)
        finally:self._setting=False
        self.hide()
        self.entry.focus_set()
        self.entry.icursor("end")
        self.event_generate("<<InlineChoiceSelected>>")

    def _choose(self,e=None):
        sel=self.listbox.curselection()
        if not sel and e is not None:
            idx=self.listbox.nearest(e.y)
        elif sel:idx=sel[0]
        else:return "break"
        if 0<=idx<self.listbox.size():self._set(self.listbox.get(idx))
        return "break"

    def _move(self,delta):
        size=self.listbox.size()
        if not size:return "break"
        sel=self.listbox.curselection()
        cur=sel[0] if sel else 0
        nxt=max(0,min(size-1,cur+delta))
        self.listbox.selection_clear(0,"end");self.listbox.selection_set(nxt)
        self.listbox.activate(nxt);self.listbox.see(nxt)
        return "break"

    def _navigate(self,delta):
        self.show()
        if self.listbox.size():
            self.listbox.focus_set()
            if delta<0:
                self.listbox.selection_clear(0,"end")
                idx=self.listbox.size()-1
                self.listbox.selection_set(idx);self.listbox.activate(idx);self.listbox.see(idx)
        return "break"

    def _accept_entry(self,e=None):
        if self._shown and self.listbox.size():
            sel=self.listbox.curselection()
            idx=sel[0] if sel else 0
            self._set(self.listbox.get(idx))
        elif self.var.get().strip() in self.values:
            self.hide()
        return "break"


def safe_combobox(master,**kwargs):
    """Combobox, jehož hodnotu kolečko myši nikdy nemění."""
    cb=ttk.Combobox(master,**kwargs)
    def _wheel(e):
        try:
            top=cb.winfo_toplevel()
            canvas=getattr(top,"_dialog_canvas",None)
            if canvas is not None:
                if getattr(e,"delta",0):
                    canvas.yview_scroll(-1 if e.delta>0 else 1,"units")
                elif getattr(e,"num",0) in (4,5):
                    canvas.yview_scroll(-1 if e.num==4 else 1,"units")
                refresh=getattr(top,"_refresh_autocomplete_popups",None)
                if refresh:top.after_idle(refresh)
        except Exception:
            pass
        # Zastaví nativní class binding TCombobox, který jinak mění položku.
        return "break"
    cb.bind("<MouseWheel>",_wheel,add="+")
    cb.bind("<Button-4>",_wheel,add="+")
    cb.bind("<Button-5>",_wheel,add="+")
    return cb

def setup_clear_filter_button(frame,command,variables,defaults=None):
    defaults=defaults or {}
    btn=ttk.Button(frame,text="✕ Zrušit filtry",width=16,command=command)
    btn._filter_overlay_control=True
    def active():
        for v in variables:
            try:
                cur=(v.get() or "").strip()
            except Exception:
                continue
            default=str(defaults.get(id(v),"")).strip()
            if cur!=default:
                return True
        return False
    def refresh(*_):
        try:
            if active():
                btn.place(relx=1.0,rely=0.5,anchor="e",x=-4)
                btn.lift()
            else:
                btn.place_forget()
        except Exception:pass
    for v in variables:
        try:v.trace_add("write",refresh)
        except Exception:pass
    frame.after_idle(refresh)
    return btn

def attach_filter_bar(tree,filter_frame):
    """Zarovná filtrovací prvky podle jejich skutečného čísla sloupce Treeview."""
    try:
        cells=[]
        for w in filter_frame.winfo_children():
            if getattr(w,"_filter_overlay_control",False):
                continue
            try:
                info=w.grid_info()
                col=int(info.get("column",0))
            except Exception:
                continue
            cells.append((col,w))
        cells=sorted(cells,key=lambda x:x[0])
        cols=list(tree["columns"])
        if not cells or not cols:return

        filter_frame.update_idletasks()
        height=max([w.winfo_reqheight() for _,w in cells]+[34])+2
        filter_frame.configure(height=height)
        filter_frame.pack_propagate(False)
        filter_frame.grid_propagate(False)
        for _,w in cells:
            try:w.grid_forget()
            except Exception:pass

        def sync(event=None):
            try:
                tree.update_idletasks()
                widths=[max(1,int(tree.column(c,"width"))) for c in cols]
                total=max(1,sum(widths))
                try:first=tree.xview()[0]
                except Exception:first=0.0
                offset=int(round(first*total))
                starts=[];acc=0
                for width in widths:
                    starts.append(acc);acc+=width
                for col,w in cells:
                    if col<0 or col>=len(widths):
                        w.place_forget();continue
                    w.place(x=starts[col]-offset,y=0,width=widths[col],height=height)
            except Exception:
                pass

        tree._filter_frame=filter_frame
        tree._filter_cells=[w for _,w in cells]
        tree._filter_cell_columns=[c for c,_ in cells]
        tree._sync_filter_bar=sync
        tree.bind("<Configure>",lambda e:tree.after_idle(sync),add="+")
        tree.bind("<B1-Motion>",lambda e:tree.after_idle(sync),add="+")
        tree.bind("<ButtonRelease-1>",lambda e:tree.after_idle(sync),add="+")
        filter_frame.bind("<Configure>",lambda e:tree.after_idle(sync),add="+")
        tree.after_idle(sync)
    except Exception:
        pass


def attach_date_cell_highlighter(tree,column,provider):
    """Barevné zvýraznění pouze datumových buněk; overlay se vždy překreslí po scrollu."""
    overlay=tk.Canvas(tree,highlightthickness=0,borderwidth=0)
    overlay.place(x=0,y=0,relwidth=1,relheight=1)
    overlay.configure(bg=ttk.Style(tree).lookup("Treeview","background") or "#10161b")
    # Overlay nesmí blokovat práci s tabulkou – po vykreslení ho držíme pod Treeview;
    # samotné datum proto zůstává v Treeview a barva je realizována prefixem + tagem.
    overlay.place_forget()
    def redraw(*_):
        try:
            mapping=provider() or {}
            for iid,state in mapping.items():
                if not tree.exists(iid):continue
                raw=str(tree.set(iid,column) or "")
                clean=raw
                for p in ("● ","⚠ "):
                    if clean.startswith(p):clean=clean[len(p):]
                prefix="⚠ " if state=="late" else ("● " if state=="soon" else "")
                tree.set(iid,column,prefix+clean if clean else clean)
        except Exception:pass
    tree.bind("<Configure>",lambda e:tree.after_idle(redraw),add="+")
    tree.bind("<MouseWheel>",lambda e:tree.after_idle(redraw),add="+")
    tree.bind("<ButtonRelease-1>",lambda e:tree.after_idle(redraw),add="+")
    tree._date_cell_redraw=redraw
    tree.after_idle(redraw)
    return redraw

def bind_row_double_click(tree,callback):
    """Double-click acts only on a real data row, never on headings/empty space/scrollbars."""
    def _handler(event):
        try:
            if tree.identify_region(event.x,event.y)!="cell":
                return "break"
            row=tree.identify_row(event.y)
            if not row:
                return "break"
            tree.selection_set(row)
            tree.focus(row)
            callback(event)
        except Exception:
            return "break"
        return "break"
    tree.bind("<Double-1>",_handler)



def find_app(widget):
    cur=widget
    for _ in range(12):
        if cur is None:return None
        if hasattr(cur,"manage_code_lists"):return cur
        cur=getattr(cur,"master",None)
    return None

def normalize_gps(value):
    """Vrátí standardní 'lat, lon' nebo prázdný řetězec; neplatné souřadnice vyhodí ValueError."""
    s=(value or "").strip()
    if not s:return ""
    s=s.replace(";",",")
    m=re.match(r"^\s*(-?\d+(?:[.,]\d+)?)\s*,\s*(-?\d+(?:[.,]\d+)?)\s*$",s)
    if not m:
        # Podpora zápisu s desetinnou tečkou odděleného mezerou.
        m=re.match(r"^\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*$",s)
    if not m:raise ValueError("Zadejte GPS ve formátu např. 49.1951, 16.6068")
    lat=float(m.group(1).replace(",","."))
    lon=float(m.group(2).replace(",","."))
    if not (-90<=lat<=90 and -180<=lon<=180):
        raise ValueError("Souřadnice jsou mimo povolený rozsah.")
    lat_s=f"{lat:.7f}".rstrip("0").rstrip(".")
    lon_s=f"{lon:.7f}".rstrip("0").rstrip(".")
    return f"{lat_s}, {lon_s}"

def bind_dialog_keys(win,confirm_callback):
    """Enter potvrzuje, Esc zavírá bez uložení; v multiline Textu Enter zůstává nový řádek."""
    def _enter(event):
        try:
            if event.widget.winfo_class()=="Text":
                return None
            if hasattr(win,"topic_entry") and str(event.widget).startswith(str(win.topic_entry)):
                return None
        except Exception:
            pass
        confirm_callback()
        return "break"
    def _escape(event):
        try:win.destroy()
        except Exception:pass
        return "break"
    win.bind("<Return>",_enter)
    win.bind("<KP_Enter>",_enter)
    win.bind("<Escape>",_escape)

def read_contacts_file(path):
    path=Path(path)
    records=[]
    if path.suffix.lower()==".vcf":
        text=path.read_text(encoding="utf-8-sig",errors="replace")
        for card in re.split(r"(?im)^END:VCARD\s*$",text):
            if "BEGIN:VCARD" not in card.upper():continue
            rec={"name":"","email":"","phone":"","company":"","role":""}
            for raw in card.splitlines():
                line=raw.strip()
                val=line.split(":",1)[1].strip() if ":" in line else ""
                upper=line.upper()
                if upper.startswith("FN") and ":" in line:rec["name"]=val
                elif upper.startswith("EMAIL") and ":" in line:rec["email"]=val
                elif upper.startswith("TEL") and ":" in line:rec["phone"]=val
                elif upper.startswith("ORG") and ":" in line:rec["company"]=val.split(";")[0].strip()
                elif upper.startswith("TITLE") and ":" in line:rec["role"]=val
            if any(rec.values()):records.append(rec)
        return records

    raw=path.read_text(encoding="utf-8-sig",errors="replace")
    try:dialect=csv.Sniffer().sniff(raw[:4096],delimiters=",;\t")
    except: dialect=csv.excel
    rows=list(csv.DictReader(raw.splitlines(),dialect=dialect))
    aliases={
        "name":["name","jméno","jmeno","full name","display name","celé jméno","cele jmeno"],
        "email":["email","e-mail","e-mail address","email address","primary email"],
        "phone":["phone","telefon","mobile phone","business phone","mobil","telephone"],
        "company":["company","společnost","spolecnost","company name","organization","firma"],
        "role":["role","funkce","job title","title","pozice"],
    }
    for row in rows:
        normalized={str(k or "").strip().lower():str(v or "").strip() for k,v in row.items()}
        rec={field:next((normalized[n] for n in names if normalized.get(n)),"") for field,names in aliases.items()}
        if any(rec.values()):records.append(rec)
    return records

def write_people_csv(path):
    with db() as con:
        rows=con.execute("""SELECT p.name,p.email,p.phone,c.official_name company,p.role
                            FROM people p LEFT JOIN companies c ON c.id=p.company_id
                            WHERE p.active=1 ORDER BY p.name COLLATE CZECH""").fetchall()
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.writer(f,delimiter=";")
        w.writerow(["Jméno","E-mail","Telefon","Společnost","Funkce"])
        for r in rows:w.writerow([r["name"],r["email"],r["phone"],r["company"],r["role"]])
    return path

def write_people_vcf(path):
    with db() as con:
        rows=con.execute("""SELECT p.name,p.email,p.phone,c.official_name company,p.role
                            FROM people p LEFT JOIN companies c ON c.id=p.company_id
                            WHERE p.active=1 ORDER BY p.name COLLATE CZECH""").fetchall()
    lines=[]
    for r in rows:
        lines+=["BEGIN:VCARD","VERSION:3.0",f"FN:{r['name'] or ''}"]
        if r["email"]:lines.append(f"EMAIL;TYPE=INTERNET:{r['email']}")
        if r["phone"]:lines.append(f"TEL:{r['phone']}")
        if r["company"]:lines.append(f"ORG:{r['company']}")
        if r["role"]:lines.append(f"TITLE:{r['role']}")
        lines.append("END:VCARD")
    Path(path).write_text("\n".join(lines)+"\n",encoding="utf-8")
    return path

def export_complete_database(target_path):
    target=Path(target_path)
    if target.suffix.lower()!=".zip":
        target=target.with_suffix(".zip")
    import tempfile, zipfile
    manifest={"app_version":APP_VERSION,"schema_version":"5.7","exported_at":datetime.now().isoformat(timespec="seconds"),"database_filename":"zakazky.db"}
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); dbcopy=td/"zakazky.db"
        with sqlite3.connect(DB) as src, sqlite3.connect(dbcopy) as dst:
            src.backup(dst)
        (td/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as z:
            z.write(dbcopy,"zakazky.db");z.write(td/"manifest.json","manifest.json")
    return target

def import_complete_database(package_path):
    package=Path(package_path)
    if not package.exists():raise FileNotFoundError(package)
    import tempfile, zipfile
    backup=backup_now("before_complete_import")
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        with zipfile.ZipFile(package) as z:
            if "zakazky.db" not in z.namelist():raise ValueError("Balíček neobsahuje zakazky.db")
            z.extract("zakazky.db",td)
        imported=td/"zakazky.db"
        with sqlite3.connect(imported) as c:
            ok=c.execute("PRAGMA integrity_check").fetchone()[0]
            if ok!="ok":raise ValueError(f"Databáze není v pořádku: {ok}")
        shutil.copy2(imported,DB)
    ensure_schema()
    return backup


def export_selected_data(target_path,selected,include_related=False):
    """Výběrový export tabulek do ZIP/JSON. Nemění pracovní databázi."""
    allowed={
        "Společnosti":["companies"],
        "Osoby":["people"],
        "Příležitosti":["actions"],
        "Akce":["projects"],
        "Poptávky":["requests"],
        "Úkoly":["tasks"],
        "Historie":["action_history"],
        "Uživatelé":["users","user_settings"],
        "Číselníky":["salespeople","materials","work_topics"],
        "Nastavení":["settings","app_meta"],
    }
    tables=[]
    for label in selected:
        tables.extend(allowed.get(label,[]))
    if include_related:
        deps={
            "companies":["people","actions","requests"],
            "actions":["requests","tasks","action_history"],
            "projects":["actions"],
            "requests":["action_history"],
        }
        extra=set(tables)
        for table in list(tables):
            extra.update(deps.get(table,[]))
        tables=list(extra)
    tables=list(dict.fromkeys(tables))
    if not tables:
        raise ValueError("Není vybráno nic k exportu.")
    target=Path(target_path)
    if target.suffix.lower()!=".zip":target=target.with_suffix(".zip")
    manifest={"app_version":APP_VERSION,"schema_version":"5.7",
              "exported_at":datetime.now().isoformat(timespec="seconds"),
              "type":"selected","tables":tables}
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        with db() as con:
            for table in tables:
                exists=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
                if not exists:continue
                rows=[dict(r) for r in con.execute(f"SELECT * FROM {table}").fetchall()]
                (td/f"{table}.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
        (td/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as z:
            for p in td.iterdir():z.write(p,p.name)
    return target

def backup_now(prefix="manual"):
    if not DB.exists(): return None
    BACKUP_DIR.mkdir(parents=True,exist_ok=True)
    target=BACKUP_DIR/f"zakazky_{prefix}_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(DB,target)
    return target

def ensure_schema():
    bootstrap_db()
    if DB.exists():
        # Always make a pre-migration backup for this application generation.
        marker=BACKUP_DIR/"v070_migration_done.txt"
        if not marker.exists():
            backup_now("before_v070")
            marker.write_text(datetime.now().isoformat(),encoding="utf-8")
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS user_settings(
          user_name TEXT NOT NULL,
          key TEXT NOT NULL,
          value TEXT DEFAULT '',
          PRIMARY KEY(user_name,key)
        );
        CREATE TABLE IF NOT EXISTS user_notes(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_name TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          text TEXT NOT NULL DEFAULT '',
          archived INTEGER NOT NULL DEFAULT 0,
          archived_at TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_user_notes_user_archive
          ON user_notes(user_name,archived,created_at DESC);
        CREATE TABLE IF NOT EXISTS salespeople(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,category TEXT DEFAULT '',note TEXT DEFAULT '',active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS companies(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          short_name TEXT NOT NULL,
          official_name TEXT DEFAULT '',
          ico TEXT DEFAULT '',
          dic TEXT DEFAULT '',
          address TEXT DEFAULT '',
          legal_form TEXT DEFAULT '',
          web TEXT DEFAULT '',
          note TEXT DEFAULT '',
          ares_checked TEXT DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS actions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          company_id INTEGER,
          salesperson_id INTEGER,
          created_date TEXT DEFAULT '',
          deadline TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'Rozpracováno',
          products TEXT DEFAULT '',
          next_step TEXT DEFAULT '',
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_by TEXT DEFAULT '',
          FOREIGN KEY(company_id) REFERENCES companies(id),
          FOREIGN KEY(salesperson_id) REFERENCES salespeople(id)
        );
        CREATE TABLE IF NOT EXISTS people(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL,
          phone TEXT DEFAULT '',
          role TEXT DEFAULT '',
          company_id INTEGER,
          note TEXT DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1,
          FOREIGN KEY(company_id) REFERENCES companies(id)
        );
        CREATE TABLE IF NOT EXISTS requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_id INTEGER,
          action_id INTEGER,
          asked_date TEXT DEFAULT '',
          received_date TEXT DEFAULT '',
          item TEXT DEFAULT '',
          note TEXT DEFAULT '',
          mail_subject TEXT DEFAULT '',
          include_project_in_subject INTEGER NOT NULL DEFAULT 1,
          recipients_snapshot TEXT DEFAULT '',
          cc_snapshot TEXT DEFAULT 'info@turto.cz',
          updated_by TEXT DEFAULT '',
          FOREIGN KEY(company_id) REFERENCES companies(id),
          FOREIGN KEY(action_id) REFERENCES actions(id)
        );
        CREATE TABLE IF NOT EXISTS work_topics(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE COLLATE CZECH,
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS person_roles(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE COLLATE CZECH,
          active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS projects(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          address TEXT DEFAULT '',
          gps_coordinates TEXT DEFAULT '',
          investor TEXT DEFAULT '',
          general_contractor TEXT DEFAULT '',
          start_date TEXT DEFAULT '',
          end_date TEXT DEFAULT '',
          note TEXT DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tasks(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          action_id INTEGER NOT NULL,
          due_date TEXT NOT NULL,
          text TEXT NOT NULL,
          note TEXT DEFAULT '',
          done INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          created_by TEXT DEFAULT '',
          done_at TEXT DEFAULT '',
          done_by TEXT DEFAULT '',
          FOREIGN KEY(action_id) REFERENCES actions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done,due_date);
        CREATE TABLE IF NOT EXISTS action_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          action_id INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          user_name TEXT DEFAULT '',
          event_type TEXT NOT NULL,
          summary TEXT NOT NULL,
          details TEXT DEFAULT '',
          related_company_id INTEGER,
          related_request_id INTEGER,
          FOREIGN KEY(action_id) REFERENCES actions(id) ON DELETE CASCADE,
          FOREIGN KEY(related_company_id) REFERENCES companies(id),
          FOREIGN KEY(related_request_id) REFERENCES requests(id)
        );
        CREATE INDEX IF NOT EXISTS idx_action_history_action ON action_history(action_id,created_at);
        """)
        if not has_column(con,"requests","requested_for_company_id"):
            con.execute("ALTER TABLE requests ADD COLUMN requested_for_company_id INTEGER")
            # Starší poptávky záměrně nepřiřazujeme k „Odběratel“ bez jistoty.
        if not has_column(con,"actions","project_id"):
            con.execute("ALTER TABLE actions ADD COLUMN project_id INTEGER")
        if not has_column(con,"projects","gps_coordinates"):
            con.execute("ALTER TABLE projects ADD COLUMN gps_coordinates TEXT DEFAULT ''")
        if not has_column(con,"requests","assigned_user"):
            con.execute("ALTER TABLE requests ADD COLUMN assigned_user TEXT DEFAULT ''")
        if not has_column(con,"requests","archived"):
            con.execute("ALTER TABLE requests ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        if not has_column(con,"requests","archived_at"):
            con.execute("ALTER TABLE requests ADD COLUMN archived_at TEXT DEFAULT ''")
        if not has_column(con,"requests","archived_by"):
            con.execute("ALTER TABLE requests ADD COLUMN archived_by TEXT DEFAULT ''")
        if not has_column(con,"requests","no_response"):
            con.execute("ALTER TABLE requests ADD COLUMN no_response INTEGER NOT NULL DEFAULT 0")
        con.execute("""UPDATE actions SET status='Rozpracováno'
                       WHERE lower(trim(coalesce(status,''))) LIKE 'čekám na obchodníka%'""")
        if not has_column(con,"tasks","assigned_user"):
            con.execute("ALTER TABLE tasks ADD COLUMN assigned_user TEXT DEFAULT ''")
        # U Poptávek se "Řeší" nikdy nedoplňuje z technického updated_by.
        # Pokud nebyl odpovědný uživatel skutečně zadán, zůstává prázdné.
        con.execute("""UPDATE requests SET assigned_user=''
                       WHERE trim(coalesce(assigned_user,'')) IN
                       ('Import původního Excelu','Historický záznam')""")
        con.execute("""UPDATE tasks SET assigned_user=created_by
                       WHERE trim(coalesce(assigned_user,''))='' AND trim(coalesce(created_by,''))<>''""")
        for col,decl in (
            ("date_created","TEXT DEFAULT ''"),
            ("ares_last_change","TEXT DEFAULT ''"),
            ("cz_nace","TEXT DEFAULT ''"),
            ("financial_office","TEXT DEFAULT ''"),
            ("district","TEXT DEFAULT ''"),
            ("municipality","TEXT DEFAULT ''"),
            ("ares_raw_json","TEXT DEFAULT ''")
        ):
            if not has_column(con,"companies",col):
                con.execute(f"ALTER TABLE companies ADD COLUMN {col} {decl}")

        con.execute("INSERT OR IGNORE INTO users(name) VALUES('Jaroslav Kučera')")
        con.execute("INSERT OR IGNORE INTO users(name) VALUES('Denisa Kovalová')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('active_user','Jaroslav Kučera')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('theme','Světlý')")
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('include_project_default','1')")
        # Vlastní společnost TURTO a interní osoby.
        turto=con.execute("SELECT id FROM companies WHERE lower(trim(short_name))='turto' OR lower(trim(official_name)) LIKE 'turto%' LIMIT 1").fetchone()
        if turto:
            turto_id=turto[0]
        else:
            turto_id=con.execute("INSERT INTO companies(short_name,official_name) VALUES('TURTO','TURTO')").lastrowid
        for uname in ("Jaroslav Kučera","Denisa Kovalová"):
            r=con.execute("SELECT id FROM people WHERE lower(trim(name))=lower(trim(?)) AND company_id=?",(uname,turto_id)).fetchone()
            if not r:
                con.execute("INSERT INTO people(name,email,company_id,role) VALUES(?,?,?,?)",(uname,"",turto_id,"Interní uživatel"))

        # --- One-time legacy migration: companies from customers + suppliers ---
        if con.execute("SELECT COUNT(*) FROM companies").fetchone()[0]==0:
            company_map={}
            def add_company(name,ico="",address="",short="",official="",dic="",legal="",web="",note=""):
                name=(name or "").strip()
                if not name:return None
                key=(ico.strip() if ico else "") or norm_name(name)
                if key in company_map:return company_map[key]
                if ico:
                    r=con.execute("SELECT id FROM companies WHERE ico=?",(ico.strip(),)).fetchone()
                    if r: company_map[key]=r[0]; return r[0]
                # normalized duplicate check in Python
                for rr in con.execute("SELECT id,short_name,official_name FROM companies"):
                    if norm_name(rr["official_name"] or rr["short_name"])==norm_name(name):
                        company_map[key]=rr["id"]; return rr["id"]
                cur=con.execute("""INSERT INTO companies(short_name,official_name,ico,dic,address,legal_form,web,note)
                    VALUES(?,?,?,?,?,?,?,?)""",(short or name,official or name,ico or "",dic or "",address or "",legal or "",web or "",note or ""))
                company_map[key]=cur.lastrowid
                return cur.lastrowid

            # old customer/supplier tables may exist
            for table in ("customers","suppliers"):
                try:
                    cols=[r[1] for r in con.execute(f"PRAGMA table_info({table})")]
                    if not cols:continue
                    for r in con.execute(f"SELECT * FROM {table}"):
                        d=dict(r)
                        add_company(d.get("name",""),d.get("ico",""),d.get("address",""),
                                    d.get("short_name",""),d.get("official_name",""),
                                    d.get("dic",""),d.get("legal_form",""),d.get("web",""),d.get("note",""))
                except sqlite3.Error: pass

            # preserve approved short names
            approved={
              "MAVI monolity s.r.o.":"MAVI","GEROtop spol. s r.o.":"GeroTop","Max Frank s.r.o.":"MaxFrank",
              "Nevoga s.r.o.":"Nevoga","PEIKKO CZECH REPUBLIC s.r.o.":"Peikko",
              "PohlCon Česká republika s.r.o.":"PohlCon","PRO-DOMA, SE":"Pro-Doma",
              "Leviat s.r.o.":"Leviat","MIVO":"MIVO"
            }
            for official,short in approved.items():
                con.execute("""UPDATE companies SET short_name=? WHERE lower(trim(official_name))=lower(trim(?))
                    OR lower(trim(short_name))=lower(trim(?))""",(short,official,official))

        # Add unified company_id columns to pre-existing migrated tables if needed.
        for table in ("actions","requests","people"):
            if not has_column(con,table,"company_id"):
                con.execute(f"ALTER TABLE {table} ADD COLUMN company_id INTEGER")

        # Backfill action companies from legacy customer_id.
        if has_column(con,"actions","customer_id"):
            try:
                rows=con.execute("""SELECT a.id,c.name,c.ico FROM actions a LEFT JOIN customers c ON c.id=a.customer_id
                    WHERE a.company_id IS NULL AND c.name IS NOT NULL""").fetchall()
                for r in rows:
                    cid=find_or_create_company(con,r["name"],r["ico"] or "")
                    con.execute("UPDATE actions SET company_id=? WHERE id=?",(cid,r["id"]))
            except sqlite3.Error:pass

        # Backfill request companies from legacy supplier_id.
        if has_column(con,"requests","supplier_id"):
            try:
                rows=con.execute("""SELECT r.id,s.name,s.ico FROM requests r LEFT JOIN suppliers s ON s.id=r.supplier_id
                    WHERE r.company_id IS NULL AND s.name IS NOT NULL""").fetchall()
                for r in rows:
                    cid=find_or_create_company(con,r["name"],r["ico"] or "")
                    con.execute("UPDATE requests SET company_id=? WHERE id=?",(cid,r["id"]))
            except sqlite3.Error:pass

        # Oprava historických MIVO Poptávek. Ve starších databázích mohla být vazba
        # na Dodavatele pouze v supplier_id, případně se oficiální název MIVO liší.
        if has_column(con,"requests","supplier_id"):
            try:
                mivo=con.execute("""SELECT id FROM companies
                    WHERE lower(trim(short_name))='mivo'
                       OR lower(trim(official_name))='mivo'
                       OR lower(trim(official_name)) LIKE 'mivo %'
                    ORDER BY id LIMIT 1""").fetchone()
                if not mivo:
                    mid=find_or_create_company(con,"MIVO","")
                else:
                    mid=mivo["id"]
                rows=con.execute("""SELECT r.id FROM requests r
                    JOIN suppliers s ON s.id=r.supplier_id
                    WHERE lower(trim(s.name))='mivo' OR lower(trim(s.name)) LIKE 'mivo %'
                       OR lower(trim(s.name)) LIKE 'mivo,%' OR lower(trim(s.name)) LIKE 'mivo.%'""").fetchall()
                for rr in rows:
                    con.execute("UPDATE requests SET company_id=? WHERE id=?",(mid,rr["id"]))
            except sqlite3.Error:
                pass

        # Znovu zkontrolovat vazbu osob na společnost podle historického názvu, pokud chybí.
        # Plošná oprava starších vazeb: pokud company_name přesně odpovídá krátkému
        # nebo oficiálnímu názvu jediné společnosti, použije se její stabilní ID.
        if has_column(con,"people","company_name"):
            rows=con.execute("SELECT id,company_name FROM people WHERE trim(coalesce(company_name,''))<>''").fetchall()
            for pr in rows:
                hits=con.execute("""SELECT id FROM companies WHERE active=1 AND
                    (lower(trim(short_name))=lower(trim(?)) OR lower(trim(official_name))=lower(trim(?)))""",
                    (pr["company_name"],pr["company_name"])).fetchall()
                ids=list(dict.fromkeys(x["id"] for x in hits))
                if len(ids)==1:
                    con.execute("UPDATE people SET company_id=? WHERE id=?",(ids[0],pr["id"]))
        # Backfill people using the preserved company_name or old typed link.
        try:
            if has_column(con,"people","company_name"):
                for r in con.execute("SELECT id,company_name FROM people WHERE company_id IS NULL AND trim(coalesce(company_name,''))<>''"):
                    cid=find_or_create_company(con,r["company_name"],"")
                    con.execute("UPDATE people SET company_id=? WHERE id=?",(cid,r["id"]))
        except sqlite3.Error:pass

        # Naplnit číselník "Co se řeší" a vytvořit vrstvu Akcí nad existujícími daty.
        for topic in ("Izolační nosníky","Vibroizolace","Akustika","Dilatace"):
            con.execute("INSERT OR IGNORE INTO work_topics(name) VALUES(?)",(topic,))
        for rr in con.execute("SELECT products FROM actions WHERE trim(coalesce(products,''))<>''").fetchall():
            raw=rr["products"] or ""
            for part in re.split(r"[;,/+]",raw):
                part=part.strip()
                if part:
                    con.execute("INSERT OR IGNORE INTO work_topics(name) VALUES(?)",(part,))

        # Akce vychází z dosavadního přehledu/Příležitostí a jejich Poptávek.
        # Slučujeme pouze přesnou normalizovanou shodu názvu; nejasné názvy zůstávají oddělené.
        existing_projects={re.sub(r"\s+"," ",(r["name"] or "").strip()).casefold():r["id"]
                           for r in con.execute("SELECT id,name FROM projects").fetchall()}
        for ar in con.execute("SELECT id,name,updated_by FROM actions WHERE project_id IS NULL ORDER BY id").fetchall():
            nm=re.sub(r"\s+"," ",(ar["name"] or "").strip())
            if not nm:
                continue
            key=nm.casefold()
            pid=existing_projects.get(key)
            if not pid:
                pid=con.execute("INSERT INTO projects(name,created_by) VALUES(?,?)",(nm,ar["updated_by"] or "")).lastrowid
                existing_projects[key]=pid
            con.execute("UPDATE actions SET project_id=? WHERE id=?",(pid,ar["id"]))

        # Finální kontrola vazeb Adresář → Společnosti; historie se nemění.
        if has_column(con,"people","company_name"):
            for pr in con.execute("""SELECT id,company_name FROM people
                                     WHERE company_id IS NULL AND trim(coalesce(company_name,''))<>''""").fetchall():
                hits=con.execute("""SELECT id FROM companies WHERE active=1 AND
                    (lower(trim(short_name))=lower(trim(?)) OR lower(trim(official_name))=lower(trim(?)))""",
                    (pr["company_name"],pr["company_name"])).fetchall()
                ids=list(dict.fromkeys(x["id"] for x in hits))
                if len(ids)==1:con.execute("UPDATE people SET company_id=? WHERE id=?",(ids[0],pr["id"]))

        # Adresář používá stabilní company_id. Existující platné vazby se zachovávají.
        # Neprovádíme žádné hádání podle názvu ani přepis uživatelských kontaktů.
        # Kontrola vazeb Adresář osob → Společnosti podle stabilní firemní identity.
        # ARES údaje (zejména IČO) jsou vlastností záznamu Společnosti; osoby se na něj
        # vážou přes company_id. Kontaktní údaje osoby se nikdy nepřepisují.
        people_cols={r[1] for r in con.execute("PRAGMA table_info(people)").fetchall()}

        # Odpojit pouze neplatné odkazy.
        con.execute("""UPDATE people SET company_id=NULL
                       WHERE company_id IS NOT NULL
                         AND company_id NOT IN (SELECT id FROM companies)""")

        # Starší databáze mohou mít vedle company_id ještě textový název firmy.
        # Ten použijeme jen tehdy, když vede k právě jedné společnosti.
        hist_company_col=next((x for x in ("company_name","company") if x in people_cols),None)
        if hist_company_col:
            for p in con.execute(f"""SELECT id,{hist_company_col} company_text
                                     FROM people
                                     WHERE company_id IS NULL
                                       AND trim(coalesce({hist_company_col},''))<>''""").fetchall():
                raw=(p["company_text"] or "").strip()
                matches=con.execute("""SELECT id FROM companies
                                       WHERE active=1 AND
                                       (lower(trim(short_name))=lower(trim(?))
                                        OR lower(trim(official_name))=lower(trim(?)))""",
                                    (raw,raw)).fetchall()
                ids={m["id"] for m in matches}
                if len(ids)==1:
                    con.execute("UPDATE people SET company_id=? WHERE id=?",(next(iter(ids)),p["id"]))

        # Pokud starší záznam osoby obsahuje IČO firmy, má přednost před názvem.
        person_ico_col=next((x for x in ("company_ico","ico_company") if x in people_cols),None)
        if person_ico_col:
            for p in con.execute(f"""SELECT id,{person_ico_col} company_ico
                                     FROM people
                                     WHERE trim(coalesce({person_ico_col},''))<>''""").fetchall():
                hits=con.execute("""SELECT id FROM companies
                                    WHERE active=1 AND trim(coalesce(ico,''))=trim(?)""",
                                 (p["company_ico"],)).fetchall()
                ids={m["id"] for m in hits}
                if len(ids)==1:
                    con.execute("UPDATE people SET company_id=? WHERE id=?",(next(iter(ids)),p["id"]))

        # Seed material list from historical requests
        for r in con.execute("SELECT DISTINCT trim(item) x FROM requests WHERE trim(coalesce(item,''))<>''"):
            con.execute("INSERT OR IGNORE INTO materials(name) VALUES(?)",(r["x"],))
        # Jednorázově vytvořit základ historie i ze starších dat, pokud historie ještě neexistuje.
        if con.execute("SELECT COUNT(*) FROM action_history").fetchone()[0]==0:
            for a in con.execute("SELECT id,created_date,updated_by FROM actions"):
                created=(a["created_date"]+" 08:00:00") if a["created_date"] else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                con.execute("""INSERT INTO action_history(action_id,created_at,user_name,event_type,summary,details)
                    VALUES(?,?,?,?,?,?)""",(a["id"],created,a["updated_by"] or "Historický záznam","legacy_action","Akce existovala před zavedením historie",""))
            for r in con.execute("""SELECT r.id,r.action_id,r.asked_date,r.updated_by,r.item,r.recipients_snapshot,r.company_id,c.official_name company
                FROM requests r LEFT JOIN companies c ON c.id=r.company_id WHERE r.action_id IS NOT NULL"""):
                created=(r["asked_date"]+" 12:00:00") if r["asked_date"] else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                detail=f"Společnost: {r['company'] or '—'}; Poptáváno: {r['item'] or '—'}; Příjemci: {r['recipients_snapshot'] or '—'}"
                con.execute("""INSERT INTO action_history(action_id,created_at,user_name,event_type,summary,details,related_company_id,related_request_id)
                    VALUES(?,?,?,?,?,?,?,?)""",(r["action_id"],created,r["updated_by"] or "Historický záznam","legacy_request","Historická poptávka",detail,r["company_id"],r["id"]))

        # Číselník funkcí Osob: základní nabídka + všechny dosavadní hodnoty.
        for _role in ("Stavbyvedoucí","Jednatel","Obchodní zástupce","Projektant",
                      "Přípravář","Nákupčí","Rozpočtář","Mistr","Technik","Asistent/ka"):
            con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(_role,))
        for _r in con.execute("SELECT DISTINCT trim(role) role FROM people WHERE trim(coalesce(role,''))<>''").fetchall():
            con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(_r["role"],))

        # Bezpečná deduplikace Osob:
        # 1) stejný neprázdný e-mail, 2) u kontaktů bez e-mailu stejné jméno + společnost.
        _groups=con.execute("""SELECT lower(trim(email)) k,MIN(id) keep_id
                               FROM people WHERE trim(coalesce(email,''))<>''
                               GROUP BY lower(trim(email)) HAVING COUNT(*)>1""").fetchall()
        for _g in _groups:
            keep=_g["keep_id"]
            for _dup in con.execute("SELECT id FROM people WHERE lower(trim(email))=? AND id<>?",(_g["k"],keep)).fetchall():
                d=_dup["id"]
                con.execute("""UPDATE people SET
                    name=CASE WHEN trim(coalesce(name,''))='' THEN coalesce((SELECT name FROM people WHERE id=?),'') ELSE name END,
                    phone=CASE WHEN trim(coalesce(phone,''))='' THEN coalesce((SELECT phone FROM people WHERE id=?),'') ELSE phone END,
                    role=CASE WHEN trim(coalesce(role,''))='' THEN coalesce((SELECT role FROM people WHERE id=?),'') ELSE role END,
                    note=CASE WHEN trim(coalesce(note,''))='' THEN coalesce((SELECT note FROM people WHERE id=?),'') ELSE note END,
                    company_id=coalesce(company_id,(SELECT company_id FROM people WHERE id=?)),
                    active=max(active,coalesce((SELECT active FROM people WHERE id=?),0))
                    WHERE id=?""",(d,d,d,d,d,d,keep))
                con.execute("DELETE FROM people WHERE id=?",(d,))
        _groups2=con.execute("""SELECT lower(trim(name)) n,coalesce(company_id,-1) c,MIN(id) keep_id
                                FROM people
                                WHERE trim(coalesce(email,''))='' AND trim(coalesce(name,''))<>''
                                GROUP BY lower(trim(name)),coalesce(company_id,-1)
                                HAVING COUNT(*)>1""").fetchall()
        for _g in _groups2:
            keep=_g["keep_id"]
            for _dup in con.execute("""SELECT id FROM people
                                       WHERE trim(coalesce(email,''))=''
                                         AND lower(trim(name))=? AND coalesce(company_id,-1)=?
                                         AND id<>?""",(_g["n"],_g["c"],keep)).fetchall():
                con.execute("DELETE FROM people WHERE id=?",(_dup["id"],))

        # Starý stav "Čekám na dodavatele" už není hlavním stavem Příležitosti.
        # Čekání se nyní odvozuje samostatně z neobdržených Poptávek.
        con.execute("UPDATE actions SET status='Rozpracováno' WHERE status='Čekám na dodavatele'")

        # Sloučení přesných duplicit společností (stejný oficiální název bez ohledu na velikost písmen/mezer).
        dup_groups=con.execute("""SELECT lower(trim(official_name)) k,MIN(id) keep_id
                                  FROM companies
                                  WHERE trim(coalesce(official_name,''))<>''
                                  GROUP BY lower(trim(official_name))
                                  HAVING COUNT(*)>1""").fetchall()
        for dg in dup_groups:
            keep_id=dg["keep_id"]
            dup_ids=[r["id"] for r in con.execute(
                "SELECT id FROM companies WHERE lower(trim(official_name))=? AND id<>?",(dg["k"],keep_id)).fetchall()]
            for did in dup_ids:
                con.execute("UPDATE people SET company_id=? WHERE company_id=?",(keep_id,did))
                con.execute("UPDATE actions SET company_id=? WHERE company_id=?",(keep_id,did))
                con.execute("UPDATE requests SET company_id=? WHERE company_id=?",(keep_id,did))
                if has_column(con,"requests","requested_for_company_id"):
                    con.execute("UPDATE requests SET requested_for_company_id=? WHERE requested_for_company_id=?",(keep_id,did))
                if has_column(con,"action_history","related_company_id"):
                    con.execute("UPDATE action_history SET related_company_id=? WHERE related_company_id=?",(keep_id,did))
                con.execute("DELETE FROM companies WHERE id=?",(did,))

        # Indexy pro nejčastější vazby, filtry a obnovování tabulek.
        con.executescript("""
        CREATE INDEX IF NOT EXISTS idx_actions_company ON actions(company_id);
        CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project_id);
        CREATE INDEX IF NOT EXISTS idx_actions_created ON actions(created_date);
        CREATE INDEX IF NOT EXISTS idx_actions_deadline ON actions(deadline);
        CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
        CREATE INDEX IF NOT EXISTS idx_requests_company ON requests(company_id);
        CREATE INDEX IF NOT EXISTS idx_requests_customer ON requests(requested_for_company_id);
        CREATE INDEX IF NOT EXISTS idx_requests_action ON requests(action_id);
        CREATE INDEX IF NOT EXISTS idx_requests_asked ON requests(asked_date);
        CREATE INDEX IF NOT EXISTS idx_requests_active ON requests(archived,no_response,received_date);
        CREATE INDEX IF NOT EXISTS idx_people_company ON people(company_id);
        CREATE INDEX IF NOT EXISTS idx_people_email ON people(email);
        CREATE INDEX IF NOT EXISTS idx_tasks_action ON tasks(action_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(done,due_date);
        CREATE INDEX IF NOT EXISTS idx_history_action ON action_history(action_id);
        CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(name);
        CREATE INDEX IF NOT EXISTS idx_companies_official ON companies(official_name);
        """)

        con.executescript("""
        CREATE TABLE IF NOT EXISTS supplier_offers(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          offer_date TEXT DEFAULT '',
          supplier_company_id INTEGER,
          customer_company_id INTEGER,
          action_id INTEGER,
          offer_number TEXT DEFAULT '',
          total_value REAL DEFAULT 0,
          currency TEXT DEFAULT 'CZK',
          validity_date TEXT DEFAULT '',
          status TEXT DEFAULT 'Importováno',
          source_pdf TEXT DEFAULT '',
          source_hash TEXT DEFAULT '',
          raw_text TEXT DEFAULT '',
          note TEXT DEFAULT '',
          imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_by TEXT DEFAULT '',
          FOREIGN KEY(supplier_company_id) REFERENCES companies(id),
          FOREIGN KEY(customer_company_id) REFERENCES companies(id),
          FOREIGN KEY(action_id) REFERENCES actions(id)
        );
        CREATE TABLE IF NOT EXISTS supplier_offer_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          offer_id INTEGER NOT NULL,
          position INTEGER DEFAULT 0,
          original_name TEXT DEFAULT '',
          item_key TEXT DEFAULT '',
          quantity REAL DEFAULT 0,
          unit TEXT DEFAULT '',
          unit_price REAL DEFAULT 0,
          discount REAL DEFAULT 0,
          net_price REAL DEFAULT 0,
          total_price REAL DEFAULT 0,
          image_path TEXT DEFAULT '',
          image_source_offer_date TEXT DEFAULT '',
          image_blob BLOB,
          image_ext TEXT DEFAULT '',
          product_code TEXT DEFAULT '',
          details TEXT DEFAULT '',
          original_unit_price REAL DEFAULT 0,
          discount_pct REAL DEFAULT 0,
          FOREIGN KEY(offer_id) REFERENCES supplier_offers(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS offer_item_aliases(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          item_key TEXT NOT NULL,
          alias TEXT NOT NULL,
          UNIQUE(item_key,alias)
        );
        CREATE INDEX IF NOT EXISTS idx_supplier_offers_date ON supplier_offers(offer_date);
        CREATE INDEX IF NOT EXISTS idx_supplier_offers_action ON supplier_offers(action_id);
        CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_offer ON supplier_offer_items(offer_id);
        CREATE INDEX IF NOT EXISTS idx_supplier_offer_items_key ON supplier_offer_items(item_key);
        CREATE TABLE IF NOT EXISTS offer_product_aliases(
          supplier TEXT NOT NULL,
          alias TEXT NOT NULL,
          canonical_key TEXT NOT NULL,
          first_seen TEXT DEFAULT '',
          last_seen TEXT DEFAULT '',
          PRIMARY KEY(supplier,alias)
        );
        CREATE TABLE IF NOT EXISTS offer_product_images(
          supplier TEXT NOT NULL,
          item_key TEXT NOT NULL,
          image_blob BLOB NOT NULL,
          image_ext TEXT DEFAULT '',
          source_offer_no TEXT DEFAULT '',
          source_offer_date TEXT DEFAULT '',
          image_hash TEXT DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(supplier,item_key)
        );
        """)
        _supplier_offer_cols={r[1] for r in con.execute("PRAGMA table_info(supplier_offers)")}
        for _col,_def in (
            ("supplier_name","TEXT DEFAULT ''"),("source_type","TEXT DEFAULT 'PDF'"),
            ("reference","TEXT DEFAULT ''"),("gross_value","REAL DEFAULT 0"),
            ("discount_pct","REAL DEFAULT 0"),("net_value","REAL DEFAULT 0")
        ):
            if _col not in _supplier_offer_cols:
                con.execute(f"ALTER TABLE supplier_offers ADD COLUMN {_col} {_def}")
        _offer_cols={r[1] for r in con.execute("PRAGMA table_info(supplier_offer_items)")}
        for _col,_def in (
            ("image_blob","BLOB"),("image_ext","TEXT DEFAULT ''"),("product_code","TEXT DEFAULT ''"),
            ("details","TEXT DEFAULT ''"),("original_unit_price","REAL DEFAULT 0"),("discount_pct","REAL DEFAULT 0")
        ):
            if _col not in _offer_cols:
                con.execute(f"ALTER TABLE supplier_offer_items ADD COLUMN {_col} {_def}")
        con.execute("""CREATE TABLE IF NOT EXISTS app_meta(
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )""")
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version','5.7')")

def find_or_create_company(con,name,ico=""):
    name=(name or "").strip()
    if not name:return None
    if ico:
        r=con.execute("SELECT id FROM companies WHERE ico=?",(ico.strip(),)).fetchone()
        if r:return r[0]
    nn=norm_name(name)
    for r in con.execute("SELECT id,short_name,official_name FROM companies WHERE active=1"):
        if norm_name(r["official_name"] or r["short_name"])==nn:return r["id"]
    return con.execute("INSERT INTO companies(short_name,official_name,ico) VALUES(?,?,?)",(name,name,ico or "")).lastrowid

def log_history(action_id,event_type,summary,details="",company_id=None,request_id=None,user_name=None,related_request_id=None):
    if not action_id:
        return
    if related_request_id is not None and request_id is None:
        request_id=related_request_id
    user_name=user_name or get_setting("active_user","")
    with db() as con:
        con.execute("""INSERT INTO action_history(
            action_id,created_at,user_name,event_type,summary,details,related_company_id,related_request_id
        ) VALUES(?,CURRENT_TIMESTAMP,?,?,?,?,?,?)""",
        (action_id,user_name,event_type,summary,details or "",company_id,request_id))


def mivo_company_ids(con):
    """ID firem odpovídajících MIVO, včetně historických variant oficiálního názvu."""
    rows=con.execute("""SELECT id,official_name,short_name FROM companies
                        WHERE active=1 OR active=0""").fetchall()
    ids=[]
    for r in rows:
        off=(r["official_name"] or "").strip().casefold()
        short=(r["short_name"] or "").strip().casefold()
        if short=="mivo" or off=="mivo" or off.startswith("mivo ") or off.startswith("mivo,") or off.startswith("mivo."):
            ids.append(r["id"])
    return ids

def request_wait_date(value,received=""):
    """Datum Poptáno bez textového varování; dlouhé čekání zvýrazňuje pouze buňku."""
    return fmt_date(value)

def request_is_overdue(value,received=""):
    if not value or received:return False
    try:
        return (date.today()-datetime.strptime(value,"%Y-%m-%d").date()).days>=7
    except Exception:
        return False

def get_setting(key,default=""):
    with db() as con:
        r=con.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone()
        return r[0] if r else default

def set_setting(key,value):
    with db() as con: con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",(key,str(value)))

def get_user_setting(user_name,key,default=""):
    if not user_name:
        return default
    with db() as con:
        r=con.execute("SELECT value FROM user_settings WHERE user_name=? AND key=?",(user_name,key)).fetchone()
        return r[0] if r else default

def set_user_setting(user_name,key,value):
    if not user_name:
        return
    with db() as con:
        con.execute("INSERT OR REPLACE INTO user_settings(user_name,key,value) VALUES(?,?,?)",(user_name,key,str(value)))

def parse_date(s):
    s=(s or "").strip()
    if not s:return ""
    for f in ("%Y-%m-%d","%d.%m.%Y","%d/%m/%Y"):
        try:return datetime.strptime(s,f).strftime("%Y-%m-%d")
        except:pass
    return s

def parse_filter_date(s):
    s=(s or "").strip()
    if not s:return None
    for f in ("%Y-%m-%d","%d.%m.%Y","%d/%m/%Y","%d.%m.%y"):
        try:return datetime.strptime(s,f).date()
        except:pass
    return None

def date_matches(value,mode,filter_value):
    if not filter_value:return True
    d=parse_filter_date(value)
    f=parse_filter_date(filter_value)
    if not d or not f:return False
    if mode=="Dříve než":return d < f
    if mode=="Později než":return d > f
    if mode=="Do data":return d <= f
    if mode=="Od data":return d >= f
    return d == f

def fmt_history_datetime(value):
    """SQLite CURRENT_TIMESTAMP is UTC; history is displayed in Europe/Prague."""
    if not value:return ""
    try:
        raw=str(value).strip().replace("Z","+00:00")
        dt=datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Europe/Prague")).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)

def fmt_date(s):
    if not s:return ""
    try:return datetime.strptime(s,"%Y-%m-%d").strftime("%d.%m.%Y")
    except:return s

def subject_date(s):
    s=parse_date(s) or date.today().isoformat()
    try:
        d=datetime.strptime(s,"%Y-%m-%d")
        return f"{d.day}.{d.month}.{d.year}"
    except:return s

def build_subject(company_short,action,item,asked,include_action):
    parts=["Poptávka TURTO",company_short]
    if include_action and action:parts.append(action)
    if item:parts.append(item)
    parts.append(subject_date(asked))
    return " - ".join([p for p in parts if p])

EMAIL_BODY="Dobrý den,\r\n\r\n\r\n\r\nPředem velice děkuji,"

def open_mail_draft(recipients,subject,cc=CC_ALWAYS):
    recipients=[x.strip() for x in recipients if x and x.strip()]

    if sys.platform.startswith("win"):
        env=os.environ.copy()
        env["ZAK_TO"]=";".join(recipients)
        env["ZAK_CC"]=cc or ""
        env["ZAK_SUBJECT"]=subject or ""
        env["ZAK_BODY"]=EMAIL_BODY
        ps=r"""
$ErrorActionPreference='Stop'
try {
  $ol=[Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
} catch {
  $ol=New-Object -ComObject Outlook.Application
}
$mail=$ol.CreateItem(0)
# Display first: Outlook applies the user's normal new-message editor,
# default stationery/font and configured signature.
$mail.Display()
Start-Sleep -Milliseconds 250
$mail.To=$env:ZAK_TO
$mail.CC=$env:ZAK_CC
$mail.Subject=$env:ZAK_SUBJECT

# Insert our text at the beginning using WordEditor. This keeps Outlook's
# default formatting and leaves the automatically prepared signature below.
try {
  $insp=$mail.GetInspector
  $editor=$insp.WordEditor
  $rng=$editor.Range(0,0)
  $rng.InsertBefore($env:ZAK_BODY + "`r`n")
} catch {
  # Fallback still preserves an already-created signature.
  $existing=$mail.HTMLBody
  $safe=[System.Net.WebUtility]::HtmlEncode($env:ZAK_BODY).Replace("`r`n","<br>")
  $mail.HTMLBody="<div>"+$safe+"</div>"+$existing
}
# Return the exact Inspector HWND to the CRM process. Calling Activate() only
# inside this PowerShell child is not sufficient on Windows because foreground
# activation may be refused for a non-foreground child process.
try {
  $insp=$mail.GetInspector
  $insp.Activate()
  Write-Output ("TURTO_OUTLOOK_HWND=" + [string]$insp.HWND)
} catch {}
"""
        try:
            r=subprocess.run(["powershell.exe","-NoProfile","-STA","-Command",ps],
                             env=env,capture_output=True,text=True,timeout=20,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if r.returncode==0:
                # CRM itself is the foreground process that initiated the user action,
                # so let CRM bring the exact Outlook Inspector to the foreground.
                try:
                    m=re.search(r'TURTO_OUTLOOK_HWND=(\d+)',r.stdout or '')
                    if m:
                        hwnd=int(m.group(1))
                        try:
                            import win32con,win32gui
                            if win32gui.IsWindow(hwnd):
                                win32gui.ShowWindow(hwnd,win32con.SW_RESTORE)
                                win32gui.SetWindowPos(
                                    hwnd,win32con.HWND_TOP,0,0,0,0,
                                    win32con.SWP_NOMOVE|win32con.SWP_NOSIZE|win32con.SWP_SHOWWINDOW)
                                try:win32gui.BringWindowToTop(hwnd)
                                except Exception:pass
                                try:win32gui.SetForegroundWindow(hwnd)
                                except Exception:pass
                                # If Windows focus-lock still refuses the foreground call,
                                # pulse topmost and use SwitchToThisWindow as a final fallback.
                                if win32gui.GetForegroundWindow()!=hwnd:
                                    try:
                                        win32gui.SetWindowPos(hwnd,win32con.HWND_TOPMOST,0,0,0,0,win32con.SWP_NOMOVE|win32con.SWP_NOSIZE)
                                        win32gui.SetWindowPos(hwnd,win32con.HWND_NOTOPMOST,0,0,0,0,win32con.SWP_NOMOVE|win32con.SWP_NOSIZE|win32con.SWP_SHOWWINDOW)
                                    except Exception:pass
                                    try:
                                        import ctypes
                                        ctypes.windll.user32.SwitchToThisWindow(hwnd,True)
                                    except Exception:pass
                        except Exception:
                            try:
                                import ctypes
                                user32=ctypes.windll.user32
                                user32.ShowWindow(hwnd,9)
                                user32.BringWindowToTop(hwnd)
                                if not user32.SetForegroundWindow(hwnd):
                                    user32.SwitchToThisWindow(hwnd,True)
                            except Exception:pass
                except Exception:pass
                return True
            detail=(r.stderr or r.stdout or "").strip()
            messagebox.showerror("Outlook",
                "Nepodařilo se vytvořit koncept v klasickém Outlooku.\n\n"
                f"Detail: {detail[:900] or 'Outlook COM není dostupný.'}")
            return False
        except Exception as e:
            messagebox.showerror("Outlook",f"Nepodařilo se vytvořit koncept:\n{e}")
            return False

    # Na jiných systémech vytvoříme koncept i bez pole Komu.
    to=";".join(recipients)
    url="mailto:"+quote(to,safe="@;,.") + "?" + urlencode(
        {"cc":cc,"subject":subject,"body":EMAIL_BODY},quote_via=quote)
    try:
        webbrowser.open(url);return True
    except Exception as e:
        messagebox.showerror("E-mail",str(e));return False


# ---------- ARES ----------
ARES_SEARCH="https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/vyhledat"
ARES_DETAIL="https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/"

def ares_detail(ico):
    req=urllib.request.Request(ARES_DETAIL+str(ico).strip(),headers={"User-Agent":"TURTO-Zakazky/0.7"})
    with urllib.request.urlopen(req,timeout=8) as resp:
        return json.load(resp)

def ares_search(q,limit=12):
    q=(q or "").strip()
    if not q:return []
    if q.isdigit() and len(q)==8:
        try:return [ares_detail(q)]
        except:return []
    body=json.dumps({"obchodniJmeno":q,"start":0,"pocet":limit}).encode("utf-8")
    req=urllib.request.Request(ARES_SEARCH,data=body,method="POST",
        headers={"Content-Type":"application/json","Accept":"application/json","User-Agent":"TURTO-Zakazky/0.7"})
    with urllib.request.urlopen(req,timeout=10) as resp:
        data=json.load(resp)
    return data.get("ekonomickeSubjekty") or data.get("ekonomickeSubjektySeznam") or []

def _first_nonempty(d,*keys):
    for k in keys:
        v=d.get(k)
        if v not in (None,"",[],{}): return v
    return ""

def _stringify_code(v):
    if isinstance(v,dict):
        return str(_first_nonempty(v,"kod","code","nazev","name") or "")
    if isinstance(v,list):
        return ", ".join(str(_stringify_code(x)) for x in v if _stringify_code(x))
    return str(v or "")

def ares_company_data(x):
    sidlo=x.get("sidlo") or {}
    addr=sidlo.get("textovaAdresa") or ""
    if not addr:
        bits=[sidlo.get("nazevUlice"),sidlo.get("cisloDomovni"),sidlo.get("cisloOrientacni"),
              sidlo.get("nazevCastiObce"),sidlo.get("nazevObce"),sidlo.get("psc")]
        addr=" ".join(str(b) for b in bits if b)
    return {
      "official_name":x.get("obchodniJmeno","") or "",
      "short_name":x.get("obchodniJmeno","") or "",
      "ico":str(x.get("ico","") or ""),
      "dic":str(_first_nonempty(x,"dic","dicSeznam") or ""),
      "address":addr or "",
      "legal_form":_stringify_code(_first_nonempty(x,"pravniForma","pravniFormaRos")),
      "date_created":str(_first_nonempty(x,"datumVzniku","datumZalozeni") or ""),
      "ares_last_change":str(_first_nonempty(x,"datumAktualizace","datumPosledniZmeny","datumZmeny","posledniZmena") or ""),
      "cz_nace":_stringify_code(_first_nonempty(x,"czNace","czNacePrevladajici","prevazujiciCzNace","nace")),
      "financial_office":_stringify_code(_first_nonempty(x,"financniUrad","financniUradKod","kodFinancnihoUradu")),
      "district":_stringify_code(_first_nonempty(sidlo,"nazevOkresu","okresNazev","okres") or _first_nonempty(x,"okres","okresNazev")),
      "municipality":_stringify_code(_first_nonempty(sidlo,"nazevObce","obecNazev","obec")),
      "ares_checked":date.today().isoformat(),
      "ares_raw_json":json.dumps(x,ensure_ascii=False,sort_keys=True)
    }



def import_mail_contacts_v220_once():
    marker="mail_contacts_v220_imported"
    with db() as con:
        if con.execute("SELECT value FROM app_meta WHERE key=?",(marker,)).fetchone():return
    path=ROOT/"seed"/"mail_contacts_v220.json"
    if not path.exists():return
    try: records=json.loads(path.read_text(encoding="utf-8"))
    except Exception:return
    with db() as con:
        for rec in records:
            email=(rec.get("email") or "").strip().lower()
            if not email:continue
            existing=con.execute("SELECT id FROM people WHERE lower(trim(email))=? LIMIT 1",(email,)).fetchone()
            cname=(rec.get("company") or "").strip(); cid=None
            if cname:
                cr=con.execute("""SELECT id FROM companies WHERE active=1 AND lower(trim(official_name))=lower(trim(?)) ORDER BY id LIMIT 1""",(cname,)).fetchone()
                if cr:cid=cr["id"]
                else:cid=con.execute("INSERT INTO companies(short_name,official_name,active) VALUES(?,?,1)",(cname,cname)).lastrowid
            role=(rec.get("role") or "").strip()
            if role:con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(role,))
            if existing:
                # Never overwrite populated user data; only fill missing fields/company.
                con.execute("""UPDATE people SET
                    name=CASE WHEN trim(coalesce(name,''))='' THEN ? ELSE name END,
                    phone=CASE WHEN trim(coalesce(phone,''))='' THEN ? ELSE phone END,
                    role=CASE WHEN trim(coalesce(role,''))='' THEN ? ELSE role END,
                    company_id=coalesce(company_id,?),active=1 WHERE id=?""",
                    (rec.get("name",""),rec.get("phone",""),role,cid,existing["id"]))
            else:
                con.execute("INSERT INTO people(name,email,phone,role,company_id,note,active) VALUES(?,?,?,?,?,'Import z e-mailové komunikace',1)",
                    (rec.get("name",""),email,rec.get("phone",""),role,cid))
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)",(marker,date.today().isoformat()))


def import_mail_contacts_v221_once():
    marker="mail_contacts_v221_imported"
    with db() as con:
        if con.execute("SELECT value FROM app_meta WHERE key=?",(marker,)).fetchone():return
    path=ROOT/"seed"/"mail_contacts_v221.json"
    if not path.exists():return
    try: records=json.loads(path.read_text(encoding="utf-8"))
    except Exception:return
    with db() as con:
        for rec in records:
            email=(rec.get("email") or "").strip().lower()
            if not email:continue
            existing=con.execute("SELECT id FROM people WHERE lower(trim(email))=? LIMIT 1",(email,)).fetchone()
            cname=(rec.get("company") or "").strip();cid=None
            if cname:
                cr=con.execute("SELECT id FROM companies WHERE active=1 AND lower(trim(official_name))=lower(trim(?)) ORDER BY id LIMIT 1",(cname,)).fetchone()
                if cr:cid=cr["id"]
                else:cid=con.execute("INSERT INTO companies(short_name,official_name,active) VALUES(?,?,1)",(cname,cname)).lastrowid
            role=(rec.get("role") or "").strip()
            if role:con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(role,))
            if existing:
                con.execute("""UPDATE people SET name=CASE WHEN trim(coalesce(name,''))='' THEN ? ELSE name END,
                    phone=CASE WHEN trim(coalesce(phone,''))='' THEN ? ELSE phone END,
                    role=CASE WHEN trim(coalesce(role,''))='' THEN ? ELSE role END,
                    company_id=coalesce(company_id,?),active=1 WHERE id=?""",
                    (rec.get("name",""),rec.get("phone",""),role,cid,existing["id"]))
            else:
                con.execute("INSERT INTO people(name,email,phone,role,company_id,note,active) VALUES(?,?,?,?,?,'Import z e-mailové komunikace – mail2',1)",
                    (rec.get("name",""),email,rec.get("phone",""),role,cid))
        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)",(marker,date.today().isoformat()))


def _normalize_person_role_v222(role):
    s=(role or "").strip()
    if not s:return ""
    low=unicodedata.normalize("NFKD",s)
    low="".join(c for c in low if not unicodedata.combining(c)).lower()
    if len(s)>95 or "@ " in s or "<mailto" in low or low.startswith(("from:","to:","od:","komu:")):
        return ""
    if any(x in low for x in ("projektant nepovolil","tak jsem to proveroval","technik si toho")):
        return ""
    if "interni uzivatel" in low:return "Interní uživatel"
    if "stavbyved" in low:return "Stavbyvedoucí"
    if "priprav" in low:return "Přípravář"
    if "rozpoc" in low or "cost manager" in low:return "Rozpočtář"
    if "sales technical" in low or "obchodne techn" in low:return "Obchodně technický zástupce"
    if any(x in low for x in ("area sales manager","sales manager","team leader sales","obchodni manazer","obchodni manager")):
        return "Obchodní manažer"
    if "sales representative" in low or "obchodni zastup" in low:return "Obchodní zástupce"
    if "sales support" in low or "sales department" in low or "export department" in low:return "Obchodní podpora"
    if any(x in low for x in ("project manager","projektovy man","vedouci projektu","project leader","manazer projektu","manager projektu")):
        return "Projektový manažer"
    if "jednatel" in low:return "Jednatel"
    if "vedouci pobock" in low:return "Vedoucí pobočky"
    if "vyrobni" in low and ("reditel" in low or "vedouci" in low):return "Vedoucí výroby"
    if "vedouci armov" in low:return "Vedoucí výroby"
    if "product manager" in low or "produktovy man" in low:return "Produktový manažer"
    if any(x in low for x in ("nakup","buyer","procurement")):return "Nákupčí"
    if "asistent" in low:return "Asistent/ka"
    if "projektant" in low or "statik" in low:return "Projektant"
    if "technik" in low:return "Technik"
    if "reditel" in low or re.search(r"\\bceo\\b",low):return "Ředitel"
    if "vedouci" in low:return "Vedoucí oddělení"
    if "e-shop" in low or "eshop" in low:return "Obchodní manažer"
    return ""

def post_import_cleanup_v222_once():
    """Jednorázový bezpečný úklid po mailových importech + konzervativní doplnění prázdných údajů."""
    marker="post_import_cleanup_v222"
    with db() as con:
        if con.execute("SELECT value FROM app_meta WHERE key=?",(marker,)).fetchone():
            return

        # 1) Zjednodušení funkcí osob.
        rows=con.execute("SELECT id,role FROM people").fetchall()
        for r in rows:
            nr=_normalize_person_role_v222(r["role"])
            if nr!=(r["role"] or "").strip():
                con.execute("UPDATE people SET role=? WHERE id=?",(nr,r["id"]))
        con.execute("DELETE FROM person_roles")
        roles=[r["role"] for r in con.execute("""SELECT DISTINCT trim(role) role FROM people
                                                WHERE trim(coalesce(role,''))<>''
                                                ORDER BY trim(role) COLLATE CZECH""").fetchall()]
        for role in roles:
            con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(role,))

        # 2) První spolehlivě dohledatelný kontakt k Příležitosti z obou exportů pošty.
        # Hodnoty se zapisují pouze tam, kde je Přijato stále prázdné.
        received=[
            ("BD Čimická","MONOKON s.r.o.","2026-01-27"),
            ("Stromovka Kladno","FERI, s.r.o.","2026-06-11"),
            ("Za Valem D1,D2,D3, I","Hinton, a.s.","2026-08-11"),
            ("BD Vršovice","FORMET","2025-11-20"),
            ("Linecká čtvrť - České Budějovice","Metrostav a.s.","2026-07-07"),
            ("BD U Pivovaru II - Benešov","PP 53, a.s.","2026-04-20"),
            ("Nový Rohan E6","Metrostav, divize 6","2026-04-24"),
            ("Na Plzeňce","PORR a.s.","2026-02-13"),
        ]
        for name,company,dt in received:
            con.execute("""UPDATE actions SET created_date=?
                           WHERE trim(coalesce(created_date,''))=''
                             AND lower(trim(name))=lower(trim(?))
                             AND company_id IN (
                               SELECT id FROM companies WHERE lower(trim(official_name))=lower(trim(?))
                                  OR lower(trim(short_name))=lower(trim(?))
                             )""",(dt,name,company,company))
        # Interně zachycená akce bez jisté zákaznické společnosti.
        con.execute("""UPDATE actions SET created_date='2026-03-03'
                       WHERE trim(coalesce(created_date,''))=''
                         AND lower(trim(name))=lower('FN Plzeň - pavilon chirurgických oborů')""")

        # 3) Adresa/lokalita jen tam, kde je přímo a jednoznačně obsažena v názvu akce.
        localities={
            "Stromovka Kladno":"Kladno",
            "BD Beroun":"Beroun",
            "BD U Pivovaru II - Benešov":"Benešov",
            "Linecká čtvrť - České Budějovice":"České Budějovice",
            "Nová Linecká čtvrť - České Budějovice":"České Budějovice",
            "FN Plzeň - pavilon chirurgických oborů":"Plzeň",
        }
        for name,loc in localities.items():
            con.execute("""UPDATE projects SET address=?
                           WHERE trim(coalesce(address,''))=''
                             AND lower(trim(name))=lower(trim(?))""",(loc,name))

        con.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES(?,?)",
                    (marker,date.today().isoformat()))

# ---------- widgets ----------
_AUTOCOMPLETE_ENTRIES=[]

def close_autocomplete_popups_on_click(event):
    """Kliknutí mimo našeptávač zavře jeho rozbalenou nabídku."""
    for entry in list(_AUTOCOMPLETE_ENTRIES):
        try:
            if not entry.winfo_exists():
                _AUTOCOMPLETE_ENTRIES.remove(entry);continue
            if not entry.popup or not entry.popup.winfo_exists() or not entry.popup.winfo_viewable():
                continue
            w=getattr(event,"widget",None)
            if w is entry:
                continue
            cur=w
            inside_popup=False
            while cur is not None:
                if cur is entry.popup:
                    inside_popup=True;break
                try:cur=cur.master
                except Exception:break
            if not inside_popup:
                entry.hide()
        except Exception:
            pass

class AutocompleteEntry(ttk.Entry):
    """Stabilní našeptávač s vlastním seznamem výsledků."""
    def __init__(self,master,values=(),textvariable=None,**kw):
        self.var=textvariable or tk.StringVar()
        super().__init__(master,textvariable=self.var,**kw)
        self.values=[]
        self.payload_map={}
        for v in values:
            if isinstance(v,(tuple,list)) and len(v)>=2:
                disp=str(v[0]);self.values.append(disp);self.payload_map[disp]=v[1]
            else:
                disp=str(v)
                if disp.strip():self.values.append(disp)
        self.selected_value=None
        self.selected_payload=None
        self.popup=None; self.listbox=None; self.after_id=None; self._setting=False; self._suppress_show=False
        _AUTOCOMPLETE_ENTRIES.append(self)
        self.var.trace_add("write",self._changed)
        self.bind("<Down>",lambda e:self._navigate(1))
        self.bind("<Up>",lambda e:self._navigate(-1))
        self.bind("<Return>",self._accept_first)
        self.bind("<Escape>",lambda e:self.hide())
        self.bind("<Button-1>",lambda e:self.after_idle(self._show),add="+")
        self.bind("<FocusIn>",lambda e:self.after_idle(self._show),add="+")
        self.bind("<FocusOut>",lambda e:self.after(120,self._hide_if_needed))
        try:
            self.winfo_toplevel().bind("<Configure>",lambda e:self.after_idle(self._reposition_popup),add="+")
        except Exception:
            pass
    def set_values(self,values):
        self.values=[]
        self.payload_map={}
        for v in values:
            if isinstance(v,(tuple,list)) and len(v)>=2:
                disp=str(v[0]);self.values.append(disp);self.payload_map[disp]=v[1]
            else:
                disp=str(v);self.values.append(disp)
    def _matches(self):
        q=self.var.get().strip().lower()
        return [v for v in self.values if q in v.lower()][:60] if q else self.values[:60]
    def _changed(self,*a):
        if self._setting:return
        self.selected_value=None
        self.selected_payload=None
        if self.after_id:
            try:self.after_cancel(self.after_id)
            except:pass
        self.after_id=self.after(70,self._show)
    def _show(self):
        self.after_id=None
        if self._suppress_show:return
        if self.focus_get()!=self:return
        matches=self._matches()
        if not matches:self.hide();return
        if not self.popup or not self.popup.winfo_exists():
            self.popup=tk.Toplevel(self);self.popup.overrideredirect(True);self.popup.attributes("-topmost",True)
            fr=ttk.Frame(self.popup,relief="solid",borderwidth=1);fr.pack(fill="both",expand=True)
            self.listbox=tk.Listbox(fr,height=7,exportselection=False,activestyle="dotbox")
            sb=ttk.Scrollbar(fr,orient="vertical",command=self.listbox.yview);self.listbox.configure(yscrollcommand=sb.set)
            self.listbox.grid(row=0,column=0,sticky="nsew");sb.grid(row=0,column=1,sticky="ns");fr.rowconfigure(0,weight=1);fr.columnconfigure(0,weight=1)
            self.listbox.bind("<ButtonRelease-1>",self._choose)
            self.listbox.bind("<Double-Button-1>",self._choose)
            self.listbox.bind("<Return>",self._choose)
            self.listbox.bind("<Up>",lambda e:self._move_list(-1))
            self.listbox.bind("<Down>",lambda e:self._move_list(1))
            self.listbox.bind("<Escape>",lambda e:self.hide())
        self.listbox.delete(0,"end")
        for v in matches:self.listbox.insert("end",v)
        self.listbox.selection_clear(0,"end");self.listbox.selection_set(0);self.listbox.activate(0)
        self.update_idletasks()
        self.popup.deiconify()
        self._reposition_popup()
        self.popup.lift()
    def _reposition_popup(self):
        """Drží popup u pole i uvnitř scrollovaného Canvasu."""
        try:
            if not self.popup or not self.popup.winfo_exists() or not self.popup.winfo_viewable():
                return
            if not self.winfo_ismapped():
                self.hide();return

            top=self.winfo_toplevel()
            canvas=getattr(top,"_dialog_canvas",None)
            content=getattr(top,"_dialog_content",None)
            ew=max(self.winfo_width(),300)
            eh=self.winfo_height()

            if canvas is not None and content is not None and canvas.winfo_ismapped():
                # U widgetů vložených do Canvasu nejsou winfo_rootx/y po scrollu
                # spolehlivým ukotvením. Spočítáme polohu vůči vnitřnímu rámu
                # a odečteme aktuální posun Canvasu.
                relx=0;rely=0;cur=self
                found=False
                while cur is not None:
                    relx+=cur.winfo_x();rely+=cur.winfo_y()
                    if cur is content:
                        found=True;break
                    try:cur=cur.master
                    except Exception:break

                if found:
                    ex=int(canvas.winfo_rootx()+relx-canvas.canvasx(0))
                    ey=int(canvas.winfo_rooty()+rely-canvas.canvasy(0))
                    cx=canvas.winfo_rootx();cy=canvas.winfo_rooty()
                    cw=canvas.winfo_width();ch=canvas.winfo_height()
                    if ey+eh<=cy or ey>=cy+ch or ex+self.winfo_width()<=cx or ex>=cx+cw:
                        self.hide();return
                else:
                    ex=self.winfo_rootx();ey=self.winfo_rooty()
            else:
                ex=self.winfo_rootx();ey=self.winfo_rooty()

            ph=min(7,max(1,self.listbox.size() if self.listbox else 1))*23+4
            self.popup.geometry(f"{ew}x{ph}+{ex}+{ey+eh}")
        except Exception:
            self.hide()

    def _set(self,value):
        self._setting=True
        try:self.var.set(value)
        finally:self._setting=False
        self.selected_value=value
        self.selected_payload=self.payload_map.get(value)
        self.icursor("end")
        # Výběr je finální akce: zavřít nabídku a zabránit FocusIn v jejím
        # okamžitém znovuotevření po vrácení fokusu do vstupního pole.
        self._suppress_show=True
        self.hide()
        self.focus_set()
        self.after(180,lambda:setattr(self,"_suppress_show",False))
        self.event_generate("<<AutocompleteSelected>>")
    def _choose(self,e=None):
        if not self.listbox:return "break"
        sel=self.listbox.curselection()
        if not sel and e is not None: idx=self.listbox.nearest(e.y)
        elif sel: idx=sel[0]
        else:return "break"
        self._set(self.listbox.get(idx));return "break"
    def _move_list(self,delta):
        if not self.listbox:return "break"
        size=self.listbox.size()
        if not size:return "break"
        sel=self.listbox.curselection()
        cur=sel[0] if sel else (0 if delta>0 else size-1)
        nxt=max(0,min(size-1,cur+delta))
        self.listbox.selection_clear(0,"end")
        self.listbox.selection_set(nxt);self.listbox.activate(nxt);self.listbox.see(nxt)
        return "break"

    def _navigate(self,delta):
        self._show()
        if self.listbox and self.listbox.size():
            self.listbox.focus_set()
            sel=self.listbox.curselection()
            # První stisk ↓ nechá první položku, první ↑ přejde na poslední.
            if delta<0 and sel and sel[0]==0:
                self.listbox.selection_clear(0,"end")
                last=self.listbox.size()-1
                self.listbox.selection_set(last);self.listbox.activate(last);self.listbox.see(last)
            elif delta>0 and sel and sel[0]==0:
                pass
            else:
                self._move_list(delta)
        return "break"

    def _focus_list(self,e=None):
        return self._navigate(1)
    def _accept_first(self,e=None):
        m=self._matches()
        if m:self._set(m[0]);return "break"
    def _hide_if_needed(self):
        try:
            f=self.focus_get()
            if f is self or f is self.listbox:return
        except:pass
        self.hide()
    def hide(self):
        if self.popup:
            try:self.popup.withdraw()
            except:pass


class CompanyDialog(tk.Toplevel):
    def __init__(self,parent,company_id=None):
        super().__init__(parent);enable_dialog_maximize(self,920,560);self.title("Společnost");self.transient(parent);self.grab_set();self.result=None;self.cid=company_id;bind_dialog_keys(self,self.ok)
        vals={}
        if company_id:
            with db() as con:
                r=con.execute("SELECT * FROM companies WHERE id=?",(company_id,)).fetchone()
                if r:vals=dict(r)
        f=scrollable_dialog_frame(self,14)
        self.vars={k:tk.StringVar(value=vals.get(k,"") or "") for k in (
            "short_name","official_name","ico","dic","address","legal_form","web",
            "date_created","ares_last_change","cz_nace","financial_office","district","municipality"
        )}
        ttk.Label(f,text="Hledat v ARES").grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        self.ares_q=tk.StringVar(value=vals.get("official_name","") or vals.get("short_name","") or "")
        ttk.Entry(f,textvariable=self.ares_q,width=62).grid(row=0,column=1,sticky="ew",pady=5)
        ttk.Button(f,text="Vyhledat",command=self.search_ares).grid(row=0,column=2,padx=(6,0))
        self.ares_q.trace_add("write",self.schedule_ares);self.search_after=None;self.search_token=0
        ttk.Label(f,text="ARES výsledky").grid(row=1,column=0,sticky="nw",padx=(0,10),pady=5)
        self.results=tk.Listbox(f,height=4,exportselection=False);self.results.grid(row=1,column=1,columnspan=2,sticky="ew",pady=5)
        self.results.bind("<Double-Button-1>",self.take_ares);self.results.bind("<Return>",self.take_ares);self.ares_results=[]
        self.ares_raw_json=vals.get("ares_raw_json","") or ""
        row=2
        for lab,key in [("Oficiální název","official_name"),("IČO","ico"),("DIČ","dic"),
            ("Sídlo","address"),("Právní forma","legal_form"),("Datum vzniku","date_created"),
            ("Poslední změna ARES","ares_last_change"),("CZ-NACE","cz_nace"),("Finanční úřad","financial_office"),
            ("Okres","district"),("Obec","municipality"),("Web","web")]:
            ttk.Label(f,text=lab).grid(row=row,column=0,sticky="w",padx=(0,10),pady=4)
            ttk.Entry(f,textvariable=self.vars[key],width=62).grid(row=row,column=1,columnspan=2,sticky="ew",pady=4);row+=1
        ttk.Label(f,text="Poznámka").grid(row=row,column=0,sticky="nw",padx=(0,10),pady=4)
        self.note=tk.Text(f,wrap="word",height=3,width=62);self.note.grid(row=row,column=1,columnspan=2,sticky="ew");self.note.insert("1.0",vals.get("note","") or "");row+=1
        ttk.Label(f,text="Osoby ve společnosti").grid(row=row,column=0,sticky="nw",padx=(0,10),pady=(10,4))
        box=ttk.Frame(f);box.grid(row=row,column=1,columnspan=2,sticky="nsew",pady=(10,4));box.columnconfigure(0,weight=1);box.rowconfigure(0,weight=1)
        self.people_tree=ttk.Treeview(box,columns=("Jméno","E-mail","Telefon","Funkce"),show="headings",height=6)
        for c,w in (("Jméno",180),("E-mail",230),("Telefon",120),("Funkce",180)):
            self.people_tree.heading(c,text=c);self.people_tree.column(c,width=w,anchor="w")
        self.people_tree.grid(row=0,column=0,sticky="nsew");sb=ttk.Scrollbar(box,orient="vertical",command=self.people_tree.yview);sb.grid(row=0,column=1,sticky="ns");self.people_tree.configure(yscrollcommand=sb.set);row+=1
        pb=ttk.Frame(f);pb.grid(row=row,column=1,columnspan=2,sticky="w",pady=(0,8))
        ttk.Button(pb,text="+ Přidat osobu",command=self.add_person).pack(side="left")
        ttk.Button(pb,text="Upravit osobu",command=self.edit_person).pack(side="left",padx=5)
        ttk.Button(pb,text="Odebrat ze společnosti",command=self.detach_person).pack(side="left");row+=1
        f.columnconfigure(1,weight=1);f.rowconfigure(row-2,weight=1)
        b=ttk.Frame(f);b.grid(row=row,column=0,columnspan=3,sticky="e",pady=(12,0))
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4);ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right",padx=4)
        self.refresh_people()
    def schedule_ares(self,*a):
        if self.search_after:
            try:self.after_cancel(self.search_after)
            except:pass
        if len(self.ares_q.get().strip())>=3:self.search_after=self.after(650,self.search_ares)
    def search_ares(self):
        q=self.ares_q.get().strip()
        if len(q)<2:return
        self.search_token+=1;token=self.search_token;self.results.delete(0,"end");self.results.insert("end","Hledám v ARES…")
        def worker():
            try:res=ares_search(q)
            except Exception as e:res=e
            self.after(0,lambda:self.show_ares(token,res))
        threading.Thread(target=worker,daemon=True).start()
    def show_ares(self,token,res):
        if token!=self.search_token:return
        self.results.delete(0,"end");self.ares_results=[]
        if isinstance(res,Exception):self.results.insert("end","ARES není dostupný – lze zadat ručně.");return
        for x in res[:15]:
            d=ares_company_data(x);self.ares_results.append(d);self.results.insert("end",f"{d['official_name']}  |  IČO {d['ico']}  |  {d['address']}")
        if not self.ares_results:self.results.insert("end","Nenalezeno")
    def take_ares(self,e=None):
        s=self.results.curselection()
        if not s or s[0]>=len(self.ares_results):return
        d=self.ares_results[s[0]]
        for k,v in d.items():
            if k in self.vars:self.vars[k].set(v)
        self.ares_raw_json=d.get("ares_raw_json","")
        self.vars["short_name"].set(d["official_name"])
    def refresh_people(self):
        for x in self.people_tree.get_children():self.people_tree.delete(x)
        if not self.cid:return
        with db() as con:rows=con.execute("SELECT id,name,email,phone,role FROM people WHERE company_id=? AND active=1 ORDER BY name COLLATE CZECH,email",(self.cid,)).fetchall()
        for r in rows:self.people_tree.insert("","end",iid=f"p{r['id']}",values=(r["name"],r["email"],r["phone"],r["role"]))
    def ensure_company_saved(self):
        if self.cid:return self.cid
        official=self.vars["official_name"].get().strip();short=official
        if not short and not official:messagebox.showwarning("Společnost","Nejdřív vyplňte název společnosti.",parent=self);return None
        short=official;ico=self.vars["ico"].get().strip()
        with db() as con:
            self.cid=con.execute("""INSERT INTO companies(short_name,official_name,ico,dic,address,legal_form,web,note,ares_checked,
                    date_created,ares_last_change,cz_nace,financial_office,district,municipality,ares_raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                    short,official,ico,self.vars["dic"].get().strip(),self.vars["address"].get().strip(),
                    self.vars["legal_form"].get().strip(),self.vars["web"].get().strip(),
                    self.note.get("1.0","end").strip(),date.today().isoformat() if ico else "",
                    self.vars["date_created"].get().strip(),self.vars["ares_last_change"].get().strip(),
                    self.vars["cz_nace"].get().strip(),self.vars["financial_office"].get().strip(),
                    self.vars["district"].get().strip(),self.vars["municipality"].get().strip(),
                    getattr(self,"ares_raw_json","")
                )).lastrowid
        return self.cid
    def add_person(self):
        cid=self.ensure_company_saved()
        if not cid:return
        d=PersonDialog(self,pre_company_id=cid);self.wait_window(d)
        if d.result:self.refresh_people()
    def edit_person(self):
        s=self.people_tree.selection()
        if not s:return messagebox.showinfo("Osoba","Vyberte osobu.",parent=self)
        d=PersonDialog(self,int(s[0][1:]));self.wait_window(d)
        if d.result:self.refresh_people()
    def detach_person(self):
        s=self.people_tree.selection()
        if not s:return messagebox.showinfo("Osoba","Vyberte osobu.",parent=self)
        if not messagebox.askyesno("Osoba","Odebrat osobu z této společnosti?\nOsoba zůstane v adresáři jako Bez společnosti.",parent=self):return
        with db() as con:con.execute("UPDATE people SET company_id=NULL WHERE id=?",(int(s[0][1:]),))
        self.refresh_people()
    def ok(self):
        official=self.vars["official_name"].get().strip();short=official
        if not short and not official:return messagebox.showwarning("Společnost","Vyplňte název.",parent=self)
        short=official;ico=self.vars["ico"].get().strip()
        with db() as con:
            if ico:
                dup=con.execute("SELECT id FROM companies WHERE ico=? AND id<>?",(ico,self.cid or -1)).fetchone()
                if dup:return messagebox.showwarning("Společnost","Firma s tímto IČO už v databázi existuje.",parent=self)
            vals=(short,official,ico,self.vars["dic"].get().strip(),self.vars["address"].get().strip(),
            self.vars["legal_form"].get().strip(),self.vars["web"].get().strip(),
            self.note.get("1.0","end").strip(),date.today().isoformat() if ico else "",
            self.vars["date_created"].get().strip(),self.vars["ares_last_change"].get().strip(),
            self.vars["cz_nace"].get().strip(),self.vars["financial_office"].get().strip(),
            self.vars["district"].get().strip(),self.vars["municipality"].get().strip(),
            getattr(self,"ares_raw_json",""))
            if self.cid:con.execute("""UPDATE companies SET short_name=?,official_name=?,ico=?,dic=?,address=?,legal_form=?,web=?,note=?,ares_checked=?,
                    date_created=?,ares_last_change=?,cz_nace=?,financial_office=?,district=?,municipality=?,ares_raw_json=? WHERE id=?""",
                    vals+(self.cid,));cid=self.cid
            else:cid=con.execute("""INSERT INTO companies(short_name,official_name,ico,dic,address,legal_form,web,note,ares_checked,
                    date_created,ares_last_change,cz_nace,financial_office,district,municipality,ares_raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",vals).lastrowid
        self.result=cid;self.destroy()

class PersonDialog(tk.Toplevel):
    def __init__(self,parent,pid=None,pre_company_id=None):
        super().__init__(parent);enable_dialog_maximize(self,740,500);self.title("Osoba");self.transient(parent);self.grab_set()
        self.result=False;self.pid=pid;bind_dialog_keys(self,self.ok)
        vals={}
        with db() as con:
            companies=con.execute("""SELECT MIN(id) id,official_name FROM companies
                                     WHERE active=1 AND trim(coalesce(official_name,''))<>''
                                     GROUP BY lower(trim(official_name))
                                     ORDER BY official_name COLLATE CZECH""").fetchall()
            roles=[r["name"] for r in con.execute("SELECT name FROM person_roles WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()]
            if pid:
                r=con.execute("""SELECT p.*,c.official_name company FROM people p
                                 LEFT JOIN companies c ON c.id=p.company_id WHERE p.id=?""",(pid,)).fetchone()
                if r:vals=dict(r)
            elif pre_company_id:
                r=con.execute("SELECT official_name FROM companies WHERE id=?",(pre_company_id,)).fetchone()
                if r:vals["company"]=r["official_name"]
        self.companies=list(companies);self.roles=list(roles)
        f=scrollable_dialog_frame(self,14)
        self.vars={k:tk.StringVar(value=vals.get(k,"") or "") for k in ("name","email","phone","role")}
        self.company=tk.StringVar(value=vals.get("company","") or "")

        for i,(lab,key) in enumerate([("Jméno","name"),("E-mail","email"),("Telefon","phone")]):
            ttk.Label(f,text=lab).grid(row=i,column=0,sticky="w",padx=(0,10),pady=5)
            ttk.Entry(f,textvariable=self.vars[key]).grid(row=i,column=1,columnspan=2,sticky="ew",pady=5)

        ttk.Label(f,text="Společnost").grid(row=3,column=0,sticky="w",padx=(0,10),pady=5)
        self.cb=AutocompleteEntry(f,textvariable=self.company,values=[r["official_name"] for r in companies])
        self.cb.grid(row=3,column=1,sticky="ew",pady=5)
        ttk.Button(f,text="+ Nová společnost",command=self.new_company).grid(row=3,column=2,padx=(6,0))

        ttk.Label(f,text="Funkce").grid(row=4,column=0,sticky="w",padx=(0,10),pady=5)
        role_wrap=ttk.Frame(f);role_wrap.grid(row=4,column=1,columnspan=2,sticky="ew");role_wrap.columnconfigure(0,weight=1)
        self.role_box=AutocompleteEntry(role_wrap,textvariable=self.vars["role"],values=self.roles)
        self.role_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(role_wrap,text="+ Přidat funkci",command=self.add_role).grid(row=0,column=1,padx=(6,0))
        ttk.Button(role_wrap,text="⚙ Spravovat",command=self.manage_roles).grid(row=0,column=2,padx=(6,0))

        ttk.Label(f,text="Poznámka").grid(row=5,column=0,sticky="nw",padx=(0,10),pady=5)
        self.note=tk.Text(f,wrap="word",height=4);self.note.grid(row=5,column=1,columnspan=2,sticky="nsew")
        self.note.insert("1.0",vals.get("note","") or "")

        self.active=tk.BooleanVar(value=bool(int(vals.get("active",1) or 0)))
        ttk.Checkbutton(f,text="Aktivní osoba",variable=self.active).grid(row=6,column=1,sticky="w",pady=(4,0))

        f.columnconfigure(1,weight=1);f.rowconfigure(5,weight=1)
        b=ttk.Frame(f);b.grid(row=7,column=0,columnspan=3,sticky="e",pady=10)
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4)
        ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right")

    def new_company(self):
        d=CompanyDialog(self);self.wait_window(d)
        if d.result:
            with db() as con:r=con.execute("SELECT official_name FROM companies WHERE id=?",(d.result,)).fetchone()
            if r:
                self.company.set(r["official_name"])
                self.companies.append({"id":d.result,"official_name":r["official_name"]})
                self.cb.set_values([x["official_name"] for x in self.companies])

    def manage_roles(self):
        app=find_app(self)
        if app:
            app.manage_code_lists("Funkce osob",self)
            with db() as con:
                self.roles=[r["name"] for r in con.execute(
                    "SELECT name FROM person_roles WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()]
            self.role_box.set_values(self.roles)

    def add_role(self):
        role=self.vars["role"].get().strip()
        if not role:return messagebox.showinfo("Funkce","Napište název funkce.",parent=self)
        with db() as con:con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(role,))
        if not any(x.casefold()==role.casefold() for x in self.roles):
            self.roles.append(role);self.roles.sort(key=str.casefold)
            self.role_box.set_values(self.roles)

    def ok(self):
        name=self.vars["name"].get().strip()
        email=self.vars["email"].get().strip()
        company_name=self.company.get().strip()
        if not name:return messagebox.showwarning("Osoba","Vyplňte jméno.",parent=self)
        if not email:return messagebox.showwarning("Osoba","Vyplňte e-mail.",parent=self)
        if not company_name:return messagebox.showwarning("Osoba","Vyberte společnost.",parent=self)

        with db() as con:
            c=con.execute("""SELECT id FROM companies
                             WHERE lower(trim(official_name))=lower(trim(?)) AND active=1
                             ORDER BY id LIMIT 1""",(company_name,)).fetchone()
            if not c:return messagebox.showwarning("Osoba","Vyberte existující společnost nebo ji založte.",parent=self)

            # Duplicita podle e-mailu je velmi silná shoda.
            by_email=con.execute("""SELECT p.id,p.name,p.email,c.official_name company
                                    FROM people p LEFT JOIN companies c ON c.id=p.company_id
                                    WHERE lower(trim(p.email))=lower(trim(?)) AND p.id<>?
                                    LIMIT 1""",(email,self.pid or -1)).fetchone()
            if by_email:
                return messagebox.showwarning("Duplicitní osoba",
                    f"Osoba se stejným e-mailem už existuje:\n\n"
                    f"{by_email['name']} – {by_email['company'] or 'bez společnosti'}\n{by_email['email']}\n\n"
                    "Upravte raději existující záznam.",parent=self)

            # Stejné jméno ve stejné společnosti: upozornit, ale dovolit výjimku.
            by_name=con.execute("""SELECT p.id,p.name,p.email,c.official_name company
                                   FROM people p LEFT JOIN companies c ON c.id=p.company_id
                                   WHERE lower(trim(p.name))=lower(trim(?)) AND p.company_id=? AND p.id<>?
                                   LIMIT 1""",(name,c["id"],self.pid or -1)).fetchone()
            if by_name and not messagebox.askyesno("Možná duplicitní osoba",
                f"Ve stejné společnosti už máme osobu se stejným jménem:\n\n"
                f"{by_name['name']} – {by_name['email'] or 'bez e-mailu'}\n\n"
                "Opravdu chcete založit další osobu?",parent=self):
                return

            role=self.vars["role"].get().strip()
            if role:con.execute("INSERT OR IGNORE INTO person_roles(name,active) VALUES(?,1)",(role,))
            vals=(name,email,self.vars["phone"].get().strip(),role,c["id"],
                  self.note.get("1.0","end").strip(),1 if self.active.get() else 0)
            if self.pid:
                con.execute("""UPDATE people SET name=?,email=?,phone=?,role=?,company_id=?,note=?,active=?
                               WHERE id=?""",vals+(self.pid,))
            else:
                con.execute("""INSERT INTO people(name,email,phone,role,company_id,note,active)
                               VALUES(?,?,?,?,?,?,?)""",vals)
        self.result=True;self.destroy()


class ProjectDialog(tk.Toplevel):
    def __init__(self,parent,pid=None):
        super().__init__(parent);enable_dialog_maximize(self,840,640);self.title("Akce")
        self.transient(parent);self.grab_set();self.result=None;self.pid=pid;bind_dialog_keys(self,self.ok)
        vals={}
        if pid:
            with db() as con:
                r=con.execute("SELECT * FROM projects WHERE id=?",(pid,)).fetchone()
                if r:vals=dict(r)

        f=scrollable_dialog_frame(self,14)
        self.vars={k:tk.StringVar(value=vals.get(k,"") or "") for k in
                   ("name","address","gps_coordinates","investor","general_contractor","start_date","end_date")}

        # Základní údaje
        ttk.Label(f,text="Název Akce").grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(f,textvariable=self.vars["name"],width=65).grid(row=0,column=1,columnspan=2,sticky="ew",pady=5)

        ttk.Label(f,text="Adresa").grid(row=1,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(f,textvariable=self.vars["address"]).grid(row=1,column=1,columnspan=2,sticky="ew",pady=5)

        ttk.Label(f,text="GPS souřadnice").grid(row=2,column=0,sticky="w",padx=(0,10),pady=5)
        gps_wrap=ttk.Frame(f);gps_wrap.grid(row=2,column=1,columnspan=2,sticky="ew",pady=5);gps_wrap.columnconfigure(0,weight=1)
        ttk.Entry(gps_wrap,textvariable=self.vars["gps_coordinates"]).grid(row=0,column=0,sticky="ew")
        ttk.Button(gps_wrap,text="Otevřít v mapě",command=self.open_map).grid(row=0,column=1,padx=(6,0))
        ttk.Label(f,text="Např. 49.1951, 16.6068 · souřadnice lze zkopírovat z Google Maps",
                  foreground="#667085").grid(row=3,column=1,columnspan=2,sticky="w",pady=(0,4))

        ttk.Label(f,text="Investor").grid(row=4,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(f,textvariable=self.vars["investor"]).grid(row=4,column=1,columnspan=2,sticky="ew",pady=5)

        ttk.Label(f,text="Generální dodavatel").grid(row=5,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(f,textvariable=self.vars["general_contractor"]).grid(row=5,column=1,columnspan=2,sticky="ew",pady=5)

        ttk.Label(f,text="Zahájení").grid(row=6,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.vars["start_date"]).grid(row=6,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Dokončení").grid(row=7,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.vars["end_date"]).grid(row=7,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Poznámka").grid(row=8,column=0,sticky="nw",padx=(0,10),pady=5)
        self.note=tk.Text(f,wrap="word",height=5);self.note.grid(row=8,column=1,columnspan=2,sticky="nsew")
        self.note.insert("1.0",vals.get("note","") or "")

        row=9
        if pid:
            ttk.Separator(f).grid(row=row,column=0,columnspan=3,sticky="ew",pady=10);row+=1
            ttk.Label(f,text="Příležitosti navázané na tuto Akci",
                      font=("Calibri",11,"bold")).grid(row=row,column=0,columnspan=3,sticky="w");row+=1
            self.opp=ttk.Treeview(f,columns=("Společnost","Příležitost","Stav","Deadline"),
                                  show="headings",height=7)
            for c,w in (("Společnost",180),("Příležitost",300),("Stav",120),("Deadline",100)):
                self.opp.heading(c,text=c);self.opp.column(c,width=w)
            self.opp.grid(row=row,column=0,columnspan=3,sticky="nsew",pady=(5,0))
            with db() as con:
                rows=con.execute("""SELECT a.id,a.name,a.status,a.deadline,c.official_name company
                                    FROM actions a LEFT JOIN companies c ON c.id=a.company_id
                                    WHERE a.project_id=? ORDER BY c.official_name,a.name""",(pid,)).fetchall()
            for r in rows:
                self.opp.insert("","end",iid=f"a{r['id']}",
                                values=(r["company"],r["name"],r["status"],fmt_date(r["deadline"])))
            bind_row_double_click(self.opp,lambda e:self._open_opportunity())
            f.rowconfigure(row,weight=1)
            row+=1

        f.columnconfigure(1,weight=1)
        b=ttk.Frame(f);b.grid(row=row,column=0,columnspan=3,sticky="e",pady=10)
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4)
        ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right")

    def open_map(self):
        gps=self.vars["gps_coordinates"].get().strip()
        address=self.vars["address"].get().strip()
        if gps:
            try:
                gps=normalize_gps(gps)
                self.vars["gps_coordinates"].set(gps)
            except ValueError as e:
                return messagebox.showwarning("GPS",str(e),parent=self)
            query=gps
        elif address:
            query=address
        else:
            return messagebox.showinfo("Mapa","Vyplňte GPS souřadnice nebo adresu.",parent=self)
        webbrowser.open("https://www.google.com/maps/search/?api=1&query="+quote(query,safe=""))

    def _open_opportunity(self):
        s=self.opp.selection()
        if s and hasattr(self.master,"edit_action_by_id"):
            self.master.edit_action_by_id(int(s[0][1:]))

    def ok(self):
        name=self.vars["name"].get().strip()
        if not name:return messagebox.showwarning("Akce","Zadejte název Akce.",parent=self)
        try:
            gps=normalize_gps(self.vars["gps_coordinates"].get())
        except ValueError as e:
            return messagebox.showwarning("GPS",str(e),parent=self)
        self.vars["gps_coordinates"].set(gps)

        vals=(name,self.vars["address"].get().strip(),gps,
              self.vars["investor"].get().strip(),self.vars["general_contractor"].get().strip(),
              parse_date(self.vars["start_date"].get()),parse_date(self.vars["end_date"].get()),
              self.note.get("1.0","end").strip())
        with db() as con:
            if self.pid:
                con.execute("""UPDATE projects SET name=?,address=?,gps_coordinates=?,investor=?,general_contractor=?,
                               start_date=?,end_date=?,note=? WHERE id=?""",vals+(self.pid,))
                pid=self.pid
            else:
                pid=con.execute("""INSERT INTO projects(
                    name,address,gps_coordinates,investor,general_contractor,start_date,end_date,note,created_by)
                    VALUES(?,?,?,?,?,?,?,?,?)""",vals+(get_setting("active_user",""),)).lastrowid
        self.result=pid;self.destroy()


class TaskDialog(tk.Toplevel):
    def __init__(self,parent,task_id=None,pre_action_id=None):
        super().__init__(parent);enable_dialog_maximize(self,720,500);self.title("Úkol / připomínka");self.transient(parent);self.grab_set();self.result=False;bind_dialog_keys(self,self.ok)
        self.task_id=task_id
        vals={}
        with db() as con:
            actions=con.execute("""SELECT MIN(id) id,trim(name) name FROM actions
                WHERE trim(coalesce(name,''))<>''
                GROUP BY lower(trim(name))
                ORDER BY trim(name) COLLATE CZECH""").fetchall()
            users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
            if task_id:
                r=con.execute("""SELECT t.*,a.name action_name FROM tasks t
                                 LEFT JOIN actions a ON a.id=t.action_id WHERE t.id=?""",(task_id,)).fetchone()
                if r: vals=dict(r)
            elif pre_action_id:
                r=con.execute("SELECT name FROM actions WHERE id=?",(pre_action_id,)).fetchone()
                if r: vals["action_name"]=r["name"]
        self.actions=actions
        f=scrollable_dialog_frame(self,14)
        self.action=tk.StringVar(value=vals.get("action_name",""))
        self.due=tk.StringVar(value=vals.get("due_date",date.today().isoformat()))
        self.text=tk.StringVar(value=vals.get("text",""))
        self.assigned=tk.StringVar(value=vals.get("assigned_user","") or get_setting("active_user",""))
        ttk.Label(f,text="Akce").grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        self.action_box=AutocompleteEntry(f,textvariable=self.action,values=[r["name"] for r in actions])
        self.action_box.grid(row=0,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Termín").grid(row=1,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.due).grid(row=1,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Co udělat").grid(row=2,column=0,sticky="w",padx=(0,10),pady=5)
        ttk.Entry(f,textvariable=self.text,width=70).grid(row=2,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Řeší").grid(row=3,column=0,sticky="nw",padx=(0,10),pady=5)
        self.assigned_box=InlineChoice(f,textvariable=self.assigned,values=users,editable=True,max_rows=6)
        self.assigned_box.grid(row=3,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Poznámka").grid(row=4,column=0,sticky="nw",padx=(0,10),pady=5)
        self.note=tk.Text(f,wrap="word",height=4);self.note.grid(row=4,column=1,sticky="ew",pady=5)
        self.note.insert("1.0",vals.get("note","") or "")
        f.columnconfigure(1,weight=1)
        b=ttk.Frame(f);b.grid(row=5,column=0,columnspan=2,sticky="e",pady=(10,0))
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4)
        ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right")
    def ok(self):
        an=self.action.get().strip()
        txt=self.text.get().strip()
        due=parse_date(self.due.get())
        if not an:return messagebox.showwarning("Úkol","Vyberte Příležitost.",parent=self)
        if not txt:return messagebox.showwarning("Úkol","Napište, co je potřeba udělat.",parent=self)
        if not due:return messagebox.showwarning("Úkol","Vyplňte termín.",parent=self)
        user=get_setting("active_user","")
        assigned=self.assigned.get().strip() or user
        note=self.note.get("1.0","end").strip()
        action_id=None
        event_type="task_create"
        summary="Přidal úkol"
        details=f"{fmt_date(due)} · {txt}"
        with db() as con:
            a=con.execute("""SELECT MIN(id) id FROM actions
                                WHERE lower(trim(name))=lower(trim(?))""",(an,)).fetchone()
            if not a:return messagebox.showwarning("Úkol","Vyberte existující Příležitost.",parent=self)
            action_id=a["id"]
            if self.task_id:
                old=con.execute("SELECT * FROM tasks WHERE id=?",(self.task_id,)).fetchone()
                con.execute("""UPDATE tasks SET action_id=?,due_date=?,text=?,note=?,assigned_user=?
                               WHERE id=?""",(action_id,due,txt,note,assigned,self.task_id))
                event_type="task_edit";summary="Upravil úkol"
                details=f"{old['due_date'] if old else '—'} / {old['text'] if old else '—'} → {due} / {txt}"
            else:
                con.execute("""INSERT INTO tasks(action_id,due_date,text,note,created_by,assigned_user)
                               VALUES(?,?,?,?,?,?)""",(action_id,due,txt,note,user,assigned))
        # Historie až PO uzavření zapisovací transakce.
        log_history(action_id,event_type,summary,details,user_name=user)
        self.result=True
        self.destroy()

class UserNotesDialog(tk.Toplevel):
    'Simple private notebook for exactly one CRM user.'
    def __init__(self,parent):
        super().__init__(parent)
        self.parent_app=parent
        self.user_name=(parent.active_user.get() or '').strip() or get_setting('active_user','')
        self.editing_id=None
        self.title(f"Poznámky – {self.user_name}")
        self.transient(parent)
        self.grab_set()
        enable_dialog_maximize(self,980,650)
        self.protocol('WM_DELETE_WINDOW',self.close)

        outer=ttk.Frame(self,padding=16)
        outer.pack(fill='both',expand=True)
        outer.columnconfigure(0,weight=1)
        outer.rowconfigure(4,weight=1)

        ttk.Label(outer,text='Osobní poznámky',font=('Calibri',16,'bold')).grid(row=0,column=0,sticky='w')
        ttk.Label(
            outer,
            text=f'{self.user_name} · rychlý osobní zápisník bez vazby na Akce, Poptávky nebo Úkoly',
            style='PageSubtitle.TLabel',
        ).grid(row=1,column=0,sticky='w',pady=(2,10))

        editor_card=ttk.Frame(outer,style='Card.TFrame',padding=12)
        editor_card.grid(row=2,column=0,sticky='ew',pady=(0,10))
        editor_card.columnconfigure(0,weight=1)
        ttk.Label(editor_card,text='Nová poznámka',style='Section.TLabel').grid(row=0,column=0,sticky='w')
        self.editor=tk.Text(editor_card,height=5,wrap='word',font=('Calibri',11))
        self.editor.grid(row=1,column=0,columnspan=3,sticky='ew',pady=(7,8))
        try:
            pal=getattr(parent,'palette',{}) or {}
            field=pal.get('field','#ffffff');fg=pal.get('fg','#1c2429');sel=pal.get('select','#d6b64c');border=pal.get('border','#d4dade')
            self.editor.configure(bg=field,fg=fg,insertbackground=fg,selectbackground=sel,selectforeground='white',highlightbackground=border,highlightcolor=border,relief='flat',borderwidth=1)
        except Exception:pass
        self.editor.bind('<Control-Return>',self._ctrl_save)
        self.editor.bind('<Control-KP_Enter>',self._ctrl_save)
        self.edit_label=ttk.Label(editor_card,text='Ctrl+Enter = uložit',style='PageSubtitle.TLabel')
        self.edit_label.grid(row=2,column=0,sticky='w')
        ttk.Button(editor_card,text='Vyčistit',command=self.clear_editor).grid(row=2,column=1,padx=(8,0))
        self.save_button=ttk.Button(editor_card,text='Uložit poznámku',style='Accent.TButton',command=self.save_note)
        self.save_button.grid(row=2,column=2,padx=(8,0))

        tools=ttk.Frame(outer,style='Panel.TFrame',padding=8)
        tools.grid(row=3,column=0,sticky='ew',pady=(0,6))
        tools.columnconfigure(1,weight=1)
        ttk.Label(tools,text='Hledat:').grid(row=0,column=0,sticky='w',padx=(0,6))
        self.search_var=tk.StringVar()
        search=ttk.Entry(tools,textvariable=self.search_var)
        search.grid(row=0,column=1,sticky='ew')
        self.show_archived=tk.BooleanVar(value=False)
        ttk.Checkbutton(
            tools,
            text='Zobrazit archivované',
            variable=self.show_archived,
            command=self.refresh,
        ).grid(row=0,column=2,sticky='e',padx=(12,0))
        self.search_var.trace_add('write',lambda *_:self.refresh())

        tree_wrap=ttk.Frame(outer,style='Panel.TFrame')
        tree_wrap.grid(row=4,column=0,sticky='nsew')
        tree_wrap.columnconfigure(0,weight=1)
        tree_wrap.rowconfigure(0,weight=1)
        self.tree=ttk.Treeview(
            tree_wrap,
            columns=('Vytvořeno','Poznámka'),
            show='headings',
            selectmode='browse',
        )
        self.tree.heading('Vytvořeno',text='Vytvořeno')
        self.tree.heading('Poznámka',text='Poznámka')
        self.tree.column('Vytvořeno',width=145,minwidth=125,stretch=False,anchor='w')
        self.tree.column('Poznámka',width=760,minwidth=300,stretch=True,anchor='w')
        ys=ttk.Scrollbar(tree_wrap,orient='vertical',command=self.tree.yview)
        self.tree.configure(yscrollcommand=ys.set)
        self.tree.grid(row=0,column=0,sticky='nsew')
        ys.grid(row=0,column=1,sticky='ns')
        self._archived_font=tkfont.Font(family='Calibri',size=11,overstrike=1)
        self.tree.tag_configure('archived',font=self._archived_font)
        bind_row_double_click(self.tree,lambda _e:self.edit_selected())
        self.tree.bind('<<TreeviewSelect>>',lambda _e:self.sync_buttons(),add='+')

        actions=ttk.Frame(outer)
        actions.grid(row=5,column=0,sticky='ew',pady=(10,0))
        self.edit_button=ttk.Button(actions,text='✎ Upravit',command=self.edit_selected)
        self.edit_button.pack(side='left')
        self.archive_button=ttk.Button(actions,text='✓ Přeškrtnout / archivovat',command=self.archive_selected)
        self.archive_button.pack(side='left',padx=(6,0))
        self.restore_button=ttk.Button(actions,text='↩ Obnovit',command=self.restore_selected)
        self.restore_button.pack(side='left',padx=(6,0))
        ttk.Button(actions,text='Zavřít',command=self.close).pack(side='right')

        self.refresh()
        self.after_idle(self.editor.focus_set)

    def _ctrl_save(self,_event=None):
        self.save_note()
        return 'break'

    def selected_id(self):
        selected=self.tree.selection()
        if not selected:return None
        iid=selected[0]
        return int(iid[1:]) if str(iid).startswith('n') else None

    def selected_row(self):
        note_id=self.selected_id()
        if not note_id:return None
        with db() as con:
            row=con.execute(
                'SELECT * FROM user_notes WHERE id=? AND user_name=?',
                (note_id,self.user_name),
            ).fetchone()
        return row

    def refresh(self):
        if not hasattr(self,'tree'):return
        for iid in self.tree.get_children(''):
            self.tree.delete(iid)
        query=(self.search_var.get() or '').strip() if hasattr(self,'search_var') else ''
        show_archived=bool(self.show_archived.get()) if hasattr(self,'show_archived') else False
        with db() as con:
            rows=con.execute(
                '''SELECT * FROM user_notes
                   WHERE user_name=?
                     AND (?=1 OR archived=0)
                     AND (?='' OR lower(text) LIKE lower(?))
                   ORDER BY archived ASC,datetime(created_at) DESC,id DESC''',
                (self.user_name,1 if show_archived else 0,query,f'%{query}%'),
            ).fetchall()
        for row in rows:
            preview=' '.join(str(row['text'] or '').split())
            tags=('archived',) if int(row['archived'] or 0) else ()
            self.tree.insert(
                '','end',iid=f"n{row['id']}",
                values=(fmt_history_datetime(row['created_at']),preview),
                tags=tags,
            )
        self.sync_buttons()

    def sync_buttons(self):
        row=self.selected_row()
        if not row:
            for button in (self.edit_button,self.archive_button,self.restore_button):
                button.state(['disabled'])
            return
        self.edit_button.state(['!disabled'])
        if int(row['archived'] or 0):
            self.archive_button.state(['disabled'])
            self.restore_button.state(['!disabled'])
        else:
            self.archive_button.state(['!disabled'])
            self.restore_button.state(['disabled'])

    def clear_editor(self):
        self.editing_id=None
        self.editor.delete('1.0','end')
        self.save_button.configure(text='Uložit poznámku')
        self.edit_label.configure(text='Ctrl+Enter = uložit')
        self.editor.focus_set()

    def save_note(self):
        note=self.editor.get('1.0','end').strip()
        if not note:
            return messagebox.showinfo('Poznámky','Napište text poznámky.',parent=self)
        with db() as con:
            if self.editing_id:
                con.execute(
                    '''UPDATE user_notes SET text=?,updated_at=CURRENT_TIMESTAMP
                       WHERE id=? AND user_name=?''',
                    (note,self.editing_id,self.user_name),
                )
            else:
                con.execute(
                    'INSERT INTO user_notes(user_name,text) VALUES(?,?)',
                    (self.user_name,note),
                )
        self.clear_editor()
        self.refresh()
        self.parent_app.refresh_notes_button()

    def edit_selected(self):
        row=self.selected_row()
        if not row:return
        self.editing_id=int(row['id'])
        self.editor.delete('1.0','end')
        self.editor.insert('1.0',row['text'] or '')
        self.save_button.configure(text='Uložit změny')
        self.edit_label.configure(text=f"Upravujete poznámku z {fmt_history_datetime(row['created_at'])}")
        self.editor.focus_set()

    def archive_selected(self):
        row=self.selected_row()
        if not row:return
        if int(row['archived'] or 0):return
        with db() as con:
            con.execute(
                '''UPDATE user_notes
                   SET archived=1,archived_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND user_name=?''',
                (row['id'],self.user_name),
            )
        if self.editing_id==int(row['id']):self.clear_editor()
        self.refresh()
        self.parent_app.refresh_notes_button()

    def restore_selected(self):
        row=self.selected_row()
        if not row:return
        if not int(row['archived'] or 0):return
        with db() as con:
            con.execute(
                '''UPDATE user_notes
                   SET archived=0,archived_at='',updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND user_name=?''',
                (row['id'],self.user_name),
            )
        self.refresh()
        self.parent_app.refresh_notes_button()

    def close(self):
        try:self.grab_release()
        except Exception:pass
        try:self.parent_app._notes_dialog=None
        except Exception:pass
        self.destroy()

class NotificationCenter(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent);enable_dialog_maximize(self,900,560);self.title("Přehled na 3 dny");self.transient(parent);self.geometry("1050x620")
        self.parent=parent
        f=scrollable_dialog_frame(self,14)
        ttk.Label(f,text="Co je potřeba udělat",font=("Calibri",16,"bold")).pack(anchor="w")
        ttk.Label(f,text="Po termínu + dnes + následující 3 dny",foreground="#667085").pack(anchor="w",pady=(2,10))
        self.tree=ttk.Treeview(f,columns=("Kdy","Typ","Akce","Co / detail"),show="headings")
        for c,w in (("Kdy",120),("Typ",130),("Akce",280),("Co / detail",470)):
            self.tree.heading(c,text=c);self.tree.column(c,width=w,anchor="w")
        self.tree.pack(fill="both",expand=True)
        self.tree.tag_configure("over",background="#ffc9c9",foreground="#6c2020")
        self.tree.tag_configure("today",background="#ffe8cf",foreground="#65350a")
        self.tree.tag_configure("soon",background="#fff7df",foreground="#5f4600")
        self.tree.tag_configure("wait",background="#dfeaf7",foreground="#17202a")
        bind_row_double_click(self.tree,self.open_item)
        b=ttk.Frame(f);b.pack(fill="x",pady=(10,0))
        ttk.Button(b,text="Označit úkol hotový",command=self.complete_selected).pack(side="left")
        ttk.Button(b,text="Zavřít",command=self.destroy).pack(side="right")
        self.refresh()
    def refresh(self):
        for x in self.tree.get_children():self.tree.delete(x)
        today=date.today(); horizon=today.toordinal()+3
        with db() as con:
            tasks=con.execute("""SELECT t.*,a.name action_name FROM tasks t
                                 JOIN actions a ON a.id=t.action_id
                                 WHERE t.done=0 AND (trim(coalesce(t.assigned_user,''))='' OR t.assigned_user=?)
                                 ORDER BY t.due_date,t.id""",(get_setting("active_user",""),)).fetchall()
            actions=con.execute("""SELECT id,name,deadline,status FROM actions
                                   WHERE trim(coalesce(deadline,''))<>'' AND status NOT IN ('Hotovo','Zrušeno')
                                   ORDER BY deadline""").fetchall()
            reqs=con.execute("""SELECT r.id,r.action_id,r.asked_date,r.item,a.name action_name,c.official_name company
                                FROM requests r
                                LEFT JOIN actions a ON a.id=r.action_id
                                LEFT JOIN companies c ON c.id=r.company_id
                                WHERE trim(coalesce(r.received_date,''))=''
                                ORDER BY r.asked_date""").fetchall()
        for r in tasks:
            try:d=datetime.strptime(r["due_date"],"%Y-%m-%d").date()
            except:continue
            if d.toordinal()>horizon:continue
            tag="over" if d<today else ("today" if d==today else "soon")
            kdy="Po termínu" if d<today else ("Dnes" if d==today else fmt_date(r["due_date"]))
            self.tree.insert("","end",iid=f"t{r['id']}",values=(kdy,"Úkol",r["action_name"],r["text"]),tags=(tag,))
        for r in actions:
            try:d=datetime.strptime(r["deadline"],"%Y-%m-%d").date()
            except:continue
            if d.toordinal()>horizon:continue
            tag="over" if d<today else ("today" if d==today else "soon")
            kdy="Po termínu" if d<today else ("Dnes" if d==today else fmt_date(r["deadline"]))
            self.tree.insert("","end",iid=f"a{r['id']}",values=(kdy,"Deadline Akce",r["name"],"Termín Akce"),tags=(tag,))
        for r in reqs:
            try:d=datetime.strptime(r["asked_date"],"%Y-%m-%d").date()
            except:continue
            age=(today-d).days
            if age<3:continue
            self.tree.insert("","end",iid=f"r{r['id']}",values=(f"čeká {age} dní","Poptávka",r["action_name"] or "—",
                f"{r['company'] or '—'} · {r['item'] or '—'}"),tags=("wait",))
    def complete_selected(self):
        s=self.tree.selection()
        if not s or not s[0].startswith("t"):
            return messagebox.showinfo("Úkol","Vyberte řádek typu Úkol.",parent=self)
        tid=int(s[0][1:])
        self.parent.complete_task_by_id(tid)
        self.refresh()
    def open_item(self,e=None):
        s=self.tree.selection()
        if not s:return
        iid=s[0]
        if iid.startswith("t"):
            with db() as con:r=con.execute("SELECT action_id FROM tasks WHERE id=?",(int(iid[1:]),)).fetchone()
            if r:self.parent.edit_action_by_id(r["action_id"])
        elif iid.startswith("a"):
            self.parent.edit_action_by_id(int(iid[1:]))
        elif iid.startswith("r"):
            self.parent.show_page("requests")
            rid=f"r{int(iid[1:])}"
            if rid in self.parent.request_tree.get_children():
                self.parent.request_tree.selection_set(rid);self.parent.request_tree.see(rid)

class ActionDialog(tk.Toplevel):
    def __init__(self,parent,aid=None):
        super().__init__(parent);enable_dialog_maximize(self,1120,650);self.title("Příležitost")
        self.transient(parent);self.grab_set();self.result=None;self.aid=aid;bind_dialog_keys(self,self.ok)
        vals={}
        with db() as con:
            self.companies=con.execute("""SELECT MIN(id) id,official_name,MAX(ico) ico FROM companies
                WHERE active=1 AND trim(coalesce(official_name,''))<>''
                GROUP BY lower(trim(official_name)) ORDER BY official_name COLLATE CZECH""").fetchall()
            self.sales=con.execute("SELECT id,name FROM salespeople WHERE active=1 ORDER BY name").fetchall()
            self.projects=con.execute("SELECT id,name FROM projects WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()
            if aid:
                r=con.execute("""SELECT a.*,c.official_name company,s.name salesperson,p.name project_name
                    FROM actions a
                    LEFT JOIN companies c ON c.id=a.company_id
                    LEFT JOIN salespeople s ON s.id=a.salesperson_id
                    LEFT JOIN projects p ON p.id=a.project_id WHERE a.id=?""",(aid,)).fetchone()
                if r:vals=dict(r)

        f=scrollable_dialog_frame(self,14)
        # Akce je jediný název. Interně se stejný text uloží i k Příležitosti,
        # aby zůstaly zachovány stávající vazby a historie.
        self.name=tk.StringVar(value=vals.get("project_name") or vals.get("name",""))
        self.company=tk.StringVar(value=vals.get("company",""))
        self.salesperson=tk.StringVar(value=vals.get("salesperson",""))
        self.received=tk.StringVar(value=vals.get("created_date",date.today().isoformat()))
        self.deadline=tk.StringVar(value=vals.get("deadline",""))
        self.status=tk.StringVar(value=vals.get("status","Rozpracováno"))
        self.products=tk.StringVar(value=vals.get("products",""))
        self.next=tk.StringVar(value=vals.get("next_step",""))

        # Akce
        ttk.Label(f,text="Akce").grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        self.action_name_box=AutocompleteEntry(f,textvariable=self.name,values=[r["name"] for r in self.projects])
        self.action_name_box.grid(row=0,column=1,sticky="ew",pady=5)

        # Společnost + možnost založení přímo z dialogu
        ttk.Label(f,text="Společnost").grid(row=1,column=0,sticky="w",padx=(0,10),pady=5)
        company_wrap=ttk.Frame(f);company_wrap.grid(row=1,column=1,sticky="ew",pady=5);company_wrap.columnconfigure(0,weight=1)
        self.company_box=AutocompleteEntry(company_wrap,textvariable=self.company,
            values=[r["official_name"] for r in self.companies])
        self.company_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(company_wrap,text="+ Nová společnost",command=self.new_company).grid(row=0,column=1,padx=(6,0))

        ttk.Label(f,text="Obchodník").grid(row=2,column=0,sticky="w",padx=(0,10),pady=5)
        sales_wrap=ttk.Frame(f);sales_wrap.grid(row=2,column=1,sticky="ew",pady=5);sales_wrap.columnconfigure(0,weight=1)
        self.salesperson_box=safe_combobox(sales_wrap,textvariable=self.salesperson,
                                          values=[r["name"] for r in self.sales],state="readonly")
        self.salesperson_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(sales_wrap,text="⚙ Spravovat",command=self.manage_salespeople).grid(row=0,column=1,padx=(6,0))

        ttk.Label(f,text="Datum přijetí").grid(row=3,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.received).grid(row=3,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Deadline").grid(row=4,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.deadline).grid(row=4,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Stav").grid(row=5,column=0,sticky="w",padx=(0,10),pady=5)
        safe_combobox(f,textvariable=self.status,values=STATUSES,state="readonly").grid(row=5,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Co se řeší").grid(row=6,column=0,sticky="nw",padx=(0,10),pady=5)
        with db() as con:
            self.topic_values=[r["name"] for r in con.execute(
                "SELECT name FROM work_topics WHERE active=1 ORDER BY name COLLATE CZECH")]
        topic_wrap=ttk.Frame(f);topic_wrap.grid(row=6,column=1,sticky="ew",pady=5);topic_wrap.columnconfigure(0,weight=1)
        self.topic_entry_var=tk.StringVar()
        self.topic_entry=AutocompleteEntry(topic_wrap,textvariable=self.topic_entry_var,values=self.topic_values)
        self.topic_entry.grid(row=0,column=0,sticky="ew")
        ttk.Button(topic_wrap,text="+ Přidat",command=self.add_topic).grid(row=0,column=1,padx=(6,0))
        ttk.Button(topic_wrap,text="⚙ Spravovat",command=self.manage_topics).grid(row=0,column=2,padx=(6,0))
        self.topic_list=ttk.Frame(topic_wrap);self.topic_list.grid(row=1,column=0,columnspan=3,sticky="ew",pady=(5,0))
        self.selected_topics=[]
        for _topic in re.split(r"\s*[;,]\s*",self.products.get().strip()):
            if _topic:self._append_topic(_topic)
        self.topic_entry.bind("<Return>",lambda e:self.add_topic())

        ttk.Label(f,text="Poznámka").grid(row=7,column=0,sticky="nw",padx=(0,10),pady=5)
        self.note=tk.Text(f,wrap="word",height=4);self.note.grid(row=7,column=1,sticky="ew")
        self.note.insert("1.0",vals.get("note","") or "")

        # Čekající Poptávky jsou samostatný procesní stav.
        row=8
        if aid:
            with db() as con:
                pending=con.execute("""SELECT r.asked_date,r.item,c.official_name company
                    FROM requests r LEFT JOIN companies c ON c.id=r.company_id
                    WHERE r.action_id=? AND trim(coalesce(r.received_date,''))=''
                      AND coalesce(r.archived,0)=0
                    ORDER BY r.asked_date,r.id""",(aid,)).fetchall()
            if pending:
                waitbox=ttk.LabelFrame(f,text=f"Čekám na poptávku / odpověď ({len(pending)})",padding=8)
                waitbox.grid(row=row,column=0,columnspan=2,sticky="ew",pady=(8,8))
                for pr in pending:
                    ttk.Label(waitbox,text=f"• {pr['company'] or '—'} · {pr['item'] or '—'} · poptáno {fmt_date(pr['asked_date'])}").pack(anchor="w")
                row+=1

        # Stejná Akce u jiných společností.
        if aid:
            with db() as con:
                current=con.execute("SELECT name,company_id FROM actions WHERE id=?",(aid,)).fetchone()
                related=[]
                if current:
                    related=con.execute("""SELECT a.id,a.created_date,a.status,c.official_name company
                        FROM actions a
                        LEFT JOIN companies c ON c.id=a.company_id
                        WHERE a.id<>?
                          AND lower(trim(a.name))=lower(trim(?))
                          AND coalesce(a.company_id,-1)<>coalesce(?,-1)
                        ORDER BY CASE WHEN trim(coalesce(a.created_date,''))='' THEN 1 ELSE 0 END,
                                 a.created_date DESC,a.id DESC""",
                        (aid,current["name"],current["company_id"])).fetchall()
            if related:
                box=ttk.LabelFrame(f,text="Stejná Akce u dalších společností",padding=8)
                box.grid(row=row,column=0,columnspan=2,sticky="ew",pady=(8,6))
                self.related_tree=ttk.Treeview(box,columns=("Společnost","Přijato","Stav"),
                                               show="headings",height=min(5,len(related)))
                for c,w in (("Společnost",360),("Přijato",120),("Stav",160)):
                    self.related_tree.heading(c,text=c);self.related_tree.column(c,width=w,anchor="w")
                self.related_tree.pack(fill="x",expand=True)
                for rr in related:
                    self.related_tree.insert("","end",iid=f"a{rr['id']}",
                        values=(rr["company"] or "—",fmt_date(rr["created_date"]),rr["status"] or ""))
                ttk.Label(box,text="Dvojklik otevře tuto Příležitost v novém okně.",
                          foreground="#667085").pack(anchor="w",pady=(5,0))
                bind_row_double_click(self.related_tree,lambda e:self.open_related_opportunity())
                row+=1

        if aid:
            ttk.Separator(f).grid(row=row,column=0,columnspan=2,sticky="ew",pady=(12,8));row+=1
            ttk.Label(f,text="Historie příležitosti",font=("Calibri",11,"bold")).grid(row=row,column=0,columnspan=2,sticky="w",pady=(0,6));row+=1
            hf=ttk.Frame(f);hf.grid(row=row,column=0,columnspan=2,sticky="nsew")
            hf.rowconfigure(0,weight=1);hf.columnconfigure(0,weight=1)
            self.history_tree=ttk.Treeview(hf,columns=("Kdy","Uživatel","Událost","Detail"),show="headings",height=8)
            for c,w in (("Kdy",130),("Uživatel",150),("Událost",220),("Detail",470)):
                self.history_tree.heading(c,text=c);self.history_tree.column(c,width=w,anchor="w")
            self.history_tree.grid(row=0,column=0,sticky="nsew")
            ys=ttk.Scrollbar(hf,orient="vertical",command=self.history_tree.yview)
            ys.grid(row=0,column=1,sticky="ns");self.history_tree.configure(yscrollcommand=ys.set)
            with db() as con:
                hist=con.execute("SELECT * FROM action_history WHERE action_id=? ORDER BY datetime(created_at) DESC,id DESC",(aid,)).fetchall()
            for h in hist:
                dt=fmt_history_datetime(h["created_at"])
                self.history_tree.insert("","end",values=(dt,h["user_name"],h["summary"],h["details"]))
            row+=1
            f.rowconfigure(row-1,weight=1)

        f.columnconfigure(1,weight=1)
        b=ttk.Frame(f);b.grid(row=row,column=0,columnspan=2,sticky="e",pady=10)
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4)
        ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right")


    def open_related_opportunity(self):
        if not hasattr(self,"related_tree"):return
        s=self.related_tree.selection()
        if not s:return
        aid=int(s[0][1:])
        d=ActionDialog(self,aid)
        self.wait_window(d)
        try:self.grab_set()
        except Exception:pass

    def manage_salespeople(self):
        app=find_app(self)
        if app:
            app.manage_code_lists("Obchodníci",self)
            with db() as con:
                self.sales=con.execute("SELECT id,name FROM salespeople WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()
            self.salesperson_box.configure(values=[r["name"] for r in self.sales])

    def manage_topics(self):
        app=find_app(self)
        if app:
            app.manage_code_lists("Co se řeší",self)
            with db() as con:
                self.topic_values=[r["name"] for r in con.execute(
                    "SELECT name FROM work_topics WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()]
            self.topic_entry.set_values(self.topic_values)

    def new_company(self):
        d=CompanyDialog(self);self.wait_window(d)
        if d.result:
            with db() as con:
                r=con.execute("SELECT id,official_name,ico FROM companies WHERE id=?",(d.result,)).fetchone()
            if r:
                self.company.set(r["official_name"])
                self.companies=list(self.companies)+[r]
                self.company_box.set_values([x["official_name"] for x in self.companies])

    def add_task(self):
        if not self.aid:return
        d=TaskDialog(self,pre_action_id=self.aid);self.wait_window(d)
        if d.result:
            self.destroy()
            if hasattr(self.master,"edit_action_by_id"):
                self.master.edit_action_by_id(self.aid)

    def create_request(self):
        if not self.aid:return
        # Pro koho = společnost akce. Pokud uživatel změnil společnost v otevřeném formuláři,
        # použijeme právě viditelnou hodnotu.
        d=RequestDialog(self,pre_action=self.aid,pre_requested_for=self.company.get().strip())
        self.wait_window(d)
        if d.result and hasattr(self.master,"save_request"):
            self.master.save_request(d)

    def _append_topic(self,topic):
        topic=(topic or "").strip()
        if not topic or any(x.lower()==topic.lower() for x in self.selected_topics):return
        self.selected_topics.append(topic);self._render_topics()

    def _render_topics(self):
        if not hasattr(self,"topic_list"):return
        for w in self.topic_list.winfo_children():w.destroy()
        for topic in self.selected_topics:
            chip=ttk.Frame(self.topic_list);chip.pack(side="left",padx=(0,5),pady=2)
            ttk.Label(chip,text=topic).pack(side="left")
            ttk.Button(chip,text="×",width=2,command=lambda x=topic:self.remove_topic(x)).pack(side="left",padx=(3,0))
        self.products.set("; ".join(self.selected_topics))

    def add_topic(self):
        topic=self.topic_entry_var.get().strip()
        if not topic:return
        self._append_topic(topic)
        with db() as con:con.execute("INSERT OR IGNORE INTO work_topics(name) VALUES(?)",(topic,))
        self.topic_entry_var.set("")

    def remove_topic(self,topic):
        self.selected_topics=[x for x in self.selected_topics if x.lower()!=topic.lower()]
        self._render_topics()

    def ok(self):
        action_name=self.name.get().strip()
        if not action_name:
            return messagebox.showwarning("Příležitost","Zadejte Akci.",parent=self)
        if hasattr(self,"topic_entry_var") and self.topic_entry_var.get().strip():
            self._append_topic(self.topic_entry_var.get().strip())
        self.products.set("; ".join(self.selected_topics))
        user=get_setting("active_user","")

        with db() as con:
            for part in re.split(r"[;,]",self.products.get()):
                part=part.strip()
                if part:con.execute("INSERT OR IGNORE INTO work_topics(name) VALUES(?)",(part,))

            company_name=self.company.get().strip()
            c=con.execute("""SELECT id FROM companies
                             WHERE lower(trim(official_name))=lower(trim(?)) AND active=1
                             ORDER BY id LIMIT 1""",(company_name,)).fetchone()
            if company_name and not c:
                return messagebox.showwarning("Příležitost",
                    "Vyberte existující společnost, nebo použijte „+ Nová společnost“.",parent=self)

            s=con.execute("SELECT id FROM salespeople WHERE name=?",(self.salesperson.get(),)).fetchone()

            # Akce a název Příležitosti jsou pro uživatele totožné.
            p=con.execute("SELECT id FROM projects WHERE lower(trim(name))=lower(trim(?)) AND active=1 ORDER BY id LIMIT 1",
                          (action_name,)).fetchone()
            if p:
                project_id=p["id"]
            else:
                project_id=con.execute("""INSERT INTO projects(name,active,created_by)
                                          VALUES(?,1,?)""",(action_name,user)).lastrowid
                self.projects.append({"id":project_id,"name":action_name})

            vals=(action_name,c["id"] if c else None,s["id"] if s else None,project_id,
                  parse_date(self.received.get()),parse_date(self.deadline.get()),self.status.get(),
                  self.products.get().strip(),self.next.get().strip(),
                  self.note.get("1.0","end").strip(),user)
            if self.aid:
                old=con.execute("SELECT * FROM actions WHERE id=?",(self.aid,)).fetchone()
                con.execute("""UPDATE actions SET name=?,company_id=?,salesperson_id=?,project_id=?,created_date=?,deadline=?,
                    status=?,products=?,next_step=?,note=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    vals+(self.aid,))
                aid=self.aid
                changes=[]
                labels={"name":"Akce","company_id":"společnost","salesperson_id":"obchodník",
                        "deadline":"deadline","status":"stav","products":"co se řeší","note":"poznámka"}
                nv={"name":vals[0],"company_id":vals[1],"salesperson_id":vals[2],
                    "deadline":vals[5],"status":vals[6],"products":vals[7],"note":vals[9]}
                for k,v in nv.items():
                    ov=old[k] if old[k] is not None else ""
                    vv=v if v is not None else ""
                    if str(ov)!=str(vv):changes.append(f"{labels[k]}: {ov or '—'} → {vv or '—'}")
            else:
                aid=con.execute("""INSERT INTO actions(name,company_id,salesperson_id,project_id,created_date,deadline,status,
                    products,next_step,note,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",vals).lastrowid
                changes=[]

        if self.aid:
            if changes:log_history(aid,"action_edit","Upravil příležitost","; ".join(changes),vals[1],user_name=user)
        else:
            log_history(aid,"action_create","Založil příležitost",
                        f"Akce: {action_name}; Společnost: {self.company.get().strip() or '—'}; Stav: {self.status.get()}",
                        vals[1],user_name=user)
        self.result=aid;self.destroy()


class RequestDialog(tk.Toplevel):
    def __init__(self,parent,rid=None,pre_action=None,pre_requested_for=None,pre_company=None):
        super().__init__(parent);enable_dialog_maximize(self,980,700);self.title("Poptávka");self.transient(parent);self.grab_set();self.result=None;self.rid=rid;bind_dialog_keys(self,self.ok)
        vals={}
        with db() as con:
            self.companies=con.execute("""SELECT MIN(id) id,official_name FROM companies
                WHERE active=1 AND trim(coalesce(official_name,''))<>''
                GROUP BY lower(trim(official_name))
                ORDER BY official_name COLLATE CZECH""").fetchall()
            self.actions=con.execute("""SELECT MIN(id) id,trim(name) name FROM actions
                WHERE trim(coalesce(name,''))<>''
                GROUP BY lower(trim(name))
                ORDER BY trim(name) COLLATE CZECH""").fetchall()
            self.materials=con.execute("SELECT id,name FROM materials WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()
            if rid:
                r=con.execute("""SELECT r.*,c.official_name company,cf.official_name requested_for,a.name action_name
                    FROM requests r
                    LEFT JOIN companies c ON c.id=r.company_id
                    LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                    LEFT JOIN actions a ON a.id=r.action_id
                    WHERE r.id=?""",(rid,)).fetchone()
                if r:vals=dict(r)
            elif pre_action:
                r=con.execute("SELECT name FROM actions WHERE id=?",(pre_action,)).fetchone()
                if r:vals["action_name"]=r["name"]
        if pre_company:
            vals["company"]=pre_company
        if pre_requested_for:
            vals["requested_for"]=pre_requested_for
        elif pre_action and not vals.get("requested_for"):
            with db() as con:
                r=con.execute("""SELECT c.official_name FROM actions a
                                 LEFT JOIN companies c ON c.id=a.company_id WHERE a.id=?""",(pre_action,)).fetchone()
                if r and r["official_name"]:vals["requested_for"]=r["official_name"]

        with db() as con:
            _mivo_ids=set(mivo_company_ids(con))
        self.is_mivo=bool(vals.get("company_id") in _mivo_ids)
        if not self.is_mivo and vals.get("company"):
            _cv=(vals.get("company") or "").strip().casefold()
            self.is_mivo=(_cv=="mivo" or _cv.startswith("mivo ") or _cv.startswith("mivo,") or _cv.startswith("mivo."))

        f=scrollable_dialog_frame(self,14)
        self.company=tk.StringVar(value=vals.get("company",""))
        self.selected_company_id=None
        self._contact_trace=None
        self.requested_for=tk.StringVar(value=vals.get("requested_for",""))
        self.action=tk.StringVar(value=vals.get("action_name",""))
        self.asked=tk.StringVar(value=vals.get("asked_date",date.today().isoformat()))
        self.received=tk.StringVar(value=vals.get("received_date",""))
        self.item=tk.StringVar(value=vals.get("item",""))
        with db() as con:
            self.user_names=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        self.assigned=tk.StringVar(value=vals.get("assigned_user","") or get_setting("active_user",""))

        ttk.Label(f,text="Dodavatel").grid(row=0,column=0,sticky="w",padx=(0,10),pady=5)
        self.company_map={r["official_name"]:r["id"] for r in self.companies}
        supplier_wrap=ttk.Frame(f);supplier_wrap.grid(row=0,column=1,columnspan=2,sticky="ew",pady=5)
        supplier_wrap.columnconfigure(0,weight=1)
        self.company_box=AutocompleteEntry(
            supplier_wrap,
            textvariable=self.company,
            values=[(r["official_name"],r["id"]) for r in self.companies]
        )
        self.company_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(supplier_wrap,text="+ Nová společnost",
                   command=self.new_supplier_company).grid(row=0,column=1,padx=(6,0))
        self.company_box.bind("<<AutocompleteSelected>>",lambda e:self._select_request_company())
        self.company_box.bind("<Return>",lambda e:self.after_idle(self._reload_contacts_from_company))
        self.company_box.bind("<FocusOut>",lambda e:self.after(120,self._reload_contacts_from_company))
        self.company.trace_add("write",self._company_text_changed)

        ttk.Label(f,text="Odběratel").grid(row=1,column=0,sticky="w",padx=(0,10),pady=5)
        customer_wrap=ttk.Frame(f);customer_wrap.grid(row=1,column=1,columnspan=2,sticky="ew",pady=5)
        customer_wrap.columnconfigure(0,weight=1)
        self.requested_for_box=AutocompleteEntry(customer_wrap,textvariable=self.requested_for,
            values=[(r["official_name"],r["id"]) for r in self.companies])
        self.requested_for_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(customer_wrap,text="+ Nová společnost",
                   command=self.new_customer_company).grid(row=0,column=1,padx=(6,0))

        ttk.Label(f,text="Akce").grid(row=2,column=0,sticky="w",padx=(0,10),pady=5)
        action_wrap=ttk.Frame(f);action_wrap.grid(row=2,column=1,columnspan=2,sticky="ew",pady=5)
        action_wrap.columnconfigure(0,weight=1)
        self.action_box=AutocompleteEntry(action_wrap,textvariable=self.action,values=[r["name"] for r in self.actions])
        self.action_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(action_wrap,text="+ Nová akce",command=self.new_action).grid(row=0,column=1,padx=(6,0))

        ttk.Label(f,text="Poptáno").grid(row=3,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.asked).grid(row=3,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Obdrženo").grid(row=4,column=0,sticky="w",padx=(0,10),pady=5)
        DatePicker(f,self.received).grid(row=4,column=1,sticky="ew",pady=5)

        ttk.Label(f,text="Poptáváno").grid(row=5,column=0,sticky="w",padx=(0,10),pady=5)
        mr=ttk.Frame(f);mr.grid(row=5,column=1,sticky="ew");mr.columnconfigure(0,weight=1)
        self.item_box=AutocompleteEntry(mr,textvariable=self.item,values=[r["name"] for r in self.materials])
        self.item_box.grid(row=0,column=0,sticky="ew")
        ttk.Button(mr,text="+ Přidat",command=self.new_material).grid(row=0,column=1,padx=(6,0))
        ttk.Button(mr,text="⚙ Spravovat",command=self.manage_materials).grid(row=0,column=2,padx=(6,0))

        self.include=tk.BooleanVar(value=bool(int(vals.get("include_project_in_subject",get_setting("include_project_default","1")) or 1)))
        ttk.Checkbutton(f,text="Uvést název akce v předmětu",variable=self.include,command=self.update_preview).grid(row=6,column=1,sticky="w",pady=4)

        self.open_after=tk.BooleanVar(value=False)

        ttk.Label(f,text="Komu zaslat").grid(row=7,column=0,sticky="nw",padx=(0,10),pady=5)
        recipient_wrap=ttk.Frame(f)
        recipient_wrap.grid(row=7,column=1,columnspan=2,sticky="ew",pady=4)
        recipient_wrap.columnconfigure(0,weight=1)
        self.contact_count_label=ttk.Label(recipient_wrap,text="Vyberte společnost, u které poptáváte.")
        self.contact_count_label.grid(row=0,column=0,sticky="w",pady=(0,4))
        self.contacts=ttk.LabelFrame(recipient_wrap,text="Osoby z Adresáře",padding=8)
        self.contacts.grid(row=1,column=0,sticky="ew")
        self.contact_vars=[]
        manual=ttk.Frame(recipient_wrap);manual.grid(row=2,column=0,sticky="ew",pady=(6,0));manual.columnconfigure(1,weight=1)
        ttk.Label(manual,text="Jiný e-mail:").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.manual_recipient=tk.StringVar()
        ttk.Entry(manual,textvariable=self.manual_recipient).grid(row=0,column=1,sticky="ew")
        ttk.Button(manual,text="+ Přidat osobu",command=self.add_contact_person).grid(row=0,column=2,padx=(6,0))

        ttk.Label(f,text=f"Kopie: {CC_ALWAYS}").grid(row=9,column=1,sticky="w",pady=4)

        ttk.Label(f,text="Předmět").grid(row=10,column=0,sticky="w",padx=(0,10),pady=5)
        _default_subject=vals.get("mail_subject","") or build_subject(
            vals.get("company",""),vals.get("action_name",""),vals.get("item",""),
            vals.get("asked_date",date.today().isoformat()),
            bool(int(vals.get("include_project_in_subject",get_setting("include_project_default","1")) or 1))
        )
        self.subject=tk.StringVar(value=_default_subject)
        ttk.Entry(f,textvariable=self.subject,state=("normal" if self.is_mivo else "readonly")).grid(
            row=10,column=1,columnspan=2,sticky="ew")

        ttk.Label(f,text="Text").grid(row=11,column=0,sticky="nw",padx=(0,10),pady=5)
        tx=tk.Text(f,wrap="word",height=5);tx.grid(row=11,column=1,columnspan=2,sticky="ew")
        tx.insert("1.0","Dobrý den,\n\n\n\nPředem velice děkuji,");tx.configure(state="disabled")

        # Similar history panel is useful for normal Poptávky, but deliberately omitted in MIVO.
        if not self.is_mivo:
            ttk.Label(f,text="Podobné předchozí poptávky").grid(row=12,column=0,sticky="nw",padx=(0,10),pady=(10,5))
            hist_frame=ttk.Frame(f)
            hist_frame.grid(row=12,column=1,columnspan=2,sticky="nsew",pady=(10,5))
            hist_frame.columnconfigure(0,weight=1)
            self.history_tree=ttk.Treeview(hist_frame,columns=("Datum","Odběratel","Dodavatel","Akce","Materiál","Stav"),show="headings",height=5)
            for c,w in (("Datum",90),("Odběratel",160),("Dodavatel",160),("Akce",230),("Materiál",220),("Stav",90)):
                self.history_tree.heading(c,text=c);self.history_tree.column(c,width=w,anchor="w")
            self.history_tree.grid(row=0,column=0,sticky="nsew")
            hs=ttk.Scrollbar(hist_frame,orient="vertical",command=self.history_tree.yview)
            hs.grid(row=0,column=1,sticky="ns");self.history_tree.configure(yscrollcommand=hs.set)
            bind_row_double_click(self.history_tree,self.open_history_detail)
            detail_row=13
            f.rowconfigure(12,weight=1)
        else:
            detail_row=12

        ttk.Label(f,text="Řeší").grid(row=detail_row,column=0,sticky="nw",padx=(0,10),pady=5)
        self.assigned_box=InlineChoice(f,textvariable=self.assigned,values=self.user_names,editable=True,max_rows=6)
        self.assigned_box.grid(row=detail_row,column=1,sticky="ew",pady=5)
        ttk.Label(f,text="Poznámka").grid(row=detail_row+1,column=0,sticky="nw",padx=(0,10),pady=5)
        self.note=tk.Text(f,wrap="word",height=3);self.note.grid(row=detail_row+1,column=1,columnspan=2,sticky="ew")
        self.note.insert("1.0",vals.get("note","") or "")

        f.columnconfigure(1,weight=1)
        b=ttk.Frame(f);b.grid(row=detail_row+2,column=0,columnspan=3,sticky="e",pady=10)
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=4)
        ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.ok).pack(side="right")

        self._contacts_after=None
        self._loaded_company_id=None
        for v in (self.requested_for,self.action,self.item,self.asked):
            v.trace_add("write",lambda *a:self._changed())
        # Pokud je společnost předvyplněná, nastavíme i interní ID autocomplete prvku.
        init_cid=self.company_map.get(self.company.get())
        if init_cid:
            self.selected_company_id=init_cid
            self.company_box.selected_payload=init_cid
            self.company_box.selected_value=self.company.get()
        init_for=self._resolve_company_id(self.requested_for.get())
        if init_for:
            self.requested_for_box.selected_payload=init_for
            self.requested_for_box.selected_value=self.requested_for.get()
        saved_recipients=[x.strip() for x in (vals.get("recipients_snapshot","") or "").split(";") if x.strip()] if rid else []
        self.load_contacts(saved_recipients)
        if saved_recipients:
            known={email.lower() for var,email in self.contact_vars if email}
            extra=[x for x in saved_recipients if x.lower() not in known]
            if extra:self.manual_recipient.set(extra[0])
        self.update_preview()
        if not self.is_mivo:self.refresh_similar()
        self.after(80,self._reload_contacts_from_company)

    def _resolve_company_id(self,name):
        name=(name or "").strip()
        if not name:return None
        # Prefer exact selected payload from autocomplete; otherwise exact official name only.
        with db() as con:
            rows=con.execute("""SELECT id FROM companies
                                WHERE active=1 AND lower(trim(official_name))=lower(trim(?))
                                ORDER BY id""",(name,)).fetchall()
        return rows[0]["id"] if len(rows)==1 else None

    def company_id(self):
        payload=getattr(self.company_box,"selected_payload",None)
        if payload:
            self.selected_company_id=payload
            return payload
        if getattr(self,"selected_company_id",None):
            # Verify text still matches that company so stale IDs cannot leak.
            with db() as con:
                r=con.execute("SELECT official_name FROM companies WHERE id=?",(self.selected_company_id,)).fetchone()
            if r and (r["official_name"] or "").strip().lower()==self.company.get().strip().lower():
                return self.selected_company_id
        cid=self._resolve_company_id(self.company.get())
        self.selected_company_id=cid
        return cid

    def requested_for_id(self):
        payload=getattr(self.requested_for_box,"selected_payload",None)
        if payload:return payload
        return self._resolve_company_id(self.requested_for.get())

    def action_id(self):
        name=self.action.get().strip()
        if not name:return None
        payload=getattr(self.action_box,"selected_payload",None)
        if payload:
            with db() as con:
                r=con.execute("SELECT id FROM actions WHERE id=?",(payload,)).fetchone()
            if r:return r["id"]
        with db() as con:
            rows=con.execute("""SELECT id FROM actions
                                WHERE lower(trim(name))=lower(trim(?))
                                ORDER BY id""",(name,)).fetchall()
        # Stejný název Akce může být u více společností. Pro Poptávku jde o
        # společnou Akci; pokud existuje, použijeme jednoznačně první historickou vazbu.
        return rows[0]["id"] if rows else None

    def _changed(self):
        self.update_preview()
        if hasattr(self,"_hist_after") and self._hist_after:
            try:self.after_cancel(self._hist_after)
            except:pass
        self._hist_after=self.after(180,self.refresh_similar)

    def _company_text_changed(self,*_):
        payload=getattr(self.company_box,"selected_payload",None)
        if payload:
            self.selected_company_id=payload
            return
        self.selected_company_id=None
        if getattr(self,"_contact_trace",None):
            try:self.after_cancel(self._contact_trace)
            except:pass
        self._contact_trace=self.after(180,self._reload_contacts_from_company)

    def _reload_contacts_from_company(self):
        self._contact_trace=None
        payload=getattr(self.company_box,"selected_payload",None)
        self.selected_company_id=payload if payload else self._resolve_company_id(self.company.get())
        self.load_contacts(None)

    def _select_request_company(self):
        payload=getattr(self.company_box,"selected_payload",None)
        self.selected_company_id=payload if payload else self._resolve_company_id(self.company.get())
        self.load_contacts(None)


    def load_contacts(self,selected=None):
        frame=getattr(self,"contacts_frame",None) or getattr(self,"contacts",None)
        if frame is None:return
        for w in frame.winfo_children():w.destroy()
        self.contact_vars=[]
        cid=self.company_id()
        if not cid:
            if hasattr(self,"contact_count_label"):self.contact_count_label.config(text="Vyberte společnost.")
            return
        with db() as con:
            company=con.execute("SELECT official_name FROM companies WHERE id=?",(cid,)).fetchone()
            rows=con.execute("""SELECT id,name,email,role FROM people
                                WHERE active=1 AND company_id=?
                                ORDER BY name COLLATE CZECH,email""",(cid,)).fetchall()
        selected_set={x.strip().lower() for x in (selected or []) if x and x.strip()}
        with_email=0
        for r in rows:
            email=(r["email"] or "").strip()
            if email:with_email+=1
            label=(r["name"] or "").strip() or "(bez jména)"
            if r["role"]:label+=f" · {r['role']}"
            label+=f" — {email}" if email else " — bez e-mailu"
            var=tk.BooleanVar(value=email.lower() in selected_set if email else False)
            cb=ttk.Checkbutton(frame,text=label,variable=var)
            if not email:cb.state(["disabled"])
            cb.pack(anchor="w",pady=2)
            self.contact_vars.append((var,email))
        nm=company["official_name"] if company else self.company.get()
        if hasattr(self,"contact_count_label"):
            self.contact_count_label.config(text=f"{nm} · osoby: {len(rows)} · s e-mailem: {with_email}")
        if not rows:
            ttk.Label(frame,text="U této společnosti nejsou v Adresáři žádné osoby.").pack(anchor="w",pady=4)


    def add_contact_person(self):
        cid=self.company_id()
        if not cid:
            return messagebox.showwarning("Příjemci","Nejdřív vyberte společnost, u které poptáváte.",parent=self)
        d=PersonDialog(self,pre_company_id=cid)
        self.wait_window(d)
        if d.result:
            self._loaded_company_id=None
            self.selected_company_id=cid
            self.company_box.selected_payload=cid
            self.load_contacts()

    def _new_request_company(self,target):
        d=CompanyDialog(self);self.wait_window(d)
        if not d.result:return
        with db() as con:
            r=con.execute("SELECT id,official_name FROM companies WHERE id=?",(d.result,)).fetchone()
        if not r:return
        # Refresh both company selectors from the shared database.
        with db() as con:
            self.companies=con.execute("""SELECT MIN(id) id,official_name FROM companies
                WHERE active=1 AND trim(coalesce(official_name,''))<>''
                GROUP BY lower(trim(official_name))
                ORDER BY official_name COLLATE CZECH""").fetchall()
        values=[(x["official_name"],x["id"]) for x in self.companies]
        self.company_box.set_values(values)
        self.requested_for_box.set_values(values)
        self.company_map={x["official_name"]:x["id"] for x in self.companies}
        if target=="supplier":
            self.company.set(r["official_name"])
            self.selected_company_id=r["id"]
            try:self.company_box.selected_payload=r["id"]
            except Exception:pass
            self.load_contacts(None)
        else:
            self.requested_for.set(r["official_name"])
            try:self.requested_for_box.selected_payload=r["id"]
            except Exception:pass

    def new_supplier_company(self):
        self._new_request_company("supplier")

    def new_customer_company(self):
        self._new_request_company("customer")

    def new_action(self):
        d=ActionDialog(self);d.name.set(self.action.get().strip())
        # Pro novou akci předvyplnit společnost "pro koho" pokud je zvolená.
        d.company.set(self.requested_for.get().strip() or self.company.get().strip())
        self.wait_window(d)
        if d.result:
            with db() as con:r=con.execute("SELECT name FROM actions WHERE id=?",(d.result,)).fetchone()
            self.action.set(r["name"])
            merged=list(self.actions)+[{"id":d.result,"name":r["name"]}]
            seen=set();unique=[]
            for x in merged:
                k=(x["name"] or "").strip().casefold()
                if not k or k in seen:continue
                seen.add(k);unique.append(x)
            self.actions=unique
            self.action_box.set_values([x["name"] for x in self.actions])

    def manage_materials(self):
        app=find_app(self)
        if app:
            app.manage_code_lists("Poptávané zboží / materiály",self)
            with db() as con:
                self.materials=con.execute(
                    "SELECT id,name FROM materials WHERE active=1 ORDER BY name COLLATE CZECH").fetchall()
            self.item_box.set_values([r["name"] for r in self.materials])

    def new_material(self):
        name=simpledialog.askstring("Materiál","Název nového poptávaného materiálu:",initialvalue=self.item.get(),parent=self)
        if not name:return
        with db() as con:con.execute("INSERT OR IGNORE INTO materials(name) VALUES(?)",(name.strip(),))
        self.item.set(name.strip());self.item_box.set_values(self.item_box.values+[name.strip()])

    def update_preview(self):
        if self.is_mivo:
            return
        self.subject.set(build_subject(self.company.get().strip(),self.action.get().strip(),self.item.get().strip(),self.asked.get(),self.include.get()))


    def refresh_similar(self):
        if not hasattr(self,"history_tree"):return
        for x in self.history_tree.get_children():self.history_tree.delete(x)
        aid=self.action_id()
        item=self.item.get().strip().lower()
        if not aid and len(item)<3:return
        with db() as con:
            sql="""SELECT r.id,r.asked_date,r.received_date,r.item,a.name action_name,
                    cu.official_name company_u,cf.official_name company_for
                   FROM requests r
                   LEFT JOIN actions a ON a.id=r.action_id
                   LEFT JOIN companies cu ON cu.id=r.company_id
                   LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                   WHERE 1=1"""
            params=[]
            clauses=[]
            if aid:
                clauses.append("r.action_id=?");params.append(aid)
            if item:
                clauses.append("lower(r.item) LIKE ?");params.append("%"+item+"%")
            if clauses:sql+=" AND ("+" OR ".join(clauses)+")"
            if self.rid:
                sql+=" AND r.id<>?";params.append(self.rid)
            sql+=" ORDER BY r.asked_date DESC,r.id DESC LIMIT 20"
            rows=con.execute(sql,params).fetchall()
        for r in rows:
            self.history_tree.insert("","end",iid=f"h{r['id']}",values=(
                fmt_date(r["asked_date"]),
                r["company_for"] or "—",
                r["company_u"] or "—",
                r["action_name"] or "—",
                r["item"] or "—",
                "Obdrženo" if r["received_date"] else "Čekám"
            ))

    def open_history_detail(self,e=None):
        s=self.history_tree.selection()
        if not s:return
        rid=int(s[0][1:])
        with db() as con:
            r=con.execute("""SELECT r.*,a.name action_name,cu.official_name company_u,cf.official_name company_for
                FROM requests r
                LEFT JOIN actions a ON a.id=r.action_id
                LEFT JOIN companies cu ON cu.id=r.company_id
                LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                WHERE r.id=?""",(rid,)).fetchone()
        if not r:return
        messagebox.showinfo("Předchozí poptávka",
            f"Datum: {fmt_date(r['asked_date'])}\n"
            f"Akce: {r['action_name'] or '—'}\n"
            f"Odběratel: {r['company_for'] or '—'}\n"
            f"Dodavatel: {r['company_u'] or '—'}\n"
            f"Materiál: {r['item'] or '—'}\n"
            f"Příjemci: {r['recipients_snapshot'] or '—'}\n"
            f"Stav: {'Obdrženo' if r['received_date'] else 'Čekám'}\n"
            f"Poznámka: {r['note'] or '—'}",
            parent=self)

    def ok(self):
        cid=self.company_id()
        if not cid:return messagebox.showwarning("Poptávka","Vyberte Dodavatele.",parent=self)
        # Odběratel je volitelný. Pokud je ale napsaný text, musí odpovídat existující společnosti.
        for_text=self.requested_for.get().strip()
        for_id=self.requested_for_id() if for_text else None
        if for_text and not for_id:
            return messagebox.showwarning("Poptávka",
                "Vyberte existujícího Odběratele, založte novou společnost, nebo pole nechte prázdné.",parent=self)
        # Akce je také volitelná. Vyplněný text ale musí odpovídat existující Akci.
        action_text=self.action.get().strip()
        aid=self.action_id() if action_text else None
        if action_text and not aid:
            return messagebox.showwarning("Poptávka",
                "Vyberte existující Akci, založte novou, nebo pole nechte prázdné.",parent=self)
        if not self.item.get().strip():return messagebox.showwarning("Poptávka","Vyplňte poptávaný materiál.",parent=self)
        asked=parse_date(self.asked.get())
        if not asked:return messagebox.showwarning("Poptávka","Vyplňte platné datum Poptáno.",parent=self)
        received=parse_date(self.received.get()) if self.received.get().strip() else ""
        with db() as con:con.execute("INSERT OR IGNORE INTO materials(name) VALUES(?)",(self.item.get().strip(),))
        rec=[email for var,email in self.contact_vars if email and var.get()]
        manual=(self.manual_recipient.get() or "").strip()
        if manual and manual not in rec:rec.append(manual)
        set_setting("include_project_default","1" if self.include.get() else "0")
        self.result={
            "company_id":cid,"requested_for_company_id":for_id,"action_id":aid,"assigned_user":self.assigned.get().strip(),
            "asked":asked,"received":received,
            "item":self.item.get().strip(),"note":self.note.get("1.0","end").strip(),
            "include":1 if self.include.get() else 0,"recipients":rec,
            "subject":self.subject.get(),"open":self.open_after.get()
        }
        self.destroy()




def configure_windows_app_identity(win):
    """Set TURTO icon/identity on the real application window and Windows taskbar."""
    try:
        ico=ROOT/"turto_logo.ico"
        if ico.exists():
            win.iconbitmap(default=str(ico))
    except Exception:
        pass
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "TURTO.Zakazky")
        except Exception:
            pass


def _load_offer_router():
    """Načte ověřený parser z TURTO Nabídky V4.7.24, zabalený přímo v CRM."""
    import importlib.util
    engine=ROOT/"offers_engine"
    if not engine.exists():
        raise RuntimeError("Chybí interní modul offers_engine.")
    if str(engine) not in sys.path:
        sys.path.insert(0,str(engine))
    name="_turto_nabidky_router"
    if name in sys.modules:return sys.modules[name]
    spec=importlib.util.spec_from_file_location(name,engine/"Nabidky_Router.py")
    mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod)
    return mod

def _offer_date_iso(value):
    s=str(value or "").strip()
    for f in ("%d.%m.%Y","%Y-%m-%d","%d.%m.%y"):
        try:return datetime.strptime(s,f).strftime("%Y-%m-%d")
        except Exception:pass
    return parse_date(s) or date.today().isoformat()

def _pdf_raw_text(path):
    try:
        import fitz
        doc=fitz.open(path)
        return "\n".join(page.get_text("text") for page in doc)
    except Exception:
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:return "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception:return ""

def extract_offer_pdf(path):
    """Parser z TURTO Nabídky V4.7.24 – Leviat + GEROtop včetně obrázků a slev."""
    router=_load_offer_router()
    data=router.parse_offer(str(path))
    return data,_pdf_raw_text(path)

def _company_id_by_name(con,name):
    name=(name or "").strip()
    if not name:return None
    r=con.execute("""SELECT id FROM companies
        WHERE lower(trim(official_name))=lower(trim(?))
           OR lower(trim(short_name))=lower(trim(?))
        ORDER BY active DESC,id LIMIT 1""",(name,name)).fetchone()
    if r:return r["id"]
    # Dodavatelský parser vrací např. GEROtop / Leviat; dovolíme částečnou shodu.
    r=con.execute("""SELECT id FROM companies
        WHERE lower(official_name) LIKE ? OR lower(short_name) LIKE ?
        ORDER BY active DESC,id LIMIT 1""",(f"%{name.casefold()}%",f"%{name.casefold()}%")).fetchone()
    return r["id"] if r else None

def _stable_offer_key(con,supplier,name,offer_date):
    """Stejná logika jako V4.7.24: pozdější kratší základní název sjednotí starší dovětky."""
    supplier=(supplier or "").strip() or "Neurčeno"
    name=str(name or "").strip()
    if not name:return name
    alias=con.execute("SELECT canonical_key FROM offer_product_aliases WHERE supplier=? AND alias=?",(supplier,name)).fetchone()
    if alias:return alias["canonical_key"]
    existing=[str(r[0]).strip() for r in con.execute("""SELECT DISTINCT i.item_key
        FROM supplier_offer_items i JOIN supplier_offers o ON o.id=i.offer_id
        WHERE coalesce(o.supplier_name,'')=? AND trim(coalesce(i.item_key,''))<>''""",(supplier,)).fetchall() if r[0]]
    shorter=[x for x in existing if len(x)<len(name) and name.startswith(x) and name[len(x):].startswith((" ","–","-","("))]
    if shorter:
        key=max(shorter,key=len)
    else:
        longer=[x for x in existing if len(x)>len(name) and x.startswith(name) and x[len(name):].startswith((" ","–","-","("))]
        key=name
        # Novější kratší název se stává hlavním klíčem i pro starší historii.
        if longer:
            for old in longer:
                con.execute("UPDATE supplier_offer_items SET item_key=? WHERE item_key=? AND offer_id IN (SELECT id FROM supplier_offers WHERE supplier_name=?)",(key,old,supplier))
                con.execute("""INSERT INTO offer_product_aliases(supplier,alias,canonical_key,first_seen,last_seen)
                    VALUES(?,?,?,?,?) ON CONFLICT(supplier,alias) DO UPDATE SET canonical_key=excluded.canonical_key,last_seen=excluded.last_seen""",
                    (supplier,old,key,offer_date,offer_date))
    con.execute("""INSERT INTO offer_product_aliases(supplier,alias,canonical_key,first_seen,last_seen)
        VALUES(?,?,?,?,?) ON CONFLICT(supplier,alias) DO UPDATE SET canonical_key=excluded.canonical_key,last_seen=excluded.last_seen""",
        (supplier,name,key,offer_date,offer_date))
    return key

def _save_canonical_image(con,supplier,item_key,image_bytes,image_ext,offer_no,offer_date):
    if not image_bytes or not item_key:return
    ih=hashlib.sha1(bytes(image_bytes)).hexdigest()
    cur=con.execute("SELECT source_offer_date,image_hash FROM offer_product_images WHERE supplier=? AND item_key=?",(supplier,item_key)).fetchone()
    def dk(v):
        try:return datetime.strptime(str(v or ""),"%Y-%m-%d").date()
        except:return date.min
    should=cur is None or dk(offer_date)>dk(cur["source_offer_date"])
    if cur and dk(offer_date)==dk(cur["source_offer_date"]) and ih!=cur["image_hash"]:should=True
    if should:
        con.execute("""INSERT INTO offer_product_images(supplier,item_key,image_blob,image_ext,source_offer_no,source_offer_date,image_hash,updated_at)
            VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(supplier,item_key) DO UPDATE SET image_blob=excluded.image_blob,image_ext=excluded.image_ext,
            source_offer_no=excluded.source_offer_no,source_offer_date=excluded.source_offer_date,image_hash=excluded.image_hash,updated_at=CURRENT_TIMESTAMP""",
            (supplier,item_key,sqlite3.Binary(image_bytes),image_ext or "",offer_no or "",offer_date,ih))

def save_offer_import(pdf_path,supplier_name="",customer_name="",action_name="",offer_date="",offer_number="",note=""):
    parsed,raw=extract_offer_pdf(pdf_path)
    data=Path(pdf_path).read_bytes();h=hashlib.sha256(data).hexdigest()
    parsed_supplier=str(parsed.get("supplier") or supplier_name or "").strip()
    parsed_date=_offer_date_iso(parsed.get("date") or offer_date)
    parsed_no=str(parsed.get("offer_no") or offer_number or "").strip()
    reference=str(parsed.get("reference") or "").strip()
    supplier_name=(supplier_name or parsed_supplier).strip()
    offer_date=parse_date(offer_date) if offer_date and offer_date!=date.today().isoformat() else parsed_date
    offer_date=offer_date or parsed_date
    offer_number=(offer_number or parsed_no).strip()

    with db() as con:
        existing=con.execute("SELECT id FROM supplier_offers WHERE source_hash=?",(h,)).fetchone()
        if existing:return existing["id"],False,len(parsed.get("items") or []),parsed

        sid=_company_id_by_name(con,supplier_name or parsed_supplier)
        cid=_company_id_by_name(con,customer_name)
        aid=None
        chosen_action=(action_name or "").strip()
        if chosen_action:
            r=con.execute("SELECT id FROM actions WHERE lower(trim(name))=lower(trim(?)) ORDER BY id DESC LIMIT 1",(chosen_action,)).fetchone()
            aid=r["id"] if r else None
        elif reference:
            r=con.execute("SELECT id,name FROM actions WHERE lower(trim(name))=lower(trim(?)) ORDER BY id DESC LIMIT 1",(reference,)).fetchone()
            if r:aid=r["id"];chosen_action=r["name"]

        oid=con.execute("""INSERT INTO supplier_offers(
            offer_date,supplier_company_id,customer_company_id,action_id,offer_number,
            source_pdf,source_hash,raw_text,note,updated_by,supplier_name,source_type,reference,
            gross_value,discount_pct,net_value,total_value)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (offer_date,sid,cid,aid,offer_number,str(pdf_path),h,raw,note,get_setting("active_user",""),
             parsed_supplier or supplier_name,str(parsed.get("source_type") or "PDF"),reference,
             float(parsed.get("gross") or 0),float(parsed.get("discount_pct") or 0),
             float(parsed.get("net") or 0),float(parsed.get("net") or parsed.get("total") or 0))).lastrowid

        for pos,item in enumerate(parsed.get("items") or [],1):
            original=str(item.get("description") or item.get("item_key") or item.get("product") or "").strip()
            key=_stable_offer_key(con,parsed_supplier or supplier_name,original,offer_date)
            qty=float(item.get("quantity") or 0)
            unit_price=float(item.get("unit_price") or 0)
            original_price=float(item.get("original_unit_price") or unit_price or 0)
            disc=float(item.get("discount_pct") or 0)
            total=float(item.get("item_total") or (qty*unit_price))
            image=item.get("image_bytes");ext=str(item.get("image_ext") or "")
            con.execute("""INSERT INTO supplier_offer_items(
                offer_id,position,original_name,item_key,quantity,unit,unit_price,discount,net_price,total_price,
                image_source_offer_date,image_blob,image_ext,product_code,details,original_unit_price,discount_pct)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (oid,int(item.get("position") or pos),original,key,qty,str(item.get("unit") or ""),
                 unit_price,disc,unit_price,total,offer_date,sqlite3.Binary(image) if image else None,ext,
                 str(item.get("product") or ""),str(item.get("details") or ""),original_price,disc))
            con.execute("INSERT OR IGNORE INTO offer_item_aliases(item_key,alias) VALUES(?,?)",(key,original))
            _save_canonical_image(con,parsed_supplier or supplier_name,key,image,ext,offer_number,offer_date)

        total=con.execute("SELECT COALESCE(SUM(total_price),0) FROM supplier_offer_items WHERE offer_id=?",(oid,)).fetchone()[0]
        con.execute("UPDATE supplier_offers SET total_value=CASE WHEN net_value>0 THEN net_value ELSE ? END WHERE id=?",(total,oid))
    return oid,True,len(parsed.get("items") or []),parsed


class OfferImportDialog(tk.Toplevel):
    def __init__(self,parent):
        super().__init__(parent);enable_dialog_maximize(self,920,620);self.title("Import PDF nabídky");self.transient(parent);self.grab_set();self.result=None
        f=scrollable_dialog_frame(self,18)
        with db() as con:
            companies=[r["official_name"] for r in con.execute("SELECT official_name FROM companies WHERE active=1 ORDER BY official_name COLLATE CZECH")]
            actions=[r["name"] for r in con.execute("SELECT DISTINCT trim(name) name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY trim(name) COLLATE CZECH")]
        self.path=tk.StringVar();self.supplier=tk.StringVar();self.customer=tk.StringVar();self.action=tk.StringVar()
        self.offer_date=tk.StringVar(value=date.today().isoformat());self.number=tk.StringVar()
        ttk.Label(f,text="PDF nabídka").grid(row=0,column=0,sticky="w",pady=6)
        p=ttk.Frame(f);p.grid(row=0,column=1,sticky="ew",pady=6);p.columnconfigure(0,weight=1)
        ttk.Entry(p,textvariable=self.path).grid(row=0,column=0,sticky="ew")
        ttk.Button(p,text="Vybrat PDF",style="Accent.TButton",command=self.pick).grid(row=0,column=1,padx=(8,0))
        ttk.Label(f,text="Dodavatel").grid(row=1,column=0,sticky="w",pady=6)
        AutocompleteEntry(f,textvariable=self.supplier,values=companies).grid(row=1,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Odběratel").grid(row=2,column=0,sticky="w",pady=6)
        AutocompleteEntry(f,textvariable=self.customer,values=companies).grid(row=2,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Akce / Příležitost").grid(row=3,column=0,sticky="w",pady=6)
        AutocompleteEntry(f,textvariable=self.action,values=actions).grid(row=3,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Datum nabídky").grid(row=4,column=0,sticky="w",pady=6);DatePicker(f,self.offer_date).grid(row=4,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Číslo nabídky").grid(row=5,column=0,sticky="w",pady=6);ttk.Entry(f,textvariable=self.number).grid(row=5,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Poznámka").grid(row=6,column=0,sticky="nw",pady=6);self.note=tk.Text(f,height=4,wrap="word");self.note.grid(row=6,column=1,sticky="ew",pady=6)
        ttk.Label(f,text="Importer zachová originální název položky a současně vytvoří item_key pro historii cen.",style="PageSubtitle.TLabel").grid(row=7,column=1,sticky="w",pady=(2,12))
        b=ttk.Frame(f);b.grid(row=8,column=0,columnspan=2,sticky="e",pady=10)
        ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="right",padx=5)
        ttk.Button(b,text="Importovat",style="Accent.TButton",command=self.ok).pack(side="right")
        f.columnconfigure(1,weight=1)
    def pick(self):
        p=filedialog.askopenfilename(parent=self,title="Vyberte PDF nabídku",filetypes=[("PDF","*.pdf")])
        if not p:return
        self.path.set(p)
        try:
            parsed,_=extract_offer_pdf(p)
            supplier=str(parsed.get("supplier") or "")
            if supplier and not self.supplier.get().strip():self.supplier.set(supplier)
            if parsed.get("offer_no"):self.number.set(str(parsed.get("offer_no")))
            if parsed.get("date"):self.offer_date.set(_offer_date_iso(parsed.get("date")))
            ref=str(parsed.get("reference") or "").strip()
            if ref and not self.action.get().strip():
                with db() as con:
                    r=con.execute("SELECT name FROM actions WHERE lower(trim(name))=lower(trim(?)) ORDER BY id DESC LIMIT 1",(ref,)).fetchone()
                if r:self.action.set(r["name"])
            self.note.delete("1.0","end")
            self.note.insert("1.0",f"Rozpoznáno: {supplier or 'neznámý dodavatel'} | CN {parsed.get('offer_no') or '—'} | položek: {len(parsed.get('items') or [])}")
        except Exception as e:
            messagebox.showwarning("Nabídky",f"PDF bylo vybráno, ale automatické rozpoznání hlásí:\n\n{e}",parent=self)
    def ok(self):
        p=self.path.get().strip()
        if not p:return messagebox.showwarning("Nabídky","Vyberte PDF.",parent=self)
        try:
            oid,created,count,parsed=save_offer_import(p,self.supplier.get(),self.customer.get(),self.action.get(),self.offer_date.get(),self.number.get(),self.note.get("1.0","end").strip())
        except Exception as e:
            return messagebox.showerror("Import PDF",str(e),parent=self)
        self.result=oid
        msg=(f"Importováno {count} položek z nabídky {parsed.get('supplier') or ''}."
             if created else "Toto PDF už je v databázi uložené.")
        messagebox.showinfo("Nabídky",msg,parent=self);self.destroy()

class OfferDetailDialog(tk.Toplevel):
    def __init__(self,parent,oid):
        super().__init__(parent);enable_dialog_maximize(self,1100,680);self.title("Cenová nabídka");self.transient(parent);self.grab_set()
        f=scrollable_dialog_frame(self,18)
        with db() as con:
            r=con.execute("""SELECT o.*,s.official_name supplier,c.official_name customer,a.name action_name
                FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?""",(oid,)).fetchone()
            items=con.execute("""SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id""",(oid,)).fetchall()
        if not r:return
        hdr=ttk.Frame(f,style="Card.TFrame",padding=12);hdr.pack(fill="x",pady=(0,10))
        ttk.Label(hdr,text=f"{r['supplier'] or 'Neurčený dodavatel'}  •  {fmt_date(r['offer_date'])}",style="Section.TLabel").pack(anchor="w")
        ttk.Label(hdr,text=f"Akce: {r['action_name'] or '—'}   |   Číslo: {r['offer_number'] or '—'}   |   Celkem: {r['total_value']:,.2f} {r['currency']}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(3,0))
        tree=ttk.Treeview(f,columns=("Poz.","Kód","Původní název","item_key","Množství","MJ","Pův. cena","Sleva","Cena/ks","Cena celkem"),show="headings",height=16)
        for c,w in (("Poz.",55),("Kód",110),("Původní název",330),("item_key",240),("Množství",80),("MJ",55),("Pův. cena",100),("Sleva",75),("Cena/ks",100),("Cena celkem",115)):
            tree.heading(c,text=c);tree.column(c,width=w,anchor="w")
        tree.pack(fill="both",expand=True)
        for it in items:
            tree.insert("","end",values=(it["position"],it["product_code"] or "",it["original_name"],it["item_key"],
                it["quantity"],it["unit"],f"{float(it['original_unit_price'] or 0):.2f}",
                f"{float(it['discount_pct'] or 0):.2f} %",f"{float(it['unit_price'] or 0):.2f}",f"{float(it['total_price'] or 0):.2f}"))
        b=ttk.Frame(f);b.pack(fill="x",pady=(10,0))
        if r["source_pdf"] and Path(r["source_pdf"]).exists():
            ttk.Button(b,text="Otevřít původní PDF",style="Toolbar.TButton",command=lambda:os.startfile(r["source_pdf"]) if sys.platform.startswith("win") else None).pack(side="left")
        ttk.Button(b,text="Zavřít",style="Accent.TButton",command=self.destroy).pack(side="right")


def _version_tuple(v):
    nums=re.findall(r"\d+",str(v or ""))
    return tuple(int(x) for x in nums[:4]) or (0,)

def _read_update_manifest(source):
    source=(source or "").strip()
    if not source:raise ValueError("Není nastaven zdroj aktualizací.")
    if re.match(r"^https?://",source,re.I):
        url=source if source.lower().endswith(".json") else source.rstrip("/")+"/latest.json"
        with urllib.request.urlopen(url,timeout=15) as r:
            data=json.loads(r.read().decode("utf-8-sig"))
        data["_base"]=url.rsplit("/",1)[0]+"/"
        return data
    p=Path(source)
    manifest=p if p.suffix.lower()==".json" else p/"latest.json"
    if not manifest.exists():raise FileNotFoundError(f"Nenalezen manifest aktualizace: {manifest}")
    data=json.loads(manifest.read_text(encoding="utf-8-sig"))
    data["_base"]=str(manifest.parent)
    return data

def _download_update_package(manifest):
    target=DATA_ROOT/"updates"
    target.mkdir(parents=True,exist_ok=True)
    ver=str(manifest.get("version") or "").strip()
    src=str(manifest.get("url") or manifest.get("file") or "").strip()
    if not ver or not src:raise ValueError("Manifest musí obsahovat version a url/file.")
    dest=target/f"ZakazkyApp_update_{ver}.zip"
    if re.match(r"^https?://",src,re.I):
        urllib.request.urlretrieve(src,dest)
    elif re.match(r"^https?://",str(manifest.get("_base","")),re.I):
        urllib.request.urlretrieve(str(manifest["_base"])+src,dest)
    else:
        base=Path(str(manifest.get("_base") or "."))
        source=Path(src)
        if not source.is_absolute():source=base/source
        if not source.exists():raise FileNotFoundError(source)
        shutil.copy2(source,dest)
    expected=str(manifest.get("sha256") or "").strip().lower()
    if expected:
        got=hashlib.sha256(dest.read_bytes()).hexdigest().lower()
        if got!=expected:
            dest.unlink(missing_ok=True)
            raise ValueError("Kontrolní součet stažené aktualizace nesouhlasí.")
    return dest

class App(tk.Tk):
    def __init__(self):
        super().__init__();configure_windows_app_identity(self);self.title(f"{APP_NAME} {APP_VERSION}");self.geometry("1600x940");self.minsize(1220,720)
        # Use native vector font rendering at integer point sizes.
        for _name,_size,_weight in (("TkDefaultFont",11,"normal"),("TkTextFont",11,"normal"),
                                    ("TkMenuFont",11,"normal"),("TkHeadingFont",11,"bold"),
                                    ("TkCaptionFont",11,"bold"),("TkSmallCaptionFont",10,"normal")):
            try:
                _f=tkfont.nametofont(_name);_f.configure(family="Calibri",size=_size,weight=_weight)
            except Exception:pass
        self.palette={}
        self.configure_styles()
        # TEST relace nikdy nepokračuje přes restart. Pokud bylo TEST poslední
        # aktivní jméno, začneme po startu bezpečně v ostré databázi.
        if get_setting("active_user","").strip().upper()==TEST_USER:
            with db() as con:
                r=con.execute("""SELECT name FROM users WHERE active=1 AND upper(trim(name))<>?
                                 ORDER BY id LIMIT 1""",(TEST_USER,)).fetchone()
            set_setting("active_user",r["name"] if r else "Jaroslav Kučera")
        self.build()
        self.protocol("WM_DELETE_WINDOW",self.close_app)
        self.bind_all("<Button-1>",close_autocomplete_popups_on_click,add="+")
        self.apply_theme(get_user_setting(get_setting("active_user","Jaroslav Kučera"),"theme","Tmavý"))
        self.refresh_all()
        self.maybe_show_morning_overview()
        _src=get_setting("update_source","").strip()
        if not _src or "ZakazkyApp_Aktualizace" in _src:
            set_setting("update_source","https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main")
            _src="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"
        if _src:
            self.after(5000,lambda:self.check_for_updates(silent=True))
    def configure_styles(self):
        s=ttk.Style(self)
        try:s.theme_use("clam")
        except:pass

        # V5.2 – jemnější CRM proporce: vyšší řádky, menší vizuální šum,
        # jednotná tlačítka a silnější hierarchie.
        s.configure("Treeview",rowheight=34,font=("Calibri",11))
        s.configure("Treeview.Heading",font=("Calibri",10,"bold"),padding=(8,9))

        s.configure("Accent.TButton",background="#f2b90b",foreground="#111111",
                    padding=(15,9),borderwidth=0,font=("Calibri",11,"bold"))
        s.map("Accent.TButton",background=[("active","#ffd23b"),("pressed","#d8a400")],
              foreground=[("active","#111111")])

        s.configure("Ghost.TButton",padding=(11,8),borderwidth=0,font=("Calibri",10))
        s.configure("Toolbar.TButton",padding=(10,7),borderwidth=1,font=("Calibri",10))
        s.configure("TopAction.TButton",padding=(10,7),borderwidth=0,font=("Calibri",10,"bold"))

        # Dashboard actions are intentionally calmer than in older versions.
        for st in ("QuickBlue.TButton","QuickOrange.TButton","QuickGreen.TButton",
                   "QuickPurple.TButton","QuickGray.TButton"):
            s.configure(st,padding=(13,10),font=("Calibri",10,"bold"),borderwidth=0)

        s.configure("Bell.TButton",padding=(8,7))
        s.configure("BellAlert.TButton",background="#d94b45",foreground="white",
                    padding=(8,7),font=("Calibri",9,"bold"))
        s.map("BellAlert.TButton",background=[("active","#ef625c")],foreground=[("active","white")])

    def build(self):
        root=ttk.Frame(self,style="App.TFrame")
        root.pack(fill="both",expand=True)
        root.rowconfigure(2,weight=1);root.columnconfigure(0,weight=1)

        # Horní stavový pruh: název aplikace, TEST banner, uživatel a nastavení.
        top=ttk.Frame(root,style="Topbar.TFrame",padding=(18,9))
        top.grid(row=0,column=0,sticky="ew")
        top.columnconfigure(1,weight=1)
        brand=ttk.Frame(top,style="Topbar.TFrame")
        brand.grid(row=0,column=0,sticky="w")
        ttk.Label(brand,text="TURTO",style="BrandAccent.TLabel",
                  font=("Calibri",13,"bold")).pack(side="left")
        ttk.Label(brand,text="  |  Zakázky CRM",style="Topbar.TLabel",
                  font=("Calibri",13,"bold")).pack(side="left")
        ttk.Label(brand,text=f"   v{APP_VERSION}",style="TopbarMuted.TLabel",
                  font=("Calibri",9)).pack(side="left",pady=(3,0))

        self.test_banner=ttk.Label(top,text="⚗  TESTOVACÍ REŽIM – ZMĚNY SE NEUKLÁDAJÍ",
                                   style="TestMode.TLabel",font=("Calibri",13,"bold"))
        self.test_banner.grid(row=0,column=1,padx=18)
        self.test_banner.grid_remove()

        with db() as con:
            users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        self.active_user=tk.StringVar(value=get_setting("active_user","Jaroslav Kučera"))
        self.userbox=safe_combobox(top,textvariable=self.active_user,values=users,state="readonly",width=1)
        self.userbox.grid_remove()

        self.user_button=ttk.Button(top,text="",style="TopAction.TButton",command=self.open_user_menu)
        self.user_button.grid(row=0,column=2,padx=(8,0))
        self.refresh_user_button()
        self.notes_button=ttk.Button(top,text="📝 Poznámky",style="TopAction.TButton",width=15,command=self.open_user_notes)
        self.notes_button.grid(row=0,column=3,padx=(6,0))
        self.refresh_notes_button()
        self.bell_button=ttk.Button(top,text="🔔",style="TopAction.TButton",width=5,command=self.open_notifications)
        self.bell_button.grid(row=0,column=4,padx=(6,0))
        ttk.Button(top,text="⚙",style="TopAction.TButton",width=4,
                   command=lambda:self.show_page("settings")).grid(row=0,column=5,padx=(6,0))

        # Hlavní horizontální navigace.
        navrow=ttk.Frame(root,style="NavBar.TFrame",padding=(10,0))
        navrow.grid(row=1,column=0,sticky="ew")
        self.nav={}
        nav_defs=[
            ("dash","⌂  Přehled"),
            ("actions","◫  Příležitosti"),
            ("projects","▣  Akce"),
            ("requests","✉  Poptávky"),
            ("mivo","M  MIVO"),
            ("offers","▤  Nabídky"),
            ("tasks","✓  Úkoly"),
            ("companies","▦  Společnosti"),
            ("people","♙  Osoby"),
            ("help","?  Nápověda"),
        ]
        for k,label in nav_defs:
            b=ttk.Button(navrow,text=label,style="TopNav.TButton",
                         command=lambda x=k:self.show_page(x))
            b.pack(side="left",padx=2,pady=(0,2))
            self.nav[k]=b

        self.host=ttk.Frame(root,style="App.TFrame")
        self.host.grid(row=2,column=0,sticky="nsew")
        self.host.rowconfigure(0,weight=1);self.host.columnconfigure(0,weight=1)

        self.pages=ttk.Frame(self.host,style="App.TFrame")
        self.pages.grid(row=0,column=0,sticky="nsew",padx=18,pady=(14,8))
        self.pages.rowconfigure(0,weight=1);self.pages.columnconfigure(0,weight=1)
        self.tabs={}
        for k in ("dash","actions","requests","mivo","offers","tasks","projects","people","companies","help","settings"):
            p=ttk.Frame(self.pages,style="App.TFrame")
            p.grid(row=0,column=0,sticky="nsew")
            self.tabs[k]=p

        # Spodní stavový řádek.
        footer=ttk.Frame(root,style="Footer.TFrame",padding=(18,8))
        footer.grid(row=3,column=0,sticky="ew")
        footer.columnconfigure(1,weight=1)
        ttk.Label(footer,text="vytvořil Ing. Jaroslav Kučera",
                  style="FooterAccent.TLabel",font=("Calibri",10,"bold")).grid(row=0,column=0,sticky="w")
        self.footer_test=tk.StringVar(value="")
        ttk.Label(footer,textvariable=self.footer_test,style="Footer.TLabel").grid(row=0,column=1)
        self.footer_db=ttk.Label(footer,text=f"Databáze: zakazky.db (schéma {APP_VERSION.rsplit('.',1)[0]})",
                                 style="Footer.TLabel")
        self.footer_db.grid(row=0,column=2,sticky="e")

        self.date_label=ttk.Label(top,text="",style="TopbarMuted.TLabel")
        self.today_summary=ttk.Label(top,text="",style="TopbarMuted.TLabel")

        self.build_dash();self.build_actions();self.build_requests();self.build_mivo();self.build_offers()
        self.build_tasks();self.build_projects();self.build_people();self.build_companies()
        self.build_help();self.build_settings();self.show_page("dash")

    def show_page(self,k):
        previous=getattr(self,"_current_page",None)
        self.tabs[k].tkraise()
        for x,b in self.nav.items():
            b.configure(style="TopNavActive.TButton" if x==k else "TopNav.TButton")
        self._current_page=k
        # Vlastní ruční řazení je pouze dočasné. Při návratu na záložku se
        # tabulka znovu načte ve svém výchozím pořadí.
        if previous is not None and previous!=k:
            refresh_map={
                "actions":"refresh_actions","requests":"refresh_requests","mivo":"refresh_mivo_requests",
                "offers":"refresh_offers","tasks":"refresh_tasks","projects":"refresh_projects","people":"refresh_people",
                "companies":"refresh_companies","dash":"refresh_dash"
            }
            fn=refresh_map.get(k)
            if fn and hasattr(self,fn):
                try:
                    tree_map={"actions":"action_tree","requests":"request_tree","mivo":"mivo_tree","offers":"offer_tree",
                              "tasks":"task_tree","projects":"project_tree","people":"people_tree","companies":"company_tree"}
                    tr=getattr(self,tree_map.get(k,""),None)
                    if tr is not None:
                        tr._sort_state={};tr._active_sort=None
                    getattr(self,fn)()
                except Exception:pass
    def tree(self,parent,cols,widths):
        wrap=ttk.Frame(parent,style="Panel.TFrame");wrap.pack(fill="both",expand=True)
        t=ttk.Treeview(wrap,columns=cols,show="headings")
        t._sort_state={}
        for c,w in zip(cols,widths):
            # The heading follows the alignment of its data cells immediately.
            t.column(c,width=w,anchor="w")
            t.heading(c,text=c,anchor=t.column(c,"anchor"),
                      command=lambda col=c,tree=t:self.sort_tree(tree,col))
        y=ttk.Scrollbar(wrap,orient="vertical",command=t.yview);y.pack(side="right",fill="y")
        def _xscroll(*args):
            t.xview(*args)
            if hasattr(t,"_sync_filter_bar"):t.after_idle(t._sync_filter_bar)
        x=ttk.Scrollbar(wrap,orient="horizontal",command=_xscroll);x.pack(side="bottom",fill="x")
        def _xset(first,last):
            x.set(first,last)
            if hasattr(t,"_sync_filter_bar"):t.after_idle(t._sync_filter_bar)
        t.configure(yscrollcommand=y.set,xscrollcommand=_xset);t.pack(fill="both",expand=True)
        # Významové barvy pracovních stavů. Barví se vždy celý řádek.
        t.tag_configure("status_active",background="#d8e8f5",foreground="#17324a")
        t.tag_configure("status_wait",background="#f5e6b5",foreground="#5b4308")
        t.tag_configure("status_soon",background="#f1d1aa",foreground="#65350a")
        t.tag_configure("status_late",background="#edc3c3",foreground="#6c2020")
        t.tag_configure("status_done",background="#d2e8d7",foreground="#24502d")
        t.tag_configure("status_won",background="#c9e4cf",foreground="#24502d")
        t.tag_configure("status_cancel",background="#d8dde1",foreground="#485159")
        t.tag_configure("status_offer",background="#ded3eb",foreground="#4b3b60")
        # Zachování starších názvů tagů kvůli kompatibilitě.
        t.tag_configure("late",background="#edc3c3",foreground="#6c2020")
        t.tag_configure("soon",background="#f1d1aa",foreground="#65350a")
        t.tag_configure("waiting",background="#f5e6b5",foreground="#5b4308")
        t.tag_configure("done",background="#d2e8d7",foreground="#24502d")
        t.tag_configure("won",background="#c9e4cf",foreground="#24502d")
        t.tag_configure("lost",background="#d8dde1",foreground="#485159")
        t.tag_configure("info",background="#d8e8f5",foreground="#17324a")
        t.tag_configure("req_fresh",background="#d8e8f5",foreground="#17324a")
        t.tag_configure("req_mid",background="#f5e6b5",foreground="#5b4308")
        t.tag_configure("req_old",background="#f1d1aa",foreground="#65350a")
        t.tag_configure("req_received",background="#d2e8d7",foreground="#24502d")
        return t

    def sort_tree(self,tree,col):
        desc=tree._sort_state.get(col,False)
        idx=list(tree["columns"]).index(col)
        date_cols={"Datum","Termín","Deadline","Poptáno","Obdrženo","Nabídka","Přijato",
                   "Vznik","ARES","Kdy","Zahájení","Dokončení","Vytvořeno","Upraveno",
                   "Archivováno","Datum vytvoření","Datum úpravy"}
        status_order={"Po termínu":0,"Dnes":1,"Čeká":2,"Hotovo":3,"Rozpracováno":2,
                      "Nabídka":3,"Vyhráno":4,"Prohráno":5,"Zrušeno":6,"Archivováno":7}
        def parse_date(s):
            s=str(s or "").strip()
            if not s:return None
            for fmt in ("%Y-%m-%d","%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M",
                        "%d.%m.%Y","%d.%m.%Y %H:%M:%S","%d.%m.%Y %H:%M",
                        "%d. %m. %Y","%d. %m. %Y %H:%M"):
                try:return datetime.strptime(s,fmt)
                except ValueError:pass
            return None
        def key(iid):
            s=str(tree.item(iid,"values")[idx] or "").strip()
            if s.startswith("⚠ "):s=s[2:].strip()
            if col in date_cols:
                d=parse_date(s)
                return (0,d) if d else (1,datetime.max)
            if col in ("Stav","Status"):return (0,status_order.get(s,99),s.lower())
            try:return (0,float(s.replace(" ","").replace(",",".")))
            except:return (1,czech_sort_key(s))
        items=list(tree.get_children(""))
        items.sort(key=key,reverse=desc)
        for pos,iid in enumerate(items):tree.move(iid,"",pos)
        tree._sort_state[col]=not desc
        tree._active_sort=(col,desc)
        for c in tree["columns"]:
            label=str(c)
            if c==col:label += " ▼" if desc else " ▲"
            tree.heading(c,text=label,command=lambda cc=c,tt=tree:self.sort_tree(tt,cc))


    def reapply_tree_sort(self,tree):
        state=getattr(tree,"_active_sort",None)
        if not state:return
        col,desc=state
        # sort_tree reads the "next direction" flag; seed it with the direction
        # that produced the currently visible order.
        tree._sort_state[col]=desc
        self.sort_tree(tree,col)

    def refresh_user_button(self):
        if not hasattr(self,"user_button"):return
        name=self.active_user.get().strip()
        parts=[p for p in name.split() if p]
        initials="".join(p[0].upper() for p in parts[:2]) if parts else "?"
        if TEST_MODE or name.upper()==TEST_USER:
            self.user_button.configure(text=f"TEST  {name}  ▾")
            if hasattr(self,"test_banner"):self.test_banner.grid()
            if hasattr(self,"footer_test"):self.footer_test.set("ⓘ  Aktuální data jsou pouze dočasná. Po ukončení aplikace budou zahozena.")
        else:
            self.user_button.configure(text=f"{initials}   {name}  ▾")
            if hasattr(self,"test_banner"):self.test_banner.grid_remove()
            if hasattr(self,"footer_test"):self.footer_test.set("")

    def refresh_notes_button(self):
        if not hasattr(self,'notes_button'):return
        user=self.active_user.get().strip() if hasattr(self,'active_user') else get_setting('active_user','')
        try:
            with db() as con:
                count=con.execute(
                    'SELECT COUNT(*) FROM user_notes WHERE user_name=? AND archived=0',
                    (user,),
                ).fetchone()[0]
        except Exception:
            count=0
        self.notes_button.configure(text=f'📝 Poznámky ({count})' if count else '📝 Poznámky')

    def open_user_notes(self):
        current=getattr(self,'_notes_dialog',None)
        try:
            if current is not None and current.winfo_exists():
                current.deiconify();current.lift();current.focus_force();return
        except Exception:pass
        self._notes_dialog=UserNotesDialog(self)

    def open_user_menu(self):
        menu=tk.Menu(self,tearoff=0,font=("Calibri",11))
        with db() as con:
            users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
        current=self.active_user.get()
        for name in users:
            menu.add_command(label=("✓ " if name==current else "   ")+name,command=lambda n=name:self.select_user(n))
        menu.add_separator()
        menu.add_command(label="Správa uživatelů…",command=self.manage_users)
        try:
            x=self.user_button.winfo_rootx();y=self.user_button.winfo_rooty()+self.user_button.winfo_height()
            menu.tk_popup(x,y)
        finally:
            menu.grab_release()

    def select_user(self,name):
        name=(name or "").strip()
        current=self.active_user.get().strip()
        if name.upper()==TEST_USER and not TEST_MODE:
            # Nastavení aktivního uživatele zapisujeme až do snapshotu, nikdy do live DB.
            enter_test_mode()
            ensure_schema()
            set_setting("active_user",TEST_USER)
        elif TEST_MODE and name.upper()!=TEST_USER:
            # Všechny testovací změny zahodíme a teprve potom přepneme ostrého uživatele.
            leave_test_mode()
            set_setting("active_user",name)
        self.active_user.set(name)
        self.on_user_changed()

    def on_user_changed(self,event=None):
        user=self.active_user.get().strip()
        # V TEST režimu jde nastavení pouze do testovací kopie.
        set_setting("active_user",user)
        theme=get_user_setting(user,"theme","Světlý")
        self.theme.set(theme) if hasattr(self,"theme") else None
        self.apply_theme(theme,False)
        self.refresh_user_button()
        self.refresh_notes_button()
        self.refresh_all()

    def close_app(self):
        # TEST DB je při každém ukončení zahozena. Při pádu ji odstraní další start.
        if TEST_MODE:leave_test_mode()
        self.destroy()

    def title_label(self,parent,text,button_text=None,button_command=None):
        descriptions={
            "Příležitosti":"Obchodní případy, termíny a navazující komunikace",
            "Poptávky":"Evidence poptávek, odpovědí a komunikace s dodavateli",
            "MIVO":"Samostatná evidence poptávek směrovaných na MIVO",
            "Nabídky":"PDF nabídky dodavatelů, položky a historie nákupních cen",
            "Úkoly / připomínky":"Termíny, odpovědnosti a návaznosti na příležitosti",
            "Akce":"Stavby a projekty propojené s příležitostmi a poptávkami",
            "Adresář osob":"Kontakty, funkce a vazby na společnosti",
            "Společnosti":"Firemní adresář, ARES a související kontakty",
        }
        row=ttk.Frame(parent,style="App.TFrame")
        row.pack(fill="x",pady=(0,12))
        left=ttk.Frame(row,style="App.TFrame")
        left.pack(side="left",fill="x",expand=True)
        ttk.Label(left,text=text,style="Title.TLabel").pack(anchor="w")
        desc=descriptions.get(text,"")
        if desc:
            ttk.Label(left,text=desc,style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,0))
        if button_text and button_command:
            ttk.Button(row,text=button_text,style="Accent.TButton",command=button_command).pack(side="right",anchor="n",pady=(2,0))
        return row

    def build_dash(self):
        p=self.tabs["dash"]
        dash_head=ttk.Frame(p,style="App.TFrame");dash_head.pack(fill="x",pady=(0,14))
        dh_left=ttk.Frame(dash_head,style="App.TFrame");dh_left.pack(side="left")
        ttk.Label(dh_left,text="Přehled",style="Title.TLabel").pack(anchor="w")
        ttk.Label(dh_left,text="Co právě vyžaduje pozornost",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,0))

        cards=ttk.Frame(p,style="App.TFrame");cards.pack(fill="x",pady=(0,12))
        self.kpis=[]
        card_defs=[("Otevřené","21","KPIBlue.TLabel"),("Po termínu","3","KPIRed.TLabel"),
                   ("Čekající poptávky","6","KPIOrange.TLabel"),("Hotové","310","KPIGreen.TLabel")]
        for i,(lab,_,num_style) in enumerate(card_defs):
            v=tk.StringVar(value="0");self.kpis.append(v)
            card=ttk.Frame(cards,style="Card.TFrame",padding=(16,12))
            card.grid(row=0,column=i,sticky="nsew",padx=(0 if i==0 else 5,0))
            ttk.Label(card,text=lab,style="CardTitle.TLabel").pack(anchor="w")
            # Číslo je přímo na kartě – bez samostatné barevné/maskované plochy.
            ttk.Label(card,textvariable=v,style=num_style,font=("Calibri",28,"bold")).pack(anchor="w",pady=(6,2))
            cards.columnconfigure(i,weight=1)


        body=ttk.Frame(p,style="App.TFrame");body.pack(fill="both",expand=True)
        body.columnconfigure(0,weight=4);body.columnconfigure(1,weight=2);body.rowconfigure(0,weight=1)

        left=ttk.Frame(body,style="Card.TFrame",padding=12);left.grid(row=0,column=0,sticky="nsew",padx=(0,10))
        ttk.Label(left,text="Aktivní příležitosti",style="Section.TLabel").pack(anchor="w",pady=(0,8))
        self.dash_tree=self.tree(left,("Stav","Deadline","Příležitost","Společnost","Obchodník","Poznámka"),
                                 [160,95,285,250,150,330])
        bind_row_double_click(self.dash_tree,lambda e:self.edit_action(self.dash_tree))

        right=ttk.Frame(body,style="App.TFrame");right.grid(row=0,column=1,sticky="nsew")
        quick=ttk.Frame(right,style="Card.TFrame",padding=12);quick.pack(fill="x",pady=(0,10))
        ttk.Label(quick,text="Rychlé akce",style="Section.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Button(quick,text="+  Nová příležitost",style="QuickBlue.TButton",command=self.new_action).pack(fill="x",pady=3)
        ttk.Button(quick,text="+  Nová poptávka",style="QuickOrange.TButton",command=self.new_request).pack(fill="x",pady=3)
        ttk.Button(quick,text="+  Nový úkol",style="QuickGreen.TButton",command=self.new_task).pack(fill="x",pady=3)
        ttk.Button(quick,text="+  Nová společnost",style="QuickPurple.TButton",command=self.new_company).pack(fill="x",pady=3)
        ttk.Button(quick,text="+  Nová osoba",style="QuickGray.TButton",command=self.new_person).pack(fill="x",pady=3)

        tasks=ttk.Frame(right,style="Card.TFrame",padding=12);tasks.pack(fill="both",expand=True,pady=(0,10))
        ttk.Label(tasks,text="Moje nejbližší úkoly",style="Section.TLabel").pack(anchor="w",pady=(0,6))
        self.dash_tasks_tree=ttk.Treeview(tasks,columns=("Termín","Úkol"),show="headings",height=5)
        self.dash_tasks_tree.heading("Termín",text="Termín");self.dash_tasks_tree.heading("Úkol",text="Úkol")
        self.dash_tasks_tree.column("Termín",width=85);self.dash_tasks_tree.column("Úkol",width=260)
        self.dash_tasks_tree.pack(fill="both",expand=True)

        req=ttk.Frame(right,style="Card.TFrame",padding=12);req.pack(fill="both",expand=True)
        ttk.Label(req,text="Čekající poptávky",style="Section.TLabel").pack(anchor="w",pady=(0,6))
        self.dash_requests_tree=ttk.Treeview(req,columns=("Stáří","Poptáváno","U společnosti","Řeší"),show="headings",height=6)
        for _c,_w in (("Stáří",65),("Poptáváno",145),("U společnosti",210),("Řeší",110)):
            self.dash_requests_tree.heading(_c,text=_c);self.dash_requests_tree.column(_c,width=_w,anchor="w")
        self.dash_requests_tree.pack(fill="both",expand=True)
        bind_row_double_click(self.dash_requests_tree,lambda e:self.edit_dashboard_request())


    def build_actions(self):
        p=self.tabs["actions"];self.title_label(p,"Příležitosti","+ Nová příležitost",self.new_action)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.delete_action).pack(side="right",padx=4)
        ttk.Button(bar,text="🔔 Připomínka",style="Toolbar.TButton",command=self.task_from_selected_action).pack(side="right",padx=4)
        ttk.Button(bar,text="✉ Poptat",style="Toolbar.TButton",command=self.request_from_selected_action).pack(side="right",padx=4)
        ttk.Button(bar,text="✎ Editovat",style="Toolbar.TButton",command=lambda:self.edit_action(self.action_tree)).pack(side="right",padx=4)

        with db() as con:
            companies=[r["official_name"] for r in con.execute("""SELECT MIN(id) id,official_name FROM companies
                WHERE active=1 AND trim(coalesce(official_name,''))<>''
                GROUP BY lower(trim(official_name)) ORDER BY official_name COLLATE CZECH""")]
            sales=[r["name"] for r in con.execute("SELECT name FROM salespeople WHERE active=1 ORDER BY name COLLATE CZECH")]
            action_names=[r["name"] for r in con.execute("""SELECT MIN(id),trim(name) name FROM actions
                WHERE trim(coalesce(name,''))<>'' GROUP BY lower(trim(name))
                ORDER BY trim(name) COLLATE CZECH""")]

        self.action_name_filter=tk.StringVar()
        self.action_company_filter=tk.StringVar()
        self.action_status=tk.StringVar()
        self.action_sp=tk.StringVar()
        self.action_received_mode=tk.StringVar(value="Do data")
        self.action_received_filter=tk.StringVar()
        self.action_date_mode=tk.StringVar(value="Do data")
        self.action_date_filter=tk.StringVar()

        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(120,90,90,280,200,160,230,220)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        def cell(col,label):
            f=ttk.Frame(filters,style="Panel.TFrame");f.grid(row=0,column=col,sticky="ew",padx=2)
            ttk.Label(f,text=label,style="FilterLabel.TLabel").pack(anchor="w")
            return f

        AutocompleteEntry(cell(0,"Stav"),textvariable=self.action_status,values=STATUSES).pack(fill="x")

        rf=cell(1,"Přijato")
        safe_combobox(rf,textvariable=self.action_received_mode,
                     values=["Dříve než","Později než","Do data","Od data","Přesně"],
                     state="readonly",width=8).pack(fill="x")
        DatePicker(rf,self.action_received_filter,width=9).pack(fill="x",pady=(2,0))

        df=cell(2,"Deadline")
        safe_combobox(df,textvariable=self.action_date_mode,
                     values=["Dříve než","Později než","Do data","Od data","Přesně"],
                     state="readonly",width=8).pack(fill="x")
        DatePicker(df,self.action_date_filter,width=9).pack(fill="x",pady=(2,0))

        AutocompleteEntry(cell(3,"Příležitost"),textvariable=self.action_name_filter,
                          values=action_names).pack(fill="x")
        AutocompleteEntry(cell(4,"Společnost"),textvariable=self.action_company_filter,
                          values=companies).pack(fill="x")
        AutocompleteEntry(cell(5,"Obchodník"),textvariable=self.action_sp,
                          values=sales).pack(fill="x")
        # Co se řeší a Poznámka záměrně bez filtrování.

        _afv=(self.action_name_filter,self.action_company_filter,self.action_status,self.action_sp,
              self.action_received_mode,self.action_received_filter,self.action_date_mode,self.action_date_filter)
        for v in _afv:
            v.trace_add("write",lambda *a:self.refresh_actions())
        setup_clear_filter_button(filters,self.clear_action_filters,_afv,
            {id(self.action_received_mode):"Do data",id(self.action_date_mode):"Do data"})

        self.action_tree=self.tree(p,("Stav","Přijato","Deadline","Příležitost","Společnost","Obchodník","Co se řeší","Poznámka"),
                                   list(widths))
        attach_filter_bar(self.action_tree,filters)
        bind_row_double_click(self.action_tree,lambda e:self.edit_action(self.action_tree))
        self.action_tree.bind("<Button-1>",self._action_status_cell_click,add="+")

    def clear_action_filters(self):
        for v in (self.action_name_filter,self.action_company_filter,self.action_status,self.action_sp,
                  self.action_received_filter,self.action_date_filter):
            v.set("")
        self.action_received_mode.set("Do data")
        self.action_date_mode.set("Do data")
        self.refresh_actions()


    def build_requests(self):
        p=self.tabs["requests"];self.title_label(p,"Poptávky","+ Nová poptávka",self.new_request)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        self.req_show_archived=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Zobrazit archivované",variable=self.req_show_archived,
                        command=self.refresh_requests).pack(side="left")
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.hard_delete_request).pack(side="right",padx=4)
        ttk.Button(bar,text="↩ Obnovit",style="Toolbar.TButton",command=self.restore_request).pack(side="right",padx=4)
        ttk.Button(bar,text="📦 Archivovat",style="Toolbar.TButton",command=self.archive_request).pack(side="right",padx=4)
        ttk.Button(bar,text="✎ Editovat",style="Toolbar.TButton",command=self.edit_request).pack(side="right",padx=4)
        ttk.Button(bar,text="Vytvořit e-mail",style="Toolbar.TButton",command=self.mail_selected).pack(side="right",padx=4)
        ttk.Button(bar,text="Obdrženo dnes",style="Toolbar.TButton",command=self.mark_received).pack(side="right",padx=4)
        ttk.Button(bar,text="Bez odezvy",style="Toolbar.TButton",command=self.mark_no_response).pack(side="right",padx=4)

        with db() as con:
            companies=[r["official_name"] for r in con.execute("""SELECT MIN(id) id,official_name FROM companies
                WHERE active=1 AND trim(coalesce(official_name,''))<>''
                GROUP BY lower(trim(official_name)) ORDER BY official_name COLLATE CZECH""")]
            users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
            actions=[r["name"] for r in con.execute("""SELECT MIN(id),trim(name) name FROM actions
                WHERE trim(coalesce(name,''))<>'' GROUP BY lower(trim(name))
                ORDER BY trim(name) COLLATE CZECH""")]

        self.req_status_filter=tk.StringVar()
        self.req_user_filter=tk.StringVar()
        self.req_at_filter=tk.StringVar()
        self.req_action_filter=tk.StringVar()
        self.req_date_mode=tk.StringVar(value="Do data")
        self.req_date_filter=tk.StringVar()

        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(100,150,90,90,190,280,220,300)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        def cell(col,label):
            f=ttk.Frame(filters,style="Panel.TFrame");f.grid(row=0,column=col,sticky="ew",padx=2)
            ttk.Label(f,text=label,style="FilterLabel.TLabel").pack(anchor="w")
            return f

        AutocompleteEntry(cell(0,"Stav"),textvariable=self.req_status_filter,
                          values=["Čekám","Obdrženo","Bez odezvy","Archivováno"]).pack(fill="x")
        AutocompleteEntry(cell(1,"Řeší"),textvariable=self.req_user_filter,
                          values=users).pack(fill="x")
        df=cell(2,"Poptáno")
        safe_combobox(df,textvariable=self.req_date_mode,
                     values=["Dříve než","Později než","Do data","Od data","Přesně"],
                     state="readonly",width=8).pack(fill="x")
        DatePicker(df,self.req_date_filter,width=9).pack(fill="x",pady=(2,0))
        # Odběratel se záměrně nefiltruje.
        AutocompleteEntry(cell(5,"Dodavatel"),textvariable=self.req_at_filter,
                          values=companies).pack(fill="x")
        AutocompleteEntry(cell(6,"Akce"),textvariable=self.req_action_filter,
                          values=actions).pack(fill="x")
        # Poptáváno ani Příjemci se záměrně nefiltrují.

        _rfv=(self.req_status_filter,self.req_user_filter,self.req_at_filter,
              self.req_action_filter,self.req_date_mode,self.req_date_filter)
        for v in _rfv:
            v.trace_add("write",lambda *a:self.refresh_requests())
        setup_clear_filter_button(filters,self.clear_request_filters,_rfv,
            {id(self.req_date_mode):"Do data"})

        self.request_tree=self.tree(p,("Stav","Řeší","Poptáno","Obdrženo","Odběratel","Dodavatel","Akce","Poptáváno","Příjemci"),
                                    list(widths))
        attach_filter_bar(self.request_tree,filters)
        bind_row_double_click(self.request_tree,lambda e:self.edit_request())
        self.request_tree.bind("<Configure>",lambda e:self.after_idle(self.refresh_requests),add="+")

    def clear_request_filters(self):
        for v in (self.req_status_filter,self.req_user_filter,self.req_at_filter,
                  self.req_action_filter,self.req_date_filter):
            v.set("")
        self.req_date_mode.set("Do data")
        self.refresh_requests()


    def _run_on_request_tree(self,tree,callback):
        """Použije existující funkce Poptávek nad zvolenou tabulkou (Poptávky/MIVO)."""
        old=self.request_tree
        self.request_tree=tree
        try:
            return callback()
        finally:
            self.request_tree=old
            try:self.refresh_requests()
            except Exception:pass
            try:self.refresh_mivo_requests()
            except Exception:pass

    def new_mivo_request(self):
        with db() as con:
            mids=mivo_company_ids(con)
            r=con.execute("SELECT official_name FROM companies WHERE id=?",(mids[0],)).fetchone() if mids else None
        supplier=r["official_name"] if r else "MIVO"
        d=RequestDialog(self,pre_company=supplier);self.wait_window(d);self.save_request(d)


    def build_mivo(self):
        p=self.tabs["mivo"];self.title_label(p,"MIVO","+ Nová poptávka",self.new_mivo_request)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        self.mivo_show_archived=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Zobrazit archivované",variable=self.mivo_show_archived,
                        command=self.refresh_mivo_requests).pack(side="left")
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.hard_delete_request)).pack(side="right",padx=4)
        ttk.Button(bar,text="↩ Obnovit",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.restore_request)).pack(side="right",padx=4)
        ttk.Button(bar,text="📦 Archivovat",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.archive_request)).pack(side="right",padx=4)
        ttk.Button(bar,text="✎ Editovat",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.edit_request)).pack(side="right",padx=4)
        ttk.Button(bar,text="Vytvořit e-mail",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.mail_selected)).pack(side="right",padx=4)
        ttk.Button(bar,text="Obdrženo dnes",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.mark_received)).pack(side="right",padx=4)
        ttk.Button(bar,text="Bez odezvy",style="Toolbar.TButton",
                   command=lambda:self._run_on_request_tree(self.mivo_tree,self.mark_no_response)).pack(side="right",padx=4)

        with db() as con:
            users=[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name COLLATE CZECH")]
            actions=[r["name"] for r in con.execute("""SELECT MIN(id),trim(name) name FROM actions
                WHERE trim(coalesce(name,''))<>'' GROUP BY lower(trim(name))
                ORDER BY trim(name) COLLATE CZECH""")]

        self.mivo_status_filter=tk.StringVar()
        self.mivo_user_filter=tk.StringVar()
        self.mivo_action_filter=tk.StringVar()
        self.mivo_date_mode=tk.StringVar(value="Do data")
        self.mivo_date_filter=tk.StringVar()

        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(100,150,90,90,170,170,250,210,270)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        def cell(col,label):
            f=ttk.Frame(filters,style="Panel.TFrame");f.grid(row=0,column=col,sticky="ew",padx=2)
            ttk.Label(f,text=label,style="FilterLabel.TLabel").pack(anchor="w")
            return f

        AutocompleteEntry(cell(0,"Stav"),textvariable=self.mivo_status_filter,
                          values=["Čekám","Obdrženo","Bez odezvy","Archivováno"]).pack(fill="x")
        AutocompleteEntry(cell(1,"Řeší"),textvariable=self.mivo_user_filter,
                          values=users).pack(fill="x")
        df=cell(2,"Poptáno")
        safe_combobox(df,textvariable=self.mivo_date_mode,
                     values=["Dříve než","Později než","Do data","Od data","Přesně"],
                     state="readonly",width=8).pack(fill="x")
        DatePicker(df,self.mivo_date_filter,width=9).pack(fill="x",pady=(2,0))
        AutocompleteEntry(cell(5,"Akce"),textvariable=self.mivo_action_filter,
                          values=actions).pack(fill="x")

        _mfv=(self.mivo_status_filter,self.mivo_user_filter,
              self.mivo_action_filter,self.mivo_date_mode,self.mivo_date_filter)
        for v in _mfv:
            v.trace_add("write",lambda *a:self.refresh_mivo_requests())
        setup_clear_filter_button(filters,self.clear_mivo_filters,_mfv,
            {id(self.mivo_date_mode):"Do data"})

        self.mivo_tree=self.tree(p,("Stav","Řeší","Poptáno","Obdrženo","Odběratel","Akce","Poptáváno","Příjemci"),
                                 list(widths))
        attach_filter_bar(self.mivo_tree,filters)
        bind_row_double_click(self.mivo_tree,
            lambda e:self._run_on_request_tree(self.mivo_tree,self.edit_request))
        self.mivo_tree.bind("<Configure>",lambda e:self.after_idle(self.refresh_mivo_requests),add="+")

    def clear_mivo_filters(self):
        for v in (self.mivo_status_filter,self.mivo_user_filter,
                  self.mivo_action_filter,self.mivo_date_filter):
            v.set("")
        self.mivo_date_mode.set("Do data")
        self.refresh_mivo_requests()


    def clear_task_filters(self):
        if hasattr(self,"task_user_filter"):self.task_user_filter.set("Všichni")
        if hasattr(self,"task_q"):self.task_q.set("")
        self.refresh_tasks()

    def clear_project_filters(self):
        if hasattr(self,"project_q"):self.project_q.set("")
        self.refresh_projects()

    def clear_people_filters(self):
        if hasattr(self,"people_q"):self.people_q.set("")
        self.refresh_people()

    def clear_company_filters(self):
        if hasattr(self,"comp_q"):self.comp_q.set("")
        self.refresh_companies()

    def build_offers(self):
        p=self.tabs["offers"];self.title_label(p,"Nabídky","+ Importovat PDF",self.import_offer_pdf)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        ttk.Button(bar,text="Otevřít detail",style="Toolbar.TButton",command=self.open_offer_detail).pack(side="right",padx=4)
        ttk.Button(bar,text="Otevřít PDF",style="Toolbar.TButton",command=self.open_offer_pdf).pack(side="right",padx=4)
        ttk.Button(bar,text="Smazat import",style="Toolbar.TButton",command=self.delete_offer).pack(side="right",padx=4)

        with db() as con:
            suppliers=[r["official_name"] for r in con.execute("SELECT official_name FROM companies WHERE active=1 ORDER BY official_name COLLATE CZECH")]
            actions=[r["name"] for r in con.execute("SELECT DISTINCT trim(name) name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY trim(name) COLLATE CZECH")]
        self.offer_supplier_filter=tk.StringVar();self.offer_action_filter=tk.StringVar();self.offer_q=tk.StringVar()
        filters=ttk.Frame(p,style="Panel.TFrame",padding=6);filters.pack(fill="x",pady=(0,5))
        ttk.Label(filters,text="Dodavatel",style="FilterLabel.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(filters,text="Akce",style="FilterLabel.TLabel").grid(row=0,column=1,sticky="w")
        ttk.Label(filters,text="Hledat",style="FilterLabel.TLabel").grid(row=0,column=2,sticky="w")
        AutocompleteEntry(filters,textvariable=self.offer_supplier_filter,values=suppliers).grid(row=1,column=0,sticky="ew",padx=(0,6))
        AutocompleteEntry(filters,textvariable=self.offer_action_filter,values=actions).grid(row=1,column=1,sticky="ew",padx=(0,6))
        ttk.Entry(filters,textvariable=self.offer_q).grid(row=1,column=2,sticky="ew")
        for i in range(3):filters.columnconfigure(i,weight=1)
        for v in (self.offer_supplier_filter,self.offer_action_filter,self.offer_q):
            v.trace_add("write",lambda *a:self.refresh_offers())

        self.offer_tree=self.tree(p,("Datum","Dodavatel","Odběratel","Akce","Číslo nabídky","Položek","Hodnota","Měna","Stav"),
                                  [100,220,220,260,150,80,120,65,110])
        bind_row_double_click(self.offer_tree,lambda e:self.open_offer_detail())

    def import_offer_pdf(self):
        d=OfferImportDialog(self);self.wait_window(d)
        if d.result:self.refresh_offers()

    def refresh_offers(self):
        if not hasattr(self,"offer_tree"):return
        sf=self.offer_supplier_filter.get().casefold().strip() if hasattr(self,"offer_supplier_filter") else ""
        af=self.offer_action_filter.get().casefold().strip() if hasattr(self,"offer_action_filter") else ""
        q=self.offer_q.get().casefold().strip() if hasattr(self,"offer_q") else ""
        for x in self.offer_tree.get_children():self.offer_tree.delete(x)
        with db() as con:
            rs=con.execute("""SELECT o.*,s.official_name supplier,c.official_name customer,a.name action_name,
                (SELECT COUNT(*) FROM supplier_offer_items i WHERE i.offer_id=o.id) item_count
                FROM supplier_offers o
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN companies c ON c.id=o.customer_company_id
                LEFT JOIN actions a ON a.id=o.action_id
                ORDER BY CASE WHEN trim(coalesce(o.offer_date,''))='' THEN 1 ELSE 0 END,
                         o.offer_date DESC,o.id DESC""").fetchall()
        for r in rs:
            hay=f"{r['supplier']} {r['customer']} {r['action_name']} {r['offer_number']} {r['note']}".casefold()
            if sf and sf not in (r["supplier"] or "").casefold():continue
            if af and af not in (r["action_name"] or "").casefold():continue
            if q and q not in hay:continue
            self.offer_tree.insert("","end",iid=f"o{r['id']}",
                values=(fmt_date(r["offer_date"]),r["supplier"] or "",r["customer"] or "",r["action_name"] or "",
                        r["offer_number"] or "",r["item_count"],f"{float(r['total_value'] or 0):,.2f}",r["currency"] or "CZK",r["status"] or ""))

    def _selected_offer_id(self):
        s=self.offer_tree.selection() if hasattr(self,"offer_tree") else ()
        return int(s[0][1:]) if s and s[0].startswith("o") else None

    def open_offer_detail(self):
        oid=self._selected_offer_id()
        if not oid:return messagebox.showinfo("Nabídky","Vyberte nabídku.",parent=self)
        d=OfferDetailDialog(self,oid);self.wait_window(d)

    def open_offer_pdf(self):
        oid=self._selected_offer_id()
        if not oid:return
        with db() as con:r=con.execute("SELECT source_pdf FROM supplier_offers WHERE id=?",(oid,)).fetchone()
        if r and r["source_pdf"] and Path(r["source_pdf"]).exists():
            if sys.platform.startswith("win"):os.startfile(r["source_pdf"])
        else:messagebox.showwarning("Nabídky","Původní PDF už není na uložené cestě.",parent=self)

    def delete_offer(self):
        oid=self._selected_offer_id()
        if not oid:return
        if not messagebox.askyesno("Nabídky","Opravdu odstranit tento import nabídky? Původní PDF na disku zůstane.",parent=self):return
        with db() as con:con.execute("DELETE FROM supplier_offers WHERE id=?",(oid,))
        self.refresh_offers()

    def build_tasks(self):
        p=self.tabs["tasks"];self.title_label(p,"Úkoly / připomínky","+ Nový úkol",self.new_task)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        self.task_show_done=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Zobrazit hotové",variable=self.task_show_done,command=self.refresh_tasks).pack(side="left")
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.delete_task).pack(side="right",padx=5)
        ttk.Button(bar,text="✓ Hotovo",command=self.complete_task).pack(side="right",padx=5)
        ttk.Button(bar,text="✎ Editovat",style="Toolbar.TButton",command=self.edit_task).pack(side="right")

        self.task_q=tk.StringVar();self.task_user_filter=tk.StringVar(value="Všichni")
        with db() as con:_task_users=["Všichni"]+[r["name"] for r in con.execute("SELECT name FROM users WHERE active=1 ORDER BY name")]
        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(110,150,95,260,400,150,150)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        def cell(col,label):
            f=ttk.Frame(filters,style="Panel.TFrame");f.grid(row=0,column=col,sticky="ew",padx=2)
            ttk.Label(f,text=label,style="FilterLabel.TLabel").pack(anchor="w")
            return f
        ttk.Label(cell(0,"Stav"),text="").pack()
        AutocompleteEntry(cell(1,"Řeší"),textvariable=self.task_user_filter,values=_task_users).pack(fill="x")
        ttk.Label(cell(2,""),text="").pack()
        ttk.Label(cell(3,""),text="").pack()
        ttk.Entry(cell(4,"Úkol"),textvariable=self.task_q).pack(fill="x")
        ttk.Label(cell(5,""),text="").pack()
        ttk.Label(cell(6,""),text="").pack()
        self.task_user_filter.trace_add("write",lambda *a:self.refresh_tasks())
        self.task_q.trace_add("write",lambda *a:self.refresh_tasks())
        setup_clear_filter_button(filters,self.clear_task_filters,
            (self.task_user_filter,self.task_q),{id(self.task_user_filter):"Všichni"})

        ttk.Label(p,text="Barvy: modrá = budoucí · žlutá = do 3 dnů · oranžová = dnes · červená = po termínu · zelená = hotovo",
                  style="Panel.TLabel").pack(anchor="w",pady=(0,6))
        self.task_tree=self.tree(p,("Stav","Řeší","Termín","Akce","Úkol","Vytvořil","Dokončil"),list(widths))
        attach_filter_bar(self.task_tree,filters)
        bind_row_double_click(self.task_tree,lambda e:self.edit_task())

    def build_projects(self):
        p=self.tabs["projects"];self.title_label(p,"Akce","+ Nová Akce",self.new_project)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.delete_project).pack(side="right",padx=5)
        ttk.Button(bar,text="⇄ Sloučit s jinou Akcí",command=self.merge_project).pack(side="right",padx=5)
        ttk.Button(bar,text="✎ Editovat",style="Toolbar.TButton",command=self.edit_project).pack(side="right",padx=5)
        self.project_q=tk.StringVar()
        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(300,300,220,220,100,100,90,150)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        ttk.Entry(filters,textvariable=self.project_q).grid(row=0,column=0,sticky="ew",padx=2)
        for i in range(1,len(widths)):ttk.Label(filters,text="").grid(row=0,column=i,sticky="ew")
        self.project_q.trace_add("write",lambda *a:self.refresh_projects())
        setup_clear_filter_button(filters,self.clear_project_filters,(self.project_q,))
        self.project_tree=self.tree(p,("Název Akce","Adresa","Investor","Generální dodavatel","Zahájení","Dokončení","Příležitostí","Poslední pohyb"),list(widths))
        attach_filter_bar(self.project_tree,filters)
        bind_row_double_click(self.project_tree,lambda e:self.edit_project())

    def build_people(self):
        p=self.tabs["people"];self.title_label(p,"Adresář osob","+ Nová osoba",self.new_person)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        self.people_show_inactive=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Zobrazit neaktivní",variable=self.people_show_inactive,
                        command=self.refresh_people).pack(side="left")
        ttk.Button(bar,text="✎ Upravit",command=self.edit_person).pack(side="right",padx=5)
        ttk.Button(bar,text="Aktivní / neaktivní",command=self.toggle_person_active).pack(side="right",padx=5)
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.delete_person).pack(side="right",padx=5)
        ttk.Button(bar,text="Import kontaktů…",command=self.import_people).pack(side="right",padx=5)
        ttk.Button(bar,text="Export kontaktů…",command=self.export_people).pack(side="right",padx=5)

        # Filtr je přímo nad sloupcem Jméno.
        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        self.people_q=tk.StringVar()
        ttk.Entry(filters,textvariable=self.people_q).grid(row=0,column=0,sticky="ew",padx=2)
        ttk.Label(filters,text="").grid(row=0,column=1,sticky="ew")
        ttk.Label(filters,text="").grid(row=0,column=2,sticky="ew")
        ttk.Label(filters,text="").grid(row=0,column=3,sticky="ew")
        ttk.Label(filters,text="").grid(row=0,column=4,sticky="ew")
        for i,w in enumerate((220,260,140,270,300)):filters.columnconfigure(i,weight=w)
        self.people_q.trace_add("write",lambda *a:self.refresh_people())
        setup_clear_filter_button(filters,self.clear_people_filters,(self.people_q,))

        self.people_tree=self.tree(p,("Jméno","E-mail","Telefon","Společnost","Funkce"),[220,260,140,270,300])
        attach_filter_bar(self.people_tree,filters)
        bind_row_double_click(self.people_tree,lambda e:self.edit_person())

    def build_companies(self):
        p=self.tabs["companies"];self.title_label(p,"Společnosti","+ Nová společnost",self.new_company)
        bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
        self.comp_show_archived=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Zobrazit archivované",variable=self.comp_show_archived,command=self.refresh_companies).pack(side="left")
        ttk.Button(bar,text="🗑 Smazat",style="Toolbar.TButton",command=self.delete_company).pack(side="right",padx=5)
        ttk.Button(bar,text="📦 Archivovat",style="Toolbar.TButton",command=self.archive_company).pack(side="right",padx=5)
        ttk.Button(bar,text="✎ Upravit",command=self.edit_company).pack(side="right",padx=5)
        ttk.Button(bar,text="Aktualizovat všechny z ARES",command=self.batch_ares).pack(side="right")
        self.comp_q=tk.StringVar()
        filters=ttk.Frame(p,style="Panel.TFrame",padding=0);filters.pack(fill="x",pady=(0,4))
        widths=(320,95,115,360,110,90,120,90)
        for i,w in enumerate(widths):filters.columnconfigure(i,weight=w)
        ttk.Entry(filters,textvariable=self.comp_q).grid(row=0,column=0,sticky="ew",padx=2)
        for i in range(1,len(widths)):ttk.Label(filters,text="").grid(row=0,column=i,sticky="ew")
        self.comp_q.trace_add("write",lambda *a:self.refresh_companies())
        setup_clear_filter_button(filters,self.clear_company_filters,(self.comp_q,))
        self.company_tree=self.tree(p,("Oficiální název","IČO","DIČ","Sídlo","Právní forma","Vznik","CZ-NACE","ARES"),list(widths))
        attach_filter_bar(self.company_tree,filters)
        bind_row_double_click(self.company_tree,lambda e:self.edit_company())

    def build_help(self):
        p=self.tabs["help"]
        hdr=ttk.Frame(p,style="App.TFrame");hdr.pack(fill="x",pady=(0,10))
        ttk.Label(hdr,text="Nápověda",style="Title.TLabel").pack(side="left")
        ttk.Label(hdr,text="Praktický průvodce procesy programu",style="Muted.TLabel").pack(side="left",padx=14)

        body=ttk.Frame(p,style="Panel.TFrame",padding=14);body.pack(fill="both",expand=True)
        body.columnconfigure(1,weight=1);body.rowconfigure(0,weight=1)
        topics=[
            ("Jak program funguje","help_overview"),
            ("Příležitosti","help_actions"),
            ("Poptávky","help_requests"),
            ("Akce","help_projects"),
            ("Úkoly","help_tasks"),
            ("Adresář a ARES","help_directory"),
            ("Import, export a zálohy","help_data"),
            ("Uživatelé a historie","help_users"),
            ("Barvy a stavy","help_colors"),
        ]
        left=ttk.Frame(body,style="Panel.TFrame");left.grid(row=0,column=0,sticky="ns",padx=(0,14))
        textwrap=ttk.Frame(body,style="Panel.TFrame");textwrap.grid(row=0,column=1,sticky="nsew")
        textwrap.rowconfigure(0,weight=1);textwrap.columnconfigure(0,weight=1)
        self.help_text=tk.Text(textwrap,wrap="word",font=("Calibri",11),relief="flat",borderwidth=0,
                               padx=18,pady=14)
        sb=ttk.Scrollbar(textwrap,orient="vertical",command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=sb.set)
        self.help_text.grid(row=0,column=0,sticky="nsew");sb.grid(row=0,column=1,sticky="ns")
        for label,key in topics:
            ttk.Button(left,text=label,width=27,command=lambda k=key:self.show_help_topic(k)).pack(fill="x",pady=3)
        self.show_help_topic("help_overview")

    def show_help_topic(self,key):
        docs={
        "help_overview":("Jak program funguje",
"""Základní tok programu

Společnost → Osoba → Akce / Příležitost → Poptávka → Úkol

Společnosti a osoby tvoří adresář. Příležitost je konkrétní obchodní nebo realizační možnost. V Příležitosti se používá jediný název „Akce“ a z ní lze vytvořit Poptávku. Úkoly slouží k hlídání konkrétních kroků a termínů.

Přehled ukazuje to, co právě vyžaduje pozornost: otevřené položky, termíny a čekající Poptávky. Dvojklik na datový řádek otevírá editaci; dvojklik na záhlaví tabulky nic neotevře.

Filtry jsou nad příslušnými sloupci. U našeptávacích filtrů lze psát i vybírat myší a kliknutí mimo rozbalený seznam jej zavře. „✕ Zrušit filtry“ se zobrazí jen při aktivním filtru. Dialogy mají posuvný obsah a víceřádkový text se zalamuje po celých slovech."""),
        "help_actions":("Příležitosti",
"""Příležitost založte pro konkrétní společnost a popište, co se řeší. Lze zadat více položek „Co se řeší“, přiřadit Akci, odpovědného uživatele a termíny.

Z Příležitosti lze vytvořit Poptávku. Při tom se vazba na Příležitost zachová, takže je později dohledatelné, proč Poptávka vznikla.

Pokud stejná Akce existuje i u jiné společnosti, detail Příležitosti ukáže společnost a datum Přijato. Dvojklik otevře související Příležitost v novém okně. Stav lze měnit přímo rozbalovacím seznamem ve sloupci Stav."""),
        "help_requests":("Poptávky",
"""Vyberte společnost, u které poptáváte. Program nabídne aktivní osoby z Adresáře, které jsou s touto společností propojené, a jejich e-mailové adresy lze zaškrtnout jako příjemce.

Poptávku lze uložit i bez příjemce a doplnit jej později. Odběratel i Akce mohou zůstat prázdné; povinný je Dodavatel. Dodavatele i Odběratele lze založit přímo z dialogu Poptávky. Tlačítko „+ Přidat osobu“ založí nový kontakt u právě vybrané společnosti.

„Vytvořit e-mail“ se pokusí otevřít koncept v klasickém spuštěném Outlooku. Pokud klasické rozhraní Outlooku není dostupné, použije se výchozí poštovní aplikace. Datum Obdrženo znamená, že odpověď na Poptávku dorazila; do té doby se Poptávka považuje za čekající.

Poptávky s Dodavatelem MIVO jsou z běžné sekce Poptávky automaticky oddělené do samostatné sekce MIVO a nezobrazují se v Přehledu mezi běžnými čekajícími Poptávkami. V MIVO se nezobrazuje zbytečný sloupec Dodavatel ani „Podobné předchozí poptávky“. Předmět e-mailu lze v MIVO napsat zcela volně.

Stav „Bez odezvy“ slouží pro starší Poptávky, které již není potřeba řešit, přestože odpověď nepřišla. Koncept e-mailu lze vytvořit i bez hlavního příjemce; program využije Outlook a jeho podpis. Za text „Předem velice děkuji,“ program nepřidává další prázdný řádek."""),
        "help_projects":("Akce",
"""Akce seskupují související Příležitosti. Pomáhají udržet pohromadě více obchodních nebo realizačních kroků patřících k jednomu projektu.

U Akce lze zadat adresu i GPS souřadnice. Pokud adresu neznáte, vložte souřadnice například z Google Maps; tlačítko „Otevřít v mapě“ otevře přesné místo. Pokud GPS chybí, lze mapu otevřít podle adresy.

„Sloučit s jinou Akcí“ převede aktuální vazby Příležitostí na cílovou Akci a původní Akci archivuje. Cílovou Akci lze vyhledávat psaním i vybrat myší. Existující Poptávky ani jejich historické záznamy se zpětně nepřepisují."""),
        "help_tasks":("Úkoly",
"""Úkol má termín, text a odpovědného uživatele. Lze jej navázat na Příležitost. Po dokončení zůstává dohledatelný v historii.

Položky po termínu se vyhodnocují podle celého data ve formátu rok-měsíc-den, nikoli jen podle dne v měsíci."""),
        "help_directory":("Adresář a ARES",
"""Společnosti jsou vedeny pod oficiálním názvem. U společnosti lze evidovat IČO, DIČ, sídlo a další údaje z ARES.

Osoba je propojena se společností přes interní vazbu společnosti. Právě tato vazba se používá například při nabídce kontaktů v Poptávce. Dvojklik na Společnost nebo Osobu otevře její editaci.

U polí Funkce, Poptávané zboží, Co se řeší a Obchodník lze tlačítkem „⚙ Spravovat“ otevřít příslušný číselník přímo z dialogu."""),
        "help_data":("Import, export a zálohy",
"""Pracovní databáze je uložena mimo instalační ZIP programu, aby aktualizace aplikace nepřepisovala vaše data. Nová verze proto pokračuje se stejnými pracovními daty.

Kompletní export slouží k přenosu celé databáze. Výběrový export umožňuje zvolit jen určité skupiny dat, například Společnosti. Při exportu si vždy vyberete cílovou složku a název souboru.

Před importem nebo větším zásahem doporučujeme vytvořit zálohu. „Zkontrolovat data“ pouze kontroluje integritu a vazby; samo nic neopravuje ani nemaže."""),
        "help_users":("Uživatelé a historie",
"""Uživatelé určují, kdo položku řeší nebo kdo ji vytvořil. Historické údaje se uchovávají i po odstranění uživatele, aby starší záznamy neztratily význam.

Aktuálně přihlášeného uživatele ani posledního zbývajícího uživatele nelze odstranit."""),
        "help_colors":("Barvy a stavy",
"""Barevnost slouží hlavně k rychlému rozlišení stavů. Odstíny jsou ve verzi 2.25 o něco výraznější, ale zůstávají tlumené a čitelné. U čekajících Poptávek ani prošlých deadlinů se kvůli termínu nepodbarvuje celý řádek; upozornění patří především k příslušnému datu.

Barva je pomocná informace; rozhodující je vždy textový stav a datum.""")
        }
        title,body=docs.get(key,docs["help_overview"])
        self.help_text.configure(state="normal")
        self.help_text.delete("1.0","end")
        self.help_text.insert("end",title+"\n\n","title")
        self.help_text.insert("end",body)
        self.help_text.insert("end",f"\n\n\nTURTO Zakázky – verze {APP_VERSION}\nVytvořil Ing. Jaroslav Kučera")
        self.help_text.tag_configure("title",font=("Calibri",16,"bold"))
        self.help_text.configure(state="disabled")

    def create_desktop_shortcut(self):
        if not sys.platform.startswith("win"):
            return messagebox.showinfo("Zástupce","Tato funkce je určena pro Windows.",parent=self)
        try:
            desktop=Path(os.environ.get("USERPROFILE",str(Path.home()))) / "Desktop"
            desktop.mkdir(parents=True,exist_ok=True)
            link=desktop/"TURTO Zakázky.lnk"
            if getattr(sys,"frozen",False):
                target=str(Path(sys.executable).resolve())
                args=""
            else:
                target=str((ROOT/"Spustit_Zakazky.bat").resolve())
                args=""
            env=os.environ.copy()
            env["ZAK_LINK"]=str(link)
            env["ZAK_TARGET"]=target
            env["ZAK_WORKDIR"]=str(ROOT)
            env["ZAK_ARGS"]=args
            ps=r"""
$w=New-Object -ComObject WScript.Shell
$s=$w.CreateShortcut($env:ZAK_LINK)
$s.TargetPath=$env:ZAK_TARGET
$s.WorkingDirectory=$env:ZAK_WORKDIR
$s.Arguments=$env:ZAK_ARGS
$s.Description='TURTO Zakázky'
$icon=Join-Path $env:ZAK_WORKDIR 'turto_logo.ico'
if (Test-Path $icon) { $s.IconLocation=$icon }
$s.Save()
"""
            r=subprocess.run(["powershell.exe","-NoProfile","-Command",ps],env=env,
                             capture_output=True,text=True,timeout=15,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            if r.returncode!=0:raise RuntimeError((r.stderr or r.stdout).strip())
            messagebox.showinfo("Zástupce",f"Zástupce byl vytvořen na ploše:\n{link}",parent=self)
        except Exception as e:
            messagebox.showerror("Zástupce",f"Zástupce se nepodařilo vytvořit:\n{e}",parent=self)

    def manage_code_lists(self,initial_kind="Funkce osob",parent=None):
        owner=parent or self
        d=tk.Toplevel(owner);d.title("Číselníky");d.transient(owner);d.grab_set()
        enable_dialog_maximize(d,760,560);d.geometry("820x600");center_dialog(d,owner)

        outer=ttk.Frame(d,padding=14);outer.pack(fill="both",expand=True)
        ttk.Label(outer,text="Správa číselníků",font=("Calibri",16,"bold")).pack(anchor="w")
        ttk.Label(outer,text="Položky lze doplňovat, přejmenovat, deaktivovat nebo smazat. "
                  "Používaná položka se při mazání pouze deaktivuje, aby se nezměnila historie.",
                  wraplength=760).pack(anchor="w",pady=(2,10))

        kinds={
            "Funkce osob":("person_roles","name"),
            "Poptávané zboží / materiály":("materials","name"),
            "Co se řeší":("work_topics","name"),
            "Obchodníci":("salespeople","name"),
        }
        top=ttk.Frame(outer);top.pack(fill="x",pady=(0,8))
        ttk.Label(top,text="Číselník:").pack(side="left")
        kind=tk.StringVar(value=initial_kind if initial_kind in kinds else "Funkce osob")
        cb=safe_combobox(top,textvariable=kind,values=list(kinds),state="readonly",width=32)
        cb.pack(side="left",padx=(7,0))

        wrap=ttk.Frame(outer);wrap.pack(fill="both",expand=True)
        tree=ttk.Treeview(wrap,columns=("Položka","Stav","Použití"),show="headings",selectmode="browse")
        for c,w in (("Položka",430),("Stav",120),("Použití",120)):
            tree.heading(c,text=c);tree.column(c,width=w,anchor="w")
        ys=ttk.Scrollbar(wrap,orient="vertical",command=tree.yview)
        ys.pack(side="right",fill="y");tree.configure(yscrollcommand=ys.set)
        tree.pack(fill="both",expand=True)

        def usage_count(table,row_id,name):
            with db() as con:
                if table=="person_roles":
                    return con.execute("""SELECT COUNT(*) FROM people
                                          WHERE lower(trim(role))=lower(trim(?))""",(name,)).fetchone()[0]
                if table=="materials":
                    return con.execute("""SELECT COUNT(*) FROM requests
                                          WHERE lower(trim(item))=lower(trim(?))""",(name,)).fetchone()[0]
                if table=="salespeople":
                    return con.execute("SELECT COUNT(*) FROM actions WHERE salesperson_id=?",(row_id,)).fetchone()[0]
                if table=="work_topics":
                    rows=con.execute("SELECT products FROM actions WHERE trim(coalesce(products,''))<>''").fetchall()
                    needle=name.strip().casefold()
                    total=0
                    for r in rows:
                        parts=[x.strip().casefold() for x in re.split(r"[;,]",r["products"] or "") if x.strip()]
                        if needle in parts:total+=1
                    return total
            return 0

        def refresh(*_):
            for x in tree.get_children():tree.delete(x)
            table,_=kinds[kind.get()]
            with db() as con:
                rows=con.execute(f"SELECT id,name,active FROM {table} ORDER BY active DESC,name COLLATE CZECH").fetchall()
            for r in rows:
                used=usage_count(table,r["id"],r["name"])
                tree.insert("","end",iid=f"x{r['id']}",
                            values=(r["name"],"Aktivní" if r["active"] else "Neaktivní",
                                    f"{used}×" if used else "—"),
                            tags=("status_cancel",) if not r["active"] else ())
        kind.trace_add("write",refresh)

        def selected():
            s=tree.selection()
            return int(s[0][1:]) if s else None

        def add():
            table,_=kinds[kind.get()]
            name=simpledialog.askstring("Nová položka",f"Nová položka – {kind.get()}:",parent=d)
            if not name or not name.strip():return
            try:
                with db() as con:con.execute(f"INSERT INTO {table}(name,active) VALUES(?,1)",(name.strip(),))
            except sqlite3.IntegrityError:
                return messagebox.showwarning("Číselník","Taková položka už existuje.",parent=d)
            refresh()

        def edit():
            rid=selected()
            if not rid:return messagebox.showinfo("Číselník","Vyberte položku.",parent=d)
            table,_=kinds[kind.get()]
            with db() as con:r=con.execute(f"SELECT name FROM {table} WHERE id=?",(rid,)).fetchone()
            if not r:return
            old=r["name"]
            name=simpledialog.askstring("Upravit položku","Název:",initialvalue=old,parent=d)
            if not name or not name.strip() or name.strip()==old:return
            try:
                with db() as con:
                    con.execute(f"UPDATE {table} SET name=? WHERE id=?",(name.strip(),rid))
            except sqlite3.IntegrityError:
                return messagebox.showwarning("Číselník","Taková položka už existuje.",parent=d)
            refresh()

        def toggle():
            rid=selected()
            if not rid:return messagebox.showinfo("Číselník","Vyberte položku.",parent=d)
            table,_=kinds[kind.get()]
            with db() as con:
                r=con.execute(f"SELECT active FROM {table} WHERE id=?",(rid,)).fetchone()
                if r:con.execute(f"UPDATE {table} SET active=? WHERE id=?",(0 if r["active"] else 1,rid))
            refresh()

        def delete():
            rid=selected()
            if not rid:return messagebox.showinfo("Číselník","Vyberte položku.",parent=d)
            table,_=kinds[kind.get()]
            with db() as con:r=con.execute(f"SELECT name,active FROM {table} WHERE id=?",(rid,)).fetchone()
            if not r:return
            used=usage_count(table,rid,r["name"])
            if used:
                if messagebox.askyesno("Používaná položka",
                    f"„{r['name']}“ je použita v {used} záznamech.\n\n"
                    "Kvůli zachování historie ji nelze fyzicky smazat. "
                    "Chcete ji označit jako neaktivní?",parent=d):
                    with db() as con:con.execute(f"UPDATE {table} SET active=0 WHERE id=?",(rid,))
                    refresh()
                return
            if not messagebox.askyesno("Smazat položku",f"Opravdu smazat „{r['name']}“?",parent=d):return
            with db() as con:con.execute(f"DELETE FROM {table} WHERE id=?",(rid,))
            refresh()

        buttons=ttk.Frame(outer);buttons.pack(fill="x",pady=(10,0))
        ttk.Button(buttons,text="+ Přidat",style="Accent.TButton",command=add).pack(side="left")
        ttk.Button(buttons,text="✎ Upravit",command=edit).pack(side="left",padx=5)
        ttk.Button(buttons,text="Aktivní / neaktivní",command=toggle).pack(side="left")
        ttk.Button(buttons,text="🗑 Smazat",command=delete).pack(side="left",padx=5)
        ttk.Button(buttons,text="Zavřít",command=d.destroy).pack(side="right")
        bind_row_double_click(tree,lambda e:edit())
        refresh()
        self.wait_window(d)
        if parent is not None:
            try:parent.grab_set()
            except Exception:pass

    def build_settings(self):
        p=self.tabs["settings"]
        hdr=ttk.Frame(p,style="App.TFrame");hdr.pack(fill="x",pady=(0,10))
        ttk.Label(hdr,text="Nastavení",style="Title.TLabel").pack(side="left")
        ttk.Button(hdr,text="← Zpět na Přehled",command=lambda:self.show_page("dash")).pack(side="right")

        f=ttk.Frame(p,style="Panel.TFrame",padding=18);f.pack(fill="x")

        ttk.Label(f,text="Vzhled",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=0,column=0,sticky="w")
        self.theme=tk.StringVar(value=get_user_setting(self.active_user.get(),"theme","Světlý"))
        cb=safe_combobox(f,textvariable=self.theme,values=["Světlý","Šedomodrý","Teplý","Tmavý"],state="readonly")
        cb.grid(row=1,column=0,sticky="w",pady=6)
        cb.bind("<<ComboboxSelected>>",lambda e:self.apply_theme(self.theme.get(),True))

        ttk.Label(f,text="Uživatelé",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=2,column=0,sticky="w",pady=(18,0))
        ttk.Button(f,text="Spravovat uživatele…",command=self.manage_users).grid(row=3,column=0,sticky="w",pady=6)
        ttk.Button(f,text="Vytvořit zástupce na ploše",command=self.create_desktop_shortcut).grid(row=3,column=1,sticky="w",padx=8,pady=6)

        ttk.Label(f,text="Číselníky",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=4,column=0,sticky="w",pady=(18,0))
        ttk.Button(f,text="Spravovat číselníky…",command=self.manage_code_lists).grid(row=5,column=0,sticky="w",pady=6)
        ttk.Label(f,text="Funkce osob · Poptávané zboží · Co se řeší · Obchodníci",
                  style="Panel.TLabel").grid(row=5,column=1,columnspan=2,sticky="w",padx=8)

        ttk.Label(f,text="Data",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=6,column=0,sticky="w",pady=(18,0))
        ttk.Button(f,text="Vytvořit zálohu",command=self.manual_backup).grid(row=7,column=0,sticky="w",pady=6)
        ttk.Button(f,text="Zkontrolovat data",command=self.database_audit).grid(row=7,column=1,sticky="w",padx=8,pady=6)
        ttk.Label(f,text=f"Databáze: {DB}",style="Panel.TLabel").grid(row=8,column=0,columnspan=3,sticky="w")

        ttk.Label(f,text="Import / export",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=9,column=0,sticky="w",pady=(18,0))
        ttk.Button(f,text="Export kompletní databáze…",command=self.export_complete_data).grid(row=10,column=0,sticky="w",pady=6)
        ttk.Button(f,text="Import kompletní databáze…",command=self.import_complete_data).grid(row=10,column=1,sticky="w",padx=8,pady=6)
        ttk.Button(f,text="Výběrový export…",command=self.export_selected_dialog).grid(row=10,column=2,sticky="w",padx=8,pady=6)

        ttk.Label(f,text="Aktualizace aplikace",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=11,column=0,sticky="w",pady=(20,0))
        self.update_source=tk.StringVar(value=get_setting("update_source","https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"))
        ttk.Entry(f,textvariable=self.update_source,width=70).grid(row=12,column=0,columnspan=2,sticky="ew",pady=6)
        ttk.Button(f,text="Vybrat složku…",command=self.choose_update_source).grid(row=12,column=2,sticky="w",padx=8)
        ttk.Button(f,text="Zkontrolovat aktualizace",style="Accent.TButton",command=self.check_for_updates).grid(row=13,column=0,sticky="w",pady=6)
        ttk.Label(f,text="Výchozí kanál: GitHub TURTO-ZakazkyApp. Zdroj lze případně změnit ručně.",
                  style="Panel.TLabel").grid(row=13,column=1,columnspan=2,sticky="w",padx=8)

    def choose_update_source(self):
        p=filedialog.askdirectory(parent=self,title="Vyberte složku aktualizací")
        if p:
            self.update_source.set(p);set_setting("update_source",p)

    def check_for_updates(self,silent=False):
        source=(self.update_source.get().strip() if hasattr(self,"update_source") else get_setting("update_source",""))
        if hasattr(self,"update_source"):set_setting("update_source",source)
        if not source:
            if not silent:messagebox.showinfo("Aktualizace","Nejprve nastavte zdroj aktualizací v Nastavení.",parent=self)
            return
        try:
            mf=_read_update_manifest(source)
            remote=str(mf.get("version") or "")
            if _version_tuple(remote)<=_version_tuple(APP_VERSION):
                if not silent:messagebox.showinfo("Aktualizace",f"Používáte aktuální verzi {APP_VERSION}.",parent=self)
                return
            if not messagebox.askyesno("Aktualizace",f"Je dostupná verze {remote}.\n\nStáhnout a nainstalovat?\n\nDatabáze zůstane beze změny.",parent=self):
                return
            package=_download_update_package(mf)
            updater=ROOT/"crm_updater.pyw"
            if not updater.exists():raise FileNotFoundError("Chybí crm_updater.pyw")
            set_setting("pending_update",remote)
            cmd=[sys.executable,str(updater),str(package),str(ROOT),str(os.getpid())]
            kwargs={}
            if sys.platform.startswith("win"):
                kwargs["creationflags"]=getattr(subprocess,"CREATE_NO_WINDOW",0)
            subprocess.Popen(cmd,**kwargs)
            self.after(250,self.close_app)
        except Exception as e:
            if not silent:messagebox.showerror("Aktualizace",str(e),parent=self)

    def selected_id(self,tree,prefix):
        s=tree.selection()
        return int(s[0][1:]) if s else None
    def action_rows(self):
        with db() as con:
            return con.execute("""SELECT a.*,c.official_name company,s.name salesperson,
                (SELECT COUNT(*) FROM requests r
                 LEFT JOIN companies rc ON rc.id=r.company_id
                 WHERE r.action_id=a.id
                   AND trim(coalesce(r.received_date,''))=''
                   AND coalesce(r.no_response,0)=0
                   AND coalesce(r.archived,0)=0
                   AND NOT (
                     lower(trim(coalesce(rc.short_name,'')))='mivo'
                     OR lower(trim(coalesce(rc.official_name,'')))='mivo'
                     OR lower(trim(coalesce(rc.official_name,''))) LIKE 'mivo %'
                   )) waiting
                FROM actions a
                LEFT JOIN companies c ON c.id=a.company_id
                LEFT JOIN salespeople s ON s.id=a.salesperson_id
                ORDER BY CASE WHEN trim(coalesce(a.created_date,''))='' THEN 1 ELSE 0 END,
                         a.created_date DESC,a.id DESC""").fetchall()
    def effective(self,r):
        return r["status"] or "Rozpracováno"
    def late(self,r):return bool(r["deadline"] and r["deadline"]<date.today().isoformat() and self.effective(r) not in ("Hotovo","Zrušeno"))
    def soon(self,r):
        try:return bool(r["deadline"] and 0<=(datetime.strptime(r["deadline"],"%Y-%m-%d").date()-date.today()).days<=2 and self.effective(r) not in ("Hotovo","Zrušeno"))
        except:return False
    def tag(self,r):
        status=(self.effective(r) or "").strip().lower()
        if status in ("hotovo","vyhráno"):
            return "status_won" if status=="vyhráno" else "status_done"
        if status in ("zrušeno","prohráno"):
            return "status_cancel"
        if "ček" in status:
            return "status_wait"
        if "nabíd" in status or "připraven" in status:
            return "status_offer"
        return "status_active"


    def request_from_selected_action(self):
        s=self.action_tree.selection()
        if not s:return messagebox.showinfo("Příležitost","Vyberte Příležitost.",parent=self)
        aid=int(s[0][1:])
        with db() as con:
            r=con.execute("""SELECT a.id,a.name,a.products,a.company_id,c.official_name company
                             FROM actions a LEFT JOIN companies c ON c.id=a.company_id WHERE a.id=?""",(aid,)).fetchone()
        if not r:return
        d=RequestDialog(self,pre_action=aid,pre_requested_for=(r["company"] or ""))
        if r["products"] and hasattr(d,"item") and not d.item.get().strip():d.item.set((r["products"] or "").split(";")[0].strip())
        self.wait_window(d)
        if d.result:self.save_request(d)


    def _action_status_cell_click(self,event):
        tree=self.action_tree
        try:
            if hasattr(self,"_action_status_editor") and self._action_status_editor:
                self._action_status_editor.destroy()
                self._action_status_editor=None
            if tree.identify_region(event.x,event.y)!="cell":return
            if tree.identify_column(event.x)!="#1":return
            row=tree.identify_row(event.y)
            if not row:return
            tree.selection_set(row);tree.focus(row)
            bbox=tree.bbox(row,"#1")
            if not bbox:return
            x,y,w,h=bbox
            current=str(tree.set(row,"Stav") or "")
            var=tk.StringVar(value=current)
            cb=safe_combobox(tree,textvariable=var,values=STATUSES,state="readonly")
            cb.place(x=x,y=y,width=w,height=h)
            self._action_status_editor=cb
            def commit(_=None):
                new_status=var.get().strip()
                try:cb.destroy()
                except Exception:pass
                self._action_status_editor=None
                if new_status and new_status!=current:
                    self._set_action_status(int(row[1:]),new_status)
            cb.bind("<<ComboboxSelected>>",commit)
            cb.bind("<Return>",commit)
            cb.bind("<Escape>",lambda e:cb.destroy())
            cb.bind("<FocusOut>",lambda e:self.after(120,lambda: cb.winfo_exists() and cb.destroy()))
            cb.focus_set()
            cb.event_generate("<Button-1>")
        except Exception:
            return

    def _set_action_status(self,aid,status):
        if status not in STATUSES:return
        user=get_setting("active_user","")
        with db() as con:
            r=con.execute("SELECT status,name,company_id FROM actions WHERE id=?",(aid,)).fetchone()
            if not r:return
            old=r["status"] or ""
            if old==status:return
            con.execute("UPDATE actions SET status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        (status,user,aid))
        log_history(aid,"status_change","Změnil stav Příležitosti",
                    f"{old or '—'} → {status}",r["company_id"],user_name=user)
        self.refresh_after_action_status()
        iid=f"a{aid}"
        if self.action_tree.exists(iid):
            self.action_tree.selection_set(iid);self.action_tree.see(iid)


    def task_from_selected_action(self):
        s=self.action_tree.selection()
        if s:self.new_task(int(s[0][1:]))

    def delete_action(self):
        s=self.action_tree.selection()
        if not s:return
        aid=int(s[0][1:])
        with db() as con:
            r=con.execute("SELECT name FROM actions WHERE id=?",(aid,)).fetchone()
            deps=con.execute("SELECT COUNT(*) FROM requests WHERE action_id=?",(aid,)).fetchone()[0]
            hist=con.execute("SELECT COUNT(*) FROM action_history WHERE action_id=?",(aid,)).fetchone()[0]
        if not r:return
        msg=f"Opravdu chcete odstranit „{r['name']}“?"
        if deps or hist:
            msg+=f"\\n\\nZáznam má {deps} poptávek a {hist} historických událostí. Nebude fyzicky smazán; bude označen jako Zrušeno a historie zůstane zachována."
        if not messagebox.askyesno("Odstranit Příležitost",msg,parent=self):return
        with db() as con:
            if deps or hist:
                con.execute("UPDATE actions SET status='Zrušeno',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(get_setting("active_user",""),aid))
                log_history(aid,"action_archive","Archivoval Příležitost","Stav změněn na Zrušeno.",user_name=get_setting("active_user",""))
            else:
                con.execute("DELETE FROM actions WHERE id=?",(aid,))
        self.refresh_all()

    def merge_project(self):
        pid=self.selected_id(self.project_tree,"p")
        if not pid:return messagebox.showinfo("Sloučit Akce","Vyberte Akci, kterou chcete sloučit.",parent=self)
        with db() as con:
            src=con.execute("SELECT id,name FROM projects WHERE id=?",(pid,)).fetchone()
            targets=con.execute("""SELECT id,name FROM projects
                                   WHERE active=1 AND id<>? ORDER BY name COLLATE CZECH""",(pid,)).fetchall()
            opp_count=con.execute("SELECT COUNT(*) FROM actions WHERE project_id=?",(pid,)).fetchone()[0]
            req_count=con.execute("""SELECT COUNT(*) FROM requests r
                                     JOIN actions a ON a.id=r.action_id
                                     WHERE a.project_id=?""",(pid,)).fetchone()[0]
        if not src:return
        if not targets:return messagebox.showinfo("Sloučit Akce","Není k dispozici jiná aktivní Akce.",parent=self)

        d=tk.Toplevel(self);d.title("Sloučit s jinou Akcí");d.transient(self);d.grab_set()
        f=ttk.Frame(d,padding=16);f.pack(fill="both",expand=True)
        ttk.Label(f,text=f"Zdrojová Akce: {src['name']}",font=("Calibri",12,"bold")).pack(anchor="w")
        ttk.Label(f,text=f"Převede se {opp_count} Příležitostí. {req_count} existujících Poptávek se nebude přepisovat; jejich záznamy a historie zůstanou beze změny.",
                  wraplength=570).pack(anchor="w",pady=(4,12))
        target_values=[(r["name"],r["id"]) for r in targets]
        target_var=tk.StringVar(value="")
        ttk.Label(f,text="Cílová Akce:").pack(anchor="w")
        target_box=AutocompleteEntry(f,textvariable=target_var,values=target_values)
        target_box.pack(fill="x",pady=(3,12))
        def do_merge():
            name=target_var.get().strip()
            target_id=getattr(target_box,"selected_payload",None)
            target=next((r for r in targets if r["id"]==target_id),None) if target_id else None
            if not target and name:
                exact=[r for r in targets if (r["name"] or "").strip().casefold()==name.casefold()]
                target=exact[0] if len(exact)==1 else None
            if not target:
                return messagebox.showwarning("Sloučit Akce","Vyberte existující cílovou Akci ze seznamu.",parent=d)
            if not messagebox.askyesno("Potvrdit sloučení",
                f"Sloučit „{src['name']}“ do „{target['name']}“?\n\n"
                f"Původní Akce bude archivována. Historické záznamy a existující Poptávky se nebudou zpětně měnit.",
                parent=d):return
            user=get_setting("active_user","")
            # Only current relationship of Opportunities is moved. No request row and no history row is rewritten.
            with db() as con:
                con.execute("UPDATE actions SET project_id=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE project_id=?",
                            (target["id"],user,pid))
                con.execute("UPDATE projects SET active=0 WHERE id=?",(pid,))
            # Record new event only; do not alter old history.
            with db() as con:
                moved=con.execute("SELECT id FROM actions WHERE project_id=?",(target["id"],)).fetchall()
            for rr in moved:
                # Only add merge note to opportunities that can be identified; old text remains untouched.
                pass
            d.destroy();self.refresh_all()
            messagebox.showinfo("Sloučení dokončeno",
                f"Akce „{src['name']}“ byla sloučena do „{target['name']}“.\n"
                f"Poptávky ani jejich historické záznamy nebyly přepsány.",parent=self)
        b=ttk.Frame(f);b.pack(fill="x")
        ttk.Button(b,text="Zrušit",command=d.destroy).pack(side="right")
        ttk.Button(b,text="Sloučit",style="Accent.TButton",command=do_merge).pack(side="right",padx=6)

    def delete_project(self):
        s=self.project_tree.selection()
        if not s:return
        pid=int(s[0][1:])
        with db() as con:
            r=con.execute("SELECT name FROM projects WHERE id=?",(pid,)).fetchone()
            deps=con.execute("SELECT COUNT(*) FROM actions WHERE project_id=?",(pid,)).fetchone()[0]
        if not r:return
        if deps:
            return messagebox.showwarning("Akce",f"Akce „{r['name']}“ obsahuje {deps} Příležitostí.\\n\\nNejdřív je přesuňte k jiné Akci. Kvůli ochraně dat ji nelze smazat.",parent=self)
        if messagebox.askyesno("Smazat Akci",f"Opravdu chcete smazat Akci „{r['name']}“?",parent=self):
            with db() as con:con.execute("DELETE FROM projects WHERE id=?",(pid,))
            self.refresh_all()

    def delete_task(self):
        s=self.task_tree.selection()
        if not s:return
        tid=int(s[0][1:])
        with db() as con:r=con.execute("SELECT * FROM tasks WHERE id=?",(tid,)).fetchone()
        if not r:return
        if not messagebox.askyesno("Smazat úkol",f"Opravdu chcete odstranit úkol „{r['text']}“?\\n\\nUdálost o odstranění zůstane v historii Akce.",parent=self):return
        log_history(r["action_id"],"task_delete","Odstranil připomínku",f"{fmt_date(r['due_date'])} · {r['text']}",user_name=get_setting("active_user",""))
        with db() as con:con.execute("DELETE FROM tasks WHERE id=?",(tid,))
        self.refresh_after_task_change()

    def new_project(self):
        d=ProjectDialog(self);self.wait_window(d)
        if d.result:self.refresh_all()

    def edit_project(self):
        s=self.project_tree.selection()
        if not s:return
        d=ProjectDialog(self,int(s[0][1:]));self.wait_window(d)
        if d.result:self.refresh_all()

    def refresh_projects(self):
        if not hasattr(self,"project_tree"):return
        q=self.project_q.get().lower().strip() if hasattr(self,"project_q") else ""
        for x in self.project_tree.get_children():self.project_tree.delete(x)
        with db() as con:
            rows=con.execute("""SELECT p.*,COUNT(a.id) opp_count,
                                SUM(CASE WHEN a.status NOT IN ('Hotovo','Zrušeno') THEN 1 ELSE 0 END) active_count
                                FROM projects p
                                LEFT JOIN actions a ON a.project_id=p.id
                                WHERE p.active=1 GROUP BY p.id
                                ORDER BY CASE WHEN trim(coalesce(p.start_date,''))='' THEN 1 ELSE 0 END,
                                         p.start_date DESC,p.id DESC""").fetchall()
        for r in rows:
            hay=f"{r['name']} {r['address']} {r['investor']} {r['general_contractor']}".lower()
            if q and q not in hay:continue
            tag="status_active" if (r["active_count"] or 0)>0 else "status_done"
            self.project_tree.insert("","end",iid=f"p{r['id']}",
                values=(r["name"],r["address"],r["investor"],r["general_contractor"],
                        fmt_date(r["start_date"]),fmt_date(r["end_date"]),r["opp_count"]),
                tags=(tag,))


    def new_task(self,pre_action_id=None):
        d=TaskDialog(self,pre_action_id=pre_action_id);self.wait_window(d)
        if d.result:self.refresh_after_task_change()

    def edit_task(self):
        s=self.task_tree.selection()
        if not s:return
        tid=int(s[0][1:])
        d=TaskDialog(self,task_id=tid);self.wait_window(d)
        if d.result:self.refresh_after_task_change()

    def complete_task_by_id(self,tid):
        user=get_setting("active_user","")
        event=None;action_id=None;text=""
        with db() as con:
            r=con.execute("SELECT * FROM tasks WHERE id=?",(tid,)).fetchone()
            if not r:return
            action_id=r["action_id"];text=r["text"]
            if r["done"]:
                con.execute("UPDATE tasks SET done=0,done_at='',done_by='' WHERE id=?",(tid,))
                event=("task_reopen","Znovu otevřel připomínku")
            else:
                con.execute("UPDATE tasks SET done=1,done_at=CURRENT_TIMESTAMP,done_by=? WHERE id=?",(user,tid))
                event=("task_done","Dokončil připomínku")
        log_history(action_id,event[0],event[1],text,user_name=user)
        self.refresh_all()

    def complete_task(self):
        s=self.task_tree.selection()
        if s:self.complete_task_by_id(int(s[0][1:]))

    def refresh_mivo_requests(self):
        if not hasattr(self,"mivo_tree"):return
        status=self.mivo_status_filter.get().casefold().strip() if hasattr(self,"mivo_status_filter") else ""
        user=self.mivo_user_filter.get().casefold().strip() if hasattr(self,"mivo_user_filter") else ""
        actionf=self.mivo_action_filter.get().casefold().strip() if hasattr(self,"mivo_action_filter") else ""
        dmode=self.mivo_date_mode.get() if hasattr(self,"mivo_date_mode") else "Do data"
        dfilter=self.mivo_date_filter.get().strip() if hasattr(self,"mivo_date_filter") else ""
        show_archived=bool(self.mivo_show_archived.get()) if hasattr(self,"mivo_show_archived") else False

        for x in self.mivo_tree.get_children():self.mivo_tree.delete(x)
        with db() as con:
            mivo_ids=set(mivo_company_ids(con))
            rows=con.execute("""SELECT r.*,c.official_name company,c.short_name company_short,
                    cf.official_name requested_for,a.name action_name
                FROM requests r
                LEFT JOIN companies c ON c.id=r.company_id
                LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                LEFT JOIN actions a ON a.id=r.action_id
                ORDER BY CASE WHEN trim(coalesce(r.asked_date,''))='' THEN 1 ELSE 0 END,
                         r.asked_date DESC,r.id DESC""").fetchall()

        overdue_cells=[]
        for r in rows:
            if r["company_id"] not in mivo_ids:continue
            if not show_archived and int(r["archived"] or 0)==1:continue
            state="Archivováno" if r["archived"] else ("Bez odezvy" if int(r["no_response"] or 0) else ("Obdrženo" if r["received_date"] else "Čekám"))
            if status and status not in state.casefold():continue
            if user and user not in (r["assigned_user"] or "").casefold():continue
            if actionf and actionf not in (r["action_name"] or "").casefold():continue
            if dfilter and not date_matches(r["asked_date"],dmode,dfilter):continue

            if r["archived"]:tag="status_cancel"
            elif r["received_date"] or int(r["no_response"] or 0):tag="req_received"
            else:tag="req_fresh"

            self.mivo_tree.insert("","end",iid=f"r{r['id']}",
                values=(state,r["assigned_user"] or "",
                        request_wait_date(r["asked_date"],r["received_date"]),
                        fmt_date(r["received_date"]),
                        r["requested_for"] or "",r["action_name"] or "",
                        r["item"],r["recipients_snapshot"]),tags=(tag,))
            overdue_cells.append((f"r{r['id']}",request_is_overdue(r["asked_date"],r["received_date"]) and not int(r["no_response"] or 0)))
        self.after_idle(lambda rows=overdue_cells:self._refresh_request_date_highlights(self.mivo_tree,rows))


    def refresh_tasks(self):
        if not hasattr(self,"task_tree"):return
        q=self.task_q.get().lower().strip() if hasattr(self,"task_q") else ""
        show_done=self.task_show_done.get() if hasattr(self,"task_show_done") else False
        uf=self.task_user_filter.get() if hasattr(self,"task_user_filter") else "Všichni"
        for x in self.task_tree.get_children():self.task_tree.delete(x)
        with db() as con:
            sql="""SELECT t.*,a.name action_name FROM tasks t JOIN actions a ON a.id=t.action_id
                   WHERE (?=1 OR t.done=0) ORDER BY t.done,t.due_date,t.id"""
            rows=con.execute(sql,(1 if show_done else 0,)).fetchall()
        today=date.today()
        for r in rows:
            hay=f"{r['action_name']} {r['text']} {r['note']} {r['assigned_user']}".lower()
            if q and q not in hay:continue
            if uf and uf!="Všichni" and uf.casefold() not in (r["assigned_user"] or "").casefold():continue
            if r["done"]:
                state="Hotovo";tag="status_done"
            else:
                try:d=datetime.strptime(r["due_date"],"%Y-%m-%d").date()
                except:d=today
                diff=(d-today).days
                if diff<0:state="Po termínu";tag="status_late"
                elif diff==0:state="Dnes";tag="status_soon"
                elif diff<=3:state="Brzy";tag="status_wait"
                else:state="Čeká";tag="status_active"
            self.task_tree.insert("","end",iid=f"t{r['id']}",
                values=(state,r["assigned_user"] or "",fmt_date(r["due_date"]),r["action_name"],r["text"],r["created_by"],r["done_by"]),
                tags=(tag,))


    def notification_count(self):
        today=date.today();horizon=today.toordinal()+3;count=0
        with db() as con:
            for r in con.execute("SELECT due_date FROM tasks WHERE done=0"):
                try:d=datetime.strptime(r["due_date"],"%Y-%m-%d").date()
                except:continue
                if d.toordinal()<=horizon:count+=1
            for r in con.execute("SELECT deadline FROM actions WHERE trim(coalesce(deadline,''))<>'' AND status NOT IN ('Hotovo','Zrušeno')"):
                try:d=datetime.strptime(r["deadline"],"%Y-%m-%d").date()
                except:continue
                if d.toordinal()<=horizon:count+=1
            count+=con.execute("""SELECT COUNT(*) FROM requests WHERE trim(coalesce(received_date,''))=''
                                 AND asked_date<>'' AND julianday(?) - julianday(asked_date) >= 3""",(today.isoformat(),)).fetchone()[0]
        return count

    def refresh_notifications(self):
        if not hasattr(self,"bell_button"):return
        n=self.notification_count()
        self.bell_button.configure(text=f"🔔 {n}" if n else "🔔",style="BellAlert.TButton" if n else "Bell.TButton")

    def open_notifications(self):
        d=NotificationCenter(self)
        self.wait_window(d)
        self.refresh_notifications()

    def maybe_show_morning_overview(self):
        user=self.active_user.get().strip()
        today=date.today().isoformat()
        if get_user_setting(user,"morning_overview_date","")!=today:
            set_user_setting(user,"morning_overview_date",today)
            if self.notification_count()>0:
                self.after(250,self.open_notifications)

    def edit_action_by_id(self,aid):
        d=ActionDialog(self,aid);self.wait_window(d)
        if d.result:self.refresh_all()

    def refresh_after_action_status(self):
        self.refresh_dash();self.refresh_actions();self.refresh_header();self.refresh_notifications()

    def refresh_after_request_change(self):
        # Poptávka ovlivňuje oba seznamy Poptávek, čekání u Příležitosti,
        # dashboard a upozornění; adresář ani Společnosti se kvůli ní nenačítají znovu.
        self.refresh_dash();self.refresh_actions();self.refresh_requests();self.refresh_mivo_requests()
        self.refresh_header();self.refresh_notifications()

    def refresh_after_task_change(self):
        self.refresh_dash();self.refresh_tasks();self.refresh_header();self.refresh_notifications()

    def refresh_all(self):
        self.refresh_dash();self.refresh_actions();self.refresh_requests();self.refresh_mivo_requests();self.refresh_offers();self.refresh_tasks();self.refresh_projects();self.refresh_people();self.refresh_companies();self.refresh_header();self.refresh_notifications()
    def refresh_header(self):
        days=["Pondělí","Úterý","Středa","Čtvrtek","Pátek","Sobota","Neděle"]
        months=["ledna","února","března","dubna","května","června","července","srpna","září","října","listopadu","prosince"]
        d=date.today()
        if hasattr(self,"date_label"):
            self.date_label.config(text=f"{days[d.weekday()]} {d.day}. {months[d.month-1]} {d.year}")
        try:
            rows=self.action_rows()
            late=sum(self.late(r) for r in rows)
            with db() as con:
                waiting=con.execute("""SELECT COUNT(*) FROM requests
                                       WHERE trim(coalesce(received_date,''))=''
                                         AND (archived IS NULL OR trim(CAST(archived AS TEXT)) IN ('','0','False','false'))""").fetchone()[0]
                tasks_today=con.execute("SELECT COUNT(*) FROM tasks WHERE done=0 AND due_date<=?",(date.today().isoformat(),)).fetchone()[0]
            self.today_summary.config(text=f"Dnes: {late} hořící termíny · {waiting} poptávek čeká na odpověď · {tasks_today} úkolů k řešení")
        except:
            pass

    def edit_dashboard_request(self):
        s=self.dash_requests_tree.selection()
        if not s:return
        rid=int(s[0][2:]) if s[0].startswith("dr") else None
        if not rid:return
        self.show_page("requests")
        self.refresh_requests()
        iid=f"r{rid}"
        if self.request_tree.exists(iid):
            self.request_tree.selection_set(iid);self.request_tree.see(iid)
            self.edit_request()

    def refresh_dash(self):
        rows=self.action_rows()
        if hasattr(self,"crm_focus"):
            late_n=sum(self.late(r) for r in rows)
            soon_n=sum(self.soon(r) for r in rows)
            try:
                with db() as con:
                    old_req=con.execute("""SELECT COUNT(*) FROM requests
                        WHERE trim(coalesce(received_date,''))='' AND coalesce(no_response,0)=0
                        AND coalesce(archived,0)=0 AND asked_date<>''
                        AND julianday(?) - julianday(asked_date) >= 7""",(date.today().isoformat(),)).fetchone()[0]
                    due_tasks=con.execute("SELECT COUNT(*) FROM tasks WHERE done=0 AND due_date<=?",(date.today().isoformat(),)).fetchone()[0]
            except Exception:
                old_req=due_tasks=0
            parts=[]
            if late_n:parts.append(f"{late_n} příležitostí po termínu")
            if soon_n:parts.append(f"{soon_n} deadline do 2 dnů")
            if old_req:parts.append(f"{old_req} poptávek bez odezvy 7+ dní")
            if due_tasks:parts.append(f"{due_tasks} úkolů k řešení")
            self.crm_focus.set("  •  ".join(parts) if parts else "Dnes není žádná kritická položka.")
        self.kpis[0].set(sum(self.effective(r) not in ("Hotovo","Zrušeno") for r in rows))
        self.kpis[1].set(sum(self.late(r) for r in rows))
        self.kpis[2].set(sum((r["waiting"] or 0)>0 for r in rows))
        self.kpis[3].set(sum(self.effective(r)=="Hotovo" for r in rows))
        for x in self.dash_tree.get_children():self.dash_tree.delete(x)
        active=[r for r in rows if self.effective(r) not in ("Hotovo","Zrušeno")]
        active.sort(key=lambda r:(0 if self.late(r) else 1,r["deadline"] or "9999",-r["id"]))
        for r in active[:80]:
            self.dash_tree.insert("","end",iid=f"a{r['id']}",
                values=("Po termínu" if self.late(r) else self.effective(r),fmt_date(r["deadline"]),
                        r["name"],r["company"] or "",r["salesperson"] or "",r["note"] or ""),tags=(self.tag(r),))

        if hasattr(self,"dash_tasks_tree"):
            for x in self.dash_tasks_tree.get_children():self.dash_tasks_tree.delete(x)
            user=get_setting("active_user","")
            with db() as con:
                tasks=con.execute("""SELECT t.id,t.due_date,t.text,a.name action_name FROM tasks t
                                     LEFT JOIN actions a ON a.id=t.action_id
                                     WHERE t.done=0 AND (trim(coalesce(t.assigned_user,''))='' OR t.assigned_user=?)
                                     ORDER BY t.due_date,t.id LIMIT 7""",(user,)).fetchall()
            for r in tasks:
                self.dash_tasks_tree.insert("","end",values=(fmt_date(r["due_date"]),f"{r['text']} · {r['action_name'] or ''}"))

        if hasattr(self,"dash_requests_tree"):
            for x in self.dash_requests_tree.get_children():self.dash_requests_tree.delete(x)
            today=date.today()
            with db() as con:
                reqs=con.execute("""SELECT r.id,r.asked_date,r.item,r.assigned_user,c.official_name company
                                    FROM requests r LEFT JOIN companies c ON c.id=r.company_id
                                    WHERE trim(coalesce(r.received_date,''))=''
                                      AND coalesce(r.no_response,0)=0
                                      AND NOT (
                                          lower(trim(coalesce(c.short_name,'')))='mivo'
                                          OR lower(trim(coalesce(c.official_name,'')))='mivo'
                                          OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo %'
                                          OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo,%'
                                          OR lower(trim(coalesce(c.official_name,''))) LIKE 'mivo.%'
                                      )
                                      AND (r.archived IS NULL OR trim(CAST(r.archived AS TEXT)) IN ('','0','False','false'))
                                    ORDER BY CASE WHEN trim(coalesce(r.asked_date,''))='' THEN 1 ELSE 0 END,
                                             r.asked_date,r.id LIMIT 10""").fetchall()
            for r in reqs:
                try:age=(today-datetime.strptime(r["asked_date"],"%Y-%m-%d").date()).days
                except:age=0
                self.dash_requests_tree.insert("","end",iid=f"dr{r['id']}",
                    values=(f"{max(age,0)} dní",r["item"] or "—",r["company"] or "—",r["assigned_user"] or "—"))


    def _refresh_action_deadline_highlights(self,rows):
        """Hořící Deadline je označen přímo v textu buňky; žádný overlay widget."""
        tree=self.action_tree
        for item in rows:
            iid=item[0];is_late=bool(item[1])
            is_soon=bool(item[2]) if len(item)>2 else False
            if not tree.exists(iid):continue
            raw=str(tree.set(iid,"Deadline") or "")
            clean=raw.replace("⚠ ","").replace("● ","").strip()
            marker="⚠ " if is_late else ("● " if is_soon else "")
            tree.set(iid,"Deadline",(marker+clean) if clean else clean)

    def refresh_actions(self):
        name_q=self.action_name_filter.get().casefold().strip() if hasattr(self,"action_name_filter") else ""
        comp=self.action_company_filter.get().casefold().strip() if hasattr(self,"action_company_filter") else ""
        st=self.action_status.get().casefold().strip() if hasattr(self,"action_status") else ""
        sp=self.action_sp.get().casefold().strip() if hasattr(self,"action_sp") else ""
        rmode=self.action_received_mode.get() if hasattr(self,"action_received_mode") else "Do data"
        rfilter=self.action_received_filter.get().strip() if hasattr(self,"action_received_filter") else ""
        dmode=self.action_date_mode.get() if hasattr(self,"action_date_mode") else "Do data"
        dfilter=self.action_date_filter.get().strip() if hasattr(self,"action_date_filter") else ""
        for x in self.action_tree.get_children():self.action_tree.delete(x)
        deadline_cells=[]
        for r in self.action_rows():
            if name_q and name_q not in (r["name"] or "").casefold():continue
            if comp and comp not in (r["company"] or "").casefold():continue
            if st and st not in self.effective(r).casefold():continue
            if sp and sp not in (r["salesperson"] or "").casefold():continue
            if rfilter and not date_matches(r["created_date"],rmode,rfilter):continue
            if dfilter and not date_matches(r["deadline"],dmode,dfilter):continue
            self.action_tree.insert("","end",iid=f"a{r['id']}",
                values=(self.effective(r),fmt_date(r["created_date"]),fmt_date(r["deadline"]),
                        r["name"],r["company"] or "",r["salesperson"] or "",r["products"],r["note"] or ""),
                tags=(self.tag(r),))
            deadline_cells.append((f"a{r['id']}",self.late(r),self.soon(r)))
        self.reapply_tree_sort(self.action_tree)
        self.after_idle(lambda rows=deadline_cells:self._refresh_action_deadline_highlights(rows))
        if hasattr(self,"_action_status_editor") and self._action_status_editor:
            try:self._action_status_editor.destroy()
            except Exception:pass
            self._action_status_editor=None


    def _refresh_request_date_highlights(self,tree,rows):
        """Stáří Poptávky je označeno přímo v hodnotě buňky, takže nikdy neujíždí při scrollu."""
        for iid,is_old in rows:
            if not tree.exists(iid):continue
            raw=str(tree.set(iid,"Poptáno") or "")
            clean=raw.replace("⚠ ","").strip()
            tree.set(iid,"Poptáno",("⚠ "+clean) if is_old and clean else clean)

    def refresh_requests(self):
        status=self.req_status_filter.get().casefold().strip() if hasattr(self,"req_status_filter") else ""
        user=self.req_user_filter.get().casefold().strip() if hasattr(self,"req_user_filter") else ""
        atf=self.req_at_filter.get().casefold().strip() if hasattr(self,"req_at_filter") else ""
        actionf=self.req_action_filter.get().casefold().strip() if hasattr(self,"req_action_filter") else ""
        dmode=self.req_date_mode.get() if hasattr(self,"req_date_mode") else "Do data"
        dfilter=self.req_date_filter.get().strip() if hasattr(self,"req_date_filter") else ""
        show_archived=bool(self.req_show_archived.get()) if hasattr(self,"req_show_archived") else False
        for x in self.request_tree.get_children():self.request_tree.delete(x)

        with db() as con:
            mivo_ids=set(mivo_company_ids(con))
            rows=con.execute("""SELECT r.*,c.official_name company,c.short_name company_short,
                    cf.official_name requested_for,a.name action_name
                FROM requests r
                LEFT JOIN companies c ON c.id=r.company_id
                LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                LEFT JOIN actions a ON a.id=r.action_id
                ORDER BY CASE WHEN trim(coalesce(r.asked_date,''))='' THEN 1 ELSE 0 END,
                         r.asked_date DESC,r.id DESC""").fetchall()

        overdue_cells=[]
        for r in rows:
            if r["company_id"] in mivo_ids:continue
            if not show_archived and int(r["archived"] or 0)==1:continue
            state="Archivováno" if r["archived"] else ("Bez odezvy" if int(r["no_response"] or 0) else ("Obdrženo" if r["received_date"] else "Čekám"))
            if status and status not in state.casefold():continue
            if user and user not in (r["assigned_user"] or "").casefold():continue
            if atf and atf not in (r["company"] or "").casefold():continue
            if actionf and actionf not in (r["action_name"] or "").casefold():continue
            if dfilter and not date_matches(r["asked_date"],dmode,dfilter):continue

            # Stáří čekání už nebarví celý řádek. Stav řádku je jednotný,
            # případné upozornění je pouze u data Poptáno.
            if r["archived"]:tag="status_cancel"
            elif r["received_date"] or int(r["no_response"] or 0):tag="req_received"
            else:tag="req_fresh"

            self.request_tree.insert("","end",iid=f"r{r['id']}",
                values=(state,r["assigned_user"] or "",
                        request_wait_date(r["asked_date"],r["received_date"]),
                        fmt_date(r["received_date"]),
                        r["requested_for"] or "",r["company"] or "",r["action_name"] or "",
                        r["item"],r["recipients_snapshot"]),
                tags=(tag,))
            overdue_cells.append((f"r{r['id']}",request_is_overdue(r["asked_date"],r["received_date"]) and not int(r["no_response"] or 0)))
        self.after_idle(lambda rows=overdue_cells:self._refresh_request_date_highlights(self.request_tree,rows))


    def refresh_people(self):
        q=self.people_q.get().lower().strip() if hasattr(self,"people_q") else ""
        show_inactive=bool(self.people_show_inactive.get()) if hasattr(self,"people_show_inactive") else False
        for x in self.people_tree.get_children():self.people_tree.delete(x)
        with db() as con:
            rows=con.execute("""SELECT p.*,c.official_name company FROM people p
                                LEFT JOIN companies c ON c.id=p.company_id
                                WHERE (?=1 OR p.active=1)
                                ORDER BY p.active DESC,p.name COLLATE CZECH,p.email""",
                             (1 if show_inactive else 0,)).fetchall()
        for r in rows:
            if q and q not in " ".join(str(r[k] or "") for k in ("name","email","phone","company","role")).lower():continue
            tag="status_cancel" if not r["active"] else "info"
            self.people_tree.insert("","end",iid=f"p{r['id']}",
                values=(r["name"],r["email"],r["phone"],r["company"] or "",r["role"]),tags=(tag,))

    def refresh_companies(self):
        q=self.comp_q.get().lower().strip()
        show_archived=self.comp_show_archived.get() if hasattr(self,"comp_show_archived") else False
        for x in self.company_tree.get_children():self.company_tree.delete(x)
        with db() as con:
            rows=con.execute("""SELECT * FROM companies
                                WHERE (?=1 OR active=1)
                                ORDER BY active DESC,official_name COLLATE CZECH""",(1 if show_archived else 0,)).fetchall()
        for r in rows:
            if q and q not in " ".join(str(r[k] or "") for k in ("official_name","ico","dic","address")).lower():continue
            tag="status_cancel" if not r["active"] else "info"
            self.company_tree.insert("","end",iid=f"c{r['id']}",
                values=(r["official_name"],r["ico"],r["dic"],r["address"],r["legal_form"],
                        fmt_date(r["date_created"]),r["cz_nace"],fmt_date(r["ares_checked"])),tags=(tag,))

    def new_action(self):
        d=ActionDialog(self);self.wait_window(d)
        if d.result:self.refresh_all()
    def edit_action(self,tree):
        aid=self.selected_id(tree,"a")
        if aid:self.edit_action_by_id(aid)
    def request_for_action(self):
        aid=self.selected_id(self.action_tree,"a");d=RequestDialog(self,pre_action=aid);self.wait_window(d);self.save_request(d)
    def new_request(self):
        d=RequestDialog(self);self.wait_window(d);self.save_request(d)
    def save_request(self,d):
        if not d.result:return
        r=d.result
        user=get_setting("active_user","")
        with db() as con:
            rid=con.execute("""INSERT INTO requests(
                company_id,requested_for_company_id,action_id,asked_date,received_date,item,note,
                mail_subject,include_project_in_subject,recipients_snapshot,cc_snapshot,updated_by,assigned_user
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (r["company_id"],r["requested_for_company_id"],r["action_id"],r["asked"],r["received"],
             r["item"],r["note"],r["subject"],r["include"],";".join(r["recipients"]),
             CC_ALWAYS,user,r.get("assigned_user",""))).lastrowid
            comp=con.execute("SELECT official_name FROM companies WHERE id=?",(r["company_id"],)).fetchone()
            comp_for=con.execute("SELECT official_name FROM companies WHERE id=?",(r["requested_for_company_id"],)).fetchone()
        log_history(r["action_id"],"request_create","Vytvořil poptávku",
            f"Odběratel: {(comp_for['official_name'] if comp_for else '—')}; "
            f"U: {(comp['official_name'] if comp else '—')}; Poptáváno: {r['item']}; "
            f"Příjemci: {', '.join(r['recipients']) or 'doplnit později'}",
            r["company_id"],rid,user_name=user)
        self.refresh_after_request_change()

    def restore_request(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:return messagebox.showinfo("Poptávka","Vyberte poptávku.",parent=self)
        with db() as con:
            r=con.execute("SELECT action_id,archived FROM requests WHERE id=?",(rid,)).fetchone()
            if not r:return
            if not int(r["archived"] or 0):
                return messagebox.showinfo("Poptávka","Tato poptávka není archivovaná.",parent=self)
            con.execute("UPDATE requests SET archived=0,archived_at='',archived_by='' WHERE id=?",(rid,))
        if r["action_id"]:
            log_history(r["action_id"],"request_restore","Obnovil poptávku",
                        "Poptávka byla vrácena z archivu.",related_request_id=rid,
                        user_name=get_setting("active_user",""))
        self.refresh_after_request_change()

    def archive_request(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:return messagebox.showinfo("Poptávka","Vyberte poptávku.",parent=self)
        with db() as con:
            r=con.execute("""SELECT r.*,a.name action_name,c.official_name company,cf.official_name requested_for
                             FROM requests r
                             LEFT JOIN actions a ON a.id=r.action_id
                             LEFT JOIN companies c ON c.id=r.company_id
                             LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                             WHERE r.id=?""",(rid,)).fetchone()
        if not r:return
        if r["archived"]:
            return messagebox.showinfo("Poptávka","Tato poptávka už je archivovaná.",parent=self)
        if not messagebox.askyesno(
            "Archivovat poptávku",
            f"Archivovat tuto poptávku?\n\n"
            f"Akce: {r['action_name'] or '—'}\n"
            f"Pro: {r['requested_for'] or '—'}\n"
            f"U: {r['company'] or '—'}\n"
            f"Poptáváno: {r['item'] or '—'}\n\n"
            f"Záznam zůstane v databázi a historii.",
            parent=self
        ):return
        user=get_setting("active_user","")
        log_history(
            r["action_id"],"request_archive","Archivoval poptávku",
            f"Pro: {r['requested_for'] or '—'}; U: {r['company'] or '—'}; "
            f"Poptáváno: {r['item'] or '—'}; Příjemci: {r['recipients_snapshot'] or '—'}",
            r["company_id"],rid,user_name=user
        )
        with db() as con:
            con.execute("""UPDATE requests
                           SET archived=1,archived_at=CURRENT_TIMESTAMP,archived_by=?
                           WHERE id=?""",(user,rid))
        if hasattr(self,"req_show_archived"):self.req_show_archived.set(False)
        self.refresh_requests()
        self.refresh_dash()

    def hard_delete_request(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:return messagebox.showinfo("Poptávka","Vyberte poptávku.",parent=self)
        with db() as con:
            r=con.execute("""SELECT r.*,a.name action_name,c.official_name company,cf.official_name requested_for
                             FROM requests r
                             LEFT JOIN actions a ON a.id=r.action_id
                             LEFT JOIN companies c ON c.id=r.company_id
                             LEFT JOIN companies cf ON cf.id=r.requested_for_company_id
                             WHERE r.id=?""",(rid,)).fetchone()
        if not r:return
        if not messagebox.askyesno(
            "Smazat poptávku",
            f"Opravdu chcete poptávku trvale smazat z evidence?\n\n"
            f"Akce: {r['action_name'] or '—'}\n"
            f"Pro: {r['requested_for'] or '—'}\n"
            f"U: {r['company'] or '—'}\n"
            f"Poptáváno: {r['item'] or '—'}\n\n"
            f"Historické události už zapsané v historii zůstanou zachované.",
            parent=self
        ):return
        user=get_setting("active_user","")
        # Před fyzickým smazáním uložíme samostatný historický otisk bez FK na request_id.
        if r["action_id"]:
            with db() as con:
                con.execute("""INSERT INTO action_history(
                    action_id,created_at,user_name,event_type,summary,details,related_company_id,related_request_id
                ) VALUES(?,CURRENT_TIMESTAMP,?,?,?,?,?,NULL)""",
                (r["action_id"],user,"request_delete","Smazal poptávku",
                 f"Pro: {r['requested_for'] or '—'}; U: {r['company'] or '—'}; "
                 f"Poptáváno: {r['item'] or '—'}; Příjemci: {r['recipients_snapshot'] or '—'}; "
                 f"Poptáno: {r['asked_date'] or '—'}; Obdrženo: {r['received_date'] or '—'}",
                 r["company_id"]))
                # Odpojíme starší history řádky od request_id, aby šel záznam smazat bez ztráty historie.
                con.execute("UPDATE action_history SET related_request_id=NULL WHERE related_request_id=?",(rid,))
                con.execute("DELETE FROM requests WHERE id=?",(rid,))
        else:
            with db() as con:
                con.execute("DELETE FROM requests WHERE id=?",(rid,))
        self.refresh_requests()
        self.refresh_dash()


    def delete_request(self):
        # Zpětná kompatibilita starších callbacků: fyzické mazání.
        self.hard_delete_request()

    def mark_received(self):
        rid=self.selected_id(self.request_tree,"r")
        if rid:
            user=get_setting("active_user","")
            with db() as con:
                rr=con.execute("SELECT action_id,company_id,item FROM requests WHERE id=?",(rid,)).fetchone()
                con.execute("UPDATE requests SET received_date=?,no_response=0,updated_by=? WHERE id=?",
                            (date.today().isoformat(),user,rid))
            if rr:log_history(rr["action_id"],"request_received","Označil poptávku jako obdrženou",
                              f"Poptáváno: {rr['item']}",rr["company_id"],rid,user_name=user)
            self.refresh_after_request_change()

    def mark_no_response(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:return messagebox.showinfo("Poptávka","Vyberte poptávku.",parent=self)
        user=get_setting("active_user","")
        with db() as con:
            rr=con.execute("SELECT action_id,company_id,item,archived FROM requests WHERE id=?",(rid,)).fetchone()
            if not rr:return
            if int(rr["archived"] or 0):
                return messagebox.showinfo("Poptávka","Archivovanou poptávku nejdřív obnovte.",parent=self)
            con.execute("UPDATE requests SET no_response=1,received_date='',updated_by=? WHERE id=?",(user,rid))
        log_history(rr["action_id"],"request_no_response","Ukončil poptávku bez odezvy",
                    f"Poptáváno: {rr['item']}",rr["company_id"],rid,user_name=user)
        self.refresh_after_request_change()

    def edit_request(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:
            return messagebox.showinfo("Poptávka","Vyberte poptávku.",parent=self)

        with db() as con:
            current=con.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
        if not current:return
        if int(current["archived"] or 0)==1:
            return messagebox.showinfo("Poptávka","Archivovanou poptávku nejdřív obnovte.",parent=self)

        # RequestDialog už umí rid načíst sám. Nepředáváme žádný neexistující parametr.
        d=RequestDialog(self,rid=rid)
        self.wait_window(d)
        if not d.result:return
        data=d.result

        user=get_setting("active_user","")
        with db() as con:
            before=con.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone()
            no_response=0 if data["received"] else int(before["no_response"] or 0)
            con.execute("""UPDATE requests SET
                company_id=?,
                requested_for_company_id=?,
                action_id=?,
                asked_date=?,
                received_date=?,
                item=?,
                note=?,
                mail_subject=?,
                include_project_in_subject=?,
                recipients_snapshot=?,
                cc_snapshot=?,
                updated_by=?,
                assigned_user=?,
                no_response=?
                WHERE id=?""",
                (data["company_id"],
                 data["requested_for_company_id"],
                 data["action_id"],
                 data["asked"],
                 data["received"],
                 data["item"],
                 data["note"],
                 data["subject"],
                 data["include"],
                 ";".join(data["recipients"]),
                 CC_ALWAYS,
                 user,
                 data.get("assigned_user",""),
                 no_response,
                 rid))

        changes=[]
        pairs=[
            ("company_id","Dodavatel",data["company_id"]),
            ("requested_for_company_id","Odběratel",data["requested_for_company_id"]),
            ("action_id","Akce",data["action_id"]),
            ("asked_date","Poptáno",data["asked"]),
            ("received_date","Obdrženo",data["received"]),
            ("item","Poptáváno",data["item"]),
            ("note","Poznámka",data["note"]),
            ("recipients_snapshot","Příjemci",";".join(data["recipients"])),
            ("assigned_user","Řeší",data.get("assigned_user","")),
        ]
        for key,label,newval in pairs:
            oldval=(before[key] or "") if before and key in before.keys() else ""
            if str(oldval)!=str(newval or ""):
                changes.append(f"{label}: {oldval or '—'} → {newval or '—'}")

        log_history(
            data["action_id"],
            "request_edit",
            "Upravil poptávku",
            "; ".join(changes) if changes else "Uloženo bez změny údajů.",
            data["company_id"],
            rid,
            user_name=user
        )
        self.refresh_after_request_change()


    def mail_selected(self):
        rid=self.selected_id(self.request_tree,"r")
        if not rid:return
        with db() as con:r=con.execute("SELECT recipients_snapshot,mail_subject,cc_snapshot FROM requests WHERE id=?",(rid,)).fetchone()
        open_mail_draft((r["recipients_snapshot"] or "").split(";"),r["mail_subject"] or "",r["cc_snapshot"] or CC_ALWAYS)
    def export_people_csv(self):
        path=filedialog.asksaveasfilename(parent=self,title="Export adresáře",defaultextension=".csv",
                                          filetypes=[("CSV","*.csv")],initialfile="adresar_osob.csv")
        if not path:return
        with db() as con:
            rows=con.execute("""SELECT p.first_name,p.last_name,p.email,p.phone,p.position,
                                c.official_name company,c.official_name,c.ico
                                FROM people p LEFT JOIN companies c ON c.id=p.company_id
                                WHERE p.active=1 ORDER BY c.official_name,p.last_name,p.first_name""").fetchall()
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f,delimiter=";")
            w.writerow(["Jméno","Příjmení","E-mail","Telefon","Pozice","Společnost","Oficiální název","IČO"])
            for r in rows:w.writerow([r["first_name"],r["last_name"],r["email"],r["phone"],r["position"],r["company"],r["official_name"],r["ico"]])
        messagebox.showinfo("Export",f"Exportováno {len(rows)} kontaktů.",parent=self)

    def import_people_csv(self):
        path=filedialog.askopenfilename(parent=self,title="Import kontaktů z Outlooku / CSV",
                                        filetypes=[("CSV","*.csv"),("Všechny soubory","*.*")])
        if not path:return
        try:
            raw=Path(path).read_text(encoding="utf-8-sig",errors="replace")
            sample=raw[:4096]
            try:dialect=csv.Sniffer().sniff(sample,delimiters=";,\\t,")
            except:dialect=csv.excel
            rows=list(csv.DictReader(raw.splitlines(),dialect=dialect))
        except Exception as e:
            return messagebox.showerror("Import",f"Soubor nelze načíst:\\n{e}",parent=self)
        def pick(r,*names):
            low={str(k).strip().lower():v for k,v in r.items() if k}
            for n in names:
                if n.lower() in low and str(low[n.lower()] or "").strip():return str(low[n.lower()]).strip()
            return ""
        added=updated=skipped=0
        with db() as con:
            for r in rows:
                email=pick(r,"E-mail","Email Address","E-mail Address","Email")
                first=pick(r,"Jméno","First Name","Given Name")
                last=pick(r,"Příjmení","Last Name","Surname")
                company=pick(r,"Společnost","Company","Company Name")
                phone=pick(r,"Telefon","Business Phone","Mobile Phone","Phone")
                position=pick(r,"Pozice","Job Title","Title")
                if not any((email,first,last)):skipped+=1;continue
                cid=None
                if company:
                    cr=con.execute("""SELECT id FROM companies WHERE active=1 AND
                        (lower(trim(short_name))=lower(trim(?)) OR lower(trim(official_name))=lower(trim(?)))""",(company,company)).fetchall()
                    ids=list(dict.fromkeys(x["id"] for x in cr))
                    if len(ids)==1:cid=ids[0]
                    elif len(ids)==0:
                        cid=con.execute("INSERT INTO companies(short_name,official_name) VALUES(?,?)",(company,company)).lastrowid
                existing=con.execute("SELECT id FROM people WHERE lower(trim(email))=lower(trim(?)) AND trim(?)<>''",(email,email)).fetchone() if email else None
                if existing:
                    con.execute("""UPDATE people SET first_name=?,last_name=?,phone=?,position=?,
                                   company_id=coalesce(?,company_id),active=1 WHERE id=?""",
                                (first,last,phone,position,cid,existing["id"]))
                    updated+=1
                else:
                    con.execute("""INSERT INTO people(first_name,last_name,email,phone,position,company_id,active)
                                   VALUES(?,?,?,?,?,?,1)""",(first,last,email,phone,position,cid))
                    added+=1
        self.refresh_all()
        messagebox.showinfo("Import",f"Hotovo.\\nNové: {added}\\nAktualizované: {updated}\\nPřeskočené: {skipped}",parent=self)

    def import_people(self):
        path=filedialog.askopenfilename(parent=self,title="Import kontaktů",
            filetypes=[("Kontakty CSV / vCard","*.csv *.vcf"),("CSV","*.csv"),("vCard","*.vcf")])
        if not path:return
        try:records=read_contacts_file(path)
        except Exception as e:return messagebox.showerror("Import kontaktů",f"Soubor se nepodařilo načíst:\n{e}",parent=self)
        if not records:return messagebox.showinfo("Import kontaktů","V souboru nebyly nalezeny žádné kontakty.",parent=self)

        imported=0;skipped=0
        for idx,rec in enumerate(records,1):
            existing=None
            if rec.get("email"):
                with db() as con:
                    existing=con.execute("SELECT id FROM people WHERE lower(trim(email))=lower(trim(?)) LIMIT 1",
                                         (rec["email"],)).fetchone()
            if existing:
                ans=messagebox.askyesnocancel("Import kontaktů",
                    f"Kontakt {idx}/{len(records)}\n\nE-mail {rec['email']} už existuje.\n\n"
                    "Ano = otevřít existující osobu k doplnění\nNe = přeskočit\nZrušit = ukončit import",parent=self)
                if ans is None:break
                if ans is False:skipped+=1;continue
                d=PersonDialog(self,pid=existing["id"])
            else:
                d=PersonDialog(self)
                d.vars["name"].set(rec.get("name",""))
                d.vars["email"].set(rec.get("email",""))
                d.vars["phone"].set(rec.get("phone",""))
                d.vars["role"].set(rec.get("role",""))
                company=rec.get("company","").strip()
                if company:
                    with db() as con:
                        hits=con.execute("""SELECT official_name FROM companies
                                            WHERE active=1 AND lower(trim(official_name))=lower(trim(?))""",
                                         (company,)).fetchall()
                    if len(hits)==1:d.company.set(hits[0]["official_name"])
            d.title(f"Import osoby {idx}/{len(records)} – doplňte údaje")
            self.wait_window(d)
            if d.result:imported+=1
            else:skipped+=1
        self.refresh_people()
        messagebox.showinfo("Import kontaktů",
            f"Import dokončen.\n\nUloženo / aktualizováno: {imported}\nPřeskočeno: {skipped}",parent=self)

    def export_people(self):
        path=filedialog.asksaveasfilename(parent=self,title="Kam exportovat kontakty?",
            defaultextension=".csv",
            filetypes=[("CSV pro Excel / Outlook","*.csv"),("vCard","*.vcf")],
            initialfile=f"Kontakty_{date.today().isoformat()}.csv")
        if not path:return
        try:
            if str(path).lower().endswith(".vcf"):write_people_vcf(path)
            else:write_people_csv(path)
            messagebox.showinfo("Export kontaktů",f"Kontakty byly exportovány:\n{path}",parent=self)
        except Exception as e:
            messagebox.showerror("Export kontaktů",f"Export se nepodařil:\n{e}",parent=self)

    def new_person(self):
        d=PersonDialog(self);self.wait_window(d)
        if d.result:self.refresh_all()
    def edit_person(self):
        pid=self.selected_id(self.people_tree,"p")
        if pid:
            d=PersonDialog(self,pid);self.wait_window(d)
            if d.result:self.refresh_all()
    def toggle_person_active(self):
        pid=self.selected_id(self.people_tree,"p")
        if not pid:return messagebox.showinfo("Osoba","Vyberte osobu.",parent=self)
        with db() as con:r=con.execute("SELECT name,active FROM people WHERE id=?",(pid,)).fetchone()
        if not r:return
        new_active=0 if r["active"] else 1
        text="označit jako neaktivní" if r["active"] else "znovu aktivovat"
        if not messagebox.askyesno("Osoba",f"Opravdu chcete {text} osobu „{r['name']}“?",parent=self):return
        with db() as con:con.execute("UPDATE people SET active=? WHERE id=?",(new_active,pid))
        self.refresh_people()

    def delete_person(self):
        pid=self.selected_id(self.people_tree,"p")
        if not pid:return messagebox.showinfo("Osoba","Vyberte osobu.",parent=self)
        with db() as con:r=con.execute("SELECT name,email FROM people WHERE id=?",(pid,)).fetchone()
        if not r:return
        if not messagebox.askyesno("Smazat osobu",
            f"Opravdu trvale smazat osobu „{r['name']}“?\n\n"
            f"E-mail: {r['email'] or '—'}\n\n"
            "Historické e-mailové snapshoty v Poptávkách zůstanou zachované.",
            parent=self):return
        with db() as con:con.execute("DELETE FROM people WHERE id=?",(pid,))
        self.refresh_people()

    def new_company(self):
        d=CompanyDialog(self);self.wait_window(d)
        if d.result:self.refresh_all()
    def edit_company(self):
        cid=self.selected_id(self.company_tree,"c")
        if cid:
            d=CompanyDialog(self,cid);self.wait_window(d)
            if d.result:self.refresh_all()
    def archive_company(self):
        cid=self.selected_id(self.company_tree,"c")
        if not cid:return messagebox.showinfo("Společnost","Vyberte společnost.",parent=self)
        with db() as con:r=con.execute("SELECT official_name,active FROM companies WHERE id=?",(cid,)).fetchone()
        if not r:return
        new_active=0 if r["active"] else 1
        verb="archivovat" if r["active"] else "obnovit"
        if not messagebox.askyesno("Společnost",f"Opravdu chcete {verb} společnost „{r['official_name']}“?",parent=self):return
        with db() as con:con.execute("UPDATE companies SET active=? WHERE id=?",(new_active,cid))
        self.refresh_all()

    def delete_company(self):
        cid=self.selected_id(self.company_tree,"c")
        if not cid:return messagebox.showinfo("Společnost","Vyberte společnost.",parent=self)
        with db() as con:
            r=con.execute("SELECT official_name FROM companies WHERE id=?",(cid,)).fetchone()
            deps={
                "osob":con.execute("SELECT COUNT(*) FROM people WHERE company_id=?",(cid,)).fetchone()[0],
                "příležitostí":con.execute("SELECT COUNT(*) FROM actions WHERE company_id=?",(cid,)).fetchone()[0],
                "poptávek":con.execute("""SELECT COUNT(*) FROM requests
                                          WHERE company_id=? OR requested_for_company_id=?""",(cid,cid)).fetchone()[0],
                "historických záznamů":con.execute("SELECT COUNT(*) FROM action_history WHERE related_company_id=?",(cid,)).fetchone()[0],
            }
        if not r:return
        total=sum(deps.values())
        if total:
            detail=", ".join(f"{v} {k}" for k,v in deps.items() if v)
            if messagebox.askyesno("Společnost má vazby",
                f"Společnost „{r['official_name']}“ nelze fyzicky smazat, protože má {detail}.\n\n"
                f"Chcete ji místo toho archivovat? Historie zůstane zachovaná.",parent=self):
                with db() as con:con.execute("UPDATE companies SET active=0 WHERE id=?",(cid,))
                self.refresh_all()
            return
        if not messagebox.askyesno("Smazat společnost",
            f"Opravdu trvale smazat společnost „{r['official_name']}“?\n\nNemá žádné navázané záznamy.",parent=self):return
        with db() as con:con.execute("DELETE FROM companies WHERE id=?",(cid,))
        self.refresh_all()

    def maybe_auto_update_ares(self):
        """Jednorázově doplní/aktualizuje všechny společnosti z ARES pro tuto databázi.
        Po úspěšném dokončení se v této databázi už znovu automaticky nespouští.
        """
        marker="ares_auto_full_v131"
        if get_setting(marker,"")=="done":
            return
        # Bez dotazování uživatele; před změnou vždy bezpečnostní záloha.
        backup=backup_now("before_auto_ares")
        win=tk.Toplevel(self);win.title("Automatická aktualizace ARES");win.geometry("650x190")
        win.transient(self)
        lab=ttk.Label(win,text="Automaticky doplňuji společnosti z ARES…",padding=20)
        lab.pack(fill="x")
        ttk.Label(win,text=f"Záloha databáze: {backup}",padding=(20,0)).pack(fill="x")
        ttk.Label(win,text="Tato automatická aktualizace se po úspěšném dokončení už nebude při dalším spuštění opakovat.",
                  padding=(20,10),foreground="#667085",wraplength=600).pack(fill="x")

        def worker():
            updated=ambiguous=notfound=errors=0
            with db() as con:
                rows=con.execute("SELECT * FROM companies WHERE active=1 ORDER BY short_name").fetchall()

            for i,r in enumerate(rows,1):
                try:
                    source=None
                    if (r["ico"] or "").strip():
                        try:
                            source=ares_detail(r["ico"].strip())
                        except Exception:
                            source=None
                    else:
                        q=(r["official_name"] or r["short_name"] or "").strip()
                        if q:
                            res=ares_search(q,10)
                            cand=[ares_company_data(x) for x in res]
                            exact=[x for x in cand if norm_name(x["official_name"])==norm_name(q)]
                            if len(exact)==1:
                                source=json.loads(exact[0]["ares_raw_json"])
                            elif len(exact)>1:
                                ambiguous+=1
                            else:
                                notfound+=1

                    if source:
                        x=ares_company_data(source)
                        with db() as con:
                            con.execute("""UPDATE companies SET official_name=?,ico=?,dic=?,address=?,legal_form=?,ares_checked=?,
                                date_created=?,ares_last_change=?,cz_nace=?,financial_office=?,district=?,municipality=?,ares_raw_json=?
                                WHERE id=?""",
                                (x["official_name"] or r["official_name"],x["ico"] or r["ico"],x["dic"],x["address"],
                                 x["legal_form"],x["ares_checked"],x["date_created"],x["ares_last_change"],
                                 x["cz_nace"],x["financial_office"],x["district"],x["municipality"],
                                 x["ares_raw_json"],r["id"]))
                        updated+=1
                    elif (r["ico"] or "").strip():
                        errors+=1
                except Exception:
                    errors+=1

                self.after(0,lambda i=i,n=len(rows),u=updated,a=ambiguous,nf=notfound,er=errors:
                    lab.config(text=f"{i}/{n} · aktualizováno {u} · nejednoznačné {a} · nenalezeno {nf} · chyby {er}"))

            # Mark done only if most companies were processed without technical errors.
            if errors < max(5, len(rows)//4):
                set_setting(marker,"done")

            def finish():
                self.refresh_all()
                messagebox.showinfo("ARES",
                    f"Automatická aktualizace dokončena.\\n\\n"
                    f"Aktualizováno: {updated}\\n"
                    f"Nejednoznačné: {ambiguous}\\n"
                    f"Nenalezeno: {notfound}\\n"
                    f"Chyby: {errors}\\n\\n"
                    f"Záloha před změnou:\\n{backup}",
                    parent=win)
                win.destroy()
            self.after(0,finish)

        threading.Thread(target=worker,daemon=True).start()

    def batch_ares(self):
        if not messagebox.askyesno("ARES","Aktualizovat všechny společnosti z ARES?\n\nPřed změnou se vytvoří záloha. Nejednoznačné shody se nepřepíší."):return
        backup=backup_now("before_ares_full")
        win=tk.Toplevel(self);win.title("Aktualizace ARES");win.geometry("640x180")
        lab=ttk.Label(win,text="Spouštím…",padding=20);lab.pack(fill="x")
        ttk.Label(win,text=f"Záloha: {backup}",padding=(20,0)).pack(fill="x")
        def worker():
            updated=ambiguous=notfound=errors=0
            with db() as con:rows=con.execute("SELECT * FROM companies WHERE active=1 ORDER BY short_name").fetchall()
            for i,r in enumerate(rows,1):
                try:
                    source=None
                    if (r["ico"] or "").strip():
                        try:source=ares_detail(r["ico"].strip())
                        except:source=None
                    else:
                        q=(r["official_name"] or r["short_name"] or "").strip()
                        res=ares_search(q,10)
                        cand=[ares_company_data(x) for x in res]
                        exact=[x for x in cand if norm_name(x["official_name"])==norm_name(q)]
                        if len(exact)==1:source=json.loads(exact[0]["ares_raw_json"])
                        elif len(exact)>1:ambiguous+=1
                        else:notfound+=1
                    if source:
                        x=ares_company_data(source)
                        with db() as con:
                            con.execute("""UPDATE companies SET official_name=?,ico=?,dic=?,address=?,legal_form=?,ares_checked=?,
                                date_created=?,ares_last_change=?,cz_nace=?,financial_office=?,district=?,municipality=?,ares_raw_json=? WHERE id=?""",
                                (x["official_name"] or r["official_name"],x["ico"] or r["ico"],x["dic"],x["address"],x["legal_form"],x["ares_checked"],
                                 x["date_created"],x["ares_last_change"],x["cz_nace"],x["financial_office"],x["district"],x["municipality"],x["ares_raw_json"],r["id"]))
                        updated+=1
                except:errors+=1
                self.after(0,lambda i=i,n=len(rows),u=updated,a=ambiguous,nf=notfound,er=errors:
                           lab.config(text=f"{i}/{n} · aktualizováno {u} · nejednoznačné {a} · nenalezeno {nf} · chyby {er}"))
            self.after(0,lambda:self._finish_ares(win,updated,ambiguous,notfound,errors,backup))
        threading.Thread(target=worker,daemon=True).start()

    def _finish_ares(self,win,updated,ambiguous,notfound,errors,backup):
        self.refresh_all()
        messagebox.showinfo("ARES",f"Hotovo.\n\nAktualizováno: {updated}\nNejednoznačné: {ambiguous}\nNenalezeno: {notfound}\nChyby: {errors}\n\nZáloha:\n{backup}",parent=win)
        win.destroy()

    def database_audit(self):
        problems=[]
        with db() as con:
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            counts={
                "Společnosti":con.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
                "Osoby":con.execute("SELECT COUNT(*) FROM people").fetchone()[0],
                "Příležitosti":con.execute("SELECT COUNT(*) FROM actions").fetchone()[0],
                "Akce":con.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "Poptávky":con.execute("SELECT COUNT(*) FROM requests").fetchone()[0],
                "Úkoly":con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                "Historie":con.execute("SELECT COUNT(*) FROM action_history").fetchone()[0],
                "Uživatelé":con.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            }
            checks=[
                ("Osoby bez existující společnosti","""SELECT COUNT(*) FROM people p LEFT JOIN companies c ON c.id=p.company_id
                                                       WHERE p.company_id IS NOT NULL AND c.id IS NULL"""),
                ("Příležitosti bez existující společnosti","""SELECT COUNT(*) FROM actions a LEFT JOIN companies c ON c.id=a.company_id
                                                              WHERE a.company_id IS NOT NULL AND c.id IS NULL"""),
                ("Příležitosti bez existující Akce","""SELECT COUNT(*) FROM actions a LEFT JOIN projects p ON p.id=a.project_id
                                                       WHERE a.project_id IS NOT NULL AND p.id IS NULL"""),
                ("Poptávky bez existující společnosti","""SELECT COUNT(*) FROM requests r LEFT JOIN companies c ON c.id=r.company_id
                                                          WHERE r.company_id IS NOT NULL AND c.id IS NULL"""),
                ("Poptávky bez existující Příležitosti","""SELECT COUNT(*) FROM requests r LEFT JOIN actions a ON a.id=r.action_id
                                                           WHERE r.action_id IS NOT NULL AND a.id IS NULL"""),
                ("Úkoly bez existující Příležitosti","""SELECT COUNT(*) FROM tasks t LEFT JOIN actions a ON a.id=t.action_id
                                                        WHERE t.action_id IS NOT NULL AND a.id IS NULL"""),
            ]
            for label,sql in checks:
                n=con.execute(sql).fetchone()[0]
                if n:problems.append(f"• {label}: {n}")
        lines=[f"SQLite integrita: {'✓ v pořádku' if integrity=='ok' else '✗ '+str(integrity)}",""]
        lines += [f"{k}: {v}" for k,v in counts.items()]
        lines += ["","Vazby mezi daty:"]
        lines += problems if problems else ["✓ Nebyly nalezeny neplatné vazby."]
        lines += ["","Kontrola nic nezměnila ani neopravovala."]
        messagebox.showinfo("Kontrola dat","\n".join(lines),parent=self)


    def manage_users(self):
        d=tk.Toplevel(self);d.title("Správa uživatelů");d.transient(self);d.grab_set();d.geometry("760x520");enable_dialog_maximize(d,720,500);center_dialog(d,self)
        f=ttk.Frame(d,padding=14);f.pack(fill="both",expand=True)
        f.columnconfigure(0,weight=1);f.rowconfigure(2,weight=1)
        ttk.Label(f,text="Správa uživatelů",font=("Calibri",15,"bold")).grid(row=0,column=0,sticky="w")
        ttk.Label(f,text="Smazání uživatele neovlivní historii. Historické záznamy uchovávají původní jméno jako text.",
                  wraplength=570).grid(row=1,column=0,sticky="ew",pady=(2,10))
        tree=ttk.Treeview(f,columns=("Jméno","Stav"),show="headings",selectmode="browse",height=12)
        tree.heading("Jméno",text="Jméno");tree.heading("Stav",text="Stav")
        tree.column("Jméno",width=360);tree.column("Stav",width=140);tree.grid(row=2,column=0,sticky="nsew")

        def refresh():
            for x in tree.get_children():tree.delete(x)
            with db() as con:rows=con.execute("SELECT id,name,active FROM users ORDER BY active DESC,name COLLATE CZECH").fetchall()
            for r in rows:tree.insert("","end",iid=f"u{r['id']}",values=(r["name"],"Aktivní" if r["active"] else "Neaktivní"))

        def selected():
            s=tree.selection();return int(s[0][1:]) if s else None

        def add():
            name=simpledialog.askstring("Nový uživatel","Jméno uživatele:",parent=d)
            if not name:return
            try:
                with db() as con:con.execute("INSERT INTO users(name) VALUES(?)",(name.strip(),))
            except sqlite3.IntegrityError:
                return messagebox.showwarning("Uživatel","Takový uživatel už existuje.",parent=d)
            refresh();self.refresh_user_selector()

        def edit():
            uid=selected()
            if not uid:return
            with db() as con:r=con.execute("SELECT name FROM users WHERE id=?",(uid,)).fetchone()
            if not r:return
            old=r["name"];name=simpledialog.askstring("Upravit uživatele","Jméno:",initialvalue=old,parent=d)
            if not name:return
            try:
                with db() as con:
                    con.execute("UPDATE users SET name=? WHERE id=?",(name.strip(),uid))
                    con.execute("UPDATE user_settings SET user_name=? WHERE user_name=?",(name.strip(),old))
                    con.execute("UPDATE user_notes SET user_name=? WHERE user_name=?",(name.strip(),old))
                if get_setting("active_user","")==old:set_setting("active_user",name.strip());self.active_user.set(name.strip())
            except sqlite3.IntegrityError:
                return messagebox.showwarning("Uživatel","Takový uživatel už existuje.",parent=d)
            refresh();self.refresh_user_selector()

        def toggle():
            uid=selected()
            if not uid:return
            with db() as con:
                r=con.execute("SELECT name,active FROM users WHERE id=?",(uid,)).fetchone()
                if not r:return
                if r["active"] and r["name"]==get_setting("active_user",""):
                    return messagebox.showwarning("Uživatel","Aktuálního uživatele nejdřív přepněte.",parent=d)
                if r["active"] and con.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]<=1:
                    return messagebox.showwarning("Uživatel","Musí zůstat alespoň jeden aktivní uživatel.",parent=d)
                con.execute("UPDATE users SET active=? WHERE id=?",(0 if r["active"] else 1,uid))
            refresh();self.refresh_user_selector()

        def delete():
            uid=selected()
            if not uid:return messagebox.showinfo("Uživatel","Vyberte uživatele.",parent=d)
            with db() as con:
                r=con.execute("SELECT name,active FROM users WHERE id=?",(uid,)).fetchone()
                if not r:return
                total=con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                active_count=con.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
            if r["name"]==get_setting("active_user",""):
                return messagebox.showwarning("Uživatel","Aktuálního uživatele nejdřív přepněte na jiného.",parent=d)
            if total<=1:return messagebox.showwarning("Uživatel","Posledního uživatele nelze smazat.",parent=d)
            if r["active"] and active_count<=1:return messagebox.showwarning("Uživatel","Musí zůstat alespoň jeden aktivní uživatel.",parent=d)
            if not messagebox.askyesno("Smazat uživatele",f"Opravdu chcete smazat uživatele „{r['name']}“?\n\nHistorie se nezmění.",parent=d):return
            with db() as con:
                con.execute("DELETE FROM users WHERE id=?",(uid,))
                con.execute("DELETE FROM user_settings WHERE user_name=?",(r["name"],))
            refresh();self.refresh_user_selector()

        b=ttk.Frame(f);b.grid(row=3,column=0,sticky="ew",pady=(12,0))
        ttk.Button(b,text="+ Přidat uživatele",style="Accent.TButton",command=add).grid(row=0,column=0,sticky="ew",padx=3,pady=3)
        ttk.Button(b,text="✎ Upravit uživatele",command=edit).grid(row=0,column=1,sticky="ew",padx=3,pady=3)
        ttk.Button(b,text="🗑 Smazat uživatele",command=delete).grid(row=0,column=2,sticky="ew",padx=3,pady=3)
        ttk.Button(b,text="Aktivní / neaktivní",command=toggle).grid(row=1,column=0,sticky="ew",padx=3,pady=3)
        ttk.Button(b,text="Zavřít",command=d.destroy).grid(row=1,column=2,sticky="ew",padx=3,pady=3)
        for _c in range(3):b.columnconfigure(_c,weight=1)
        bind_row_double_click(tree,lambda e:edit())
        refresh();self.wait_window(d)

    def export_selected_dialog(self):
        d=tk.Toplevel(self);d.title("Výběrový export");d.transient(self);d.grab_set()
        f=ttk.Frame(d,padding=16);f.pack(fill="both",expand=True)
        ttk.Label(f,text="Co chcete exportovat?",font=("Calibri",14,"bold")).pack(anchor="w",pady=(0,8))
        labels=["Společnosti","Osoby","Příležitosti","Akce","Poptávky","Úkoly","Historie","Uživatelé","Číselníky","Nastavení"]
        vars={x:tk.BooleanVar(value=(x=="Společnosti")) for x in labels}
        grid=ttk.Frame(f);grid.pack(fill="x")
        for i,label in enumerate(labels):
            ttk.Checkbutton(grid,text=label,variable=vars[label]).grid(row=i//2,column=i%2,sticky="w",padx=(0,24),pady=3)
        related=tk.BooleanVar(value=False)
        ttk.Checkbutton(f,text="Včetně souvisejících vazeb",variable=related).pack(anchor="w",pady=(10,4))
        def go():
            selected=[x for x,v in vars.items() if v.get()]
            if not selected:return messagebox.showwarning("Export","Vyberte alespoň jednu položku.",parent=d)
            path=filedialog.asksaveasfilename(parent=d,title="Kam uložit výběrový export?",defaultextension=".zip",
                                              filetypes=[("ZIP balíček","*.zip")],
                                              initialfile=f"ZakazkyApp_vyber_{date.today().isoformat()}.zip")
            if not path:return
            try:
                out=export_selected_data(path,selected,related.get())
                messagebox.showinfo("Export",f"Export dokončen:\n{out}",parent=d);d.destroy()
            except Exception as e:messagebox.showerror("Export",str(e),parent=d)
        b=ttk.Frame(f);b.pack(fill="x",pady=(12,0))
        ttk.Button(b,text="Zrušit",command=d.destroy).pack(side="right")
        ttk.Button(b,text="Exportovat",style="Accent.TButton",command=go).pack(side="right",padx=6)

    def export_complete_data(self):
        path=filedialog.asksaveasfilename(parent=self,title="Kam exportovat kompletní data?",defaultextension=".zip",filetypes=[("ZIP balíček","*.zip")],initialfile=f"ZakazkyApp_data_{date.today().isoformat()}.zip")
        if not path:return
        try:messagebox.showinfo("Export",f"Kompletní data byla exportována:\n{export_complete_database(path)}",parent=self)
        except Exception as e:messagebox.showerror("Export",f"Export se nepodařil:\n{e}",parent=self)

    def import_complete_data(self):
        path=filedialog.askopenfilename(parent=self,title="Import kompletních dat",filetypes=[("ZIP balíček","*.zip")])
        if not path:return
        if not messagebox.askyesno("Import kompletních dat","Import nahradí aktuální databázi. Před změnou se automaticky vytvoří záloha. Pokračovat?",parent=self):return
        try:
            backup=import_complete_database(path);self.refresh_all();messagebox.showinfo("Import",f"Import dokončen.\nZáloha před importem:\n{backup}",parent=self)
        except Exception as e:messagebox.showerror("Import",f"Import se nepodařil:\n{e}",parent=self)

    def manual_backup(self):
        p=backup_now("manual");messagebox.showinfo("Záloha",f"Záloha vytvořena:\n{p}")
    def apply_theme(self,theme=None,save=True):
        if theme is None and hasattr(self,"theme_var"):theme=self.theme_var.get()
        theme=theme or "Tmavý"
        dark=(theme=="Tmavý")
        if dark:
            bg="#0b1014";panel="#12181d";field="#1a2228";fg="#f3f5f6";muted="#929ca4"
            head="#1b2329";select="#735b1c";border="#2a343b";card="#10161b"
            topbar="#0d1317";navbar="#12191e";accent="#f2b90b";accent_active="#ffd23b"
        else:
            bg="#f2f4f5";panel="#fafbfb";field="#ffffff";fg="#1c2429";muted="#6c777f"
            head="#e9edef";select="#d6b64c";border="#d4dade";card="#ffffff"
            topbar="#192229";navbar="#232e35";accent="#d79f00";accent_active="#efba19"

        self.palette={"bg":bg,"panel":panel,"field":field,"fg":fg,"muted":muted,
                      "head":head,"select":select,"border":border,"card":card,
                      "topbar":topbar,"navbar":navbar,"accent":accent}

        self.configure(bg=bg)
        s=ttk.Style(self)
        s.configure(".",font=("Calibri",11),background=bg,foreground=fg)
        s.configure("App.TFrame",background=bg)
        s.configure("TFrame",background=bg)
        s.configure("Panel.TFrame",background=panel,relief="flat")
        s.configure("Card.TFrame",background=card,relief="solid",borderwidth=1,bordercolor=border)
        s.configure("Topbar.TFrame",background=topbar)
        s.configure("NavBar.TFrame",background=navbar)
        s.configure("Footer.TFrame",background=bg)

        s.configure("TLabel",background=bg,foreground=fg)
        s.configure("Panel.TLabel",background=panel,foreground=fg)
        s.configure("FilterLabel.TLabel",background=panel,foreground=muted,font=("Calibri",9,"bold"),padding=(2,0))
        s.configure("Topbar.TLabel",background=topbar,foreground="#f4f5f6")
        s.configure("TopbarMuted.TLabel",background=topbar,foreground="#aeb5ba")
        s.configure("Footer.TLabel",background=bg,foreground=muted)
        s.configure("FooterAccent.TLabel",background=bg,foreground=accent)
        s.configure("BrandAccent.TLabel",background=topbar,foreground=accent)
        s.configure("PageSubtitle.TLabel",background=bg,foreground=muted,font=("Calibri",10))
        s.configure("DialogShell.TFrame",background=bg)
        s.configure("DialogBody.TFrame",background=bg)
        s.configure("DialogHeader.TFrame",background=panel)
        s.configure("DialogTitle.TLabel",background=panel,foreground=fg,font=("Calibri",17,"bold"))
        s.configure("DialogSubtitle.TLabel",background=panel,foreground=muted,font=("Calibri",10))
        s.configure("Title.TLabel",background=bg,foreground=fg,font=("Calibri",20,"bold"))
        s.configure("Section.TLabel",background=card,foreground=fg,font=("Calibri",11,"bold"),padding=(0,2))
        s.configure("CardTitle.TLabel",background=card,foreground=fg,font=("Calibri",11,"bold"))
        s.configure("FocusBadge.TLabel",background=accent,foreground="#111111",font=("Calibri",9,"bold"),padding=(8,4))
        s.configure("FocusText.TLabel",background=card,foreground=fg,font=("Calibri",10,"bold"))

        s.configure("KPIBlue.TLabel",background=card,foreground="#6faee8")
        s.configure("KPIRed.TLabel",background=card,foreground="#ef6b68")
        s.configure("KPIOrange.TLabel",background=card,foreground=accent)
        s.configure("KPIGreen.TLabel",background=card,foreground="#65c18c")

        s.configure("TLabelframe",background=card,foreground=fg,bordercolor=border)
        s.configure("TLabelframe.Label",background=card,foreground=fg,font=("Calibri",11,"bold"))
        s.configure("TButton",background=panel,foreground=fg,padding=(10,7),bordercolor=border,relief="flat")
        s.map("TButton",background=[("active",head),("pressed",field)],foreground=[("disabled",muted)])
        s.configure("Toolbar.TButton",background=panel,foreground=fg,padding=(10,7),bordercolor=border)
        s.map("Toolbar.TButton",background=[("active",head)])
        s.configure("Ghost.TButton",background=bg,foreground=muted,padding=(10,7),borderwidth=0)
        s.map("Ghost.TButton",foreground=[("active",fg)],background=[("active",bg)])
        s.configure("TopAction.TButton",background=topbar,foreground="#f3f4f5",padding=(9,6),borderwidth=0)
        s.map("TopAction.TButton",background=[("active","#252d33")],foreground=[("active","white")])
        s.configure("TopNav.TButton",background=navbar,foreground="#bfc7cc",padding=(16,12),borderwidth=0,font=("Calibri",10))
        s.configure("TopNavActive.TButton",background=head,foreground=accent,padding=(16,12),
                    borderwidth=0,font=("Calibri",10,"bold"))
        s.map("TopNav.TButton",background=[("active",head)],foreground=[("active","white")])
        s.map("TopNavActive.TButton",background=[("active",head)],foreground=[("active",accent)])

        s.configure("Accent.TButton",background=accent,foreground="#111111",padding=(12,8),
                    borderwidth=0,font=("Calibri",11,"bold"))
        s.map("Accent.TButton",background=[("active",accent_active)],foreground=[("active","#111111")])
        s.configure("TCheckbutton",background=panel,foreground=fg)
        s.map("TCheckbutton",background=[("active",panel)],foreground=[("disabled",muted)])
        s.configure("TEntry",fieldbackground=field,foreground=fg,insertcolor=fg,bordercolor=border,padding=(8,7))
        s.configure("TCombobox",fieldbackground=field,background=field,foreground=fg,arrowcolor=fg,bordercolor=border,padding=(7,6))
        s.map("TCombobox",fieldbackground=[("readonly",field)],foreground=[("readonly",fg)])
        s.configure("Treeview",background=card,fieldbackground=card,foreground=fg,rowheight=34,bordercolor=border,relief="flat")
        s.map("Treeview",background=[("selected",select)],foreground=[("selected","white")])
        s.configure("Treeview.Heading",background=head,foreground=fg,font=("Calibri",11,"bold"),relief="flat")
        s.map("Treeview.Heading",
              background=[("active",accent),("pressed",accent_active)],
              foreground=[("active","#111111"),("pressed","#111111")])

        s.configure("Bell.TButton",background=topbar,foreground="white")
        s.configure("BellAlert.TButton",background="#c43c35",foreground="white",font=("Calibri",9,"bold"))
        s.configure("TestMode.TLabel",background=accent,foreground="#111111",padding=(18,8),relief="flat")

        self.option_add("*TCombobox*Listbox.background",field)
        self.option_add("*TCombobox*Listbox.foreground",fg)
        self.option_add("*TCombobox*Listbox.selectBackground",select)
        self.option_add("*TCombobox*Listbox.selectForeground","white")
        def recolor(w):
            try:
                cls=w.winfo_class()
                if cls in ("Text","Listbox"):
                    w.configure(bg=field,fg=fg,insertbackground=fg,selectbackground=select,selectforeground="white",
                                highlightbackground=border,highlightcolor=select)
                elif cls=="Canvas":
                    w.configure(bg=bg,highlightbackground=bg)
                elif cls=="Treeview":
                    if dark:
                        status_colors={
                            "status_active":("#16222b","#e8f1f6"),"info":("#16222b","#e8f1f6"),"req_fresh":("#16222b","#e8f1f6"),
                            "status_wait":("#262318","#f4ead0"),"waiting":("#262318","#f4ead0"),"req_mid":("#262318","#f4ead0"),
                            "status_soon":("#2b211a","#f7e8d9"),"soon":("#2b211a","#f7e8d9"),"req_old":("#2b211a","#f7e8d9"),
                            "status_late":("#2c1c1d","#f7e4e4"),"late":("#2c1c1d","#f7e4e4"),
                            "status_done":("#16251e","#e7f5ec"),"done":("#16251e","#e7f5ec"),
                            "status_won":("#17271f","#e7f5ec"),"won":("#17271f","#e7f5ec"),"req_received":("#16251e","#e7f5ec"),
                            "status_cancel":("#202529","#e4e8ea"),"lost":("#202529","#e4e8ea"),
                            "status_offer":("#241e2b","#eee6f5")
                        }
                        for tag,(tb,tfg) in status_colors.items():
                            try:w.tag_configure(tag,background=tb,foreground=tfg)
                            except Exception:pass
                elif cls=="Menu":
                    w.configure(bg=panel,fg=fg,activebackground=select,activeforeground="white")
            except:pass
            try:
                for ch in w.winfo_children():recolor(ch)
            except:pass
        recolor(self)
        if save and hasattr(self,"active_user"):set_user_setting(self.active_user.get().strip(),"theme",theme)
        if hasattr(self,"theme"):self.theme.set(theme)
        if hasattr(self,"refresh_user_button"):self.refresh_user_button()


if __name__=="__main__":
    cleanup_stale_test_session()
    ensure_schema()
    ensure_test_user()
    migrate_v41_visual_once()
    import_mail_contacts_v220_once()
    import_mail_contacts_v221_once()
    restore_people_from_v280_backup_once()
    post_import_cleanup_v222_once()
    App().mainloop()
