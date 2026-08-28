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
            rows=con.execute("""SELECT o.offer_date,o.offer_number,o.supplier_name,
                       coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),'') supplier,
                       CASE
                         WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                         WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                         ELSE ''
                       END action_name,
                       i.original_name,i.product_code,i.quantity,i.unit,
                       i.original_unit_price,i.discount_pct,i.unit_price,i.total_price
                FROM supplier_offer_items i
                JOIN supplier_offers o ON o.id=i.offer_id
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN projects pd ON pd.id=o.project_id
                LEFT JOIN requests rq ON rq.id=o.request_id
                LEFT JOIN actions ra ON ra.id=rq.action_id
                LEFT JOIN projects pr ON pr.id=ra.project_id
                WHERE i.item_key=? AND (
                    coalesce(o.supplier_name,'')=?
                    OR coalesce(s.official_name,'')=?
                    OR coalesce(s.short_name,'')=?
                )
                ORDER BY o.offer_date DESC,o.id DESC,i.id DESC""",(item_key,supplier,supplier,supplier)).fetchall()
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
            r=con.execute("""SELECT o.*,
                       coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),'') supplier,
                       c.official_name customer,
                       CASE
                         WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                         WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                         ELSE ''
                       END action_name
                FROM supplier_offers o
                LEFT JOIN companies s ON s.id=o.supplier_company_id
                LEFT JOIN companies c ON c.id=o.customer_company_id
                LEFT JOIN projects pd ON pd.id=o.project_id
                LEFT JOIN requests rq ON rq.id=o.request_id
                LEFT JOIN actions ra ON ra.id=rq.action_id
                LEFT JOIN projects pr ON pr.id=ra.project_id
                WHERE o.id=?""",(self.oid,)).fetchone()
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


def _offer_filter_values():
    """Read only values that are relevant to the offer view."""
    suppliers=[]
    actions=[]
    try:
        with M.db() as con:
            suppliers=[
                r["supplier"] for r in con.execute(
                    """SELECT DISTINCT
                           coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),'') supplier
                       FROM supplier_offers o
                       LEFT JOIN companies s ON s.id=o.supplier_company_id
                       WHERE trim(coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),''))<>''
                       ORDER BY supplier COLLATE CZECH"""
                ).fetchall()
            ]
            actions=[
                r["name"] for r in con.execute(
                    """SELECT DISTINCT name FROM (
                           SELECT CASE
                             WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                             WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                             ELSE ''
                           END name
                           FROM supplier_offers o
                           LEFT JOIN projects pd ON pd.id=o.project_id
                           LEFT JOIN requests rq ON rq.id=o.request_id
                           LEFT JOIN actions ra ON ra.id=rq.action_id
                           LEFT JOIN projects pr ON pr.id=ra.project_id
                       )
                       WHERE trim(coalesce(name,''))<>''
                       ORDER BY name COLLATE CZECH"""
                ).fetchall()
            ]
    except Exception:
        pass
    return suppliers,actions


def clear_offer_filters(self):
    for name in ("offer_q","offer_supplier_filter","offer_action_filter"):
        try:getattr(self,name).set("")
        except Exception:pass
    try:self.refresh_offers()
    except Exception:pass


def update_offer_selection(self,*_):
    tree=getattr(self,"offer_tree",None)
    label=getattr(self,"offer_selection_label",None)
    if tree is None or label is None:return
    try:
        count=len(tree.selection())
        label.configure(text=f"Vybráno: {count}" if count else "Nevybrána žádná nabídka")
    except Exception:
        pass


