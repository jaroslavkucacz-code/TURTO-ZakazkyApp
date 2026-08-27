# TURTO Zakazky CRM v5.8 feature layer
# Loaded by the release workflow after the base application has been defined.
import os, sys, io
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

M=None
GITHUB_UPDATE="https://raw.githubusercontent.com/jaroslavkucacz-code/TURTO-ZakazkyApp/main"

class OfferPriceHistoryDialog(tk.Toplevel):
    def __init__(self,parent,supplier,item_key,title_text=""):
        super().__init__(parent);M.enable_dialog_maximize(self,1050,650);self.title("Historie ceny položky");self.transient(parent);self.grab_set()
        f=M.scrollable_dialog_frame(self,18)
        with M.db() as con:
            rows=con.execute("""SELECT o.offer_date,o.offer_number,o.supplier_name,s.official_name supplier,
                       a.name action_name,i.original_name,i.product_code,i.quantity,i.unit,
                       i.original_unit_price,i.discount_pct,i.unit_price,i.total_price
                FROM supplier_offer_items i
                JOIN supplier_offers o ON o.id=i.offer_id
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN actions a ON a.id=o.action_id
                WHERE i.item_key=? AND (coalesce(o.supplier_name,'')=? OR coalesce(s.official_name,'')=?)
                ORDER BY o.offer_date DESC,o.id DESC,i.id DESC""",(item_key,supplier,supplier)).fetchall()
        ttk.Label(f,text=title_text or item_key,style="Section.TLabel").pack(anchor="w")
        ttk.Label(f,text=f"Dodavatel: {supplier or '—'}   •   item_key: {item_key}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(2,10))
        prices=[float(r["unit_price"] or 0) for r in rows if float(r["unit_price"] or 0)>0]
        latest=prices[0] if prices else 0;previous=prices[1] if len(prices)>1 else 0
        low=min(prices) if prices else 0;high=max(prices) if prices else 0
        change=((latest/previous-1)*100) if latest and previous else None
        cards=ttk.Frame(f,style="Panel.TFrame");cards.pack(fill="x",pady=(0,10))
        for i,(lab,val) in enumerate((("Poslední cena",f"{latest:,.2f}"),("Nejnižší",f"{low:,.2f}"),("Nejvyšší",f"{high:,.2f}"),("Změna",f"{change:+.1f} %" if change is not None else "—"))):
            c=ttk.Frame(cards,style="Card.TFrame",padding=10);c.grid(row=0,column=i,sticky="ew",padx=(0 if i==0 else 4,4))
            ttk.Label(c,text=lab,style="PageSubtitle.TLabel").pack(anchor="w");ttk.Label(c,text=val,style="Section.TLabel").pack(anchor="w");cards.columnconfigure(i,weight=1)
        cols=("Datum","Číslo nabídky","Akce","Původní název","Kód","Množství","MJ","Pův. cena","Sleva","Cena/ks","Celkem")
        tree=ttk.Treeview(f,columns=cols,show="headings",height=16)
        for c,w in zip(cols,(95,130,190,300,100,85,55,105,75,105,115)):tree.heading(c,text=c);tree.column(c,width=w,anchor="w")
        tree.pack(fill="both",expand=True)
        for r in rows:
            tree.insert("","end",values=(M.fmt_date(r["offer_date"]),r["offer_number"] or "",r["action_name"] or "",r["original_name"] or "",r["product_code"] or "",r["quantity"],r["unit"] or "",f"{float(r['original_unit_price'] or 0):,.2f}",f"{float(r['discount_pct'] or 0):.2f} %",f"{float(r['unit_price'] or 0):,.2f}",f"{float(r['total_price'] or 0):,.2f}"))
        ttk.Button(f,text="Zavřít",style="Accent.TButton",command=self.destroy).pack(anchor="e",pady=(10,0))

class OfferActionLinkDialog(tk.Toplevel):
    def __init__(self,parent,current=""):
        super().__init__(parent);M.enable_dialog_maximize(self,760,300);self.title("Přiřadit nabídku k Akci");self.transient(parent);self.grab_set();self.result=None
        f=M.scrollable_dialog_frame(self,18)
        with M.db() as con:actions=[r["name"] for r in con.execute("SELECT DISTINCT trim(name) name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY trim(name) COLLATE CZECH")]
        self.value=tk.StringVar(value=current or "")
        ttk.Label(f,text="Akce / Příležitost",style="Section.TLabel").grid(row=0,column=0,columnspan=2,sticky="w",pady=(0,10))
        M.AutocompleteEntry(f,textvariable=self.value,values=actions).grid(row=1,column=0,columnspan=2,sticky="ew",pady=6)
        ttk.Label(f,text="Začněte psát název; nabídka se připojí pouze k existující Akci.",style="PageSubtitle.TLabel").grid(row=2,column=0,columnspan=2,sticky="w")
        b=ttk.Frame(f);b.grid(row=3,column=0,columnspan=2,sticky="e",pady=(16,0))
        ttk.Button(b,text="Odpojit",command=lambda:self.finish("")).pack(side="left",padx=(0,6));ttk.Button(b,text="Zrušit",command=self.destroy).pack(side="left",padx=(0,6));ttk.Button(b,text="Uložit",style="Accent.TButton",command=self.save).pack(side="left")
        f.columnconfigure(0,weight=1)
    def finish(self,v):self.result=v;self.destroy()
    def save(self):
        v=self.value.get().strip()
        if not v:return self.finish("")
        with M.db() as con:r=con.execute("SELECT name FROM actions WHERE lower(trim(name))=lower(trim(?)) ORDER BY id DESC LIMIT 1",(v,)).fetchone()
        if not r:return messagebox.showwarning("Nabídky","Vyberte existující Akci ze seznamu.",parent=self)
        self.finish(r["name"])

class OfferDetailDialog(tk.Toplevel):
    def __init__(self,parent,oid):
        super().__init__(parent);M.enable_dialog_maximize(self,1260,760);self.title("Cenová nabídka");self.transient(parent);self.grab_set();self.oid=oid;self.parent_app=parent
        self.f=M.scrollable_dialog_frame(self,18);self._build()
    def _load(self):
        with M.db() as con:
            r=con.execute("""SELECT o.*,coalesce(s.official_name,o.supplier_name) supplier,c.official_name customer,a.name action_name FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id WHERE o.id=?""",(self.oid,)).fetchone()
            items=con.execute("SELECT * FROM supplier_offer_items WHERE offer_id=? ORDER BY position,id",(self.oid,)).fetchall()
        return r,items
    def _build(self):
        for w in self.f.winfo_children():w.destroy()
        r,items=self._load();self.offer_row=r
        if not r:return
        hdr=ttk.Frame(self.f,style="Card.TFrame",padding=12);hdr.pack(fill="x",pady=(0,10))
        ttk.Label(hdr,text=f"{r['supplier'] or 'Neurčený dodavatel'}  •  {M.fmt_date(r['offer_date'])}",style="Section.TLabel").pack(anchor="w")
        ttk.Label(hdr,text=f"Akce: {r['action_name'] or '—'}   |   Číslo: {r['offer_number'] or '—'}   |   Celkem: {float(r['total_value'] or 0):,.2f} {r['currency'] or 'CZK'}",style="PageSubtitle.TLabel").pack(anchor="w",pady=(3,0))
        if float(r["discount_pct"] or 0)>0:ttk.Label(hdr,text=f"Souhrnná sleva: {float(r['discount_pct'] or 0):.2f} %   •   Před slevou: {float(r['gross_value'] or 0):,.2f}   •   Po slevě: {float(r['net_value'] or r['total_value'] or 0):,.2f}",style="Section.TLabel").pack(anchor="w",pady=(6,0))
        tools=ttk.Frame(self.f,style="Panel.TFrame",padding=(0,0,0,8));tools.pack(fill="x")
        ttk.Button(tools,text="Historie ceny",command=self.open_history).pack(side="left",padx=(0,5));ttk.Button(tools,text="Obrázek položky",command=self.open_image).pack(side="left",padx=5);ttk.Button(tools,text="Přiřadit k Akci…",command=self.link_action).pack(side="left",padx=5)
        ttk.Label(tools,text="Tip: dvojklik na položku otevře historii ceny.",style="PageSubtitle.TLabel").pack(side="right")
        cols=("Poz.","Kód","Původní název","item_key","Množství","MJ","Pův. cena","Sleva","Cena/ks","Cena celkem")
        self.tree=ttk.Treeview(self.f,columns=cols,show="headings",height=17)
        for c,w in (("Poz.",55),("Kód",110),("Původní název",330),("item_key",240),("Množství",80),("MJ",55),("Pův. cena",100),("Sleva",75),("Cena/ks",100),("Cena celkem",115)):self.tree.heading(c,text=c);self.tree.column(c,width=w,anchor="w")
        self.tree.pack(fill="both",expand=True);self.item_by_iid={}
        try:self.tree.tag_configure("discount",font=("Calibri",10,"bold"))
        except Exception:pass
        for it in items:
            iid=f"i{it['id']}";self.item_by_iid[iid]=dict(it);tags=("discount",) if float(it["discount_pct"] or 0)>0 else ()
            self.tree.insert("","end",iid=iid,tags=tags,values=(it["position"],it["product_code"] or "",it["original_name"],it["item_key"],it["quantity"],it["unit"],f"{float(it['original_unit_price'] or 0):.2f}",f"{float(it['discount_pct'] or 0):.2f} %",f"{float(it['unit_price'] or 0):.2f}",f"{float(it['total_price'] or 0):.2f}"))
        M.bind_row_double_click(self.tree,lambda e:self.open_history())
        b=ttk.Frame(self.f);b.pack(fill="x",pady=(10,0))
        if r["source_pdf"] and Path(r["source_pdf"]).exists():ttk.Button(b,text="Otevřít původní PDF",style="Toolbar.TButton",command=lambda:os.startfile(r["source_pdf"]) if sys.platform.startswith("win") else None).pack(side="left")
        ttk.Button(b,text="Zavřít",style="Accent.TButton",command=self.destroy).pack(side="right")
    def _selected_item(self):
        s=self.tree.selection() if hasattr(self,"tree") else ();return self.item_by_iid.get(s[0]) if s else None
    def open_history(self):
        it=self._selected_item()
        if not it:return messagebox.showinfo("Nabídky","Vyberte položku nabídky.",parent=self)
        d=OfferPriceHistoryDialog(self,self.offer_row["supplier"] or self.offer_row["supplier_name"] or "",it["item_key"] or it["original_name"],it["original_name"] or it["item_key"]);self.wait_window(d)
    def open_image(self):
        it=self._selected_item()
        if not it:return messagebox.showinfo("Nabídky","Vyberte položku nabídky.",parent=self)
        supplier=self.offer_row["supplier"] or self.offer_row["supplier_name"] or ""
        with M.db() as con:
            im=con.execute("SELECT image_blob,image_ext,source_offer_no,source_offer_date FROM offer_product_images WHERE supplier=? AND item_key=?",(supplier,it["item_key"])).fetchone()
            if not im or not im["image_blob"]:
                im2=con.execute("SELECT image_blob,image_ext FROM supplier_offer_items WHERE id=?",(it["id"],)).fetchone()
                if im2 and im2["image_blob"]:im={"image_blob":im2["image_blob"],"image_ext":im2["image_ext"],"source_offer_no":self.offer_row["offer_number"],"source_offer_date":self.offer_row["offer_date"]}
        if not im or not im["image_blob"]:return messagebox.showinfo("Nabídky","K této položce není uložen obrázek.",parent=self)
        try:
            from PIL import Image,ImageTk
            img=Image.open(io.BytesIO(bytes(im["image_blob"])));img.thumbnail((900,620))
            d=tk.Toplevel(self);d.title(f"Obrázek – {it['original_name']}");d.transient(self);d.grab_set();ph=ImageTk.PhotoImage(img);lab=ttk.Label(d,image=ph);lab.image=ph;lab.pack(padx=14,pady=14)
            ttk.Label(d,text=f"Zdroj: nabídka {im['source_offer_no'] or '—'} z {M.fmt_date(im['source_offer_date'])}",style="PageSubtitle.TLabel").pack(pady=(0,8));ttk.Button(d,text="Zavřít",command=d.destroy).pack(pady=(0,14))
        except Exception as e:messagebox.showerror("Nabídky",f"Obrázek se nepodařilo otevřít:\n{e}",parent=self)
    def link_action(self):
        d=OfferActionLinkDialog(self,self.offer_row["action_name"] or "");self.wait_window(d)
        if d.result is None:return
        with M.db() as con:
            aid=None
            if d.result:
                rr=con.execute("SELECT id FROM actions WHERE lower(trim(name))=lower(trim(?)) ORDER BY id DESC LIMIT 1",(d.result,)).fetchone();aid=rr["id"] if rr else None
            con.execute("UPDATE supplier_offers SET action_id=? WHERE id=?",(aid,self.oid))
        try:self.parent_app.refresh_offers()
        except Exception:pass
        self._build()

def build_offers(self):
    p=self.tabs["offers"];self.title_label(p,"Nabídky","+ Importovat PDF",self.import_offer_pdf)
    bar=ttk.Frame(p,style="Panel.TFrame",padding=10);bar.pack(fill="x",pady=(0,6))
    ttk.Button(bar,text="Otevřít detail",style="Toolbar.TButton",command=self.open_offer_detail).pack(side="right",padx=4);ttk.Button(bar,text="Otevřít PDF",style="Toolbar.TButton",command=self.open_offer_pdf).pack(side="right",padx=4);ttk.Button(bar,text="Smazat import",style="Toolbar.TButton",command=self.delete_offer).pack(side="right",padx=4)
    ttk.Label(bar,text="Hledání prochází i názvy, kódy a item_key položek.",style="PageSubtitle.TLabel").pack(side="left")
    with M.db() as con:
        suppliers=[r["official_name"] for r in con.execute("SELECT official_name FROM companies WHERE active=1 ORDER BY official_name COLLATE CZECH")];actions=[r["name"] for r in con.execute("SELECT DISTINCT trim(name) name FROM actions WHERE trim(coalesce(name,''))<>'' ORDER BY trim(name) COLLATE CZECH")]
    self.offer_supplier_filter=tk.StringVar();self.offer_action_filter=tk.StringVar();self.offer_q=tk.StringVar();filters=ttk.Frame(p,style="Panel.TFrame",padding=6);filters.pack(fill="x",pady=(0,5))
    for i,lab in enumerate(("Dodavatel","Akce","Položka / text")):ttk.Label(filters,text=lab,style="FilterLabel.TLabel").grid(row=0,column=i,sticky="w")
    M.AutocompleteEntry(filters,textvariable=self.offer_supplier_filter,values=suppliers).grid(row=1,column=0,sticky="ew",padx=(0,6));M.AutocompleteEntry(filters,textvariable=self.offer_action_filter,values=actions).grid(row=1,column=1,sticky="ew",padx=(0,6));ttk.Entry(filters,textvariable=self.offer_q).grid(row=1,column=2,sticky="ew")
    for i in range(3):filters.columnconfigure(i,weight=1)
    for v in (self.offer_supplier_filter,self.offer_action_filter,self.offer_q):v.trace_add("write",lambda *a:self.refresh_offers())
    self.offer_tree=self.tree(p,("Datum","Dodavatel","Odběratel","Akce","Číslo nabídky","Položek","Hodnota","Měna","Stav"),[100,220,220,260,150,80,120,65,110]);M.bind_row_double_click(self.offer_tree,lambda e:self.open_offer_detail())

def refresh_offers(self):
    if not hasattr(self,"offer_tree"):return
    sf=self.offer_supplier_filter.get().casefold().strip() if hasattr(self,"offer_supplier_filter") else "";af=self.offer_action_filter.get().casefold().strip() if hasattr(self,"offer_action_filter") else "";q=self.offer_q.get().casefold().strip() if hasattr(self,"offer_q") else ""
    for x in self.offer_tree.get_children():self.offer_tree.delete(x)
    with M.db() as con:
        rs=con.execute("""SELECT o.*,coalesce(s.official_name,o.supplier_name) supplier,c.official_name customer,a.name action_name,(SELECT COUNT(*) FROM supplier_offer_items i WHERE i.offer_id=o.id) item_count,(SELECT group_concat(coalesce(i.original_name,'') || ' ' || coalesce(i.item_key,'') || ' ' || coalesce(i.product_code,''),' | ') FROM supplier_offer_items i WHERE i.offer_id=o.id) item_search FROM supplier_offers o LEFT JOIN companies s ON s.id=o.supplier_company_id LEFT JOIN companies c ON c.id=o.customer_company_id LEFT JOIN actions a ON a.id=o.action_id ORDER BY CASE WHEN trim(coalesce(o.offer_date,''))='' THEN 1 ELSE 0 END,o.offer_date DESC,o.id DESC""").fetchall()
    for r in rs:
        hay=f"{r['supplier']} {r['customer']} {r['action_name']} {r['offer_number']} {r['note']} {r['reference']} {r['item_search']}".casefold()
        if sf and sf not in (r["supplier"] or "").casefold():continue
        if af and af not in (r["action_name"] or "").casefold():continue
        if q and q not in hay:continue
        self.offer_tree.insert("","end",iid=f"o{r['id']}",values=(M.fmt_date(r["offer_date"]),r["supplier"] or "",r["customer"] or "",r["action_name"] or "",r["offer_number"] or "",r["item_count"],f"{float(r['total_value'] or 0):,.2f}",r["currency"] or "CZK",r["status"] or ""))

def build_settings(self):
    p=self.tabs["settings"];hdr=ttk.Frame(p,style="App.TFrame");hdr.pack(fill="x",pady=(0,10));ttk.Label(hdr,text="Nastavení",style="Title.TLabel").pack(side="left");ttk.Button(hdr,text="← Zpět na Přehled",command=lambda:self.show_page("dash")).pack(side="right")
    f=ttk.Frame(p,style="Panel.TFrame",padding=18);f.pack(fill="x")
    ttk.Label(f,text="Vzhled",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=0,column=0,sticky="w");self.theme=tk.StringVar(value=M.get_user_setting(self.active_user.get(),"theme","Světlý"));cb=M.safe_combobox(f,textvariable=self.theme,values=["Světlý","Šedomodrý","Teplý","Tmavý"],state="readonly");cb.grid(row=1,column=0,sticky="w",pady=6);cb.bind("<<ComboboxSelected>>",lambda e:self.apply_theme(self.theme.get(),True))
    ttk.Label(f,text="Uživatelé",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=2,column=0,sticky="w",pady=(18,0));ttk.Button(f,text="Spravovat uživatele…",command=self.manage_users).grid(row=3,column=0,sticky="w",pady=6);ttk.Button(f,text="Vytvořit zástupce na ploše",command=self.create_desktop_shortcut).grid(row=3,column=1,sticky="w",padx=8,pady=6)
    ttk.Label(f,text="Číselníky",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=4,column=0,sticky="w",pady=(18,0));ttk.Button(f,text="Spravovat číselníky…",command=self.manage_code_lists).grid(row=5,column=0,sticky="w",pady=6);ttk.Label(f,text="Funkce osob · Poptávané zboží · Co se řeší · Obchodníci",style="Panel.TLabel").grid(row=5,column=1,columnspan=2,sticky="w",padx=8)
    ttk.Label(f,text="Data",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=6,column=0,sticky="w",pady=(18,0));ttk.Button(f,text="Vytvořit zálohu",command=self.manual_backup).grid(row=7,column=0,sticky="w",pady=6);ttk.Button(f,text="Zkontrolovat data",command=self.database_audit).grid(row=7,column=1,sticky="w",padx=8,pady=6);ttk.Label(f,text=f"Databáze: {M.DB}",style="Panel.TLabel").grid(row=8,column=0,columnspan=3,sticky="w")
    ttk.Label(f,text="Import / export",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=9,column=0,sticky="w",pady=(18,0));ttk.Button(f,text="Export kompletní databáze…",command=self.export_complete_data).grid(row=10,column=0,sticky="w",pady=6);ttk.Button(f,text="Import kompletní databáze…",command=self.import_complete_data).grid(row=10,column=1,sticky="w",padx=8,pady=6);ttk.Button(f,text="Výběrový export…",command=self.export_selected_dialog).grid(row=10,column=2,sticky="w",padx=8,pady=6)
    ttk.Label(f,text="Aktualizace aplikace",style="Panel.TLabel",font=("Calibri",12,"bold")).grid(row=11,column=0,sticky="w",pady=(20,0));M.set_setting("update_source",GITHUB_UPDATE);self.update_source=tk.StringVar(value=GITHUB_UPDATE)
    ttk.Label(f,text="GitHub • TURTO-ZakazkyApp • stabilní kanál",style="Panel.TLabel").grid(row=12,column=0,columnspan=2,sticky="w",pady=6);ttk.Button(f,text="Zkontrolovat aktualizace",style="Accent.TButton",command=self.check_for_updates).grid(row=13,column=0,sticky="w",pady=6);ttk.Label(f,text="Aktualizace se stahují automaticky z GitHubu. Databáze ani firemní data se na GitHub neodesílají.",style="Panel.TLabel").grid(row=13,column=1,columnspan=2,sticky="w",padx=8)

def apply(module):
    global M;M=module
    module.OfferDetailDialog=OfferDetailDialog
    module.OfferPriceHistoryDialog=OfferPriceHistoryDialog
    module.OfferActionLinkDialog=OfferActionLinkDialog
    module.App.build_offers=build_offers
    module.App.refresh_offers=refresh_offers
    module.App.build_settings=build_settings
    orig_init=module.App.__init__
    def init(self,*a,**kw):
        try:module.set_setting("update_source",GITHUB_UPDATE)
        except Exception:pass
        return orig_init(self,*a,**kw)
    module.App.__init__=init