def build_offers(self):
    p=self.tabs["offers"]
    # This is the canonical composition of the Offers page. Older feature
    # modules still provide commands, but they no longer own page layout.
    self._offer_drop_area_ready=True
    self.title_label(p,"Nabídky")

    primary=ttk.Frame(p,style="Panel.TFrame",padding=(10,8))
    primary.pack(fill="x",pady=(0,6))
    if callable(getattr(self,"import_offer_sources",None)):
        ttk.Button(
            primary,text="📥 Zpracovat nabídku",style="Accent.TButton",
            command=self.import_offer_sources,
        ).pack(side="left")
    if callable(getattr(self,"import_selected_outlook_offer",None)):
        ttk.Button(
            primary,text="✉ Načíst z Outlooku",style="Toolbar.TButton",
            command=self.import_selected_outlook_offer,
        ).pack(side="left",padx=(6,0))
    if callable(getattr(self,"open_product_prices",None)):
        ttk.Button(
            primary,text="💰 Produkty / ceny",style="Toolbar.TButton",
            command=self.open_product_prices,
        ).pack(side="left",padx=(6,0))
    ttk.Label(
        primary,
        text="PDF / MSG lze také přetáhnout do okna programu; dodavatel se rozpozná automaticky.",
        style="PageSubtitle.TLabel",
    ).pack(side="left",padx=(12,0))

    suppliers,actions=_offer_filter_values()
    self.offer_q=tk.StringVar()
    self.offer_supplier_filter=tk.StringVar()
    self.offer_action_filter=tk.StringVar()

    filters=ttk.Frame(p,style="Panel.TFrame",padding=(10,7))
    filters.pack(fill="x",pady=(0,6))
    ttk.Label(filters,text="Hledat",style="FilterLabel.TLabel").grid(row=0,column=0,sticky="w")
    ttk.Label(filters,text="Dodavatel",style="FilterLabel.TLabel").grid(row=0,column=1,sticky="w")
    ttk.Label(filters,text="Akce",style="FilterLabel.TLabel").grid(row=0,column=2,sticky="w")
    ttk.Entry(filters,textvariable=self.offer_q).grid(row=1,column=0,sticky="ew",padx=(0,6))
    self.offer_supplier_box=M.AutocompleteEntry(filters,textvariable=self.offer_supplier_filter,values=suppliers)
    self.offer_supplier_box.grid(row=1,column=1,sticky="ew",padx=(0,6))
    self.offer_action_box=M.AutocompleteEntry(filters,textvariable=self.offer_action_filter,values=actions)
    self.offer_action_box.grid(row=1,column=2,sticky="ew",padx=(0,6))
    ttk.Button(
        filters,text="Vymazat filtry",style="Toolbar.TButton",
        command=lambda:clear_offer_filters(self),
    ).grid(row=1,column=3,sticky="e")
    filters.columnconfigure(0,weight=2)
    filters.columnconfigure(1,weight=1)
    filters.columnconfigure(2,weight=2)
    for variable in (self.offer_q,self.offer_supplier_filter,self.offer_action_filter):
        variable.trace_add("write",lambda *_:self.refresh_offers())

    columns=("Datum","Dodavatel","Číslo nabídky","Přiřazení","Akce","Reference","Položek","Hodnota","Měna","Stav")
    widths=[100,185,140,105,245,215,70,115,60,95]
    self.offer_tree=self.tree(p,columns,widths)
    try:self.offer_tree.configure(selectmode="extended")
    except Exception:pass
    M.bind_row_double_click(self.offer_tree,lambda e:self.open_offer_detail())
    self.offer_tree.bind("<<TreeviewSelect>>",lambda e:update_offer_selection(self),add="+")

    actions_bar=ttk.Frame(p,style="Panel.TFrame",padding=(10,7))
    actions_bar.pack(fill="x",pady=(6,0))
    self.offer_selection_label=ttk.Label(
        actions_bar,text="Nevybrána žádná nabídka",style="PageSubtitle.TLabel",
    )
    self.offer_selection_label.pack(side="left")
    ttk.Button(
        actions_bar,text="Smazat z databáze",style="Toolbar.TButton",
        command=self.delete_offer,
    ).pack(side="right")
    if callable(getattr(self,"export_selected_offer_excel",None)):
        ttk.Button(
            actions_bar,text="Extrakce dat",style="Toolbar.TButton",
            command=self.export_selected_offer_excel,
        ).pack(side="right",padx=6)
    ttk.Button(
        actions_bar,text="Otevřít detail",style="Accent.TButton",
        command=self.open_offer_detail,
    ).pack(side="right")

    self.refresh_offers()
    update_offer_selection(self)


def refresh_offers(self):
    if not hasattr(self,"offer_tree"):return
    sf=self.offer_supplier_filter.get().casefold().strip() if hasattr(self,"offer_supplier_filter") else ""
    af=self.offer_action_filter.get().casefold().strip() if hasattr(self,"offer_action_filter") else ""
    q=self.offer_q.get().casefold().strip() if hasattr(self,"offer_q") else ""
    for x in self.offer_tree.get_children():self.offer_tree.delete(x)

    with M.db() as con:
        # Only current canonical links count as assignments. Historical action_id
        # values created by the old reference auto-match are deliberately ignored.
        rs=con.execute("""SELECT o.*,
                coalesce(nullif(trim(s.official_name),''),nullif(trim(s.short_name),''),nullif(trim(o.supplier_name),''),'') supplier,
                CASE
                  WHEN o.request_id IS NOT NULL THEN coalesce(pr.name,pd.name,'')
                  WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN coalesce(pd.name,'')
                  ELSE ''
                END action_name,
                CASE
                  WHEN o.request_id IS NOT NULL THEN '✓ Poptávka'
                  WHEN o.project_id IS NOT NULL AND o.action_id IS NULL THEN '✓ Akce'
                  ELSE '—'
                END link_state,
                (SELECT COUNT(*) FROM supplier_offer_items i WHERE i.offer_id=o.id) item_count,
                (SELECT group_concat(coalesce(i.original_name,'') || ' ' ||
                                     coalesce(i.item_key,'') || ' ' ||
                                     coalesce(i.product_code,''),' | ')
                   FROM supplier_offer_items i WHERE i.offer_id=o.id) item_search
            FROM supplier_offers o
            LEFT JOIN companies s ON s.id=o.supplier_company_id
            LEFT JOIN projects pd ON pd.id=o.project_id
            LEFT JOIN requests rq ON rq.id=o.request_id
            LEFT JOIN actions ra ON ra.id=rq.action_id
            LEFT JOIN projects pr ON pr.id=ra.project_id
            ORDER BY CASE WHEN trim(coalesce(o.offer_date,''))='' THEN 1 ELSE 0 END,
                     o.offer_date DESC,o.id DESC""").fetchall()

    # Filters are live: after the first offer from a new supplier/action arrives,
    # the already-open Offers page immediately learns the new values.
    try:
        supplier_values=sorted(
            {str(r["supplier"] or "").strip() for r in rs if str(r["supplier"] or "").strip()},
            key=M.czech_sort_key,
        )
        action_values=sorted(
            {str(r["action_name"] or "").strip() for r in rs if str(r["action_name"] or "").strip()},
            key=M.czech_sort_key,
        )
        supplier_box=getattr(self,"offer_supplier_box",None)
        action_box=getattr(self,"offer_action_box",None)
        if supplier_box is not None and callable(getattr(supplier_box,"set_values",None)):
            supplier_box.set_values(supplier_values)
        if action_box is not None and callable(getattr(action_box,"set_values",None)):
            action_box.set_values(action_values)
    except Exception:
        pass

    for r in rs:
        supplier=r["supplier"] or ""
        action=r["action_name"] or ""
        link_state=r["link_state"] or "—"
        reference=r["reference"] or ""
        hay=f"{supplier} {action} {link_state} {r['offer_number']} {r['note']} {reference} {r['item_search']}".casefold()
        if sf and sf not in supplier.casefold():continue
        if af and af not in action.casefold():continue
        if q and q not in hay:continue
        self.offer_tree.insert(
            "","end",iid=f"o{r['id']}",
            values=(
                M.fmt_date(r["offer_date"]),
                supplier,
                r["offer_number"] or "",
                link_state,
                action,
                reference,
                r["item_count"],
                f"{float(r['total_value'] or 0):,.2f}",
                r["currency"] or "CZK",
                r["status"] or "",
            ),
        )
    update_offer_selection(self)
    try:
        layout=getattr(M,"schedule_final_tree_layout",None)
        if callable(layout):layout(self)
    except Exception:
        pass


def install_offer_ui(module):
    """Reassert one canonical Offers UI after legacy feature modules register commands."""
    module.App.build_offers=build_offers
    module.App.refresh_offers=refresh_offers
    module.App.clear_offer_filters=clear_offer_filters
    module.App._update_offer_selection=update_offer_selection


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
    install_offer_ui(module)
    module.App.build_settings=build_settings
    orig_init=module.App.__init__
    def init(self,*a,**kw):
        try:module.set_setting("update_source",GITHUB_UPDATE)
        except Exception:pass
        return orig_init(self,*a,**kw)
    module.App.__init__=init